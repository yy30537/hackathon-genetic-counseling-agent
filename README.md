
# 🧬 垂直自闭症辅助问诊 AI Chatbot (MVP)

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
> *   👉 [点击查看《后端知识库架构与数据字典 (MCP & RAG)》](./docs/后端知识库架构与数据字典.md)
> *   👉 [点击查看《竞品分析与深度市场调研报告》](./docs/market-research.md)

## 👤 4. 目标用户与极简旅程 (User Journey)

**目标画像：** 手持基因测序报告、发现孩子有发育异常，且处于高焦虑状态的家长。

**无分叉的极简交互流 (The Straight Line)：**
1.  **双输入 (Input)：** 用户输入“大白话异常症状描述” + 上传“基因分析报告 (VUS片段)”。
2.  **黑盒处理 (Process)：** MCP 标准化翻译 -> RAG 指南检索与比对 -> 提取科普安抚话术。
3.  **单输出 (Output)：** 生成一份结构化的《症状与基因筛查比对报告》，附带强警示性免责声明与明确的专科复诊建议。

## 🛠️ 5. 核心技术栈 (Tech Stack)

*   **LLM API:** Minimax M3 (核心自然语言理解与生成)
*   **Frontend:** Streamlit (极速构建响应式 Chatbot UI)
*   **Vector DB:** ChromaDB (本地轻量级 RAG 知识检索)
*   **Development Tools:** Cursor IDE + 内置 Agent (AI 辅助极速开发)
*   **Medical Ontology:** HPO (Human Phenotype Ontology) API

## 🚀 6. 快速启动 (Quick Start)

在本地环境中运行此 MVP 需确保已安装 Python 3.9+ 环境。

```bash
# 1. 克隆项目仓库
git clone [https://github.com/your-repo/autism-ai-screener.git](https://github.com/your-repo/autism-ai-screener.git)
cd autism-ai-screener

# 2. 安装依赖包
pip install -r requirements.txt

# 3. 配置环境变量 (Minimax API Key)
# 请在根目录下创建 .env 文件，并填入以下内容：
# MINIMAX_API_KEY=your_api_key_here

# 4. 启动应用
streamlit run app.py


