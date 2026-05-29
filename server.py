# server.py — Niblit FastAPI server (lightweight alternative to app.py)
#
# Implements the Niblit Cognitive Runtime Shell — a web-based evolution of
# niblit_dashboard.py.  The dashboard preserves the canonical Niblit identity:
#   • same sidebar COMMANDS model and panel-dispatch logic as niblit_dashboard.py
#   • same five panel types: Search, Chat (main), Terminal, Setup, Expanded
#   • same mode selector concept (API / Local)
#   • live cognitive telemetry in the sidebar footer
#
# New supporting API endpoints mirror app.py's surface so both servers are
# API-compatible with existing clients (Router V2, memory, deployment, providers).

import asyncio
import datetime
import difflib
import json as _json
import logging
import os
import threading

# Load .env file when running locally (e.g. Termux).  On Vercel / Render the
# platform injects env vars directly, so this is a no-op in those environments.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on os.environ

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

try:
    from modules.unified_runtime import get_unified_runtime
except Exception:
    get_unified_runtime = None

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


def _get_unified_runtime():
    if get_unified_runtime is None:
        return None
    try:
        return get_unified_runtime()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# NIBLIT DASHBOARD — sidebar command model
# Canonical source: niblit_dashboard.py COMMANDS list.
# Preserved exactly so web and APK share the same navigation contract.
# ══════════════════════════════════════════════════════════════

SEARCH_PROVIDERS = ["DDGS", "SerpAPI", "GitHub REST", "Qdrant", "MarketData"]

COMMANDS = [
    {"title": "📊 Status",        "key": "status",       "type": "status"},
    {"title": "🧠 Memory",        "key": "memory",       "type": "panel"},
    {"title": "📚 Learn Topic",   "key": "learn_about",  "type": "input",
     "input_label": "Topic:"},
    {"title": "🔍 Search",        "key": "search",       "type": "search"},
    {"title": "🖥\u2009 Terminal", "key": "terminal",    "type": "terminal"},
    {"title": "⚙\u2009 Setup",    "key": "setup",       "type": "setup"},
    {"title": "📁 File Upload",   "key": "file_upload",  "type": "file"},
    {"title": "🔄 Reflect",       "key": "reflect",      "type": "action"},
    {"title": "💡 Self-Idea",     "key": "self-idea",    "type": "action"},
    {"title": "🔬 Self-Research", "key": "self-research","type": "input",
     "input_label": "Topic:"},
]

# Shell commands vocabulary used by the suggestion engine.
_SHELL_COMMANDS = [
    "help", "status", "health", "memory", "time", "metrics", "dump",
    "remember", "learn about", "ideas about", "recall", "knowledge stats",
    "autonomous-learn start", "autonomous-learn stop", "autonomous-learn status",
    "auto-research start", "auto-research stop", "auto-research status",
    "search", "summary", "self-research", "self-idea", "reflect", "auto-reflect",
    "evolve", "evolve start", "evolve stop", "evolve status", "evolve history",
    "generate code", "run code", "validate", "execute file",
    "read file", "write file", "list files", "file environment",
    "study software", "software categories", "my structure", "my threads",
    "my modules", "my commands", "dashboard", "operational flow", "resource usage",
    "slsa-status", "start_slsa", "stop_slsa", "reload", "upgrade",
    "toggle-llm on", "toggle-llm off", "shutdown",
    "run-diagnostics", "run-live-test", "loop-errors",
    "orchestrate audit", "orchestrate self-heal", "orchestrate pipeline",
    "llm-provider list", "llm-provider status",
    "runtime status", "runtime provider", "runtime infer",
    "retrieval status", "retrieval inspect", "retrieval contradictions",
    "retrieval mastery", "retrieval sources", "retrieval gaps",
    "retrieval reflections", "retrieval curriculum", "retrieval lineage",
    "retrieval confidence", "retrieval causality",
]


# ── Small runtime helpers ──────────────────────────────────────────────────────

def _ts() -> str:
    """Return a UTC timestamp string matching the NiblitIO format."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("[%Y-%m-%d %H:%M:%S]")


def _list_threads() -> str:
    """Return the live thread list as a newline-separated string."""
    return "\n".join(
        f"{t.name} | alive={t.is_alive()}"
        for t in threading.enumerate()
    )


_boot_messages: list = []
_boot_lock = threading.Lock()


def _get_boot_messages() -> list:
    """Return boot messages, generating them on the first call."""
    global _boot_messages  # pylint: disable=global-statement
    with _boot_lock:
        if _boot_messages:
            return list(_boot_messages)
        msgs = [f"{_ts()} TRUE AUTONOMOUS NIBLIT BOOT"]
        core = get_core()
        if core:
            msgs.append(f"{_ts()} CORE READY")
            msgs.append(f"{_ts()} [DEBUG] Threads: {len(threading.enumerate())}")
            msgs.append(f"{_ts()} READY")
        else:
            msgs.append(f"{_ts()} [WARN] NiblitCore unavailable — degraded mode")
            msgs.append(f"{_ts()} READY (degraded)")
        _boot_messages = msgs
        return list(msgs)


def _suggest_command(user_input: str) -> list:
    """Return close-match command suggestions."""
    matches = difflib.get_close_matches(user_input, _SHELL_COMMANDS, n=3, cutoff=0.5)
    return [m for m in matches if m != user_input]


# ══════════════════════════════════════════════════════════════
# NIBLIT COGNITIVE RUNTIME SHELL — dashboard HTML
#
# This is the web evolution of niblit_dashboard.py.  The layout mirrors
# the APK dashboard architecture exactly:
#
#   Topbar:  brand + mode selector (API / Local) + runtime status
#   Sidebar: same COMMANDS list → same panel types (status / panel /
#            input / search / terminal / setup / file / action)
#            + live telemetry footer (threads, facts, ALE, mode)
#   Main:    ExpandedPanel (status/memory results, collapsible)
#            SearchPanel (collapsible, same SEARCH_PROVIDERS)
#            ChatPanel   (main interaction area — always visible)
#            TerminalPanel (collapsible, monospace shell feel)
#            SetupPanel (collapsible, system info)
#            InputOverlay (for "input"-type commands — mirrors InputBubble)
#            InputBar
#
# __JSON_COMMANDS__ and __JSON_PROVIDERS__ are replaced at render time.
# ══════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Niblit AIOS — Cognitive Runtime</title>
  <style>
    /* ── Niblit Cognitive Runtime design tokens ── */
    :root {
      --bg:#0c0e14; --surface:#0f1219; --surface2:#141820; --surface3:#1a2030;
      --border:#1c2135; --border2:#28304a;
      --primary:#4df6c4; --primary-dim:rgba(77,246,196,.10);
      --primary-glow:rgba(77,246,196,.25);
      --secondary:#7ab5ff; --accent:#ffc14d; --danger:#ff5f6d; --warn:#f0a030;
      --text:#c5d5e8; --text-muted:#4d6075; --text-dim:#273040;
      --term-green:#00ef9b; --term-bg:#050709;
      --code-text:#a8bfcf; --code-bg:#080b10;
      --sidebar-w:220px; --topbar-h:50px;
      --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
      --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
      --radius:6px;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html,body{height:100%;background:var(--bg);color:var(--text);
              font-family:var(--font);font-size:13px;line-height:1.5}
    ::-webkit-scrollbar{width:4px;height:4px}
    ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

    /* ══ TOPBAR ══ */
    #topbar{
      position:fixed;top:0;left:0;right:0;height:var(--topbar-h);z-index:200;
      background:rgba(12,14,20,.96);backdrop-filter:blur(8px);
      border-bottom:1px solid var(--border);
      display:flex;align-items:center;padding:0 12px;gap:10px;
    }
    #menu-btn{background:none;border:none;color:var(--text-muted);cursor:pointer;
              font-size:16px;padding:5px 7px;border-radius:4px;line-height:1}
    #menu-btn:hover{background:var(--surface2);color:var(--text)}
    .brand{display:flex;align-items:center;gap:8px;flex-shrink:0}
    .brand-logo{
      width:28px;height:28px;border-radius:6px;flex-shrink:0;
      background:linear-gradient(135deg,#0f3a2e,#0d3a60);
      display:flex;align-items:center;justify-content:center;
      color:var(--primary);font-weight:800;font-size:13px;
      border:1px solid var(--primary-dim);
      box-shadow:0 0 8px rgba(77,246,196,.15);
    }
    .brand-name{font-size:14px;font-weight:700;color:var(--text);letter-spacing:-.3px}
    .brand-tag{font-size:10px;color:var(--text-muted);background:var(--surface2);
               padding:1px 5px;border-radius:8px;border:1px solid var(--border)}
    #mode-row{display:flex;align-items:center;gap:5px;margin-left:auto}
    #mode-label{font-size:10px;color:var(--text-muted)}
    #mode-select{background:var(--surface2);border:1px solid var(--border);
                 color:var(--text);padding:3px 6px;border-radius:4px;
                 font-size:11px;font-family:var(--mono)}
    #topbar-right{display:flex;align-items:center;gap:8px;margin-left:12px}
    #runtime-status{
      display:flex;align-items:center;gap:5px;padding:4px 10px;
      border-radius:14px;font-size:11px;font-weight:600;
      background:rgba(77,246,196,.08);color:var(--primary);
      border:1px solid rgba(77,246,196,.18);
    }
    #status-dot{width:6px;height:6px;border-radius:50%;background:var(--primary);
                box-shadow:0 0 5px var(--primary);animation:pulse 2s infinite}
    @keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}
    #runtime-status.offline{background:rgba(255,95,109,.08);color:var(--danger);
                             border-color:rgba(255,95,109,.18)}
    #runtime-status.offline #status-dot{background:var(--danger);
                                        box-shadow:0 0 5px var(--danger);animation:none}
    #runtime-status.degraded{background:rgba(240,160,48,.08);color:var(--warn);
                              border-color:rgba(240,160,48,.18)}
    #runtime-status.degraded #status-dot{background:var(--warn);
                                         box-shadow:0 0 5px var(--warn)}
    .hdr-btn{background:var(--surface2);border:1px solid var(--border);
             color:var(--text-muted);padding:4px 10px;border-radius:5px;
             cursor:pointer;font-size:11px;transition:all .15s}
    .hdr-btn:hover{border-color:var(--primary);color:var(--primary);
                   background:var(--primary-dim)}

    /* ══ LAYOUT ══ */
    #layout{display:flex;height:100vh;padding-top:var(--topbar-h)}

    /* ══ SIDEBAR ══ */
    #sidebar{
      width:var(--sidebar-w);background:var(--surface);
      border-right:1px solid var(--border);
      display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;
      transition:width .2s cubic-bezier(.4,0,.2,1);
    }
    #sidebar.collapsed{width:0}
    #sidebar-inner{
      width:var(--sidebar-w);overflow-y:auto;
      flex:1;padding-bottom:4px;
    }
    .sb-section{padding:8px 10px 2px;font-size:9px;font-weight:700;
                letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted)}
    .sb-btn{
      width:100%;background:none;border:none;
      display:flex;align-items:center;gap:8px;
      padding:7px 12px;cursor:pointer;color:var(--text-muted);text-align:left;
      font-size:12px;font-family:var(--font);
      border-left:2px solid transparent;
      transition:background .1s,color .1s,border-color .1s;
    }
    .sb-btn:hover{background:var(--surface2);color:var(--text)}
    .sb-btn.active{color:var(--primary);border-left-color:var(--primary);
                   background:var(--primary-dim)}
    .sb-icon{width:18px;text-align:center;font-size:14px;flex-shrink:0}
    .sb-divider{border:none;border-top:1px solid var(--border);margin:4px 0}

    /* Sidebar telemetry footer (mirrors niblit_dashboard.py status footer) */
    #sb-tel{
      padding:8px 12px 10px;border-top:1px solid var(--border);
      background:var(--surface);flex-shrink:0;
    }
    .tel-row{display:flex;justify-content:space-between;margin-bottom:3px}
    .tel-k{font-size:10px;color:var(--text-muted);font-family:var(--mono)}
    .tel-v{font-size:10px;color:var(--primary);font-family:var(--mono)}
    .tel-v.off{color:var(--text-dim)}

    /* ══ MAIN ══ */
    #main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}

    /* Collapsible panels */
    .cpanel{overflow:hidden;transition:max-height .22s cubic-bezier(.4,0,.2,1)}
    .cpanel.hidden{max-height:0!important}
    .ph{
      display:flex;align-items:center;gap:8px;padding:7px 12px;
      background:var(--surface);cursor:pointer;
      font-size:11px;font-weight:600;color:var(--text-muted);
      border-bottom:1px solid var(--border);
      border-left:2px solid var(--border2);
    }
    .ph:hover{background:var(--surface2);color:var(--text)}
    .ph.on{border-left-color:var(--primary);color:var(--primary)}
    .ph-title{flex:1}
    .ph-close{background:none;border:none;color:var(--text-muted);
              cursor:pointer;font-size:12px;padding:0 2px;line-height:1}
    .ph-close:hover{color:var(--danger)}
    .pb{padding:10px 12px;background:var(--surface)}

    /* ── EXPANDED PANEL (status / memory results) ── */
    #xpanel{max-height:190px}
    #xpanel-content{
      font-family:var(--mono);font-size:11px;color:var(--code-text);
      background:var(--code-bg);padding:8px 10px;border-radius:var(--radius);
      white-space:pre-wrap;max-height:120px;overflow-y:auto;
      border:1px solid var(--border);
    }

    /* ── SEARCH PANEL ── */
    #spanel{max-height:52px}
    #sbar{display:flex;gap:6px;align-items:center}
    #sinput{
      flex:1;background:var(--surface2);border:1px solid var(--border);
      border-radius:4px;padding:5px 8px;font-size:12px;font-family:var(--font);
      color:var(--text);outline:none;
    }
    #sinput:focus{border-color:var(--primary)}
    #sprovider{
      background:var(--surface2);border:1px solid var(--border);
      color:var(--text);padding:4px 6px;border-radius:4px;
      font-size:11px;font-family:var(--mono);
    }
    .sgo{background:var(--surface2);border:1px solid var(--border);
         color:var(--text-muted);padding:4px 8px;border-radius:4px;
         cursor:pointer;font-size:11px}
    .sgo:hover{border-color:var(--primary);color:var(--primary)}

    /* ── CHAT PANEL ── */
    #cpan{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0}
    #cmsg{flex:1;overflow-y:auto;padding:10px 0}
    .mrow{display:flex;gap:8px;padding:3px 12px;max-width:800px;width:100%}
    .mrow.u{flex-direction:row-reverse;margin-left:auto;margin-right:0}
    .mav{width:26px;height:26px;border-radius:50%;flex-shrink:0;font-size:11px;
         font-weight:700;display:flex;align-items:center;justify-content:center}
    .mav.ai{background:linear-gradient(135deg,#0f3a2e,#0d3a60);
            color:var(--primary);border:1px solid rgba(77,246,196,.25)}
    .mav.usr{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
    .mc{flex:1;min-width:0}
    .mm{font-size:10px;color:var(--text-muted);margin-bottom:2px;
        display:flex;gap:5px}
    .mrow.u .mm{justify-content:flex-end}
    .mb{background:var(--surface2);border:1px solid var(--border);
        border-radius:var(--radius);padding:7px 10px;
        font-size:12.5px;line-height:1.55;color:var(--text)}
    .mrow.u .mb{background:var(--primary-dim);border-color:rgba(77,246,196,.18)}
    .mb code{background:var(--code-bg);color:var(--code-text);padding:1px 4px;
             border-radius:3px;font-family:var(--mono);font-size:11px}
    .mb pre{background:var(--code-bg);color:var(--code-text);padding:8px 10px;
            border-radius:4px;margin:5px 0;overflow-x:auto;
            font-family:var(--mono);font-size:11px;line-height:1.6;
            border:1px solid var(--border)}
    .msugg{font-size:11px;color:var(--secondary);margin-top:3px;font-style:italic}
    /* Boot block */
    #boot-blk{
      background:var(--term-bg);border:1px solid var(--border);
      border-radius:var(--radius);padding:8px 10px;margin:6px 12px;
      font-family:var(--mono);font-size:11px;line-height:1.8;
      border-left:2px solid var(--primary);display:none;
    }
    .bl-ok{color:var(--term-green)}.bl-warn{color:var(--warn)}
    .bl-err{color:var(--danger)}.bl-hdr{color:var(--primary);font-weight:700}
    .bl-dim{color:var(--text-muted)}
    /* Thinking */
    #thinking{display:none;align-items:center;gap:8px;padding:3px 12px}
    .tdots{display:flex;gap:4px}
    .tdots span{width:5px;height:5px;border-radius:50%;background:var(--primary);
                animation:tdot .9s ease-in-out infinite}
    .tdots span:nth-child(2){animation-delay:.2s}
    .tdots span:nth-child(3){animation-delay:.4s}
    @keyframes tdot{0%,100%{transform:translateY(0);opacity:.3}50%{transform:translateY(-4px);opacity:1}}

    /* ── TERMINAL PANEL ── */
    #tpanel{max-height:210px}
    #tout{
      background:var(--term-bg);color:var(--term-green);font-family:var(--mono);
      font-size:11px;padding:7px 9px;height:110px;overflow-y:auto;
      border-radius:4px;white-space:pre-wrap;border:1px solid var(--border);
    }
    #tinrow{display:flex;gap:5px;margin-top:5px}
    #tinput{
      flex:1;background:var(--term-bg);border:1px solid var(--border);
      border-radius:4px;padding:4px 7px;font-size:11px;font-family:var(--mono);
      color:var(--term-green);outline:none;
    }
    #tinput:focus{border-color:var(--term-green)}
    .tbtn{background:var(--surface2);border:1px solid var(--border);
          color:var(--text-muted);padding:4px 7px;border-radius:4px;
          cursor:pointer;font-size:11px;font-family:var(--mono)}
    .tbtn:hover{border-color:var(--term-green);color:var(--term-green)}

    /* ── SETUP PANEL ── */
    #setupanel{max-height:180px}
    #setup-content{font-family:var(--mono);font-size:11px;color:var(--code-text);
                   background:var(--code-bg);padding:8px 10px;
                   border-radius:4px;white-space:pre-wrap;max-height:110px;
                   overflow-y:auto;border:1px solid var(--border)}

    /* ── INPUT OVERLAY (mirrors niblit_dashboard.py InputBubble) ── */
    #ioverlay{
      display:none;padding:6px 12px;background:var(--surface2);
      border-top:1px solid var(--border);align-items:center;gap:7px;
    }
    #ioverlay.show{display:flex}
    #ilabel{font-size:11px;color:var(--text-muted);min-width:55px;flex-shrink:0}
    #iinput{
      flex:1;background:var(--surface);border:1px solid var(--border);
      border-radius:4px;padding:5px 7px;font-size:12px;font-family:var(--font);
      color:var(--text);outline:none;
    }
    #iinput:focus{border-color:var(--primary)}
    .iobtn{background:none;border:1px solid var(--border);color:var(--text-muted);
           padding:3px 7px;border-radius:4px;cursor:pointer;font-size:11px}
    .iobtn:hover{border-color:var(--primary);color:var(--primary)}

    /* ── INPUT BAR ── */
    #ibar{
      background:var(--surface);border-top:1px solid var(--border);
      padding:9px 12px 11px;display:flex;gap:7px;align-items:flex-end;
    }
    #cinput{
      flex:1;background:var(--surface2);border:1.5px solid var(--border);
      border-radius:var(--radius);padding:7px 10px;font-size:13px;
      font-family:var(--font);color:var(--text);outline:none;
      resize:none;min-height:38px;max-height:110px;line-height:1.5;
    }
    #cinput:focus{border-color:var(--primary)}
    #cinput::placeholder{color:var(--text-muted)}
    #sendbtn{
      background:linear-gradient(135deg,#0f3a2e,#0a2e48);color:var(--primary);
      border:1px solid rgba(77,246,196,.28);border-radius:var(--radius);
      padding:7px 16px;cursor:pointer;font-size:13px;font-weight:600;
      min-height:38px;transition:all .15s;
    }
    #sendbtn:hover:not(:disabled){box-shadow:0 0 10px rgba(77,246,196,.25);
                                   border-color:var(--primary)}
    #sendbtn:disabled{opacity:.35;cursor:not-allowed}

    /* ══ MOBILE ══ */
    @media(max-width:600px){
      :root{--sidebar-w:200px}
      #sidebar{position:fixed;top:var(--topbar-h);left:0;bottom:0;
               z-index:150;width:0!important}
      #sidebar.mob-open{width:var(--sidebar-w)!important}
    }
  </style>
</head>
<body>

<!-- ══ TOPBAR ══ -->
<header id="topbar">
  <button id="menu-btn" onclick="toggleSidebar()" title="Toggle sidebar">☰</button>
  <div class="brand">
    <div class="brand-logo">N</div>
    <span class="brand-name">Niblit AIOS</span>
    <span class="brand-tag">Cognitive Runtime</span>
  </div>
  <div id="mode-row">
    <span id="mode-label">Mode:</span>
    <select id="mode-select" onchange="onModeChange(this.value)">
      <option value="api">🌐 API</option>
      <option value="local">🖥 Local</option>
    </select>
  </div>
  <div id="topbar-right">
    <div id="runtime-status">
      <span id="status-dot"></span>
      <span id="status-txt">booting…</span>
    </div>
    <button class="hdr-btn" onclick="sendText('help')">? Help</button>
  </div>
</header>

<!-- ══ LAYOUT ══ -->
<div id="layout">

  <!-- ══ SIDEBAR ══ -->
  <!-- Mirrors niblit_dashboard.py SideBarPanel + COMMANDS list -->
  <nav id="sidebar">
    <div id="sidebar-inner">
      <div class="sb-section">Panels</div>
      <!-- populated by buildSidebar() from __JSON_COMMANDS__ -->
    </div>
    <!-- Telemetry footer: mirrors niblit_dashboard.py status polling -->
    <div id="sb-tel">
      <div class="tel-row">
        <span class="tel-k">threads</span>
        <span class="tel-v" id="tel-threads">—</span>
      </div>
      <div class="tel-row">
        <span class="tel-k">facts</span>
        <span class="tel-v" id="tel-facts">—</span>
      </div>
      <div class="tel-row">
        <span class="tel-k">ale</span>
        <span class="tel-v" id="tel-ale">—</span>
      </div>
      <div class="tel-row">
        <span class="tel-k">mode</span>
        <span class="tel-v" id="tel-mode">api</span>
      </div>
    </div>
  </nav>

  <!-- ══ MAIN AREA ══ -->
  <div id="main">

    <!-- ExpandedPanel: shows status/memory results (mirrors niblit_dashboard.py) -->
    <div class="cpanel hidden" id="xpanel">
      <div class="ph on">
        <span class="sb-icon" id="xpanel-icon">📊</span>
        <span class="ph-title" id="xpanel-title">Status</span>
        <button class="ph-close" onclick="hidePanel('xpanel')">✕</button>
      </div>
      <div class="pb">
        <div id="xpanel-content">Loading…</div>
      </div>
    </div>

    <!-- SearchPanel: mirrors niblit_dashboard.py SearchPanel -->
    <div class="cpanel hidden" id="spanel">
      <div class="ph on">
        <span class="sb-icon">🔍</span>
        <span class="ph-title">Search</span>
        <button class="ph-close" onclick="hidePanel('spanel')">✕</button>
      </div>
      <div class="pb" style="padding:6px 10px">
        <div id="sbar">
          <input id="sinput" type="text" placeholder="Search query…"
                 autocomplete="off"
                 onkeydown="if(event.key==='Enter')doSearch()"/>
          <select id="sprovider"><!-- populated by buildProviders() --></select>
          <button class="sgo" onclick="doSearch()">Go</button>
        </div>
      </div>
    </div>

    <!-- ChatPanel: main interaction area (always visible) -->
    <div id="cpan">
      <div id="boot-blk"></div>
      <div id="cmsg">
        <div class="mrow">
          <div class="mav ai">N</div>
          <div class="mc">
            <div class="mm">
              <span>Niblit AIOS</span>
              <span id="boot-ts"></span>
            </div>
            <div class="mb">
              ▶ Niblit Cognitive Runtime — ready.<br/>
              <span style="color:var(--text-muted);font-size:11px">
                Use the sidebar to navigate panels · type any command below
              </span>
            </div>
          </div>
        </div>
      </div>
      <div id="thinking">
        <div class="mav ai">N</div>
        <div class="tdots"><span></span><span></span><span></span></div>
      </div>
    </div>

    <!-- TerminalPanel: mirrors niblit_dashboard.py TerminalPanel -->
    <div class="cpanel hidden" id="tpanel">
      <div class="ph on">
        <span class="sb-icon">🖥</span>
        <span class="ph-title">Terminal</span>
        <button class="ph-close" onclick="hidePanel('tpanel')">✕</button>
      </div>
      <div class="pb">
        <div id="tout">$ Niblit shell ready&#10;</div>
        <div id="tinrow">
          <input id="tinput" type="text" placeholder="Enter command…"
                 onkeydown="if(event.key==='Enter')runTermCmd()"/>
          <button class="tbtn" onclick="runTermCmd()">Run</button>
          <button class="tbtn"
                  onclick="document.getElementById('tout').textContent='$ '">
            Clr
          </button>
        </div>
      </div>
    </div>

    <!-- SetupPanel: mirrors niblit_dashboard.py SetupPanel -->
    <div class="cpanel hidden" id="setupanel">
      <div class="ph on">
        <span class="sb-icon">⚙</span>
        <span class="ph-title">Setup / System Info</span>
        <button class="ph-close" onclick="hidePanel('setupanel')">✕</button>
      </div>
      <div class="pb">
        <div id="setup-content">Loading system info…</div>
      </div>
    </div>

    <!-- InputOverlay: mirrors niblit_dashboard.py InputBubble -->
    <div id="ioverlay">
      <span id="ilabel">Input:</span>
      <input id="iinput" type="text" autocomplete="off"
             onkeydown="if(event.key==='Enter')submitOverlay();
                        if(event.key==='Escape')hideOverlay()"/>
      <button class="iobtn" onclick="submitOverlay()">OK</button>
      <button class="iobtn" onclick="hideOverlay()">✕</button>
    </div>

    <!-- Input bar -->
    <div id="ibar">
      <textarea id="cinput" rows="1"
                placeholder="Type a command (status, search, reflect…) or ask anything…"
                autocomplete="off" spellcheck="false"></textarea>
      <button id="sendbtn" onclick="sendChat()">Send ↵</button>
    </div>

  </div><!-- /main -->
</div><!-- /layout -->

<script>
'use strict';
// ════════════════════════════════════════════
// DATA — injected from Python at render time
// ════════════════════════════════════════════
const COMMANDS  = __JSON_COMMANDS__;
const PROVIDERS = __JSON_PROVIDERS__;
let _mode = 'api';
let _oCmd = '', _oLabel = '';

// ════════════════════════════════════════════
// SIDEBAR — mirrors niblit_dashboard.py SideBarPanel
// ════════════════════════════════════════════
(function buildSidebar(){
  const inner = document.getElementById('sidebar-inner');
  COMMANDS.forEach(c => {
    const btn = document.createElement('button');
    btn.className = 'sb-btn';
    btn.id = 'sb-' + c.key;
    btn.innerHTML = `<span class="sb-icon">${c.title.split(' ')[0]}</span>`
                  + `<span>${c.title.replace(/^[^\s]+\s*/,'')}</span>`;
    btn.onclick = () => handleCommand(c.key, c.type, c.input_label);
    inner.appendChild(btn);
  });
})();

(function buildProviders(){
  const sel = document.getElementById('sprovider');
  PROVIDERS.forEach(p => {
    const o = document.createElement('option');
    o.textContent = p;
    sel.appendChild(o);
  });
})();

// ════════════════════════════════════════════
// PANEL SYSTEM
// ════════════════════════════════════════════
function showPanel(id){ const p=document.getElementById(id); if(p)p.classList.remove('hidden'); }
function hidePanel(id){ const p=document.getElementById(id); if(p)p.classList.add('hidden'); }

function clearActiveSb(){
  document.querySelectorAll('.sb-btn').forEach(b=>b.classList.remove('active'));
}

// ════════════════════════════════════════════
// COMMAND DISPATCH — mirrors niblit_dashboard.py handle_command()
// ════════════════════════════════════════════
function handleCommand(key, type, inputLabel){
  clearActiveSb();
  const sb = document.getElementById('sb-'+key);
  if(sb) sb.classList.add('active');

  if(type === 'status'){
    fetchXPanel('status','📊','System Status');
  } else if(type === 'panel'){
    fetchXPanel('memory','🧠','Memory');
  } else if(type === 'search'){
    showPanel('spanel');
    setTimeout(()=>document.getElementById('sinput').focus(), 50);
  } else if(type === 'terminal'){
    showPanel('tpanel');
    setTimeout(()=>document.getElementById('tinput').focus(), 50);
  } else if(type === 'setup'){
    fetchSetup();
  } else if(type === 'file'){
    sendText('file environment');
  } else if(type === 'action'){
    sendText(key);
  } else if(type === 'input'){
    showInputOverlay(key, inputLabel || 'Input:');
  }
}

// ════════════════════════════════════════════
// EXPANDED PANEL — mirrors niblit_dashboard.py _expand_sidebar_panel
// ════════════════════════════════════════════
async function fetchXPanel(what, icon, title){
  showPanel('xpanel');
  document.getElementById('xpanel-icon').textContent  = icon;
  document.getElementById('xpanel-title').textContent = title;
  document.getElementById('xpanel-content').textContent = 'Loading…';
  try {
    let txt = '';
    if(what === 'status'){
      const r = await fetch('/api/status');
      if(r.ok){
        const j = await r.json();
        txt += `online:  ${j.online ? '✅ yes' : '❌ no'}\n`;
        if(j.threads  !== undefined) txt += `threads: ${j.threads}\n`;
        if(j.facts_count !== undefined) txt += `facts:   ${j.facts_count}\n`;
        if(j.personality) txt += `mood:    ${j.personality.mood||'—'}\n`;
      }
    } else {
      const r = await fetch('/memory');
      if(r.ok){
        const j = await r.json();
        txt = (j.facts||[]).slice(0,12)
               .map(f=>`${String(f.key||'').slice(0,32).padEnd(32)} ${String(f.value||'').slice(0,60)}`)
               .join('\n') || '[No facts stored]';
      }
    }
    document.getElementById('xpanel-content').textContent = txt || '[No data]';
  } catch(e){
    document.getElementById('xpanel-content').textContent = `[Error: ${e.message}]`;
  }
}

// ════════════════════════════════════════════
// SETUP PANEL — mirrors niblit_dashboard.py SetupPanel
// ════════════════════════════════════════════
async function fetchSetup(){
  showPanel('setupanel');
  document.getElementById('setup-content').textContent = 'Loading…';
  try {
    const r = await fetch('/api/status');
    if(!r.ok) throw new Error('status unavailable');
    const j = await r.json();
    let txt = `service:  niblit\n`;
    txt += `online:   ${j.online ? 'yes' : 'no'}\n`;
    txt += `threads:  ${j.threads||'—'}\n`;
    if(j.facts_count !== undefined) txt += `facts:    ${j.facts_count}\n`;
    if(j.personality){
      txt += `mood:     ${j.personality.mood||'—'}\n`;
      txt += `tone:     ${j.personality.tone||'—'}\n`;
    }
    document.getElementById('setup-content').textContent = txt;
  } catch(e){
    document.getElementById('setup-content').textContent = `[Setup info unavailable: ${e.message}]`;
  }
}

// ════════════════════════════════════════════
// SEARCH — mirrors niblit_dashboard.py SearchPanel
// ════════════════════════════════════════════
function doSearch(){
  const q = document.getElementById('sinput').value.trim();
  if(!q) return;
  document.getElementById('sinput').value = '';
  hidePanel('spanel');
  const prov = document.getElementById('sprovider').value;
  const cmd  = prov === 'DDGS' ? 'search ' : `search ${prov.toLowerCase()} `;
  sendText(cmd + q);
}

// ════════════════════════════════════════════
// TERMINAL — mirrors niblit_dashboard.py TerminalPanel
// ════════════════════════════════════════════
function runTermCmd(){
  const ti = document.getElementById('tinput');
  const cmd = ti.value.trim();
  if(!cmd) return;
  ti.value = '';
  const tout = document.getElementById('tout');
  tout.textContent += `$ ${cmd}\n`;
  tout.scrollTop = tout.scrollHeight;
  sendText(cmd).then(reply => {
    if(reply){ tout.textContent += reply + '\n'; tout.scrollTop = tout.scrollHeight; }
  });
}

// ════════════════════════════════════════════
// INPUT OVERLAY — mirrors niblit_dashboard.py InputBubble
// ════════════════════════════════════════════
function showInputOverlay(cmdKey, label){
  _oCmd = cmdKey; _oLabel = label;
  document.getElementById('ilabel').textContent = label;
  document.getElementById('iinput').value = '';
  document.getElementById('ioverlay').classList.add('show');
  setTimeout(()=>document.getElementById('iinput').focus(), 50);
}
function hideOverlay(){
  document.getElementById('ioverlay').classList.remove('show');
  _oCmd = '';
}
function submitOverlay(){
  const text = document.getElementById('iinput').value.trim();
  if(!text) return;
  hideOverlay();
  const MAP = { learn_about:'learn about', 'self-research':'self-research' };
  sendText((MAP[_oCmd]||_oCmd) + ' ' + text);
}

// ════════════════════════════════════════════
// CHAT
// ════════════════════════════════════════════
function esc(t){ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtTime(){ return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); }
function renderMd(t){
  let s = esc(t);
  s = s.replace(/```([^`]*?)```/gs, (_,c) => `<pre><code>${c}</code></pre>`);
  s = s.replace(/`([^`\n]+?)`/g, (_,c) => `<code>${c}</code>`);
  return s;
}

function addMsg(who, text, suggestion){
  const isUser = who === 'user';
  const msgs = document.getElementById('cmsg');
  const row = document.createElement('div');
  row.className = 'mrow' + (isUser ? ' u' : '');
  const av  = document.createElement('div');
  av.className = 'mav ' + (isUser ? 'usr' : 'ai');
  av.textContent = isUser ? '👤' : 'N';
  const mc  = document.createElement('div'); mc.className = 'mc';
  const mm  = document.createElement('div'); mm.className = 'mm';
  mm.innerHTML = `<span>${isUser?'You':'Niblit'}</span><span>${fmtTime()}</span>`;
  const mb  = document.createElement('div'); mb.className = 'mb';
  mb.innerHTML = isUser ? esc(text) : renderMd(text);
  mc.appendChild(mm); mc.appendChild(mb);
  if(suggestion){ const s=document.createElement('div'); s.className='msugg'; s.textContent=suggestion; mc.appendChild(s); }
  if(isUser){ row.appendChild(mc); row.appendChild(av); }
  else       { row.appendChild(av);  row.appendChild(mc); }
  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
}

function setThinking(on){
  document.getElementById('thinking').style.display = on ? 'flex' : 'none';
  document.getElementById('sendbtn').disabled = on;
}
function setStatus(txt, state){
  document.getElementById('status-txt').textContent = txt;
  const el = document.getElementById('runtime-status');
  el.className = state || ''; el.id = 'runtime-status';
}

async function sendText(text){
  addMsg('user', text);
  setThinking(true);
  try {
    const resp = await fetch('/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text})
    });
    const j = await resp.json();
    if(j.error) addMsg('ai','[error] '+j.error);
    else        addMsg('ai', j.reply||'[no reply]', j.suggestion);
    return j.reply || '';
  } catch(e){
    addMsg('ai','[Network error: '+e.message+']');
    return '';
  } finally {
    setThinking(false);
    document.getElementById('cinput').focus({preventScroll:true});
  }
}

function sendChat(){
  const inp = document.getElementById('cinput');
  const text = inp.value.trim();
  if(!text) return;
  inp.value = ''; inp.style.height = 'auto';
  sendText(text);
}

const cinput = document.getElementById('cinput');
cinput.addEventListener('input',function(){ this.style.height='auto'; this.style.height=Math.min(this.scrollHeight,110)+'px'; });
cinput.addEventListener('keydown',function(e){ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();} });

// ════════════════════════════════════════════
// RUNTIME MODE — mirrors niblit_dashboard.py mode_spinner
// ════════════════════════════════════════════
function onModeChange(mode){
  _mode = mode;
  document.getElementById('tel-mode').textContent = mode;
}

// ════════════════════════════════════════════
// BOOT SEQUENCE
// ════════════════════════════════════════════
async function runBoot(){
  setStatus('booting…','');
  document.getElementById('boot-ts').textContent = fmtTime();
  const blk = document.getElementById('boot-blk');
  blk.style.display = 'block';
  blk.innerHTML = '<span class="bl-hdr">▶ Niblit AIOS — Cognitive Runtime Boot</span>\n';
  setThinking(true);
  try {
    const r = await fetch('/api/boot');
    const j = await r.json();
    (j.messages||[]).forEach(m => {
      const cls = m.includes('[WARN]')?'bl-warn':m.includes('[ERR]')?'bl-err':m.includes('[DEBUG]')?'bl-dim':'bl-ok';
      blk.innerHTML += `<span class="${cls}">${esc(m)}</span>\n`;
    });
    setStatus(j.ready?'online':'degraded', j.ready?'':'degraded');
  } catch(e){
    blk.innerHTML += `<span class="bl-err">[boot error] ${esc(e.message)}</span>\n`;
    setStatus('offline','offline');
  } finally {
    setThinking(false);
    document.getElementById('cinput').focus();
  }
}

// ════════════════════════════════════════════
// LIVE TELEMETRY — mirrors niblit_dashboard.py status polling
// ════════════════════════════════════════════
async function refreshTelemetry(){
  try {
    const r = await fetch('/api/bg_status');
    if(!r.ok) return;
    const j = await r.json();
    document.getElementById('tel-threads').textContent = j.threads || '—';
    if(j.ale){
      const a = j.ale;
      document.getElementById('tel-ale').textContent = a.running?`▶ #${a.cycle}`:'■ stopped';
      document.getElementById('tel-ale').className   = 'tel-v' + (a.running?'':' off');
    }
    const sr = await fetch('/api/status');
    if(sr.ok){
      const sj = await sr.json();
      if(sj.facts_count !== undefined)
        document.getElementById('tel-facts').textContent = sj.facts_count + ' facts';
    }
  } catch(_){}
}
setInterval(refreshTelemetry, 15000);
setTimeout(refreshTelemetry, 3000);

// Status pill poll
async function pollStatus(){
  try {
    const r = await fetch('/ping');
    const j = await r.json();
    setStatus(j.status==='ok'?'online':'degraded', j.status==='ok'?'':'degraded');
  } catch(_){ setStatus('offline','offline'); }
}
setInterval(pollStatus, 12000);

// ════════════════════════════════════════════
// UNIFIED RUNTIME STREAM (WebSocket)
// ════════════════════════════════════════════
let rtSocket = null;
let rtRetryTimer = null;
function _runtimeWsUrl(){
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws/runtime`;
}
function startRuntimeSocket(){
  try{
    if(rtSocket && (rtSocket.readyState===WebSocket.OPEN || rtSocket.readyState===WebSocket.CONNECTING)) return;
    rtSocket = new WebSocket(_runtimeWsUrl());
    rtSocket.onmessage = (ev) => {
      let msg = null;
      try{ msg = JSON.parse(ev.data); } catch(_){ return; }
      if(!msg || msg.stream_format!=='niblit.runtime.stream.v1') return;
      const st = msg.state || {};
      const tel = msg.telemetry || {};
      if(st.active_provider){
        document.getElementById('tel-mode').textContent = st.runtime_mode || document.getElementById('tel-mode').textContent;
      }
      if(tel.threads !== undefined) document.getElementById('tel-threads').textContent = tel.threads;
      if(tel.facts_count !== undefined && tel.facts_count !== null) document.getElementById('tel-facts').textContent = tel.facts_count + ' facts';
      if(tel.ale){
        const a = tel.ale;
        document.getElementById('tel-ale').textContent = a.running ? `▶ #${a.cycle}` : '■ stopped';
        document.getElementById('tel-ale').className = 'tel-v' + (a.running ? '' : ' off');
      }
      if(st.active_provider){
        const s = document.getElementById('status-txt');
        if(s && s.textContent && s.textContent.startsWith('online')){
          s.textContent = `online · ${st.active_provider}`;
        }
      }
    };
    rtSocket.onclose = () => {
      if(rtRetryTimer) clearTimeout(rtRetryTimer);
      rtRetryTimer = setTimeout(startRuntimeSocket, 2000);
    };
    rtSocket.onerror = () => {
      try{ rtSocket.close(); }catch(_){}
    };
  } catch(_){}
}

runBoot();
startRuntimeSocket();
</script>
</body>
</html>
"""


def _build_dashboard() -> str:
    """Inject COMMANDS and SEARCH_PROVIDERS into the dashboard HTML template."""
    def _json_for_script(value) -> str:
        # Escape characters that can break out of <script> context.
        return (
            _json.dumps(value, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )

    return (
        DASHBOARD_HTML
        .replace("__JSON_COMMANDS__", _json_for_script(COMMANDS))
        .replace("__JSON_PROVIDERS__", _json_for_script(SEARCH_PROVIDERS))
    )


class ChatBody(BaseModel):
    text: str = ""


@app.get("/")
def dashboard():
    return HTMLResponse(_build_dashboard())


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
    runtime = _get_unified_runtime()
    try:
        if runtime is not None:
            reply = runtime.dispatch_command(command=text, core=n)
        else:
            reply = n.handle(text)
    except Exception as exc:
        logging.getLogger("NiblitServer").error("chat error: %s", exc)
        reply = "[error] chat failed — see server logs"
    return {"reply": reply}


@app.get("/memory")
def memory():
    n = get_core()
    if not n:
        return {"facts": []}
    facts = n.db.list_facts(limit=200)
    return {"facts": facts}


# ══════════════════════════════════════════════════════════════
# NEW API ENDPOINTS — support the Cognitive Runtime Shell UI
# Mirror app.py's surface so clients are compatible with both servers.
# ══════════════════════════════════════════════════════════════

@app.get("/api/boot")
def api_boot():
    """Return boot messages (mirrors app.py /api/boot and main.py boot())."""
    msgs = _get_boot_messages()
    core = get_core()
    runtime = _get_unified_runtime()
    if runtime is not None:
        try:
            runtime.boot(core=core)
        except Exception:
            pass
    return JSONResponse({"messages": msgs, "ready": core is not None})


@app.get("/api/commands")
def api_commands():
    """Return the sidebar COMMANDS catalogue (mirrors niblit_dashboard.py COMMANDS)."""
    return JSONResponse({"commands": COMMANDS, "count": len(COMMANDS)})


@app.get("/api/bg_status")
def api_bg_status():
    """Background process telemetry — lightweight, polled every 15 s from UI."""
    core = get_core()
    data: dict = {
        "ts": _ts(),
        "ale": None,
        "threads": len(threading.enumerate()),
    }
    if core:
        ale = getattr(core, "autonomous_engine", None)
        if ale:
            data["ale"] = {
                "running": getattr(ale, "running", False),
                "cycle":   getattr(ale, "_cycle_count", 0),
                "topic":   ale.get_current_topic() if hasattr(ale, "get_current_topic") else None,
            }
    runtime = _get_unified_runtime()
    if runtime is not None:
        try:
            snap = runtime.state(core=core)
            data["runtime"] = {
                "mode": snap["state"].get("runtime_mode", "api"),
                "active_provider": snap["state"].get("active_provider", "qwen"),
            }
        except Exception:
            pass
    return JSONResponse(data)


@app.get("/api/status")
def api_status():
    """Detailed system status (mirrors app.py /api/status)."""
    core = get_core()
    data: dict = {
        "online":  core is not None,
        "service": "niblit",
        "threads": len(threading.enumerate()),
    }
    if core:
        try:
            data["personality"] = core.db.get_personality()
        except Exception:
            pass
        try:
            data["facts_count"] = len(core.db.list_facts(limit=500))
        except Exception:
            pass
    runtime = _get_unified_runtime()
    if runtime is not None:
        try:
            snap = runtime.state(core=core)
            data["runtime"] = {
                "active_provider": snap["state"].get("active_provider", "qwen"),
                "runtime_mode": snap["state"].get("runtime_mode", "api"),
                "deployment": snap["state"].get("deployment", {}),
                "event_counts": snap.get("events", {}).get("event_counts", {}),
            }
        except Exception:
            pass
    return JSONResponse(data)


@app.get("/api/suggest")
def api_suggest(q: str = ""):
    """Close-match command suggestions (mirrors app.py /api/suggest)."""
    q = q.strip()
    if not q:
        return JSONResponse({"suggestions": []})
    return JSONResponse({"suggestions": _suggest_command(q), "query": q})


@app.get("/api/threads")
def api_threads():
    """Return the live thread list (mirrors app.py /api/threads)."""
    return JSONResponse({"threads": _list_threads()})


@app.get("/api/runtime/state")
def api_runtime_state():
    """Unified runtime state envelope for UI/API/runtime interoperability."""
    core = get_core()
    runtime = _get_unified_runtime()
    if runtime is None:
        return JSONResponse(
            {
                "stream_format": "niblit.runtime.stream.v1",
                "type": "runtime.state",
                "state": {"runtime_mode": "api", "active_provider": "qwen"},
                "telemetry": {},
                "events": {},
            }
        )
    return JSONResponse(runtime.state(core=core))


@app.get("/api/runtime/events")
def api_runtime_events(since: int = 0, limit: int = 100):
    """Replay normalized runtime events from the unified runtime event bus."""
    runtime = _get_unified_runtime()
    if runtime is None:
        return JSONResponse({"events": [], "since": since, "limit": limit})
    return JSONResponse({"events": runtime.events(since=since, limit=limit), "since": since, "limit": limit})


@app.get("/api/runtime/episodes")
def api_runtime_episodes(limit: int = 50):
    """Replay cognitive episodes and governed reflection summaries."""
    runtime = _get_unified_runtime()
    if runtime is None:
        return JSONResponse({"episodes": [], "reflections": [], "dataset": {}, "compression": {}})
    state = runtime.state(core=get_core())
    cognition = state.get("cognition", {})
    return JSONResponse(
        {
            "episodes": runtime.episodes(limit=limit),
            "reflections": cognition.get("reflections", []),
            "dataset": cognition.get("datasets", {}),
            "compression": cognition.get("compression", {}),
            "confidence": cognition.get("confidence_summary", {}),
        }
    )


@app.websocket("/ws/runtime")
async def ws_runtime(websocket: WebSocket):
    """Live runtime stream for telemetry + events in canonical stream format."""
    await websocket.accept()
    runtime = _get_unified_runtime()
    if runtime is None:
        await websocket.send_json(
            {
                "stream_format": "niblit.runtime.stream.v1",
                "type": "runtime.warning",
                "message": "Unified runtime unavailable",
            }
        )
        await websocket.close()
        return

    cursor = 0
    try:
        while True:
            frame = runtime.stream_frame(core=get_core(), since=cursor)
            events = frame.get("events", [])
            if events:
                cursor = max(cursor, max(int(e.get("id", 0)) for e in events))
            await websocket.send_json(frame)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json(
                {
                    "stream_format": "niblit.runtime.stream.v1",
                    "type": "runtime.warning",
                    "message": str(exc),
                }
            )
        except Exception:
            pass


def run_server():
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Niblit HTTP server on http://0.0.0.0:{port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port)

if __name__ == "__main__":
    run_server()
