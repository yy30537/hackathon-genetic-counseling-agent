# 前后端交接：Phase 3 前端收尾 + Phase 5/6 前端项验收

> 作者：backend agent（在 `feat/be-mcp-rag-llm` 分支上交完后端 Phase 2 后写的）
> 接收人：frontend agent（`feat/fe-*` 分支，对 `app.py` + `.streamlit/config.toml` 负全责）
> 适用版本：`/Users/woshiwudidianhuodawang/Desktop/hackathon-genetic-counseling-agent`
> 阅读前提：本仓库 `app.py` 仍是 Phase 0 的骨架（170 行，`CSS=""`，所有 `render_*` 都是 `# TODO`），`.streamlit/config.toml` 也未创建。本文档不是 "TODO 复述"，而是把后端在 Phase 2 锁死的契约与 Phase 5 反断言留给前端的几条具体事项落到文件层面。

---

## 1. 你需要先读懂的 4 份文件（顺序不要乱）

| 文件 | 用途 | 跳读优先级 |
|---|---|---|
| [docs/schema.md](./schema.md) | 后端响应结构 + 错误码表（HTTP 200 / 422 / 500 / 502 各自的 `error_code`） | ⭐⭐⭐ |
| [docs/UI_BLUEPRINT.md](./UI_BLUEPRINT.md) | §1.5 主题、§3 状态机、§4 字段→组件映射、§5 引用编号算法、§6 组件规格 C-01..C-17、§7 完整 CSS、§8 函数清单（**函数名不得改**） | ⭐⭐⭐ |
| [docs/PRD.md](./PRD.md) §0 / §1.4 / §3 | 后端硬约束 + Won't Have（W1-W5）边界 | ⭐⭐ |
| [TASK_TRACKER.md §3 Phase 3 / §5](../TASK_TRACKER.md) | 前端 sub-task 3.0.1–3.5.15（V1-V15 视觉验收清单） | ⭐⭐ |

**严禁**先看 `app.py` 的现有骨架并按它写 — 骨架是你要**替换**的对象，不是范本。

---

## 2. 后端 Phase 2 锁死的契约（你直接对接的部分）

```text
POST /api/screen
Content-Type: application/json
Body: {"symptoms": str, "gene_report": str}

200: {status, hpo_terms[], comparisons[], vus_reassurance, next_steps[],
      disclaimer, mcp_translation, retrieved_chunks[], confidence_level?}
422 INVALID_INPUT   / 422 HPO_NO_MATCH
500 MISSING_API_KEY / 502 MINIMAX_API_ERROR
错误体统一 {status:"error", error_code, error_message}
```

完整字段定义 + Literal 类型见 [docs/schema.md §3](./schema.md)。

`confidence_level`：**MVP 阶段后端不会输出该字段**（`response_model_exclude_none=True` 在 main.py:764 钉死）。前端 `render_confidence_line` 在字段缺失时必须**整行静默不渲染**（per UI_BLUEPRINT §6.17）。

错误响应的关键是——**没有 `disclaimer` 字段**。前端的兜底声明一律走 `load_fallback_disclaimer()`，从桶 C 原文取（per UI_BLUEPRINT §3「回退文案源」）。

---

## 3. Phase 5 后端 agent 已经验证、可标 ✅ 的事

### 5.1 禁用词零输出（PASS · 后端）
- main.py 内 6 处「确诊」全部位于：a) system prompt 的「禁止规则」；b) `_sanitize_explanation()` 兜底替换。**0 处将禁用词作为输出文本**。
- 验收脚本 `scripts/run_acceptance.py:65-72` 实际扫描 `comparisons[].explanation ∪ vus_reassurance ∪ next_steps`，**豁免** `disclaimer` 与 `retrieved_chunks`（per schema I3 坑）。

### 5.2 disclaimer 唯一来源（PASS · 后端）
- `main.py:799` 单点 `disclaimer=official_disclaimer()`。
- 整份 main.py 0 处硬编码"本系统提供的信息比对"。
- `config.py:55` 单一读桶 C；`scripts/run_acceptance.py:22,56` 复用同一函数比对。

### 5.3 RAG 切片无药名 / schema I3 豁免边界（PASS · 后端 + **警示给你**）
- ChromaDB 内 165 条切片做 18 个药名扫描 = **0 命中**。
- 禁用诊断措辞 3 条命中，全部位于 schema I3 豁免范围：
  - `bucket_c` 免责原文 1 条（这是"法定免责"，不该改）
  - `bucket_b "VUS 绝不是确诊书"` 1 条
  - `bucket_a` 描述 WES 诊断能力的医学常识段 1 条
- **给你的警示**：`render_evidence_panel` 的 C-10 ChunkCard 可以正常显示这三段（它们在 `retrieved_chunks[i].text`），但**绝不能把桶 B 的"VUS 绝不是确诊书"复制粘贴进 `vus_reassurance` 字段**。一旦这么干，验收脚本扫描 `vus_reassurance` 时命中"确诊" → AC5 失败。

### 5.4 confidence_level 用词护栏（PASS · 后端 + 给你警示）
- 后端全程 0 命中「概率 / 可能性 / 几率 / 患病概率 / 确诊概率 / 发病概率」。
- MVP 后端不输出该字段，所以前端**根本不会渲染 C-17**。等你 Phase 3 收尾时也要保留这种「字段缺失 → 静默」的语义，不要主动渲染占位文案。

### 5.6 confidence 数值禁夹带（PASS · 后端）
- main.py `_synthesize_report_async` / `_extract_*` 整段未拼接任何具体数字到 vus/next_steps。
- 前端若是 Stage="success" 取出 `payload["next_steps"]` 渲染——里面**绝对没有"78 / 100"这种字符串**，你别自己加。

### 5.9 W1-W5 Won't Have 五项零命中（PASS · 全部）
- W1 登录注册 = 0 命中
- W2 会话持久化 = 0 命中
- W3 诊断结论 = 仅 main.py 禁止规则 + RAG 章节标题白名单命中（合规）
- W4 患者数据落库 = 0 命中
- W5 多模态 = 0 命中

### 5.10 后端半边（PASS · 后端）
- 所有错误路径都走 `ScreeningError` → `exception_handler` 收口为统一 `ErrorResponse`。
- **后端永远不会向客户端返回非结构化错误或崩溃**。前端拿到 4xx/5xx 一定是合规的 `{status, error_code, error_message}`。

---

## 4. 你（frontend agent）需要做的三件事（在 5.5 / 5.7 / 5.8 / 5.10 前端半边）

### 4.1 实现完整的 `app.py`（§8 函数清单 1 个不能改）
- 严格按 [UI_BLUEPRINT.md §8](./UI_BLUEPRINT.md) 的 16 个函数名 + 调用顺序写。
- `CSS` 常量**逐字**等于 §7 全文（不要重新发明样式类、不要引入外部 `@import`）。
- **`call_backend(symptoms, gene_report) -> tuple[stage, payload_or_err]` 必须全程 `try/except`**，把连接失败、超时、非 200、JSON 解析失败四种异常都映射成 `("error", {...})`。UI_BLUEPRINT §0 硬约束。**禁止白屏，禁止把 traceback 打到页面**。

### 4.2 创建 `.streamlit/config.toml`
按 [UI_BLUEPRINT.md §1.5](./UI_BLUEPRINT.md) 全文：
```toml
[theme]
base = "light"
primaryColor = "#5B8C85"
backgroundColor = "#FAFAF7"
secondaryBackgroundColor = "#F4F3EE"
textColor = "#1F2321"

[client]
toolbarMode = "minimal"
```
**逐字相等**，任何色值偏差都会击穿 §1.1 设计令牌表。

### 4.3 C-12 错误卡兜底（5.10 前端半边）
错误态四码映射（[UI_BLUEPRINT.md §6.12](./UI_BLUEPRINT.md)）：
```text
INVALID_INPUT    → 标题：输入还需要补全
HPO_NO_MATCH     → 标题：暂未匹配到标准表型术语
MISSING_API_KEY  → 标题：后端缺少模型密钥
MINIMAX_API_ERROR→ 标题：模型服务暂时不可用
连接失败/超时    → 标题：无法连接后端服务
其他             → 标题：请求失败
```
任何异常都要落到 C-12（**禁止白屏**），并且底部保留"重试"按钮 + `session_state` 里的输入值。

---

## 5. Phase 6 前端收尾要落实的 6 件事

| 序号 | 事项 | 验证 |
|---|---|---|
| 1 | `python scripts/run_acceptance.py` 退出码 0（要先把 PID 27718 的 uvicorn kill 掉，给端口 8000 让位） | shell 看退出码 |
| 2 | `streamlit run app.py` 启动后 4 种状态下 disclaimer 都逐字等于桶 C | 浏览器肉眼 / `grep "本系统提供的信息比对" app.py` = 0 |
| 3 | `USE_MOCK=True` 切换后左 4 HPO / 2 比对卡 / 5 步骤；右 1 MCP + 5 切片 | V7 自验 |
| 4 | 比对卡页脚编号 = `①` `②`，与 §5.3 期望一致 | V8 |
| 5 | `confidence_level` 缺失时左栏不渲染 C-17 | V15 |
| 6 | OS 深色模式刷新配色不变（验证 config.toml 生效） | V12 |

---

## 6. 一个**会被你踩到**的隐患

`PID 27718` 在 127.0.0.1:8000 上跑着上一会话残留的旧版 backend（即 Phase 2 之前的 uvicorn）。**sandbox 内的 agent 没法 kill 它**。**前端 `app.py` 的 `BACKEND_URL` 默认 `http://127.0.0.1:8000`**——也就是说前端启动后，实际打交道的是 PID 27718 的僵尸进程。

**它在响应 `/api/screen` 时仍能跑通 schema，但它**响应的是**它内存里的旧版本 main.py**（不带 `/healthz`，不带 `_m3_chat` 三段式 M3 调用，不带 `ScreenError` 的双错误码映射）。

**表现**：你的前端一打开，左栏可能出现 502 / 错误卡 / 不一致字段——而 backend agent 的 `main.py` 是好的。

**解决**（在你自己 shell 里）：
```bash
lsof -nP -iTCP:8000  # 应输出 PID 27718
kill 27718           # 释放端口
# 然后再正常启动
source .venv/bin/activate
uvicorn main:app --port 8000 &
streamlit run app.py
python scripts/run_acceptance.py
```

任何情况下**不要**改 `.env` 里的 `BACKEND_URL=http://127.0.0.1:8000`——它属于 `data/**` / `.env*` 人类属主。

---

## 7. 你交付时，应当给验收 agent 留的钩子

Phase 4 验收 agent（`scripts/run_acceptance.py` 属主）需要把 tc_06 / tc_09 / tc_10 / tc_11 跑通。后端已经把 env-var hook 留好了：

```bash
HPO_FAKE_MODE=hpo_no_match      # tc_11 → 422 HPO_NO_MATCH
HPO_FAKE_MODE=missing_api_key   # tc_09 → 500 MISSING_API_KEY
M3_FAKE_MODE=minimax_timeout    # tc_10 → 502 MINIMAX_API_ERROR
```

这些环境变量由 main.py:94 `apply_acceptance_setup()` 在端点入口读取，验收脚本只需在 spawn uvicorn 时设上即可。**你前端不需要再改任何东西**。

但如果你看到验收脚本说"无法连接后端"，先排查 PID 27718 是不是还在占着 8000。

---

## 8. Phase 5 反断言清单里你（前端）必须自验的项目

```text
5.5  grep -nE "st\.(dataframe|table|json)\b" app.py   → 0 命中
5.7  retrieved_chunks 必须渲染到 C-09/C-10 卡片，
     不得用 st.expander 默认灰框                   → 视觉自验 + grep
5.8  grep "本系统提供的信息比对" app.py             → 0 命中
5.10 连接失败/超时/解析错误全落入 C-12 卡          → 视觉自验 + 把后端 kill 掉一次验证
```

骨架上这四项目前 0 命中只是因为函数体还是 `# TODO`——不构成已合规证据。等你写完 render_* 后**重新跑这四项**，才是真正的合规证据。

---

## 9. 你不动的东西（属主边界，AGENTS.md §1）

- `main.py` ← backend 属主，已就绪
- `scripts/rag_builder.py` ← RAG 属主，已就绪
- `scripts/run_acceptance.py` ← RAG/验收属主，不要动；tc_09/10/11 接入由验收 agent 自己处理
- `config.py` ← 人类属主
- `.env` / `.env.example` ← 人类属主
- `data/**` ← 人类属主
- `docs/**` ← 人类属主（除 `docs/HANDOFF_FRONTEND_AGENT.md`，这个文档是交接凭证，不算扩展规范）
- `requirements.txt` ← 人类属主

---

> **最后核对**：写完 `app.py` + `.streamlit/config.toml` 后请按本文件第 8 节跑一遍静态扫描 + 第 4 节跑一遍手动验收。任何一项红 → 该会话内自修；多会话协作失败 → 升格给人类协调。
