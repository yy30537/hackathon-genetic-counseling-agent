# RAG 原文语料下载清单

本项目的知识库采用**双来源**策略：

1. **精编切片**（已就位）：`bucket_a_differential.json` / `bucket_b_vus.json` / `bucket_c_compliance.json`，共 10 条，内容来自 [docs/后端知识库架构与数据字典.md](../../docs/后端知识库架构与数据字典.md)。这是合规安全的核心，缺失原文也能跑通。
2. **原文切片**（需手动下载）：按下表把文档存入 `data/knowledge/raw/`，运行 `python scripts/rag_builder.py` 后自动切分入库。

---

## 保存要求（重要）

- **格式**：纯文本 `.txt`，UTF-8 编码。网页上全选复制粘贴进文本编辑器即可。
- **必须保留章节标题行**（如 `Clinical Characteristics`、`Differential Diagnosis`、`Management`）。切分脚本依赖这些标题做章节过滤，标题丢失会导致整篇被跳过。
- **不要手动删除 Management 章节**：脚本会自动识别并丢弃，保留原样即可，这样过滤日志能算出准确的丢弃比例。
- 文件名必须与下表**完全一致**，脚本按文件名推断来源与病种。

---

## GeneReviews（NCBI Bookshelf）

| 目标文件名 | NBK ID | 病种 | 链接 |
|---|---|---|---|
| `genereviews_mecp2_rett.txt` | NBK1497 | Rett 综合征 / MECP2 | https://www.ncbi.nlm.nih.gov/books/NBK1497/ |
| `genereviews_fmr1_fragile_x.txt` | NBK1384 | 脆性 X 综合征 / FMR1 | https://www.ncbi.nlm.nih.gov/books/NBK1384/ |
| `genereviews_ube3a_angelman.txt` | NBK1144 | 安格曼综合征 / UBE3A | https://www.ncbi.nlm.nih.gov/books/NBK1144/ |
| `genereviews_tsc.txt` | NBK1220 | 结节性硬化症 / TSC1-TSC2 | https://www.ncbi.nlm.nih.gov/books/NBK1220/ |
| `genereviews_nsd1_sotos.txt` | NBK1479 | Sotos 综合征 / NSD1 | https://www.ncbi.nlm.nih.gov/books/NBK1479/ |
| `genereviews_prader_willi.txt` | NBK1330 | Prader-Willi 综合征 | https://www.ncbi.nlm.nih.gov/books/NBK1330/ |

## PubMed 摘要

| 目标文件名 | PMID | 主题 | 链接 |
|---|---|---|---|
| `pubmed_33921431_wes_value.txt` | 33921431 | WES 在 ASD 中的诊断价值 | https://pubmed.ncbi.nlm.nih.gov/33921431/ |
| `pubmed_37878314_vus_acmg.txt` | 37878314 | ACMG VUS 大规模重分类数据 | https://pubmed.ncbi.nlm.nih.gov/37878314/ |

## AAP 临床指南（可选）

| 目标文件名 | 说明 |
|---|---|
| `aap_asd_guideline_abstract.txt` | 全文位于 publications.aap.org 付费墙后，仅需保存摘要。缺失不影响灌库，桶 A 已有该指南的精编要点。 |

链接：https://publications.aap.org/pediatrics/article/145/1/e20193447/36917/

---

## 合规与版权

- **章节过滤**：`scripts/rag_builder.py` 只收录 Clinical Characteristics、Clinical Description、Diagnosis、Differential Diagnosis 等描述性章节，**强制丢弃 Management、Treatment、Surveillance、Agents and Circumstances to Avoid、Therapies Under Investigation** 等含干预与用药建议的章节。这是 PRD 中 W3 / AC5 红线的结构性保障——GeneReviews 的 Management 章节含明确药名与方案，一旦入库就可能被检索并输出，直接击穿 Non-Device CDS 定位。
- **兜底扫描**：即便通过章节过滤，每个切片仍会扫描用药关键词，命中即丢弃并告警。
- **版权**：GeneReviews 版权归 University of Washington 所有，允许本地个人使用但限制再分发。`data/knowledge/raw/` 已加入 [.gitignore](../../.gitignore)，**请勿把原文提交到公开仓库**。
