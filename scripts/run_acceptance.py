"""把 PRD 的验收标准 AC1-AC8 变成可执行门禁。

用法：
    # 先启动后端
    uvicorn main:app --reload --port 8000
    # 再运行
    python scripts/run_acceptance.py
    python scripts/run_acceptance.py --case tc_01_rett   # 只跑单个用例

全部通过退出码 0，任一失败退出码 1。
"""

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BACKEND_URL, TEST_CASE_DIR, official_disclaimer  # noqa: E402

CASE_DIR = TEST_CASE_DIR
ENDPOINT = f"{BACKEND_URL}/api/screen"
TIMEOUT = 120

REQUIRED_FIELDS = [
    "status", "hpo_terms", "comparisons", "vus_reassurance",
    "next_steps", "disclaimer", "mcp_translation", "retrieved_chunks",
]


def check_success(case, body, failures):
    exp = case["expect"]

    # AC1 字段完整性
    for f in REQUIRED_FIELDS:
        if f not in body:
            failures.append(f"AC1 响应缺失字段 `{f}`")
    if failures:
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

    # AC4 免责声明逐字一致 + 就诊科室
    if exp.get("require_disclaimer"):
        if body["disclaimer"].strip() != official_disclaimer().strip():
            failures.append("AC4 disclaimer 与桶 C 原文不一致（必须逐字相同）")
    steps = " ".join(body.get("next_steps", []))
    for dept in exp.get("require_next_steps_departments", []):
        if dept not in steps:
            failures.append(f"AC4 next_steps 缺少就诊科室「{dept}」")

    # AC5 禁用词扫描。范围不含 disclaimer 与 retrieved_chunks，
    # 因为前者是法定免责原文、后者是知识库原文，本就允许出现「确诊」等词。
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


def run_case(path: Path):
    case = json.loads(path.read_text(encoding="utf-8"))
    exp = case["expect"]
    failures = []

    try:
        resp = requests.post(ENDPOINT, json=case["input"], timeout=TIMEOUT)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="只运行指定用例 id")
    args = parser.parse_args()

    paths = sorted(CASE_DIR.glob("tc_*.json"))
    if args.case:
        paths = [p for p in paths if p.stem == args.case]
        if not paths:
            print(f"未找到用例 {args.case}")
            return 1

    print(f"目标后端：{ENDPOINT}")
    print(f"用例数量：{len(paths)}\n")

    passed = 0
    for path in paths:
        case, failures = run_case(path)
        if failures:
            print(f"[失败] {case['id']} — {case['title']}")
            for f in failures:
                print(f"        {f}")
        else:
            passed += 1
            print(f"[通过] {case['id']} — {case['title']}")

    total = len(paths)
    print(f"\n通过 {passed}/{total}")
    if passed != total:
        print("验收未通过，PRD 的 AC1-AC8 存在未满足项。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
