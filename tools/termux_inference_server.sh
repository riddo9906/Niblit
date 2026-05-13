#!/usr/bin/env bash
# tools/termux_inference_server.sh
# Hardened runtime launcher for Termux / portable runtime bridge.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="niblit"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="${2:-}"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: bash $0 [--profile niblit|cloud-server|termux-local]" >&2
            exit 1
            ;;
    esac
done

# shellcheck disable=SC1091
source "$SCRIPT_DIR/runtime_profiles/profile_loader.sh"
niblit_apply_profile "$PROFILE"

LLAMA_PORT="${NIBLIT_LLAMA_PORT:-8080}"
N_THREADS="${NIBLIT_GGUF_N_THREADS:-4}"
CTX_SIZE="${NIBLIT_GGUF_N_CTX:-4096}"
TUNNEL_TOOL="${NIBLIT_TUNNEL_TOOL:-}"
FLY_APP="${FLY_APP_NAME:-niblit}"
PUBLIC_URL_OVERRIDE="${PUBLIC_URL:-${NIBLIT_PUBLIC_URL:-}}"

# Ω.7 governance/runtime signals
RUNTIME_MODE="${NIBLIT_RUNTIME_MODE:-normal}"
SURVIVAL_MODE="${NIBLIT_SURVIVAL_MODE:-false}"
ATTENTION_PRESSURE="${NIBLIT_ATTENTION_PRESSURE:-0.0}"
THERMAL_STATE="${NIBLIT_THERMAL_STATE:-unknown}"
RESOURCE_PRESSURE="${NIBLIT_RESOURCE_PRESSURE:-normal}"
COHERENCE_MODE="${NIBLIT_COHERENCE_MODE:-stable}"

LLAMA_PID=""
CF_PID=""
NGROK_PID=""
CF_LOG=""
NGROK_LOG=""

_json_escape() {
    python3 - <<'PY' "$1"
import json,sys
print(json.dumps(sys.argv[1]))
PY
}

log_event() {
    local level="$1"
    local event="$2"
    local msg="$3"
    local ts
    ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf '{"ts":"%s","level":"%s","event":"%s","message":%s,"profile":"%s","runtime_mode":"%s","survival_mode":"%s","attention_pressure":"%s","thermal":"%s","resource_pressure":"%s","coherence_mode":"%s"}\n' \
        "$ts" "$level" "$event" "$(_json_escape "$msg")" "$PROFILE" "$RUNTIME_MODE" "$SURVIVAL_MODE" "$ATTENTION_PRESSURE" "$THERMAL_STATE" "$RESOURCE_PRESSURE" "$COHERENCE_MODE"
}

cleanup() {
    local code=$?
    log_event "INFO" "runtime.cleanup.begin" "Shutting down background processes"

    for pid in "$LLAMA_PID" "$CF_PID" "$NGROK_PID"; do
        if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            sleep 0.5
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    [ -n "${CF_LOG:-}" ] && [ -f "$CF_LOG" ] && rm -f "$CF_LOG" || true
    [ -n "${NGROK_LOG:-}" ] && [ -f "$NGROK_LOG" ] && rm -f "$NGROK_LOG" || true

    if [ "$code" -eq 0 ]; then
        log_event "INFO" "runtime.cleanup.complete" "Clean shutdown complete"
    else
        log_event "ERROR" "runtime.cleanup.error" "Shutdown due to error"
    fi
    exit "$code"
}
trap cleanup EXIT INT TERM

_is_server_binary() {
    local bin="$1"
    local name
    name=$(basename "$bin")
    if echo "$name" | grep -qi "server"; then
        return 0
    fi
    "$bin" --help 2>&1 | grep -q -- "--host"
}

_find_server_in_dir() {
    local dir="$1"
    [ -x "$dir/llama-server" ] && echo "$dir/llama-server"
}

LLAMA_BIN=""
if [ -n "${NIBLIT_LLAMA_BINARY:-}" ] && [ -x "$NIBLIT_LLAMA_BINARY" ]; then
    LLAMA_BIN="$NIBLIT_LLAMA_BINARY"
    if ! _is_server_binary "$LLAMA_BIN"; then
        nearby="$(_find_server_in_dir "$(dirname "$LLAMA_BIN")")"
        if [ -n "$nearby" ]; then
            LLAMA_BIN="$nearby"
            log_event "WARN" "runtime.binary.autocorrect" "NIBLIT_LLAMA_BINARY was not server; switched to sibling llama-server"
        else
            log_event "ERROR" "runtime.binary.invalid" "NIBLIT_LLAMA_BINARY is not llama-server"
            exit 1
        fi
    fi
elif [ -x "$HOME/llama.cpp/build/bin/llama-server" ]; then
    LLAMA_BIN="$HOME/llama.cpp/build/bin/llama-server"
elif [ -x "/data/data/com.termux/files/home/llama.cpp/build/bin/llama-server" ]; then
    LLAMA_BIN="/data/data/com.termux/files/home/llama.cpp/build/bin/llama-server"
elif command -v llama-server >/dev/null 2>&1; then
    LLAMA_BIN="$(command -v llama-server)"
fi

if [ -z "$LLAMA_BIN" ]; then
    log_event "ERROR" "runtime.binary.missing" "llama-server binary not found"
    exit 1
fi

MODEL_FILE=""
if [ -n "${NIBLIT_GGUF_MODEL_PATH:-}" ] && [ -f "$NIBLIT_GGUF_MODEL_PATH" ]; then
    MODEL_FILE="$NIBLIT_GGUF_MODEL_PATH"
else
    for search_dir in "$HOME/models" "/data/data/com.termux/files/home/models"; do
        if [ -d "$search_dir" ]; then
            found=$(find "$search_dir" -maxdepth 1 -name "*.gguf" -type f 2>/dev/null | head -1 || true)
            if [ -n "$found" ]; then
                MODEL_FILE="$found"
                break
            fi
        fi
    done
fi

if [ -z "$MODEL_FILE" ] || [ ! -f "$MODEL_FILE" ]; then
    log_event "ERROR" "runtime.model.missing" "No GGUF model found; run python $REPO_ROOT/tools/install_local_qwen_model.py --setup"
    exit 1
fi

if [ -z "$TUNNEL_TOOL" ]; then
    if command -v cloudflared >/dev/null 2>&1; then
        TUNNEL_TOOL="cloudflared"
    elif command -v ngrok >/dev/null 2>&1; then
        TUNNEL_TOOL="ngrok"
    else
        TUNNEL_TOOL="none"
    fi
fi

log_event "INFO" "runtime.model.selected" "Model=$(basename "$MODEL_FILE")"
log_event "INFO" "runtime.backend.state" "Backend=${NIBLIT_GGUF_BACKEND:-subprocess} tunnel_tool=$TUNNEL_TOOL"
log_event "INFO" "runtime.mode.changed" "EVENT_RUNTIME_MODE_CHANGED -> $RUNTIME_MODE"
log_event "INFO" "execution.envelope.published" "EVENT_EXECUTION_ENVELOPE_PUBLISHED (tooling telemetry)"
log_event "INFO" "resource.adapted" "EVENT_RESOURCE_ADAPTED pressure=$RESOURCE_PRESSURE thermal=$THERMAL_STATE"
log_event "INFO" "attention.allocated" "EVENT_ATTENTION_ALLOCATED pressure=$ATTENTION_PRESSURE"
log_event "INFO" "reflection.complete" "EVENT_REFLECTION_COMPLETE coherence_mode=$COHERENCE_MODE"

"$LLAMA_BIN" \
    --host 0.0.0.0 \
    --port "$LLAMA_PORT" \
    --model "$MODEL_FILE" \
    --ctx-size "$CTX_SIZE" \
    --threads "$N_THREADS" \
    -np 1 &
LLAMA_PID=$!
log_event "INFO" "runtime.backend.started" "llama-server pid=$LLAMA_PID url=http://127.0.0.1:$LLAMA_PORT"

readiness_probe() {
    local endpoint="$1"
    curl -sf "http://127.0.0.1:${LLAMA_PORT}${endpoint}" >/dev/null 2>&1
}

probe_order=("/health" "/v1/models" "/props" "/")
ready=0
start_ts=$(date +%s)
for attempt in $(seq 1 60); do
    for endpoint in "${probe_order[@]}"; do
        if readiness_probe "$endpoint"; then
            now=$(date +%s)
            delta=$((now - start_ts))
            log_event "INFO" "runtime.readiness.ok" "probe=$endpoint attempt=$attempt readiness_s=${delta}"
            ready=1
            break
        fi
    done
    [ "$ready" -eq 1 ] && break

    if ! kill -0 "$LLAMA_PID" 2>/dev/null; then
        log_event "ERROR" "runtime.backend.crash" "llama-server process exited before readiness"
        exit 1
    fi
    if [ $((attempt % 10)) -eq 0 ]; then
        now=$(date +%s)
        delta=$((now - start_ts))
        log_event "WARN" "runtime.readiness.retry" "attempt=$attempt elapsed_s=$delta probes=${probe_order[*]}"
    fi
    sleep 2
done

if [ "$ready" -ne 1 ]; then
    log_event "ERROR" "runtime.readiness.timeout" "Failed readiness probes: ${probe_order[*]}"
    exit 1
fi

PUBLIC_URL="${PUBLIC_URL_OVERRIDE}"
if [ -n "$PUBLIC_URL" ]; then
    log_event "INFO" "runtime.tunnel.override" "Using PUBLIC_URL override: $PUBLIC_URL"
fi

if [ -z "$PUBLIC_URL" ]; then
    if [ "$TUNNEL_TOOL" = "cloudflared" ]; then
        CF_LOG="$(mktemp)"
        cloudflared tunnel --url "http://localhost:${LLAMA_PORT}" --no-autoupdate >"$CF_LOG" 2>&1 &
        CF_PID=$!
        log_event "INFO" "runtime.tunnel.start" "cloudflared pid=$CF_PID"

        for _ in $(seq 1 40); do
            PUBLIC_URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1 || true)
            [ -n "$PUBLIC_URL" ] && break
            sleep 2
        done

        if [ -z "$PUBLIC_URL" ]; then
            if kill -0 "$CF_PID" 2>/dev/null; then
                log_event "ERROR" "runtime.tunnel.discovery_failed" "cloudflared alive but URL not discovered"
                tail -n 30 "$CF_LOG" || true
                echo "Hint: open cloudflared log and copy trycloudflare URL manually: $CF_LOG"
            else
                log_event "ERROR" "runtime.tunnel.process_dead" "cloudflared exited unexpectedly"
                tail -n 30 "$CF_LOG" || true
                echo "Hint: reinstall cloudflared (pkg install cloudflared) and retry."
            fi
        fi

    elif [ "$TUNNEL_TOOL" = "ngrok" ]; then
        NGROK_LOG="$(mktemp)"
        ngrok http "$LLAMA_PORT" --log="$NGROK_LOG" &
        NGROK_PID=$!
        log_event "INFO" "runtime.tunnel.start" "ngrok pid=$NGROK_PID"
        sleep 6
        PUBLIC_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import json,sys
try:
 d=json.load(sys.stdin)
 t=[x.get("public_url","") for x in d.get("tunnels",[]) if str(x.get("public_url","")).startswith("https")]
 print(t[0] if t else "")
except Exception:
 print("")')

        if [ -z "$PUBLIC_URL" ]; then
            if kill -0 "$NGROK_PID" 2>/dev/null; then
                log_event "ERROR" "runtime.tunnel.discovery_failed" "ngrok alive but URL not discovered"
                tail -n 30 "$NGROK_LOG" || true
                echo "Hint: check ngrok dashboard http://127.0.0.1:4040/status"
            else
                log_event "ERROR" "runtime.tunnel.process_dead" "ngrok exited unexpectedly"
                tail -n 30 "$NGROK_LOG" || true
                echo "Hint: run 'ngrok config add-authtoken <token>' and retry."
            fi
        fi

    else
        log_event "WARN" "runtime.tunnel.none" "No tunnel tool enabled"
    fi
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "  Niblit Runtime Inference Bridge · Running"
echo "════════════════════════════════════════════════════════════════════"
echo "  Profile      : $PROFILE"
echo "  Repo root    : $REPO_ROOT"
echo "  llama-server : http://127.0.0.1:${LLAMA_PORT}"
echo "  Model        : $(basename "$MODEL_FILE")"
if [ -n "$PUBLIC_URL" ]; then
    echo "  Public URL   : $PUBLIC_URL"
    echo ""
    echo "  fly secrets set NIBLIT_LLAMA_SERVER_URL=${PUBLIC_URL} -a ${FLY_APP}"
    echo "  fly secrets set NIBLIT_GGUF_BACKEND=http -a ${FLY_APP}"
else
    echo "  Public URL   : (not discovered)"
    echo ""
    echo "  Set manually when available:"
    echo "  fly secrets set NIBLIT_LLAMA_SERVER_URL=https://YOUR_TUNNEL_URL -a ${FLY_APP}"
    echo "  fly secrets set NIBLIT_GGUF_BACKEND=http -a ${FLY_APP}"
fi
echo "════════════════════════════════════════════════════════════════════"
echo "Press Ctrl+C to stop all services."

wait
