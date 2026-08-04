"""澄清端点 POST /api/clarify 的断言脚本。

独立于 run_acceptance.py：后者是 PRD AC1-AC6 的门禁，只打 /api/screen，
两者语义不同，不合并以免污染既有门禁。

用法:
    # 先启动后端
    uvicorn main:app --port 8000
    # 再运行
    python scripts/check_clarify.py
    python scripts/check_clarify.py --url http://127.0.0.1:8010/api/clarify

退出码: 0 全过, 1 任一失败
"""
import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BACKEND_URL, KNOWLEDGE_DIR, official_disclaimer  # noqa: E402

TIMEOUT = 180

REQUIRED_FIELDS = ["status", "reply", "options", "mcp_translation", "disclaimer"]
OPTION_FIELDS = ["hpo_id", "name", "plain", "matched_text"]

MAX_OPTIONS = 5

# 与 40-compliance.mdc 同步的禁词
BANNED = ["确诊", "患有", "即为", "需服用", "建议用药"]

DISCLAIMER = official_disclaimer().strip()

# 正向用例：家长一句话说了多件事，期望候选覆盖面不塌缩到单一语义簇
CASES = [
    {
        "id": "utterance_regression",
        "title": "发育倒退 + 搓手 + 步态不稳",
        "payload": {
            "utterance": (
                "孩子快3岁了，本来会喊爸爸妈妈，现在都不说了，"
                "整天在胸前搓手，走路也晃晃悠悠的"
            ),
            "picked": [],
        },
        "min_options": 3,
    },
    {
        "id": "utterance_social",
        "title": "回避目光 + 拍手 + 坐不住",
        "payload": {
            "utterance": "孩子六岁了，不肯看人的眼睛，一紧张就使劲拍手，上课一分钟都坐不住",
            "picked": [],
        },
        "min_options": 3,
    },
]


def load_condition_words() -> set:
    """桶 A 的病名与基因名。聊天候选只该承载表型，出现病名即视为滑向诊断。"""
    path = KNOWLEDGE_DIR / "bucket_a_differential.json"
    words = set()
    for entry in json.loads(path.read_text(encoding="utf-8")):
        for run in (entry.get("condition", ""), entry.get("gene", "")):
            for part in run.replace("/", " ").split():
                token = part.strip("()（），,。").strip()
                # 只保留判别力足够的专名，避免「综合征」这类通用词误伤
                if len(token) >= 3 and token not in {"综合征", "相关疾病"}:
                    words.add(token.lower())
    return words


CONDITION_WORDS = load_condition_words()


def check_case(url: str, case: dict, failures: list) -> None:
    tag = f"{case['id']} — {case['title']}"
    try:
        r = requests.post(url, json=case["payload"], timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        failures.append((tag, f"请求失败：{type(e).__name__}"))
        return

    if r.status_code != 200:
        failures.append((tag, f"期望 HTTP 200，实际 {r.status_code}：{r.text[:200]}"))
        return

    try:
        body = r.json()
    except ValueError:
        failures.append((tag, "响应不是合法 JSON"))
        return

    for f in REQUIRED_FIELDS:
        if f not in body:
            failures.append((tag, f"缺字段 {f}"))
    if body.get("status") != "success":
        failures.append((tag, f"status 应为 success，实际 {body.get('status')}"))

    # disclaimer 必须是桶 C 逐字原文，不经 LLM
    if (body.get("disclaimer") or "").strip() != DISCLAIMER:
        failures.append((tag, "disclaimer 与桶 C 原文不一致"))

    options = body.get("options") or []
    if not options:
        failures.append((tag, "options 为空"))
        return
    if len(options) > MAX_OPTIONS:
        failures.append((tag, f"options 有 {len(options)} 条，超过上限 {MAX_OPTIONS}"))
    if len(options) < case["min_options"]:
        failures.append(
            (tag, f"options 仅 {len(options)} 条，少于期望的 {case['min_options']} 条")
        )

    seen = set()
    for o in options:
        for f in OPTION_FIELDS:
            if f not in o:
                failures.append((tag, f"option 缺字段 {f}：{o}"))
        hpo_id = o.get("hpo_id", "")
        if not hpo_id.startswith("HP:"):
            failures.append((tag, f"hpo_id 不以 HP: 开头：{hpo_id}"))
        if hpo_id in seen:
            failures.append((tag, f"hpo_id 重复：{hpo_id}"))
        seen.add(hpo_id)
        if not (o.get("name") or "").strip():
            failures.append((tag, f"{hpo_id} 的 name 为空"))
        if not (o.get("plain") or "").strip():
            failures.append((tag, f"{hpo_id} 的 plain 为空"))

    # 合规：禁词与病名在 reply / options 中必须零命中
    scan_parts = [body.get("reply", "")]
    for o in options:
        scan_parts.append(o.get("name", ""))
        scan_parts.append(o.get("plain", ""))
    scan = " ".join(scan_parts)
    hit = [w for w in BANNED if w in scan]
    if hit:
        failures.append((tag, f"命中禁用词：{hit}"))
    low = scan.lower()
    disease_hit = [w for w in CONDITION_WORDS if w in low]
    if disease_hit:
        failures.append((tag, f"候选中出现病名/基因名：{disease_hit}"))


def check_picked_dedup(url: str, failures: list) -> None:
    """picked 回传的 hpo_id 不得再次出现，否则多轮追问会一直推同一条。"""
    tag = "picked_dedup — 已勾选项去重"
    first = {"utterance": "孩子整天在胸前搓手，走路晃", "picked": []}
    try:
        r1 = requests.post(url, json=first, timeout=TIMEOUT)
        if r1.status_code != 200:
            failures.append((tag, f"首轮期望 200，实际 {r1.status_code}"))
            return
        picked = [o["hpo_id"] for o in r1.json().get("options", [])][:2]
        if not picked:
            failures.append((tag, "首轮没有候选，无法验证去重"))
            return
        r2 = requests.post(
            url, json={"utterance": first["utterance"], "picked": picked},
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        failures.append((tag, f"请求失败：{type(e).__name__}"))
        return
    if r2.status_code != 200:
        failures.append((tag, f"次轮期望 200，实际 {r2.status_code}"))
        return
    again = [o["hpo_id"] for o in r2.json().get("options", [])]
    leaked = [h for h in picked if h in again]
    if leaked:
        failures.append((tag, f"已勾选项再次出现：{leaked}"))


def check_invalid_input(url: str, failures: list) -> None:
    tag = "invalid_input — 空白 utterance 应被 422 拦截"
    try:
        r = requests.post(url, json={"utterance": "   ", "picked": []}, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        failures.append((tag, f"请求失败：{type(e).__name__}"))
        return
    if r.status_code != 422:
        failures.append((tag, f"期望 HTTP 422，实际 {r.status_code}"))
        return
    body = r.json()
    if body.get("error_code") != "INVALID_INPUT":
        failures.append((tag, f"error_code 应为 INVALID_INPUT，实际 {body.get('error_code')}"))
    if "disclaimer" in body:
        failures.append((tag, "ErrorResponse 不应含 disclaimer"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=f"{BACKEND_URL}/api/clarify")
    args = parser.parse_args()

    print(f"目标端点: {args.url}")
    failures: list = []

    for case in CASES:
        check_case(args.url, case, failures)
    check_picked_dedup(args.url, failures)
    check_invalid_input(args.url, failures)

    total = len(CASES) + 2
    if failures:
        print(f"\n失败 {len(failures)} 项：")
        for tag, reason in failures:
            print(f"[失败] {tag}\n        {reason}")
        return 1
    print(f"\n全部通过（{total} 项检查）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
