
# 🧬 垂直自闭症辅助问诊 AI Chatbot (MVP)

产品名称：ASD-GenDecoder (ASD 基因解码器)
产品名称备选：AutisMap (Autism 自闭症 + Map 导航图)

标语 (Slogan)：

“让晦涩的基因报告说人话，终结自闭症的诊断漫游。” / “精准定位自闭症与罕见基因病的边界。”

> 一款专为自闭症 (ASD) 及高相似度基因病设计的 AI 筛查与基因报告解读工具。

![Hackathon MVP](https://img.shields.io/badge/Status-Hackathon_MVP-brightgreen)
![LLM](https://img.shields.io/badge/Model-Minimax_M3-blue)
![Frontend](https://img.shields.io/badge/UI-Streamlit-red)

## 📌 1. 破题与核心痛点 (The Problem)

在面对“遗传病筛查与科普”这一宏大命题时，我们选择放弃大而全的泛医疗工具，像手术刀一样精准切入 **自闭症 (ASD) 与罕见单基因病** 这一极度垂直的交叉领域。

*   **表型极其相似，极易误诊：** 自闭症发病率已达 1/36，但部分罕见单基因病（如脆性 X 综合征、安格曼综合征）在早期症状上与自闭症高度重合，传统的“诊断漫游”往往耗时数月甚至数年。
*   **基因报告带来的极度恐慌：** 大量患儿家长在拿到全外显子测序 (WES) 报告时，面对晦涩的 **VUS（临床意义未明变异）** 处于极度信息不对称与焦虑中。

## 🎯 2. 产品定位与解决方案 (Our Solution)

本项目定位于一款 **“就诊前置信息整理与科普工具”**。我们将碎片化的行为症状与晦涩的基因测序片段相映射，为家长提供客观的比对报告与就诊建议。

**🛡️ 核心合规护栏 (Non-Device CDS)：**
本项目严格遵循 FDA 关于“非医疗器械临床决策支持”的豁免标准。系统不提供任何诊断结论或用药建议，仅作为“专业医学指南的搬运工与翻译官”，最终决策权完全交还给专科医生。

## 🧠 3. 核心架构：MCP + RAG 双轨制

为了在医疗领域彻底消除大模型的“幻觉”，我们对底层系统进行了硬核划界：

*   **🎙️ MCP (动态翻译官)：** 接入 HPO（人类表型本体）API。负责将家长口语化的“孩子整天傻笑”，瞬间标准化翻译为 `HP:0000748 (不恰当的笑)`。
*   **📚 RAG (权威教科书)：** 基于 ChromaDB 搭建。负责根据标准化症状去查阅内置的 AAP (美国儿科学会) 和 GeneReviews 最新临床指南，严格照本宣科输出。

> **📖 详细项目文档导航：**
> *   👉 [《产品需求文档 (PRD)》](./docs/PRD.md) —— 功能优先级、验收标准与合规红线
> *   👉 [《API 数据契约》](./docs/schema.md) —— 前后端唯一事实来源，动手写代码前必读
> *   👉 [《环境搭建指南》](./docs/env-setup.md) —— 从虚拟环境到全链路跑通的完整步骤
> *   👉 [《后端知识库架构与数据字典 (MCP & RAG)》](./docs/后端知识库架构与数据字典.md)
> *   👉 [《data/ 数据资产地图》](./data/README.md) —— 语料、测试用例与前端 Mock 的分工
> *   👉 [《竞品分析与深度市场调研报告》](./docs/market-research.md)

## 👤 4. 目标用户与极简旅程 (User Journey)

**目标画像：** 手持基因测序报告、发现孩子有发育异常，且处于高焦虑状态的家长。

**无分叉的极简交互流 (The Straight Line)：**
1.  **双输入 (Input)：** 用户输入“大白话异常症状描述” + 粘贴“基因分析报告 (VUS片段)”文本。
2.  **黑盒处理 (Process)：** MCP 标准化翻译 -> RAG 指南检索与比对 -> 提取科普安抚话术。
3.  **单输出 (Output)：** 生成一份结构化的《症状与基因筛查比对报告》，附带强警示性免责声明与明确的专科复诊建议。

## 🛠️ 5. 核心技术栈 (Tech Stack)

*   **LLM API:** Minimax M3 (核心自然语言理解与生成)
*   **Frontend:** Streamlit (极速构建响应式 Chatbot UI)
*   **Vector DB:** ChromaDB (本地轻量级 RAG 知识检索)
*   **Development Tools:** Cursor IDE + 内置 Agent (AI 辅助极速开发)
*   **Medical Ontology:** HPO (Human Phenotype Ontology) API

## 🚀 6. 快速启动 (Quick Start)

需要 Python 3.9+ 与 Node.js 18+（后者用于 HPO-MCP-Server）。完整说明见 [docs/env-setup.md](./docs/env-setup.md)。

```bash
# 1. 克隆项目仓库
git clone https://github.com/your-repo/autism-ai-screener.git
cd autism-ai-screener

# 2. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 搭建 HPO-MCP-Server（未纳入本仓库，需自行 clone 并编译）
git clone https://github.com/Augmented-Nature/HPO-MCP-Server.git
cd HPO-MCP-Server && npm install && npm run build && cd ..
# 记下 HPO-MCP-Server/build/index.js 的绝对路径，下一步要填

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入两项必填变量：
#   MINIMAX_API_KEY      —— Minimax 控制台生成，形如 sk-cp-...
#   HPO_MCP_SERVER_PATH  —— 上一步 build/index.js 的绝对路径

# 6. 构建 RAG 向量库（首次运行会下载约 95MB 的中文向量模型）
python scripts/rag_builder.py

# 7. 启动后端
uvicorn main:app --reload --port 8000

# 8. 另开一个终端，激活同一虚拟环境后启动前端
source .venv/bin/activate
streamlit run app.py
```

启动后可选做一次验收自检，它会把 [data/test_cases/](./data/test_cases/) 下的 7 个用例逐条打给后端，校验字段完整性、免责声明与合规红线：

```bash
python scripts/run_acceptance.py
```

> **注意**：第 7、8 步是**两个独立进程**，需各占一个终端。前端只做渲染，所有 MCP、RAG 与大模型调用都发生在后端。

