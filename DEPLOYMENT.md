# Niblit – Vercel Deployment Guide

Deploy the Niblit AI web application to [Vercel](https://vercel.com) in a few minutes.

---

## Prerequisites

- A [Vercel account](https://vercel.com/signup) (free tier works)
- A [Hugging Face account](https://huggingface.co/join) with an API token
- Your Niblit repository forked or connected to Vercel

---

## Quick Deploy

### 1. Fork / clone the repository

```bash
git clone https://github.com/riddo9906/Niblit.git
cd Niblit
```

### 2. Install the Vercel CLI (optional but recommended)

```bash
npm install -g vercel
```

### 3. Configure environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description | Required |
|---|---|---|
| `HF_TOKEN` | Hugging Face API token (read access is enough) | ✅ Yes |
| `SECRET_KEY` | Random secret key for Flask sessions | ✅ Yes |
| `FLASK_ENV` | Set to `production` for Vercel | ✅ Yes |
| `NIBLIT_NAME` | Custom AI name (default: `Niblit`) | No |
| `NIBLIT_MOOD` | Default personality mood | No |

Generate a secure `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Deploying to Vercel

### Option A – Vercel Dashboard (recommended for first deploy)

1. Go to [vercel.com/new](https://vercel.com/new)
2. Import your GitHub repository
3. Vercel will auto-detect the Python project via `vercel.json`
4. Under **Environment Variables**, add each variable from `.env.example`
5. Click **Deploy**

### Option B – Vercel CLI

```bash
vercel login
vercel --prod
```

Follow the prompts. When asked about environment variables, set them in the
Vercel dashboard at **Project → Settings → Environment Variables** or pass
them with:

```bash
vercel env add HF_TOKEN
vercel env add SECRET_KEY
vercel env add FLASK_ENV
```

---

## Vercel Configuration Reference

`vercel.json` settings used in this project:

| Setting | Value | Purpose |
|---|---|---|
| `maxLambdaSize` | `50mb` | Allows large ML dependencies |
| `memory` | `1024 MB` | Enough RAM for NiblitCore |
| `maxDuration` | `30 s` | Prevents timeouts on first chat request |
| `FLASK_ENV` | `production` | Disables debug mode |

---

## Available Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Web dashboard UI |
| `/health` | GET | Lightweight health check (no AI init) |
| `/ping` | GET | Status + personality data |
| `/chat` | POST | Send a message, receive a reply |
| `/memory` | GET | List stored facts |

### `/chat` example

```bash
curl -X POST https://your-app.vercel.app/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello Niblit!"}'
```

Response:

```json
{"reply": "Hello! How can I help you?"}
```

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start the dev server
python server.py
# → http://localhost:5000
```

Or with gunicorn (mirrors the production WSGI server):

```bash
gunicorn server:app --bind 0.0.0.0:5000
```

---

## Troubleshooting

### "Function timeout" on first request

The NiblitCore engine initializes lazily (on first request) to avoid
increasing cold-start time. The `maxDuration` is set to 30 seconds to
accommodate this. If your AI model is large, consider:
- Reducing model complexity in `niblit_core.py`
- Using a lighter Hugging Face model

### "Module not found" errors

Make sure all dependencies are listed in `requirements.txt`. Vercel installs
them automatically during the build phase.

### Environment variable not found

Verify the variable is set in **Vercel → Project → Settings → Environment
Variables** and that you selected the correct environment (Production,
Preview, or Development).

### 413 / payload too large

Vercel's default request size limit is 4.5 MB. Keep chat messages concise.

---

## Monitoring

- **Vercel dashboard** → Deployments → Logs (real-time function logs)
- **Health check**: `GET /health` returns `{"status": "ok", "service": "niblit"}`
- Use an external monitor (e.g., [UptimeRobot](https://uptimerobot.com)) to
  hit `/health` every minute and alert on failures.

---

## CI/CD

A GitHub Actions workflow (`.github/workflows/deploy.yml`) validates every
push to `main`:

1. Installs dependencies
2. Runs a syntax check on `server.py`
3. Verifies `vercel.json` is valid JSON

On success, Vercel's own GitHub integration automatically deploys the branch.
