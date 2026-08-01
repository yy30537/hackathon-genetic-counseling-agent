"""构建本地 RAG 向量库。

双来源语料：
  1. data/knowledge/*.json  精编切片，始终入库，合规安全核心。
  2. data/knowledge/raw/*.txt  手动下载的 GeneReviews / PubMed 原文，需经章节过滤与用药词拦截。

用法（在项目根目录执行）：
    python scripts/rag_builder.py            # 增量重建（先清空 collection）
    python scripts/rag_builder.py --dry-run  # 只做切分与过滤，不写入向量库

下载清单见 data/knowledge/SOURCES.md。
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    KNOWLEDGE_DIR,
    RAW_DIR,
)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# 只收录描述性章节。GeneReviews 的章节标题为独立成行的短句。
SECTION_ALLOW = [
    "clinical characteristics",
    "clinical description",
    "diagnosis",
    "suggestive findings",
    "establishing the diagnosis",
    "differential diagnosis",
    "genotype-phenotype correlations",
    "phenotype correlations",
    "prevalence",
    "nomenclature",
    "abstract",
]

# 含干预与用药建议的章节，强制丢弃。这是 PRD W3 / AC5 红线的第一道保障。
SECTION_DENY = [
    "management",
    "treatment of manifestations",
    "surveillance",
    "agents and circumstances to avoid",
    "therapies under investigation",
    "pregnancy management",
    "evaluations following initial diagnosis",
    "prevention of primary manifestations",
    "prevention of secondary complications",
]

# 兜底：即便章节过滤放行，命中以下词的切片一律丢弃。
DRUG_PATTERNS = [
    r"everolimus", r"sirolimus", r"risperidone", r"aripiprazole", r"valproat",
    r"carbamazepine", r"lamotrigine", r"levetiracetam", r"vigabatrin",
    r"clonazepam", r"melatonin", r"methylphenidate", r"fluoxetine", r"sertraline",
    r"\bmg/kg\b", r"\bdosage\b", r"\bdosing\b", r"\bprescrib",
    r"利培酮", r"阿立哌唑", r"丙戊酸", r"卡马西平", r"左乙拉西坦", r"氨己烯酸",
    r"抗癫痫药", r"精神药物治疗", r"用药剂量", r"服用剂量", r"每日剂量",
]
DRUG_RE = re.compile("|".join(DRUG_PATTERNS), re.IGNORECASE)

# 文件名 -> (病种, 基因, 来源类型)
RAW_FILE_META = {
    "genereviews_mecp2_rett.txt": ("Rett 综合征 / MECP2 相关疾病", "MECP2", "genereviews"),
    "genereviews_fmr1_fragile_x.txt": ("脆性 X 综合征", "FMR1", "genereviews"),
    "genereviews_ube3a_angelman.txt": ("安格曼综合征", "UBE3A", "genereviews"),
    "genereviews_tsc.txt": ("结节性硬化症", "TSC1/TSC2", "genereviews"),
    "genereviews_nsd1_sotos.txt": ("Sotos 综合征", "NSD1", "genereviews"),
    "genereviews_prader_willi.txt": ("Prader-Willi 综合征", "15q11.2-q13", "genereviews"),
    "pubmed_33921431_wes_value.txt": ("全外显子测序的诊断价值", "", "pubmed"),
    "pubmed_37878314_vus_acmg.txt": ("VUS 重分类数据", "", "pubmed"),
    "aap_asd_guideline_abstract.txt": ("ASD 初级保健指南", "", "aap"),
}

# PubMed 与 AAP 属于科普/证据类，归入桶 B；GeneReviews 属于鉴别规则，归入桶 A。
RAW_BUCKET = {"genereviews": "A", "pubmed": "B", "aap": "A"}

# 占位文件哨兵。data/knowledge/raw/ 下预置了同名空壳文件用于提示下载，
# 内容含此标记即视为尚未填充，直接跳过，避免把说明文字灌进向量库。
PLACEHOLDER_MARK = "RAG_CORPUS_PLACEHOLDER"


def is_heading(line: str) -> bool:
    """GeneReviews 章节标题：独立成行、较短、无句末标点。"""
    s = line.strip()
    if not (0 < len(s) <= 60):
        return False
    if s.endswith((".", "。", ",", "，", ";", "；", ":")):
        return False
    return bool(re.match(r"^[A-Z\u4e00-\u9fff]", s))


def split_sections(text: str):
    """按标题行切成 (标题, 正文) 列表。首个标题之前的内容归入 __preamble__。"""
    sections, title, buf = [], "__preamble__", []
    for line in text.splitlines():
        if is_heading(line):
            if buf:
                sections.append((title, "\n".join(buf)))
            title, buf = line.strip(), []
        else:
            buf.append(line)
    if buf:
        sections.append((title, "\n".join(buf)))
    return sections


def section_verdict(title: str) -> str:
    """返回 allow / deny / skip。"""
    t = title.lower()
    for kw in SECTION_DENY:
        if kw in t:
            return "deny"
    for kw in SECTION_ALLOW:
        if kw in t:
            return "allow"
    return "skip"


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按段落聚合的滑窗切分，纯标准库实现。"""
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in paragraphs:
        if len(cur) + len(p) + 1 <= size:
            cur = f"{cur}\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            # 段落本身超长时按字符硬切
            while len(p) > size:
                chunks.append(p[:size])
                p = p[size - overlap:]
            cur = p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) >= 40]


def load_curated():
    """读取精编切片，始终入库。"""
    docs = []
    for path in sorted(KNOWLEDGE_DIR.glob("bucket_*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            docs.append({
                "id": entry["id"],
                "text": entry["text"],
                "metadata": {
                    "bucket": entry["bucket"],
                    "source": entry["source"],
                    "condition": entry.get("condition", ""),
                    "gene": entry.get("gene", ""),
                    "origin": "curated",
                },
            })
    return docs


def load_raw():
    """读取并过滤原文语料。返回 (docs, 统计信息)。"""
    docs = []
    stats = {
        "files": 0, "placeholders": 0,
        "denied_sections": 0, "skipped_sections": 0, "drug_blocked": 0,
    }
    if not RAW_DIR.exists():
        return docs, stats

    for path in sorted(RAW_DIR.glob("*.txt")):
        meta = RAW_FILE_META.get(path.name)
        if meta is None:
            print(f"  [跳过] {path.name} 不在 SOURCES.md 清单中，文件名需完全一致")
            continue

        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER_MARK in text:
            stats["placeholders"] += 1
            print(f"  [待填充] {path.name} 仍是占位文件，尚未粘贴原文")
            continue

        condition, gene, origin = meta
        bucket = RAW_BUCKET[origin]
        stats["files"] += 1
        kept = 0

        for title, body in split_sections(text):
            verdict = section_verdict(title)
            if verdict == "deny":
                stats["denied_sections"] += 1
                continue
            if verdict == "skip":
                stats["skipped_sections"] += 1
                continue

            for i, chunk in enumerate(chunk_text(body)):
                if DRUG_RE.search(chunk):
                    stats["drug_blocked"] += 1
                    continue
                docs.append({
                    "id": f"{path.stem}__{re.sub(r'[^a-z0-9]+', '_', title.lower())[:40]}__{i}",
                    "text": chunk,
                    "metadata": {
                        "bucket": bucket,
                        "source": path.stem,
                        "condition": condition,
                        "gene": gene,
                        "origin": origin,
                        "section": title,
                    },
                })
                kept += 1
        print(f"  [已收录] {path.name} -> {kept} 条切片")

    return docs, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只切分不写库")
    args = parser.parse_args()

    print("读取精编切片...")
    curated = load_curated()
    print(f"  精编切片 {len(curated)} 条")

    print("读取原文语料...")
    raw, stats = load_raw()
    if stats["files"] == 0:
        print("  未发现已填充的原文语料。仅使用精编切片。")
        print("  如需完整 RAG，请按 data/knowledge/SOURCES.md 下载文档至 data/knowledge/raw/")
    else:
        print(f"  原文文件 {stats['files']} 份 -> {len(raw)} 条切片")
        print(f"  合规过滤：丢弃干预/用药章节 {stats['denied_sections']} 个，"
              f"无关章节 {stats['skipped_sections']} 个，用药词拦截 {stats['drug_blocked']} 条")
    if stats["placeholders"]:
        print(f"  仍有 {stats['placeholders']} 份占位文件待填充（上方标记为「待填充」）")

    docs = curated + raw
    # 按 id 去重，精编优先
    seen, unique = set(), []
    for d in docs:
        if d["id"] not in seen:
            seen.add(d["id"])
            unique.append(d)
    docs = unique

    print(f"\n合计入库 {len(docs)} 条切片"
          f"（桶 A {sum(1 for d in docs if d['metadata']['bucket'] == 'A')}，"
          f"桶 B {sum(1 for d in docs if d['metadata']['bucket'] == 'B')}，"
          f"桶 C {sum(1 for d in docs if d['metadata']['bucket'] == 'C')}）")

    if args.dry_run:
        print("--dry-run 已启用，未写入向量库。")
        return

    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    # 重建以避免残留旧切片
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME, embedding_function=embedder
    )
    collection.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[d["metadata"] for d in docs],
    )
    print(f"知识库已写入 ChromaDB：{CHROMA_PATH} / {COLLECTION_NAME}")
    print(f"向量模型：{EMBEDDING_MODEL}")


if __name__ == "__main__":
    sys.exit(main())
