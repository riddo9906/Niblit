#!/usr/bin/env bash
# tools/termux_inference_server.sh — Run llama-server on Termux and expose it
#                                    to Fly.io as a remote inference backend.
#
# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE
# ─────────────────────────────────────────────────────────────────────────────
#
#   Android / Termux (your phone)            Fly.io (cloud)
#   ┌───────────────────────────┐            ┌──────────────────────────┐
#   │  llama-server             │            │  Niblit API (uvicorn)    │
#   │  port 8080  (GGUF model)  │ ◄──────── │  QwenLocalBrain (http)   │
#   │                           │  tunnel    │  port 8080               │
#   │  cloudflared / ngrok      │  NIBLIT_   │                          │
#   │  → https://xxx.tryclou…  │  LLAMA_    │                          │
#   └───────────────────────────┘  SERVER_   └──────────────────────────┘
#                                  URL=...
#
# This script:
#   1. Finds (or is told) the llama-server binary and GGUF model.
#   2. Starts llama-server on TERMUX (port 8080 by default).
#   3. Creates a public HTTPS tunnel via cloudflared or ngrok.
#   4. Prints the exact `fly secrets set` command to wire Fly.io to Termux.
#
# ─────────────────────────────────────────────────────────────────────────────
# REQUIREMENTS  (install in Termux before running)
# ─────────────────────────────────────────────────────────────────────────────
#   pkg install cloudflared          # OR: pkg install ngrok
#   # llama-server binary — build with:
#   #   cd ~/llama.cpp && mkdir -p build && cd build
#   #   cmake .. -DLLAMA_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF
#   #   cmake --build . -j1
#   # GGUF model — download e.g.:
#   #   python tools/install_local_qwen_model.py
#
# ─────────────────────────────────────────────────────────────────────────────
# USAGE
# ─────────────────────────────────────────────────────────────────────────────
#   bash tools/termux_inference_server.sh
#   # Copy the printed `fly secrets set` command and run it on your laptop.
#   # Keep this script running while you use the Fly deployment.
#
# ENVIRONMENT VARIABLES (override defaults)
#   NIBLIT_LLAMA_BINARY      Path to llama-server binary  (auto-detected)
#   NIBLIT_GGUF_MODEL_PATH   Path to GGUF model file      (auto-detected)
#   NIBLIT_LLAMA_PORT        Port for llama-server         (default 8080)
#   NIBLIT_GGUF_N_CTX        Context size                  (default 4096)
#   NIBLIT_GGUF_N_THREADS    CPU threads                   (default 4)
#   NIBLIT_TUNNEL_TOOL       "cloudflared" | "ngrok" | "none"  (auto-detect)
#   FLY_APP_NAME             Your Fly app name             (default "niblit")
# ─────────────────────────────────────────────────────────────────────────────

set -e

LLAMA_PORT="${NIBLIT_LLAMA_PORT:-8080}"
N_THREADS="${NIBLIT_GGUF_N_THREADS:-4}"
CTX_SIZE="${NIBLIT_GGUF_N_CTX:-4096}"
TUNNEL_TOOL="${NIBLIT_TUNNEL_TOOL:-}"
FLY_APP="${FLY_APP_NAME:-niblit}"

# ── Locate llama-server binary ────────────────────────────────────────────────
if [ -n "${NIBLIT_LLAMA_BINARY:-}" ] && [ -x "$NIBLIT_LLAMA_BINARY" ]; then
    LLAMA_BIN="$NIBLIT_LLAMA_BINARY"
elif command -v llama-server &>/dev/null; then
    LLAMA_BIN=$(command -v llama-server)
elif [ -x "$HOME/llama.cpp/build/bin/llama-server" ]; then
    LLAMA_BIN="$HOME/llama.cpp/build/bin/llama-server"
elif [ -x "/data/data/com.termux/files/home/llama.cpp/build/bin/llama-server" ]; then
    LLAMA_BIN="/data/data/com.termux/files/home/llama.cpp/build/bin/llama-server"
else
    echo "❌ llama-server binary not found."
    echo ""
    echo "   Build it from source in Termux:"
    echo "     cd ~"
    echo "     git clone https://github.com/ggml-org/llama.cpp"
    echo "     cd llama.cpp && mkdir -p build && cd build"
    echo "     cmake .. -DLLAMA_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF"
    echo "     cmake --build . -j1"
    echo ""
    echo "   Or download a pre-built release and place it in ~/llama.cpp/build/bin/"
    exit 1
fi
echo "✅ llama-server: $LLAMA_BIN"

# ── Locate GGUF model ─────────────────────────────────────────────────────────
if [ -n "${NIBLIT_GGUF_MODEL_PATH:-}" ] && [ -f "$NIBLIT_GGUF_MODEL_PATH" ]; then
    MODEL_FILE="$NIBLIT_GGUF_MODEL_PATH"
else
    # Search common Termux model locations using find to handle missing dirs safely
    MODEL_FILE=""
    for search_dir in \
        "$HOME/models" \
        "/data/data/com.termux/files/home/models"; do
        if [ -d "$search_dir" ]; then
            found=$(find "$search_dir" -maxdepth 1 -name "*.gguf" -type f 2>/dev/null | head -1)
            if [ -n "$found" ]; then
                MODEL_FILE="$found"
                break
            fi
        fi
    done
    # Prefer known model names if multiple exist
    for candidate in \
        "$HOME/models/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
        "$HOME/models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf" \
        "$HOME/models/qwen2.5-1.5b-instruct-q4_k_m.gguf" \
        "$HOME/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf"; do
        if [ -f "$candidate" ]; then
            MODEL_FILE="$candidate"
            break
        fi
    done
fi

if [ -z "${MODEL_FILE:-}" ] || [ ! -f "$MODEL_FILE" ]; then
    echo "❌ No GGUF model found."
    echo ""
    echo "   Download one with:"
    echo "     python /app/tools/install_local_qwen_model.py"
    echo ""
    echo "   Or set the path manually:"
    echo "     export NIBLIT_GGUF_MODEL_PATH=~/models/your-model.gguf"
    exit 1
fi
echo "✅ Model:         $MODEL_FILE"

# ── Detect tunnel tool ────────────────────────────────────────────────────────
if [ -z "$TUNNEL_TOOL" ]; then
    if command -v cloudflared &>/dev/null; then
        TUNNEL_TOOL="cloudflared"
    elif command -v ngrok &>/dev/null; then
        TUNNEL_TOOL="ngrok"
    else
        TUNNEL_TOOL="none"
    fi
fi
echo "✅ Tunnel tool:   ${TUNNEL_TOOL}"
echo ""

# ── Start llama-server ────────────────────────────────────────────────────────
echo "🚀 Starting llama-server on 0.0.0.0:${LLAMA_PORT}..."
"$LLAMA_BIN" \
    --host 0.0.0.0 \
    --port "$LLAMA_PORT" \
    --model "$MODEL_FILE" \
    --ctx-size "$CTX_SIZE" \
    --threads "$N_THREADS" \
    -np 1 &
LLAMA_PID=$!
echo "   PID: ${LLAMA_PID}"

# Wait for llama-server to be ready
echo "   Waiting for llama-server to be ready..."
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${LLAMA_PORT}/health" >/dev/null 2>&1; then
        echo "✅ llama-server ready"
        break
    fi
    sleep 2
done

# ── Start tunnel ──────────────────────────────────────────────────────────────
PUBLIC_URL=""

if [ "$TUNNEL_TOOL" = "cloudflared" ]; then
    echo ""
    echo "🌐 Starting Cloudflare Tunnel..."
    CF_LOG=$(mktemp)
    # Use --no-autoupdate to prevent update prompts breaking the URL capture
    cloudflared tunnel --url "http://localhost:${LLAMA_PORT}" --no-autoupdate >"$CF_LOG" 2>&1 &
    CF_PID=$!
    echo "   cloudflared PID: ${CF_PID}"
    echo "   Waiting for tunnel URL..."
    for i in $(seq 1 30); do
        PUBLIC_URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1) || true
        [ -n "$PUBLIC_URL" ] && break
        sleep 2
    done
    if [ -z "$PUBLIC_URL" ]; then
        echo "⚠️  Could not extract tunnel URL automatically."
        echo "   Check cloudflared output in: $CF_LOG"
        echo "   Copy the https://...trycloudflare.com URL shown there."
    fi

elif [ "$TUNNEL_TOOL" = "ngrok" ]; then
    echo ""
    echo "🌐 Starting ngrok tunnel..."
    ngrok http "$LLAMA_PORT" --log=/tmp/ngrok.log &
    NGROK_PID=$!
    echo "   ngrok PID: ${NGROK_PID}"
    sleep 6
    PUBLIC_URL=$(
        curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | python3 -c "
import sys, json
tunnels = json.load(sys.stdin).get('tunnels', [])
https = [t['public_url'] for t in tunnels if t.get('public_url','').startswith('https')]
print(https[0] if https else '')
" 2>/dev/null
    ) || true
    if [ -z "$PUBLIC_URL" ]; then
        echo "⚠️  Could not read ngrok URL from local API."
        echo "   Check the ngrok dashboard or /tmp/ngrok.log for the public URL."
    fi

else
    echo ""
    echo "⚠️  No tunnel tool available."
    echo "   Install cloudflared:  pkg install cloudflared"
    echo "   Then re-run this script."
    echo ""
    echo "   Alternatives if your device is reachable from Fly's private network:"
    echo "     fly wireguard create   # connects Termux to Fly's WireGuard VPN"
    echo "     # Then set NIBLIT_LLAMA_SERVER_URL to your Termux WireGuard IP"
fi

# ── Print final instructions ──────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "  Niblit Termux Inference Server  ·  Running"
echo "════════════════════════════════════════════════════════════════════"
echo "  llama-server : http://127.0.0.1:${LLAMA_PORT}"
echo "  Model        : $(basename "$MODEL_FILE")"
if [ -n "$PUBLIC_URL" ]; then
    echo "  Public URL   : $PUBLIC_URL"
    echo ""
    echo "  ✅ Run these commands on your LAPTOP to wire Fly.io to Termux:"
    echo ""
    echo "     fly secrets set NIBLIT_LLAMA_SERVER_URL=${PUBLIC_URL} -a ${FLY_APP}"
    echo "     fly secrets set NIBLIT_GGUF_BACKEND=http -a ${FLY_APP}"
    echo ""
    echo "  Fly will restart automatically and use your Termux device for LLM"
    echo "  inference.  Keep this script running while Fly is active."
    echo ""
    echo "  To revert to HF cloud LLM:"
    echo "     fly secrets unset NIBLIT_LLAMA_SERVER_URL -a ${FLY_APP}"
else
    echo ""
    echo "  ⚠️  Set the public URL as a Fly secret once you have it:"
    echo ""
    echo "     fly secrets set NIBLIT_LLAMA_SERVER_URL=https://YOUR_TUNNEL_URL -a ${FLY_APP}"
    echo "     fly secrets set NIBLIT_GGUF_BACKEND=http -a ${FLY_APP}"
fi
echo "════════════════════════════════════════════════════════════════════"
echo "  Press Ctrl+C to stop all services."
echo ""

# ── Wait for all background processes ────────────────────────────────────────
wait
