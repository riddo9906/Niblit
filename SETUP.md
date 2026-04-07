# Niblit — External Environment Setup Guide

This guide covers every third-party service and credential Niblit uses across
all eight architecture phases.  Follow only the phases you intend to activate;
Niblit always starts and runs without any optional keys.

---

## Quick-start checklist

| Phase | Service | Env var(s) | Required? |
|---|---|---|---|
| 0 | Vercel | — | Hosting only |
| 1–2 | Hugging Face | `HF_TOKEN` | **Yes** (primary LLM) |
| 4 | OpenAI | `OPENAI_API_KEY` | Optional |
| 4 | Anthropic | `ANTHROPIC_API_KEY` | Optional |
| 4 | SerpEx | `SERPEX_API_KEY` | Optional (web search) |
| 4 | GitHub | `GITHUB_TOKEN` | Optional (code search) |
| 4 | Stack Overflow | `STACKOVERFLOW_API_KEY` | Optional (bug lookup) |
| 4 | PyPI | `PYPI_API_URL` | None required |
| 3 | Qdrant | `QDRANT_URL` + `QDRANT_API_KEY` | Optional (vector DB) |
| 5 | Docker | `SANDBOX_ENABLED=true` | Optional (sandboxing) |

---

## Step 0 — Copy the environment template

```bash
cp .env.example .env
# Then open .env in your editor and fill in the values below
```

On Vercel, set all values via **Project → Settings → Environment Variables**
instead of a `.env` file.

---

## Phase 1–2 — Hugging Face (required)

Niblit uses Hugging Face Inference as its default LLM backend.

### 1. Create an account

Go to [https://huggingface.co/join](https://huggingface.co/join).

### 2. Generate a token

1. Visit [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. Click **New token**.
3. Choose **Read** access (sufficient for inference).
4. Copy the token.

### 3. Set the environment variable

```dotenv
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 4. (Optional) Choose a different model

```dotenv
# Default: moonshotai/Kimi-K2-Instruct-0905
# Any HF Inference-compatible model ID works
HF_TOKEN=hf_...
```

---

## Phase 4 — OpenAI (optional LLM)

Niblit's `OpenAIAdapter` activates automatically when this key is present.

### 1. Create an account

[https://platform.openai.com](https://platform.openai.com)

### 2. Generate an API key

1. Go to [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys).
2. Click **Create new secret key**.
3. Copy the key immediately (shown once).

### 3. Set environment variables

```dotenv
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o-mini   # or gpt-4o, gpt-4-turbo, etc.
```

### 4. Billing

Add a payment method at
[https://platform.openai.com/settings/billing](https://platform.openai.com/settings/billing).
The free tier grants $5 of credit.

---

## Phase 4 — Anthropic Claude (optional LLM)

Niblit's `AnthropicAdapter` activates automatically when this key is present.

### 1. Create an account

[https://console.anthropic.com](https://console.anthropic.com)

### 2. Generate an API key

1. Go to **Settings → API Keys**.
2. Click **Create Key**.
3. Copy the key.

### 3. Set environment variables

```dotenv
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_MODEL=claude-3-haiku-20240307   # or claude-3-5-sonnet-20241022
```

### Available models

| Model | Speed | Cost |
|---|---|---|
| `claude-3-haiku-20240307` | Fast | Lowest |
| `claude-3-5-sonnet-20241022` | Balanced | Medium |
| `claude-opus-4-5` | Slow | Highest |

---

## Phase 4 — SerpEx web search (optional)

Used by the autonomous researcher and ALE as the primary web-search backend.
Falls back to DuckDuckGo/Wikipedia when absent.

### 1. Register

[https://serpex.dev](https://serpex.dev)

### 2. Set the environment variable

```dotenv
SERPEX_API_KEY=your_serpex_api_key_here
```

---

## Phase 4 — GitHub Code Search (optional)

Used to discover code patterns, find training data, and study refactoring
examples from public repositories.

### 1. Log in to GitHub

[https://github.com](https://github.com)

### 2. Create a Personal Access Token

1. Go to [https://github.com/settings/tokens](https://github.com/settings/tokens).
2. Click **Generate new token (classic)**.
3. Select only the **public_repo** scope (read-only access to public repos).
4. Copy the token.

> **Fine-grained tokens** also work — grant **Contents: Read-only** on public
> repositories.

### 3. Set the environment variable

```dotenv
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 4. Rate limits

| Auth state | Requests / hour |
|---|---|
| Unauthenticated | 10 |
| Authenticated (PAT) | 30 (search API) |

---

## Phase 4 — Stack Exchange / Stack Overflow API (optional)

Used to look up bug solutions, code explanations, and patterns during
autonomous code research.  The unauthenticated tier (300 req/day) works
without any key.

### 1. Register your app

1. Log in to Stack Overflow at [https://stackoverflow.com](https://stackoverflow.com).
2. Go to [https://stackapps.com/apps/oauth/register](https://stackapps.com/apps/oauth/register).
3. Fill in a name (e.g. "Niblit Research"), website URL, and description.
4. Click **Register Your Application**.
5. Copy the **Key** shown on the app page.

### 2. Set the environment variable

```dotenv
STACKOVERFLOW_API_KEY=your_stack_exchange_key_here
```

### Rate limits

| Auth state | Requests / day |
|---|---|
| No key | 300 |
| With key | 10 000 |

---

## Phase 4 — PyPI (no key required)

The `PyPISearch` module queries `https://pypi.org/pypi/<name>/json` directly.
No registration is needed.  Override the base URL only if you use a private
mirror:

```dotenv
PYPI_API_URL=https://pypi.org/pypi   # default, override for mirrors only
```

---

## Phase 3 — Qdrant vector database (optional)

Qdrant provides persistent semantic search for Niblit's knowledge base.
When not configured the built-in in-memory vector store is used.

### Option A — Qdrant Cloud (recommended)

1. Sign up at [https://cloud.qdrant.io](https://cloud.qdrant.io).
2. Create a **Free Tier** cluster (1 GB RAM, 20 GB storage).
3. On the cluster page copy:
   - **Cluster URL** (e.g. `https://abc123.us-east4-0.gcp.cloud.qdrant.io`)
   - **API Key** (generate under **Security**)

```dotenv
QDRANT_URL=https://abc123.us-east4-0.gcp.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key_here
QDRANT_COLLECTION=niblit_knowledge
```

### Option B — Self-hosted with Docker

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant
```

```dotenv
QDRANT_URL=http://localhost:6333
# QDRANT_API_KEY is optional for local instances
```

### Embedding model

Niblit embeds text with a sentence-transformers model.  The default
`intfloat/multilingual-e5-small` is downloaded automatically on first use.
It supports 100 languages and produces 384-dimensional dense vectors.

```dotenv
EMBEDDING_MODEL=intfloat/multilingual-e5-small   # default — multilingual, 384-dim
```

Install the embedding dependency:

```bash
pip install sentence-transformers
```

To use FAISS as a local vector index (no network required):

```bash
pip install faiss-cpu          # CPU build
# or
pip install faiss-gpu          # GPU build
```

---

## Phase 5 — Docker sandbox execution (optional)

Allows generated code to run in an isolated container.  Only enable this when
Docker is installed and available on the host.

### 1. Install Docker

Follow the official guide: [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)

Verify installation:

```bash
docker --version
docker run --rm hello-world
```

### 2. Enable sandboxing

```dotenv
SANDBOX_ENABLED=true
DOCKER_HOST=unix:///var/run/docker.sock   # default on Linux/Mac
SANDBOX_IMAGE=python:3.12-slim            # base image for code execution
SANDBOX_TIMEOUT=30                        # seconds before container is killed
SANDBOX_MEMORY_MB=256                     # memory limit per container
```

### 3. (Optional) Pull the sandbox image in advance

```bash
docker pull python:3.12-slim
```

### Security notes

- Containers are run with no network access by default.
- CPU and memory are limited via `SANDBOX_MEMORY_MB` and `SANDBOX_TIMEOUT`.
- Never set `SANDBOX_ENABLED=true` on a shared / public-facing server without
  additional isolation (e.g. gVisor / Kata containers).

---

## Verifying your setup

After filling in `.env`, run:

```bash
python -c "
from config import settings
print('HF_TOKEN:     ', bool(settings.HF_TOKEN))
print('OPENAI:       ', bool(settings.OPENAI_API_KEY))
print('ANTHROPIC:    ', bool(settings.ANTHROPIC_API_KEY))
print('SERPEX:       ', bool(settings.SERPEX_API_KEY))
print('GITHUB:       ', bool(settings.GITHUB_TOKEN))
print('STACKOVERFLOW:', bool(settings.STACKOVERFLOW_API_KEY))
print('QDRANT:       ', bool(settings.QDRANT_URL))
print('SANDBOX:      ', settings.SANDBOX_ENABLED)
"
```

---

## Full architecture overview

```
USER / API CLIENTS
       │
 API GATEWAY (Vercel / Flask)
       │
 ORCHESTRATION LAYER  ← core/orchestrator.py
       │
 ┌─────┼─────────────────────┐
 │     │                     │
AGENTS  KNOWLEDGE SYSTEM   EXECUTION
 │     │                     │
 │  ┌──┴──────────────┐   ┌──┴──────┐
 │  │ sqlite_store    │   │ sandbox │
 │  │ vector_store    │   │ docker  │
 │  │ knowledge_graph │   │ build   │
 │  └─────────────────┘   └─────────┘
 │
 ├ planner_agent.py
 ├ research_agent.py     ← GitHub, SO, PyPI, SerpEx
 ├ coding_agent.py       ← HF / OpenAI / Anthropic
 ├ testing_agent.py
 ├ reflection_agent.py
 └ architecture_agent.py

EVENT BUS  ← core/event_bus.py
TASK QUEUE ← core/task_queue.py
RUNTIME    ← core/runtime_manager.py
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `HF_TOKEN not set` | Missing env var | Add `HF_TOKEN=hf_...` to `.env` |
| `429 Too Many Requests` (GitHub) | Unauthenticated or over limit | Add `GITHUB_TOKEN` |
| `qdrant_client not installed` | Missing dependency | `pip install qdrant-client` |
| `sentence_transformers not installed` | Missing embedding dep | `pip install sentence-transformers` |
| Docker sandbox errors | Docker not running | Start Docker daemon |
| SO search returns empty | Rate limited | Add `STACKOVERFLOW_API_KEY` |

---

## Adding all dependencies at once

```bash
pip install \
  huggingface_hub \
  openai \
  anthropic \
  requests \
  sentence-transformers \
  faiss-cpu \
  qdrant-client \
  python-dotenv
```

For the full feature set on a Termux / Android environment:

```bash
pip install huggingface_hub requests python-dotenv
# faiss-cpu and sentence-transformers require a compiler; install via:
pkg install python-numpy  # Termux
pip install sentence-transformers --no-build-isolation
```
