FROM python:3.11-slim-bookworm

# Node 给 HPO-MCP-Server 用
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# 先装 CPU 版 torch，避免 pip 默认拉数 GB 的 CUDA/nvidia 包（筛查不需要 GPU）
# Streamlit≥1.53 切到 Starlette 后与当前 starlette 的 GZipResponder 签名不兼容，会 500；钉在 1.52
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir 'streamlit>=1.31,<1.53'

# 构建期预拉 embedding，避免首请求超时
ENV EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# HPO（仓库外依赖，构建时拉）
RUN git clone --depth 1 https://github.com/Augmented-Nature/HPO-MCP-Server.git /app/HPO-MCP-Server \
    && cd /app/HPO-MCP-Server && npm install && npm run build

COPY . .

RUN chmod +x start.sh

ENV CHROMA_DB_PATH=/app/chroma_db
ENV HPO_MCP_SERVER_PATH=/app/HPO-MCP-Server/build/index.js
ENV BACKEND_URL=http://127.0.0.1:8000
ENV PYTHONUNBUFFERED=1

CMD ["/bin/sh", "-c", "exec ./start.sh"]
