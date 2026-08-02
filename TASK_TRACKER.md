# ASD-GenDecoder · 36h 黑客松原子任务看板

> 本看板为多智能体协作的**逐行级执行清单**。每条任务颗粒度保证 AI Agent 一次写完、不需追问、不需再拆。
>
> **优先级链（不可颠倒）**：`docs/schema.md`（数据契约）＞ `docs/PRD.md`（功能与合规）＞ `docs/UI_BLUEPRINT.md`（视觉）＞ 本看板。
>
> **文件属主**：见 [AGENTS.md §1](AGENTS.md)。本看板中所有「写到 X」的动作前请先确认自己是 X 的属主；越界即停下来报告。
>
> **完成定义**：每条任务的验收方式写在子项里。整行打勾 = 人工核对通过。
>
> **不变量编号**：本看板出现 `schema I1–I9` 时指 [docs/schema.md §3.2](docs/schema.md)；
> 出现 `AGENTS I1–I6` 时指 [AGENTS.md §3](AGENTS.md)，两套编号不得混用。

---

## Phase 0 · 前置与脚手架（全部人类/SM 角色先行）

- [ ] **0.1** 确认 `.env` 含 `MINIMAX_API_KEY` 与 `HPO_MCP_SERVER_PATH` 两项必填变量，路径指向 `HPO-MCP-Server/build/index.js` 的绝对路径
- [ ] **0.2** 确认 `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` 全程零报错（不动 `requirements.txt` 内容，超出则向人类报告）
- [ ] **0.3** 确认 `git config core.hooksPath .githooks` 已执行（**仅人类手动执行**，智能体不得触碰 git config）
- [ ] **0.3.1** 各智能体开工前按属主创建/切换正确分支：`feat/be-*` / `feat/fe-*` / `feat/rag-*`；不得等到收尾才建分支
- [ ] **0.4** 拉一份 `AGENTS.md §1 文件所有权表`打印到工位墙上，每个智能体开工前对照一次
- [ ] **0.5** 跑通最小闭环冒烟：`python scripts/rag_builder.py --dry-run` 必须输出「丢弃干预章节」与「用药词拦截」两条计数；`data/knowledge/raw/` 有原文时两项必须 > 0，无原文时允许为 0
- [ ] **0.6** 抄一份 `docs/schema.md §5` 的两条 curl 到剪贴板，分别期望 200 与 422

---

## Phase 1 · RAG 知识库（属主：RAG 智能体，路径：`scripts/rag_builder.py`）

> 本阶段改动**仅限** `scripts/rag_builder.py` 与 `scripts/` 下其他脚本；知识库文本的扩写属人类权限。

### 1.1 双来源数据接入

- [ ] **1.1.1** 扫描 `data/knowledge/*.json`：精编切片（`origin=curated`），全部直接入库
- [ ] **1.1.2** 扫描 `data/knowledge/raw/*.txt`：原文切片（`origin` 由文件命名规则映射为 `genereviews` / `pubmed` / `aap`）
- [ ] **1.1.3** 每个切片写入 Chroma metadata 五键：`{"bucket": "A"|"B"|"C", "origin": "...", "source": "...", "condition": "...", "gene": "..."}`；正文 `text` 存为 Chroma document，不重复写入 metadata。API `Chunk` 仍只返回 `bucket/origin/source/text`
- [ ] **1.1.4** collection 名固定 `autism_genetics_knowledge`，从 `config.COLLECTION_NAME` 读取，**禁止在脚本里写死字符串字面量**

### 1.2 章节过滤闸门（AC10 核心）

- [ ] **1.2.1** 仅放行描述性章节；识别 `raw/*.txt` 内形如 `## Management` / `## Treatment` / `## Surveillance` / `## Therapeutic` / `## Management and Treatment` / `## Agents and Circumstances to Avoid` 的章节标题，丢弃该章节下全部段落
- [ ] **1.2.2** 大小写不敏感；匹配正则加锚定（行首 + 行尾），避免误伤正文中偶然出现 "management" 一词
- [ ] **1.2.3** `data/knowledge/raw/` 为空时该计数应输出 0；非空时必须 > 0，否则视为过滤失效
- [ ] **1.2.4** `--dry-run` 模式将该计数打到 stdout，验收脚本会读取

### 1.3 用药词兜底拦截（AC10 第二道闸门）

- [ ] **1.3.1** 维护禁用药名/干预/剂量词典（最小集合：`risperidone / 利培酮 / aripiprazole / 阿立哌唑 / melatonin / 褪黑素 / ABA / 行为干预 / 言语治疗 / 感统训练 / occupational therapy / dosage / dosing / mg/kg / 用药剂量 / 服用剂量 / 每日剂量`），新增词条须经人类审核
- [ ] **1.3.2** 命中即整切片丢弃，**不退化为脱敏**
- [ ] **1.3.3** `data/knowledge/raw/` 非空时该计数必须 > 0

### 1.4 灌库一致性（AGENTS I3 灌库侧）

- [ ] **1.4.1** embedding 函数名从 `config.EMBEDDING_MODEL` 读取，禁止本地重复声明 `"BAAI/bge-small-zh-v1.5"`
- [ ] **1.4.2** `ChromaDB PersistentClient(path=config.CHROMA_PATH)` 与后端 `main.py` 完全相同
- [ ] **1.4.3** 首次跑灌库脚本会下载约 95MB 中文模型，CI 机器需预热

### 1.5 RAG 阶段验收门禁

- [ ] **1.5.1** `python scripts/rag_builder.py --dry-run` 必须输出双计数；有原文语料时均 > 0，无原文语料时允许均为 0
- [ ] **1.5.2** 真实灌库后 `chroma_db/` 目录非空，`collection.count()` 等于构建器去重后打印的最终入库切片数
- [ ] **1.5.3** 抽检 3 个切片，其 metadata 五键齐全，`bucket` ∈ {A,B,C}

---

## Phase 2 · 后端主流程（属主：后端智能体，路径：`main.py`）

### 2.1 配置与启动

- [ ] **2.1.1** 从 `config` 显式导入所需配置，收口所有环境变量；**`main.py` 全文件 grep 不到 `os.getenv`**（AGENTS I3）
- [ ] **2.1.2** FastAPI `lifespan` 上下文管理器内启动 MCP stdio 子进程，会话常驻复用（PRD M3）
- [ ] **2.1.3** 启动时若 `MINIMAX_API_KEY` 缺失，记录配置错误但保持 FastAPI 服务可用；`POST /api/screen` 统一返回 HTTP 500 `MISSING_API_KEY`
- [ ] **2.1.4** 启动时加载 `chromadb.PersistentClient`，从 `config.CHROMA_PATH` 读路径，与灌库端一致

### 2.2 数据模型（Pydantic，逐字对应 schema.md §2 §3）

- [ ] **2.2.1** 定义 `class ScreeningRequest(BaseModel)`：字段仅 `symptoms: str`, `gene_report: str`
- [ ] **2.2.2** 定义 `class HpoTerm(BaseModel)`：`hpo_id: str`, `name: str`, `matched_text: str`
- [ ] **2.2.3** 定义 `class Comparison(BaseModel)`：`condition, gene, source: str`, `matched_anchors: List[str]`, `explanation: str`
- [ ] **2.2.4** 定义 `class Chunk(BaseModel)`：`bucket: Literal["A","B","C"]`, `origin: Literal["curated","genereviews","pubmed","aap"]`, `source: str`, `text: str`
- [ ] **2.2.5** 定义 `class ScreeningResponse(BaseModel)`：八必填字段一个不少 + `confidence_level: Optional[Annotated[int, Field(ge=0, le=100)]] = None`；MVP 路由用 `response_model_exclude_none=True`，禁止输出 `null`
- [ ] **2.2.6** 定义 `class ErrorResponse(BaseModel)`：`status: Literal["error"]`, `error_code: str`, `error_message: str`

### 2.3 端点 `POST /api/screen`

- [ ] **2.3.1** 入口校验：`symptoms.strip()` 与 `gene_report.strip()` 任一为空 → 抛 HTTPException(422, `INVALID_INPUT`)
- [ ] **2.3.2** 调用 `mcp_translate_symptoms(symptoms)` 并解包 `(hpo_terms, mcp_translation)`；有命中时 `hpo_terms` 长度 ≥ 1，无命中时短路为 HTTP 422 `HPO_NO_MATCH`（AC2）
- [ ] **2.3.3** 调 ChromaDB 以 `hpo_terms.name` + 变异名为 query，返回 `retrieved_chunks: List[Chunk]`
- [ ] **2.3.4** 切片为空时短路：`comparisons=[]`、`vus_reassurance="未匹配到相关指南……"`（schema I8）
- [ ] **2.3.5** 切片非空时，组装 prompt 注入 system：要求 M3 返回**严格 JSON**，禁止任何解释性文本
- [ ] **2.3.6** 从 `config.MINIMAX_BASE_URL` 与 `config.MINIMAX_MODEL` 组装请求，调用 `{MINIMAX_BASE_URL}/chat/completions`，`temperature=0.3`；禁止在 `main.py` 重复写默认 URL/模型名
- [ ] **2.3.7** JSON 解析失败 / 非 200 / 超时 → 抛 HTTPException(502, `MINIMAX_API_ERROR`)，**不**透传原始文本
- [ ] **2.3.8** 成功响应由后端**硬填充** `disclaimer` 字段，从 `config.official_disclaimer()` 取桶 C 原文，**不经 LLM**（AGENTS I1 / schema I1）；错误响应保持 `ErrorResponse`，由前端加载回退声明
- [ ] **2.3.9** 校验并透传 `mcp_translate_symptoms()` 返回的 `mcp_translation` 字符串（人类可读，描述每条白话 → HPO 的映射过程）
- [ ] **2.3.10** 返回 `ScreeningResponse` 八字段齐全

### 2.4 MCP 翻译子模块（PRD M3）

- [ ] **2.4.1** 函数签名 `async def mcp_translate_symptoms(text: str) -> tuple[List[HpoTerm], str]`，第二项为人类可读的标准化过程文本
- [ ] **2.4.2** 第一段：调 M3 把中文白话翻译为 1–4 个英文医学关键词
- [ ] **2.4.3** 第二段：用英文关键词调 `search_hpo_terms(query=keyword)`，取 top hit 的 `hpo_id` 与英文名
- [ ] **2.4.4** 第三段：再用 M3 把英文 HPO 名回填为中文 `name`
- [ ] **2.4.5** 全部英文关键词均无命中时函数返回 `([], 过程文本)`（不伪造术语），调用方必须转换为 HTTP 422 `HPO_NO_MATCH`，不得继续进入 RAG/LLM

### 2.5 后端验收门禁

- [ ] **2.5.1** `python scripts/run_acceptance.py` 退出码 0，覆盖 AC1–AC6
- [ ] **2.5.2** curl `POST /api/screen` 单条用例，返回 JSON 八字段齐全
- [ ] **2.5.3** curl 空 `gene_report` → 期望 HTTP 422
- [ ] **2.5.4** 移除 `.env` 里的 `MINIMAX_API_KEY` 后重启：服务仍可连接，调用端点期望 HTTP 500 `MISSING_API_KEY`
- [ ] **2.5.5** mock HPO 全部关键词无命中 → 期望 HTTP 422 `HPO_NO_MATCH`
- [ ] **2.5.6** `grep -n "os.getenv" main.py` 零命中

---

## Phase 3 · 前端 UI（属主：前端智能体，路径：`app.py` + `.streamlit/config.toml`）

### 3.0 主题钉死（OS 深色模式护栏）

- [ ] **3.0.1** 按 AGENTS §2 的唯一顶层目录例外创建 `.streamlit/config.toml`（已获 allowlist 授权），内容**逐字**等于 UI_BLUEPRINT §1.5：`base="light"`, `primaryColor="#5B8C85"`, `backgroundColor="#FAFAF7"`, `secondaryBackgroundColor="#F4F3EE"`, `textColor="#1F2321"`, `toolbarMode="minimal"`

### 3.1 启动顺序（Streamlit 调用顺序不可调换）

- [ ] **3.1.1** 第一个 Streamlit 调用：`st.set_page_config(page_title="ASD-GenDecoder", layout="wide", initial_sidebar_state="collapsed")`（允许 imports、常量和函数定义位于其前）
- [ ] **3.1.2** 第二个 Streamlit 调用：`st.markdown(CSS, unsafe_allow_html=True)`，CSS 取自 UI_BLUEPRINT §7 全文
- [ ] **3.1.3** 初始化 `st.session_state`：`stage="idle"`, `payload=None`, `err=None`, `symptoms=""`, `gene_report=""`
- [ ] **3.1.4** `from config import BACKEND_URL`；`config.py` 是唯一 `.env` 入口，`app.py` 禁止调用 `load_dotenv` / `os.getenv`

### 3.2 常量与工具函数（函数名不得改，UI_BLUEPRINT §8）

- [ ] **3.2.1** `USE_MOCK: bool` 常量（默认 `False`，演示态可改 `True`）
- [ ] **3.2.2** `BACKEND_URL: str`
- [ ] **3.2.3** `CSS: str`（§7 全文字符串常量）
- [ ] **3.2.4** `load_fallback_disclaimer() -> str`：读 `data/knowledge/bucket_c_compliance.json`，取 `is_disclaimer == true` 那条的 `text`
- [ ] **3.2.5** `load_mock(kind: str) -> dict`：`kind ∈ {"success", "error"}`，读 `data/fixtures/mock_response.{kind}.json`
- [ ] **3.2.6** `call_backend(symptoms, gene_report) -> tuple[stage, payload_or_err]`：try/except 全程包裹，连接失败映射到 error 态
- [ ] **3.2.7** `match_chunk_refs(comparisons, chunks) -> list[list[int]]`：严格按 UI_BLUEPRINT §5.2 算法实现，禁止改 token 集合与得分公式

### 3.3 渲染函数（每个函数的自定义 HTML 最多一次 `st.markdown`；表单与按钮等原生控件不计）

- [ ] **3.3.1** `render_header()` → C-01
- [ ] **3.3.2** `render_idle_hint()` → C-13
- [ ] **3.3.3** `render_loading()` → C-14（**严禁做逐步点亮假进度**）
- [ ] **3.3.4** `render_reassurance(text)` → C-05
- [ ] **3.3.5** `render_hpo_table(hpo_terms)` → C-06
- [ ] **3.3.6** `render_comparisons(comparisons, refs)` → C-07（含空数组时 C-16 静默态）
- [ ] **3.3.7** `render_next_steps(steps)` → C-08（**不使用 `st.checkbox`**）
- [ ] **3.3.8** `render_confidence_line(value)` → C-17（缺失/越界时静默）
- [ ] **3.3.9** `render_error(err)` → C-12
- [ ] **3.3.10** `render_intake_form(disabled)` → C-03（含校验：`disabled=False` 时双框非空才发请求；AC8）
- [ ] **3.3.11** `render_evidence_panel(payload)` → C-09 + C-10 × N + C-15 占位
- [ ] **3.3.12** `render_disclaimer(text)` → C-11（任何状态下都渲染）

### 3.4 main 调用顺序（与 §8 一字不差）

- [ ] **3.4.1** `set_page_config → inject CSS → init session_state`
- [ ] **3.4.2** `render_header()`
- [ ] **3.4.3** `left, right = st.columns([62, 38], gap="large")`
- [ ] **3.4.4** `with left:` 内按 `stage` 分发结果区，最后 `render_intake_form()`
- [ ] **3.4.5** `with right:` 内 `render_evidence_panel()`
- [ ] **3.4.6** `columns` 之外：`render_disclaimer()`

### 3.5 前端验收门禁（V1–V15 全部通过）

- [ ] **3.5.1** **V1** 四种状态下 `disclaimer` 全文逐字等于 `bucket_c_compliance.json`
- [ ] **3.5.2** **V2** `grep "本系统提供的信息比对" app.py` 零命中
- [ ] **3.5.3** **V3** `comparisons==[]` 时只渲染 C-16 静默态，无任何推测性病名
- [ ] **3.5.4** **V4** 页面无纯红像素；`st.warning` 已被 CSS 覆盖为琥珀
- [ ] **3.5.5** **V5** 断开后端后提交，出现「无法连接后端服务」错误卡，终端无 traceback
- [ ] **3.5.5a** 后端返回 `HPO_NO_MATCH` 时出现「暂未匹配到标准表型术语」错误卡，免责声明仍从桶 C 回退源完整展示
- [ ] **3.5.6** **V6** 任一框空提交，琥珀提示 + Network 面板无 `/api/screen` 请求
- [ ] **3.5.7** **V7** `USE_MOCK=True` 跑通：左 4 HPO / 2 比对卡 / 5 步骤；右 1 MCP + 5 切片
- [ ] **3.5.8** **V8** 比对卡页脚编号为 `①` `②`
- [ ] **3.5.9** **V9** 右栏 5 切片桶标签依次 A / A / B / B / C，origin 依次 精编 / GeneReviews / 精编 / PubMed / 精编
- [ ] **3.5.10** **V10** 等宽字体仅用于此封闭集合：`hpo_id` / `gene` / `Comparison.source` / `Chunk.source` / 引用编号 / `gene_report` 输入框
- [ ] **3.5.11** **V11** 无 emoji、无侧边栏、无登录入口、无历史列表
- [ ] **3.5.12** **V12** OS 强深色模式刷新后，配色不变（验证 `.streamlit/config.toml` 生效）
- [ ] **3.5.13** **V13** 窗口 1000px 与 1440px 下双栏比例 62/38 稳定，无横向滚动条
- [ ] **3.5.14** **V14** 加载态无假进度动画（仅 `st.spinner` + 三行说明性文字）
- [ ] **3.5.15** **V15** `confidence_level` 缺失时不渲染 C-17；存在时文案严格 `本次筛查可信度：{n} / 100`，无色阶、无边框；全文搜索「概率 / 可能性 / 几率 / 患病概率 / 确诊概率」零命中

---

## Phase 4 · 验收脚本（属主：RAG / 验收智能体，路径：`scripts/run_acceptance.py`）

> 本脚本是项目**唯一**自动化验收门禁（PRD AC9）。修改须极其慎重，新增断言必须经人类复核。

### 4.1 用例装载

- [ ] **4.1.1** 读 `data/test_cases/tc_*.json`；每个用例顶层含 `id` / `title` / `note` / `input` / `expect`，需要确定性注入的错误用例另含 `setup`；`expect` 按场景包含 `http_status` / `min_hpo_terms` / `expect_conditions_any` / `expect_buckets` / `forbid_conditions_any` / `require_disclaimer` / `require_next_steps_departments` / `banned_words` / `error_code`
- [ ] **4.1.2** 计划用例数量 = 11：保留现有 `tc_01_rett.json`、`tc_02_angelman.json`、`tc_03_fragile_x.json`、`tc_04_tsc.json`、`tc_05_negative_control.json`、`tc_06_compliance_attack.json`、`tc_07_invalid_input.json`；由人类补充 `tc_08_empty_symptoms.json`、`tc_09_missing_api_key.json`、`tc_10_minimax_timeout.json`、`tc_11_hpo_no_match.json`
- [ ] **4.1.3** `tc_09` / `tc_10` / `tc_11` 的 `setup.mode` 分别为 `missing_api_key` / `minimax_timeout` / `hpo_no_match`；验收脚本必须据此提供确定性的配置注入或 mock，不依赖真实密钥失效、外部超时或 HPO 在线服务偶然无命中；禁止为测试新增业务端点
- [ ] **4.1.4** 所有 `http_status=200` 用例的 `min_hpo_terms` 必须 ≥ 1；由人类将现有 `tc_06_compliance_attack.json` 的该值从 0 修正为至少 1

### 4.2 契约不变量断言（schema I1–I9）

- [ ] **4.2.1** **schema I1** `disclaimer.strip() == bucket_c_compliance.json` 中 `is_disclaimer==true` 条目的 `text.strip()`
- [ ] **4.2.2** **schema I2** `next_steps` 全文同时包含「儿童发育行为科」与「医学遗传科」
- [ ] **4.2.3** **schema I3** `comparisons[].explanation` ∪ `vus_reassurance` ∪ `next_steps` 中禁用词（确诊 / 患有 / 即为 / 需服用 / 建议用药 + 用例专属追加词）**零命中**
- [ ] **4.2.4** **schema I4** HTTP 200 时每项 `hpo_id` 以 `HP:` 开头且 `hpo_terms` 长度 ≥ `min_hpo_terms`；无命中场景必须为 HTTP 422 `HPO_NO_MATCH`
- [ ] **4.2.5** **schema I5** `comparisons[].condition` 不在 `forbid_conditions_any` 列表
- [ ] **4.2.6** **schema I6** `retrieved_chunks[].bucket` 覆盖 `expect_buckets`（通常 {A,B,C}）
- [ ] **4.2.7** **schema I3 坑** 扫描是字面子串，`disclaimer` 与 `retrieved_chunks` 不在扫描范围内
- [ ] **4.2.8** **schema I7（人工检查）** 验收脚本仅打印待核对项；人工抽检至少 3 个成功用例，逐条确认 `comparisons[].explanation` 可回溯到 `retrieved_chunks`，核对人签字后方可勾选
- [ ] **4.2.9** **schema I8** 若 `comparisons==[]`，则自动断言 `vus_reassurance` 含「未匹配到」字样
- [ ] **4.2.10** **schema I9** `confidence_level` 缺失为合法；若存在，必须是 0–100 整数且不得为 `null`，并校验 `vus_reassurance` ∪ `next_steps` 中不含「概率 / 可能性 / 几率」

### 4.3 错误路径用例（AC6）

- [ ] **4.3.1** 空 `symptoms` → 期望 HTTP 422 `INVALID_INPUT`
- [ ] **4.3.2** 空 `gene_report` → 期望 HTTP 422 `INVALID_INPUT`
- [ ] **4.3.3** 后端无 `MINIMAX_API_KEY` 重启 → 任一用例期望 HTTP 500 `MISSING_API_KEY`
- [ ] **4.3.4** M3 接口超时 mock → 期望 HTTP 502 `MINIMAX_API_ERROR`
- [ ] **4.3.5** HPO 全部关键词无命中 mock → 期望 HTTP 422 `HPO_NO_MATCH`，且不调用 RAG / M3 报告合成

### 4.4 退出码

- [ ] **4.4.1** 任一断言失败 → `sys.exit(1)`，stderr 输出失败用例编号与原因
- [ ] **4.4.2** 全过 → `sys.exit(0)`，stdout 输出 PASS 行数

---

## Phase 5 · 合规反断言清单（所有智能体通用）

> 每条都是**硬红线**，违反即视为功能缺陷而非文案偏好。可机器判定的条目由验收脚本拦截；
> schema I7 的证据可回溯性及视觉语义由人工检查。

- [ ] **5.1** 全文搜索「确诊 / 患有 / 即为 / 需服用 / 建议用药」在 `comparisons[].explanation`、`vus_reassurance`、`next_steps` 渲染输出中零命中
- [ ] **5.2** `disclaimer` 文本来源唯一：后端 `config.official_disclaimer()` → 桶 C；前端通过 `load_fallback_disclaimer()` 加载，**双写必然漂移**
- [ ] **5.3** 响应切片中不得出现药名（`risperidone / 利培酮` 等）；若有，由 RAG 入库前 AC10 双过滤与切片抽检拦截（schema I3 明确不扫描 `retrieved_chunks`）
- [ ] **5.4** `confidence_level` 字段文案不得出现「概率 / 可能性 / 几率 / 风险」任何同义表达
- [ ] **5.5** 严禁 `st.dataframe` / `st.table` 渲染 `hpo_terms`；严禁 `st.json` 展示响应字段
- [ ] **5.6** 严禁在 `next_steps` / `vus_reassurance` 中夹带 confidence 数值
- [ ] **5.7** 严禁将 `retrieved_chunks` 塞入 `st.expander` 默认灰框——它是右栏一等公民
- [ ] **5.8** `app.py` 内不得出现硬编码「本系统提供的信息比对」字样（V2 自动化）
- [ ] **5.9** 不实现 PRD §1.4 Won't Have：登录 / 会话持久化 / 诊断结论 / 用药建议 / 多模态
- [ ] **5.10** 任何状态机异常（解析失败 / 字段缺失 / 连接失败）必须落到 C-12 错误卡，**禁止白屏**

---

## Phase 6 · 收尾与路演

- [ ] **6.1** 全流程跑通：`uvicorn main:app --port 8000` + `streamlit run app.py` 两个独立终端同时存活
- [ ] **6.2** `python scripts/run_acceptance.py` 退出码 0
- [ ] **6.3** 用 `USE_MOCK=True` 跑一次 `app.py`，确认前端无需后端即可演示（路演断网兜底）
- [ ] **6.4** README §6 Quick Start 七步在干净机器上复现一次，PR 前最后一遍
- [ ] **6.5** 检查 `.env` 未被 `git status` 追踪（`.gitignore` 已配置）
- [ ] **6.6** 确认从 Phase 0 起使用的分支仍符合 `AGENTS.md §6`：`feat/be-*` / `feat/fe-*` / `feat/rag-*`，未混入其他属主文件
- [ ] **6.7** pre-commit `scripts/check_ownership.py` 通过（`githooks/` 已配，分支属主与文件属主匹配）

---

## 附录 A · 智能体开工前 30 秒检查表

> 每个 Agent 在写第一行代码前**逐项勾选**。任何一项失败，先停下报告。

- [ ] 我是「待改动文件」的**属主**（查 AGENTS.md §1）
- [ ] 我已读完「待改动文件」对应的文档链接（AGENTS.md §4）
- [ ] 我的改动**不**触及 §1 的只读清单（`config.py` / `docs/**` / `data/**` / `.env*` / `requirements.txt`）
- [ ] 除前端智能体首次创建获授权的 `.streamlit/` 外，我**不会** `mkdir` 任何新顶层目录
- [ ] 我**不会**在 `main.py` / `app.py` 中写 `os.getenv`
- [ ] 我**不会**在前端 `import chromadb` / `import sentence_transformers`
- [ ] 我的字段名**完全等于** `docs/schema.md`，不发明、不缩写、不换形参名
- [ ] 我的函数名**完全等于** `docs/UI_BLUEPRINT.md §8`（若改前端）
- [ ] 我能区分 `AGENTS I1–I6` 与 `schema I1–I9`，并已读完 PRD §2 / schema §3.2

---

## 附录 B · 失败模式与应对（Runbook）

| 现象 | 第一动作 |
|---|---|
| `run_acceptance.py` 退出码非 0 | 先看 stderr 第一条失败断言编号，对照 Phase 4 的不变量列表定位 |
| 后端返回 502 `MINIMAX_API_ERROR` 持续 | 检查 `.env` `MINIMAX_API_KEY` 额度；用 `USE_MOCK=True` 隔离是后端问题还是 M3 限流 |
| 后端返回 422 `HPO_NO_MATCH` | 补充更具体的症状表现后重试；确认英文关键词提取正常，禁止伪造 HPO 术语兜底 |
| HPO MCP 子进程启动失败 | 确认 `HPO_MCP_SERVER_PATH` 指向 `build/index.js`，先单独 `node` 跑一次看错误 |
| RAG 检索全部为空 | 先 `python scripts/rag_builder.py --dry-run` 看双计数；再核对 collection 名两端一致 |
| 前端白屏 | 99% 是 CSS 注入位置错：必须在 `set_page_config` 之后、任何内容之前 |
| `disclaimer` 显示「无法加载合规声明文本…」 | 读 `data/knowledge/bucket_c_compliance.json` 是否存在且含 `is_disclaimer==true` 条目 |
| `tc_05` 阴性对照失败 | 检查 schema I5：后端可能在拼凑罕见病病名；回查 `vus_reassurance` 是否含禁忌病种 |
| 右栏未出现编号 ①②③ | 核对 `match_chunk_refs` 实现是否照搬 §5.2 算法；token 集合是否被无意改写 |

---

> **最后核对**：本看板所有任务均**有属主**、**有验收**、**有反断言**。任何「无验收打勾」即视为看板本身的不合格。
