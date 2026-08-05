# ASD-GenDecoder（ASD 基因解码器）

> 帮手持基因报告的家长，把口语症状与 VUS 片段对照权威指南，生成就诊前置比对报告。

🏆 **AIY 黑客松 2026 深圳站** 参赛作品
🎫 命题企业 / 赛道：华大生命科学研究院赛道
👤 团队：code vibers
🔢 团队编号：【HD0031】(组委会分配)

---

## 👥 团队分工
| 成员 | 负责 |
|---|---|
| 【赵述华】 | 【后端】 |
| 【赵相云】 | 【前端】 |
| 【李集】 | 【debug/市场分析】 |
| 【席文杰】 | 【迭代】 |

## ✨ 它能做什么
- 双输入筛查：家长用大白话描述异常症状，并粘贴基因报告（VUS）文本，一键生成结构化比对报告
- HPO 标准化：经 MCP 调用人类表型本体，把口语症状映射为标准 HPO 术语
- RAG 照本宣科：基于 ChromaDB 检索 AAP / GeneReviews 等指南切片，禁止大模型自由发挥
- VUS 科普安抚：用知识库原文解释「临床意义未明变异」，降低信息不对称带来的焦虑
- 合规护栏：严格 Non-Device CDS——不诊断、不定性、不开药；固定免责声明 + 引导至儿童发育行为科 / 医学遗传科

## 📹 演示
视频：文件夹内
🔗 在线体验：

## 🛠️ 用到的技术 / AI 工具
- **LLM**：MiniMax M3
- **前端**：Streamlit
- **后端**：FastAPI + Uvicorn
- **向量库 / Embedding**：ChromaDB + BAAI/bge-small-zh-v1.5
- **医学本体**：HPO（Human Phenotype Ontology）via MCP Server
- **开发工具**：Cursor IDE + Agent

## 🚀 怎么跑起来
需要 Python 3.9+ 与 Node.js 18+（后者用于 HPO-MCP-Server）。完整说明见 [docs/env-setup.md](./docs/env-setup.md)。

```bash
# 1. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 搭建 HPO-MCP-Server（未纳入本仓库，需自行 clone 并编译）
git clone https://github.com/Augmented-Nature/HPO-MCP-Server.git
cd HPO-MCP-Server && npm install && npm run build && cd ..

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入：
#   MINIMAX_API_KEY      —— MiniMax 控制台生成
#   HPO_MCP_SERVER_PATH  —— 上一步 build/index.js 的绝对路径

# 5. 构建 RAG 向量库（首次会下载约 95MB 中文向量模型）
python scripts/rag_builder.py

# 6. 启动后端
uvicorn main:app --reload --port 8000

# 7. 另开终端，激活同一虚拟环境后启动前端
source .venv/bin/activate
streamlit run app.py
```

可选验收自检：

```bash
python scripts/run_acceptance.py
```

> 第 6、7 步是两个独立进程。前端只做渲染，MCP / RAG / 大模型调用都发生在后端。

## 📌 后续计划
- 报告 PDF / 图片导出
- 多轮追问与症状澄清对话
- 扩充更多单基因病数据桶
- HPO 术语置信度评分与人工纠偏
- 基因报告文件上传（当前为文本粘贴）
- 筛查匹配可信度（confidence_level）展示

---

## 📄 版权与许可
本作品版权归 赵相云，赵述华，席文杰，李集 +2026 全体组员 共同所有，采用 [MIT License](./LICENSE) 开源，使用请署名。
> 本项目为 AIY 黑客松参赛作品，作品归团队所有；AIY 组委会仅作收录与展示。
