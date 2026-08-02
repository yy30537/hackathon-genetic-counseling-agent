"""把 data/knowledge/raw/*.pdf 转成灌库脚本能读的纯文本，覆盖同名 .txt。

这是 scripts/rag_builder.py 的前置步骤，本身不写向量库、不做切分。
之所以拆成独立脚本，是为了让中间产物可以肉眼复核：合规闸门完全依赖章节标题，
而 PDF 抽取最容易破坏的就是标题的独立成行结构。

用法（在项目根目录执行）：
    python scripts/pdf_to_text.py --dry-run  # 只打印标题识别情况，不写盘
    python scripts/pdf_to_text.py            # 确认无误后覆盖同名 txt

转换完成后必须回到 rag_builder 复核两道闸门是否照常触发：
    python scripts/rag_builder.py --dry-run
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RAW_DIR  # noqa: E402
from rag_builder import (  # noqa: E402
    RAW_FILE_META,
    SECTION_ALLOW,
    SECTION_DENY,
    is_heading,
    section_verdict,
)

# 句末标点。行尾命中即视为段落结束，不与下一行合并。
SENT_END = (".", "!", "?", ":", ";", "。", "！", "？", "：", "；", "•")

# 已知章节关键词。行首命中且够短的行强制独立成行，绝不参与重排，
# 否则标题会被后一行正文吞掉，章节过滤直接失效。
HEADING_KEYWORDS = tuple(SECTION_ALLOW) + tuple(SECTION_DENY)

# 页眉页脚判定：同一行文本出现在超过此比例的页面上即视为版面噪声。
CHROME_RATIO = 0.5
CHROME_MAX_LEN = 90


def normalize_ws(text: str) -> str:
    """统一空白字符。PDF 里大量 \\xa0 会让后续的标题判定与去重失准。"""
    return text.replace("\xa0", " ").replace("\u2009", " ").replace("\u200b", "")


def chrome_key(line: str) -> str:
    """页眉页脚归一化键。

    GeneReviews 每页页脚是「文档名 + 页码」（如 MECP2 Disorders 5），页码逐页递增，
    按原文精确计数永远达不到阈值。去掉行首尾的页码后才能识别出这是同一行版面噪声。
    这一步很关键：页脚一旦残留，就会在正文中间被 is_heading() 判成标题，
    把 Clinical Description 这类 ALLOW 章节拦腰截断，后半段全部漏进 skip 被丢掉。
    """
    s = normalize_ws(line).strip()
    s = re.sub(r"\s*\d+\s*$", "", s)
    s = re.sub(r"^\s*\d+\s*", "", s)
    return s.strip().lower()


def looks_like_section_heading(line: str) -> bool:
    """行首命中已知章节关键词的短行。这类行必须保持独立。"""
    s = line.strip().lower().rstrip(":：")
    if not s or len(s) > 60:
        return False
    return any(s.startswith(kw) for kw in HEADING_KEYWORDS)


def is_continuation(line: str) -> bool:
    """判断该行是否为上一行的软换行续写。"""
    s = line.lstrip()
    if not s:
        return False
    ch = s[0]
    if ch.islower():
        return True
    if ch in ",)]，）":
        return True
    # 纯数字续写（如被拆断的数值区间），但排除 "1. " 这类列表项
    if ch.isdigit() and not re.match(r"^\d+[.)]\s", s):
        return True
    return False


def drop_page_chrome(pages: list[str]) -> tuple[list[str], int]:
    """剔除重复出现在多数页面上的页眉页脚行。"""
    n = len(pages)
    if n < 4:
        return pages, 0

    counter: Counter[str] = Counter()
    for text in pages:
        seen = set()
        for raw in text.splitlines():
            key = chrome_key(raw)
            if key and len(key) <= CHROME_MAX_LEN:
                seen.add(key)
        for key in seen:
            counter[key] += 1

    threshold = max(3, int(n * CHROME_RATIO))
    chrome = {key for key, hits in counter.items() if hits >= threshold}
    if not chrome:
        return pages, 0

    cleaned = []
    for text in pages:
        kept = [ln for ln in text.splitlines() if chrome_key(ln) not in chrome]
        cleaned.append("\n".join(kept))
    return cleaned, len(chrome)


def reflow(lines: list[str]) -> list[str]:
    """把 PDF 按栏宽硬换行的正文重新接成完整段落。

    这是本脚本的核心。不做这一步，正文里大量「较短、首字母大写、无尾标点」的
    软换行会被 rag_builder.is_heading() 误判为章节标题，把文档切成上百个碎片，
    导致 Management 等章节无法被完整识别与丢弃。
    """
    out: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue

        if out and out[-1] and not looks_like_section_heading(s):
            prev = out[-1]
            if (
                not looks_like_section_heading(prev)
                and not prev.endswith(SENT_END)
                and is_continuation(s)
            ):
                if prev.endswith("-"):
                    out[-1] = prev[:-1] + s
                else:
                    out[-1] = f"{prev} {s}"
                continue

        out.append(s)

    return [ln for ln in out if ln != "" or True]


def extract(path: Path) -> tuple[str, dict]:
    """PDF -> 纯文本。返回 (文本, 统计信息)。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [normalize_ws(page.extract_text() or "") for page in reader.pages]
    pages, chrome_count = drop_page_chrome(pages)

    raw_lines: list[str] = []
    for text in pages:
        raw_lines.extend(text.splitlines())
        raw_lines.append("")

    lines = reflow(raw_lines)
    body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"

    headings = [ln for ln in lines if is_heading(ln)]
    allow_hits, deny_hits = [], []
    for h in headings:
        verdict = section_verdict(h)
        if verdict == "allow":
            allow_hits.append(h)
        elif verdict == "deny":
            deny_hits.append(h)

    stats = {
        "pages": len(pages),
        "chrome_lines": chrome_count,
        "lines": len(lines),
        "headings": len(headings),
        "allow": allow_hits,
        "deny": deny_hits,
    }
    return body, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印识别结果，不覆盖 txt"
    )
    args = parser.parse_args()

    pdfs = sorted(RAW_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"{RAW_DIR} 下没有 PDF，无需转换。")
        return 0

    converted = 0
    failures: list[str] = []

    for pdf in pdfs:
        target_name = f"{pdf.stem}.txt"
        if target_name not in RAW_FILE_META:
            print(f"  [跳过] {pdf.name} 不在 SOURCES.md 清单中，文件名需完全一致")
            continue

        body, stats = extract(pdf)
        _, _, origin = RAW_FILE_META[target_name]

        print(f"\n{pdf.name}")
        print(
            f"  页数 {stats['pages']}｜重排后 {stats['lines']} 行｜"
            f"标题 {stats['headings']} 个｜页眉页脚剔除 {stats['chrome_lines']} 种"
        )
        print(f"  收录章节 {len(stats['allow'])} 个：{stats['allow'][:6]}")
        print(f"  丢弃章节 {len(stats['deny'])} 个：{stats['deny'][:6]}")

        # GeneReviews 必然含干预章节。一个都没识别出来说明标题结构被抽坏了，
        # 此时继续灌库会让 Management 内容混入向量库，直接击穿合规定位。
        if origin == "genereviews" and not stats["deny"]:
            failures.append(f"{pdf.name}：未识别到任何干预类章节，标题可能已损坏")
            print("  [异常] 未识别到 Management / Treatment 等干预章节")
        if not stats["allow"]:
            failures.append(f"{pdf.name}：未识别到任何可收录章节，转换结果为空壳")
            print("  [异常] 未识别到任何可收录章节")

        if not args.dry_run:
            (RAW_DIR / target_name).write_text(body, encoding="utf-8")
            converted += 1

    print()
    if args.dry_run:
        print("--dry-run 已启用，未写入任何 txt。")
    else:
        print(f"已转换并覆盖 {converted} 份 txt。")
        print("下一步：python scripts/rag_builder.py --dry-run  复核两道合规闸门")

    if failures:
        print("\n以下文件需要人工复核：")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
