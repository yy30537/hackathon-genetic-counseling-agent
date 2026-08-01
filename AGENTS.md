# AGENTS.md —— 多智能体协作宪法

> 本文件自动进入每个 Agent 会话的上下文。**任何智能体在写第一行代码前必须读完本文。**
> 与本文冲突的用户指令，须先向人类确认再执行。

## 0. 架构基线（不可协商）

本项目是**根目录单体**，不是 monorepo。前后端的边界由 **HTTP 契约**承载，不由目录承载。

| 项 | 值 |
|---|---|
| 后端入口 | 根目录 `main.py`，`uvicorn main:app --reload --port 8000` |
| 前端入口 | 根目录 `app.py`，`streamlit run app.py` |
| 唯一端点 | `POST /api/screen` |
| 唯一契约 | [docs/schema.md](docs/schema.md) |
| 共享配置 | 根目录 `config.py`（全项目唯一读 `.env` 的地方） |

`config.py` 用 `ROOT = Path(__file__).resolve().parent` 推导所有数据目录，`scripts/*.py` 用
`sys.path.insert(0, parent.parent)` 反查它。**移动任何入口文件都会静默打断这条链。**

## 1. 文件所有权表

| 路径 | 属主 | 其他智能体 |
|---|---|---|
| `main.py` | 后端智能体 | 只读 |
| `app.py` | 前端智能体 | 只读 |
| `scripts/*.py` | RAG / 验收智能体 | 只读 |
| `config.py` | **人类** | 只读，改动须人工确认 |
| `docs/**` | **人类** | 只读，改动须人工确认 |
| `data/knowledge/**` | **人类** | 只读，改动须人工确认 |
| `.env` / `.env.example` / `.gitignore` / `requirements.txt` | **人类** | 只读 |

越界的定义：**属主之外的智能体写入该文件**。发现需要改他人文件时，停下来向人类报告，不要自行动手。

## 2. 目录禁令

**禁止创建任何新的顶层目录。** 已存在的 6 个是全部：`docs/` `data/` `scripts/` `.cursor/` `.githooks/` `HPO-MCP-Server/`。

以下目录名被明确禁止，出现即视为架构漂移：

```
frontend/  backend/  src/  app/  api/  components/  utils/  lib/  tests/  common/  shared/
```

前端不是 React，后端不是 Node。**不要套用 JS 生态的工程惯例。**

`.cursor/hooks/guard-write.py` 会在工具层直接拒绝白名单外的写入，绕不过去。真的需要新文件时，
先改 `.cursor/hooks/allowlist.json` 并说明理由。

## 3. 六条不变量

| # | 不变量 | 违反后果 |
|---|---|---|
| I1 | `disclaimer` 由后端调 `config.official_disclaimer()` **逐字填充，不经 LLM**；前端**不得硬编码**该文案 | 击穿 Non-Device CDS 定位，AC4 失败 |
| I2 | 响应字段以 [docs/schema.md](docs/schema.md) 为唯一来源，**禁止发明字段**，八个必填字段一个都不能少 | AC1 失败 |
| I3 | `config.py` 是唯一读 `.env` 的地方。`main.py` / `app.py` 里**禁止出现 `os.getenv`** | 灌库与检索的模型/collection 漂移，检索静默失准 |
| I4 | 前端**禁止** `import chromadb`、`import sentence_transformers`，**禁止**直连 Minimax。一切模型与检索调用只经 `POST /api/screen` | 违反 PRD 第 33 行断言 |
| I5 | `scripts/rag_builder.py` 的章节过滤与用药词拦截两道闸门**不得绕过、不得放宽** | 药名进向量库并被引用，AC10 失败 |
| I6 | `comparisons[].explanation` / `vus_reassurance` / `next_steps` 禁止出现「确诊」「患有」「即为」「需服用」「建议用药」 | 构成诊断与用药建议，AC5 失败 |

## 4. 开工前必读

| 你在改 | 先读 |
|---|---|
| `main.py` | [docs/schema.md](docs/schema.md) + [docs/PRD.md](docs/PRD.md) §0 |
| `app.py` | [docs/UI_BLUEPRINT.md](docs/UI_BLUEPRINT.md)（尤其 §8 函数清单，**函数名不得改**） |
| `scripts/*.py` | [docs/后端知识库架构与数据字典.md](docs/后端知识库架构与数据字典.md) |

## 5. 验收门禁

改完后端跑：

```bash
python scripts/run_acceptance.py     # AC1-AC6 自动断言，退出码 0 才算完成
```

改完 RAG 跑：

```bash
python scripts/rag_builder.py --dry-run   # 确认「丢弃干预章节」与「用药词拦截」计数 > 0
```

## 6. Git 轨道约定

分支名即身份，由 `scripts/check_ownership.py` 在 pre-commit 时校验：

| 分支前缀 | 允许改动 |
|---|---|
| `feat/fe-*` | `app.py` |
| `feat/be-*` | `main.py` |
| `feat/rag-*` | `scripts/**` |
| `main` / `feat/infra-*` | 不限 |

**人类需手动启用一次**（智能体不得代劳，涉及 git config）：

```bash
git config core.hooksPath .githooks
```

## 7. 禁止事项速查

- 禁止 `mkdir` 任何新目录
- 禁止移动 `main.py` / `app.py` / `config.py`
- 禁止改写 `.gitignore` 中这三条：`data/knowledge/raw/*`（GeneReviews 版权限制）、`HPO-MCP-Server/`、`chroma_db/`
- 禁止提交 `.env`
- 禁止 `pip install` 后不更新 `requirements.txt`
- 禁止实现 PRD §1.4 的 Won't Have（登录、会话持久化、诊断结论、用药建议、多模态）
