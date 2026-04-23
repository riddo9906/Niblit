#!/bin/sh
# assets/setup_niblit.sh
# ─────────────────────────────────────────────────────────────────────────────
# Niblit APK — in-proot setup script
#
# This script runs INSIDE the proot Linux environment on first launch.
# It installs all Python and system packages that Niblit needs to operate
# fully offline and independently of the host Android system.
#
# Usage (from Python via ProotEnvironment.run):
#     env.run("sh /root/niblit/assets/setup_niblit.sh")
#
# Or manually in the Niblit terminal tab:
#     sh /root/niblit/assets/setup_niblit.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

log() { echo "[niblit-setup] $*"; }
ok()  { echo "[niblit-setup] ✅ $*"; }
err() { echo "[niblit-setup] ❌ $*" >&2; }

log "=== Niblit APK Environment Setup ==="
log "Running as: $(id)"
log "Alpine version: $(cat /etc/alpine-release 2>/dev/null || echo unknown)"
log ""

# ── 1. Update package index ───────────────────────────────────────────────────
log "Updating package index…"
apk update --no-progress 2>&1 | tail -3
ok "Package index updated"

# ── 2. Install system dependencies ───────────────────────────────────────────
log "Installing system tools…"
apk add --no-progress \
    python3 \
    py3-pip \
    py3-setuptools \
    py3-wheel \
    py3-cryptography \
    git \
    curl \
    wget \
    bash \
    coreutils \
    findutils \
    grep \
    sed \
    gawk \
    tar \
    xz \
    bzip2 \
    gzip \
    unzip \
    openssl \
    ca-certificates \
    libffi \
    libffi-dev \
    musl-dev \
    gcc \
    g++ \
    make \
    2>&1 | tail -5
ok "System tools installed"

# ── 3. Upgrade pip ────────────────────────────────────────────────────────────
log "Upgrading pip…"
python3 -m pip install --upgrade --quiet pip
ok "pip upgraded to $(pip3 --version | awk '{print $2}')"

# ── 4. Install core Python packages ──────────────────────────────────────────
log "Installing core Python packages…"
pip3 install --no-cache-dir --quiet \
    requests \
    python-dotenv \
    aiohttp \
    duckduckgo-search \
    beautifulsoup4 \
    lxml \
    numpy \
    scipy \
    scikit-learn \
    2>&1 | tail -5
ok "Core packages installed"

# ── 5. Install NLP / AI dependencies ─────────────────────────────────────────
log "Installing NLP and AI packages (this may take a while)…"
pip3 install --no-cache-dir --quiet \
    transformers \
    tokenizers \
    sentencepiece \
    huggingface_hub \
    torch \
    2>&1 | tail -5 || log "torch install failed — will use CPU fallback only"
ok "NLP packages installed (or skipped)"

# ── 6. Install Niblit-specific packages ──────────────────────────────────────
log "Installing Niblit runtime packages…"
pip3 install --no-cache-dir --quiet \
    sqlite-utils \
    faiss-cpu \
    sentence-transformers \
    qdrant-client \
    2>&1 | tail -5 || log "Some optional packages skipped"
ok "Niblit runtime packages done"

# ── 7. Write niblit launcher script ──────────────────────────────────────────
log "Writing niblit launcher…"
mkdir -p /usr/local/bin
cat > /usr/local/bin/niblit << 'LAUNCHER'
#!/bin/sh
# Niblit launcher — runs inside proot
exec python3 /root/niblit/main.py "$@"
LAUNCHER
chmod +x /usr/local/bin/niblit
ok "niblit launcher written to /usr/local/bin/niblit"

# ── 8. Verify installation ────────────────────────────────────────────────────
log "Verifying installation…"
python3 --version
pip3 --version
python3 -c "import requests; print('requests OK')"
python3 -c "import dotenv; print('dotenv OK')"
log ""
ok "=== Setup complete! Type 'niblit' to start the Niblit agent. ==="
