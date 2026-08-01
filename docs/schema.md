# API 数据契约 (Contract-First Schema)

> 前后端唯一事实来源。前端与后端智能体均以本文档为准平行开发，任何偏离视为 Bug。
> 配套 Mock：[data/fixtures/mock_response.success.json](../data/fixtures/mock_response.success.json) 与 [data/fixtures/mock_response.error.json](../data/fixtures/mock_response.error.json)

---

## 1. API 路由定义 (Endpoint)

| 项 | 值 |
|---|---|
| Path | `/api/screen` |
| Method | `POST` |
| Base URL | `http://127.0.0.1:8000` |
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
| `source` | String | Required | 切片出处标识 |
| `text` | String | Required | 切片原文 |

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

## 4. Mock 数据

### 4.1 成功态（同步落盘于 [data/fixtures/mock_response.success.json](../data/fixtures/mock_response.success.json)）

```json
{
  "status": "success",
  "hpo_terms": [
    {
      "hpo_id": "HP:0000733",
      "name": "刻板动作",
      "matched_text": "总是不停地搓手绞手"
    },
    {
      "hpo_id": "HP:0000750",
      "name": "语言发育延迟",
      "matched_text": "1岁半以前会说的词现在都不说了"
    },
    {
      "hpo_id": "HP:0000748",
      "name": "不恰当的笑",
      "matched_text": "经常无缘无故地笑"
    },
    {
      "hpo_id": "HP:0002540",
      "name": "步态不稳",
      "matched_text": "走路也不太稳"
    }
  ],
  "comparisons": [
    {
      "condition": "Rett 综合征",
      "gene": "MECP2",
      "matched_anchors": ["语言发育倒退", "手部刻板动作", "步态不稳"],
      "explanation": "GeneReviews 关于 MECP2 相关疾病的资料记载，其典型病程为早期发育基本正常，随后出现已获得的语言与手部功能倒退，并伴随搓手、绞手等特征性手部刻板动作，部分患儿合并步态共济失调。您描述的几项表现与该资料中提到的观察要点存在重合，建议就诊时将「发育倒退的起始月龄」与「手部动作的具体形式」作为重点线索向医生说明。需要留意的是，本条仅为文献特征的客观比对，不构成任何结论。",
      "source": "GeneReviews - MECP2-Related Disorders"
    },
    {
      "condition": "安格曼综合征",
      "gene": "UBE3A",
      "matched_anchors": ["不恰当的笑", "语言功能严重受限", "步态共济失调"],
      "explanation": "GeneReviews 关于安格曼综合征的资料提到，频繁爆发的大笑与微笑、几乎无语言、宽基底且手臂高举屈曲的共济失调步态是其常被提及的观察锚点。您提到的「无缘无故地笑」与「走路不稳」在文献描述上与之有部分交集，因此列为需要专业医生一并排除的方向。该资料同时指出，此病由 15q11.2-q13 区域母源 UBE3A 表达缺失引起，与当前报告中的 MECP2 变异属于不同机制，是否需要进一步检查应由遗传科医生判断。",
      "source": "GeneReviews - Angelman Syndrome"
    }
  ],
  "vus_reassurance": "看到报告上「临床意义未明（VUS）」这几个字时感到不安是非常正常的，但请先不要过度担心。VUS 可以理解为基因这本说明书里遇到的一个「生僻字」——它只代表目前全球医学数据库积累的证据还不足以判断它的含义，而不是一张下了结论的通知单。ACMG 的大规模变异数据分析显示，在接受广泛基因组检测的人群中，高达 41% 的个体都会收到至少一个 VUS 报告；而经过平均近三年的重新分类过程后，其中高达 80.2% 最终被证实为完全无害的良性改变。也正因如此，国际指南明确要求临床医生不得仅凭一个 VUS 就对孩子采取激进的医疗干预。测序的真正价值在于精确解释发病机制、并据此制定有针对性的监测方案，而不是给孩子贴上标签。",
  "next_steps": [
    "携带本信息整理单、完整的 WES 测序报告原件，以及孩子从出生至今的成长发育记录（如会说话、会走路的月龄），前往正规三甲医疗机构的儿童发育行为科就诊。",
    "同时预约医学遗传科门诊，就报告中 MECP2 c.455C>G (p.Pro152Arg) 这一 VUS 变异的解读、是否需要进行父母双方验证测序（Trio 验证）等问题，向专业医生当面咨询。",
    "就诊前用手机录下孩子搓手、绞手时的短视频，并记录每天发生的大致频次与持续时长，这类客观材料能显著提高医生问诊的效率。",
    "整理并向医生说明「语言倒退」的具体时间点：孩子最多时会说哪些词、大约从几月龄开始减少、目前还保留哪些表达方式。",
    "若后续出现愣神、肢体抽动等疑似发作性表现，请及时记录发生时间并尽快告知就诊医生。"
  ],
  "disclaimer": "本系统提供的信息比对与基因知识科普均基于权威医学文献检索生成。本报告仅用于帮助家长梳理日常生活中的前置症状线索，并翻译晦涩的基因术语。本系统不可替代执业医师的面诊，绝不作为任何疾病的确诊结论，亦不提供任何具体的干预或用药建议。强烈建议您携带此信息整理单，前往正规三甲医疗机构的儿童发育行为科及医学遗传科，由专业医生进行最终临床评估。",
  "mcp_translation": "已将 4 条白话描述标准化为 HPO 术语：「总是不停地搓手绞手」-> HP:0000733 (刻板动作)；「1岁半以前会说的词现在都不说了」-> HP:0000750 (语言发育延迟)；「经常无缘无故地笑」-> HP:0000748 (不恰当的笑)；「走路也不太稳」-> HP:0002540 (步态不稳)。基因位点解析结果：MECP2 / c.455C>G (p.Pro152Arg) / VUS。",
  "retrieved_chunks": [
    {
      "bucket": "A",
      "source": "GeneReviews_MECP2",
      "text": "MECP2 相关疾病的典型病程为早期发育基本正常，6 至 18 月龄后出现已获得的语言与手部功能倒退，并伴随搓手、绞手、拍手等特征性手部刻板动作，常合并步态共济失调、后天性小头畸形与呼吸节律异常。"
    },
    {
      "bucket": "A",
      "source": "GeneReviews_Angelman",
      "text": "安格曼综合征由 15q11.2-q13 区域母源 UBE3A 基因表达缺失引起。标志性表现为「快乐木偶」行为（频繁爆发、极易被激惹的大笑和微笑）、明显的步态共济失调（宽基底、手臂高举屈曲）、极高发的癫痫以及严重睡眠节律紊乱；临床上与 ASD 重合于言语功能严重剥夺、刻板行为与重度智力障碍。"
    },
    {
      "bucket": "B",
      "source": "ACMG_VUS_PMID37878314",
      "text": "VUS 极其常见：在进行广泛基因组检测的人群中，高达 41% 的个体都会收到至少一个 VUS 报告。科学实证数据显示，历经平均近三年的重分类过程后，高达 80.2% 的 VUS 最终会被证实为完全无害的良性改变。国际指南严禁临床医生仅仅依据一个 VUS 就对孩子做出激进的医疗干预决策。"
    },
    {
      "bucket": "B",
      "source": "WES_Value_PMID33921431",
      "text": "在伴有复杂躯体症状或癫痫的 ASD 患者中，全外显子测序（WES）是极其重要的确诊工具，诊断率可达 20%-30%。测序的核心目的不是判定绝症，而是精确解释发病机制并据此制定针对性监控方案。"
    },
    {
      "bucket": "C",
      "source": "FDA_NonDeviceCDS_Disclaimer",
      "text": "本系统提供的信息比对与基因知识科普均基于权威医学文献检索生成。本报告仅用于帮助家长梳理日常生活中的前置症状线索，并翻译晦涩的基因术语。本系统不可替代执业医师的面诊，绝不作为任何疾病的确诊结论，亦不提供任何具体的干预或用药建议。强烈建议您携带此信息整理单，前往正规三甲医疗机构的儿童发育行为科及医学遗传科，由专业医生进行最终临床评估。"
    }
  ]
}
```

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
