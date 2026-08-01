# API 数据契约 (Contract-First Schema)

> 前后端唯一事实来源。前端与后端智能体均以本文档为准平行开发，任何偏离视为 Bug。
> 配套 Mock：[data/fixtures/mock_response.success.json](../data/fixtures/mock_response.success.json) 与 [data/fixtures/mock_response.error.json](../data/fixtures/mock_response.error.json)

---

## 1. API 路由定义 (Endpoint)

| 项 | 值 |
|---|---|
| Path | `/api/screen` |
| Method | `POST` |
| Base URL | `http://127.0.0.1:8000`（默认值，前端从 `.env` 的 `BACKEND_URL` 读取，可覆盖） |
| Content-Type | `application/json` |

**Description**：全系统唯一业务端点，串联 MCP 表型标准化、RAG 知识检索与 Minimax M3 生成三段流水线，返回结构化的《症状与基因筛查比对报告》。

---

## 2. 请求数据结构 (Request Schema)

Pydantic 模型：`ScreeningRequest`。单层扁平，无任何嵌套。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `symptoms` | String | Required | 家长白话症状描述，非空 |
| `gene_report` | String | Required | 基因测序报告或 VUS 片段原文，非空 |

```python
class ScreeningRequest(BaseModel):
    symptoms: str
    gene_report: str
```

```json
{
  "symptoms": "孩子3岁，1岁半以前会说的词现在都不说了，最近半年总是不停地搓手绞手，还经常无缘无故地笑，走路也不太稳。",
  "gene_report": "全外显子测序（WES）检出 MECP2 基因错义变异 c.455C>G (p.Pro152Arg)，临床意义未明（VUS）。"
}
```

---

## 3. 成功响应数据结构 (Success Response Schema, HTTP 200)

Pydantic 模型：`ScreeningResponse`。允许一层「数组套简单对象」，禁止更深嵌套。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | String | Required | 固定为 `"success"` |
| `hpo_terms` | Array\<HpoTerm\> | Required | MCP 标准化结果，长度 ≥ 1 |
| `comparisons` | Array\<Comparison\> | Required | 鉴别比对结果，无命中时为空数组 |
| `vus_reassurance` | String | Required | 桶 B 的 VUS 降维安抚话术 |
| `next_steps` | Array\<String\> | Required | 就诊建议清单，必须含儿童发育行为科与医学遗传科 |
| `disclaimer` | String | Required | 桶 C 免责声明逐字原文，**后端硬编码填充，不经 LLM** |
| `mcp_translation` | String | Required | MCP 标准化过程原始输出，供前端调试面板展示 |
| `retrieved_chunks` | Array\<Chunk\> | Required | RAG 命中切片，供前端调试面板展示 |

### 子对象定义

`HpoTerm`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `hpo_id` | String | Required | 形如 `HP:0000733` |
| `name` | String | Required | 标准表型名称 |
| `matched_text` | String | Required | 命中的家长原话片段 |

`Comparison`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `condition` | String | Required | 疾病名称 |
| `gene` | String | Required | 相关基因 |
| `matched_anchors` | Array\<String\> | Required | 命中的鉴别锚点 |
| `explanation` | String | Required | 客观描述，严禁确诊措辞 |
| `source` | String | Required | 文献来源，如 `GeneReviews` |

`Chunk`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `bucket` | String | Required | 枚举 `"A"` / `"B"` / `"C"` |
| `origin` | String | Required | 枚举 `"curated"` / `"genereviews"` / `"pubmed"` / `"aap"`，标识切片来自精编语料还是下载原文 |
| `source` | String | Required | 切片出处标识 |
| `text` | String | Required | 切片原文 |

> `origin` 直接透传 ChromaDB 中由 [scripts/rag_builder.py](../scripts/rag_builder.py) 写入的同名 metadata，前端调试面板据此区分「精编摘要」与「文献原文」。

### Pydantic 声明

```python
class HpoTerm(BaseModel):
    hpo_id: str
    name: str
    matched_text: str


class Comparison(BaseModel):
    condition: str
    gene: str
    matched_anchors: List[str]
    explanation: str
    source: str


class Chunk(BaseModel):
    bucket: Literal["A", "B", "C"]
    origin: Literal["curated", "genereviews", "pubmed", "aap"]
    source: str
    text: str


class ScreeningResponse(BaseModel):
    status: Literal["success"] = "success"
    hpo_terms: List[HpoTerm]
    comparisons: List[Comparison]
    vus_reassurance: str
    next_steps: List[str]
    disclaimer: str
    mcp_translation: str
    retrieved_chunks: List[Chunk]
```

---

## 3.1 错误响应数据结构 (Error Response Schema)

错误语义由 HTTP 状态码承载，响应体统一为 `ErrorResponse`。禁止「一律 200 + status 字段」的信封模式。

```python
class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str
    error_message: str
```

| HTTP 状态码 | `error_code` | 触发条件 |
|---|---|---|
| 422 | `INVALID_INPUT` | `symptoms` 或 `gene_report` 为空 / 全空白 |
| 500 | `MISSING_API_KEY` | 后端未从 `.env` 读取到 `MINIMAX_API_KEY` |
| 502 | `MINIMAX_API_ERROR` | Minimax 接口返回非 200、超时，或返回内容无法解析为约定 JSON |

---

## 3.2 契约不变量

字段类型合法**不等于**响应合法。以下约束是契约的一部分，实现时必须一并满足。

### 由验收脚本自动断言

[scripts/run_acceptance.py](../scripts/run_acceptance.py) 会逐条校验，违反即退出码 1：

| # | 不变量 | 为什么 |
|---|---|---|
| I1 | `disclaimer` 必须**逐字等于** [data/knowledge/bucket_c_compliance.json](../data/knowledge/bucket_c_compliance.json) 中的原文（首尾空白除外），由后端硬编码填充 | 靠 prompt 祈使模型输出免责声明不可靠。这是 Non-Device CDS 定位的结构性保障，不是文案偏好 |
| I2 | `next_steps` 必须同时出现「儿童发育行为科」与「医学遗传科」 | 产品的落点是把用户交还给专科医生，缺任一科室即断链 |
| I3 | `comparisons[].explanation`、`vus_reassurance`、`next_steps` 三者中禁止出现「确诊」「患有」「即为」「需服用」「建议用药」及场景专属药名 | 越过这条线即构成诊断与用药建议，丧失豁免资格 |
| I4 | 每项 `hpo_id` 以 `HP:` 开头；`hpo_terms` 数量不低于用例声明的 `min_hpo_terms` | 表型标准化是 MCP 存在的意义，返回空数组等于这一环没跑 |
| I5 | `comparisons` 中不得出现用例 `forbid_conditions_any` 列出的病种 | 禁止为了给答案而硬凑罕见病。阴性对照用例 `tc_05` 专门验这条 |
| I6 | `retrieved_chunks` 的 `bucket` 需覆盖用例声明的 `expect_buckets`（通常为 A/B/C 全覆盖） | 三个桶各自驱动一块输出，缺桶意味着对应分区是模型编的 |

关于 I3 的两个坑：

- 扫描是**字面子串**匹配，即便用于否定句式（如「这不是确诊结论」）也会判失败，需改写措辞绕开该词。
- 禁用词清单逐用例给出，不同场景会追加专属词——`tc_06` 追加了「利培酮」「剂量」。
- 扫描范围**不含** `disclaimer` 与 `retrieved_chunks`：前者是法定免责原文，后者是知识库原文，两者本就允许出现「确诊」等词。

### 靠设计与人工评审保障

以下两条难以用字符串断言，但同样是硬要求，实现时不要因为脚本不查就放过：

| # | 不变量 | 落实方式 |
|---|---|---|
| I7 | `comparisons[].explanation` 的每个论断都必须能回溯到 `retrieved_chunks` 中的某个切片 | RAG 照本宣科原则。在 system prompt 中要求模型只依据给定切片作答，路演前人工抽查 |
| I8 | 检索无命中时 `comparisons` 返回**空数组**，且 `vus_reassurance` 明确说明未匹配到相关指南 | 宁可少说也不编造。后端在切片为空时应短路，不要把空上下文丢给模型自由发挥 |

---

## 4. Mock 数据

### 4.1 成功态

**完整数据以 [data/fixtures/mock_response.success.json](../data/fixtures/mock_response.success.json) 为准**，前端直接读取该文件即可在后端就绪前跑通全部渲染。下面只保留字段骨架用于快速对形状，数组各留一项，长文案已截断——**请勿把这段骨架当数据用，也不要在此处维护第二份全文**。

```json
{
  "status": "success",
  "hpo_terms": [
    { "hpo_id": "HP:0000733", "name": "刻板动作", "matched_text": "总是不停地搓手绞手" }
  ],
  "comparisons": [
    {
      "condition": "Rett 综合征",
      "gene": "MECP2",
      "matched_anchors": ["语言发育倒退", "手部刻板动作", "步态不稳"],
      "explanation": "GeneReviews 关于 MECP2 相关疾病的资料记载，其典型病程为早期发育基本正常，随后出现已获得的语言与手部功能倒退……（完整内容见 fixtures）",
      "source": "GeneReviews - MECP2-Related Disorders"
    }
  ],
  "vus_reassurance": "看到报告上「临床意义未明（VUS）」这几个字时感到不安是非常正常的……（完整内容见 fixtures）",
  "next_steps": [
    "携带本信息整理单、完整的 WES 测序报告原件……前往正规三甲医疗机构的儿童发育行为科就诊。"
  ],
  "disclaimer": "本系统提供的信息比对与基因知识科普均基于权威医学文献检索生成……（桶 C 逐字原文，见 data/knowledge/bucket_c_compliance.json）",
  "mcp_translation": "已将 4 条白话描述标准化为 HPO 术语：「总是不停地搓手绞手」-> HP:0000733 (刻板动作)……",
  "retrieved_chunks": [
    {
      "bucket": "A",
      "origin": "curated",
      "source": "GeneReviews_MECP2",
      "text": "MECP2 相关疾病的典型病程为早期发育基本正常，6 至 18 月龄后出现已获得的语言与手部功能倒退……"
    }
  ]
}
```

fixtures 中的完整样例含 4 条 `hpo_terms`、2 条 `comparisons`、5 条 `next_steps` 与 5 条覆盖桶 A/B/C 的 `retrieved_chunks`。

### 4.2 错误态（HTTP 502）

```json
{
  "status": "error",
  "error_code": "MINIMAX_API_ERROR",
  "error_message": "调用 Minimax M3 失败：接口返回状态码 429（请求过于频繁）。请稍后重试；若持续失败，请检查 .env 中的 MINIMAX_API_KEY 额度。"
}
```

### 4.3 错误态（HTTP 422）

```json
{
  "status": "error",
  "error_code": "INVALID_INPUT",
  "error_message": "症状描述与基因报告均为必填项，请补全后重新提交。"
}
```

---

## 5. 快速自测

后端起来后先用一条 curl 确认契约通了，再接前端：

```bash
curl -s -X POST http://127.0.0.1:8000/api/screen \
  -H "Content-Type: application/json" \
  -d '{
        "symptoms": "孩子3岁，会说的词都不说了，总是搓手绞手，走路不太稳。",
        "gene_report": "WES 检出 MECP2 基因错义变异 c.455C>G (p.Pro152Arg)，临床意义未明（VUS）。"
      }' | python3 -m json.tool
```

验证 422 分支：

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/screen \
  -H "Content-Type: application/json" \
  -d '{"symptoms": "孩子不太爱说话。", "gene_report": "   "}'
# 期望输出 422
```

字段与不变量的完整校验交给验收脚本，它会跑完 [data/test_cases/](../data/test_cases/) 下的全部 7 个用例：

```bash
python scripts/run_acceptance.py
```
