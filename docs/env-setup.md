# 00-赛前工具链搭建指南


## 第一步：安装 Cursor 编辑器

1. 访问 Cursor 官网：https://cursor.com/
2. 下载适用于 Mac 的安装包。
3. 下载完成后，将 Cursor 拖入“应用程序”文件夹并运行。
4. 首次启动时按默认设置连续点击 Continue 即可。

## 第二步：配置 GitHub 与可视化协作工具

1. 访问 https://github.com/ 注册 GitHub 账号。
2. 访问 https://desktop.github.com/ 下载并安装 GitHub Desktop。
3. 运行 GitHub Desktop，使用刚注册的账号登录并完成网页授权。
4. 在 GitHub Desktop 中点击 "Create a New Repository on your hard drive"，命名项目库（例如 `hackathon-demo`），并点击 "Publish repository" 将其发布到云端。
5. 回到 Cursor 界面，点击 File -> Open Folder，选择刚刚创建的项目文件夹。

## 第三步：获取 MiniMax API 密钥

1. 访问 MiniMax 开发者平台：https://platform.minimax.io/
2. 注册并登录账号，进入控制台 (Console)。
3. 在左侧导航栏进入 API Keys 管理页面。
4. 点击 Create new key。
5. 复制屏幕上生成的以 `sk-cp-` 开头的密钥，妥善保存在本地（该密钥仅完整显示一次）。

## 第四步：在 Cursor 中配置 MiniMax 算力

1. 在 Cursor 中使用快捷键 `Cmd + ,` 唤出设置面板。
2. 进入左侧导航栏的 Models 选项卡。
3. 关闭列表内所有自带默认模型（如 Claude 3.5 Sonnet, GPT-4o 等）右侧的开关。
4. 点击 Add Model 输入框，输入 `MiniMax-M3`，点击 `+` 号添加，并确保其右侧开关开启。
5. 向下滚动至 API Keys 区域的 OpenAI API Key 板块：
   - 开启板块右侧开关。
   - 在密钥输入框内粘贴第三步获取的 MiniMax 密钥。
   - 开启 Override OpenAI Base URL 开关。
   - 在 Base URL 输入框中严格填入：`https://api.minimax.io/v1`

# SpectrumX：基于 MCP、RAG 与 MiniMax M3 的本地环境搭建全指南

本文档汇集了在 Mac 环境下使用 Cursor 从零开始配置项目的所有步骤，涵盖了 Homebrew 与 Node.js 的环境准备、HPO-MCP-Server 的搭建与测试、以及 RAG (检索增强生成) 模块的构建与前后端（FastAPI + Streamlit）全链路闭环部署。

---

## 阶段一：基础环境准备 (Mac)

### 1.1 安装 Homebrew (包管理器)
打开终端 (Terminal)，执行以下命令安装 Homebrew：
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
**配置环境变量 (重要)**：安装完成后，如果终端提示 "Next steps"，请根据您的芯片架构运行配置命令：
* **M系列芯片 (Apple Silicon)**：
  ```bash
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  eval "$(/opt/homebrew/bin/brew shellenv)"
  ```
* **Intel 芯片**：
  ```bash
  echo 'eval "$(/usr/local/bin/brew shellenv)"' >> ~/.zprofile
  eval "$(/usr/local/bin/brew shellenv)"
  ```
验证：运行 `brew -v` 确保输出版本号。

*(注：若连接 GitHub 下载缓慢或卡死，可终止命令并尝试使用国内加速源脚本：`/bin/zsh -c "$(curl -fsSL https://gitee.com/cunkai/HomebrewCN/raw/master/Homebrew.sh)"`)*

### 1.2 安装 Node.js 与 npm
```bash
brew install node
```
验证安装：运行 `node -v` (需 v18+) 和 `npm -v`。

### 1.3 安装 Python (3.9+)
本项目后端 (FastAPI)、RAG (ChromaDB) 与前端 (Streamlit) 均基于 Python。使用 Homebrew 安装：
```bash
brew install python
```
验证安装：运行 `python3 --version` (需 3.9 或更高) 和 `pip3 --version`。

### 1.4 创建并激活 Python 虚拟环境 (强烈推荐)
虚拟环境将本项目的依赖与系统 Python 隔离，避免版本冲突。**后续所有 `pip install` 与 `python` 命令都必须在激活虚拟环境后执行。**

1. 在 Cursor 中打开项目根目录，唤出终端 (`Ctrl + ~`)，确认当前位于项目根目录。
2. 创建名为 `.venv` 的虚拟环境：
   ```bash
   python3 -m venv .venv
   ```
3. 激活虚拟环境 (macOS / zsh)：
   ```bash
   source .venv/bin/activate
   ```
   激活成功后，终端提示符前会出现 `(.venv)` 前缀。
4. 升级 pip 至最新版：
   ```bash
   pip install --upgrade pip
   ```
5. 将虚拟环境目录加入 `.gitignore`，避免误提交：
   ```bash
   echo ".venv/" >> .gitignore
   ```

> **提示**：每次新开终端窗口都需重新执行 `source .venv/bin/activate`。退出虚拟环境使用命令 `deactivate`。
>
> **一键安装依赖**：建议在项目根目录创建 `requirements.txt`（内容见 [附录：requirements.txt](#附录requirementstxt)），随后执行 `pip install -r requirements.txt` 即可一次性装齐所有 Python 依赖，无需再逐条 `pip install`。

---

## 阶段二：搭建与配置 HPO-MCP-Server

该服务用于将家长的白话文症状描述，通过大模型转化为标准的 HPO 医学表型术语。

### 2.1 下载与编译
**在项目根目录**（即本仓库根目录）执行，让服务器落在 `HPO-MCP-Server/` 子目录下：
```bash
git clone https://github.com/Augmented-Nature/HPO-MCP-Server.git
cd HPO-MCP-Server
npm install
npm run build
```
`npm install` 会自动触发一次 `prepare` -> `npm run build`，所以看到重复的 build 输出属于正常现象。编译产物为 `HPO-MCP-Server/build/index.js`。

> `npm install` 结尾提示的 vulnerabilities 与 npm 新版本通知可以忽略，不影响本地 MCP 服务运行；**不要**执行 `npm audit fix --force`，它会引入破坏性升级。

### 2.2 注册 MCP 服务器（编辑 mcp.json）
当前版本的 Cursor 已取消旧的 `Settings -> Features -> MCP -> + Add New MCP Server` 表单，自定义 MCP 服务器统一通过 `mcp.json` 配置文件管理。

本项目采用**项目级配置**：仓库根目录下的 [`.cursor/mcp.json`](../.cursor/mcp.json)（已随仓库提交，clone 下来即生效，无需每人手动添加）：

```json
{
  "mcpServers": {
    "hpo-server": {
      "type": "stdio",
      "command": "node",
      "args": ["${workspaceFolder}/HPO-MCP-Server/build/index.js"]
    }
  }
}
```

其中 `${workspaceFolder}` 是 Cursor 官方支持的插值变量，指向包含 `.cursor/mcp.json` 的项目根目录。用它而不是绝对路径，团队每个人的机器都能直接复用同一份配置。

**在 Cursor 界面里打开该文件的方式**：点击侧边栏的 **Customize** -> 找到 MCP 区域 -> 点击 **New MCP Server**，Cursor 会直接打开 `mcp.json` 供编辑（而不是弹出表单）。

> **可选：全局配置**。若你希望在所有项目中都能用这台服务器，改为编辑 `~/.cursor/mcp.json`，此时 `${workspaceFolder}` 不再适用，`args` 必须填写绝对路径，例如 `["/Users/yourname/Desktop/hackathon-genetic-counseling-agent/HPO-MCP-Server/build/index.js"]`。

配置保存后，需要重新加载 Cursor 窗口（`Cmd + Shift + P` -> `Developer: Reload Window`），或在 Customize 面板把 `hpo-server` 开关关掉再打开，服务器才会连接。

### 2.3 验证服务是否正常
**方式一：命令行自检（推荐，无需浏览器）**。在项目根目录执行，直接与服务器做一次 MCP 握手并列出工具：
```bash
cd HPO-MCP-Server
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1.0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | node build/index.js
```
预期：stderr 输出 `HPO MCP server running on stdio`，stdout 返回两条 JSON，其中包含 `"name":"hpo-server"` 以及 12 个工具名（`search_hpo_terms`、`get_hpo_term`、`get_hpo_ancestors`、`get_hpo_parents`、`get_hpo_children`、`get_hpo_descendants`、`validate_hpo_id`、`get_hpo_term_path`、`compare_hpo_terms`、`get_hpo_term_stats`、`batch_get_hpo_terms`、`get_all_hpo_terms`）。

**方式二：在 Cursor 内确认**。打开侧边栏 **Customize**，`hpo-server` 应显示为已连接并列出 12 个工具。若连接失败，打开输出面板（`Cmd + Shift + U`）在下拉框中选择 **MCP Logs** 查看启动报错。

**方式三：图形化排查（可选）**。用官方 Inspector 交互式调用工具：
```bash
npx @modelcontextprotocol/inspector node ./build/index.js
```

### 2.4 冒烟测试（确认端到端可用）
在 Cursor 的 Chat 中输入：
```
用 search_hpo_terms 搜索 seizure
```
预期返回 `HP:0001250 Seizure` 及其定义。该服务器直连公开 API `https://ontology.jax.org/api/hp`，**无需任何 API Key**，但需要联网。

> **重要：语言限制**。HPO 官方 API 只索引英文术语，直接拿中文白话（如“整天傻笑”）去查会检索不到。因此本项目的调用链必须是：先由 MiniMax M3 把家长口语描述翻译成英文医学关键词（如 `inappropriate laughter`），再交给 `search_hpo_terms` 换取标准 HPO 编码 —— 这正是 PRD 中「MCP 翻译官」这一角色的落地方式。

### 2.5 注意事项：队友首次拉取项目
`HPO-MCP-Server/` 已被根目录 `.gitignore` 忽略（内含体积巨大的 `node_modules`，不纳入本仓库）。因此**每位成员 clone 本仓库后都必须自行执行一次 2.1 的 clone + `npm install`**，否则 `.cursor/mcp.json` 指向的 `build/index.js` 不存在，Cursor 会报服务器启动失败。

---

## 阶段三：搭建本地 RAG (检索增强生成) 模块

此模块用于构建本地的医学知识向量库（鉴别诊断、基因测序科学解读、合规声明），供后续的检索调用。

### 3.1 安装核心 Python 库
确认已激活虚拟环境（终端提示符含 `(.venv)`，见 [1.4 节](#14-创建并激活-python-虚拟环境-强烈推荐)），然后运行：
```bash
pip install chromadb sentence-transformers langchain
```

### 3.2 准备与清洗“数据桶” (构建本地向量库)
在 Cursor 项目目录中创建 `rag_builder.py` 并运行：

```python
import chromadb
from chromadb.utils import embedding_functions

# 1. 初始化 ChromaDB
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# 2. 使用本地开源 Embedding 模型
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

# 3. 创建 Collection
collection = chroma_client.get_or_create_collection(
    name="autism_genetics_knowledge",
    embedding_function=sentence_transformer_ef
)

# 4. 准备数据桶内容 (A/B/C)
documents = [
    "在儿童18个月和24个月必须进行标准化筛查。如果患儿伴发新发的攻击性或严重的自伤行为，干预的首要原则并非盲目使用精神药物，必须首先全面排除隐匿性躯体疼痛（如隐匿的牙痛或胃肠道痉挛）。",
    "脆性X综合征（Fragile X Syndrome, FXS）：最常见的导致 ASD 的单基因突变（FMR1基因 CGG 异常扩增）。患者常伴有明显的颅面特征（长脸、突出前额、大耳廓），且超过80%会合并强烈的 ADHD 症状及难以控制的焦虑。",
    "VUS 极其常见：在进行广泛基因组检测的人群中，高达 41% 的个体都会收到至少一个 VUS 报告，这是科学技术发展过程中的正常现象。它绝不是确诊书，不要过度恐慌。",
    "本系统不可替代执业医师的面诊，绝不作为任何疾病的确诊结论，亦不提供任何具体的干预或用药建议。强烈建议前往医学遗传科评估。"
]

metadatas = [
    {"source": "AAP_Guidelines", "bucket": "A"},
    {"source": "GeneReviews_FMR1", "bucket": "A"},
    {"source": "ACMG_VUS", "bucket": "B"},
    {"source": "FDA_Disclaimer", "bucket": "C"}
]
ids = ["doc_a1", "doc_a2", "doc_b1", "doc_c1"]

# 5. 灌入数据
collection.add(
    documents=documents,
    metadatas=metadatas,
    ids=ids
)
print("✅ 知识库已成功灌入 ChromaDB 本地向量库！")
```
运行：`python rag_builder.py`

### 3.3 编写检索函数
创建 `rag_retriever.py` 以测试检索逻辑：

```python
import chromadb
from chromadb.utils import embedding_functions

chroma_client = chromadb.PersistentClient(path="./chroma_db")
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = chroma_client.get_collection(name="autism_genetics_knowledge", embedding_function=sentence_transformer_ef)

def query_medical_guidelines(standardized_symptoms: str, gene_report: str):
    query_text = f"症状: {standardized_symptoms} 基因: {gene_report}"
    results = collection.query(
        query_texts=[query_text],
        n_results=3
    )
    retrieved_docs = results['documents'][0]
    return "\n".join(retrieved_docs)

if __name__ == "__main__":
    context = query_medical_guidelines("严重智力障碍，频繁大笑，步态不稳", "UBE3A 缺失")
    print("检索到的医学背景知识：\n", context)
```

---

## 阶段四：闭环组装 (后端 FastAPI 衔接 MCP, RAG 与 MiniMax)

构建轻量级后端 API，串联 MCP 模拟翻译、RAG 检索以及 MiniMax大模型生成，最后套用合规护栏。

### 4.1 安装后端依赖
（同样在已激活的虚拟环境下运行）
```bash
pip install fastapi uvicorn requests python-dotenv
```

### 4.2 配置 API 密钥环境变量 (.env)
后端通过 `python-dotenv` 从项目根目录的 `.env` 文件读取密钥。在项目根目录创建 `.env`，填入 [第三步](#第三步获取-minimax-api-密钥) 获取的密钥：
```bash
MINIMAX_API_KEY=你的_MiniMax_密钥
```
> **安全提示**：务必将 `.env` 加入 `.gitignore`（`echo ".env" >> .gitignore`），严禁将密钥提交到 GitHub。

### 4.3 编写后端 API (main.py)
在项目根目录创建 `main.py`：

```python
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")

app = FastAPI(title="SpectrumX Backend API", version="1.0")

chroma_client = chromadb.PersistentClient(path="./chroma_db")
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = chroma_client.get_or_create_collection(
    name="autism_genetics_knowledge",
    embedding_function=sentence_transformer_ef
)

class ScreeningRequest(BaseModel):
    symptoms: str
    gene_report: str

def mcp_translate_symptoms(raw_symptoms: str) -> str:
    # MVP阶段：模拟MCP翻译结果。生产环境应调用之前测试通的 HPO-MCP-Server 工具
    return f"标准化表型代码 -> 原始描述: {raw_symptoms} (已映射至标准 HPO 词条)"

def retrieve_rag_context(standardized_symptoms: str, gene_report: str) -> str:
    query_text = f"症状: {standardized_symptoms} 基因: {gene_report}"
    results = collection.query(query_texts=[query_text], n_results=2)
    return "\n- ".join(results['documents'][0])

@app.post("/api/screen")
def run_screening_pipeline(data: ScreeningRequest):
    try:
        # Step 1 & 2
        hpo_standardized = mcp_translate_symptoms(data.symptoms)
        rag_knowledge = retrieve_rag_context(hpo_standardized, data.gene_report)
        
        # Step 3: 合规与护栏 Prompt (包含数据桶 C)
        system_prompt = (
            "你是一个专业的罕见病与自闭症前置筛查科普助手。请严格根据提供的【权威参考资料】回答用户问题，"
            "绝对不能主观臆造或给出确诊结论。\n\n"
            f"【权威参考资料 (RAG)】:\n- {rag_knowledge}\n\n"
            "【合规硬性要求】:\n"
            "无论风险高低，严禁出现'您确诊了XXX'或'建议服用XXX'。在报告最末尾，"
            "必须强制附带以下免责声明：\n"
            "'本系统提供的信息比对与基因知识科普均基于权威医学文献检索生成。本报告仅用于帮助家长梳理日常生活中的前置症状线索，"
            "并翻译晦涩的基因术语。本系统不可替代执业医师的面诊，绝不作为任何疾病的确诊结论。强烈建议您携带此信息整理单，"
            "前往正规三甲医疗机构的儿童发育行为科及医学遗传科，由专业医生进行最终临床评估。'"
        )
        user_prompt = f"患儿症状描述：{data.symptoms}\n标准化表型：{hpo_standardized}\n基因测序报告/VUS：{data.gene_report}"

        # Step 4: 调用 MiniMax M3
        url = "https://api.minimax.io/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "MiniMax-M3",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "stream": False
        }
        
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Minimax API Error: {response.text}")
            
        ai_reply = response.json()['choices'][0]['message']['content']
        
        return {
            "status": "success",
            "mcp_translation": hpo_standardized,
            "retrieved_knowledge": rag_knowledge,
            "screening_report": ai_reply
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
**启动后端**: `uvicorn main:app --reload --port 8000`  
*(可通过 `http://127.0.0.1:8000/docs` 访问 Swagger UI 测试 API)*

---

## 阶段五：前端可视化 (Streamlit)
安装 `pip install streamlit`，并创建 `app.py`：

```python
import streamlit as st
import requests

st.title("🧬 SpectrumX - 自闭症与基因筛查助手")

symptoms_input = st.text_area("请输入孩子的日常异常表现（大白话）", placeholder="例如：经常无故大笑，手部有刻板动作，语言能力倒退...")
gene_input = st.text_input("请输入基因检测报告或 VUS 片段", placeholder="例如：MECP2 基因 VUS 变异")

if st.button("生成筛查比对与前置就诊单"):
    if not symptoms_input or not gene_input:
        st.warning("请完整填写症状和基因报告信息！")
    else:
        with st.spinner("MCP 翻译官正在转换表型，RAG 正在检索教科书..."):
            try:
                response = requests.post(
                    "http://127.0.0.1:8000/api/screen",
                    json={"symptoms": symptoms_input, "gene_report": gene_input}
                )
                
                if response.status_code == 200:
                    res_data = response.json()
                    st.success("分析完成！")
                    st.subheader("📋 最终筛查与前置就诊建议报告")
                    st.markdown(res_data["screening_report"])
                    
                    with st.expander("🔍 查看底层黑盒架构运行日志 (MCP + RAG)"):
                        st.text(f"【MCP 标准化结果】:\n{res_data['mcp_translation']}")
                        st.text(f"【RAG 检索到的医学知识切片】:\n{res_data['retrieved_knowledge']}")
                else:
                    st.error(f"调用失败: {response.text}")
            except Exception as ex:
                st.error(f"连接后端服务出错: {ex}")
```
**启动前端**: `streamlit run app.py`（需保持阶段四的后端 `uvicorn` 进程处于运行状态）

此时，一套打通 MCP + RAG + FastAPI + Streamlit 的本地化全链路 MVP 就已成功跑通。

---

## 附录：requirements.txt

在项目根目录创建 `requirements.txt`，一次性锁定所有 Python 依赖，激活虚拟环境后执行 `pip install -r requirements.txt` 即可：

```text
chromadb
sentence-transformers
langchain
fastapi
uvicorn
requests
python-dotenv
streamlit
```

> 运行顺序回顾：`source .venv/bin/activate` → `pip install -r requirements.txt` → `python rag_builder.py`（灌库）→ `uvicorn main:app --reload --port 8000`（后端）→ 新开终端并再次激活虚拟环境 → `streamlit run app.py`（前端）。