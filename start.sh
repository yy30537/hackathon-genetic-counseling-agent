#!/bin/sh
set -e

# 容器内后端固定 8000；对外端口必须用 Railway 注入的 PORT
uvicorn main:app --host 127.0.0.1 --port 8000 &

exec streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT:-8501}" \
  --server.headless true \
  --browser.gatherUsageStats false
