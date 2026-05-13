#!/usr/bin/env bash
# Portable llama runtime binary installer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="niblit"
INSTALL_DIR="/usr/local/bin"
ACTION="${INSTALL_ACTION:-upgrade}" # upgrade|overwrite|skip

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile) PROFILE="${2:-}"; shift 2 ;;
        --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
        --action) ACTION="${2:-}"; shift 2 ;;
        *)
            echo "Unknown arg: $1" >&2
            echo "Usage: bash $0 [--profile <name>] [--install-dir <path>] [--action upgrade|overwrite|skip]" >&2
            exit 1
            ;;
    esac
done

# shellcheck disable=SC1091
source "$SCRIPT_DIR/runtime_profiles/profile_loader.sh"
niblit_apply_profile "$PROFILE"

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[install_llama_server] Missing required tool: $cmd" >&2
        exit 1
    fi
}

for dep in curl unzip tar python3; do
    require_cmd "$dep"
done

ARCH="$(uname -m)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
IS_TERMUX="false"
IS_FLY="false"
[ -d "/data/data/com.termux/files/usr" ] && IS_TERMUX="true"
[ -n "${FLY_APP_NAME:-}" ] || [ -n "${FLY_ALLOC_ID:-}" ] && IS_FLY="true"

ARCH_SUFFIX=""
case "$ARCH" in
    x86_64|amd64) ARCH_SUFFIX="x64" ;;
    aarch64|arm64) ARCH_SUFFIX="arm64" ;;
    armv7l|armv8l) ARCH_SUFFIX="arm" ;;
    *)
        echo "[install_llama_server] Unsupported architecture: $ARCH" >&2
        exit 1
        ;;
esac

if [ -x "$INSTALL_DIR/llama-server" ]; then
    case "$ACTION" in
        skip)
            echo "[install_llama_server] Existing install found at $INSTALL_DIR/llama-server, action=skip"
            exit 0
            ;;
        overwrite|upgrade)
            echo "[install_llama_server] Existing install found, action=$ACTION"
            ;;
        *)
            echo "[install_llama_server] Invalid --action '$ACTION' (expected upgrade|overwrite|skip)" >&2
            exit 1
            ;;
    esac
fi

if [ -n "${LLAMA_CPP_VERSION:-}" ]; then
    RELEASE_TAG="$LLAMA_CPP_VERSION"
else
    RELEASE_TAG=$(curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest | python3 -c "import json,sys;print(json.load(sys.stdin)['tag_name'])")
fi

if [ -z "$RELEASE_TAG" ]; then
    echo "[install_llama_server] Could not resolve release tag" >&2
    exit 1
fi

TMPDIR=$(mktemp -d)
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

ZIP_ASSET="llama-${RELEASE_TAG}-bin-ubuntu-${ARCH_SUFFIX}.zip"
TAR_ASSET="llama-${RELEASE_TAG}-bin-ubuntu-${ARCH_SUFFIX}.tar.gz"
BASE_URL="https://github.com/ggml-org/llama.cpp/releases/download/${RELEASE_TAG}"

DOWNLOAD_PATH=""
if curl -fsSL --retry 3 --retry-delay 2 "${BASE_URL}/${ZIP_ASSET}" -o "$TMPDIR/llama.zip"; then
    DOWNLOAD_PATH="$TMPDIR/llama.zip"
    unzip -q "$DOWNLOAD_PATH" -d "$TMPDIR/unpack"
elif curl -fsSL --retry 3 --retry-delay 2 "${BASE_URL}/${TAR_ASSET}" -o "$TMPDIR/llama.tar.gz"; then
    DOWNLOAD_PATH="$TMPDIR/llama.tar.gz"
    tar -xzf "$DOWNLOAD_PATH" -C "$TMPDIR"
    mkdir -p "$TMPDIR/unpack"
    find "$TMPDIR" -maxdepth 2 -type f -name "llama-*" -exec cp {} "$TMPDIR/unpack/" \;
else
    echo "[install_llama_server] Failed to download release assets for ${RELEASE_TAG}/${ARCH_SUFFIX}" >&2
    echo "[install_llama_server] Checked: ${ZIP_ASSET} and ${TAR_ASSET}" >&2
    exit 1
fi

BINARY="$(find "$TMPDIR" -type f -name "llama-server" | head -1 || true)"
if [ -z "$BINARY" ]; then
    echo "[install_llama_server] llama-server not found in downloaded archive" >&2
    find "$TMPDIR" -type f | head -30
    exit 1
fi

mkdir -p "$INSTALL_DIR"
cp "$BINARY" "$INSTALL_DIR/llama-server"
chmod +x "$INSTALL_DIR/llama-server"

echo "[install_llama_server] ✅ Installed: $INSTALL_DIR/llama-server"
"$INSTALL_DIR/llama-server" --version 2>&1 | head -2 || true

echo ""
echo "Environment summary:"
echo "  profile       : $PROFILE"
echo "  release       : $RELEASE_TAG"
echo "  os/arch       : $OS/$ARCH"
echo "  matrix        : ${ARCH_SUFFIX} termux=${IS_TERMUX} fly=${IS_FLY}"

echo ""
echo "Next steps:"
echo "  - Set NIBLIT_LLAMA_BINARY=$INSTALL_DIR/llama-server"
echo "  - Ensure NIBLIT_GGUF_MODEL_PATH points to a valid GGUF model"
echo "  - Optional override next run: export LLAMA_CPP_VERSION=<tag>"
