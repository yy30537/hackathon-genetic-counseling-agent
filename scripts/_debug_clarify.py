"""调试脚本：直接调用 clarify 链路关键函数，把每一步的中间结果写入 /tmp/debug-1fb3a2.log。"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402

LOG_PATH = Path("/tmp/debug-1fb3a2.log")


def emit(hypothesis: str, location: str, message: str, data: dict) -> None:
    payload = {
        "id": f"log_{__import__('time').time_ns()}",
        "timestamp": __import__('time').time_ns() // 1_000_000,
        "location": location,
        "message": message,
        "hypothesisId": hypothesis,
        "data": data,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def main_async() -> None:
    utterance = "孩子老是打人，比较暴躁，做不定"
    emit("H1", "debug-clarify.py:main", "输入 utterance", {"utterance": utterance})

    # H1: 离线规则扫描
    seeds = main._clarify_offline_seeds(utterance)
    emit("H1", "debug-clarify.py:main", "离线规则种子", {"count": len(seeds), "seeds": seeds})

    # H2/H3: M3 抽词
    keywords, kw_logs = await main._clarify_keywords(utterance)
    emit("H2", "debug-clarify.py:main", "M3 抽词结果", {"count": len(keywords), "keywords": keywords})
    for ln in kw_logs:
        emit("H2", "debug-clarify.py:main", "抽词日志", {"line": ln})

    # H3: 用 keywords 调 MCP
    seen: set = set()
    log_lines: list = []
    groups, missed = await main._mcp_search_keyword_groups(keywords, utterance, seen, log_lines)
    emit("H3", "debug-clarify.py:main", "MCP 检索结果", {"groups": len(groups), "missed": len(missed), "items": [g[:3] for g in groups]})
    for ln in log_lines:
        emit("H3", "debug-clarify.py:main", "检索日志", {"line": ln})

    # 完整链路
    pool, logs = await main._clarify_collect(utterance, [])
    emit("H4", "debug-clarify.py:main", "完整链路候选池", {"count": len(pool), "items": pool})
    for ln in logs:
        emit("H4", "debug-clarify.py:main", "链路日志", {"line": ln})


if __name__ == "__main__":
    asyncio.run(main_async())
