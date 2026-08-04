"""把 PRD 的验收标准 AC1-AC8 变成可执行门禁。

用法:
    # 先启动后端
    uvicorn main:app --port 8000
    # 再运行
    python scripts/run_acceptance.py
    python scripts/run_acceptance.py --case tc_01_rett   # 只跑单个用例

实现要点:
  * 读 data/test_cases/tc_*.json,字段逐字对应 schema.md §3 / I1-I9
  * 含 setup.mode 的用例(missing_api_key / minimax_timeout / hpo_no_match)由
    脚本起一个临时 uvicorn 子进程,以 ASD_MOCK 环境变量注入 mock 行为;
    避免依赖真实失效或线上偶发不命中
  * 退出码:0 全过,1 任一失败
"""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BACKEND_URL, TEST_CASE_DIR, official_disclaimer  # noqa: E402

CASE_DIR = TEST_CASE_DIR
# M3 是推理模型，带 RAG 切片的长提示词要先跑一段思维链，单次往返常在 30-90 秒。
# 这是客户端等待时长，不是对响应速度的断言。
TIMEOUT = 180

REQUIRED_FIELDS = [
    "status", "hpo_terms", "comparisons", "vus_reassurance",
    "next_steps", "disclaimer", "mcp_translation", "retrieved_chunks",
]

# 跟 40-compliance.mdc 同步的禁词
_BANNED_BASE = ["确诊", "患有", "即为", "需服用", "建议用药"]
_BANNED_CONF = ["概率", "可能性", "几率", "概率", "患病概率", "确诊概率"]

# 桶 C disclaimer 原文
DISCLAIMER_BUCKET_C: str = official_disclaimer().strip()


# ---------- setup 模式子进程管理 ----------


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def mock_backend(mock_mode: str):
    """起一个临时 uvicorn 子进程,通过 /tmp/asd_mock 文件通道注入 mock 行为。"""
    port = _pick_free_port()
    mock_file = Path("/tmp/asd_mock")
    mock_file.write_text(mock_mode, encoding="utf-8")
    log_path = Path("/tmp") / f"uvicorn-acceptance-{mock_mode}.log"
    log_f = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    try:
        # 等服务起来
        # lifespan 要加载 ChromaDB 的 SentenceTransformer，冷启动可达一分钟
        for _ in range(240):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError(f"mock 后端未在端口 {port} 起来: {log_path}")
        yield f"http://127.0.0.1:{port}/api/screen"
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        log_f.close()
        try:
            mock_file.unlink()
        except FileNotFoundError:
            pass


# ---------- 断言 ----------


def check_success(case, body, failures):
    exp = case["expect"]

    # AC1 字段完整性
    for f in REQUIRED_FIELDS:
        if f not in body:
            failures.append(f"AC1 响应缺失字段 `{f}`")
    if any(f"AC1" in x for x in failures):
        return

    # AC2 HPO 标准化
    terms = body["hpo_terms"]
    if len(terms) < exp.get("min_hpo_terms", 1):
        failures.append(
            f"AC2 hpo_terms 数量 {len(terms)} 少于要求的 {exp.get('min_hpo_terms', 1)}"
        )
    for t in terms:
        if not str(t.get("hpo_id", "")).startswith("HP:"):
            failures.append(f"AC2 hpo_id 格式非法：{t.get('hpo_id')!r}")

    # AC4 disclaimer 逐字 + 必含科室
    if exp.get("require_disclaimer"):
        if body["disclaimer"].strip() != DISCLAIMER_BUCKET_C:
            failures.append("AC4 disclaimer 与桶 C 原文不一致（必须逐字相同）")
    steps = " ".join(body.get("next_steps", []))
    for dept in exp.get("require_next_steps_departments", []):
        if dept not in steps:
            failures.append(f"AC4 next_steps 缺少就诊科室「{dept}」")

    # AC5 禁词扫描
    scope = " ".join(
        [c.get("explanation", "") for c in body.get("comparisons", [])]
        + [body.get("vus_reassurance", "")]
        + body.get("next_steps", [])
    )
    for w in exp.get("banned_words", []):
        if w in scope:
            failures.append(f"AC5 输出出现禁用词「{w}」")

    # AC3 比对结论可回溯
    conds = " ".join(
        f"{c.get('condition', '')} {c.get('gene', '')}"
        for c in body.get("comparisons", [])
    )
    wanted = exp.get("expect_conditions_any")
    if wanted and not any(w in conds for w in wanted):
        failures.append(f"AC3 comparisons 未命中期望病种之一 {wanted}，实际为「{conds.strip()}」")
    for forbidden in exp.get("forbid_conditions_any", []):
        if forbidden in conds:
            failures.append(f"AC3 comparisons 出现不应牵强关联的病种「{forbidden}」")

    # 检索覆盖
    buckets = {c.get("bucket") for c in body.get("retrieved_chunks", [])}
    for b in exp.get("expect_buckets", []):
        if b not in buckets:
            failures.append(f"retrieved_chunks 未覆盖数据桶 {b}（实际 {sorted(buckets)}）")

    # schema I8：comparisons==[] 时 vus_reassurance 必含「未匹配到」
    if not body.get("comparisons"):
        vus = body.get("vus_reassurance", "")
        if "未匹配到" not in vus:
            failures.append(
                "schema I8 comparisons=[] 时 vus_reassurance 须含「未匹配到」"
            )

    # schema I9：confidence_level 字段若存在必须是 0-100 整数;不得为 null
    if "confidence_level" in body:
        cl = body["confidence_level"]
        if cl is None:
            failures.append("schema I9 confidence_level 不得为 null（应字段缺失或为整数）")
        elif not isinstance(cl, int) or not 0 <= cl <= 100:
            failures.append(f"schema I9 confidence_level 非法：{cl!r}")
        # 措辞扫描：v.us_reassurance + next_steps + confidence_level 任意文案
        conf_text = str(cl) if not isinstance(cl, dict) else json.dumps(cl, ensure_ascii=False)
        conf_scope = " ".join(
            [body.get("vus_reassurance", "")]
            + body.get("next_steps", [])
            + [conf_text]
        )
        for w in _BANNED_CONF:
            if w in conf_scope:
                failures.append(f"schema I9 措辞含禁用词「{w}」")


def check_error(case, body, failures):
    exp = case["expect"]
    if body.get("status") != "error":
        failures.append(f"AC6 错误响应 status 应为 error，实际 {body.get('status')!r}")
    if exp.get("error_code") and body.get("error_code") != exp["error_code"]:
        failures.append(
            f"AC6 error_code 应为 {exp['error_code']}，实际 {body.get('error_code')!r}"
        )
    if not body.get("error_message"):
        failures.append("AC6 error_message 为空，前端无法展示错误态")


def run_case(path: Path, default_url: str):
    case = json.loads(path.read_text(encoding="utf-8"))
    exp = case["expect"]
    failures = []
    setup = case.get("setup", {})
    mode = setup.get("mode") if isinstance(setup, dict) else None

    # setup 模式:起临时子进程
    if mode:
        try:
            with mock_backend(mode) as url:
                resp = requests.post(url, json=case["input"], timeout=TIMEOUT)
        except Exception as e:
            return case, [f"setup 模式 {mode} 启动失败: {e}"]
    else:
        try:
            resp = requests.post(default_url, json=case["input"], timeout=TIMEOUT)
        except requests.exceptions.ConnectionError:
            return case, ["无法连接后端，请先运行 uvicorn main:app --port 8000"]
        except requests.exceptions.Timeout:
            return case, [f"请求超时（>{TIMEOUT}s）"]

    want_status = exp.get("http_status", 200)
    if resp.status_code != want_status:
        failures.append(f"HTTP 状态码应为 {want_status}，实际 {resp.status_code}")

    try:
        body = resp.json()
    except ValueError:
        failures.append("响应体不是合法 JSON")
        return case, failures

    if want_status == 200:
        check_success(case, body, failures)
    else:
        check_error(case, body, failures)

    return case, failures


# ---------- 主入口 ----------


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="只运行指定用例 id")
    args = parser.parse_args()

    default_url = f"{BACKEND_URL}/api/screen"

    paths = sorted(CASE_DIR.glob("tc_*.json"))
    if args.case:
        paths = [p for p in paths if p.stem == args.case]
        if not paths:
            print(f"未找到用例 {args.case}", file=sys.stderr)
            return 1

    print(f"目标后端(默认): {default_url}")
    print(f"用例数量: {len(paths)}\n")

    passed = 0
    for path in paths:
        case, failures = run_case(path, default_url)
        if failures:
            print(f"[失败] {case['id']} — {case['title']}", file=sys.stderr)
            for f in failures:
                print(f"        {f}", file=sys.stderr)
        else:
            passed += 1
            print(f"[通过] {case['id']} — {case['title']}")

    total = len(paths)
    print(f"\n通过 {passed}/{total}")
    if passed != total:
        print("验收未通过，PRD 的 AC1-AC8 存在未满足项。", file=sys.stderr)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
