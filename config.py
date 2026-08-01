"""全项目共享配置。

灌库脚本与后端必须使用**同一个** collection 名与 embedding 模型，否则检索会静默失准
（查得到结果，但相似度计算全是噪声）。这类 bug 极难在现场定位，故把两端共用的常量
收在此处，禁止在各自模块里另写默认值。

根目录模块（main.py / app.py）直接 `import config`；
scripts/ 下的脚本需先把项目根加入 sys.path，见 scripts/rag_builder.py 顶部。
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

load_dotenv(ROOT / ".env")

# ---------- 目录 ----------

DATA_DIR = ROOT / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
RAW_DIR = KNOWLEDGE_DIR / "raw"
TEST_CASE_DIR = DATA_DIR / "test_cases"
FIXTURES_DIR = DATA_DIR / "fixtures"
BUCKET_C_PATH = KNOWLEDGE_DIR / "bucket_c_compliance.json"

# ---------- 向量库 ----------

# collection 名不走环境变量：两端必须一致，没有按环境切换的场景。
COLLECTION_NAME = "autism_genetics_knowledge"

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")

# 知识库是中文，必须用中文/多语言模型。换模型后须重新灌库。
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

# ---------- 服务地址 ----------

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

# ---------- Minimax ----------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")

# ---------- HPO MCP ----------

HPO_MCP_SERVER_PATH = os.getenv("HPO_MCP_SERVER_PATH", "")


def official_disclaimer() -> str:
    """桶 C 的免责声明原文。

    后端必须用本函数的返回值**逐字**填充响应的 disclaimer 字段，不经大模型；
    验收脚本也用它做比对。两端共用同一个读取入口，杜绝文案漂移。
    """
    entries = json.loads(BUCKET_C_PATH.read_text(encoding="utf-8"))
    for e in entries:
        if e.get("is_disclaimer"):
            return e["text"]
    return entries[0]["text"]
