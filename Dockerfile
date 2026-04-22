# Dockerfile — Niblit container for Fly.io (and any Docker-based deployment)
# ──────────────────────────────────────────────────────────────────────────────
# Build:   docker build -t niblit .
# Run:     docker run -p 8080:8080 --env-file .env niblit
# Fly.io:  fly deploy   (uses this file automatically via fly.toml)
# ──────────────────────────────────────────────────────────────────────────────

# Use the official Python 3.12 slim image as the base
FROM python:3.14-slim

# ── System dependencies ───────────────────────────────────────────────────────
# Build tools needed for some Python packages (numpy, faiss-cpu, etc.)
# unzip is needed by tools/install_llama_server.sh (installs llama-server binary)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        git \
        curl \
        unzip \
        libsqlite3-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
# Use requirements-fly.txt for the Fly.io build.
# This lean set omits heavy ML packages (torch, sentence-transformers, etc.)
# that would OOM-kill a 512 MB Fly Machine before uvicorn can bind to port 8080.
# All omitted packages are guarded by try/except in niblit_core.py so the app
# runs in "cloud mode" (web API + KB + router) without them.
# For full ML features install requirements.txt locally (Termux / GPU server).
COPY requirements-fly.txt .

# Install Python packages
# --no-cache-dir keeps the image lean
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-fly.txt

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# ── Persistent-data directory ─────────────────────────────────────────────────
# On Fly.io this path is the Fly Volume mount point (/data).
# For local Docker runs it remains empty unless you bind-mount a host directory:
#   docker run -v $(pwd)/data:/data ...
RUN mkdir -p /data

# ── Environment defaults ──────────────────────────────────────────────────────
# These are baked into the image and can be overridden by fly.toml [env] or
# `fly secrets set`.  They mirror the fly.toml [env] defaults so that
# `docker run` without --env-file also produces a sensible configuration.
ENV APP_ENV=production \
    PORT=8080 \
    NIBLIT_DATA_DIR=/data \
    NIBLIT_MEMORY_PATH=/data/niblit_memory.json \
    NIBLIT_DB_PATH=/data/niblit.db \
    FUSED_MEMORY_DB_PATH=/data/niblit_fused.sqlite \
    ALE_CHECKPOINT_PATH=/data/ale_state.json \
    NIBLIT_GAME_LOG_PATH=/data/niblit_game_log.jsonl \
    NIBLIT_GAME_STATE_PATH=/data/niblit_game_state.json \
    LEAN_WORKSPACE=/data/lean_workspace \
    NIBLIT_LLM_PROVIDER=qwen \
    NIBLIT_BRAIN_MODE=balanced \
    NIBLIT_LLM_MODEL=moonshotai/Kimi-K2-Instruct-0905 \
    NIBLIT_GGUF_BACKEND=http \
    NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8081 \
    NIBLIT_LLAMA_SERVER_PORT=8081 \
    NIBLIT_GGUF_MODEL_PATH=/data/model.gguf \
    OANDA_ENVIRONMENT=practice \
    ALPACA_PAPER=true \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Port ──────────────────────────────────────────────────────────────────────
EXPOSE 8080

# ── Healthcheck ───────────────────────────────────────────────────────────────
# Fly.io will mark the Machine unhealthy if /health doesn't respond 200 within
# 30 seconds of startup. Niblit's app.py exposes GET /health.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# ── Entrypoint ────────────────────────────────────────────────────────────────
# start.sh optionally starts llama-server (when binary + model are present),
# then starts uvicorn.  See start.sh for the full startup logic.
RUN chmod +x /app/start.sh /app/tools/install_llama_server.sh \
             /app/tools/termux_inference_server.sh
CMD ["/app/start.sh"]
