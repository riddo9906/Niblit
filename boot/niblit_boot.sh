#!/usr/bin/env bash
# =============================================================================
# boot/niblit_boot.sh — Universal Niblit Startup Script
# =============================================================================
# Launched by the OS service (systemd, Termux:Boot, LaunchAgent, Task Scheduler).
# Also usable manually:  bash boot/niblit_boot.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIBLIT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON="${PYTHON:-$(which python3 2>/dev/null || which python)}"

export NIBLIT_BOOT_MODE="${NIBLIT_BOOT_MODE:-service}"
export PYTHONUNBUFFERED=1

# ── Data directory (writable, platform-aware) ──────────────────────────────
if [[ -z "${NIBLIT_DATA_DIR:-}" ]]; then
    if [[ -d "/data/data/com.termux" ]]; then
        export NIBLIT_DATA_DIR="$HOME/niblit_data"
    elif [[ -n "${FLY_APP_NAME:-}" ]] || [[ -d "/data" && -w "/data" ]]; then
        export NIBLIT_DATA_DIR="/data"
    else
        export NIBLIT_DATA_DIR="$HOME/.niblit"
    fi
fi
mkdir -p "$NIBLIT_DATA_DIR"

# ── Log file ──────────────────────────────────────────────────────────────
LOG_FILE="${NIBLIT_DATA_DIR}/niblit_boot.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"; }

log "=== Niblit Boot ==="
log "Root   : $NIBLIT_ROOT"
log "Python : $PYTHON"
log "Data   : $NIBLIT_DATA_DIR"
log "Mode   : $NIBLIT_BOOT_MODE"

# ── Platform detection ─────────────────────────────────────────────────────
uname_s="$(uname -s 2>/dev/null || echo Unknown)"
uname_m="$(uname -m 2>/dev/null || echo unknown)"
log "Platform: $uname_s / $uname_m"

# Termux wake-lock (Android only)
if [[ -d "/data/data/com.termux" ]]; then
    termux-wake-lock 2>/dev/null || true
    log "Termux wake-lock acquired"
fi

# ── Change to Niblit root and launch ──────────────────────────────────────
cd "$NIBLIT_ROOT"

log "Starting Niblit..."
exec "$PYTHON" app.py
