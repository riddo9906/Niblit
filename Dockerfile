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
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        git \
        curl \
        libsqlite3-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
# Copy requirements first so Docker can cache the pip install layer
COPY requirements.txt .

# Install Python packages
# --no-cache-dir keeps the image lean
# torch / sentence-transformers can be large; they are included to keep Niblit
# fully functional. If image size is a concern, comment out heavy ML deps.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# ── Persistent-data directory ─────────────────────────────────────────────────
# On Fly.io this path is the Fly Volume mount point (/data).
# For local Docker runs it remains empty unless you bind-mount a host directory:
#   docker run -v $(pwd)/data:/data ...
RUN mkdir -p /data

# ── Environment defaults ──────────────────────────────────────────────────────
ENV APP_ENV=production \
    PORT=8080 \
    NIBLIT_MEMORY_PATH=/data/niblit_memory.json \
    NIBLIT_DB_PATH=/data/niblit.db \
    FUSED_MEMORY_DB_PATH=/data/niblit_fused.sqlite \
    ALE_CHECKPOINT_PATH=/data/ale_state.json \
    NIBLIT_GAME_LOG_PATH=/data/niblit_game_log.jsonl \
    NIBLIT_GAME_STATE_PATH=/data/niblit_game_state.json \
    LEAN_WORKSPACE=/data/lean_workspace \
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
# Workers=1 is mandatory: Niblit uses in-process singletons (NiblitMemory,
# ALE, TradingBrain, etc.) that must not be forked across multiple workers.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--log-level", "info"]
