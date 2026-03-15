# Niblit — AI Agent with Mobile Support

Niblit is a Python-based AI agent with HuggingFace LLM integration, memory
management, self-healing capabilities, and a REST API.  It can be deployed on
Vercel (serverless) and now ships with a **Kivy mobile app** that can be
packaged as an **Android APK** using Buildozer.

---

## Table of Contents

- [Features](#features)
- [Quick Start (Local)](#quick-start-local)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Android APK Build](#android-apk-build)
- [Running Tests](#running-tests)
- [Configuration Guide](#configuration-guide)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

---

## Features

- 🤖 **AI Agent** — HuggingFace LLM integration with memory and event sourcing
- 🌐 **REST API** — Flask endpoints for chat, memory, health checks
- 📊 **Web Dashboard** — Browser-based chat UI
- 📱 **Mobile App** — Kivy-based Android/iOS client (`kivy_app.py`)
- 🗄️ **SQLite Database** — Persistent storage layer (`niblit_sqlite_db.py`)
- 🔒 **CORS + Security Headers** — Mobile-friendly API configuration
- ⚙️ **Centralized Config** — Environment-based settings (`config.py`)
- 🧪 **Test Suite** — Pytest tests with coverage reporting
- 🚀 **CI/CD** — GitHub Actions workflows for testing and linting

---

## Quick Start (Local)

```bash
# 1. Clone the repository
git clone https://github.com/riddo9906/Niblit.git
cd Niblit

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your HF_TOKEN

# 5. Start the server
python server.py
# → http://localhost:5000
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HF_TOKEN` | ✅ Yes | — | HuggingFace API token |
| `NIBLIT_API_KEY` | No | `""` | Optional API key for endpoint protection |
| `PORT` | No | `5000` | Server port (local use) |
| `FLASK_ENV` | No | `development` | `development` / `testing` / `production` |
| `DEBUG` | No | `False` | Enable Flask debug mode |
| `NIBLIT_SQLITE_DB_PATH` | No | `niblit_data.sqlite` | SQLite database path |
| `CORS_ORIGINS` | No | `*` | Comma-separated CORS origins |
| `MOBILE_ENABLED` | No | `True` | Enable mobile API features |
| `LOG_LEVEL` | No | `INFO` | Logging level |

---

## API Reference

### `GET /health`

Lightweight liveness probe. Does not initialise the AI core.

```bash
curl http://localhost:5000/health
# {"status": "ok", "service": "niblit"}
```

### `GET /ping`

Returns system status including personality mood.

```bash
curl http://localhost:5000/ping
# {"status": "ok", "personality": {"mood": "neutral", "tone": "calm"}}
```

### `POST /chat`

Send a message to Niblit and receive a reply.

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, Niblit!"}'
# {"reply": "Hello! How can I help you today?"}
```

**Request body:**
```json
{ "text": "your message here" }
```

**Responses:**
- `200 OK` — `{"reply": "..."}`
- `400 Bad Request` — missing or empty `text`
- `500 Internal Server Error` — AI core unavailable

### `GET /memory`

Returns stored knowledge facts (up to 200 entries).

```bash
curl http://localhost:5000/memory
# {"facts": [{"key": "...", "value": "...", "created_at": "..."}]}
```

---

## Android APK Build

### Prerequisites

- Ubuntu 20.04+ (or WSL2 on Windows)
- Python 3.10+
- Java 17 (OpenJDK)

```bash
# Install build tools
sudo apt update && sudo apt install -y \
  python3-pip python3-venv git zip unzip \
  openjdk-17-jdk

# Install Kivy and Buildozer
pip install kivy==2.3.0 buildozer cython

# Build debug APK (first build downloads Android SDK/NDK — ~5 GB)
buildozer android debug

# The APK will be in:
ls bin/*.apk
```

### Configure the API URL

Before building, set the server URL the app should connect to:

```bash
export NIBLIT_API_URL=https://your-server.vercel.app
```

Or edit `kivy_app.py`:
```python
_API_URL = os.getenv("NIBLIT_API_URL", "https://your-server.vercel.app")
```

### Release APK

```bash
# Generate a signing keystore (first time only)
keytool -genkey -v -keystore niblit.keystore \
  -alias niblit -keyalg RSA -keysize 2048 -validity 10000

# Build release APK
buildozer android release
```

### Desktop Preview (no Android needed)

```bash
pip install kivy requests
python kivy_app.py
```

---

## Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest test_server.py test_niblit_db.py -v

# Run with coverage
pytest test_server.py test_niblit_db.py \
  --cov=server --cov=niblit_sqlite_db --cov=config \
  --cov-report=term-missing

# Run only DB tests
pytest test_niblit_db.py -v

# Run only API tests
pytest test_server.py -v
```

---

## Configuration Guide

Niblit uses `config.py` for centralised settings:

```python
from config import settings

print(settings.PORT)          # 5000
print(settings.MOBILE_ENABLED)  # True
print(settings.CORS_ORIGINS)  # "*"
```

### Environments

| `FLASK_ENV` | Behaviour |
|-------------|-----------|
| `development` (default) | DEBUG=True, verbose logging |
| `testing` | In-memory DB, no real HF calls |
| `production` | DEBUG=False, strict settings |

---

## Troubleshooting

### Mobile: Cannot connect to server

1. Ensure `NIBLIT_API_URL` points to a publicly accessible server (not `localhost`).
2. Android emulators use `10.0.2.2` to reach the host machine — this is the default.
3. Check that CORS is enabled (`flask-cors` is installed).

### APK build fails: SDK not found

```bash
# Manually set SDK path if auto-detection fails
export ANDROID_SDK_ROOT=~/.buildozer/android/platform/android-sdk
export ANDROID_NDK_HOME=~/.buildozer/android/platform/android-ndk-r25b
```

### APK build fails: Java version

Buildozer requires Java 11 or 17. Check with:

```bash
java -version
# If wrong version:
sudo apt install openjdk-17-jdk
sudo update-alternatives --config java
```

### Tests fail: Flask import error

```bash
pip install -r requirements.txt
```

---

## Project Structure

```
Niblit/
├── app.py                  # Vercel-optimised Flask app
├── server.py               # Standalone Flask server
├── kivy_app.py             # Kivy mobile app
├── buildozer.spec          # Android APK build configuration
├── config.py               # Centralised configuration
├── niblit_sqlite_db.py     # SQLite database layer
├── niblit_core.py          # Core AI agent
├── niblit_router.py        # Command routing
├── niblit_memory.py        # Memory management
├── modules/                # AI subsystem modules
├── tools/                  # Utility scripts
├── test_server.py          # API unit tests
├── test_niblit_db.py       # Database integration tests
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Dev/test dependencies
├── .env.example            # Environment variable template
├── vercel.json             # Vercel deployment config
└── .github/
    └── workflows/
        ├── test.yml        # CI test pipeline
        ├── pylint.yaml     # Lint pipeline
        └── deploy.yml      # Deployment validation
```
