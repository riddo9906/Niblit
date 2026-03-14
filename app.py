try:
    from flask import Flask, request, jsonify, render_template_string
    _flask_available = True
except ImportError:
    Flask = request = jsonify = render_template_string = None
    _flask_available = False
import time, logging, os
try:
    from niblit_core import NiblitCore
except Exception:
    NiblitCore = None

if _flask_available:
    app = Flask(__name__)
else:
    app = None
    logging.getLogger("NiblitApp").warning("Flask not installed — app.py web server unavailable")

# ------------------------------
# API Key Protection
# ------------------------------
API_KEY = os.environ.get("NIBLIT_API_KEY", None)

def require_key():
    if not API_KEY:
        return True   # key unset: no restriction
    req_key = request.headers.get("X-API-Key")
    return req_key == API_KEY

# ------------------------------
# Rate Limiting (simple)
# ------------------------------
RATE_LIMIT = 10              # requests
RATE_WINDOW = 60             # seconds
rate_store = {}

def rate_limited(ip):
    now = time.time()
    entry = rate_store.get(ip, [])
    # remove old timestamps
    entry = [t for t in entry if now - t < RATE_WINDOW]
    rate_store[ip] = entry
    if len(entry) >= RATE_LIMIT:
        return True
    rate_store[ip].append(now)
    return False

# ------------------------------
# Niblit Core Loader
# ------------------------------
_core = None
def get_core():
    global _core
    if _core is None and NiblitCore:
        try:
            _core = NiblitCore()
        except Exception as e:
            app.logger.error(f"NiblitCore init error: {e}")
            _core = None
    return _core

# ------------------------------
# Dashboard UI
# ------------------------------
DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Niblit Dashboard</title>
  <style>
    body{font-family:Inter,Arial;background:#0b0b0f;color:#eaeaea;padding:20px}
    .card{background:#0f1720;padding:18px;border-radius:8px;box-shadow:0 6px 18px rgba(2,6,23,0.6);max-width:980px;margin:auto}
    textarea{width:100%;height:90px;background:#071023;border:1px solid #142236;color:#cfefff;padding:8px;border-radius:6px}
    button{padding:10px 16px;border-radius:6px;border:none;background:#0ea5a4;color:#012}
    #chatbox{height:260px;background:#04060a;border-radius:6px;padding:10px;overflow:auto;margin-top:10px;border:1px solid #122}
    .user{color:#6ee7b7} .bot{color:#fbcf6b}
  </style>
</head>
<body>
<div class="card">
  <h1>Niblit (Web)</h1>
  <p>System status: <span id="status">loading...</span></p>
  <textarea id="input" placeholder="Type a command..."></textarea><br>
  <button onclick="send()">Send</button>
  <div id="chatbox"></div>
</div>

<script>
async function send(){
  let t=document.getElementById("input").value;
  if(!t) return;
  let c=document.getElementById("chatbox");
  c.innerHTML+='<div class="user"><b>You:</b> '+t+'</div>';
  document.getElementById("input").value='';
  let resp=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})});
  let j=await resp.json();
  c.innerHTML+='<div class="bot"><b>Niblit:</b> '+(j.reply||"[no reply]")+'</div>';
  c.scrollTop=c.scrollHeight;
}
async function status(){
  let r=await fetch('/ping'); let j=await r.json();
  document.getElementById('status').innerText=j.status+" (mood:"+j.personality?.mood+")";
}
setInterval(status,5000); status();
</script>
</body>
</html>
"""

if _flask_available:
    @app.route("/health", methods=["GET"])
    def health():
        """Lightweight liveness probe — no NiblitCore init required."""
        return jsonify({"status": "ok", "service": "niblit"})

    @app.route("/", methods=["GET"])
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/ping")
    def ping():
        if rate_limited(request.remote_addr):
            return jsonify({"error": "rate limit reached"}), 429
        core = get_core()
        if not core: return jsonify({"status":"no-core"})
        try:
            p = core.memory.get_personality()
        except:
            p = {}
        return jsonify({"status":"ok","personality":p})

    @app.route("/chat", methods=["POST"])
    def chat():
        if not require_key():
            return jsonify({"error":"unauthorized"}), 401
        if rate_limited(request.remote_addr):
            return jsonify({"error": "rate limit reached"}), 429
        core = get_core()
        if not core:
            return jsonify({"error":"core failed"}), 500
        data = request.get_json(force=True) or {}
        text = data.get("text","")
        try:
            r = core.handle(text)
        except Exception as e:
            r = f"[error] {e}"
        return jsonify({"reply":r})

    @app.route("/memory")
    def memory():
        if not require_key():
            return jsonify({"error":"unauthorized"}), 401
        if rate_limited(request.remote_addr):
            return jsonify({"error": "rate limit reached"}), 429
        core = get_core()
        if not core:
            return jsonify({"facts":[]})
        try:
            f = core.memory.list_facts(limit=200)
        except:
            f = []
        return jsonify({"facts":f})

if __name__ == "__main__":
    if not _flask_available:
        print("ERROR: Flask is not installed. Run: pip install flask")
    else:
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
