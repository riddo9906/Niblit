# server.py — Niblit FastAPI server (lightweight alternative to app.py)
import os

# Load .env file when running locally (e.g. Termux).  On Vercel / Render the
# platform injects env vars directly, so this is a no-op in those environments.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on os.environ

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:
    from niblit_core import NiblitCore
except Exception:
    NiblitCore = None

try:
    from config import settings as _settings
except Exception:
    _settings = None

_origins = getattr(_settings, "CORS_ORIGINS", "*") if _settings else "*"
_origins_list = [_origins] if isinstance(_origins, str) else list(_origins)

app = FastAPI(title="Niblit Server", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-initialize NiblitCore to reduce cold-start time on serverless
_core = None

def get_core():
    """Return a shared NiblitCore instance, initializing it on first call."""
    global _core  # pylint: disable=global-statement
    if _core is None and NiblitCore:
        _core = NiblitCore()
    return _core

# Simple HTML dashboard template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Niblit Dashboard</title>
<style>
body { font-family: Arial, sans-serif; background:#1b1b1b; color:#f1f1f1; }
.container { width: 90%; max-width: 900px; margin:auto; padding:20px; }
textarea { width:100%; height:80px; background:#222; color:#f1f1f1; border:none; padding:10px; }
button { padding:10px 20px; margin-top:10px; background:#444; color:#f1f1f1; border:none; cursor:pointer; }
#chatbox { border:1px solid #333; padding:10px; height:300px; overflow-y:scroll; background:#111; margin-top:10px;}
.chat-msg { margin:5px 0; }
.user { color:#4ef; }
.bot { color:#fa4; }
</style>
</head>
<body>
<div class="container">
<h1>Niblit Dashboard</h1>
<p>System Status: <span id="status">Initializing...</span></p>

<textarea id="input" placeholder="Type a command or question..."></textarea><br>
<button onclick="send()">Send</button>

<div id="chatbox"></div>

<script>
async function send() {
    let input = document.getElementById("input").value;
    if(!input) return;
    let chatbox = document.getElementById("chatbox");
    chatbox.innerHTML += '<div class="chat-msg user">You: ' + input + '</div>';
    document.getElementById("input").value = '';

    let resp = await fetch("/chat", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({text:input})
    });
    let data = await resp.json();
    chatbox.innerHTML += '<div class="chat-msg bot">Niblit: ' + (data.reply || '[no reply]') + '</div>';
    chatbox.scrollTop = chatbox.scrollHeight;
}

async function checkStatus() {
    let resp = await fetch("/ping");
    let data = await resp.json();
    document.getElementById("status").innerText = "OK - Personality mood: " + (data.personality.mood || "neutral");
}
setInterval(checkStatus, 5000);
checkStatus();
</script>
</div>
</body>
</html>
"""


class ChatBody(BaseModel):
    text: str = ""


@app.get("/")
def dashboard():
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/health")
def health():
    """Lightweight liveness probe — does not initialize NiblitCore."""
    return {"status": "ok", "service": "niblit"}


@app.get("/ping")
def ping():
    n = get_core()
    return {"status": "ok", "personality": n.db.get_personality() if n else {}}


@app.post("/chat")
def chat(body: ChatBody):
    n = get_core()
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "no text provided"}, status_code=400)
    if not n:
        return JSONResponse({"error": "core unavailable"}, status_code=500)
    reply = n.handle(text)
    return {"reply": reply}


@app.get("/memory")
def memory():
    n = get_core()
    if not n:
        return {"facts": []}
    facts = n.db.list_facts(limit=200)
    return {"facts": facts}


def run_server():
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Niblit HTTP server on http://0.0.0.0:{port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port)

if __name__ == "__main__":
    run_server()
