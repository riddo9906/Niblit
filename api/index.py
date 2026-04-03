"""
api/index.py — Complete Vercel Python serverless entry-point for Niblit.

Vercel builds **only** this file (via the explicit ``builds`` entry in
vercel.json).  ``app.py`` is used for local development only and is never
imported here.

This module is intentionally self-contained:

* Every route the Niblit web-frontend expects is defined here.
* Imports that could fail (NiblitCore and its heavy deps) are loaded lazily
  inside ``_get_core()``, so the module always imports cleanly.
* Rate limiting and optional API-key authentication mirror ``app.py``.
* The command catalog (``COMMAND_GROUPS``) is inlined so ``/api/commands``
  works even when NiblitCore is unavailable.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import sys
import threading
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# ── FastAPI application ──────────────────────────────────────────────────────
app = FastAPI(title="Niblit AI", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

log = logging.getLogger("NiblitVercel")

# ── Lazy NiblitCore ──────────────────────────────────────────────────────────
# NiblitCore and its heavy deps are only loaded on the first real request.
# If unavailable (e.g. missing optional packages) the API still boots and
# returns structured error responses instead of a 500.
_core = None
_core_error: Optional[str] = None
_core_loaded = False


def _get_core():
    """Return the singleton NiblitCore, loading it once on first call."""
    global _core, _core_error, _core_loaded
    if _core_loaded:
        return _core
    _core_loaded = True
    # Add the repo root to sys.path so niblit_core is importable.
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from niblit_core import NiblitCore  # type: ignore[import]
        _core = NiblitCore()
    except Exception as exc:
        _core_error = str(exc)
        log.warning("NiblitCore unavailable: %s", exc)
    return _core


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _list_threads() -> list:
    return [t.name for t in threading.enumerate()]


# ── API-key guard ────────────────────────────────────────────────────────────

_API_KEY: Optional[str] = os.environ.get("NIBLIT_API_KEY")


def _require_key(request: Request) -> bool:
    """Return True when the request is authorised (or no key is configured)."""
    if not _API_KEY:
        return True
    return request.headers.get("X-API-Key") == _API_KEY


# ── Rate limiter (per-IP, in-process) ────────────────────────────────────────

_RATE_LIMIT = 10      # max requests per window
_RATE_WINDOW = 60     # window size in seconds
_rate_store: dict = {}


def _rate_limited(request: Request) -> bool:
    ip = (request.client.host if request.client else None) or "unknown"
    now = time.time()
    hits = [t for t in _rate_store.get(ip, []) if now - t < _RATE_WINDOW]
    _rate_store[ip] = hits
    if len(hits) >= _RATE_LIMIT:
        return True
    _rate_store[ip].append(now)
    return False


# ── Command catalog ──────────────────────────────────────────────────────────
# Mirrors app.py COMMAND_GROUPS — pure static data, no imports needed.
# Used by /api/commands (sidebar UI) and /api/suggest (command palette).

COMMAND_GROUPS = [
    {
        "group": "Core",
        "icon": "🏠",
        "commands": [
            {"label": "help",                     "cmd": "help",           "desc": "Show the complete Niblit command reference"},
            {"label": "time",                     "cmd": "time",           "desc": "Display current date and time"},
            {"label": "status",                   "cmd": "status",         "desc": "Show overall system status (modules, threads, memory)"},
            {"label": "health",                   "cmd": "health",         "desc": "Run a comprehensive health check across all subsystems"},
            {"label": "metrics",                  "cmd": "metrics",        "desc": "Show real-time performance metrics (CPU, RAM, latency)"},
            {"label": "dump",                     "cmd": "dump",           "desc": "Show memory dump-loop stats and last snapshot info"},
        ],
    },
    {
        "group": "Memory & Learning",
        "icon": "📝",
        "commands": [
            {"label": "remember key:value",       "cmd": "remember ",      "desc": "Persist a key-value fact to canonical niblit_memory",                 "has_input": True},
            {"label": "learn about <topic>",      "cmd": "learn about ",   "desc": "Queue a topic for autonomous background research (ALE Step 1)",       "has_input": True},
            {"label": "ideas about <topic>",      "cmd": "ideas about ",   "desc": "Run SelfIdeaGenerator to produce creative implementation ideas",      "has_input": True},
            {"label": "dump visible",             "cmd": "dump visible",   "desc": "Enable verbose niblit_memory dump output in logs"},
            {"label": "dump invisible",           "cmd": "dump invisible", "desc": "Silence niblit_memory dump output (default)"},
        ],
    },
    {
        "group": "Knowledge & Recall",
        "icon": "🧠",
        "commands": [
            {"label": "recall <topic>",           "cmd": "recall ",        "desc": "Full-text search across KnowledgeDB facts for any stored topic",      "has_input": True},
            {"label": "acquired data",            "cmd": "acquired data",  "desc": "Browse all facts acquired by the Autonomous Learning Engine"},
            {"label": "acquired data <category>", "cmd": "acquired data ", "desc": "Filter ALE facts by category: research / ideas / code / reflection",  "has_input": True},
            {"label": "knowledge stats",          "cmd": "knowledge stats","desc": "KnowledgeDB statistics: fact counts, top tags, ALE step breakdown"},
            {"label": "ale processes",            "cmd": "ale processes",  "desc": "Describe all 28 ALE pipeline steps with data-flow and status"},
        ],
    },
    {
        "group": "Autonomous Learning Engine",
        "icon": "🤖",
        "commands": [
            {"label": "autonomous-learn start",          "cmd": "autonomous-learn start",           "desc": "Resume the 28-step ALE background loop"},
            {"label": "autonomous-learn stop",           "cmd": "autonomous-learn stop",            "desc": "Pause the ALE loop (knowledge already stored is retained)"},
            {"label": "autonomous-learn status",         "cmd": "autonomous-learn status",          "desc": "View ALE cycle count, current topic, step timings, and KB facts"},
            {"label": "add-topic <topic>",               "cmd": "autonomous-learn add-topic ",      "desc": "Inject a new research topic into the ALE rotation queue",             "has_input": True},
            {"label": "autonomous-learn code-status",    "cmd": "autonomous-learn code-status",     "desc": "Show ALE code-generation literacy loop status"},
            {"label": "autonomous-learn serpex-research","cmd": "autonomous-learn serpex-research", "desc": "Trigger ALE Step 27: Serpex live web research on current topic"},
            {"label": "autonomous-learn serpex-search",  "cmd": "autonomous-learn serpex-search ",  "desc": "Ad-hoc Serpex web search stored into KnowledgeDB",                    "has_input": True},
        ],
    },
    {
        "group": "Auto Research",
        "icon": "🔭",
        "commands": [
            {"label": "auto-research start",      "cmd": "auto-research start",   "desc": "Start SelfResearcher continuous background research + ALE engine"},
            {"label": "auto-research stop",       "cmd": "auto-research stop",    "desc": "Stop SelfResearcher auto-research loop and pause ALE"},
            {"label": "auto-research status",     "cmd": "auto-research status",  "desc": "Show auto-research enabled/disabled state and last topic"},
            {"label": "auto-research pause",      "cmd": "auto-research pause",   "desc": "Temporarily pause auto-research without clearing the topic queue"},
            {"label": "auto-research resume",     "cmd": "auto-research resume",  "desc": "Resume a paused auto-research session"},
        ],
    },
    {
        "group": "Research & Internet",
        "icon": "🔍",
        "commands": [
            {"label": "search <query>",           "cmd": "search ",        "desc": "Live internet search via SerpEx → DuckDuckGo fallback",               "has_input": True, "is_search": True},
            {"label": "summary <query>",          "cmd": "summary ",       "desc": "Fetch a concise web summary and store it in KnowledgeDB",             "has_input": True},
            {"label": "self-research <topic>",    "cmd": "self-research ", "desc": "Run SelfResearcher (Serpex → Searchcode → Engine → Internet chain)",  "has_input": True},
            {"label": "research code <lang>",     "cmd": "research code ", "desc": "Research a programming language or framework → feed CodeGenerator",   "has_input": True},
        ],
    },
    {
        "group": "Self-Teacher & Learners",
        "icon": "🎓",
        "commands": [
            {"label": "self-teach <topic>",       "cmd": "self-teach ",    "desc": "SelfTeacher: research → store in niblit_memory → feed learner → reflect", "has_input": True},
            {"label": "learn about <topic>",      "cmd": "learn about ",   "desc": "Queue a topic; ALE will research it and call SelfTeacher in Step 6",      "has_input": True},
            {"label": "ideas about <topic>",      "cmd": "ideas about ",   "desc": "Generate ideas via SelfIdeaGenerator → store in niblit_memory",          "has_input": True},
        ],
    },
    {
        "group": "Brain & Self-Implementation",
        "icon": "🧬",
        "commands": [
            {"label": "self-idea <prompt>",       "cmd": "self-idea ",     "desc": "Generate an idea via SelfIdeaGenerator and auto-implement it",                   "has_input": True},
            {"label": "self-implement <plan>",    "cmd": "self-implement ","desc": "Enqueue an implementation plan directly to SelfImplementer",                     "has_input": True},
            {"label": "reflect <text>",           "cmd": "reflect ",       "desc": "Run ReflectModule on text and store reflection in KnowledgeDB",                  "has_input": True},
            {"label": "auto-reflect",             "cmd": "auto-reflect",   "desc": "Auto-reflect on the most recent interactions and store insights"},
            {"label": "self-heal",                "cmd": "self-heal",      "desc": "Run SelfHealer to detect and repair common runtime issues"},
        ],
    },
    {
        "group": "Evolution Engine",
        "icon": "🌱",
        "commands": [
            {"label": "evolve",                   "cmd": "evolve",         "desc": "Run one EvolveEngine step (research → code → teach → reflect → improve)"},
            {"label": "evolve start",             "cmd": "evolve start",   "desc": "Start the EvolveEngine continuous background evolution loop"},
            {"label": "evolve stop",              "cmd": "evolve stop",    "desc": "Stop the background evolution loop (current cycle completes first)"},
            {"label": "evolve status",            "cmd": "evolve status",  "desc": "Show evolution loop state, last step, and improvements made"},
            {"label": "evolve history",           "cmd": "evolve history", "desc": "List recent evolution steps with direction, code generated, and outcome"},
        ],
    },
    {
        "group": "Code Generation",
        "icon": "💻",
        "commands": [
            {"label": "generate code <lang>",     "cmd": "generate code ",    "desc": "Generate a complete code module (language + optional template key)",  "has_input": True},
            {"label": "run code <lang> <code>",   "cmd": "run code ",         "desc": "Execute an inline code snippet and return stdout / errors",           "has_input": True},
            {"label": "validate <lang> <code>",   "cmd": "validate ",         "desc": "Validate syntax and structure without executing",                     "has_input": True},
            {"label": "execute file <path>",      "cmd": "execute file ",     "desc": "Execute a script file and capture its output",                        "has_input": True},
            {"label": "code templates [lang]",    "cmd": "code templates",    "desc": "List all available code templates (filtered by language if given)"},
            {"label": "available languages",      "cmd": "available languages","desc": "List every language supported by CodeGenerator"},
        ],
    },
    {
        "group": "File Manager",
        "icon": "📁",
        "commands": [
            {"label": "read file <path>",            "cmd": "read file ",    "desc": "Read and display a file from the filesystem",          "has_input": True},
            {"label": "write file <path> <content>", "cmd": "write file ",   "desc": "Write content to a file (creates if not present)",     "has_input": True},
            {"label": "list files [dir]",            "cmd": "list files",    "desc": "List directory contents (defaults to working dir)"},
            {"label": "file environment",            "cmd": "file environment","desc": "Show filesystem environment info (paths, disk, OS)"},
        ],
    },
    {
        "group": "Introspection",
        "icon": "🔬",
        "commands": [
            {"label": "my structure",             "cmd": "my structure",      "desc": "Full structural inventory: modules, adapters, engines, memory"},
            {"label": "my threads",               "cmd": "my threads",        "desc": "List every active thread with name, state, and daemon flag"},
            {"label": "my loops",                 "cmd": "my loops",          "desc": "Show all background loop names, intervals, and running states"},
            {"label": "my modules",               "cmd": "my modules",        "desc": "List all loaded Python modules and their wiring status"},
            {"label": "dashboard",                "cmd": "dashboard",         "desc": "Full runtime dashboard: threads, loops, memory, ALE, modules"},
            {"label": "resource usage",           "cmd": "resource usage",    "desc": "Show RAM usage, CPU percent, and process uptime"},
        ],
    },
    {
        "group": "Settings",
        "icon": "⚙️",
        "commands": [
            {"label": "toggle-llm on",            "cmd": "toggle-llm on",  "desc": "Enable the HuggingFace LLM adapter for AI-assisted responses"},
            {"label": "toggle-llm off",           "cmd": "toggle-llm off", "desc": "Disable the LLM adapter (research-only mode, no API calls)"},
        ],
    },
    {
        "group": "Diagnostics",
        "icon": "🩺",
        "commands": [
            {"label": "run-diagnostics",          "cmd": "run-diagnostics","desc": "Execute the full Niblit diagnostic suite across all subsystems"},
            {"label": "loop-errors",              "cmd": "loop-errors",    "desc": "Display all errors captured by the LoopTracer since startup"},
        ],
    },
]

_ALL_CMDS: list = [c["cmd"].strip() for g in COMMAND_GROUPS for c in g["commands"]]


def _suggest(q: str) -> list:
    """Return close-match command suggestions for *q*."""
    return difflib.get_close_matches(q.lower(), _ALL_CMDS, n=3, cutoff=0.6)


# ── Request models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str = ""
    message: str = ""


class SearchBody(BaseModel):
    query: str = ""
    text: str = ""


# ── Dashboard HTML ──────────────────────────────────────────────────────────
_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Niblit AI — Terminal</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#0b0b0f;color:#e2e8f0;font-family:Inter,system-ui,sans-serif;font-size:14px;overflow:hidden}
#topbar{display:flex;align-items:center;gap:12px;padding:0 16px;height:40px;background:#0d0d13;border-bottom:1px solid #1e2030;flex-shrink:0}
.logo{font-weight:700;color:#0ea5a4;letter-spacing:.05em;font-size:15px}
.dot{width:8px;height:8px;border-radius:50%;background:#6ee7b7;flex-shrink:0;transition:background .4s}
.dot.red{background:#f87171}
.tstat{color:#64748b;font-size:12px}
.tstat span{color:#e2e8f0}
.spacer{flex:1}
#main{display:flex;height:calc(100vh - 40px);overflow:hidden}
/* ── Sidebar ─────────────────────────────────────────────── */
#sidebar{width:220px;flex-shrink:0;background:#111116;border-right:1px solid #1e2030;display:flex;flex-direction:column;overflow:hidden}
.sb-head{padding:10px 12px 6px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#64748b;flex-shrink:0}
#sidebar-inner{flex:1;overflow-y:auto;padding-bottom:8px}
#sidebar-inner::-webkit-scrollbar{width:4px}
#sidebar-inner::-webkit-scrollbar-thumb{background:#1e2030;border-radius:2px}
.sg-label{padding:8px 12px 2px;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#4b5563;display:flex;align-items:center;gap:5px}
.sg-label .gi{font-size:12px}
.sc{display:flex;align-items:center;gap:6px;padding:4px 12px 4px 20px;cursor:pointer;border-radius:4px;margin:0 4px;color:#94a3b8;font-size:12px;transition:background .1s,color .1s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc:hover{background:#1e2030;color:#e2e8f0}
.sc-dot{width:4px;height:4px;border-radius:50%;background:#0ea5a4;flex-shrink:0}
/* ── Terminal ─────────────────────────────────────────────── */
#terminal{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
#output{flex:1;overflow-y:auto;padding:12px 16px;font-family:'JetBrains Mono',Consolas,'Courier New',monospace;font-size:13px;line-height:1.65}
#output::-webkit-scrollbar{width:6px}
#output::-webkit-scrollbar-thumb{background:#1e2030;border-radius:3px}
.ln{padding:1px 0;word-break:break-all}
.ln.pl{color:#0ea5a4;font-weight:600}
.ln.rp{color:#c9d1d9}
.ln.er{color:#f87171}
.ln.sy{color:#64748b;font-style:italic}
.ln.bt{color:#6ee7b7}
.ln.sp{color:#1e2030;user-select:none}
#inputbar{display:flex;align-items:center;gap:8px;padding:10px 16px;border-top:1px solid #1e2030;background:#0d0d13;flex-shrink:0;position:relative}
.prompt{color:#0ea5a4;font-family:'JetBrains Mono',Consolas,monospace;font-weight:700;font-size:13px;white-space:nowrap}
#cmd-input{flex:1;background:transparent;border:none;outline:none;color:#e2e8f0;font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;caret-color:#0ea5a4;min-width:0}
#cmd-input::placeholder{color:#334155}
#send-btn{background:#0ea5a4;border:none;color:#0b0b0f;padding:5px 14px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:700;white-space:nowrap;flex-shrink:0}
#send-btn:hover{background:#0ccbca}
#send-btn:disabled{background:#1e2030;color:#4b5563;cursor:not-allowed}
#sug-box{position:absolute;bottom:52px;left:56px;right:60px;background:#1a1a24;border:1px solid #334155;border-radius:4px;font-family:monospace;font-size:12px;z-index:100;display:none;max-height:140px;overflow-y:auto}
.sug-item{padding:5px 10px;cursor:pointer;color:#94a3b8}
.sug-item:hover,.sug-item.act{background:#0ea5a4;color:#0b0b0f}
/* ── Status panel ─────────────────────────────────────────── */
#status{width:240px;flex-shrink:0;background:#111116;border-left:1px solid #1e2030;display:flex;flex-direction:column;overflow:hidden}
.sp-head{padding:10px 12px 6px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#64748b;flex-shrink:0;border-bottom:1px solid #1e2030}
#status-inner{flex:1;overflow-y:auto;padding:10px 12px}
#status-inner::-webkit-scrollbar{width:4px}
#status-inner::-webkit-scrollbar-thumb{background:#1e2030;border-radius:2px}
.sp-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #0d0d13}
.sp-k{color:#64748b;font-size:12px}
.sp-v{font-size:12px;color:#e2e8f0;text-align:right;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sp-v.ok{color:#6ee7b7}.sp-v.er{color:#f87171}.sp-v.wa{color:#fbbf24}
.sp-sec{margin-top:10px;margin-bottom:4px;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#4b5563}
.sp-topic{padding:3px 6px;margin:3px 0;background:#0d0d13;border-radius:3px;font-size:11px;color:#94a3b8;border-left:2px solid #0ea5a4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:800px){#sidebar{display:none}#status{display:none}}
</style>
</head>
<body>
<div id="topbar">
  <div class="logo">&#x1F916; NIBLIT AI</div>
  <div id="live-dot" class="dot red" title="Connecting..."></div>
  <div class="tstat">Core: <span id="t-core">...</span></div>
  <div class="tstat">Threads: <span id="t-threads">&#8212;</span></div>
  <div class="tstat">ALE: <span id="t-ale">&#8212;</span></div>
  <div class="spacer"></div>
  <div class="tstat" id="t-clock"></div>
</div>
<div id="main">
  <!-- Sidebar -->
  <div id="sidebar">
    <div class="sb-head">Commands</div>
    <div id="sidebar-inner"><div id="cmd-groups"><div class="sg-label">&#x23F3; Loading&#8230;</div></div></div>
  </div>
  <!-- Terminal -->
  <div id="terminal">
    <div id="output"></div>
    <div id="inputbar">
      <span class="prompt">niblit&gt;</span>
      <input id="cmd-input" type="text" placeholder="type a command or message&#8230;" autocomplete="off" autocorrect="off" spellcheck="false">
      <div id="sug-box"></div>
      <button id="send-btn" onclick="doSend()">Send &#x23CE;</button>
    </div>
  </div>
  <!-- Status panel -->
  <div id="status">
    <div class="sp-head">System Status</div>
    <div id="status-inner">
      <div class="sp-row"><span class="sp-k">Core</span><span class="sp-v" id="sp-core">&#8230;</span></div>
      <div class="sp-row"><span class="sp-k">ALE</span><span class="sp-v" id="sp-ale">&#8230;</span></div>
      <div class="sp-row"><span class="sp-k">Cycle</span><span class="sp-v" id="sp-cycle">&#8212;</span></div>
      <div class="sp-row"><span class="sp-k">Threads</span><span class="sp-v" id="sp-threads">&#8212;</span></div>
      <div class="sp-row"><span class="sp-k">Facts</span><span class="sp-v" id="sp-facts">&#8212;</span></div>
      <div class="sp-row"><span class="sp-k">Updated</span><span class="sp-v" id="sp-ts">&#8212;</span></div>
      <div class="sp-sec">Current Topic</div>
      <div class="sp-topic" id="sp-topic">&#8212;</div>
      <div class="sp-sec">Research Queue</div>
      <div id="sp-topics"></div>
    </div>
  </div>
</div>
<script>
'use strict';
var out=document.getElementById('output'),inp=document.getElementById('cmd-input');
var sugBox=document.getElementById('sug-box');
var hist=[],histIdx=-1,busy=false,sugItems=[],sugSel=-1;

function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function addLine(text,cls){
  var d=document.createElement('div');
  d.className='ln '+(cls||'rp');
  d.textContent=text;
  out.appendChild(d);
  out.scrollTop=out.scrollHeight;
}
function addSep(){addLine('\\u2500'.repeat(58),'sp');}

function setBusy(b){
  busy=b;
  document.getElementById('send-btn').disabled=b;
  inp.disabled=b;
  document.getElementById('send-btn').textContent=b?'\\u2026':'Send \\u23CE';
}

async function doSend(){
  var text=inp.value.trim();
  if(!text||busy)return;
  inp.value='';hist.unshift(text);histIdx=-1;
  hideSug();
  addLine('niblit> '+text,'pl');
  setBusy(true);
  try{
    var res=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})});
    var data=await res.json();
    if(data.error){addLine('[error] '+data.error,'er');}
    else{(data.reply||'').split('\\n').forEach(function(l){addLine(l,'rp');});}
  }catch(e){addLine('[network error] '+e.message,'er');}
  setBusy(false);inp.focus();
}

function hideSug(){sugBox.style.display='none';sugItems=[];sugSel=-1;}

function showSug(items){
  sugItems=items;sugSel=-1;
  sugBox.innerHTML='';
  if(!items.length){hideSug();return;}
  items.forEach(function(s,i){
    var d=document.createElement('div');d.className='sug-item';d.textContent=s;
    d.addEventListener('mousedown',function(e){e.preventDefault();inp.value=s+' ';hideSug();inp.focus();});
    sugBox.appendChild(d);
  });
  sugBox.style.display='block';
}

inp.addEventListener('input',function(){
  var v=inp.value;
  if(!v){hideSug();return;}
  fetch('/api/suggest?q='+encodeURIComponent(v)).then(function(r){return r.json();}).then(function(d){
    if(inp.value===v)showSug(d.suggestions||[]);
  }).catch(function(){});
});

inp.addEventListener('keydown',function(e){
  if(e.key==='Enter'){e.preventDefault();if(sugSel>=0&&sugItems[sugSel]){inp.value=sugItems[sugSel]+' ';hideSug();}else{doSend();}return;}
  if(e.key==='Escape'){hideSug();return;}
  if(e.key==='Tab'){e.preventDefault();if(sugItems.length===1){inp.value=sugItems[0]+' ';hideSug();}else if(sugItems.length>1){sugSel=(sugSel+1)%sugItems.length;Array.from(sugBox.children).forEach(function(c,i){c.className='sug-item'+(i===sugSel?' act':'');});}return;}
  if(e.key==='ArrowDown'){e.preventDefault();if(sugItems.length){sugSel=(sugSel+1)%sugItems.length;Array.from(sugBox.children).forEach(function(c,i){c.className='sug-item'+(i===sugSel?' act':'');});}else if(histIdx>0){histIdx--;inp.value=hist[histIdx];}else{histIdx=-1;inp.value='';}return;}
  if(e.key==='ArrowUp'){e.preventDefault();if(sugItems.length){if(sugSel>0)sugSel--;Array.from(sugBox.children).forEach(function(c,i){c.className='sug-item'+(i===sugSel?' act':'');});}else if(histIdx<hist.length-1){histIdx++;inp.value=hist[histIdx];}return;}
});
document.addEventListener('click',function(e){if(!sugBox.contains(e.target)&&e.target!==inp)hideSug();});

async function loadBoot(){
  addLine('\\u250c'+('\\u2500'.repeat(43))+'\\u2510','bt');
  addLine('\\u2502           NIBLIT AI  TERMINAL            \\u2502','bt');
  addLine('\\u2502     Autonomous Intelligence Platform     \\u2502','bt');
  addLine('\\u2514'+('\\u2500'.repeat(43))+'\\u2518','bt');
  addLine('Connecting to Niblit core\\u2026','sy');
  try{
    var res=await fetch('/api/boot');
    var data=await res.json();
    addSep();
    (data.messages||[]).forEach(function(m){addLine(m,'bt');});
    addSep();
    if(data.ready){
      addLine('\\u2713 Core ready. Type any command or message below.','sy');
      addLine('  Tip: Tab = autocomplete  \\u2191/\\u2193 = history  Click sidebar = run command','sy');
    }else{
      addLine('\\u26a0 Running in degraded mode \\u2014 NiblitCore unavailable.','er');
      addLine('  Commands will return errors until core loads.','sy');
    }
  }catch(e){addLine('[boot error] '+e.message,'er');}
}

async function loadCommands(){
  try{
    var res=await fetch('/api/commands');
    var data=await res.json();
    var ctr=document.getElementById('cmd-groups');ctr.innerHTML='';
    (data.commands||[]).forEach(function(g){
      var lbl=document.createElement('div');lbl.className='sg-label';
      lbl.innerHTML='<span class="gi">'+esc(g.icon||'')+'</span>'+esc(g.group||'');
      ctr.appendChild(lbl);
      (g.commands||[]).forEach(function(c){
        var div=document.createElement('div');div.className='sc';div.title=esc(c.desc||'');
        div.innerHTML='<span class="sc-dot"></span>'+esc(c.label||c.cmd||'');
        div.addEventListener('click',function(){inp.value=c.cmd||'';inp.focus();if(!c.has_input)doSend();});
        ctr.appendChild(div);
      });
    });
  }catch(e){document.getElementById('cmd-groups').innerHTML='<div class="sg-label">Failed to load</div>';}
}

async function pollBg(){
  try{
    var res=await fetch('/api/bg_status');
    var d=await res.json();
    document.getElementById('t-threads').textContent=d.threads||'\\u2014';
    document.getElementById('sp-threads').textContent=d.threads||'\\u2014';
    document.getElementById('sp-ts').textContent=(d.ts||'').slice(11)||'\\u2014';
    if(d.ale){
      var a=d.ale,run=a.running;
      document.getElementById('t-ale').textContent=run?'running':'stopped';
      var sv=document.getElementById('sp-ale');sv.textContent=run?'running':'stopped';sv.className='sp-v '+(run?'ok':'wa');
      document.getElementById('sp-cycle').textContent=a.cycle||'0';
      document.getElementById('sp-topic').textContent=a.topic||'\\u2014';
    }
    if((d.topics||[]).length){
      var tp=document.getElementById('sp-topics');tp.innerHTML='';
      d.topics.forEach(function(t){var div=document.createElement('div');div.className='sp-topic';div.textContent=t;tp.appendChild(div);});
    }
    document.getElementById('live-dot').className='dot';
    document.getElementById('live-dot').title='Live';
  }catch(e){document.getElementById('live-dot').className='dot red';}
}

async function pollStatus(){
  try{
    var res=await fetch('/api/status');
    var d=await res.json();
    var ok=d.core_loaded;
    document.getElementById('t-core').textContent=ok?'ok':'error';
    var sv=document.getElementById('sp-core');
    sv.textContent=ok?'\\u2713 loaded':'\\u2717 '+(d.core_error||'unavailable');
    sv.className='sp-v '+(ok?'ok':'er');
    if(d.facts_count!==undefined)document.getElementById('sp-facts').textContent=d.facts_count;
  }catch(e){}
}

function updateClock(){document.getElementById('t-clock').textContent=new Date().toLocaleTimeString();}

loadBoot();loadCommands();pollBg();pollStatus();
setInterval(pollBg,15000);setInterval(pollStatus,30000);setInterval(updateClock,1000);
inp.focus();
</script>
</body>
</html>"""

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "niblit", "mode": "serverless"}


@app.get("/")
def index(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return HTMLResponse(_DASHBOARD_HTML)
    return {
        "service": "Niblit AI",
        "status": "ok",
        "endpoints": [
            "/health", "/ping", "/chat", "/memory",
            "/api/status", "/api/boot", "/api/commands",
            "/api/suggest", "/api/threads", "/api/bg_status",
            "/api/search",
        ],
    }


@app.get("/ping")
def ping():
    return {"pong": True, "ts": int(time.time())}


@app.get("/api/boot")
def api_boot():
    """Return the boot sequence messages (mirrors main.py boot())."""
    msgs = [f"{_ts()} TRUE AUTONOMOUS NIBLIT BOOT"]
    core = _get_core()
    if core:
        msgs += [
            f"{_ts()} CORE READY",
            f"{_ts()} Active threads: {len(threading.enumerate())}",
            f"{_ts()} READY",
        ]
    else:
        msgs += [
            f"{_ts()} [WARN] NiblitCore unavailable — running in degraded mode",
            f"{_ts()} READY (degraded)",
        ]
    return {"messages": msgs, "ready": core is not None}


@app.get("/api/commands")
def api_commands():
    """Return the full command catalog used by the sidebar menu."""
    return {
        "commands": COMMAND_GROUPS,
        "count": sum(len(g["commands"]) for g in COMMAND_GROUPS),
    }


@app.get("/api/suggest")
def api_suggest(q: str = ""):
    """Return close-match command suggestions for a partial query."""
    return {"suggestions": _suggest(q.strip()), "query": q}


@app.get("/api/threads")
def api_threads():
    """Return the live thread list."""
    return {"threads": _list_threads()}


@app.get("/api/status")
def api_status():
    """Return detailed system status."""
    core = _get_core()
    data: dict = {
        "core_loaded": core is not None,
        "core_error": _core_error,
        "ts": int(time.time()),
    }
    if core:
        try:
            data["personality"] = core.memory.get_personality()
        except Exception:
            pass
        try:
            data["facts_count"] = len(core.memory.list_facts(limit=500))
        except Exception:
            pass
    return data


@app.get("/api/bg_status")
def api_bg_status():
    """Lightweight background status — polled every ~15 s by the UI."""
    core = _get_core()
    data: dict = {
        "ts": _ts(),
        "ale": None,
        "topics": [],
        "threads": len(threading.enumerate()),
    }
    if core:
        ale = getattr(core, "autonomous_engine", None)
        if ale:
            data["ale"] = {
                "running": getattr(ale, "running", False),
                "cycle": getattr(ale, "_cycle_count", 0),
                "topic": (
                    ale.get_current_topic()
                    if hasattr(ale, "get_current_topic") else None
                ),
            }
            data["topics"] = getattr(ale, "research_topics", [])[:5]
    return data


@app.get("/api/search")
def api_search_get(request: Request, q: str = "", query: str = ""):
    """Search endpoint (GET) — wraps the 'search <query>' command."""
    if not _require_key(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _rate_limited(request):
        return JSONResponse({"error": "rate limit reached"}, status_code=429)
    search_q = (q or query).strip()
    if not search_q:
        return JSONResponse(
            {"error": "missing query — send ?q=<query> or POST {\"query\":\"...\"}"},
            status_code=400,
        )
    core = _get_core()
    if not core:
        return JSONResponse({"error": "core unavailable"}, status_code=503)
    try:
        result = core.handle(f"search {search_q}")
    except Exception as exc:
        log.error("search error: %s", exc)
        result = f"[error] {exc}"
    return {"query": search_q, "result": result}


@app.post("/api/search")
def api_search_post(request: Request, body: SearchBody):
    """Search endpoint (POST) — wraps the 'search <query>' command."""
    if not _require_key(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _rate_limited(request):
        return JSONResponse({"error": "rate limit reached"}, status_code=429)
    search_q = (body.query or body.text).strip()
    if not search_q:
        return JSONResponse({"error": "missing query"}, status_code=400)
    core = _get_core()
    if not core:
        return JSONResponse({"error": "core unavailable"}, status_code=503)
    try:
        result = core.handle(f"search {search_q}")
    except Exception as exc:
        log.error("search error: %s", exc)
        result = f"[error] {exc}"
    return {"query": search_q, "result": result}


@app.post("/chat")
def chat(request: Request, body: ChatRequest):
    """Process user input through NiblitCore (mirrors main.py run_shell())."""
    if not _require_key(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _rate_limited(request):
        return JSONResponse({"error": "rate limit reached"}, status_code=429)
    text = (body.text or body.message).strip()
    if not text:
        return JSONResponse({"error": "no text provided"}, status_code=400)
    core = _get_core()
    if core is None:
        log.warning("NiblitCore unavailable for chat request")
        return {
            "reply": "[error] NiblitCore unavailable — see server logs",
            "ts": int(time.time()),
        }
    try:
        reply = core.handle(text)
    except Exception as exc:
        log.error("core.handle error: %s", exc)
        reply = "[error] request failed — see server logs"
    return {"reply": reply, "ts": int(time.time())}


@app.get("/memory")
def memory(request: Request):
    """Return stored facts from NiblitMemory."""
    if not _require_key(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _rate_limited(request):
        return JSONResponse({"error": "rate limit reached"}, status_code=429)
    core = _get_core()
    facts: list = []
    if core:
        try:
            facts = core.memory.list_facts(limit=200)
        except Exception:
            pass
    return {"facts": facts, "count": len(facts)}
