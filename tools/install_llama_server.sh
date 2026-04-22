#!/usr/bin/env bash
# tools/install_llama_server.sh — Install llama-server binary on Fly.io
#
# Run this ONCE from a fly ssh console session to put the llama-server binary
# inside the running container.  The binary survives for the lifetime of the
# current machine image (re-run after a fresh deploy replaces the machine).
#
# Usage (from your laptop):
#   fly ssh console -a niblit
#   bash /app/tools/install_llama_server.sh [INSTALL_DIR]
#
# INSTALL_DIR defaults to /usr/local/bin
#
# After installing, upload a GGUF model to /data/model.gguf and restart:
#   fly sftp shell -a niblit
#   put /local/path/to/model.gguf /data/model.gguf
#   fly machine restart -a niblit

set -e

INSTALL_DIR="${1:-/usr/local/bin}"

echo "[install_llama_server] ════════════════════════════════════"
echo "[install_llama_server]   llama-server installer for Fly.io"
echo "[install_llama_server] ════════════════════════════════════"

# ── Detect architecture ───────────────────────────────────────────────────────
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH_SUFFIX="x64" ;;
    aarch64) ARCH_SUFFIX="arm64" ;;
    *)
        echo "[install_llama_server] ❌ Unsupported architecture: ${ARCH}"
        exit 1
        ;;
esac
echo "[install_llama_server] Architecture: ${ARCH} → ${ARCH_SUFFIX}"

# ── Fetch latest release tag ──────────────────────────────────────────────────
echo "[install_llama_server] Fetching latest llama.cpp release tag..."
RELEASE_TAG=$(
    curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null
) || true

if [ -z "$RELEASE_TAG" ]; then
    echo "[install_llama_server] ❌ Could not fetch release tag."
    echo "   Check network connectivity from: fly ssh console -a niblit"
    exit 1
fi
echo "[install_llama_server] Release: ${RELEASE_TAG}"

# ── Build download URL ────────────────────────────────────────────────────────
ARCHIVE="llama-${RELEASE_TAG}-bin-ubuntu-${ARCH_SUFFIX}.zip"
URL="https://github.com/ggml-org/llama.cpp/releases/download/${RELEASE_TAG}/${ARCHIVE}"
echo "[install_llama_server] Downloading: ${URL}"

# ── Download and extract ──────────────────────────────────────────────────────
TMPDIR=$(mktemp -d)
# shellcheck disable=SC2064
trap "rm -rf ${TMPDIR}" EXIT

if ! curl -fsSL --retry 3 --retry-delay 3 "$URL" -o "${TMPDIR}/llama.zip"; then
    echo "[install_llama_server] ❌ Download failed."
    echo "   The release may not provide Ubuntu binaries for this architecture."
    echo "   Browse available assets at:"
    echo "     https://github.com/ggml-org/llama.cpp/releases/tag/${RELEASE_TAG}"
    exit 1
fi

cd "$TMPDIR"
unzip -q llama.zip

BINARY=$(find "$TMPDIR" -name "llama-server" -type f | head -1)
if [ -z "$BINARY" ]; then
    echo "[install_llama_server] ❌ llama-server binary not found in archive."
    echo "   Archive contents:"
    find "$TMPDIR" -type f | head -20
    exit 1
fi

# ── Install ───────────────────────────────────────────────────────────────────
cp "$BINARY" "${INSTALL_DIR}/llama-server"
chmod +x "${INSTALL_DIR}/llama-server"

echo "[install_llama_server] ✅ Installed: ${INSTALL_DIR}/llama-server"
"${INSTALL_DIR}/llama-server" --version 2>&1 | head -2 || true

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Next steps"
echo "════════════════════════════════════════════════════════════════"
echo "  1. Upload a GGUF model (from your laptop):"
echo ""
echo "       fly sftp shell -a niblit"
echo "       put /local/path/to/qwen2.5-0.5b-instruct-q4_k_m.gguf /data/model.gguf"
echo ""
echo "  2. Confirm the model path (default /data/model.gguf) is correct:"
echo ""
echo "       fly secrets set NIBLIT_GGUF_MODEL_PATH=/data/model.gguf -a niblit"
echo ""
echo "  3. Restart the machine to pick up the new binary + model:"
echo ""
echo "       fly machine restart -a niblit"
echo ""
echo "  Alternatively, use your Termux device as the inference backend"
echo "  (no local binary or model needed on Fly):"
echo ""
echo "       bash /app/tools/termux_inference_server.sh   # run on Termux"
echo ""
echo "════════════════════════════════════════════════════════════════"
