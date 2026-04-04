#!/usr/bin/env bash
# =============================================================================
# boot/install.sh — Niblit One-Command Installer
# =============================================================================
# Works on:
#   • Linux (any distro, x86_64 or ARM)
#   • Raspberry Pi / Jetson / Embedded ARM
#   • Android / Termux
#   • macOS (via LaunchAgent)
#
# Usage:
#   bash boot/install.sh            # installs for current user
#   sudo bash boot/install.sh       # installs system-wide (Linux only)
# =============================================================================

set -euo pipefail

NIBLIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$(which python3 || which python)}"
SERVICE_NAME="niblit"

info()  { echo -e "\033[1;34m[niblit]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[niblit]\033[0m ✅ $*"; }
warn()  { echo -e "\033[1;33m[niblit]\033[0m ⚠️  $*"; }
err()   { echo -e "\033[1;31m[niblit]\033[0m ❌ $*"; exit 1; }

info "Installing Niblit from: $NIBLIT_ROOT"
info "Python: $PYTHON"

# ── Detect platform ───────────────────────────────────────────────────────────
PLATFORM="linux"
if [[ -d "/data/data/com.termux" ]] || echo "${PREFIX:-}" | grep -q "termux"; then
    PLATFORM="termux"
elif [[ "$(uname)" == "Darwin" ]]; then
    PLATFORM="macos"
fi
info "Platform detected: $PLATFORM"

# ── Install Python dependencies ───────────────────────────────────────────────
if [[ -f "$NIBLIT_ROOT/requirements.txt" ]]; then
    info "Installing Python requirements..."
    "$PYTHON" -m pip install --upgrade pip --quiet
    "$PYTHON" -m pip install -r "$NIBLIT_ROOT/requirements.txt" --quiet || warn "Some packages failed — Niblit will run in degraded mode"
    ok "Python requirements installed"
fi

# ── Platform-specific service installation ────────────────────────────────────

install_systemd_user() {
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Niblit AI System — autonomous learning & OS integration layer
After=network.target

[Service]
Type=simple
WorkingDirectory=${NIBLIT_ROOT}
ExecStart=${PYTHON} ${NIBLIT_ROOT}/app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"
Environment="NIBLIT_BOOT_MODE=service"

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable "${SERVICE_NAME}.service" 2>/dev/null || true
    systemctl --user start  "${SERVICE_NAME}.service" 2>/dev/null || true
    ok "Niblit systemd user service installed and started"
    info "Control: systemctl --user {start|stop|restart|status} niblit"
}

install_systemd_system() {
    cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Niblit AI System — autonomous learning & OS integration layer
After=network.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${NIBLIT_ROOT}
ExecStart=${PYTHON} ${NIBLIT_ROOT}/app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"
Environment="NIBLIT_BOOT_MODE=service"

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
    systemctl start  "${SERVICE_NAME}.service"
    ok "Niblit system-wide systemd service installed and started"
    info "Control: sudo systemctl {start|stop|restart|status} niblit"
}

install_termux() {
    BOOT_DIR="$HOME/.termux/boot"
    mkdir -p "$BOOT_DIR"
    SCRIPT="$BOOT_DIR/niblit_start.sh"
    cat > "$SCRIPT" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd "${NIBLIT_ROOT}"
export NIBLIT_BOOT_MODE=service
nohup "${PYTHON}" app.py >> "\$HOME/niblit.log" 2>&1 &
EOF
    chmod +x "$SCRIPT"
    ok "Termux boot hook installed: $SCRIPT"
    warn "Install Termux:Boot from F-Droid and grant it permission to run on device boot"
}

install_macos() {
    LABEL="io.niblit.daemon"
    PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
    mkdir -p "$(dirname "$PLIST")"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${NIBLIT_ROOT}/app.py</string>
    </array>
    <key>WorkingDirectory</key>  <string>${NIBLIT_ROOT}</string>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NIBLIT_BOOT_MODE</key><string>service</string>
    </dict>
    <key>StandardOutPath</key>   <string>${HOME}/Library/Logs/niblit.log</string>
    <key>StandardErrorPath</key> <string>${HOME}/Library/Logs/niblit.err</string>
</dict>
</plist>
EOF
    launchctl load "$PLIST" 2>/dev/null || true
    ok "macOS LaunchAgent installed: $PLIST"
}

case "$PLATFORM" in
    termux) install_termux ;;
    macos)  install_macos  ;;
    linux)
        if [[ "$(id -u)" -eq 0 ]]; then
            install_systemd_system
        else
            install_systemd_user
        fi
        ;;
    *) warn "Unknown platform '$PLATFORM' — Niblit not installed as a service" ;;
esac

# ── Create data directory ─────────────────────────────────────────────────────
DATA_DIR="${NIBLIT_DATA_DIR:-$HOME/.niblit}"
mkdir -p "$DATA_DIR"
ok "Niblit data directory: $DATA_DIR"

echo ""
ok "Niblit installation complete!"
info "Run 'python app.py' to start manually, or reboot to test auto-start."
info "Logs: journalctl --user -u niblit -f  (Linux) | ~/niblit.log (Termux/macOS)"
