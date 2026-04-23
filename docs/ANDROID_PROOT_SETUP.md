# Android / proot-Ubuntu Two-Venv Setup

This guide shows how to run **Niblit** and **Freqtrade** side-by-side on
Android using Termux + proot-distro Ubuntu, with two separate Python
virtual environments.

---

## 1. Directory layout

```
~/
├── projects/
│   ├── Niblit/                 ← riddo9906/Niblit repo
│   └── niblit-lean-algos/      ← riddo9906/niblit-lean-algos repo
├── niblit-env/                 ← Python 3.10 venv  (Niblit service)
└── niblit-py311/               ← Python 3.11.9 venv (Freqtrade)
```

---

## 2. Prerequisites (Termux + proot-Ubuntu)

```bash
# In Termux
pkg update && pkg install proot-distro
proot-distro install ubuntu

# Enter proot Ubuntu shell (use this for all commands below)
proot-distro login ubuntu
```

Inside proot Ubuntu, ensure Python 3.10 and 3.11 are available:

```bash
sudo apt update
sudo apt install python3.10 python3.10-venv python3.11 python3.11-venv \
    git curl build-essential -y
```

---

## 3. Clone repositories

```bash
cd ~/projects
git clone https://github.com/riddo9906/Niblit.git Niblit
git clone https://github.com/riddo9906/niblit-lean-algos.git niblit-lean-algos
```

---

## 4. Create virtual environments

```bash
# Niblit — Python 3.10
python3.10 -m venv ~/niblit-env

# Freqtrade — Python 3.11.9
python3.11 -m venv ~/niblit-py311
```

---

## 5. Install Niblit (Android profile — no FAISS / torch)

```bash
source ~/niblit-env/bin/activate

cd ~/projects/Niblit

# Install the Android-safe requirements profile
pip install --upgrade pip
pip install -r requirements/android.txt
```

> **What's excluded by the android profile:**
> `faiss-cpu`, `sentence-transformers`, `transformers`, `accelerate`,
> `sentencepiece`, `safetensors`, `scrapy`, `docker`, `lean`, `scikit-learn`.
> Niblit starts fine without these — see fallback notes below.

---

## 6. Configure Niblit environment

```bash
cd ~/projects/Niblit
cp .env.example .env
```

Edit `.env` and set at minimum:

```ini
# Required for HuggingFace model downloads (optional features)
HF_TOKEN=hf_your_token_here

# Android profile: disables FAISS / sentence-transformers
NIBLIT_PROFILE=android

# Vector backend: numpy cosine-similarity (no FAISS needed)
NIBLIT_VECTOR_BACKEND=numpy

# Embeddings backend: none (no sentence-transformers needed)
NIBLIT_EMBEDDINGS_BACKEND=none

# Brain mode: local (offline-friendly)
NIBLIT_BRAIN_MODE=local
```

---

## 7. Start the Niblit service

```bash
source ~/niblit-env/bin/activate
cd ~/projects/Niblit

uvicorn app:app --host 127.0.0.1 --port 8000
```

Expected startup log lines (android profile):

```
INFO:VectorStore:[VectorStore] NIBLIT_PROFILE=android
INFO:VectorStore:[VectorStore] sentence-transformers not installed; using none embeddings backend
INFO:VectorStore:[VectorStore] FAISS not installed; using numpy cosine-similarity backend
INFO:     Application startup complete.
```

### Verify

```bash
# Quick health check
curl http://127.0.0.1:8000/health

# Test the trade signal endpoint
curl -s -X POST http://127.0.0.1:8000/trade/signal \
  -H "Content-Type: application/json" \
  -d '{"pair":"BTC/USDT","timeframe":"1h","last_candle":{"close":65000,"rsi":45}}'
```

Expected response:

```json
{
  "action": "hold",
  "confidence": 0.5,
  "metadata": {"source": "fallback", "pair": "BTC/USDT", "timeframe": "1h", "profile": "android"}
}
```

---

## 8. Install Freqtrade (Python 3.11.9 venv)

Follow Freqtrade's official installation guide, then activate the venv:

```bash
source ~/niblit-py311/bin/activate

# Install Freqtrade (official script or pip)
pip install freqtrade

# Install the niblit-lean-algos helper deps
cd ~/projects/niblit-lean-algos
pip install -r requirements.txt

# Optional: install requests for better HTTP handling in the adapter
pip install requests
```

---

## 9. Configure the Freqtrade strategy

```bash
export NIBLIT_API_URL=http://127.0.0.1:8000
export NIBLIT_TIMEFRAME=1h
# Optional, only if you set NIBLIT_API_KEY in Niblit's .env
# export NIBLIT_API_KEY=your_key_here
```

---

## 10. Run a Freqtrade backtest using NiblitSignalStrategy

Make sure **Niblit is running** (Step 7), then in a second terminal:

```bash
source ~/niblit-py311/bin/activate
export NIBLIT_API_URL=http://127.0.0.1:8000

cd ~/projects/niblit-lean-algos

freqtrade backtesting \
    --strategy NiblitSignalStrategy \
    --strategy-path algorithms/21_niblit_freqtrade \
    --timeframe 1h \
    --timerange 20240101-20240201 \
    -c user_data/config.json
```

> **Fallback behaviour:** If Niblit is not running or returns an error,
> `NiblitSignalStrategy` automatically falls back to `"hold"` — no trades
> are entered. A warning is logged on each failed request.

### Run a dry-run

```bash
freqtrade trade --dry-run \
    --strategy NiblitSignalStrategy \
    --strategy-path algorithms/21_niblit_freqtrade \
    -c user_data/config.json
```

---

## 11. Environment variable reference

| Variable | Default | Description |
|---|---|---|
| `NIBLIT_PROFILE` | `core` | Installation profile: `android` / `core` / `full` |
| `NIBLIT_VECTOR_BACKEND` | `auto` | `numpy` / `faiss` / `qdrant` / `auto` |
| `NIBLIT_EMBEDDINGS_BACKEND` | `auto` | `none` / `sentence_transformers` / `remote` / `auto` |
| `NIBLIT_API_URL` | `http://127.0.0.1:8000` | Niblit base URL (read by Freqtrade adapter) |
| `NIBLIT_API_KEY` | _(blank)_ | Optional API key for `/trade/signal` |
| `NIBLIT_SIGNAL_TIMEOUT` | `5` | HTTP timeout in seconds |
| `NIBLIT_SIGNAL_RETRIES` | `2` | Retry attempts on failure |
| `NIBLIT_MIN_CONFIDENCE` | `0.55` | Minimum confidence threshold to act on a signal |
| `NIBLIT_TIMEFRAME` | `1h` | Freqtrade candle timeframe |

---

## 12. Switching to full local ML (PC later)

When you move to a PC with enough RAM, just swap the requirements profile:

```bash
source ~/niblit-env/bin/activate
pip install -r requirements/full.txt
# Install torch for your platform separately:
pip install torch           # CPU
# or: pip install torch --index-url https://download.pytorch.org/whl/cu121  # CUDA 12.1
```

Then update `.env`:

```ini
NIBLIT_PROFILE=full
NIBLIT_VECTOR_BACKEND=auto        # will use FAISS then Qdrant
NIBLIT_EMBEDDINGS_BACKEND=auto    # will use sentence-transformers
```

No code changes are required.  The profile env vars activate the richer
backends automatically at startup.

---

## 13. Troubleshooting

| Symptom | Fix |
|---|---|
| `ImportError: No module named 'faiss'` | Expected on Android — set `NIBLIT_PROFILE=android` |
| `ImportError: No module named 'sentence_transformers'` | Expected on Android — set `NIBLIT_EMBEDDINGS_BACKEND=none` |
| `/trade/signal` returns `"hold"` with `source=fallback` | Niblit brain not initialised yet — check startup logs |
| Freqtrade adapter logs `signal request failed` | Niblit not running or wrong `NIBLIT_API_URL` |
| `uvicorn` port 8000 already in use | Use `--port 8001` and update `NIBLIT_API_URL` accordingly |
