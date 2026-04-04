# Niblit — Render Deployment Guide

This guide explains how to deploy Niblit to [Render](https://render.com) as a persistent web service.

---

## Why Render?

Unlike Vercel (serverless, 30-second limit), Render runs Niblit as a **long-lived process**.  
This means:

- Background daemon threads (ALE, BackgroundTrainer, TradingBrain, etc.) stay alive between requests.
- No cold-start penalty after the first boot.
- Persistent disk is available if you upgrade from the free tier.

---

## Prerequisites

- A [Render account](https://render.com) (free tier is sufficient for basic use)
- The Niblit repository forked or accessible on GitHub
- A [Hugging Face](https://huggingface.co) API token

---

## Step 1 — Connect Repository to Render

1. Log in to the [Render Dashboard](https://dashboard.render.com).
2. Click **New → Blueprint**.
3. Connect your GitHub account and select your fork of this repository.
4. Render will detect `render.yaml` automatically and pre-fill the service configuration.
5. Click **Apply** to create the service.

Alternatively, deploy a single web service manually:

1. Click **New → Web Service**.
2. Connect your GitHub repository.
3. Set the following fields:

| Field | Value |
|---|---|
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
| **Health Check Path** | `/health` |

---

## Step 2 — Set Environment Variables

Render automatically reads the `envVars` block from `render.yaml` for Blueprint deployments.  
For manual deployments, set these in **Service → Environment**:

### Required

| Variable | Description |
|---|---|
| `HF_TOKEN` | HuggingFace API token — activates the LLM brain. Get one at https://huggingface.co/settings/tokens |

### Security

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random secret (Render auto-generates this via `render.yaml`) |
| `NIBLIT_API_KEY` | Optional bearer token to protect `/chat` and `/memory` |
| `CORS_ORIGINS` | Allowed CORS origins (default `*`) |

### Recommended

| Variable | Description |
|---|---|
| `SERPEX_API_KEY` | Serpex web-search key — activates autonomous research |
| `GITHUB_TOKEN` | GitHub PAT — activates GitHubSync and code search |
| `OPENAI_API_KEY` | Optional second LLM provider |
| `ANTHROPIC_API_KEY` | Optional third LLM provider (Claude) |

For the full list of supported variables (Trading Brain, LEAN, Qdrant, Trainer, MCP, etc.)
see [`VERCEL_SETUP.md`](VERCEL_SETUP.md) — all variables are identical across both platforms.

---

## Step 3 — Verify the Deployment

Once deployed, visit your Render URL and check:

| Endpoint | Method | Expected Response |
|---|---|---|
| `/` | GET | Niblit Dashboard UI |
| `/health` | GET | `{"status": "ok", "service": "niblit"}` |
| `/ping` | GET | `{"status": "ok", "personality": {...}}` |
| `/chat` | POST | `{"reply": "..."}` |
| `/memory` | GET | `{"facts": [...]}` |

```bash
# Liveness probe
curl https://<your-render-url>/health

# Full status
curl https://<your-render-url>/ping

# Chat
curl -X POST https://<your-render-url>/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "hello"}'
```

---

## Step 4 — Free Tier Notes

| Limitation | Detail |
|---|---|
| **Sleep after inactivity** | Free web services spin down after 15 minutes of no traffic. The first request after sleep takes ~30 seconds while the process restarts. Use `/health` as a keep-alive ping if needed. |
| **No persistent disk** | Memory files (`niblit_memory.json`, `ale_state.json`) are written to the ephemeral filesystem. They survive restarts only if you add a Render [Disk](https://render.com/docs/disks). |
| **512 MB RAM** | Sufficient for core + ALE. Heavy models (large embeddings) may require upgrading to the Starter plan. |

To add a persistent disk (paid plans only):

```yaml
# add to the service block in render.yaml
disk:
  name: niblit-data
  mountPath: /data
  sizeGB: 1
```

Then set `NIBLIT_MEMORY_PATH=/data` so memory files land on the persistent volume.

---

## Troubleshooting

### Service fails to start

Check **Service → Logs** in the Render dashboard.  
Common causes:
- `HF_TOKEN` not set → LLM brain fails to initialise (non-fatal; Niblit still starts).
- Missing dependency → ensure `pip install -r requirements.txt` succeeded in the build step.

### `{"error": "core unavailable"}` on `/chat`

`NiblitCore` failed to initialise. Check logs for the root cause.  
Niblit handles this gracefully and will return an error response rather than crashing.

### `{"error": "unauthorized"}` on `/chat` or `/memory`

`NIBLIT_API_KEY` is set. Include the header:

```bash
curl -H "X-API-Key: <your-key>" https://<your-render-url>/chat \
  -X POST -H "Content-Type: application/json" \
  -d '{"text": "hello"}'
```

---

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in values
python app.py
# Open http://localhost:5000
```

To simulate the Render environment locally:

```bash
PORT=5000 uvicorn app:app --host 0.0.0.0 --port 5000
```
