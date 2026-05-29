"""
app.py — Niblit FastAPI application for Vercel serverless deployment

Implements content negotiation with JSONRenderer, HTMLRenderer, and
BrowsableAPIRenderer.  All endpoints auto-select the best renderer based on
the incoming Accept header.

The /chat endpoint mirrors the run_shell() logic from main.py so that
the web experience is identical to running Niblit in a Termux terminal.
"""

import asyncio
import difflib
import datetime
import hmac
import json as _json
import threading
import time
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

# Load .env file when running locally (e.g. Termux).  On Vercel / Render the
# platform injects env vars directly, so this is a no-op in those environments.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on os.environ

from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse, JSONResponse
from pydantic import BaseModel

try:
    from niblit_core import NiblitCore
except Exception:
    NiblitCore = None

try:
    from modules.unified_runtime import get_unified_runtime
except Exception:
    get_unified_runtime = None

# ══════════════════════════════════════════════════════════════
# CONTENT NEGOTIATION RENDERERS
# ══════════════════════════════════════════════════════════════

class JSONRenderer:
    """Renders response data as JSON.  Supports ?indent= query param."""
    media_type = "application/json"
    charset = None

    def render(self, data, request: Request = None, media_type=None, **options):
        indent = options.get("indent")
        if request is not None:
            indent = indent or request.query_params.get("indent")
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

    def render(self, data, request: Request = None, media_type=None, **options):
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

    def render(self, data, request: Request = None, media_type=None, **options):
        status = options.get("status", "200 OK")
        url = str(request.url) if request is not None else ""
        body = _json.dumps(data, indent=2, default=str)
        html = self._TMPL.format(status=status, url=url, data=body)
        return html, "text/html; charset=utf-8"


_DEFAULT_RENDERERS = [JSONRenderer(), BrowsableAPIRenderer()]


def negotiate_renderer(request: Request, renderers=None):
    """Pick the best renderer via Accept-header content negotiation.

    Parses quality values (``q=``) so that
    ``Accept: text/html;q=0.1,application/json;q=0.9`` correctly picks the
    JSON renderer over the HTML renderer.
    """
    active = renderers if renderers is not None else _DEFAULT_RENDERERS
    accept_header = request.headers.get("accept", "") if request is not None else ""
    if not accept_header:
        return active[0]

    # Build a list of (quality, media_type) pairs from the Accept header.
    accepted: List[tuple] = []
    for part in accept_header.split(","):
        part = part.strip()
        if not part:
            continue
        segments = [s.strip() for s in part.split(";")]
        media_type = segments[0]
        quality = 1.0
        for seg in segments[1:]:
            if seg.startswith("q="):
                try:
                    quality = float(seg[2:])
                except ValueError:
                    pass
                break
        accepted.append((quality, media_type))

    # Sort by descending quality so highest-preference type is checked first.
    accepted.sort(key=lambda x: x[0], reverse=True)

    for _q, media_type in accepted:
        for r in active:
            if r.media_type == media_type or media_type == "*/*":
                return r
            # Wildcard sub-type match: e.g. "text/*" matches "text/html"
            if "/" in media_type:
                main, sub = media_type.split("/", 1)
                if sub == "*" and r.media_type.startswith(f"{main}/"):
                    return r
    return active[0]


def render_response(request: Request, data, status=200, renderers=None, headers=None):
    """Content-negotiate and return a FastAPI Response."""
    # Standard HTTP status phrases for common codes
    _PHRASES = {
        200: "OK", 201: "Created", 204: "No Content",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 429: "Too Many Requests",
        500: "Internal Server Error", 503: "Service Unavailable",
    }
    phrase = _PHRASES.get(status, "OK" if status < 400 else "Error")
    status_str = f"{status} {phrase}"
    renderer = negotiate_renderer(request, renderers)
    body, ct = renderer.render(data, request=request, status_code=status, status=status_str)
    return Response(content=body, status_code=status, media_type=ct, headers=headers)


# ══════════════════════════════════════════════════════════════
# API KEY PROTECTION
# ══════════════════════════════════════════════════════════════

API_KEY = os.environ.get("NIBLIT_API_KEY", None)


def require_key(request: Request) -> bool:
    if not API_KEY:
        return True
    req_key = request.headers.get("X-API-Key")
    if req_key is None:
        return False
    # Use constant-time comparison to prevent timing-based key enumeration.
    return hmac.compare_digest(req_key, API_KEY)


# ══════════════════════════════════════════════════════════════
# RATE LIMITING
# ══════════════════════════════════════════════════════════════

RATE_LIMIT = 10
RATE_WINDOW = 60
rate_store: dict = {}


def rate_limited(request: Request) -> bool:
    ip = (request.client.host if request.client else None) or "unknown"
    now = time.time()
    # Rough GC: keep the dict from growing unboundedly with unique IPs.
    if len(rate_store) > 10_000:
        rate_store.clear()
    entry = [t for t in rate_store.get(ip, []) if now - t < RATE_WINDOW]
    rate_store[ip] = entry
    if len(entry) >= RATE_LIMIT:
        return True
    rate_store[ip].append(now)
    return False


def _guard(request: Request) -> None:
    """FastAPI dependency that enforces auth and rate-limiting together."""
    if not require_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many requests")


# ══════════════════════════════════════════════════════════════
# NIBLIT CORE LOADER (lazy — avoids cold-start penalty)
# ══════════════════════════════════════════════════════════════

_core = None
_core_lock = threading.Lock()


def get_core():
    global _core  # pylint: disable=global-statement
    if _core is None:
        with _core_lock:
            if _core is None and NiblitCore:  # double-checked locking
                try:
                    _core = NiblitCore()
                except Exception as exc:
                    logging.getLogger("NiblitApp").error("NiblitCore init error: %s", exc)
    return _core


def _get_unified_runtime():
    if get_unified_runtime is None:
        return None
    try:
        return get_unified_runtime()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# MAIN.PY HELPERS  (mirrors the helpers in main.py exactly)
# ══════════════════════════════════════════════════════════════

# Direct command keys handled in _direct_commands() (exact-match shortcut).
_DIRECT_CMD_KEYS = ("help", "commands", "status", "health", "memory",
                    "self-heal", "self-teach", "threads")
# Prefixes routed to NiblitRouter — single source of truth shared with
# _shell_process to avoid duplication.
_ROUTED_PREFIXES = ("search ", "summary ", "self-research ", "learn about ")
# Full command vocabulary used by suggest_command() — mirrors every command
# exposed in niblit_core.help_text() so the suggestion engine covers them all.
_SHELL_COMMANDS = list(_DIRECT_CMD_KEYS) + [
    # core
    "time", "metrics", "dump",
    # memory & learning
    "remember", "learn about", "ideas about",
    # knowledge
    "recall", "acquired data", "knowledge stats", "ale processes", "kb stats",
    # internet / research
    "search", "summary", "self-research", "research code",
    # self-improvement
    "self-idea", "self-implement", "self-teach", "idea-implement",
    "reflect", "auto-reflect",
    # autonomous learning
    "autonomous-learn start", "autonomous-learn stop",
    "autonomous-learn status", "autonomous-learn add-topic",
    "autonomous-learn code-status",
    # improvements
    "show improvements", "run improvement-cycle", "improvement-status",
    # evolution
    "evolve", "evolve start", "evolve stop", "evolve status", "evolve history",
    # code generation
    "generate code", "run code", "validate", "execute file",
    "code templates", "study language", "available languages",
    # file manager
    "read file", "write file", "list files", "file environment",
    # software study
    "study software", "software categories", "analyze architecture",
    "design software", "what have i studied",
    # structural introspection
    "my structure", "my threads", "my loops", "my modules", "my commands",
    "dashboard", "operational flow", "resource usage",
    # SLSA
    "slsa-status", "start_slsa", "stop_slsa", "restart_slsa",
    # live update
    "reload", "upgrade", "update-history",
    # settings / system
    "toggle-llm on", "toggle-llm off", "shutdown",
    # diagnostics
    "run-diagnostics", "run-live-test", "loop-errors",
    # orchestrator
    "orchestrate audit", "orchestrate self-heal", "orchestrate fix-guide",
    "orchestrate verify", "orchestrate pipeline", "hf-task",
    # debug
    "debug on", "debug off",
]


try:
    from modules.utils import timestamp as _ts_util  # shared utility
    def _ts() -> str:
        return _ts_util()
except Exception:
    def _ts() -> str:  # type: ignore[misc]
        """Return a timestamp string matching NiblitIO.timestamp() format (UTC)."""
        return datetime.datetime.now(datetime.timezone.utc).strftime("[%Y-%m-%d %H:%M:%S]")


def suggest_command(user_input):
    """Return close-match suggestions exactly like main.py suggest_command()."""
    matches = difflib.get_close_matches(user_input, _SHELL_COMMANDS, n=3, cutoff=0.5)
    # Never suggest a command identical to what the user already typed — difflib
    # returns exact matches too, which causes spurious "Did you mean X?" messages
    # immediately after X was executed successfully.
    return [m for m in matches if m != user_input]


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
    debug_lines is always empty in normal operation — it is only populated
    when the user explicitly sends a 'debug' prefixed command so that routing
    trace messages never appear alongside ordinary chat responses.
    """
    cmd = user_input.strip()
    lower = cmd.lower()
    ts = _ts()

    # EXIT / QUIT — acknowledged but we don't actually shut the server down
    if lower in ("exit", "quit", "shutdown"):
        return {"reply": f"{ts} Shutdown acknowledged (server continues running).",
                "suggestion": None, "ts": ts, "debug_lines": []}

    # DIRECT COMMANDS (exact match, same as main.py)
    direct = _direct_commands(core)
    if lower in direct:
        try:
            result = direct[lower]()
        except Exception as exc:
            result = f"[Command failed] {exc}"
        return {"reply": str(result), "suggestion": None, "ts": ts, "debug_lines": []}

    # ROUTED COMMANDS (search, summary, self-research, learn about)
    if any(lower.startswith(p) for p in _ROUTED_PREFIXES):
        if core.router:
            resp = core.router.process(cmd)
        else:
            resp = core.handle(cmd)
        return {"reply": str(resp), "suggestion": None, "ts": ts, "debug_lines": []}

    # CATCH-ALL — pass to core.handle() exactly like main.py
    response = core.handle(cmd)

    # Suggestion engine (same as main.py).
    # Only run when the input is NOT already a recognised command — suggesting
    # close matches for a command that just executed successfully is confusing.
    suggestion = None
    if lower not in _SHELL_COMMANDS:
        sug = suggest_command(lower)
        if sug:
            suggestion = f"Did you mean: {sug[0]} ?"

    return {"reply": str(response), "suggestion": suggestion, "ts": ts, "debug_lines": []}


# ══════════════════════════════════════════════════════════════
# COMMAND CATALOGUE  — every command from niblit_core.help_text()
# Used by the sidebar menu (/api/commands) and JS quick-actions.
# ══════════════════════════════════════════════════════════════

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
            {"label": "autonomous-learn start",         "cmd": "autonomous-learn start",          "desc": "Resume the 28-step Autonomous Learning Engine (ALE) background loop"},
            {"label": "autonomous-learn stop",          "cmd": "autonomous-learn stop",           "desc": "Pause the ALE loop (knowledge already stored is retained)"},
            {"label": "autonomous-learn status",        "cmd": "autonomous-learn status",         "desc": "View ALE cycle count, current topic, step timings, and KB facts"},
            {"label": "add-topic <topic>",              "cmd": "autonomous-learn add-topic ",     "desc": "Inject a new research topic into the ALE rotation queue",             "has_input": True},
            {"label": "autonomous-learn code-status",   "cmd": "autonomous-learn code-status",    "desc": "Show ALE code-generation literacy loop status (langs, last file)"},
            {"label": "autonomous-learn serpex-research","cmd": "autonomous-learn serpex-research","desc": "Trigger ALE Step 27: Serpex live web research on the current topic"},
            {"label": "autonomous-learn serpex-search <q>","cmd": "autonomous-learn serpex-search ","desc": "Ad-hoc Serpex web search stored straight into KnowledgeDB",        "has_input": True},
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
        "group": "Dynamic Topic Enrichment",
        "icon": "🧩",
        "commands": [
            {"label": "refresh-topics",           "cmd": "refresh-topics",                "desc": "Propose & inject fresh research topics via DynamicTopicManager now"},
            {"label": "refresh-topics status",    "cmd": "refresh-topics status",         "desc": "Show DynamicTopicManager seed count, embedding model, ALE topic-list size"},
            {"label": "refresh-topics add <t>",   "cmd": "refresh-topics add ",           "desc": "Add a manual seed topic to the DynamicTopicManager", "has_input": True},
        ],
    },
    {
        "group": "Self-Improvement",
        "icon": "⚡",
        "commands": [
            {"label": "show improvements",        "cmd": "show improvements",       "desc": "List all 10 registered self-improvement modules and their states"},
            {"label": "run improvement-cycle",    "cmd": "run improvement-cycle",   "desc": "Manually trigger one full improvement cycle across all 10 modules"},
            {"label": "improvement-status",       "cmd": "improvement-status",      "desc": "Show last run time, success rate, and output for each improvement"},
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
        "group": "Researcher Engine",
        "icon": "🔬",
        "commands": [
            {"label": "self-research <topic>",    "cmd": "self-research ", "desc": "SelfResearcher: Serpex (1) → Searchcode (2) → ResearcherEngine (3) → Internet (4)", "has_input": True},
            {"label": "summary <query>",          "cmd": "summary ",       "desc": "ResearcherEngine: check vector-store cache → live web → persist to niblit_memory", "has_input": True},
            {"label": "search <query>",           "cmd": "search ",        "desc": "Direct internet search (SerpEx primary, DuckDuckGo fallback)",        "has_input": True, "is_search": True},
        ],
    },
    {
        "group": "Self-Teacher & Learners",
        "icon": "🎓",
        "commands": [
            {"label": "self-teach <topic>",       "cmd": "self-teach ",    "desc": "SelfTeacher: research topic → store in niblit_memory → feed learner → reflect",  "has_input": True},
            {"label": "learn about <topic>",      "cmd": "learn about ",   "desc": "Queue a topic; ALE will research it and call SelfTeacher in Step 6",             "has_input": True},
            {"label": "ideas about <topic>",      "cmd": "ideas about ",   "desc": "Generate ideas via SelfIdeaGenerator → store in niblit_memory",                 "has_input": True},
        ],
    },
    {
        "group": "Brain & Self-Implementation",
        "icon": "🧬",
        "commands": [
            {"label": "self-idea <prompt>",       "cmd": "self-idea ",     "desc": "Generate an idea via SelfIdeaGenerator and auto-implement it",                   "has_input": True},
            {"label": "self-implement <plan>",    "cmd": "self-implement ","desc": "Enqueue an implementation plan directly to SelfImplementer",                     "has_input": True},
            {"label": "idea-implement <prompt>",  "cmd": "idea-implement ","desc": "Full pipeline: generate idea → implement → compile → store in niblit_memory",    "has_input": True},
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
            {"label": "generate code <lang>",     "cmd": "generate code ",   "desc": "Generate a complete code module (language + optional template key)",     "has_input": True},
            {"label": "run code <lang> <code>",   "cmd": "run code ",        "desc": "Execute an inline code snippet and return stdout / errors",              "has_input": True},
            {"label": "validate <lang> <code>",   "cmd": "validate ",        "desc": "Validate syntax and structure without executing",                        "has_input": True},
            {"label": "execute file <path>",      "cmd": "execute file ",    "desc": "Execute a script file and capture its output",                           "has_input": True},
            {"label": "code templates [lang]",    "cmd": "code templates",   "desc": "List all available code templates (filtered by language if given)"},
            {"label": "study language <lang>",    "cmd": "study language ",  "desc": "Fetch best practices and idioms for a programming language",             "has_input": True},
            {"label": "available languages",      "cmd": "available languages","desc": "List every language supported by CodeGenerator"},
        ],
    },
    {
        "group": "File Manager",
        "icon": "📁",
        "commands": [
            {"label": "read file <path>",              "cmd": "read file ",    "desc": "Read and display a file from the filesystem",              "has_input": True},
            {"label": "write file <path> <content>",   "cmd": "write file ",   "desc": "Write content to a file (creates if not present)",         "has_input": True},
            {"label": "list files [dir]",              "cmd": "list files",    "desc": "List directory contents (defaults to working directory)"},
            {"label": "file environment",              "cmd": "file environment","desc": "Show filesystem environment info (paths, disk, OS)"},
        ],
    },
    {
        "group": "Software Study",
        "icon": "📚",
        "commands": [
            {"label": "study software <cat>",      "cmd": "study software ",   "desc": "Deep-study a software category and store patterns in KnowledgeDB",  "has_input": True},
            {"label": "software categories",       "cmd": "software categories","desc": "List all available SoftwareStudier study categories"},
            {"label": "analyze architecture <n>",  "cmd": "analyze architecture ","desc": "Analyse a named architecture pattern and store insights",         "has_input": True},
            {"label": "design software <desc>",    "cmd": "design software ",  "desc": "Generate a software design document and persist it",                "has_input": True},
            {"label": "what have i studied",       "cmd": "what have i studied","desc": "Show all software categories studied in this session"},
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
            {"label": "my commands",              "cmd": "my commands",       "desc": "Enumerate every registered command with handler and priority"},
            {"label": "dashboard",                "cmd": "dashboard",         "desc": "Full runtime dashboard: threads, loops, memory, ALE, modules"},
            {"label": "operational flow",         "cmd": "operational flow",  "desc": "Explain how CLI routing, background loops, and memory all connect"},
            {"label": "resource usage",           "cmd": "resource usage",    "desc": "Show RAM usage, CPU percent, and process uptime"},
        ],
    },
    {
        "group": "SLSA Engine",
        "icon": "🛡️",
        "commands": [
            {"label": "slsa-status",              "cmd": "slsa-status",         "desc": "Show SLSA engine running state and last artifact built"},
            {"label": "start_slsa [topics]",      "cmd": "start_slsa",          "desc": "Start SLSA knowledge-artifact generation (optional topic list)"},
            {"label": "stop_slsa",                "cmd": "stop_slsa",           "desc": "Stop the SLSA background loop"},
            {"label": "restart_slsa [topics]",    "cmd": "restart_slsa",        "desc": "Restart SLSA with an updated topic list"},
        ],
    },
    {
        "group": "Live Update",
        "icon": "🔄",
        "commands": [
            {"label": "reload <module>",          "cmd": "reload ",        "desc": "Hot-reload a single Python module without restarting Niblit",            "has_input": True},
            {"label": "upgrade",                  "cmd": "upgrade",        "desc": "Detect and hot-reload all changed modules in one pass"},
            {"label": "update-history",           "cmd": "update-history", "desc": "Show history of hot-reloaded modules with timestamps"},
        ],
    },
    {
        "group": "Settings",
        "icon": "⚙️",
        "commands": [
            {"label": "toggle-llm on",            "cmd": "toggle-llm on",  "desc": "Enable the HuggingFace LLM adapter for AI-assisted responses"},
            {"label": "toggle-llm off",           "cmd": "toggle-llm off", "desc": "Disable the LLM adapter (research-only mode, no API calls)"},
            {"label": "shutdown",                 "cmd": "shutdown",        "desc": "Save state, stop all background threads, and exit gracefully"},
        ],
    },
    {
        "group": "Diagnostics",
        "icon": "🩺",
        "commands": [
            {"label": "run-diagnostics",          "cmd": "run-diagnostics","desc": "Execute the full Niblit diagnostic suite across all subsystems"},
            {"label": "run-live-test",            "cmd": "run-live-test",  "desc": "Run the interactive live command tester (smoke-tests all routes)"},
            {"label": "loop-errors",              "cmd": "loop-errors",    "desc": "Display all errors captured by the LoopTracer since startup"},
        ],
    },
    {
        "group": "Orchestrator",
        "icon": "🎛️",
        "commands": [
            {"label": "orchestrate audit",        "cmd": "orchestrate audit",      "desc": "Run a full repository audit (imports, wiring, missing symbols)"},
            {"label": "orchestrate self-heal",    "cmd": "orchestrate self-heal",  "desc": "Orchestrate automated self-healing across detected issues"},
            {"label": "orchestrate fix-guide",    "cmd": "orchestrate fix-guide",  "desc": "Generate a structured fix guide for all outstanding issues"},
            {"label": "orchestrate verify",       "cmd": "orchestrate verify",     "desc": "Verify all imports and inter-module dependencies"},
            {"label": "orchestrate pipeline",     "cmd": "orchestrate pipeline",   "desc": "Run the complete full-upgrade pipeline end-to-end"},
            {"label": "hf-task <prompt>",         "cmd": "hf-task ",               "desc": "Execute a HuggingFace task with the given prompt",              "has_input": True},
        ],
    },
]


# ══════════════════════════════════════════════════════════════
# DASHBOARD HTML  — modern web-browser style AI assistant
#
# Layout:  top nav-bar  |  collapsible left sidebar  |  chat panel
# On page-load the /api/boot sequence plays (same as main.py boot()),
# then Niblit is ready for interactive input — full runtime logic intact.
# ══════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Niblit AIOS — Autonomous Intelligence</title>
  <style>
    /* ── design tokens ── */
    :root{
      --bg:#0d1117;--surface:#161b22;--surface2:#21262d;--surface3:#30363d;
      --border:#30363d;--border2:#484f58;
      --primary:#58a6ff;--primary-dark:#1f6feb;--primary-glow:rgba(88,166,255,.15);
      --accent:#3fb950;--accent2:#d2a8ff;--warn:#d29922;--danger:#f85149;
      --text:#e6edf3;--text-muted:#8b949e;--text-dim:#484f58;
      --chat-user-bg:#1f6feb;--chat-ai-bg:#161b22;
      --code-bg:#0d1117;--code-text:#c9d1d9;
      --radius:8px;--radius-lg:12px;
      --font:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif;
      --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
      --sidebar-w:280px;--topbar-h:58px;
      --shadow:0 8px 24px rgba(1,4,9,.4);
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;line-height:1.5}
    a{color:var(--primary);text-decoration:none}
    ::selection{background:var(--primary-glow)}

    /* ── scrollbars ── */
    ::-webkit-scrollbar{width:5px;height:5px}
    ::-webkit-scrollbar-thumb{background:var(--surface3);border-radius:3px}
    ::-webkit-scrollbar-track{background:transparent}

    /* ══ TOPBAR ══ */
    #topbar{
      position:fixed;top:0;left:0;right:0;height:var(--topbar-h);z-index:200;
      background:rgba(13,17,23,.92);backdrop-filter:blur(12px);
      border-bottom:1px solid var(--border);
      display:flex;align-items:center;padding:0 16px;gap:12px;
    }
    #menu-btn{background:none;border:none;cursor:pointer;color:var(--text-muted);
              font-size:18px;padding:6px 8px;border-radius:6px;line-height:1;transition:color .15s,background .15s}
    #menu-btn:hover{color:var(--text);background:var(--surface2)}

    .brand{display:flex;align-items:center;gap:10px;text-decoration:none;flex-shrink:0}
    .brand-logo{
      width:34px;height:34px;border-radius:8px;flex-shrink:0;
      background:linear-gradient(135deg,#1f6feb 0%,#388bfd 50%,#3fb950 100%);
      display:flex;align-items:center;justify-content:center;
      color:#fff;font-weight:800;font-size:15px;letter-spacing:-.5px;
      box-shadow:0 0 12px rgba(88,166,255,.4);
    }
    .brand-name{font-size:16px;font-weight:700;color:var(--text);letter-spacing:-.4px}
    .brand-version{font-size:10px;color:var(--text-muted);background:var(--surface2);
                   padding:1px 6px;border-radius:10px;border:1px solid var(--border);margin-left:4px}

    #topbar-search{
      flex:1;max-width:440px;margin:0 auto;position:relative;
    }
    #top-search{
      width:100%;background:var(--surface2);border:1px solid var(--border);
      border-radius:8px;padding:7px 14px 7px 36px;font-size:13px;
      color:var(--text);outline:none;font-family:var(--font);
      transition:border-color .15s,box-shadow .15s;
    }
    #top-search:focus{border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-glow)}
    #top-search::placeholder{color:var(--text-muted)}
    .search-icon{position:absolute;left:10px;top:50%;transform:translateY(-50%);
                 color:var(--text-muted);font-size:14px;pointer-events:none}

    #topbar-right{display:flex;align-items:center;gap:8px;margin-left:auto;flex-shrink:0}
    #status-pill{
      display:flex;align-items:center;gap:6px;padding:5px 12px;
      border-radius:20px;font-size:12px;font-weight:600;cursor:default;
      background:rgba(63,185,80,.1);color:var(--accent);border:1px solid rgba(63,185,80,.25);
    }
    #status-pill.degraded{background:rgba(210,153,34,.1);color:var(--warn);border-color:rgba(210,153,34,.25)}
    #status-pill.offline{background:rgba(248,81,73,.1);color:var(--danger);border-color:rgba(248,81,73,.25)}
    #status-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex-shrink:0;
                box-shadow:0 0 6px var(--accent)}
    #status-pill.degraded #status-dot{background:var(--warn);box-shadow:0 0 6px var(--warn)}
    #status-pill.offline #status-dot{background:var(--danger);box-shadow:0 0 6px var(--danger)}
    .hdr-btn{
      background:var(--surface2);border:1px solid var(--border);color:var(--text-muted);
      padding:6px 12px;border-radius:7px;cursor:pointer;font-size:12px;font-weight:500;
      display:flex;align-items:center;gap:5px;transition:all .15s;white-space:nowrap;
    }
    .hdr-btn:hover{border-color:var(--primary);color:var(--primary);background:var(--primary-glow)}

    /* ══ LAYOUT ══ */
    #layout{display:flex;height:100vh;padding-top:var(--topbar-h)}

    /* ══ SIDEBAR ══ */
    #sidebar{
      width:var(--sidebar-w);background:var(--surface);
      border-right:1px solid var(--border);
      display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;
      transition:width .22s cubic-bezier(.4,0,.2,1);
    }
    #sidebar.collapsed{width:0}
    #sidebar-inner{width:var(--sidebar-w);overflow-y:auto;height:100%;padding-bottom:16px}

    .sb-header{
      padding:16px;border-bottom:1px solid var(--border);
      display:flex;align-items:center;justify-content:space-between;
    }
    .sb-header-title{font-size:11px;font-weight:700;letter-spacing:.08em;
                     text-transform:uppercase;color:var(--text-muted)}
    .sb-count{font-size:11px;color:var(--text-dim);background:var(--surface2);
              padding:2px 7px;border-radius:10px}

    .sb-group{margin:4px 8px}
    .sb-toggle{
      width:100%;background:none;border:none;color:var(--text-muted);
      padding:7px 8px;text-align:left;cursor:pointer;font-size:12.5px;font-weight:600;
      display:flex;align-items:center;gap:8px;border-radius:var(--radius);
      transition:background .12s,color .12s;
    }
    .sb-toggle:hover{background:var(--surface2);color:var(--text)}
    .sb-toggle.open{color:var(--text)}
    .g-icon{font-size:14px;flex-shrink:0;width:18px;text-align:center}
    .g-name{flex:1}
    .g-arr{font-size:10px;opacity:.5;transition:transform .2s;transform:rotate(0)}
    .sb-toggle.open .g-arr{transform:rotate(90deg)}
    .g-cnt{font-size:10px;color:var(--text-dim);background:var(--surface2);
           padding:1px 5px;border-radius:8px;margin-left:auto;margin-right:4px}
    .sb-list{display:none;margin:2px 0 4px 8px}
    .sb-list.vis{display:block}
    .sb-cmd{
      padding:5px 10px;color:var(--text-muted);cursor:pointer;
      font-size:12px;border-radius:6px;
      display:flex;flex-direction:column;gap:1px;
      transition:background .1s,color .1s;
      border:1px solid transparent;
    }
    .sb-cmd:hover{background:var(--surface2);color:var(--text);border-color:var(--border)}
    .sb-cmd .c-label{font-family:var(--mono);font-size:11.5px;color:var(--primary)}
    .sb-cmd:hover .c-label{color:var(--accent)}
    .sb-cmd .c-desc{font-size:10px;color:var(--text-dim);white-space:nowrap;
                    overflow:hidden;text-overflow:ellipsis}

    /* ══ MAIN ══ */
    #main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}

    /* ══ CHAT FEED ══ */
    #chat-feed{flex:1;overflow-y:auto;padding:20px 0;display:flex;flex-direction:column;gap:0}

    /* welcome card */
    #welcome{max-width:720px;margin:0 auto 16px;padding:0 20px;width:100%}
    .welcome-card{
      background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
      padding:20px 24px;display:flex;gap:16px;align-items:flex-start;
    }
    .welcome-icon{
      width:44px;height:44px;border-radius:10px;flex-shrink:0;
      background:linear-gradient(135deg,#1f6feb,#3fb950);
      display:flex;align-items:center;justify-content:center;
      font-size:22px;
    }
    .welcome-body h2{font-size:16px;font-weight:700;color:var(--text);margin-bottom:4px}
    .welcome-body p{font-size:13px;color:var(--text-muted);line-height:1.6}

    /* boot sequence */
    #boot-area{max-width:720px;margin:0 auto 8px;padding:0 20px;width:100%}
    .boot-block{
      background:var(--code-bg);border:1px solid var(--border);border-radius:var(--radius);
      padding:14px 18px;font-family:var(--mono);font-size:12px;line-height:1.75;
      border-left:3px solid var(--accent);
    }
    .bl-ok{color:var(--accent)} .bl-warn{color:var(--warn)} .bl-dim{color:var(--text-muted)}
    .bl-err{color:var(--danger)} .bl-hdr{color:var(--primary);font-weight:700}

    /* messages */
    .msg-row{max-width:780px;margin:0 auto;padding:6px 20px;width:100%;display:flex;gap:12px}
    .msg-row.from-user{flex-direction:row-reverse}
    .msg-av{
      width:32px;height:32px;border-radius:50%;flex-shrink:0;font-size:13px;font-weight:700;
      display:flex;align-items:center;justify-content:center;
    }
    .msg-av.ai{background:linear-gradient(135deg,#1f6feb,#3fb950);color:#fff;letter-spacing:-.3px}
    .msg-av.user{background:var(--surface3);color:var(--text);font-size:15px}
    .msg-body{flex:1;min-width:0}
    .msg-meta{font-size:11px;color:var(--text-muted);margin-bottom:4px;display:flex;gap:8px;align-items:center}
    .from-user .msg-meta{justify-content:flex-end}
    .meta-name{font-weight:600}
    .meta-cmd{
      font-family:var(--mono);font-size:10px;background:var(--surface2);
      padding:1px 6px;border-radius:4px;color:var(--accent2);border:1px solid var(--border);
    }
    .msg-bubble{
      background:var(--surface);border:1px solid var(--border);
      border-radius:12px;padding:12px 16px;font-size:13.5px;line-height:1.75;
      white-space:pre-wrap;word-break:break-word;
    }
    .from-user .msg-bubble{
      background:var(--chat-user-bg);color:#fff;border-color:transparent;
      border-bottom-right-radius:4px;
    }
    .msg-bubble.err{background:rgba(248,81,73,.08);border-color:rgba(248,81,73,.3);color:var(--danger)}
    .msg-bubble code{
      background:var(--code-bg);color:var(--code-text);
      padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px;
    }
    .msg-bubble pre{
      background:var(--code-bg);color:var(--code-text);
      border-radius:8px;padding:14px 16px;margin:8px 0 0;overflow-x:auto;
      font-family:var(--mono);font-size:12px;line-height:1.6;
      border:1px solid var(--border);
    }
    .msg-suggestion{font-size:12px;color:var(--accent2);margin-top:6px;font-style:italic}
    .msg-debug{font-size:11px;color:var(--text-muted);font-family:var(--mono);
               padding:4px 0 0;display:flex;flex-direction:column;gap:1px}

    /* thinking */
    #thinking-row{max-width:780px;margin:0 auto;padding:4px 20px;
                  display:none;align-items:center;gap:12px;width:100%}
    .thinking-dots{display:flex;gap:5px;padding:10px 0}
    .thinking-dots span{
      width:8px;height:8px;border-radius:50%;background:var(--primary);
      animation:tdot .9s ease-in-out infinite;
    }
    .thinking-dots span:nth-child(2){animation-delay:.2s}
    .thinking-dots span:nth-child(3){animation-delay:.4s}
    @keyframes tdot{0%,100%{transform:translateY(0);opacity:.3}50%{transform:translateY(-5px);opacity:1}}

    /* ══ HOW IT WORKS PANEL ══ */
    #how-panel{
      max-width:780px;margin:0 auto 12px;padding:0 20px;width:100%;
    }
    .how-card{
      background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
      overflow:hidden;
    }
    .how-toggle{
      width:100%;background:none;border:none;color:var(--text);padding:14px 18px;
      text-align:left;cursor:pointer;font-size:13px;font-weight:600;
      display:flex;align-items:center;gap:10px;transition:background .15s;
    }
    .how-toggle:hover{background:var(--surface2)}
    .how-body{display:none;padding:0 18px 16px;border-top:1px solid var(--border)}
    .how-body.open{display:block}
    .how-flow{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
    .flow-step{
      background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);
      padding:10px 14px;font-size:12px;flex:1;min-width:150px;position:relative;
    }
    .flow-step::after{
      content:'→';position:absolute;right:-14px;top:50%;transform:translateY(-50%);
      color:var(--text-dim);font-size:14px;
    }
    .flow-step:last-child::after{display:none}
    .flow-step .fs-title{font-weight:700;color:var(--primary);margin-bottom:3px;font-size:11.5px}
    .flow-step .fs-desc{color:var(--text-muted);font-size:11px}
    .how-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-top:10px}
    .how-feat{
      background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);
      padding:10px 12px;
    }
    .hf-title{font-size:12px;font-weight:600;color:var(--text);margin-bottom:3px;display:flex;gap:6px;align-items:center}
    .hf-desc{font-size:11px;color:var(--text-muted)}

    /* ══ QUICK CHIPS ══ */
    #chips-bar{max-width:780px;margin:0 auto;padding:0 20px 8px;
               display:flex;flex-wrap:wrap;gap:6px}
    .chip{
      padding:5px 12px;border-radius:20px;font-size:12px;font-weight:500;
      border:1px solid var(--border);background:var(--surface2);
      color:var(--text-muted);cursor:pointer;transition:all .12s;white-space:nowrap;
    }
    .chip:hover{border-color:var(--primary);color:var(--primary);background:var(--primary-glow)}
    .chip.accent{border-color:rgba(63,185,80,.3);color:var(--accent)}
    .chip.accent:hover{background:rgba(63,185,80,.1)}

    /* ══ INPUT BAR ══ */
    #input-bar{
      background:var(--surface);border-top:1px solid var(--border);
      padding:12px 20px 14px;display:flex;align-items:flex-end;gap:10px;
      max-width:780px;width:100%;margin:0 auto;align-self:center;
    }
    #chat-input{
      flex:1;background:var(--surface2);border:1.5px solid var(--border);
      border-radius:10px;padding:10px 14px;font-size:13.5px;font-family:var(--font);
      color:var(--text);outline:none;resize:none;min-height:44px;max-height:140px;
      line-height:1.55;transition:border-color .15s,box-shadow .15s;
    }
    #chat-input:focus{border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-glow)}
    #chat-input::placeholder{color:var(--text-muted)}
    #send-btn{
      background:var(--primary-dark);color:#fff;border:none;border-radius:10px;
      padding:10px 22px;cursor:pointer;font-size:14px;font-weight:600;
      font-family:var(--font);white-space:nowrap;align-self:flex-end;min-height:44px;
      transition:background .15s,box-shadow .15s;
    }
    #send-btn:hover:not(:disabled){background:var(--primary);box-shadow:0 0 12px var(--primary-glow)}
    #send-btn:disabled{opacity:.35;cursor:not-allowed}
    .input-hint{
      max-width:780px;margin:0 auto;padding:0 20px 8px;
      font-size:11px;color:var(--text-dim);text-align:center;
    }
    .input-hint a{color:var(--primary);cursor:pointer}

    /* ══ COMMAND PALETTE OVERLAY ══ */
    #palette-overlay{
      display:none;position:fixed;inset:0;z-index:500;
      background:rgba(1,4,9,.7);backdrop-filter:blur(4px);
      align-items:flex-start;justify-content:center;padding-top:80px;
    }
    #palette-overlay.open{display:flex}
    #palette{
      width:90%;max-width:580px;background:var(--surface);
      border:1px solid var(--border2);border-radius:var(--radius-lg);
      box-shadow:var(--shadow);overflow:hidden;
    }
    #palette-input{
      width:100%;background:transparent;border:none;border-bottom:1px solid var(--border);
      padding:14px 18px;font-size:15px;color:var(--text);outline:none;font-family:var(--font);
    }
    #palette-input::placeholder{color:var(--text-muted)}
    #palette-results{max-height:380px;overflow-y:auto}
    .pal-item{
      padding:10px 18px;cursor:pointer;border-bottom:1px solid var(--border);
      display:flex;align-items:center;gap:12px;transition:background .1s;
    }
    .pal-item:hover,.pal-item.active{background:var(--surface2)}
    .pal-item:last-child{border-bottom:none}
    .pal-icon{font-size:16px;flex-shrink:0;width:22px;text-align:center}
    .pal-info{flex:1;min-width:0}
    .pal-cmd{font-family:var(--mono);font-size:12.5px;color:var(--primary);font-weight:600}
    .pal-desc{font-size:11px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .pal-group{font-size:10px;color:var(--text-dim);flex-shrink:0;background:var(--surface2);
               padding:2px 7px;border-radius:8px}
    .pal-hint{padding:10px 18px;font-size:11px;color:var(--text-muted);text-align:center}
    #palette-kbd{padding:8px 18px;border-top:1px solid var(--border);
                 font-size:11px;color:var(--text-dim);display:flex;gap:14px}
    kbd{background:var(--surface2);border:1px solid var(--border);border-radius:4px;
        padding:1px 5px;font-size:10px;font-family:var(--mono)}

    /* ══ MOBILE ══ */
    @media(max-width:720px){
      :root{--sidebar-w:260px}
      #sidebar{position:fixed;top:var(--topbar-h);left:0;bottom:0;z-index:150;width:0!important}
      #sidebar.mob-open{width:var(--sidebar-w)!important}
      #topbar-search{display:none}
      #how-panel,#welcome{padding:0 12px}
      #input-bar{padding:10px 12px 12px}
      #chips-bar{padding:0 12px 8px}
    }

    /* ══ BACKGROUND STATUS PANEL ══ */
    #bg-panel{
      position:fixed;bottom:16px;right:16px;z-index:300;
      background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
      min-width:240px;max-width:320px;box-shadow:var(--shadow);
      font-size:11px;overflow:hidden;
    }
    #bg-panel-toggle{
      width:100%;background:none;border:none;padding:8px 12px;
      display:flex;align-items:center;gap:8px;cursor:pointer;
      color:var(--text-muted);font-size:11px;font-family:var(--font);
    }
    #bg-panel-toggle:hover{background:var(--surface2)}
    #bg-panel-body{display:none;padding:8px 12px 10px;border-top:1px solid var(--border)}
    #bg-panel-body.open{display:block}
    .bp-row{display:flex;justify-content:space-between;gap:8px;margin-bottom:4px;align-items:baseline}
    .bp-key{color:var(--text-muted)}
    .bp-val{color:var(--text);font-family:var(--mono);font-size:10.5px;text-align:right;max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .bp-val.on{color:var(--accent)}
    .bp-val.off{color:var(--text-dim)}
    #bg-pulse{width:7px;height:7px;border-radius:50%;background:var(--accent);flex-shrink:0;box-shadow:0 0 6px var(--accent);animation:pulse 2s ease-in-out infinite}
    #bg-pulse.off{background:var(--text-dim);box-shadow:none;animation:none}
    @keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}
  </style>
</head>
<body>

<!-- ══ TOPBAR ══ -->
<div id="topbar">
  <button id="menu-btn" onclick="toggleSidebar()" title="Toggle sidebar (⌘B)">☰</button>
  <a class="brand" href="#">
    <div class="brand-logo">N</div>
    <span class="brand-name">Niblit AIOS</span>
    <span class="brand-version">v2</span>
  </a>
  <div id="topbar-search">
    <span class="search-icon">🔍</span>
    <input id="top-search" type="text" placeholder="Search the web via Niblit… (Enter to send)" autocomplete="off"/>
  </div>
  <div id="topbar-right">
    <div id="status-pill" title="System status">
      <span id="status-dot"></span>
      <span id="status-txt">booting…</span>
    </div>
    <button class="hdr-btn" onclick="openPalette()" title="Command palette (⌘K)">⌘K Commands</button>
    <button class="hdr-btn" onclick="sendText('help')" title="Help">? Help</button>
  </div>
</div>

<!-- ══ COMMAND PALETTE ══ -->
<div id="palette-overlay" onclick="if(event.target===this)closePalette()">
  <div id="palette">
    <input id="palette-input" placeholder="Search commands…" autocomplete="off" spellcheck="false"/>
    <div id="palette-results"></div>
    <div id="palette-kbd">
      <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
      <span><kbd>Enter</kbd> run command</span>
      <span><kbd>Esc</kbd> close</span>
    </div>
  </div>
</div>

<!-- ══ LAYOUT ══ -->
<div id="layout">

  <!-- ══ SIDEBAR ══ -->
  <nav id="sidebar">
    <div id="sidebar-inner">
      <div class="sb-header">
        <span class="sb-header-title">Commands</span>
        <span class="sb-count" id="sb-total">0 total</span>
      </div>
      <!-- populated by JS -->
    </div>
  </nav>

  <!-- ══ MAIN ══ -->
  <div id="main">
    <div id="chat-feed">

      <!-- welcome -->
      <div id="welcome">
        <div class="welcome-card">
          <div class="welcome-icon">🤖</div>
          <div class="welcome-body">
            <h2>Welcome to Niblit AIOS</h2>
            <p>An autonomous AI system with a 28-step learning engine, semantic memory, vector search,
               code generation, self-improvement, and real-time research. Type any command or question below,
               or press <strong>⌘K</strong> to open the command palette.</p>
          </div>
        </div>
      </div>

      <!-- boot area -->
      <div id="boot-area"></div>

      <!-- messages -->

    </div><!-- /chat-feed -->

    <!-- thinking indicator -->
    <div id="thinking-row">
      <div class="msg-av ai">N</div>
      <div class="thinking-dots"><span></span><span></span><span></span></div>
    </div>

    <!-- how it works -->
    <div id="how-panel">
      <div class="how-card">
        <button class="how-toggle" onclick="toggleHow(this)">
          <span>⚡</span> How Niblit Chat Works <span style="margin-left:auto;font-size:11px;color:var(--text-muted);font-weight:400">click to expand</span>
        </button>
        <div class="how-body" id="how-body">
          <div class="how-flow">
            <div class="flow-step">
              <div class="fs-title">1 · Input</div>
              <div class="fs-desc">You type a command or question</div>
            </div>
            <div class="flow-step">
              <div class="fs-title">2 · Router</div>
              <div class="fs-desc">NiblitRouter pattern-matches the command prefix</div>
            </div>
            <div class="flow-step">
              <div class="fs-title">3 · Handler</div>
              <div class="fs-desc">Dedicated handler executes (ALE, Research, Code…)</div>
            </div>
            <div class="flow-step">
              <div class="fs-title">4 · Core</div>
              <div class="fs-desc">NiblitCore falls back for general chat via LLM</div>
            </div>
            <div class="flow-step">
              <div class="fs-title">5 · Memory</div>
              <div class="fs-desc">Reply stored in KnowledgeDB + Qdrant vector store</div>
            </div>
          </div>
          <div class="how-grid" id="feat-grid">
            <div class="how-feat"><div class="hf-title">🤖 ALE (28 steps)</div><div class="hf-desc">Autonomous learning engine that runs continuously in the background, cycling through research, code generation, reflection, and evolution.</div></div>
            <div class="how-feat"><div class="hf-title">🔍 Research Pipeline</div><div class="hf-desc">Serpex → Searchcode → ResearcherEngine → Internet fallback. All results are ingested into KnowledgeDB and Qdrant.</div></div>
            <div class="how-feat"><div class="hf-title">🧩 Dynamic Topics</div><div class="hf-desc">DynamicTopicManager uses hybrid enrichment (semantic + BM25 + KB mining) to keep ALE exploring fresh topics every 10 minutes.</div></div>
            <div class="how-feat"><div class="hf-title">🧠 Vector Memory</div><div class="hf-desc">FusedMemory combines SQLite facts with Qdrant dense-vector search. All knowledge is semantically queryable.</div></div>
            <div class="how-feat"><div class="hf-title">💻 Code Generation</div><div class="hf-desc">LLM-powered code generator with context from the vector store. Supports Python, JS, Go, Rust, and 20+ languages.</div></div>
            <div class="how-feat"><div class="hf-title">⚡ Self-Improvement</div><div class="hf-desc">10-module improvement engine runs every 3 cycles. EvolveEngine continuously updates the codebase.</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- quick chips -->
    <div id="chips-bar">
      <span class="chip" onclick="sendText('status')">⚡ status</span>
      <span class="chip" onclick="sendText('autonomous-learn status')">🤖 ale status</span>
      <span class="chip" onclick="sendText('auto-research status')">🔭 research</span>
      <span class="chip" onclick="sendText('refresh-topics')">🧩 refresh topics</span>
      <span class="chip" onclick="sendText('knowledge stats')">🧠 kb stats</span>
      <span class="chip" onclick="sendText('evolve status')">🌱 evolve</span>
      <span class="chip accent" onclick="openPalette()">⌘K all commands</span>
    </div>

    <!-- input bar -->
    <div id="input-bar">
      <textarea id="chat-input" rows="1" placeholder="Type a command (e.g. 'status', 'search neural networks') or ask anything…" autocomplete="off" spellcheck="false"></textarea>
      <button id="send-btn" onclick="sendChat()">Send ↵</button>
    </div>
    <div class="input-hint">
      Enter to send · Shift+Enter for new line ·
      <a onclick="openPalette()">⌘K command palette</a> ·
      <a onclick="sendText('help')">view all commands</a>
    </div>

  </div><!-- /main -->
</div><!-- /layout -->

<script>
'use strict';
// ════════════════════════════════════════════════════════
// DATA
// ════════════════════════════════════════════════════════
const GROUPS = __JSON_GROUPS__;
const NIBLIT_KEY = __API_KEY__;
const ALL_CMDS = [];
GROUPS.forEach(g => g.commands.forEach(c => ALL_CMDS.push({...c, group:g.group, icon:g.icon})));

// ════════════════════════════════════════════════════════
// SIDEBAR
// ════════════════════════════════════════════════════════
(function buildSidebar(){
  const inner = document.getElementById('sidebar-inner');
  let total = 0;
  GROUPS.forEach((g, gi) => {
    total += g.commands.length;
    const wrap = document.createElement('div');
    wrap.className = 'sb-group';

    const tog = document.createElement('button');
    tog.className = 'sb-toggle' + (gi < 4 ? ' open' : '');
    tog.innerHTML = `<span class="g-icon">${g.icon}</span><span class="g-name">${g.group}</span>`
                  + `<span class="g-cnt">${g.commands.length}</span><span class="g-arr">▶</span>`;

    const lst = document.createElement('div');
    lst.className = 'sb-list' + (gi < 4 ? ' vis' : '');

    tog.onclick = () => { tog.classList.toggle('open'); lst.classList.toggle('vis'); };

    g.commands.forEach(c => {
      const item = document.createElement('div');
      item.className = 'sb-cmd';
      item.innerHTML = `<div class="c-label">${c.label}</div><div class="c-desc">${c.desc}</div>`;
      item.onclick = () => {
        if(c.is_search){ document.getElementById('top-search').focus(); return; }
        if(c.has_input){
          const ta = document.getElementById('chat-input');
          ta.value = c.cmd; ta.focus(); autoResize(ta);
        } else {
          sendText(c.cmd);
        }
        if(window.innerWidth <= 720) document.getElementById('sidebar').classList.remove('mob-open');
      };
      lst.appendChild(item);
    });

    wrap.appendChild(tog); wrap.appendChild(lst);
    inner.appendChild(wrap);
  });
  document.getElementById('sb-total').textContent = total + ' total';
})();

// ════════════════════════════════════════════════════════
// SIDEBAR TOGGLE
// ════════════════════════════════════════════════════════
function toggleSidebar(){
  const sb = document.getElementById('sidebar');
  if(window.innerWidth <= 720) sb.classList.toggle('mob-open');
  else sb.classList.toggle('collapsed');
}

// ════════════════════════════════════════════════════════
// COMMAND PALETTE
// ════════════════════════════════════════════════════════
let palActive = -1;

function openPalette(){
  document.getElementById('palette-overlay').classList.add('open');
  const pi = document.getElementById('palette-input');
  pi.value = ''; pi.focus();
  renderPalette('');
  palActive = -1;
}
function closePalette(){
  document.getElementById('palette-overlay').classList.remove('open');
}
function renderPalette(q){
  const res = document.getElementById('palette-results');
  res.innerHTML = '';
  const lower = q.toLowerCase();
  const matches = q
    ? ALL_CMDS.filter(c =>
        c.label.toLowerCase().includes(lower) ||
        c.desc.toLowerCase().includes(lower) ||
        c.group.toLowerCase().includes(lower))
    : ALL_CMDS.slice(0, 20);

  if(!matches.length){
    res.innerHTML = `<div class="pal-hint">No commands match "${q}"</div>`;
    return;
  }
  matches.slice(0, 25).forEach((c, i) => {
    const item = document.createElement('div');
    item.className = 'pal-item' + (i === palActive ? ' active' : '');
    item.innerHTML = `<span class="pal-icon">${c.icon}</span>`
      + `<div class="pal-info"><div class="pal-cmd">${c.label}</div><div class="pal-desc">${c.desc}</div></div>`
      + `<span class="pal-group">${c.group}</span>`;
    item.onclick = () => { runPaletteItem(c); };
    res.appendChild(item);
  });
}
function runPaletteItem(c){
  closePalette();
  if(c.is_search){ document.getElementById('top-search').focus(); return; }
  if(c.has_input){
    const ta = document.getElementById('chat-input');
    ta.value = c.cmd; ta.focus(); autoResize(ta);
  } else {
    sendText(c.cmd);
  }
}
document.getElementById('palette-input').addEventListener('input', e => {
  palActive = -1;
  renderPalette(e.target.value.trim());
});
document.getElementById('palette-input').addEventListener('keydown', e => {
  const items = document.querySelectorAll('.pal-item');
  if(e.key === 'ArrowDown'){ e.preventDefault(); palActive = Math.min(palActive+1, items.length-1); items.forEach((el,i)=>el.classList.toggle('active',i===palActive)); }
  else if(e.key === 'ArrowUp'){ e.preventDefault(); palActive = Math.max(palActive-1, 0); items.forEach((el,i)=>el.classList.toggle('active',i===palActive)); }
  else if(e.key === 'Enter'){
    e.preventDefault();
    const active = document.querySelector('.pal-item.active');
    if(active) active.click();
    else {
      const q = e.target.value.trim();
      if(q){ closePalette(); sendText(q); }
    }
  }
  else if(e.key === 'Escape') closePalette();
});
document.addEventListener('keydown', e => {
  if((e.metaKey || e.ctrlKey) && e.key === 'k'){ e.preventDefault(); openPalette(); }
  if(e.key === 'Escape' && document.getElementById('palette-overlay').classList.contains('open')) closePalette();
});

// ════════════════════════════════════════════════════════
// HOW IT WORKS TOGGLE
// ════════════════════════════════════════════════════════
function toggleHow(btn){
  const body = document.getElementById('how-body');
  body.classList.toggle('open');
  const lbl = btn.querySelector('span:last-child');
  lbl.textContent = body.classList.contains('open') ? 'click to collapse' : 'click to expand';
}

// ════════════════════════════════════════════════════════
// TOP SEARCH
// ════════════════════════════════════════════════════════
document.getElementById('top-search').addEventListener('keydown', e => {
  if(e.key === 'Enter'){
    e.preventDefault();
    const q = e.target.value.trim();
    if(q){ e.target.value = ''; sendText('search ' + q); }
  }
});

// ════════════════════════════════════════════════════════
// BOOT SEQUENCE
// ════════════════════════════════════════════════════════
async function runBoot(){
  const bootArea = document.getElementById('boot-area');
  setStatus('booting…', '');
  const block = document.createElement('div');
  block.className = 'boot-block';
  block.innerHTML = '<span class="bl-hdr">▶ Niblit AIOS — Autonomous Intelligence Runtime</span>\n';
  bootArea.appendChild(block);
  setThinking(true);
  try {
    const r = await fetch('/api/boot');
    const j = await r.json();
    (j.messages || []).forEach(m => {
      const cls = m.includes('[DEBUG]') ? 'bl-dim' : m.includes('[WARN]') ? 'bl-warn' : m.includes('[ERR]') ? 'bl-err' : 'bl-ok';
      block.innerHTML += `<span class="${cls}">${escHtml(m)}</span>\n`;
    });
    setStatus(j.ready ? 'online' : 'degraded', j.ready ? '' : 'degraded');
  } catch(ex){
    block.innerHTML += `<span class="bl-err">[boot error] ${escHtml(ex.message)}</span>\n`;
    setStatus('offline', 'offline');
  } finally {
    setThinking(false);
    document.getElementById('chat-input').focus();
  }
}

// ════════════════════════════════════════════════════════
// STATUS
// ════════════════════════════════════════════════════════
function setStatus(label, state){
  const pill = document.getElementById('status-pill');
  document.getElementById('status-txt').textContent = label;
  pill.className = state ? 'status-pill ' + state : 'status-pill';
  pill.id = 'status-pill';
}
async function pollStatus(){
  try {
    const r = await fetch('/ping');
    const j = await r.json();
    const mood = j.personality && j.personality.mood ? ' · ' + j.personality.mood : '';
    setStatus(j.status === 'ok' ? 'online' + mood : j.status || 'degraded',
              j.status === 'ok' ? '' : 'degraded');
  } catch(_){ setStatus('offline', 'offline'); }
}
setInterval(pollStatus, 12000);

// ════════════════════════════════════════════════════════
// CHAT
// ════════════════════════════════════════════════════════
const feed = document.getElementById('chat-feed');

function escHtml(t){ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function renderMd(text){
  let s = escHtml(text);
  s = s.replace(/```([^`]*?)```/gs, (_,c) => `<pre><code>${c}</code></pre>`);
  s = s.replace(/`([^`\n]+?)`/g, (_,c) => `<code>${c}</code>`);
  return s;
}

function fmtTime(){ return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); }

function detectCmdType(text){
  const lower = text.toLowerCase();
  const cmd = ALL_CMDS.find(c => lower.startsWith(c.cmd.toLowerCase().trim()));
  return cmd ? cmd.group : null;
}

function addMsg(who, text, debugLines, suggestion, cmdHint){
  const isUser = who === 'user';
  const isErr  = who === 'err';
  const row = document.createElement('div');
  row.className = 'msg-row' + (isUser ? ' from-user' : '');
  const av = document.createElement('div');
  av.className = 'msg-av ' + (isUser ? 'user' : 'ai');
  av.textContent = isUser ? '👤' : 'N';
  const body = document.createElement('div');
  body.className = 'msg-body';
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.innerHTML = `<span class="meta-name">${isUser?'You':'Niblit'}</span><span>${fmtTime()}</span>`
    + (cmdHint ? `<span class="meta-cmd">${escHtml(cmdHint)}</span>` : '');
  body.appendChild(meta);
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble' + (isErr ? ' err' : '');
  bubble.innerHTML = isUser ? escHtml(text) : renderMd(text);
  body.appendChild(bubble);
  if(debugLines && debugLines.length){
    const d = document.createElement('div');
    d.className = 'msg-debug';
    debugLines.forEach(l => { const s=document.createElement('span'); s.textContent=l; d.appendChild(s); });
    body.appendChild(d);
  }
  if(suggestion){
    const s = document.createElement('div');
    s.className = 'msg-suggestion'; s.textContent = suggestion;
    body.appendChild(s);
  }
  if(isUser){ row.appendChild(body); row.appendChild(av); }
  else       { row.appendChild(av);  row.appendChild(body); }
  feed.appendChild(row);
  feed.scrollTop = feed.scrollHeight;
}

// ════════════════════════════════════════════════════════
// THINKING
// ════════════════════════════════════════════════════════
function setThinking(on){
  document.getElementById('thinking-row').style.display = on ? 'flex' : 'none';
  document.getElementById('send-btn').disabled = on;
  // DO NOT disable chat-input — user must always be able to type
  if(on){ const f=document.getElementById('chat-feed'); if(f.scrollTop+f.clientHeight >= f.scrollHeight-50) f.scrollTop=f.scrollHeight; }
}

// ════════════════════════════════════════════════════════
// INPUT
// ════════════════════════════════════════════════════════
function autoResize(el){
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}
const chatInput = document.getElementById('chat-input');
chatInput.addEventListener('input', function(){ autoResize(this); });
chatInput.addEventListener('keydown', function(e){
  if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); sendChat(); }
});

function sendChat(){
  const text = chatInput.value.trim();
  if(!text) return;
  chatInput.value = ''; autoResize(chatInput);
  sendText(text);
}

async function sendText(text){
  const feed = document.getElementById('chat-feed');
  const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 60;
  const group = detectCmdType(text);
  addMsg('user', text, [], null, group);
  setThinking(true);
  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', ...(NIBLIT_KEY ? {'X-API-Key': NIBLIT_KEY} : {})},
      body: JSON.stringify({text})
    });
    const j = await resp.json();
    if(j.error) addMsg('err', j.error);
    else addMsg('niblit', j.reply || '[no reply]', j.debug_lines || [], j.suggestion || null);
    if(atBottom) feed.scrollTop = feed.scrollHeight;
  } catch(ex){
    addMsg('err', 'Network error: ' + ex.message);
  } finally {
    setThinking(false);
    // Always re-focus input WITHOUT scrolling the page if user scrolled away
    chatInput.focus({preventScroll: true});
  }
}

// ════════════════════════════════════════════════════════
// BACKGROUND STATUS PANEL — silent polling, never interrupts chat
// ════════════════════════════════════════════════════════
function toggleBgPanel(){
  const body = document.getElementById('bg-panel-body');
  const arr = document.querySelector('#bg-panel-toggle span:last-child');
  body.classList.toggle('open');
  if(arr) arr.textContent = body.classList.contains('open') ? '▼' : '▲';
}

async function refreshBgStatus(){
  try {
    const r = await fetch('/api/bg_status');
    const j = await r.json();
    const ale = j.ale;
    const pulse = document.getElementById('bg-pulse');
    const label = document.getElementById('bg-label');
    if(ale){
      const running = ale.running;
      pulse.className = running ? '' : 'off';
      label.textContent = running
        ? `ALE: cycle #${ale.cycle} — ${ale.topic || 'idle'}`
        : 'ALE: stopped';
      document.getElementById('bp-ale-running').textContent = running ? '✅ yes' : '⏹ no';
      document.getElementById('bp-ale-running').className = 'bp-val ' + (running ? 'on' : 'off');
      document.getElementById('bp-cycle').textContent = '#' + (ale.cycle || 0);
      document.getElementById('bp-topic').textContent = ale.topic || '—';
    } else {
      pulse.className = 'off';
      label.textContent = 'ALE: not init';
    }
    document.getElementById('bp-threads').textContent = j.threads || '—';
    const dtm = j.dtm;
    if(dtm){
      document.getElementById('bp-dtm').textContent = dtm.thread_alive ? `✅ ${dtm.seeds} seeds` : '⏹ inactive';
    }
  } catch(_){}
}
setInterval(refreshBgStatus, 15000);
setTimeout(refreshBgStatus, 3000);

// ════════════════════════════════════════════════════════
// INIT
// ════════════════════════════════════════════════════════
runBoot();
</script>
<!-- ══ BACKGROUND STATUS PANEL ══ -->
<div id="bg-panel">
  <button id="bg-panel-toggle" onclick="toggleBgPanel()">
    <span id="bg-pulse"></span>
    <span id="bg-label">ALE: loading…</span>
    <span style="margin-left:auto;font-size:10px;opacity:.5">▲</span>
  </button>
  <div id="bg-panel-body">
    <div class="bp-row"><span class="bp-key">ALE running</span><span class="bp-val" id="bp-ale-running">—</span></div>
    <div class="bp-row"><span class="bp-key">Cycle</span><span class="bp-val" id="bp-cycle">—</span></div>
    <div class="bp-row"><span class="bp-key">Topic</span><span class="bp-val" id="bp-topic">—</span></div>
    <div class="bp-row"><span class="bp-key">Threads</span><span class="bp-val" id="bp-threads">—</span></div>
    <div class="bp-row"><span class="bp-key">Topic refresh</span><span class="bp-val" id="bp-dtm">—</span></div>
  </div>
</div>

</body>
</html>
"""


def _build_dashboard():
    """Inject Python-side data (COMMAND_GROUPS, API_KEY) into the dashboard HTML template."""
    groups_json = _json.dumps(COMMAND_GROUPS)
    api_key_json = _json.dumps(API_KEY or "")
    return (
        DASHBOARD_HTML
        .replace("__JSON_GROUPS__", groups_json)
        .replace("__API_KEY__", api_key_json)
    )
# FLASK ROUTES
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def _lifespan(application: "FastAPI"):
    """
    FastAPI lifespan — mirrors the boot() sequence in main.py so Fly.io
    starts up with all 8 initialization layers running before the first
    user request arrives (identical to Termux behaviour).

    Phase 0 (NiblitCore.__init__) runs synchronously here; it completes in
    < 1 s and starts the DeferredInitThread that covers Layers 1-5 in the
    background — no blocking of uvicorn startup.
    """
    _log = logging.getLogger("NiblitApp")

    # ── Install the notification-queue log handler (same as main.py) ─────
    try:
        from core.notification_queue import NotificationQueueHandler as _NQH
        _nqh = _NQH()
        _nqh.setLevel(logging.INFO)
        logging.getLogger().addHandler(_nqh)
        _log.debug("[lifespan] NotificationQueueHandler installed")
    except Exception as _e:
        _log.debug("[lifespan] NotificationQueueHandler unavailable: %s", _e)

    # ── Pre-warm NiblitCore (Phase 0 — fast, < 1 s) ───────────────────────
    # Phase 1 (heavy modules) starts automatically in a background daemon
    # thread inside NiblitCore.__init__, so this call never blocks uvicorn.
    _log.info("[lifespan] Pre-warming NiblitCore (Phase 0)…")
    _core_ref = get_core()
    if _core_ref is not None:
        _log.info("[lifespan] ✅ NiblitCore Phase 0 ready — background init running")
    else:
        _log.warning("[lifespan] ⚠️  NiblitCore failed to initialise — running in degraded mode")

    # ── Apply env-configured backend URL to both inference singletons ─────
    # This ensures the effective NIBLIT_LLAMA_SERVER_URL and NIBLIT_GGUF_BACKEND
    # values (set in fly.toml or via `fly secrets set`) are honoured even if
    # the Python singletons were constructed before the env was fully applied.
    _llama_url = os.environ.get("NIBLIT_LLAMA_SERVER_URL", "").strip()
    _backend_mode = os.environ.get("NIBLIT_BACKEND_MODE",
                     os.environ.get("NIBLIT_GGUF_BACKEND", "http")).strip().lower()
    if _llama_url:
        try:
            from modules.local_brain import set_backend_url as _set_backend_url
            _set_backend_url(_llama_url, _backend_mode)
            _log.info("[lifespan] ✅ LocalBrain backend wired → %s (mode=%s)", _llama_url, _backend_mode)
        except Exception as _lbe:
            _log.debug("[lifespan] set_backend_url skipped: %s", _lbe)

    _cloud_url = os.environ.get("NIBLIT_CLOUD_SERVER_URL", "").strip()
    if _cloud_url:
        try:
            from niblit_brain import set_cloud_brain_url as _set_cloud_brain_url
            _set_cloud_brain_url(_cloud_url)
            _log.info("[lifespan] ✅ CloudBrain URL wired → %s", _cloud_url)
        except Exception as _cbe:
            _log.debug("[lifespan] set_cloud_brain_url skipped: %s", _cbe)

    yield  # application is running

    # ── Graceful shutdown ────────────────────────────────────────────────
    if _core_ref is not None:
        try:
            _core_ref.running = False
            _log.info("[lifespan] NiblitCore shutdown flag set")
        except Exception:
            pass


app = FastAPI(title="Niblit AIOS", docs_url=None, redoc_url=None, lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security headers middleware ──────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Request models ────────────────────────────────────────────

class ChatBody(BaseModel):
    text: str = ""


class SearchBody(BaseModel):
    query: str = ""
    text: str = ""


class OpenAIMessage(BaseModel):
    role: str
    content: str


_OPENAI_DEFAULT_MAX_TOKENS = int(
    os.environ.get("NIBLIT_OPENAI_MAX_TOKENS", os.environ.get("NIBLIT_LOCAL_MAX_NEW", "512"))
)


class OpenAIChatRequest(BaseModel):
    """OpenAI-compatible chat completion request.

    Accepted by ``POST /v1/chat/completions`` so this Niblit deployment can
    act as the niblit-cloud-server inference backend for other Niblit
    instances (e.g. the main Niblit Fly.io app calling
    ``NIBLIT_LLAMA_SERVER_URL``).
    """

    model: str = "niblit"
    messages: List[OpenAIMessage] = []
    max_tokens: int = _OPENAI_DEFAULT_MAX_TOKENS
    temperature: float = 0.7
    stream: bool = False
    stop: Optional[List[str]] = None


# ── OpenAI-compatible models list ───────────────────────────────────────
@app.get("/v1/models")
def v1_models():
    """OpenAI-compatible model list endpoint.

    Enables this Niblit deployment to act as a drop-in inference backend
    for other Niblit instances.  ``QwenLocalBrain._check_server_url()``
    probes ``GET /v1/models`` to confirm server availability, so exposing
    this endpoint prevents spurious 404 failures during health checks.
    """
    return JSONResponse({
        "object": "list",
        "data": [
            {
                "id": "niblit",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "niblit",
            }
        ],
    })


# ── Liveness probe ──────────────────────────────────────
@app.get("/health")
def health(request: Request):
    """Lightweight liveness probe — no NiblitCore init required."""
    return render_response(request, {"status": "ok", "service": "niblit"})


# ── OpenAI-compatible inference endpoint ────────────────
@app.post("/v1/chat/completions", dependencies=[Depends(_guard)])
def openai_chat_completions(request: Request, body: OpenAIChatRequest):
    """OpenAI-compatible chat completions endpoint.

    Makes this Niblit deployment act as the inference backend for other
    Niblit instances (niblit-cloud-server).  ``QwenLocalBrain``'s HTTP
    backend calls ``POST /v1/chat/completions`` when
    ``NIBLIT_GGUF_BACKEND=http`` and ``NIBLIT_LLAMA_SERVER_URL`` points here.

    Messages are processed through the local brain when available; the
    full Niblit router (``core.handle()``) is used as a fallback so the
    cloud-server always returns a meaningful response.
    """

    # Extract system prompt and last user message from the messages list.
    system_prompt: Optional[str] = None
    user_message: str = ""
    for msg in body.messages:
        if msg.role == "system":
            system_prompt = msg.content
        elif msg.role == "user":
            user_message = msg.content  # keep overwriting to get the last user turn

    if not user_message:
        return JSONResponse({"error": "no user message in messages"}, status_code=400)

    reply = ""
    core = get_core()

    # Prefer the local brain's raw generation (bypasses the command router so
    # raw LLM prompts are not misinterpreted as Niblit commands).
    local_brain = getattr(core, "local_brain", None) if core else None
    if local_brain is not None and local_brain.is_available():
        try:
            max_new_tokens = max(1, int(body.max_tokens))
            if system_prompt:
                reply = local_brain.ask(
                    user_message,
                    system_prompt=system_prompt,
                    max_new_tokens=max_new_tokens,
                )
            else:
                reply = local_brain.chat(user_message, max_new_tokens=max_new_tokens)
        except Exception as exc:
            log.warning("openai_chat_completions local_brain error: %s", exc)
            reply = ""
        # Treat LocalBrain error strings as empty so fallbacks can handle them.
        if isinstance(reply, str) and reply.startswith("[LocalBrain"):
            reply = ""

    # Fall back to brain_router (cloud / HF) if local brain is unavailable.
    if not reply:
        brain_router = getattr(core, "brain_router", None) if core else None
        if brain_router is not None:
            try:
                reply = brain_router.route(user_message) or ""
            except Exception as exc:
                log.warning("openai_chat_completions brain_router error: %s", exc)
                reply = ""

    # Last resort: full Niblit command handler.
    if not reply and core is not None:
        try:
            reply = str(core.handle(user_message))
        except Exception as exc:
            log.warning("openai_chat_completions core.handle error: %s", exc)
            reply = "[NiblitCloud error: inference unavailable]"

    if not reply:
        reply = "[NiblitCloud: no inference backend available]"

    return JSONResponse({
        "id": f"niblit-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.get("/")
def dashboard(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return HTMLResponse(_build_dashboard())
    return render_response(request, {"service": "niblit", "status": "ok",
                            "endpoints": ["/api/boot", "/api/commands", "/api/search",
                                          "/api/status", "/api/suggest", "/api/threads",
                                          "/api/runtime/state", "/api/runtime/events", "/ws/runtime",
                                          "/ping", "/chat", "/memory",
                                          "/v1/models", "/v1/chat/completions", "/health"]})


# ── Ping / personality ──────────────────────────────────
@app.get("/ping")
def ping(request: Request):
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    core = get_core()
    try:
        p = core.memory.get_personality() if core else {}
    except Exception:
        p = {}
    return render_response(request, {"status": "ok" if core else "no-core", "personality": p})


# ── API: boot messages (mirrors main.py boot()) ─────────
@app.get("/api/boot")
def api_boot(request: Request):
    """
    Return the boot messages that main.py prints on startup.
    Triggers lazy NiblitCore init so the web user sees the same
    sequence as running Niblit in a Termux terminal.
    """
    msgs = _get_boot_messages()
    core = get_core()
    runtime = _get_unified_runtime()
    if runtime is not None:
        try:
            runtime.boot(core=core)
        except Exception:
            pass
    return render_response(request, {"messages": msgs, "ready": core is not None})


# ── API: command suggestions ─────────────────────────────
@app.get("/api/suggest")
def api_suggest(request: Request, q: str = ""):
    """Return close-match command suggestions like main.py suggest_command()."""
    q = q.strip()
    if not q:
        return render_response(request, {"suggestions": []})
    return render_response(request, {"suggestions": suggest_command(q), "query": q})


# ── API: thread list ────────────────────────────────────
@app.get("/api/threads")
def api_threads(request: Request):
    """Return the live thread list — same as the 'threads' command in main.py."""
    return render_response(request, {"threads": _list_threads()})


# ── API: list commands ───────────────────────────────────
@app.get("/api/commands")
def api_commands(request: Request):
    """Return the full command catalogue (used by the sidebar menu)."""
    return render_response(request, {"commands": COMMAND_GROUPS,
                            "count": sum(len(g["commands"]) for g in COMMAND_GROUPS)})


# ── API: system status ───────────────────────────────────
@app.get("/api/status")
def api_status(request: Request):
    """Return detailed system status."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
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
    return render_response(request, data)


# ── API: cross-repo runtime contract (cloud/lean compatibility) ─────────────
@app.get("/niblit/runtime")
def api_niblit_runtime(request: Request):
    """Return schema-v2 runtime contract for cloud and lean adapters."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        core = get_core()
        coord = getattr(core, "runtime_coordinator", None) if core else None
        if coord is None:
            from modules.distributed_runtime_coordinator import get_distributed_runtime_coordinator

            coord = get_distributed_runtime_coordinator()
        state = coord.refresh()
        return render_response(request, dict(state.runtime_contract))
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_niblit_runtime error: %s", exc)
        return JSONResponse(content={"error": "runtime contract unavailable"}, status_code=503)


@app.get("/cluster/status")
def api_cluster_status(request: Request):
    """Federation-readiness cluster status (standalone-safe)."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        core = get_core()
        coord = getattr(core, "runtime_coordinator", None) if core else None
        if coord is None:
            from modules.distributed_runtime_coordinator import get_distributed_runtime_coordinator

            coord = get_distributed_runtime_coordinator()
        return render_response(request, coord.cluster_status())
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_cluster_status error: %s", exc)
        return JSONResponse(content={"error": "cluster status unavailable"}, status_code=503)


@app.get("/federation/peers")
def api_federation_peers(request: Request):
    """Known federation peers from the runtime coordinator registry."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        core = get_core()
        coord = getattr(core, "runtime_coordinator", None) if core else None
        if coord is None:
            from modules.distributed_runtime_coordinator import get_distributed_runtime_coordinator

            coord = get_distributed_runtime_coordinator()
        peers = coord.federation_peers()
        return render_response(request, {"peers": peers, "count": len(peers)})
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_federation_peers error: %s", exc)
        return JSONResponse(content={"error": "federation peers unavailable"}, status_code=503)


@app.get("/federation/status")
def api_federation_status(request: Request):
    """Federation contract readiness metadata (Ω.8 foundation)."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        from api.federation import federation_status

        return render_response(request, federation_status())
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_federation_status error: %s", exc)
        return JSONResponse(content={"error": "federation status unavailable"}, status_code=503)


# ── API: background status (lightweight, polls every 15s) ──
@app.get("/api/bg_status")
def api_bg_status(request: Request):
    """Background status — lightweight, polls every 15s from UI."""
    core = get_core()
    data = {
        "ts": _ts(),
        "ale": None,
        "topics": [],
        "dtm": None,
        "threads": len(threading.enumerate()),
    }
    if core:
        ale = getattr(core, "autonomous_engine", None)
        if ale:
            data["ale"] = {
                "running": getattr(ale, "running", False),
                "cycle": getattr(ale, "_cycle_count", 0),
                "topic": ale.get_current_topic() if hasattr(ale, "get_current_topic") else None,
            }
            topics = getattr(ale, "research_topics", [])
            data["topics"] = topics[:5] if topics else []
        dtm = getattr(core, "dynamic_topic_manager", None)
        if dtm:
            refresh_thread = getattr(core, "_topic_refresh_thread", None)
            data["dtm"] = {
                "seeds": len(getattr(dtm, "seed_topics", [])),
                "thread_alive": refresh_thread is not None and refresh_thread.is_alive(),
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
    return render_response(request, data)


@app.get("/api/runtime/state")
def api_runtime_state(request: Request):
    """Unified runtime state envelope (additive, compatibility-safe)."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    runtime = _get_unified_runtime()
    if runtime is None:
        return render_response(
            request,
            {
                "stream_format": "niblit.runtime.stream.v1",
                "type": "runtime.state",
                "state": {"runtime_mode": "api", "active_provider": "qwen"},
                "telemetry": {},
                "events": {},
            },
        )
    return render_response(request, runtime.state(core=get_core()))


@app.get("/api/runtime/events")
def api_runtime_events(request: Request, since: int = 0, limit: int = 100):
    """Replay unified runtime events for shell/clients."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    runtime = _get_unified_runtime()
    if runtime is None:
        return render_response(request, {"events": [], "since": since, "limit": limit})
    return render_response(
        request,
        {"events": runtime.events(since=since, limit=limit), "since": since, "limit": limit},
    )


@app.get("/api/runtime/episodes")
def api_runtime_episodes(request: Request, limit: int = 50):
    """Replay cognitive episodes and long-horizon reflections."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    runtime = _get_unified_runtime()
    if runtime is None:
        return render_response(request, {"episodes": [], "reflections": [], "dataset": {}, "compression": {}})
    state = runtime.state(core=get_core())
    cognition = state.get("cognition", {})
    return render_response(
        request,
        {
            "episodes": runtime.episodes(limit=limit),
            "reflections": cognition.get("reflections", []),
            "dataset": cognition.get("datasets", {}),
            "compression": cognition.get("compression", {}),
            "confidence": cognition.get("confidence_summary", {}),
        },
    )


@app.websocket("/ws/runtime")
async def ws_runtime(websocket: WebSocket):
    """Live unified runtime stream in canonical format."""
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


# ── API: search (GET or POST) ────────────────────────────
@app.get("/api/search", dependencies=[Depends(_guard)])
def api_search_get(request: Request, q: str = "", query: str = ""):
    """Dedicated search endpoint (GET) — wraps the 'search <query>' command."""
    search_q = (q or query).strip()
    if not search_q:
        return render_response(request,
            {"error": "missing query — send ?q=<query> or POST {\"query\":\"...\"}"},
            status=400)
    core = get_core()
    if not core:
        return render_response(request, {"error": "core failed"}, status=500)
    try:
        result = core.handle(f"search {search_q}")
    except Exception as exc:
        logging.getLogger("NiblitApp").error("search error: %s", exc)
        result = "[error] search failed — see server logs"
    return render_response(request, {"query": search_q, "result": result})


@app.post("/api/search", dependencies=[Depends(_guard)])
def api_search_post(request: Request, body: SearchBody):
    """Dedicated search endpoint (POST) — wraps the 'search <query>' command."""
    search_q = (body.query or body.text).strip()
    if not search_q:
        return render_response(request,
            {"error": "missing query — send ?q=<query> or POST {\"query\":\"...\"}"},
            status=400)
    core = get_core()
    if not core:
        return render_response(request, {"error": "core failed"}, status=500)
    try:
        result = core.handle(f"search {search_q}")
    except Exception as exc:
        logging.getLogger("NiblitApp").error("search error: %s", exc)
        result = "[error] search failed — see server logs"
    return render_response(request, {"query": search_q, "result": result})


# ── Chat (mirrors run_shell() from main.py) ─────────────
@app.post("/chat", dependencies=[Depends(_guard)])
def chat(request: Request, body: ChatBody):
    """
    Process user input using the same logic as main.py run_shell():
    direct commands → router-routed commands → core.handle() catch-all
    + suggestion engine.  Returns reply, suggestion, ts, debug_lines.
    """

    # ── Layer A: basic SecurityMembrane (fast, always-on) ────────────────
    client_ip = request.client.host if request.client else "unknown"
    text_raw = body.text
    try:
        from modules.security_membrane import get_security_membrane
        core_ref = get_core()
        membrane = get_security_membrane(
            knowledge_db=getattr(core_ref, "db", None) if core_ref else None
        )
        result_sm = membrane.inspect(ip=client_ip, payload=text_raw, command=text_raw)
        if not result_sm.allowed:
            return render_response(
                request, {"error": f"Request blocked: {result_sm.reason}"}, status=429
            )
        # Sanitize the input
        text_sanitized = membrane.sanitize(text_raw)
    except Exception:
        text_sanitized = text_raw  # graceful fallback

    # ── Layer B: CyberMembrane — all 8 adaptive security layers ──────────
    # InputGuard → SessionWarden → StealthDetector → TrackerSensor →
    # IntegrityMonitor → AdaptiveFirewall → OutputGuard (MembraneOrchestrator)
    # Identical protection to what Termux receives via niblit_core.cyber_membrane.
    try:
        from modules.niblit_cyber_membrane import get_cyber_membrane
        core_ref = get_core()
        _cm = getattr(core_ref, "cyber_membrane", None)
        if _cm is None:
            _cm = get_cyber_membrane(
                knowledge_db=getattr(core_ref, "db", None) if core_ref else None
            )
        # Stable session id: prefer API key or X-Session-Id header, fall back to IP
        _session_id = (
            request.headers.get("X-API-Key", "")
            or request.headers.get("X-Session-Id", "")
            or client_ip
        )
        _cm_result = _cm.inspect_input(
            ip=client_ip,
            session_id=_session_id,
            command=text_sanitized,
            payload=text_sanitized,
        )
        if not _cm_result.allowed:
            return render_response(
                request,
                {"error": f"Request blocked by security layer: {_cm_result.reason}"},
                status=429,
            )
    except Exception:
        pass  # CyberMembrane unavailable — degrade gracefully

    core = get_core()
    if not core:
        return render_response(request, {"error": "core failed"}, status=500)
    text = text_sanitized.strip()
    if not text:
        return render_response(request, {"error": "no text provided"}, status=400)
    try:
        result = _shell_process(core, text)
    except Exception as exc:
        logging.getLogger("NiblitApp").error("_shell_process error: %s", exc)
        result = {"reply": "[error] request failed — see server logs", "suggestion": None,
                  "ts": _ts(), "debug_lines": []}

    # ── Layer C: OutputGuard — scrub API keys / PII from outbound reply ───
    try:
        _reply = result.get("reply", "")
        if isinstance(_reply, str):
            _cm_out = getattr(core, "cyber_membrane", None)
            if _cm_out is None:
                from modules.niblit_cyber_membrane import get_cyber_membrane
                _cm_out = get_cyber_membrane()
            _clean_reply, _redacted = _cm_out.inspect_output(_reply)
            if _redacted:
                logging.getLogger("NiblitApp").debug(
                    "[OutputGuard] Redacted from reply: %s", _redacted
                )
            result = dict(result)
            result["reply"] = _clean_reply
    except Exception:
        pass  # OutputGuard unavailable — send reply as-is

    return render_response(request, result)


# ── Memory ──────────────────────────────────────────────
@app.get("/memory", dependencies=[Depends(_guard)])
def memory(request: Request):
    core = get_core()
    facts = []
    if core:
        try:
            facts = core.memory.list_facts(limit=200)
        except Exception:
            pass
    return render_response(request, {"facts": facts, "count": len(facts)})


# ── Cross-environment state exchange endpoints ──────────────────────────────

@app.get("/api/state")
def api_state_get(request: Request):
    """Return the current NiblitStateEnvelope (for Node/Rust nodes to pull)."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        from modules.env_state import get_env_state_manager
        core = get_core()
        mgr = get_env_state_manager(knowledge_db=getattr(core, "db", None) if core else None)
        import json as _json
        return JSONResponse(content=_json.loads(mgr.to_json()))
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_state_get error: %s", exc)
        return JSONResponse(content={"error": "state unavailable — see server logs"}, status_code=503)
@app.post("/api/state")
async def api_state_post(request: Request):
    """Accept a NiblitStateEnvelope from a foreign runtime (Node/Rust)."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        payload = await request.body()
        from modules.env_state import get_env_state_manager
        core = get_core()
        mgr = get_env_state_manager(knowledge_db=getattr(core, "db", None) if core else None)
        ok = mgr.merge_from_json(payload.decode("utf-8", errors="replace"))
        if ok:
            mgr.save()
            return JSONResponse(content={"status": "merged"})
        return JSONResponse(content={"error": "checksum mismatch or invalid payload"}, status_code=400)
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_state_post error: %s", exc)
        return JSONResponse(content={"error": "state merge failed — see server logs"}, status_code=500)

@app.post("/api/env/capabilities")
async def api_env_capabilities(request: Request):
    """Accept environment capability report from a foreign runtime node."""
    if rate_limited(request):
        return render_response(request, {"error": "rate limit reached"}, status=429)
    try:
        data = await request.json()
        from modules.env_state import get_env_state_manager
        core = get_core()
        mgr = get_env_state_manager(knowledge_db=getattr(core, "db", None) if core else None)
        runtime = data.get("runtime", "unknown")
        caps = data.get("capabilities", {})
        if isinstance(caps, list):
            caps = {c: True for c in caps}
        mgr.update({"env_capabilities": {f"{runtime}.{k}": v for k, v in caps.items()}}, runtime=runtime)
        # Also register with niblit_runtime if available
        if core and hasattr(core, "niblit_runtime") and core.niblit_runtime:
            name = data.get("component_name", runtime)
            level = float(data.get("declared_level", 1.0))
            core.niblit_runtime.adapt_component(name, level)
        return JSONResponse(content={"status": "accepted"})
    except Exception as exc:
        logging.getLogger("NiblitApp").error("api_env_capabilities error: %s", exc)
        return JSONResponse(content={"error": "capabilities update failed — see server logs"}, status_code=500)

# ══════════════════════════════════════════════════════════════
# TRADE SIGNAL API  — Freqtrade / external strategy integration
#
# These endpoints work under any NIBLIT_PROFILE (including android).
# They do NOT require FAISS or sentence-transformers.
#
# POST /trade/signal
#   Freqtrade (or any strategy) sends current market state and receives
#   a buy / sell / hold recommendation.
#
# POST /trade/feedback
#   Freqtrade sends the outcome of an executed trade so Niblit can
#   learn from it (stored in knowledge DB for future research).
# ══════════════════════════════════════════════════════════════


class TradeSignalRequest(BaseModel):
    """Market state payload sent by an external strategy."""
    pair: str                                          # e.g. "BTC/USDT"
    timeframe: str = "1h"
    ohlcv: Optional[List[List[float]]] = None          # [[ts,o,h,l,c,v], …]
    last_candle: Optional[Dict[str, float]] = None     # last candle + indicator dict
    features: Optional[Dict[str, float]] = None        # additional feature dict


class TradeSignalResponse(BaseModel):
    """Signal response returned to the calling strategy."""
    action: str        # "buy" | "sell" | "hold"
    confidence: float  # 0.0 – 1.0
    metadata: Dict[str, str]


class TradeFeedbackRequest(BaseModel):
    """Trade outcome sent back by the strategy so Niblit can learn."""
    pair: str
    action: str               # action that was executed
    outcome: str              # "profit" | "loss" | "neutral"
    pnl_pct: Optional[float] = None
    timeframe: str = "1h"
    features: Optional[Dict[str, float]] = None


class FeedbackRequest(BaseModel):
    """Explicit user thumbs-up/down on any Niblit response.

    Fields
    ------
    score:      +1 (good), 0 (neutral), -1 (bad).
    query:      The user message that prompted the response (optional).
    response:   The Niblit response being rated (optional).
    context:    Arbitrary caller-supplied context dict (optional).
    """
    score: int  # +1, 0, or -1
    query: str = ""
    response: str = ""
    context: Optional[Dict[str, Any]] = None


_trade_log: logging.Logger = logging.getLogger("NiblitTrade")


def _niblit_trade_signal(pair: str, features: Optional[Dict[str, float]], timeframe: str = "1h") -> Dict[str, object]:
    """Ask NiblitBrain / TradingBrain for a signal, then enrich with KB history.

    Falls back to a 'hold' response if the brain or trading module is not
    available (safe for android profile without ML deps).
    """
    raw_action = "hold"
    raw_confidence = 0.5

    # ── 1. TradingBrain decision ──────────────────────────────────────────────
    try:
        core = get_core()
        trading_brain = getattr(core, "trading_brain", None) if core else None
        if trading_brain is not None and hasattr(trading_brain, "decide_action"):
            action_raw = trading_brain.decide_action(pair)
            action_map = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}
            raw_action = action_map.get(str(action_raw).upper(), "hold")
            raw_confidence = 0.65
    except Exception as exc:
        _trade_log.debug("TradingBrain.decide_action failed: %s", exc)

    # ── 2. NiblitBrain fallback ───────────────────────────────────────────────
    if raw_action == "hold":
        try:
            core = get_core()
            brain = getattr(core, "brain", None) if core else None
            if brain is not None and hasattr(brain, "think"):
                prompt = (
                    f"Given current market data for {pair} with indicators "
                    f"{features or {}}, reply with exactly one word: BUY, SELL, or HOLD."
                )
                raw_answer = str(brain.think(prompt)).strip().upper()
                parts = raw_answer.split()
                answer = parts[0] if parts else "HOLD"
                action_map = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}
                raw_action = action_map.get(answer, "hold")
                raw_confidence = 0.55
        except Exception as exc:
            _trade_log.debug("NiblitBrain.think failed: %s", exc)

    # ── 3. Enrich with KB pattern history ────────────────────────────────────
    try:
        from modules.trade_kb_learner import TradeKBLearner
        core = get_core()
        kb_db = getattr(core, "db", None) if core else None
        learner = TradeKBLearner(knowledge_db=kb_db)
        enriched = learner.enrich_signal(
            pair, timeframe, features or {}, raw_action, raw_confidence
        )
        return {
            "action": enriched["action"],
            "confidence": enriched["confidence"],
            "source": enriched.get("source", "trade_kb_learner"),
            "reason": enriched.get("reason", ""),
            "win_rate": enriched.get("win_rate"),
            "sample_size": enriched.get("sample_size", 0),
        }
    except Exception as exc:
        _trade_log.debug("TradeKBLearner enrichment failed: %s", exc)

    return {"action": raw_action, "confidence": raw_confidence, "source": "raw"}


@app.post("/trade/signal", response_model=TradeSignalResponse)
def trade_signal(request: Request, body: TradeSignalRequest):
    """Return a trading signal for the given pair and market state.

    Works in every profile (android, core, full).  When the full ML stack is
    unavailable the endpoint returns a safe 'hold' signal with low confidence.

    Request body:
        pair        — trading pair, e.g. "BTC/USDT"
        timeframe   — candle timeframe, e.g. "1h"
        ohlcv       — list of [timestamp, open, high, low, close, volume] arrays (optional)
        last_candle — dict of last candle values + indicator values (optional)
        features    — additional feature dict (optional)

    Response:
        action      — "buy" | "sell" | "hold"
        confidence  — float 0..1
        metadata    — dict with source, pair, profile, timeframe
    """
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)

    combined_features: Dict[str, float] = {}
    if body.features:
        combined_features.update(body.features)
    if body.last_candle:
        combined_features.update(body.last_candle)

    try:
        result = _niblit_trade_signal(body.pair, combined_features, timeframe=body.timeframe)
    except Exception as exc:
        _trade_log.error("trade_signal error: %s", exc)
        result = {"action": "hold", "confidence": 0.5, "source": "error_fallback"}

    profile = os.environ.get("NIBLIT_PROFILE", "core")
    return JSONResponse(content={
        "action": str(result.get("action", "hold")),
        "confidence": float(result.get("confidence", 0.5)),
        "metadata": {
            "source": str(result.get("source", "unknown")),
            "pair": body.pair,
            "timeframe": body.timeframe,
            "profile": profile,
            "reason": str(result.get("reason", "")),
            "win_rate": result.get("win_rate"),
            "sample_size": int(result.get("sample_size") or 0),
        },
    })


@app.post("/trade/feedback")
def trade_feedback(request: Request, body: TradeFeedbackRequest):
    """Accept trade outcome feedback so Niblit can learn from it.

    The outcome is stored as a knowledge-base entry and fed to the
    TradeKBLearner so future signal requests improve their accuracy over time.
    When NIBLIT_RL_ENABLED=1 and the RL policy is wired in, the reward is
    also propagated to the RL policy via TradingStudy.log_trade().
    Works in every profile.
    """
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)

    note = (
        f"Trade feedback: {body.pair} | action={body.action} | outcome={body.outcome}"
        + (f" | pnl={body.pnl_pct:.2f}%" if body.pnl_pct is not None else "")
    )
    _trade_log.info(note)

    stored = False
    try:
        core = get_core()
        if core and hasattr(core, "db") and core.db:
            core.db.store(
                key=f"trade_feedback_{body.pair}_{body.action}",
                value=note,
                category="trade_feedback",
            )
            stored = True
    except Exception as exc:
        _trade_log.debug("trade_feedback store error: %s", exc)

    # ── Feed outcome to TradeKBLearner so pattern memory grows ───────────────
    kb_learned = False
    try:
        from modules.trade_kb_learner import TradeKBLearner
        core = get_core()
        kb_db = getattr(core, "db", None) if core else None
        learner = TradeKBLearner(knowledge_db=kb_db)
        features: Dict[str, float] = dict(body.features or {})
        learner.record_outcome(
            pair=body.pair,
            timeframe=body.timeframe,
            features=features,
            action=body.action,
            outcome=body.outcome,
            pnl_pct=body.pnl_pct,
        )
        kb_learned = True
    except Exception as exc:
        _trade_log.debug("TradeKBLearner record_outcome error: %s", exc)

    # ── Propagate reward to TradingStudy / RL policy ─────────────────────────
    rl_rewarded = False
    try:
        core = get_core()
        ts = getattr(core, "trading_study", None) if core else None
        if ts and hasattr(ts, "log_trade"):
            pnl = body.pnl_pct or 0.0
            ts.log_trade(
                symbol=body.pair,
                side=body.action,
                price=0.0,
                qty=0.0,
                pnl=pnl,
                source="freqtrade_feedback",
            )
            rl_rewarded = True
    except Exception as exc:
        _trade_log.debug("TradingStudy.log_trade error: %s", exc)

    # ── Record trading episode into PolicyOptimizer ───────────────────────────
    # Normalise PnL into [0,1] so the policy layer can learn which advisors
    # perform best for trading-context decisions over time.
    try:
        from modules.policy_optimizer import get_policy_optimizer
        _po = get_policy_optimizer()
        _pnl = body.pnl_pct or 0.0
        # map PnL % to outcome score: 0 pnl→0.5, +5%→0.75, -5%→0.25, clamped [0,1]
        _outcome = max(0.0, min(1.0, 0.5 + _pnl / 20.0))
        _po.record_episode(
            context_type="trading",
            advisor_chosen="memory",  # TradeKBLearner uses memory/historical patterns
            advisor_confidences={"memory": _outcome},
            outcome_score=_outcome,
        )
    except Exception as _po_exc:
        _trade_log.debug("PolicyOptimizer trade episode error: %s", _po_exc)

    return JSONResponse(content={
        "status": "accepted",
        "stored": stored,
        "kb_learned": kb_learned,
        "rl_rewarded": rl_rewarded,
    })


@app.post("/feedback", dependencies=[Depends(_guard)])
def user_feedback(request: Request, body: FeedbackRequest):
    """Accept explicit user thumbs-up/down on any Niblit response.

    ``score`` must be +1 (good), 0 (neutral), or -1 (bad).
    The signal is injected into both the PolicyOptimizer (episode log) and
    the EvaluationEngine (reinforce/decay adaptive weights) so the system
    learns from direct human preference in addition to automatic quality scoring.
    """
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)

    score = max(-1, min(1, int(body.score)))
    # Normalise to [0, 1] for the learning layers: -1→0.0, 0→0.5, +1→1.0
    outcome_score = (score + 1) / 2.0

    _app_log = logging.getLogger("NiblitApp")
    _app_log.info("[Feedback] score=%+d  query=%r", score, (body.query or "")[:80])

    po_recorded = False
    try:
        from modules.policy_optimizer import get_policy_optimizer
        po = get_policy_optimizer()
        ctx_type = po.classify_context(body.query or "")
        # explicit_user is a special advisor name that marks ground-truth feedback
        po.record_episode(
            context_type=ctx_type,
            advisor_chosen="explicit_user",
            advisor_confidences={"explicit_user": outcome_score},
            outcome_score=outcome_score,
        )
        po_recorded = True
    except Exception as _po_err:
        _app_log.debug("[Feedback] PolicyOptimizer record_episode failed: %s", _po_err)

    eval_adjusted = False
    try:
        core = get_core()
        ee = getattr(core, "evaluation_engine", None) if core else None
        if ee is not None and hasattr(ee, "reinforce"):
            delta = 0.05 * score  # +0.05 on thumbs-up, -0.05 on thumbs-down
            if body.query or body.response:
                # Reinforce the advisor that was likely chosen for this response.
                # We infer it from the most recent signal in NiblitState.
                ns = getattr(core, "niblit_state", None)
                last_decision = (
                    getattr(ns, "signals", {}).get("decision", {}) if ns else {}
                )
                chosen_adv = last_decision.get("chosen_advisor", "llm")
                if delta != 0:
                    ee.reinforce(chosen_adv, delta)
                    eval_adjusted = True
    except Exception as _ee_err:
        _app_log.debug("[Feedback] EvaluationEngine reinforce failed: %s", _ee_err)

    return JSONResponse(content={
        "status": "accepted",
        "score": score,
        "outcome_score": round(outcome_score, 2),
        "po_recorded": po_recorded,
        "eval_adjusted": eval_adjusted,
    })


# ── Trade pattern analysis endpoint ─────────────────────────────────────────

@app.get("/trade/analyze")
def trade_analyze(request: Request, pair: str = "", limit: int = 20):
    """Return a human-readable summary of Niblit's learned trading patterns.

    Query params:
        pair  — filter by pair, e.g. ?pair=BTC/USDT  (optional)
        limit — max pattern buckets to return (default 20)
    """
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)
    try:
        from modules.trade_kb_learner import TradeKBLearner
        core = get_core()
        kb_db = getattr(core, "db", None) if core else None
        learner = TradeKBLearner(knowledge_db=kb_db)
        summary = learner.summarize(pair=pair or None, limit=max(1, min(limit, 100)))
        return JSONResponse(content={"summary": summary, "pair_filter": pair or "all"})
    except Exception as exc:
        logging.getLogger("NiblitApp").error("trade_analyze error: %s", exc)
        return JSONResponse(content={"error": "analysis failed — see server logs"}, status_code=500)


# ── Knowledge recall API endpoints ────────────────────────────────────────────

@app.get("/kb/think")
def kb_think(request: Request, topic: str = ""):
    """Synthesise what Niblit knows about *topic* (TF-IDF ranked retrieval).

    Query params:
        topic — the subject to synthesise knowledge about (required)
    """
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)
    if not topic:
        return JSONResponse(content={"error": "topic query parameter required"}, status_code=400)
    try:
        core = get_core()
        db = getattr(core, "db", None) if core else None
        if db is None:
            return JSONResponse(content={"error": "KB not available"}, status_code=503)
        answer = db.think_about(topic)
        return JSONResponse(content={"topic": topic, "synthesis": answer})
    except Exception as exc:
        logging.getLogger("NiblitApp").error("kb_think error: %s", exc)
        return JSONResponse(content={"error": "synthesis failed — see server logs"}, status_code=500)


@app.get("/kb/health")
def kb_health(request: Request, topic: str = ""):
    """Return knowledge health metrics for *topic* (or the whole KB).

    Query params:
        topic — optional filter topic
    """
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)
    try:
        core = get_core()
        db = getattr(core, "db", None) if core else None
        if db is None:
            return JSONResponse(content={"error": "KB not available"}, status_code=503)
        health = db.knowledge_health(topic)
        return JSONResponse(content={"topic": topic or "all", **health})
    except Exception as exc:
        logging.getLogger("NiblitApp").error("kb_health error: %s", exc)
        return JSONResponse(content={"error": "health check failed — see server logs"}, status_code=500)


@app.post("/kb/consolidate")
def kb_consolidate(request: Request, dry_run: bool = False):
    """Merge duplicate KB facts (same key) — call with ?dry_run=true to preview."""
    if rate_limited(request):
        return JSONResponse(content={"error": "rate limit reached"}, status_code=429)
    try:
        core = get_core()
        db = getattr(core, "db", None) if core else None
        if db is None:
            return JSONResponse(content={"error": "KB not available"}, status_code=503)
        report = db.consolidate_facts(dry_run=dry_run)
        return JSONResponse(content=report)
    except Exception as exc:
        logging.getLogger("NiblitApp").error("kb_consolidate error: %s", exc)
        return JSONResponse(content={"error": "consolidation failed — see server logs"}, status_code=500)


# Register /mcp (JSON-RPC POST) and /mcp/sse (SSE notifications).
# Any MCP-compatible client (Claude Desktop, VS Code Copilot, Cursor …)
# can connect to Niblit through these endpoints.
try:
    from modules.mcp_server import register_fastapi_routes as _mcp_register
    _mcp_register(app)
except Exception as _mcp_exc:
    import logging as _lg
    _lg.getLogger("NiblitApp").debug("MCP routes not registered: %s", _mcp_exc)


# ══════════════════════════════════════════════════════════════
# LOCAL DEV ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Niblit Web AI on http://0.0.0.0:{port}")
    uvicorn.run("app:app", host="0.0.0.0", port=port,
                reload=os.environ.get("APP_DEBUG", "0") == "1")
