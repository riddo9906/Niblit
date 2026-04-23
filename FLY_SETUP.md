# Niblit — Fly.io Deployment Guide

Deploy Niblit to [Fly.io](https://fly.io) as a persistent, long-running container with **up to 3 GB of free persistent volume storage** for knowledge, state files, and the LEAN workspace.

---

## Why Fly.io?

| Feature | Vercel | Render | **Fly.io** |
|---|---|---|---|
| Runtime | Serverless (30 s limit) | Long-lived process | **Long-lived container** |
| Persistent disk | ❌ | ✅ (paid plans) | ✅ **3 GB free** |
| Background threads | ❌ cold-start kills them | ✅ | ✅ |
| Custom Dockerfile | ❌ | ❌ | ✅ |
| Global regions | Edge CDN | US regions | **30+ regions** |
| Free tier Machine | — | 512 MB RAM | **256 MB – 2 GB RAM** |

Fly.io is the recommended platform when you need Niblit's ALE, TradingBrain,
and LeanEngine to keep running continuously, and when you want the full 3 GB
volume for knowledge persistence.

---

## Prerequisites

1. **Fly.io account** — sign up at <https://fly.io> (free, no credit card required for the free tier)
2. **flyctl CLI** — install with:
   ```bash
   curl -L https://fly.io/install.sh | sh
   # or on macOS: brew install flyctl
   ```
3. **Docker** — only needed if you want to test the image locally before deploying
4. The Niblit repository cloned locally (or your fork on GitHub)

---

## Quick Deploy (5 steps)

### Step 1 — Log in to Fly.io

```bash
fly auth login
```

### Step 2 — Create the Fly app

Run this **once** from the repository root. It registers the app name and does not deploy yet.

```bash
fly launch --no-deploy --name niblit --region lax
```

> Change `lax` (Los Angeles) to your preferred [Fly region code](https://fly.io/docs/reference/regions/).
> The `fly.toml` file already includes `primary_region = "lax"` — update it if you pick a different region.

### Step 3 — Create the persistent volume

The free tier gives you 3 GB. Create it once:

```bash
fly volumes create niblit_data --size 3 --region lax
```

All runtime state files (memory, knowledge DB, LEAN workspace, ALE checkpoint,
game logs) are stored here at `/data` and survive restarts and new deploys.

### Step 4 — Set secrets (sensitive env vars)

**Required:**
```bash
fly secrets set HF_TOKEN=<your-huggingface-token>
```

**Recommended for local brain on Fly (remote inference):**
```bash
fly secrets set NIBLIT_GGUF_BACKEND=http
fly secrets set NIBLIT_LLAMA_SERVER_URL=https://niblit-cloud-server.fly.dev
```

**Optional — unlock more features:**
```bash
# QuantConnect / LEAN cloud live trading
fly secrets set QC_USER_ID=<your-qc-user-id>
fly secrets set QC_API_TOKEN=<your-qc-api-token>

# Twelve Data (free tier: 800 req/day — stocks, ETFs, forex, crypto, indices)
fly secrets set TWELVE_DATA_API_KEY=<your-key>

# OANDA (free practice account — forex, CFDs, equity indices)
fly secrets set OANDA_API_KEY=<your-key>
fly secrets set OANDA_ACCOUNT_ID=<your-account-id>

# Alpaca (free paper account — US equities + crypto)
fly secrets set ALPACA_API_KEY=<your-key>
fly secrets set ALPACA_API_SECRET=<your-secret>

# LLM providers
fly secrets set OPENAI_API_KEY=<your-key>
fly secrets set ANTHROPIC_API_KEY=<your-key>

# Research / search
fly secrets set GITHUB_TOKEN=<your-token>
fly secrets set SERPEX_API_KEY=<your-key>

# Qdrant vector database (optional — use remote Qdrant Cloud)
fly secrets set QDRANT_URL=<https://...>
fly secrets set QDRANT_API_KEY=<your-key>

# Security
fly secrets set NIBLIT_API_KEY=<random-string>
```

### Step 5 — Deploy

```bash
fly deploy
```

Fly.io builds the Docker image, pushes it to the registry, and starts your
Machine. Watch the logs in real time:

```bash
fly logs
```

Visit your Niblit instance at:
```
https://niblit.fly.dev
```
(Replace `niblit` with your actual app name if it was already taken.)

---

## Configuration

The `fly.toml` file already contains the full configuration. Key settings:

| Setting | Value | Notes |
|---|---|---|
| `primary_region` | `lax` | Change to your nearest region |
| `vm.size` | `shared-cpu-1x` | Upgrade to `shared-cpu-2x` for ML models |
| `vm.memory` | `512mb` | Increase if sentence-transformers OOMs |
| `swap_size_mb` | `512` | Prevents OOM on brief spikes |
| `mounts.source` | `niblit_data` | Persistent volume name |
| `mounts.destination` | `/data` | Mount path inside container |
| `auto_stop_machines` | `false` | Keeps background threads alive |
| `min_machines_running` | `1` | Always keep one Machine running |

---

## Scaling

### Upgrade Machine size (more RAM for ML models)

```bash
fly scale vm shared-cpu-2x --memory 1024
```

Available sizes: `shared-cpu-1x` (256 MB), `shared-cpu-2x` (512 MB),
`performance-1x` (2 GB+).

### Increase volume size

```bash
fly volumes extend <volume-id> --size 10
```

List volume IDs with `fly volumes list`.

---

## Persistent state paths

All state files land on the `/data` volume and persist across deploys:

| File | Purpose |
|---|---|
| `/data/niblit_memory.json` | NiblitMemory + KnowledgeDB |
| `/data/niblit.db` | LocalDB (SQLite) |
| `/data/niblit_fused.sqlite` | FusedMemory vector store (SQLite) |
| `/data/ale_state.json` | ALE checkpoint (resume after restart) |
| `/data/niblit_game_log.jsonl` | Game engine event log |
| `/data/niblit_game_state.json` | Game engine saved state |
| `/data/lean_workspace/` | QuantConnect/LEAN algorithm projects |

---

## Useful commands

```bash
# Open a remote shell inside the running container
fly ssh console

# Check running Machines
fly status

# View real-time logs
fly logs

# Restart the app
fly apps restart niblit

# Redeploy after code changes
fly deploy

# List volumes
fly volumes list

# SSH and inspect /data
fly ssh console -C "ls -la /data"

# Check memory usage
fly ssh console -C "free -h"

# Run the Niblit shell interactively (for testing)
fly ssh console -C "python3 main.py"
```

---

## Troubleshooting

### Machine won't start / health check fails

1. Check logs: `fly logs`
2. Ensure the volume exists: `fly volumes list`
3. Ensure `HF_TOKEN` is set: `fly secrets list`
4. If OOM: upgrade RAM with `fly scale vm shared-cpu-2x --memory 1024`

### Volume not mounted

Make sure you created the volume in the **same region** as the app:
```bash
fly volumes create niblit_data --size 3 --region lax
```

### "App not found" error

Run `fly launch --no-deploy` first to register the app, then `fly deploy`.

### Large Docker image / slow builds

The image includes ML dependencies (sentence-transformers, faiss-cpu, etc.).
To speed up rebuilds, Fly.io caches Docker layers — the first build is slow
(5–10 minutes), subsequent builds only rebuild changed layers.

---

## Environment variables reference

See `fly.toml` `[env]` section for non-sensitive defaults.
Set sensitive values with `fly secrets set`.

| Variable | Required | Source |
|---|---|---|
| `HF_TOKEN` | **Yes** | `fly secrets set` |
| `QC_USER_ID` | For LEAN cloud | `fly secrets set` |
| `QC_API_TOKEN` | For LEAN cloud | `fly secrets set` |
| `TWELVE_DATA_API_KEY` | For Twelve Data | `fly secrets set` |
| `OANDA_API_KEY` | For OANDA | `fly secrets set` |
| `OANDA_ACCOUNT_ID` | For OANDA | `fly secrets set` |
| `ALPACA_API_KEY` | For Alpaca | `fly secrets set` |
| `ALPACA_API_SECRET` | For Alpaca | `fly secrets set` |
| `OPENAI_API_KEY` | Optional | `fly secrets set` |
| `ANTHROPIC_API_KEY` | Optional | `fly secrets set` |
| `QDRANT_URL` | Optional | `fly secrets set` |
| `NIBLIT_API_KEY` | Optional | `fly secrets set` |
| `APP_ENV` | Auto | `fly.toml [env]` |
| `NIBLIT_MEMORY_PATH` | Auto | `fly.toml [env]` |
| `LEAN_WORKSPACE` | Auto | `fly.toml [env]` |
