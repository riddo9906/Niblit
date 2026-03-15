# server.py
import os

try:
    from flask import Flask, request, jsonify, render_template_string
    _flask_available = True
except ImportError:
    Flask = request = jsonify = render_template_string = None
    _flask_available = False
    import logging as _logging
    _logging.getLogger("NiblitServer").warning("Flask not installed — server.py web server unavailable")

try:
    from flask_cors import CORS as _CORS
    _cors_available = True
except ImportError:
    _CORS = None
    _cors_available = False

try:
    from niblit_core import NiblitCore
except Exception:
    NiblitCore = None

try:
    from config import settings as _settings
except Exception:
    _settings = None

if _flask_available:
    app = Flask("niblit_server")
    # Enable CORS for mobile and web clients
    if _cors_available and _CORS:
        _origins = getattr(_settings, "CORS_ORIGINS", "*") if _settings else "*"
        _CORS(app, resources={
            r"/chat": {"origins": _origins},
            r"/memory": {"origins": _origins},
            r"/health": {"origins": _origins},
            r"/ping": {"origins": _origins},
        })
else:
    app = None

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

if _flask_available and app is not None:
    @app.after_request
    def _add_security_headers(response):
        """Attach basic security headers to every response."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.route("/")
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/health", methods=["GET"])
    def health():
        """Lightweight liveness probe — does not initialize NiblitCore."""
        return jsonify({"status": "ok", "service": "niblit"})

    @app.route("/ping", methods=["GET"])
    def ping():
        n = get_core()
        return jsonify({"status": "ok", "personality": n.db.get_personality() if n else {}})

    @app.route("/chat", methods=["POST"])
    def chat():
        n = get_core()
        data = request.get_json(force=True, silent=True) or {}
        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "no text provided"}), 400
        if not n:
            return jsonify({"error": "core unavailable"}), 500
        reply = n.handle(text)
        return jsonify({"reply": reply})

    @app.route("/memory", methods=["GET"])
    def memory():
        n = get_core()
        if not n:
            return jsonify({"facts": []})
        facts = n.db.list_facts(limit=200)
        return jsonify({"facts": facts})

def run_server():
    if not _flask_available:
        print("ERROR: Flask is not installed. Run: pip install flask")
        return
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Niblit HTTP server on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    run_server()
