"""
app.py — Niblit Flask API for Vercel serverless deployment

Implements Flask-API style content negotiation with JSONRenderer,
HTMLRenderer, and BrowsableAPIRenderer.  All endpoints auto-select
the best renderer based on the incoming Accept header.

The /chat endpoint mirrors the run_shell() logic from main.py so that
the web experience is identical to running Niblit in a Termux terminal.
"""

import difflib
import datetime
import json as _json
import threading
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
# MAIN.PY HELPERS  (mirrors the helpers in main.py exactly)
# ══════════════════════════════════════════════════════════════

# Commands list used by suggest_command — same as main.py.
# Direct command keys (help, status, memory, self-heal, self-teach, threads)
# plus routed-prefix stems and a few extras mirror main.py COMMANDS list.
_DIRECT_CMD_KEYS = ("help", "commands", "status", "health", "memory",
                    "self-heal", "self-teach", "threads")
# Prefixes handled by NiblitRouter — module-level constant used by both
# suggest_command and _shell_process to ensure a single source of truth.
_ROUTED_PREFIXES = ("search ", "summary ", "self-research ", "learn about ")
_SHELL_COMMANDS = list(_DIRECT_CMD_KEYS) + [
    "search", "summary", "self-research", "learn about",
    "debug on", "debug off",
]


def _ts():
    """Return a timestamp string matching NiblitIO.timestamp() format."""
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def suggest_command(user_input):
    """Return close-match suggestions exactly like main.py suggest_command()."""
    return difflib.get_close_matches(user_input, _SHELL_COMMANDS, n=3, cutoff=0.5)


def _list_threads():
    """Return thread list string exactly like main.py list_threads()."""
    return "\n".join(
        f"{t.name} | alive={t.is_alive()}"
        for t in threading.enumerate()
    )


# ── Boot messages (generated once, cached) ──────────────────
_boot_messages: list = []
_boot_lock = threading.Lock()


def _get_boot_messages():
    """
    Return the boot messages that main.py would print to the terminal.
    Triggers NiblitCore init (lazy) and captures the sequence.
    """
    global _boot_messages  # pylint: disable=global-statement
    with _boot_lock:
        if _boot_messages:
            return list(_boot_messages)
        msgs = []
        msgs.append(f"{_ts()} TRUE AUTONOMOUS NIBLIT BOOT")
        core = get_core()
        if core:
            msgs.append(f"{_ts()} CORE READY")
            msgs.append(f"{_ts()} [DEBUG] Active Threads After Boot:")
            msgs.append(f"{_ts()} [DEBUG] {_list_threads()}")
            msgs.append(f"{_ts()} READY")
        else:
            msgs.append(f"{_ts()} [WARN] NiblitCore failed to initialise — running in degraded mode")
            msgs.append(f"{_ts()} READY (degraded)")
        _boot_messages = msgs
        return list(msgs)


# ── Direct commands map (mirrors DIRECT_COMMANDS in main.py) ─

def _direct_commands(core):
    """Build the same direct-commands dict as main.py's DIRECT_COMMANDS."""
    def _status():
        lines = ["[STATUS]", f"LLM enabled: {getattr(core, 'llm_enabled', 'N/A')}"]
        try:
            mem_count = len(core.db.recent_interactions(50)) if hasattr(core.db, "recent_interactions") else "N/A"
        except Exception:
            mem_count = "N/A"
        lines.append(f"Memory entries: {mem_count}")
        return "\n".join(lines)

    def _memory():
        try:
            entries = core.db.recent_interactions(50) if hasattr(core.db, "recent_interactions") else []
            return "\n".join(str(e) for e in entries) or "[No memory entries]"
        except Exception:
            return "[Memory API missing]"

    def _self_heal():
        healer = getattr(core, "self_healer", None)
        if healer and hasattr(healer, "run_cycle"):
            try:
                return healer.run_cycle()
            except Exception as exc:
                return f"[SELF-HEAL ERROR] {exc}"
        return "[SELF-HEAL NOT AVAILABLE]"

    def _self_teach():
        teacher = getattr(core, "self_teacher", None)
        if teacher and hasattr(teacher, "teach"):
            try:
                return teacher.teach()
            except Exception as exc:
                return f"[SELF-TEACH ERROR] {exc}"
        return "[SELF-TEACH NOT AVAILABLE]"

    def _help():
        try:
            return core.help_text()
        except Exception:
            return "[help unavailable]"

    return {
        "help": _help,
        "commands": _help,
        "status": _status,
        "health": _status,
        "memory": _memory,
        "self-heal": _self_heal,
        "self-teach": _self_teach,
        "threads": _list_threads,
    }


# ── Shell-style command processor (mirrors run_shell in main.py) ─

def _shell_process(core, user_input: str) -> dict:
    """
    Process user_input exactly the way main.py run_shell() does and return
    a structured dict with: reply, suggestion, ts, debug_lines.
    """
    cmd = user_input.strip()
    lower = cmd.lower()
    ts = _ts()

    # EXIT / QUIT — acknowledged but we don't actually shut the server down
    if lower in ("exit", "quit", "shutdown"):
        return {"reply": f"{ts} Shutdown acknowledged (server continues running).",
                "suggestion": None, "ts": ts, "debug_lines": []}

    debug_lines = [f"{ts} [DEBUG] COMMAND RECEIVED → {cmd}"]

    # DIRECT COMMANDS (exact match, same as main.py)
    direct = _direct_commands(core)
    if lower in direct:
        try:
            result = direct[lower]()
            debug_lines.append(f"{_ts()} [DEBUG] COMMAND RESULT ← {lower}")
        except Exception as exc:
            result = f"[Command failed] {exc}"
        return {"reply": str(result), "suggestion": None, "ts": ts, "debug_lines": debug_lines}

    # ROUTED COMMANDS (search, summary, self-research, learn about)
    if any(lower.startswith(p) for p in _ROUTED_PREFIXES):
        debug_lines.append(f"{_ts()} [DEBUG] ROUTER PROCESS → {cmd}")
        if core.router:
            resp = core.router.process(cmd)
        else:
            resp = core.handle(cmd)
        debug_lines.append(f"{_ts()} [DEBUG] ROUTER RESULT RETURNED")
        return {"reply": str(resp), "suggestion": None, "ts": ts, "debug_lines": debug_lines}

    # CATCH-ALL — pass to core.handle() exactly like main.py
    debug_lines.append(f"{_ts()} [DEBUG] Passing to core.handle()")
    response = core.handle(cmd)

    # Suggestion engine (same as main.py)
    suggestion = None
    sug = suggest_command(lower)
    if sug:
        suggestion = f"Did you mean: {sug[0]} ?"

    return {"reply": str(response), "suggestion": suggestion, "ts": ts, "debug_lines": debug_lines}



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
# DASHBOARD HTML  (terminal-style web AI frontend)
#
# On load the UI calls /api/boot which returns the same messages
# that main.py boot() prints to the Termux terminal, then drops
# the user into an interactive "Niblit > " prompt — identical to
# running Niblit locally.
# ══════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Niblit AIOS</title>
  <style>
    :root{
      --bg:#0b0e14;--panel:#0d1117;--border:#1a2640;
      --accent:#0ea5a4;--accent2:#134e4a;
      --green:#39d353;--yellow:#fbcf6b;--red:#f87171;--dim:#566a7f;
      --font:'Courier New',Courier,monospace;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html,body{height:100%;background:var(--bg);color:var(--green);
              font-family:var(--font);font-size:13px;line-height:1.55}

    /* ── top bar ── */
    #topbar{background:var(--panel);border-bottom:1px solid var(--border);
            padding:6px 14px;display:flex;align-items:center;gap:12px;
            font-size:11px;color:var(--dim);flex-shrink:0}
    #topbar .title{color:var(--accent);font-weight:bold;font-size:13px;letter-spacing:.06em}
    #status-pill{padding:2px 9px;border-radius:10px;background:var(--accent2);
                 color:var(--green);font-size:10px;font-weight:bold}
    #topbar-right{margin-left:auto;display:flex;gap:8px;align-items:center}
    .tb-btn{background:none;border:1px solid var(--border);color:var(--dim);
            padding:3px 10px;border-radius:4px;cursor:pointer;font-size:10px;
            font-family:var(--font)}
    .tb-btn:hover{border-color:var(--accent);color:var(--accent)}

    /* ── layout ── */
    #layout{display:flex;height:calc(100vh - 33px)}

    /* ── sidebar ── */
    #sidebar{width:240px;background:var(--panel);border-right:1px solid var(--border);
             overflow-y:auto;display:flex;flex-direction:column;flex-shrink:0;
             transition:width .2s}
    #sidebar.collapsed{width:0;overflow:hidden}
    .sb-section{border-bottom:1px solid var(--border)}
    .sb-toggle{width:100%;background:none;border:none;color:var(--yellow);
               padding:7px 10px;text-align:left;cursor:pointer;
               font-family:var(--font);font-size:11px;font-weight:bold;
               display:flex;align-items:center;gap:6px}
    .sb-toggle:hover{background:rgba(14,165,164,.08)}
    .sb-toggle .arr{margin-left:auto;font-size:9px;transition:transform .2s}
    .sb-toggle.open .arr{transform:rotate(90deg)}
    .sb-list{display:none;padding-bottom:4px}
    .sb-list.vis{display:block}
    .sb-item{padding:4px 10px 4px 24px;color:var(--dim);cursor:pointer;
             font-size:11px;line-height:1.4}
    .sb-item:hover{color:var(--green);background:rgba(57,211,83,.06)}
    .sb-item .desc{font-size:10px;color:#3a4a5a;display:block;margin-top:1px}

    /* ── terminal main area ── */
    #main{flex:1;display:flex;flex-direction:column;overflow:hidden}

    /* ── search bar ── */
    #search-bar{background:#0a0f1a;border-bottom:1px solid var(--border);
                padding:7px 12px;display:none;gap:8px;align-items:center}
    #search-bar.vis{display:flex}
    #search-input{flex:1;background:var(--bg);border:1px solid var(--border);
                  color:var(--green);padding:5px 10px;border-radius:4px;
                  font-family:var(--font);font-size:12px;outline:none}
    #search-input:focus{border-color:var(--accent)}
    #search-input::placeholder{color:var(--dim)}
    #s-btn{background:var(--accent);color:#012;border:none;padding:5px 14px;
           border-radius:4px;cursor:pointer;font-family:var(--font);font-weight:bold;font-size:11px}
    #s-btn:hover{opacity:.85}

    /* ── terminal output ── */
    #terminal{flex:1;overflow-y:auto;padding:12px 16px;
              display:flex;flex-direction:column;gap:2px}
    .tline{white-space:pre-wrap;word-break:break-word;line-height:1.5}
    .tline.boot{color:#4a90d9}
    .tline.debug{color:var(--dim);font-size:11px}
    .tline.prompt{color:var(--yellow)}
    .tline.response{color:var(--green)}
    .tline.suggestion{color:var(--accent);font-style:italic;font-size:11px}
    .tline.err{color:var(--red)}
    .tline.sep{color:#1e2d3d}
    .cursor-blink{display:inline-block;width:7px;height:13px;background:var(--green);
                  vertical-align:bottom;animation:blink 1s step-end infinite}
    @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}

    /* ── typing indicator ── */
    #thinking{color:var(--dim);font-size:11px;padding:4px 16px;
              display:none;font-style:italic}

    /* ── input row ── */
    #input-row{background:#0a0f1a;border-top:1px solid var(--border);
               padding:8px 12px;display:flex;align-items:center;gap:8px;flex-shrink:0}
    #prompt-label{color:var(--yellow);white-space:nowrap;font-weight:bold;font-size:13px}
    #chat-input{flex:1;background:transparent;border:none;color:var(--green);
                font-family:var(--font);font-size:13px;outline:none;
                caret-color:var(--green)}
    #chat-input::placeholder{color:var(--dim)}
    #send-btn{background:var(--accent);color:#012;border:none;padding:6px 16px;
              border-radius:4px;cursor:pointer;font-family:var(--font);
              font-weight:bold;font-size:12px;white-space:nowrap}
    #send-btn:hover{opacity:.85}
    #send-btn:disabled{opacity:.35;cursor:not-allowed}

    /* ── scrollbar ── */
    ::-webkit-scrollbar{width:5px}
    ::-webkit-scrollbar-thumb{background:#1a2640;border-radius:3px}

    /* ── mobile ── */
    @media(max-width:640px){
      #sidebar{width:0}#sidebar.open{width:220px}
      #menu-btn{display:flex!important}
    }
    #menu-btn{display:none;background:none;border:none;color:var(--dim);
              font-size:1.2rem;cursor:pointer}
  </style>
</head>
<body>

<!-- top bar -->
<div id="topbar">
  <button id="menu-btn" aria-label="menu">☰</button>
  <span class="title">NIBLIT AIOS</span>
  <span id="status-pill">booting…</span>
  <div id="topbar-right">
    <button class="tb-btn" onclick="toggleSearch()">🔍 Search</button>
    <button class="tb-btn" onclick="toggleSidebar()">⌘ Commands</button>
  </div>
</div>

<!-- layout -->
<div id="layout">

  <!-- sidebar -->
  <nav id="sidebar"><!-- populated by JS --></nav>

  <!-- terminal area -->
  <div id="main">

    <!-- search bar -->
    <div id="search-bar">
      <input id="search-input" type="text" placeholder="Search via Niblit…" autocomplete="off"/>
      <button id="s-btn" onclick="runSearch()">Search</button>
    </div>

    <!-- terminal output -->
    <div id="terminal"></div>
    <div id="thinking">Niblit is thinking…</div>

    <!-- input row -->
    <div id="input-row">
      <span id="prompt-label">Niblit &gt;</span>
      <input id="chat-input" type="text" placeholder="type a command…" autocomplete="off" spellcheck="false"/>
      <button id="send-btn" onclick="sendChat()">Send</button>
    </div>

  </div>
</div>

<script>
// ── command groups injected by Flask ──
const GROUPS = __JSON_GROUPS__;

// ── build sidebar ──
const sbEl = document.getElementById('sidebar');
GROUPS.forEach((g,gi)=>{
  const sec = document.createElement('div'); sec.className='sb-section';
  const tog = document.createElement('button'); tog.className='sb-toggle'+(gi===0?' open':'');
  tog.innerHTML=`<span>${g.icon}</span><span>${g.group}</span><span class="arr">▶</span>`;
  const lst = document.createElement('div'); lst.className='sb-list'+(gi===0?' vis':'');
  tog.onclick=()=>{ tog.classList.toggle('open'); lst.classList.toggle('vis'); };
  g.commands.forEach(c=>{
    const it=document.createElement('div'); it.className='sb-item';
    it.innerHTML=`${c.label}<span class="desc">${c.desc}</span>`;
    it.onclick=()=>{
      if(c.is_search){
        document.getElementById('search-bar').classList.add('vis');
        document.getElementById('search-input').focus();
      } else if(c.has_input){
        const inp=document.getElementById('chat-input');
        inp.value=c.cmd; inp.focus();
      } else { sendText(c.cmd); }
    };
    lst.appendChild(it);
  });
  sec.appendChild(tog); sec.appendChild(lst); sbEl.appendChild(sec);
});

function toggleSidebar(){
  document.getElementById('sidebar').classList.toggle('collapsed');
}
document.getElementById('menu-btn').onclick=()=>
  document.getElementById('sidebar').classList.toggle('open');

// ── search bar ──
function toggleSearch(){
  const b=document.getElementById('search-bar');
  b.classList.toggle('vis');
  if(b.classList.contains('vis')) document.getElementById('search-input').focus();
}
document.getElementById('search-input').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();runSearch();}
});
async function runSearch(){
  const q=document.getElementById('search-input').value.trim();
  if(!q) return;
  document.getElementById('search-input').value='';
  document.getElementById('search-bar').classList.remove('vis');
  await sendText('search '+q);
}

// ── terminal helpers ──
const term = document.getElementById('terminal');

function tline(text, cls){
  const d=document.createElement('div'); d.className='tline '+(cls||'');
  d.textContent=text;
  term.appendChild(d);
  term.scrollTop=term.scrollHeight;
}

function tlineHTML(html, cls){
  const d=document.createElement('div'); d.className='tline '+(cls||'');
  d.innerHTML=html;
  term.appendChild(d);
  term.scrollTop=term.scrollHeight;
}

function setThinking(on){
  document.getElementById('thinking').style.display=on?'block':'none';
  document.getElementById('send-btn').disabled=on;
  document.getElementById('chat-input').disabled=on;
}

// ── boot sequence ──
async function boot(){
  tline('','sep');
  tline('╔══════════════════════════════════════╗','boot');
  tline('║   NIBLIT AIOS — TRUE AUTONOMOUS AI   ║','boot');
  tline('╚══════════════════════════════════════╝','boot');
  tline('','sep');
  setThinking(true);
  try {
    const r=await fetch('/api/boot');
    const j=await r.json();
    (j.messages||[]).forEach(m=>{
      const cls=m.includes('[DEBUG]')?'debug':'boot';
      tline(m,cls);
    });
    // update status pill
    const pill=document.getElementById('status-pill');
    if(j.ready){
      pill.textContent='online';
      pill.style.background='var(--accent2)';
      pill.style.color='var(--green)';
    } else {
      pill.textContent='degraded';
      pill.style.background='#3d1515';
      pill.style.color='var(--red)';
    }
  } catch(ex){
    tline('[boot error] '+ex.message,'err');
    document.getElementById('status-pill').textContent='offline';
  } finally {
    setThinking(false);
  }
  tline('','sep');
  tline('Type a command or ask me anything. Use the sidebar or 🔍 Search.','debug');
  tline('','sep');
}

// ── send command ──
document.getElementById('chat-input').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();sendChat();}
});

function sendChat(){
  const inp=document.getElementById('chat-input');
  const text=inp.value.trim();
  if(!text) return;
  inp.value='';
  sendText(text);
}

async function sendText(text){
  // echo prompt + user input like a terminal
  tline('Niblit > '+text,'prompt');
  setThinking(true);
  try {
    const resp=await fetch('/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text})
    });
    const j=await resp.json();
    if(j.error){
      tline('[error] '+j.error,'err');
    } else {
      // debug lines (shown as dim)
      (j.debug_lines||[]).forEach(l=>tline(l,'debug'));
      // main reply
      if(j.reply) tline(j.reply,'response');
      // suggestion
      if(j.suggestion) tline(j.suggestion,'suggestion');
    }
  } catch(ex){
    tline('[network error] '+ex.message,'err');
  } finally {
    setThinking(false);
    document.getElementById('chat-input').focus();
  }
}

// ── status poll ──
async function pollStatus(){
  try {
    const r=await fetch('/ping');
    const j=await r.json();
    const pill=document.getElementById('status-pill');
    const mood=j.personality&&j.personality.mood?' · '+j.personality.mood:'';
    if(j.status==='ok'){
      pill.textContent='online'+mood;
      pill.style.background='var(--accent2)';
      pill.style.color='var(--green)';
    } else {
      pill.textContent=j.status||'degraded';
      pill.style.background='#3d1515';
      pill.style.color='var(--red)';
    }
  } catch(_){
    const pill=document.getElementById('status-pill');
    pill.textContent='offline';
    pill.style.background='#3d1515';
    pill.style.color='var(--red)';
  }
}
setInterval(pollStatus,8000);

// ── start ──
boot();
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
                                "endpoints": ["/api/boot", "/api/commands", "/api/search",
                                              "/api/status", "/api/suggest", "/api/threads",
                                              "/ping", "/chat", "/memory"]})

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

    # ── API: boot messages (mirrors main.py boot()) ─────────
    @app.route("/api/boot", methods=["GET"])
    def api_boot():
        """
        Return the boot messages that main.py prints on startup.
        Triggers lazy NiblitCore init so the web user sees the same
        sequence as running Niblit in a Termux terminal.
        """
        msgs = _get_boot_messages()
        core = get_core()
        return render_response({"messages": msgs, "ready": core is not None})

    # ── API: command suggestions ─────────────────────────────
    @app.route("/api/suggest", methods=["GET"])
    def api_suggest():
        """Return close-match command suggestions like main.py suggest_command()."""
        q = request.args.get("q", "").strip()
        if not q:
            return render_response({"suggestions": []})
        return render_response({"suggestions": suggest_command(q), "query": q})

    # ── API: thread list ────────────────────────────────────
    @app.route("/api/threads", methods=["GET"])
    def api_threads():
        """Return the live thread list — same as the 'threads' command in main.py."""
        return render_response({"threads": _list_threads()})

    # ── API: list commands ───────────────────────────────────
    @app.route("/api/commands", methods=["GET"])
    def api_commands():
        """Return the full command catalogue (used by the sidebar menu)."""
        return render_response({"commands": COMMAND_GROUPS,
                                "count": sum(len(g["commands"]) for g in COMMAND_GROUPS)})

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
            return render_response(
                {"error": "missing query — send ?q=<query> or POST {\"query\":\"...\"}"},
                status=400)
        core = get_core()
        if not core:
            return render_response({"error": "core failed"}, status=500)
        try:
            result = core.handle(f"search {query}")
        except Exception as exc:
            result = f"[error] {exc}"
        return render_response({"query": query, "result": result})

    # ── Chat (mirrors run_shell() from main.py) ─────────────
    @app.route("/chat", methods=["POST"])
    def chat():
        """
        Process user input using the same logic as main.py run_shell():
        direct commands → router-routed commands → core.handle() catch-all
        + suggestion engine.  Returns reply, suggestion, ts, debug_lines.
        """
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
            result = _shell_process(core, text)
        except Exception as exc:
            result = {"reply": f"[error] {exc}", "suggestion": None,
                      "ts": _ts(), "debug_lines": []}
        return render_response(result)

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
