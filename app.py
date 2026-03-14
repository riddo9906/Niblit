"""
app.py — Niblit Flask API for Vercel serverless deployment

Implements Flask-API style content negotiation with JSONRenderer,
HTMLRenderer, and BrowsableAPIRenderer.  All endpoints auto-select
the best renderer based on the incoming Accept header.
"""

import json as _json
import time
import logging
import os

try:
    from flask import Flask, request, jsonify, render_template_string, Response
    _flask_available = True
except ImportError:
    Flask = request = jsonify = render_template_string = Response = None
    _flask_available = False

try:
    from niblit_core import NiblitCore
except Exception:
    NiblitCore = None

if _flask_available:
    app = Flask(__name__)
else:
    app = None
    logging.getLogger("NiblitApp").warning("Flask not installed — app.py web server unavailable")

# ══════════════════════════════════════════════════════════════
# FLASK-API STYLE RENDERERS
# ══════════════════════════════════════════════════════════════

class JSONRenderer:
    """Renders response data as JSON.  Supports ?indent= query param."""
    media_type = "application/json"
    charset = None

    def render(self, data, media_type=None, **options):
        indent = options.get("indent") or request.args.get("indent")
        try:
            indent = int(indent)
        except (TypeError, ValueError):
            indent = None
        body = _json.dumps(data, indent=indent, default=str)
        ct = "application/json"
        return body, ct


class HTMLRenderer:
    """Returns pre-rendered HTML.  data must be a str."""
    media_type = "text/html"
    charset = "utf-8"

    def render(self, data, media_type=None, **options):
        if isinstance(data, str):
            return data, "text/html; charset=utf-8"
        body = _json.dumps(data, indent=2, default=str)
        return f"<pre>{body}</pre>", "text/html; charset=utf-8"


class BrowsableAPIRenderer:
    """Wraps JSON data in a minimal browsable HTML API page."""
    media_type = "text/html"
    charset = "utf-8"

    _TMPL = """\
<!doctype html><html><head>
<meta charset="utf-8"><title>Niblit API — {url}</title>
<style>
body{{font-family:Inter,monospace;background:#0b0b0f;color:#eaeaea;padding:24px}}
h2{{color:#0ea5a4}}pre{{background:#0f1720;padding:16px;border-radius:6px;
overflow:auto;color:#cfefff;font-size:13px}}
.badge{{display:inline-block;padding:4px 10px;border-radius:4px;
font-size:12px;font-weight:bold;background:#134e4a;color:#6ee7b7}}
</style></head><body>
<h2>Niblit Browsable API</h2>
<p><span class="badge">{status}</span>&nbsp;&nbsp;<code>{url}</code></p>
<pre>{data}</pre>
</body></html>"""

    def render(self, data, media_type=None, **options):
        status = options.get("status", "200 OK")
        url = request.url if request else ""
        body = _json.dumps(data, indent=2, default=str)
        html = self._TMPL.format(status=status, url=url, data=body)
        return html, "text/html; charset=utf-8"


_DEFAULT_RENDERERS = [JSONRenderer(), BrowsableAPIRenderer()]


def negotiate_renderer(renderers=None):
    """Pick the best renderer via Accept-header content negotiation."""
    active = renderers if renderers is not None else _DEFAULT_RENDERERS
    best = request.accept_mimetypes.best_match([r.media_type for r in active])
    for r in active:
        if r.media_type == best:
            return r
    return active[0]


def render_response(data, status=200, renderers=None, headers=None):
    """Content-negotiate and return a Flask Response."""
    # Standard HTTP status phrases for common codes
    _PHRASES = {
        200: "OK", 201: "Created", 204: "No Content",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 429: "Too Many Requests",
        500: "Internal Server Error", 503: "Service Unavailable",
    }
    phrase = _PHRASES.get(status, "OK" if status < 400 else "Error")
    status_str = f"{status} {phrase}"
    renderer = negotiate_renderer(renderers)
    body, ct = renderer.render(data, status_code=status, status=status_str)
    resp = Response(body, status=status, content_type=ct)
    if headers:
        for k, v in headers.items():
            resp.headers[k] = v
    return resp


# ══════════════════════════════════════════════════════════════
# API KEY PROTECTION
# ══════════════════════════════════════════════════════════════

API_KEY = os.environ.get("NIBLIT_API_KEY", None)


def require_key():
    if not API_KEY:
        return True
    req_key = request.headers.get("X-API-Key")
    return req_key == API_KEY


# ══════════════════════════════════════════════════════════════
# RATE LIMITING
# ══════════════════════════════════════════════════════════════

RATE_LIMIT = 10
RATE_WINDOW = 60
rate_store: dict = {}


def rate_limited(ip):
    now = time.time()
    entry = [t for t in rate_store.get(ip, []) if now - t < RATE_WINDOW]
    rate_store[ip] = entry
    if len(entry) >= RATE_LIMIT:
        return True
    rate_store[ip].append(now)
    return False


# ══════════════════════════════════════════════════════════════
# NIBLIT CORE LOADER (lazy — avoids cold-start penalty)
# ══════════════════════════════════════════════════════════════

_core = None


def get_core():
    global _core  # pylint: disable=global-statement
    if _core is None and NiblitCore:
        try:
            _core = NiblitCore()
        except Exception as exc:
            if app:
                app.logger.error("NiblitCore init error: %s", exc)
    return _core


# ══════════════════════════════════════════════════════════════
# COMMAND CATALOGUE  (used by /api/commands and the sidebar menu)
# ══════════════════════════════════════════════════════════════

COMMAND_GROUPS = [
    {
        "group": "Conversation",
        "icon": "💬",
        "commands": [
            {"label": "hi / hello / hey",        "cmd": "hi",            "desc": "Casual greeting"},
            {"label": "how are you?",             "cmd": "how are you",   "desc": "Check in"},
            {"label": "thanks",                   "cmd": "thanks",        "desc": "Say thank you"},
        ],
    },
    {
        "group": "Knowledge & Recall",
        "icon": "🧠",
        "commands": [
            {"label": "recall <topic>",           "cmd": "recall ",        "desc": "Search KnowledgeDB for any stored fact", "has_input": True},
            {"label": "acquired data",            "cmd": "acquired data",  "desc": "Browse all facts acquired by ALE processes"},
            {"label": "knowledge stats",          "cmd": "knowledge stats","desc": "Full KnowledgeDB summary"},
            {"label": "ale processes",            "cmd": "ale processes",  "desc": "Explain all 12 ALE steps + module status"},
            {"label": "kb stats",                 "cmd": "kb stats",       "desc": "KnowledgeDB statistics"},
        ],
    },
    {
        "group": "Research & Search",
        "icon": "🔍",
        "commands": [
            {"label": "search <query>",           "cmd": "search ",        "desc": "Search internet (primary data source)", "has_input": True, "is_search": True},
            {"label": "summary <query>",          "cmd": "summary ",       "desc": "Quick summary via internet", "has_input": True},
            {"label": "self-research <topic>",    "cmd": "self-research ", "desc": "Deep research using researcher + internet", "has_input": True},
        ],
    },
    {
        "group": "Self-Improvement",
        "icon": "⚡",
        "commands": [
            {"label": "self-idea <prompt>",       "cmd": "self-idea ",     "desc": "Generate & implement idea via SelfIdeaImplementation", "has_input": True},
            {"label": "self-implement <plan>",    "cmd": "self-implement ","desc": "Enqueue a plan to SelfImplementer", "has_input": True},
            {"label": "self-teach <topic>",       "cmd": "self-teach ",    "desc": "Teach a topic using SelfTeacher + research", "has_input": True},
            {"label": "idea-implement <prompt>",  "cmd": "idea-implement ","desc": "Generate and implement ideas", "has_input": True},
            {"label": "reflect <topic>",          "cmd": "reflect ",       "desc": "Reflect using ReflectModule", "has_input": True},
            {"label": "auto-reflect",             "cmd": "auto-reflect",   "desc": "Reflect on recent interactions"},
        ],
    },
    {
        "group": "Autonomous Learning",
        "icon": "🤖",
        "commands": [
            {"label": "autonomous-learn start",   "cmd": "autonomous-learn start",       "desc": "Start autonomous learning"},
            {"label": "autonomous-learn stop",    "cmd": "autonomous-learn stop",        "desc": "Stop autonomous learning"},
            {"label": "autonomous-learn status",  "cmd": "autonomous-learn status",      "desc": "View learning statistics"},
            {"label": "autonomous-learn code-status","cmd": "autonomous-learn code-status","desc": "Programming literacy loop status"},
            {"label": "add-topic <topic>",        "cmd": "autonomous-learn add-topic ",  "desc": "Add research topic", "has_input": True},
        ],
    },
    {
        "group": "Improvements",
        "icon": "🔧",
        "commands": [
            {"label": "show improvements",        "cmd": "show improvements",      "desc": "View 10 improvement modules"},
            {"label": "run improvement-cycle",    "cmd": "run improvement-cycle",  "desc": "Execute improvement cycle"},
            {"label": "improvement-status",       "cmd": "improvement-status",     "desc": "View improvement status"},
        ],
    },
    {
        "group": "System",
        "icon": "⚙️",
        "commands": [
            {"label": "status / health",          "cmd": "status",         "desc": "System status"},
            {"label": "toggle-llm on",            "cmd": "toggle-llm on",  "desc": "Enable LLM (use AI)"},
            {"label": "toggle-llm off",           "cmd": "toggle-llm off", "desc": "Disable LLM (use research mode)"},
            {"label": "help / commands",          "cmd": "help",           "desc": "Show all commands"},
            {"label": "start_slsa",               "cmd": "start_slsa",     "desc": "Start SLSA engine"},
            {"label": "stop_slsa",                "cmd": "stop_slsa",      "desc": "Stop SLSA engine"},
            {"label": "slsa-status",              "cmd": "slsa-status",    "desc": "SLSA status"},
        ],
    },
]


# ══════════════════════════════════════════════════════════════
# DASHBOARD HTML  (full web AI frontend)
# ══════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Niblit — Web AI</title>
  <style>
    :root{
      --bg:#0b0b0f;--sidebar:#0d1117;--panel:#0f1720;--border:#1a2640;
      --accent:#0ea5a4;--accent2:#134e4a;--text:#eaeaea;--dim:#8899a6;
      --user:#6ee7b7;--bot:#fbcf6b;--err:#f87171;--radius:8px;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:Inter,Arial,sans-serif;background:var(--bg);color:var(--text);
         display:flex;flex-direction:column;height:100vh;overflow:hidden}

    /* ── top bar ── */
    #topbar{background:var(--sidebar);border-bottom:1px solid var(--border);
            padding:10px 18px;display:flex;align-items:center;gap:14px;flex-shrink:0}
    #topbar h1{font-size:1.1rem;color:var(--accent);letter-spacing:.05em}
    #status-pill{font-size:.75rem;padding:3px 10px;border-radius:20px;
                 background:var(--accent2);color:var(--user)}
    #topbar-spacer{flex:1}
    #search-toggle{background:none;border:1px solid var(--border);color:var(--dim);
                   padding:5px 12px;border-radius:var(--radius);cursor:pointer;font-size:.8rem}
    #search-toggle:hover{border-color:var(--accent);color:var(--accent)}

    /* ── layout ── */
    #layout{display:flex;flex:1;overflow:hidden}

    /* ── sidebar ── */
    #sidebar{width:260px;background:var(--sidebar);border-right:1px solid var(--border);
             overflow-y:auto;flex-shrink:0;display:flex;flex-direction:column}
    #sidebar-header{padding:12px 14px;font-size:.7rem;color:var(--dim);
                    text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid var(--border)}
    .cmd-group{border-bottom:1px solid var(--border)}
    .group-toggle{width:100%;background:none;border:none;color:var(--text);
                  padding:9px 14px;text-align:left;cursor:pointer;display:flex;
                  align-items:center;gap:8px;font-size:.82rem;font-weight:600}
    .group-toggle:hover{background:rgba(14,165,164,.07)}
    .group-toggle .arrow{margin-left:auto;font-size:.65rem;transition:transform .2s}
    .group-toggle.open .arrow{transform:rotate(90deg)}
    .cmd-list{display:none;padding:0 0 4px 0}
    .cmd-list.visible{display:block}
    .cmd-item{padding:6px 14px 6px 36px;font-size:.78rem;color:var(--dim);
              cursor:pointer;line-height:1.4;transition:background .15s,color .15s}
    .cmd-item:hover{background:rgba(14,165,164,.1);color:var(--text)}
    .cmd-item .cmd-desc{font-size:.7rem;color:#55667a;display:block;margin-top:1px}

    /* ── main area ── */
    #main{flex:1;display:flex;flex-direction:column;overflow:hidden}

    /* ── search bar (collapsible) ── */
    #search-bar{background:var(--panel);border-bottom:1px solid var(--border);
                padding:10px 14px;display:none;gap:8px;align-items:center}
    #search-bar.visible{display:flex}
    #search-input{flex:1;background:var(--bg);border:1px solid var(--border);
                  color:var(--text);padding:7px 12px;border-radius:var(--radius);
                  font-size:.85rem;outline:none}
    #search-input:focus{border-color:var(--accent)}
    #search-input::placeholder{color:var(--dim)}
    #search-btn{background:var(--accent);color:#012;border:none;padding:7px 16px;
                border-radius:var(--radius);cursor:pointer;font-weight:600;font-size:.82rem}
    #search-btn:hover{opacity:.85}

    /* ── chat window ── */
    #chatbox{flex:1;overflow-y:auto;padding:18px 24px;display:flex;flex-direction:column;gap:12px}
    .msg{max-width:78%;padding:10px 14px;border-radius:var(--radius);
         font-size:.86rem;line-height:1.6;word-break:break-word}
    .msg.user{align-self:flex-end;background:var(--accent2);color:var(--user);
              border-bottom-right-radius:2px}
    .msg.bot{align-self:flex-start;background:var(--panel);color:var(--bot);
             border-bottom-left-radius:2px;border:1px solid var(--border)}
    .msg.err{align-self:flex-start;background:#2d1515;color:var(--err);
             border:1px solid #5a1e1e;border-bottom-left-radius:2px}
    .msg .label{font-size:.68rem;font-weight:700;text-transform:uppercase;
                letter-spacing:.06em;margin-bottom:4px;opacity:.7}
    .msg pre{background:rgba(0,0,0,.3);padding:8px;border-radius:4px;
             overflow-x:auto;font-size:.78rem;margin-top:6px}

    /* ── typing indicator ── */
    #typing{align-self:flex-start;padding:8px 14px;color:var(--dim);
            font-size:.8rem;display:none;font-style:italic}

    /* ── chat input ── */
    #chat-input-area{background:var(--panel);border-top:1px solid var(--border);
                     padding:12px 16px;display:flex;gap:10px;align-items:flex-end;flex-shrink:0}
    #chat-input{flex:1;background:var(--bg);border:1px solid var(--border);
                color:var(--text);padding:9px 14px;border-radius:var(--radius);
                font-size:.9rem;outline:none;resize:none;max-height:120px;
                font-family:inherit;line-height:1.5}
    #chat-input:focus{border-color:var(--accent)}
    #chat-input::placeholder{color:var(--dim)}
    #send-btn{background:var(--accent);color:#012;border:none;padding:9px 20px;
              border-radius:var(--radius);cursor:pointer;font-weight:700;
              font-size:.9rem;flex-shrink:0}
    #send-btn:hover{opacity:.85}
    #send-btn:disabled{opacity:.4;cursor:not-allowed}

    /* ── scrollbar ── */
    ::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:transparent}
    ::-webkit-scrollbar-thumb{background:#1a2640;border-radius:3px}

    /* ── mobile ── */
    @media(max-width:680px){
      #sidebar{width:0;overflow:hidden;transition:width .25s}
      #sidebar.open{width:240px}
      #menu-btn{display:flex!important}
    }
    #menu-btn{display:none;background:none;border:none;color:var(--text);
              font-size:1.3rem;cursor:pointer;padding:4px 6px}
  </style>
</head>
<body>

<!-- top bar -->
<div id="topbar">
  <button id="menu-btn" aria-label="Toggle menu">☰</button>
  <h1>🤖 Niblit <span style="font-weight:300;font-size:.8rem">Web AI</span></h1>
  <span id="status-pill">connecting…</span>
  <div id="topbar-spacer"></div>
  <button id="search-toggle" onclick="toggleSearch()">🔍 Search</button>
</div>

<!-- layout -->
<div id="layout">

  <!-- sidebar command menu -->
  <nav id="sidebar">
    <div id="sidebar-header">Commands</div>
    <!-- groups injected by JS -->
  </nav>

  <!-- main -->
  <div id="main">

    <!-- search bar -->
    <div id="search-bar">
      <input id="search-input" type="text" placeholder="Search the internet via Niblit…" autocomplete="off"/>
      <button id="search-btn" onclick="runSearch()">Search</button>
    </div>

    <!-- chat window -->
    <div id="chatbox"></div>
    <div id="typing">Niblit is thinking…</div>

    <!-- chat input -->
    <div id="chat-input-area">
      <textarea id="chat-input" rows="1" placeholder="Type a command or question… (Enter to send, Shift+Enter for newline)"></textarea>
      <button id="send-btn" onclick="sendChat()">Send</button>
    </div>
  </div>
</div>

<script>
// ── command groups (injected from Flask) ──
const GROUPS = __JSON_GROUPS__;

// ── build sidebar ──
const sidebar = document.getElementById('sidebar');
GROUPS.forEach((g, gi) => {
  const group = document.createElement('div');
  group.className = 'cmd-group';
  const btn = document.createElement('button');
  btn.className = 'group-toggle';
  btn.innerHTML = `<span>${g.icon}</span><span>${g.group}</span><span class="arrow">▶</span>`;
  btn.onclick = () => {
    btn.classList.toggle('open');
    list.classList.toggle('visible');
  };
  const list = document.createElement('div');
  list.className = 'cmd-list' + (gi === 0 ? ' visible' : '');
  if (gi === 0) btn.classList.add('open');
  g.commands.forEach(c => {
    const item = document.createElement('div');
    item.className = 'cmd-item';
    item.innerHTML = `${c.label}<span class="cmd-desc">${c.desc}</span>`;
    item.onclick = () => {
      if (c.is_search) {
        // open search bar pre-filled
        document.getElementById('search-bar').classList.add('visible');
        document.getElementById('search-input').focus();
      } else if (c.has_input) {
        const inp = document.getElementById('chat-input');
        inp.value = c.cmd;
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
        autoResize(inp);
      } else {
        sendText(c.cmd);
      }
    };
    list.appendChild(item);
  });
  group.appendChild(btn);
  group.appendChild(list);
  sidebar.appendChild(group);
});

// ── mobile menu toggle ──
document.getElementById('menu-btn').onclick = () =>
  document.getElementById('sidebar').classList.toggle('open');

// ── search bar toggle ──
function toggleSearch() {
  const bar = document.getElementById('search-bar');
  bar.classList.toggle('visible');
  if (bar.classList.contains('visible'))
    document.getElementById('search-input').focus();
}

// ── search enter key ──
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); runSearch(); }
});

async function runSearch() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  document.getElementById('search-input').value = '';
  document.getElementById('search-bar').classList.remove('visible');
  await sendText('search ' + q);
}

// ── chat helpers ──
function addMsg(role, text) {
  const box = document.getElementById('chatbox');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const label = role === 'user' ? 'You' : role === 'bot' ? 'Niblit' : 'Error';
  // format pre blocks for long output
  const escaped = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const formatted = escaped.length > 400
    ? `<div class="label">${label}</div><pre>${escaped}</pre>`
    : `<div class="label">${label}</div>${escaped}`;
  div.innerHTML = formatted;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function setTyping(on) {
  document.getElementById('typing').style.display = on ? 'block' : 'none';
  document.getElementById('send-btn').disabled = on;
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

document.getElementById('chat-input').addEventListener('input', function(){ autoResize(this); });
document.getElementById('chat-input').addEventListener('keydown', function(e){
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

function sendChat() {
  const inp = document.getElementById('chat-input');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  autoResize(inp);
  sendText(text);
}

async function sendText(text) {
  addMsg('user', text);
  setTyping(true);
  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    const j = await resp.json();
    if (j.error) addMsg('err', j.error);
    else addMsg('bot', j.reply || '[no reply]');
  } catch(ex) {
    addMsg('err', 'Network error: ' + ex.message);
  } finally {
    setTyping(false);
  }
}

// ── status poll ──
async function pollStatus() {
  try {
    const r = await fetch('/ping');
    const j = await r.json();
    const mood = j.personality && j.personality.mood ? ` · ${j.personality.mood}` : '';
    document.getElementById('status-pill').textContent =
      j.status === 'ok' ? `online${mood}` : j.status || 'degraded';
    document.getElementById('status-pill').style.background =
      j.status === 'ok' ? 'var(--accent2)' : '#3d1515';
    document.getElementById('status-pill').style.color =
      j.status === 'ok' ? 'var(--user)' : 'var(--err)';
  } catch(_) {
    document.getElementById('status-pill').textContent = 'offline';
    document.getElementById('status-pill').style.background = '#3d1515';
    document.getElementById('status-pill').style.color = 'var(--err)';
  }
}
setInterval(pollStatus, 6000);
pollStatus();

// ── welcome message ──
addMsg('bot', 'Hello! I\'m Niblit, your autonomous AI assistant. Type a command, use the sidebar menu, or ask me anything. Use 🔍 Search to search the internet.');
</script>
</body>
</html>
"""


def _build_dashboard():
    """Inject Python-side data (COMMAND_GROUPS) into the dashboard HTML template."""
    groups_json = _json.dumps(COMMAND_GROUPS)
    return DASHBOARD_HTML.replace("__JSON_GROUPS__", groups_json)


# ══════════════════════════════════════════════════════════════
# FLASK ROUTES
# ══════════════════════════════════════════════════════════════

if _flask_available:

    # ── Liveness probe ──────────────────────────────────────
    @app.route("/health", methods=["GET"])
    def health():
        """Lightweight liveness probe — no NiblitCore init required."""
        return render_response({"status": "ok", "service": "niblit"})

    # ── Dashboard / root ────────────────────────────────────
    @app.route("/", methods=["GET"])
    def dashboard():
        renderer = negotiate_renderer([HTMLRenderer(), JSONRenderer()])
        if isinstance(renderer, HTMLRenderer):
            return Response(_build_dashboard(), content_type="text/html; charset=utf-8")
        return render_response({"service": "niblit", "status": "ok",
                                "endpoints": ["/api/commands", "/api/search",
                                              "/api/status", "/ping", "/chat", "/memory"]})

    # ── Ping / personality ──────────────────────────────────
    @app.route("/ping", methods=["GET"])
    def ping():
        if rate_limited(request.remote_addr):
            return render_response({"error": "rate limit reached"}, status=429)
        core = get_core()
        try:
            p = core.memory.get_personality() if core else {}
        except Exception:
            p = {}
        return render_response({"status": "ok" if core else "no-core", "personality": p})

    # ── API: list commands ───────────────────────────────────
    @app.route("/api/commands", methods=["GET"])
    def api_commands():
        """Return the full command catalogue (used by the sidebar menu)."""
        return render_response({"commands": COMMAND_GROUPS, "count": sum(len(g["commands"]) for g in COMMAND_GROUPS)})

    # ── API: system status ───────────────────────────────────
    @app.route("/api/status", methods=["GET"])
    def api_status():
        """Return detailed system status."""
        if rate_limited(request.remote_addr):
            return render_response({"error": "rate limit reached"}, status=429)
        core = get_core()
        data = {"online": core is not None, "service": "niblit"}
        if core:
            try:
                data["personality"] = core.memory.get_personality()
            except Exception:
                pass
            try:
                # Use a small limit just to obtain a count — the memory API
                # does not currently expose a dedicated count method.
                data["facts_count"] = len(core.memory.list_facts(limit=500))
            except Exception:
                pass
        return render_response(data)

    # ── API: search ─────────────────────────────────────────
    @app.route("/api/search", methods=["GET", "POST"])
    def api_search():
        """Dedicated search endpoint — wraps the 'search <query>' command."""
        if not require_key():
            return render_response({"error": "unauthorized"}, status=401)
        if rate_limited(request.remote_addr):
            return render_response({"error": "rate limit reached"}, status=429)
        # Accept query from JSON body, form data, or query string
        if request.method == "POST":
            body = request.get_json(force=True, silent=True) or {}
            query = body.get("query") or body.get("text") or ""
        else:
            query = request.args.get("q") or request.args.get("query") or ""
        query = query.strip()
        if not query:
            return render_response({"error": "missing query — send ?q=<query> or POST {\"query\":\"...\"}"},
                                   status=400)
        core = get_core()
        if not core:
            return render_response({"error": "core failed"}, status=500)
        try:
            result = core.handle(f"search {query}")
        except Exception as exc:
            result = f"[error] {exc}"
        return render_response({"query": query, "result": result})

    # ── Chat ────────────────────────────────────────────────
    @app.route("/chat", methods=["POST"])
    def chat():
        if not require_key():
            return render_response({"error": "unauthorized"}, status=401)
        if rate_limited(request.remote_addr):
            return render_response({"error": "rate limit reached"}, status=429)
        core = get_core()
        if not core:
            return render_response({"error": "core failed"}, status=500)
        data = request.get_json(force=True, silent=True) or {}
        text = data.get("text", "").strip()
        if not text:
            return render_response({"error": "no text provided"}, status=400)
        try:
            reply = core.handle(text)
        except Exception as exc:
            reply = f"[error] {exc}"
        return render_response({"reply": reply})

    # ── Memory ──────────────────────────────────────────────
    @app.route("/memory", methods=["GET"])
    def memory():
        if not require_key():
            return render_response({"error": "unauthorized"}, status=401)
        if rate_limited(request.remote_addr):
            return render_response({"error": "rate limit reached"}, status=429)
        core = get_core()
        facts = []
        if core:
            try:
                facts = core.memory.list_facts(limit=200)
            except Exception:
                pass
        return render_response({"facts": facts, "count": len(facts)})


# ══════════════════════════════════════════════════════════════
# LOCAL DEV ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not _flask_available:
        print("ERROR: Flask is not installed. Run: pip install flask")
    else:
        port = int(os.environ.get("PORT", 5000))
        print(f"Starting Niblit Web AI on http://0.0.0.0:{port}")
        app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
