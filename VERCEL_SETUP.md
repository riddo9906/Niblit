# Vercel Deployment — Environment Variable Setup

This guide explains every environment variable you need to set in Vercel so that
all Niblit modules (HFBrain, TradingBrain, GitHubSync, BackgroundTrainer, ALE, LEAN,
Phase-2 Agents, etc.) are fully activated on your deployed instance.

---

## How to set environment variables on Vercel

1. Open your project at **https://vercel.com/dashboard**
2. Click **Settings** → **Environment Variables**
3. For each variable below, click **Add New**, enter the **Name** and **Value**, select
   the environments (**Production**, **Preview**, **Development** — usually all three),
   then click **Save**
4. After adding all variables, go to **Deployments**, select the latest deployment, and
   click **Redeploy** (or just push a new commit) so the new env vars take effect

---

## Required — must be set for the brain to activate

| Variable | Value | Purpose |
|---|---|---|
| `HF_TOKEN` | `hf_xxxx…` | HuggingFace token — activates HFBrain and the LLM adapter. Get it at https://huggingface.co/settings/tokens (read scope is enough). |

---

## Strongly Recommended — activate autonomous research

| Variable | Value | Purpose |
|---|---|---|
| `SERPEX_API_KEY` | `sk-…` | Serpex web search — primary backend for ALE Step 1 (unified research). Without it, research falls back to DuckDuckGo / Wikipedia only. Get at https://serpex.dev |
| `GITHUB_TOKEN` | `ghp_…` | GitHub PAT — activates GitHubSync and GitHub Code Search. Create at https://github.com/settings/tokens with `public_repo` (read-only is fine). |
| `OPENAI_API_KEY` | `sk-…` | Optional second LLM provider. Without it, only HFBrain is used. Get at https://platform.openai.com/api-keys |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Optional third LLM provider (claude-3-haiku). Get at https://console.anthropic.com/account/keys |

---

## Trading Brain — Binance market data

| Variable | Default | Purpose |
|---|---|---|
| `BINANCE_API_KEY` | *(blank)* | Binance API key — enables authenticated trading data. Without it the brain uses public-only endpoints (paper mode). Create at https://www.binance.com/en/my/settings/api-management |
| `BINANCE_API_SECRET` | *(blank)* | Binance API secret (companion to the key above). |
| `TRADING_SYMBOL` | `BTCUSDT` | Default trading pair. Can be changed live with `trading pair <SYMBOL>`. |
| `TRADING_INTERVAL` | `1m` | Default kline interval (e.g. `1m`, `5m`, `1h`). |
| `TRADING_CYCLE_SECS` | `60` | Seconds between autonomous trading cycles. |
| `TRADING_KLINE_LIMIT` | `200` | Number of candles fetched per cycle. |

---

## LEAN Engine — QuantConnect backtesting & live trading

| Variable | Default | Purpose |
|---|---|---|
| `LEAN_API_USER_ID` | *(blank)* | QuantConnect user ID (shown at https://www.quantconnect.com/account). |
| `LEAN_API_TOKEN` | *(blank)* | QuantConnect API token (same page). |
| `LEAN_WORKSPACE` | *(project root)* | Local directory where LEAN projects are stored. |
| `LEAN_BACKTEST_TIMEOUT_SECS` | `3600` | Per-backtest timeout. |
| `LEAN_LIVE_TIMEOUT_SECS` | `86400` | Per-live-trading session timeout. |
| `LEAN_SWEEP_ITER_TIMEOUT_SECS` | `900` | Per-iteration timeout during parameter sweeps. |

---

## Background Trainer

| Variable | Default | Purpose |
|---|---|---|
| `TRAINER_BATCH_SIZE` | `32` | Examples per training batch. |
| `TRAINER_INTERVAL_SECS` | `60` | Seconds between training steps. |
| `TRAINER_STEP_TIMEOUT_SECS` | `30` | Hard timeout per step. |

---

## Knowledge & Vector Database (semantic search)

| Variable | Default | Purpose |
|---|---|---|
| `QDRANT_URL` | *(blank — uses in-memory fallback)* | Qdrant instance URL. Cloud: https://cloud.qdrant.io. Leave blank for the lightweight in-memory backend. |
| `QDRANT_API_KEY` | *(blank)* | Qdrant API key (only needed for cloud instances). |
| `QDRANT_COLLECTION` | `niblit_knowledge` | Collection name shared across all components. |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | Sentence-transformer model for embeddings (multilingual, 384-dim). |

---

## GitHub Sync (auto-push evolved files)

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_REPO` | *(blank)* | Target repo slug, e.g. `yourname/Niblit`. Required for `github push`. |
| `GITHUB_BRANCH` | `niblit/auto-improve` | Branch Niblit pushes evolved code to. |
| `NIBLIT_GITHUB_DRY_RUN` | `1` | Set to `0` to enable actual pushes. Default `1` = dry-run only (safe). |

---

## MCP Server (AI client integration)

| Variable | Default | Purpose |
|---|---|---|
| `MCP_ENABLED` | `true` | Set `false` to disable MCP endpoints (`/mcp`, `/mcp/sse`). |
| `MCP_SECRET` | *(blank — no auth)* | Bearer token clients must send. Set a strong value in production. |

---

## Runtime flags (fine-grained module control)

| Variable | Default | Purpose |
|---|---|---|
| `NIBLIT_AUTONOMOUS_ENGINE` | `true` | Enable the 29-step Autonomous Learning Engine. |
| `NIBLIT_IMPROVEMENTS` | `true` | Enable the 17 production improvement modules. |
| `NIBLIT_SELF_IMPROVEMENTS` | `true` | Enable the 10 self-improvement modules. |
| `NIBLIT_LOOPS` | `true` | Enable all background loops. |
| `NIBLIT_DEBUG` | `false` | Enable verbose debug logging. |
| `NIBLIT_LOG_LEVEL` | `INFO` | Log level: `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `NIBLIT_MEMORY_PATH` | *(blank — project root)* | Override where `niblit_memory.json` is stored. |
| `NIBLIT_GAME_DISPLAY` | `0` | Set `1` only if a display is available (not on Vercel). |

---

## Security & CORS

| Variable | Default | Purpose |
|---|---|---|
| `NIBLIT_API_KEY` | *(blank — no auth)* | Protect `/chat` and `/memory` endpoints with a bearer token. |
| `SECRET_KEY` | `niblit-secret-change-me` | **Change this** to a random string in production. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins, or `*` to allow all. |

---

## Vercel function limits

The `vercel.json` allocates **512 MB** and **30 seconds** per request.  
Heavy operations like `autonomous-learn start` run in background daemon threads that
persist for the lifetime of the serverless instance — they do NOT count against the
30-second HTTP timeout.

> **Note for Vercel hobby tier:** The free tier has a 10-second execution limit.  
> Upgrade to **Pro** (30 seconds) for the full Niblit experience.  
> Alternatively, self-host with `python main.py` or `uvicorn app:app` for unlimited background threads.

---

## Minimal set to get everything working

Copy and paste the following into Vercel Settings → Environment Variables:

```
HF_TOKEN          = hf_your_token_here
SERPEX_API_KEY    = your_serpex_key
GITHUB_TOKEN      = ghp_your_github_pat
OPENAI_API_KEY    = sk-your_openai_key     (optional but recommended)
BINANCE_API_KEY   = your_binance_key       (optional — paper mode without it)
BINANCE_API_SECRET= your_binance_secret
SECRET_KEY        = some-long-random-string
CORS_ORIGINS      = *
NIBLIT_AUTONOMOUS_ENGINE = true
NIBLIT_IMPROVEMENTS      = true
NIBLIT_SELF_IMPROVEMENTS = true
NIBLIT_DEBUG      = false
```

After adding these, **redeploy** the project and type `status` in the terminal — all
green checkmarks mean every module is active.
