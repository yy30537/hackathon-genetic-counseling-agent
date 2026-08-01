# Prompt: 生成前后端数据契约 (API Schema) 与 Mock 数据

> 用途：交给并发开发中的后端智能体执行，产出 `docs/schema.md` 与 `data/fixtures/mock_response.success.json`。
> 直接复制下方 `<Role>` 到最后一行使用。

---

<Role>
你是一名拥有极高工程素养的首席后端架构师。
</Role>

<Context>
我们正在进行 36 小时的 AI 黑客松，团队采取“多智能体并发开发”模式（前端与后端同时开工）。
后端的指定技术栈为：Python + FastAPI。
我们的核心开发原则是 Contract-First（契约先行）。前端和后端的 AI 智能体将以此契约为唯一标准进行平行的自动代码生成。
产品为 ASD-GenDecoder：面向手持基因测序报告、发现孩子发育异常且处于高焦虑状态的家长，提供“就诊前置信息整理与科普”。严格遵循 FDA Non-Device CDS 豁免标准，不诊断、不定性、不开药。
</Context>

<Input>
请读取项目文件：@docs/PRD.md @docs/后端知识库架构与数据字典.md @README.md
</Input>

<Task>
请不要输出任何业务逻辑代码（禁止实现 RAG 检索、MCP 调用、LLM 请求等函数体）。
例外豁免：允许且鼓励输出 Pydantic `BaseModel` 的字段声明，它属于契约本身而非业务逻辑。

你的任务是根据 PRD 中的“Must Have 核心回路”和“Entity Flow”，定义出极其严谨的 RESTful API 接口契约，并输出为一份 `docs/schema.md` 文档。
</Task>

<Constraints>
以下为不可协商的既定约束，直接采用，禁止自行发明替代方案：

1. 路由锁定为 `POST /api/screen`。禁止使用 `/api/v1/analyze` 等任何其他路径或版本前缀。
2. 请求字段锁定为 `symptoms` 与 `gene_report`，均为 String 且 Required。禁止重命名。
3. 错误契约以 HTTP 状态码为准：成功返回 200，失败返回 4xx/5xx，不使用“一律 200 + status 字段”的信封模式。
4. 扁平化约束仅适用于 Request（Request 必须是单层扁平结构）。Response 允许一层“数组套简单对象”，以承载 HPO 术语表与比对结果，禁止再深一层嵌套。
5. `disclaimer` 字段由后端从知识库数据桶 C 直接取原文填充，不经大模型生成。契约中必须将其标注为 Required 且内容固定。
6. 报告正文必须结构化拆分为独立字段，禁止把大段 Markdown 塞进单一 `content` 字段。
</Constraints>

<Output>
文件名称：`docs/schema.md`
请严格遵循以下结构输出（文档内需包含接口定义及 JSON 代码块）：

## 1. API 路由定义 (Endpoint)
- Path: `POST /api/screen`
- Method: POST
- Description: 用一句话概括这个接口的作用，强调它是串联 MCP 标准化、RAG 检索与大模型生成的唯一核心节点。

## 2. 请求数据结构 (Request Schema)
前端发给后端的 JSON 结构，对应 Pydantic 模型 `ScreeningRequest`。
- 必须单层扁平，无嵌套。
- 明确标注每个字段的类型（String / Int / Boolean 等）与是否必填（Required）。
- 字段：`symptoms`（家长白话症状描述）、`gene_report`（基因测序报告或 VUS 片段）。

## 3. 成功响应数据结构 (Success Response Schema, HTTP 200)
对应 Pydantic 模型 `ScreeningResponse`。大模型的返回结果必须被严格结构化，至少包含以下字段，逐个标注类型与是否必填：

- `status`: String，固定为 `"success"`。
- `hpo_terms`: Array of Object，MCP 标准化结果。每项含 `hpo_id`（形如 `HP:0000733`）、`name`、`matched_text`（对应家长原话片段）。
- `comparisons`: Array of Object，症状与基因的鉴别比对结果。每项含 `condition`（疾病名）、`gene`、`matched_anchors`（Array of String，命中的鉴别锚点）、`explanation`（客观描述，禁止确诊措辞）、`source`（文献来源，如 GeneReviews）。
- `vus_reassurance`: String，来自数据桶 B 的 VUS 降维安抚话术。
- `next_steps`: Array of String，就诊建议清单，必须包含儿童发育行为科与医学遗传科。
- `disclaimer`: String，Required，数据桶 C 免责声明逐字原文，后端硬编码填充。
- `mcp_translation`: String，MCP 标准化过程的原始输出，供前端调试面板展示。
- `retrieved_chunks`: Array of Object，RAG 命中切片。每项含 `bucket`（"A"/"B"/"C"）、`source`、`text`。

## 3.1 错误响应数据结构 (Error Response Schema)
以 HTTP 状态码承载错误语义，响应体统一为：`{ "status": "error", "error_code": String, "error_message": String }`。
请以表格列出以下三种错误的 HTTP 状态码、`error_code` 与触发条件：
- `INVALID_INPUT`：`symptoms` 或 `gene_report` 为空。
- `MISSING_API_KEY`：后端未读取到 `MINIMAX_API_KEY`。
- `MINIMAX_API_ERROR`：Minimax 接口返回非 200 或超时。

## 4. 前端救命稻草：逼真的 Mock JSON 数据
这是最重要的一步，前端的 AI 智能体现在立刻就需要拿着假数据去生成 UI 组件。

- 输出一段极其逼真、完全符合第 3 节 Schema 的成功态 JSON 代码块，并同时将该 JSON 原样落盘为独立文件 `data/fixtures/mock_response.success.json`（前端可直接 `json.load` 读取）。
- 额外输出一段错误态 JSON 代码块（以 `MINIMAX_API_ERROR` 为例）。
- Mock 必须使用以下固定情境，绝对禁止 "test"、"foo" 这类无意义占位符：
  - 患儿：3 岁男童。
  - 家长白话描述：出生后发育正常，约 1 岁半后会说的词逐渐消失；最近半年总是不停地搓手、绞手；经常无缘无故地笑；走路不太稳。
  - 基因报告：全外显子测序 (WES) 检出 `MECP2` 基因错义变异，临床意义未明 (VUS)。
- `hpo_terms` 至少 3 项，`comparisons` 至少 2 项（其一为 Rett 综合征，另一项为需要排除的鉴别项），`retrieved_chunks` 至少 3 项且覆盖桶 A/B/C。
- 所有文案的语气必须温和、客观、贴近真实大模型输出，且严禁出现“确诊”“患有”“即为”“需服用”“建议用药”等措辞。
</Output>
