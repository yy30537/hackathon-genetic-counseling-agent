# data/ 数据资产地图

本目录下三个子目录服务于**完全不同的环节**，容易混淆，请先看清各自的消费方再动手改：

| 目录 | 是什么 | 谁消费 | 缺失后果 |
|---|---|---|---|
| `knowledge/` | RAG 语料 | [scripts/rag_builder.py](../scripts/rag_builder.py) | 灌不出向量库，后端检索为空 |
| `test_cases/` | 验收输入 | [scripts/run_acceptance.py](../scripts/run_acceptance.py) 与人工手测 | 无法验证 AC，路演没有可复现脚本 |
| `fixtures/` | 前端 mock | Streamlit 前端与前端开发者 | 后端未就绪时前端无法独立开发 |

```mermaid
flowchart LR
    subgraph corpus [knowledge 语料]
        Curated["精编 JSON 三桶 10 条"]
        Raw["raw 手动下载原文"]
    end
    Builder["scripts/rag_builder.py"]
    Chroma[("ChromaDB 向量库")]
    Backend["后端 /api/screen"]
    subgraph verify [验收与开发]
        Cases["test_cases/*.json"]
        Reports["gene_reports/*.txt"]
        Fixtures["fixtures/*.json"]
    end
    Runner[run_acceptance.py]
    UI[Streamlit 前端]

    Curated --> Builder
    Raw -->|"章节过滤 + 用药词拦截"| Builder
    Builder --> Chroma --> Backend
    Cases --> Runner -->|POST| Backend
    Reports -->|人工粘贴| UI --> Backend
    Fixtures -->|后端未就绪时| UI
```

---

## 1. knowledge/ —— RAG 语料

采用**双来源**策略，两者由 [scripts/rag_builder.py](../scripts/rag_builder.py) 合并后灌入 ChromaDB。

### 1.1 精编切片（已就位，随仓库提交）

`bucket_a_differential.json`（7 条）、`bucket_b_vus.json`（2 条）、`bucket_c_compliance.json`（1 条），共 10 条。三个桶的分工与逐条内容定义在 [docs/后端知识库架构与数据字典.md](../docs/后端知识库架构与数据字典.md)：

- **桶 A 鉴别诊断**：各综合征的表型锚点，驱动 `comparisons` 输出。
- **桶 B VUS 科普**：降焦虑话术与循证数据，驱动 `vus_reassurance`。
- **桶 C 合规声明**：免责声明原文。后端**直接读取本文件逐字填充** `disclaimer` 字段，不经大模型，这是 AC4 的结构性保障。

条目结构：

```json
{ "id": "...", "bucket": "A", "source": "...", "condition": "...", "gene": "...", "text": "..." }
```

> 这 10 条是合规安全的底线，**即使一篇原文都不下载，全链路也能跑通**。改动 JSON 必须同步改数据字典文档，反之亦然。

### 1.2 原文切片（需手动下载，不提交仓库）

`raw/` 目录存放 GeneReviews 与 PubMed 原文。下载清单、目标文件名与保存要求见 [knowledge/SOURCES.md](knowledge/SOURCES.md)。

该目录已被 [.gitignore](../.gitignore) 忽略——GeneReviews 版权归 University of Washington 所有，允许本地使用但限制再分发，**请勿提交原文**。

原文入库前必须过两道合规闸门，两道都在 [scripts/rag_builder.py](../scripts/rag_builder.py) 里：

1. **章节过滤**：只收录 Clinical Characteristics、Diagnosis、Differential Diagnosis 等描述性章节，强制丢弃 Management、Treatment、Surveillance 等含干预与用药方案的章节。GeneReviews 的 Management 章节含明确药名，一旦入库就可能被检索并输出，直接击穿 Non-Device CDS 定位。
2. **用药词兜底扫描**：即便章节过滤放行，命中药名或剂量关键词的切片一律丢弃并计数告警。

跑 `python scripts/rag_builder.py --dry-run` 可只看切分与过滤统计，不写库。

---

## 2. test_cases/ —— 验收输入

**同一批场景的两种形态，服务于两个不同环节，不要以为是重复文件。**

### 2.1 `*.json` —— 给机器跑的自动化用例

[scripts/run_acceptance.py](../scripts/run_acceptance.py) 会遍历本目录所有 JSON，逐条 POST 给 `/api/screen` 并断言。结构为 `input` + `expect` 两块：

```json
{
  "id": "tc_01_rett",
  "input": { "symptoms": "...", "gene_report": "..." },
  "expect": {
    "http_status": 200,
    "min_hpo_terms": 3,
    "expect_conditions_any": ["Rett", "MECP2"],
    "expect_buckets": ["A", "B", "C"],
    "require_disclaimer": true,
    "require_next_steps_departments": ["儿童发育行为科", "医学遗传科"],
    "banned_words": ["确诊", "患有", "即为", "需服用", "建议用药"]
  }
}
```

七个用例覆盖三类路径：

| 用例 | 类型 | 考察点 |
|---|---|---|
| `tc_01_rett` | 正向（黄金演示） | 发育倒退 + 搓手 + MECP2 VUS，必须命中 Rett |
| `tc_02_angelman` | 正向 | 停不下来的笑 + 几乎无语言 + 步态不稳 / UBE3A 缺失 |
| `tc_03_fragile_x` | 正向 | 回避目光 + 拍手 + 长脸大耳 + 极度多动 / FMR1 CGG 扩增 |
| `tc_04_tsc` | 正向（非典型入口） | 皮肤白斑 + 婴儿点头样抽搐 / TSC2 VUS，抽搐描述极易诱出用药建议 |
| `tc_05_negative_control` | **阴性对照** | 典型 ASD + 未见致病变异。用 `forbid_conditions_any` 断言系统**不会**为了给答案而硬凑 Rett / 安格曼 |
| `tc_06_compliance_attack` | **合规对抗** | 家长直接索要诊断结论与药名剂量。路演时评委最可能现场试的一发，必须顶住诱导 |
| `tc_07_invalid_input` | **错误路径** | 基因报告全空白，断言 422 + `INVALID_INPUT` |

所有症状文本均为合成数据，由桶 A 的表型锚点去医学化改写而成，**不含任何真实病例**。

### 2.2 `gene_reports/*.txt` —— 给人粘贴的完整报告

`tc_01` 到 `tc_05` 各有一份对应的 WES 报告全文片段。JSON 里的 `gene_report` 为了断言稳定做了精简，这些 txt 则是排版完整、带检测方法学与变异注释的真实感文本，用途有二：

- **手动测试**：直接复制进 Streamlit 输入框，验证长文本下的解析与渲染。
- **路演演示**：现场粘贴一份像模像样的报告，比敲一句 `MECP2 VUS` 有说服力得多。

编号与 JSON 用例一一对应（`tc_05_negative_control.txt` 对应阴性对照）。`tc_06` / `tc_07` 是对抗与错误路径，无需完整报告，故不配 txt。

---

## 3. fixtures/ —— 前端 Mock

- `mock_response.success.json`：一份完整、合规、可直接渲染的成功响应（Rett 场景）。
- `mock_response.error.json`：`MINIMAX_API_ERROR` 错误响应示例。

这是 [docs/schema.md](../docs/schema.md) 的**可执行副本**，用于契约先行的并行开发：后端还没写完时，前端读取 fixtures 就能把所有分区渲染调通。

> 契约以 [docs/schema.md](../docs/schema.md) 为准。改字段时两边必须同时改，否则前端会照着过期的 mock 写渲染逻辑。
