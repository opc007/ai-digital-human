FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY configs ./configs
COPY src ./src
COPY web ./web
COPY scripts ./scripts
COPY tools ./tools
# 初始素材放到 data_bootstrap：compose 会挂载 ./data 覆盖镜像内 /app/data，
# 启动时再把缺失的初始素材补回挂载卷（见 CMD 的 bootstrap 一步）
COPY data/avatars ./data_bootstrap/avatars

ENV PYTHONPATH=/app/src
ENV APP_ENV=production

EXPOSE 8100
CMD ["sh", "-c", "mkdir -p /app/data && cp -rn /app/data_bootstrap/. /app/data/ 2>/dev/null || true; exec python scripts/07_run_api.py --host 0.0.0.0 --port 8100"]
