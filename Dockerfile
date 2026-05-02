# ─────────────────────────────────────────────
# Pikmin Bloom Radar Bot — Dockerfile
# Base: python:3.10-slim
# ─────────────────────────────────────────────

FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 先複製 requirements.txt，利用 Docker 快取加速重建
COPY requirements.txt .

# 安裝依賴（不安裝 pip 快取，減小 image 大小）
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式原始碼
COPY main.py config.py osm_service.py mapping.py ./

# 宣告容器監聽 Port
EXPOSE 8000

# 啟動 uvicorn（生產模式，1 worker，async friendly）
# 若需多工可改為 --workers 2，但 LINE webhook 通常不需要高並發
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
