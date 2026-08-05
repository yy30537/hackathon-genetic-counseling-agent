# ASD-GenDecoder（自闭症基因解码器）

> 让晦涩的基因报告说人话，**终结自闭症与罕见基因病的误诊漫游**。

🏆 **AIY 黑客松 2026 深圳站**参赛作品
命题/赛道：华大生命科学研究院赛道
🔢 团队编号：HD0031

> ⚖️ **合规护栏**：本项目严格遵循 FDA「非医疗器械临床决策支持」豁免标准，不下诊断、不开药，只做专业医学指南的搬运工与翻译官，最终决策权交还给专科医生。

---

## 👥 团队分工

| 成员 | 负责 |
|---|---|
| 【赵述华】 | 【后端 】 |
| 【赵相云】 | 【前端 / 演示照片】 |
| 【席文杰】 | 【用户调研 / Pitch 路演】 |
| 【李集】 | 【双轨隔离/debug】 |



---

## ✨ 它能做什么

- **功能一**：【将家长口语化的"孩子整天傻笑""两岁还不会叫人"等症状描述，通过 HPO 本体翻译为标准医学术语，供下游检索使用】
- **功能二**：【用户粘贴 WES 基因报告中的 VUS 片段，系统基于 AAP / GeneReviews 指南检索，生成结构化的症状与基因比对报告，附带就诊建议】

> 两个核心功能的一句话描述由团队成员填写，确保与 docs/PRD.md 口径一致。

---

## 📺 演示



🔗 在线体验：

---

## 🛠️ 用到的技术 / AI 工具

- **大模型**：Minimax M3（自然语言理解与生成）
- **前端**：Streamlit（Python，零前端构建）
- **后端**：FastAPI（Python，单端点 `POST /api/screen`）
- **向量库**：ChromaDB + 中文开源向量模型（约 95MB，本地离线）
- **医学本体**：HPO（Human Phenotype Ontology）via HPO-MCP-Server
- **开发工具**：Cursor IDE + 内置 Agent

---

## 🚀 怎么跑起来

> 完整说明见 [`docs/env-setup.md`](./docs/env-setup.md)。需要 Python 3.9+ 与 Node.js 18+（后者用于 HPO-MCP-Server）。

```bash
# 1. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 搭建 HPO-MCP-Server（未纳入本仓库，需自行 clone 并编译）
git clone https://github.com/Augmented-Nature/HPO-MCP-Server.git
cd HPO-MCP-Server && npm install && npm run build && cd ..
# 记下 build/index.js 的绝对路径，下一步要填

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入两项必填变量：
#   MINIMAX_API_KEY       —— MiniMax 控制台生成
#   HPO_MCP_SERVER_PATH   —— 上一步 build/index.js 的绝对路径

# 5. 构建 RAG 向量库（首次运行会下载约 95MB 的中文向量模型）
python scripts/rag_builder.py

# 6. 启动后端（终端 A）
uvicorn main:app --reload --port 8000

# 7. 另开一个终端，激活同一虚拟环境后启动前端（终端 B）
source .venv/bin/activate
streamlit run app.py
```

可选验收自检：

```bash
python scripts/run_acceptance.py    # 把 data/test_cases/ 下的用例逐条打给后端，校验字段、合规红线
```

> 第 6、7 步是**两个独立进程**，需各占一个终端。前端只做渲染，所有 MCP、RAG 与大模型调用都发生在后端。

---

## 🎯 后续计划

【接下来你还想加什么。持续迭代记录，正是它作为「真实产品」的价值所在。可参考方向：】

- 【例如：把 HPO 翻译与 RAG 检索封装为 Coze 智能体插件，开放给其他罕见病方向复用】
- 【例如：补充中文 VUS 知识库切片，覆盖国内主流检测机构的报告格式】
- 【例如：与儿童发育行为科 / 医学遗传科的转诊路径合作，做真实就诊闭环】
- 【……】

---

## 📜 版权与许可

本作品版权归 **【真正参与的队员姓名】** 共同所有，采用 [MIT License](./LICENSE) 开源，使用请署名。

> 本项目为 AIY 黑客松参赛作品，作品归团队所有；AIY 组委会仅作收录与展示。