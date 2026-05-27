#!/usr/bin/env bash
# start.sh — Niblit Fly.io container entrypoint
#
# Behaviour
# ─────────────────────────────────────────────────────────────────────────────
# 1. If NIBLIT_LLAMA_SERVER_URL points to a LOCAL address (127.0.0.1 /
#    localhost) AND a llama-server binary + GGUF model file are present,
#    starts llama-server in the background on NIBLIT_LLAMA_SERVER_PORT
#    (default 8081) before uvicorn.
#    NOTE: port 8080 is intentionally avoided because uvicorn binds 8080
#    for Fly's HTTP routing; llama-server therefore uses 8081.
#
# 2. If NIBLIT_LLAMA_SERVER_URL is a REMOTE URL (e.g. niblit-cloud-server,
#    a Cloudflare/ngrok tunnel to a Termux device, or another Fly machine),
#    uvicorn starts immediately. QwenLocalBrain._check_server_url() will probe the remote
#    endpoint at startup; if it is unreachable, Niblit falls back to the
#    HF cloud LLM (HF_TOKEN required).
#
# 3. Always starts uvicorn last on $PORT (default 8080).
#
# Key environment variables (all have safe defaults)
# ─────────────────────────────────────────────────────────────────────────────
#   NIBLIT_LLAMA_SERVER_URL   Base URL QwenLocalBrain connects to.
#                             Default: http://127.0.0.1:8081
#   NIBLIT_LLAMA_SERVER_PORT  Port for the LOCAL llama-server process.
#                             Default: 8081
#   NIBLIT_LLAMA_BINARY       Path to llama-server binary.
#                             Default: /home/riddo9906/llama.cpp/build/bin/llama-server
#   NIBLIT_GGUF_MODEL_PATH    Path to the GGUF model file.
#                             Default: /home/riddo9906/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
#   NIBLIT_GGUF_N_CTX         Context size passed to llama-server. Default: 16384
#   NIBLIT_GGUF_N_THREADS     CPU threads for llama-server. Default: 2
#   PORT                      Port for uvicorn. Default: 8080

set -e

PORT="${PORT:-8080}"
LLAMA_URL="${NIBLIT_LLAMA_SERVER_URL:-http://127.0.0.1:8081}"
LLAMA_PORT="${NIBLIT_LLAMA_SERVER_PORT:-8081}"
LLAMA_BIN="${NIBLIT_LLAMA_BINARY:-/home/riddo9906/llama.cpp/build/bin/llama-server}"
MODEL_FILE="${NIBLIT_GGUF_MODEL_PATH:-/home/riddo9906/models/qwen2.5-0.5b-instruct-q4_k_m.gguf}"

echo "[start.sh] ════════════════════════════════════════════"
echo "[start.sh]   Niblit  ·  Fly.io startup"
echo "[start.sh] ════════════════════════════════════════════"
echo "[start.sh] DATA_DIR             = ${NIBLIT_DATA_DIR:-/data}"
echo "[start.sh] NIBLIT_LLM_PROVIDER  = ${NIBLIT_LLM_PROVIDER:-qwen}"
echo "[start.sh] NIBLIT_GGUF_BACKEND  = ${NIBLIT_GGUF_BACKEND:-http}"
echo "[start.sh] NIBLIT_BACKEND_MODE  = ${NIBLIT_BACKEND_MODE:-http}"
echo "[start.sh] LLAMA_SERVER_URL     = ${LLAMA_URL}"
echo "[start.sh] NIBLIT_CLOUD_SERVER  = ${NIBLIT_CLOUD_SERVER_URL:-https://niblit-cloud-server.fly.dev}"
echo "[start.sh] ────────────────────────────────────────────"

# ── Helper: detect whether a URL targets this machine ─────────────────────────
_is_local_url() {
    case "$1" in
        *"127.0.0.1"* | *"localhost"* | *"0.0.0.0"*) return 0 ;;
        *) return 1 ;;
    esac
}

# ── Optionally start a local llama-server ─────────────────────────────────────
if _is_local_url "$LLAMA_URL"; then
    if [ -x "$LLAMA_BIN" ] && [ -f "$MODEL_FILE" ]; then
        echo "[start.sh] ✅ Starting llama-server (local) on port ${LLAMA_PORT}"
        echo "[start.sh]    Binary : ${LLAMA_BIN}"
        echo "[start.sh]    Model  : ${MODEL_FILE}"

        "$LLAMA_BIN" \
            --host 127.0.0.1 \
            --port "$LLAMA_PORT" \
            --model "$MODEL_FILE" \
            --ctx-size "${NIBLIT_GGUF_N_CTX:-${NIBLIT_RUNTIME_CONTEXT_TARGET:-16384}}" \
            --threads "${NIBLIT_GGUF_N_THREADS:-2}" \
            -np 1 \
            --log-disable &
        LLAMA_PID=$!
        echo "[start.sh]    PID    : ${LLAMA_PID}"

        echo "[start.sh] Waiting for llama-server to be ready..."
        READY=0
        for i in $(seq 1 30); do
            if curl -sf "http://127.0.0.1:${LLAMA_PORT}/health" >/dev/null 2>&1; then
                echo "[start.sh] ✅ llama-server ready after $(( i * 2 )) seconds"
                READY=1
                break
            fi
            sleep 2
        done
        if [ "$READY" -eq 0 ]; then
            echo "[start.sh] ⚠️  llama-server did not respond in 60s; Niblit will use HF fallback"
        fi
    else
        echo "[start.sh] ℹ️  Local llama-server not started:"
        if [ -x "$LLAMA_BIN" ]; then
            echo "[start.sh]   Binary  : ${LLAMA_BIN} ✅"
        else
            echo "[start.sh]   Binary  : ${LLAMA_BIN} ❌  (run tools/install_llama_server.sh)"
        fi
        if [ -f "$MODEL_FILE" ]; then
            echo "[start.sh]   Model   : ${MODEL_FILE} ✅"
        else
            echo "[start.sh]   Model   : ${MODEL_FILE} ❌"
            echo "[start.sh]             Upload with:  fly sftp shell"
            echo "[start.sh]             then: put /local/path/to/model.gguf /home/riddo9906/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        fi
        echo "[start.sh]   → Alternative: use Termux as remote inference backend"
        echo "[start.sh]     bash tools/termux_inference_server.sh  # run on Termux"
        echo "[start.sh]   → Niblit will fall back to HF cloud LLM (HF_TOKEN required)"
    fi
else
    # Remote llama-server — Termux tunnel, another Fly machine, etc.
    echo "[start.sh] 🌐 Remote inference backend: ${LLAMA_URL}"
    echo "[start.sh]    QwenLocalBrain will probe at startup."
    echo "[start.sh]    If unreachable, Niblit falls back to HF cloud LLM."
fi

# ── Start Niblit API ───────────────────────────────────────────────────────────
echo "[start.sh] ────────────────────────────────────────────"
echo "[start.sh] 🚀 Starting Niblit (uvicorn) on port ${PORT}"
exec uvicorn app:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers 1 \
    --log-level info
