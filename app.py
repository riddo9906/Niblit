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


def _ts():
    """Return a timestamp string matching NiblitIO.timestamp() format (UTC)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("[%Y-%m-%d %H:%M:%S]")


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



# ══════════════════════════════════════════════════════════════
# COMMAND CATALOGUE  — every command from niblit_core.help_text()
# Used by the sidebar menu (/api/commands) and JS quick-actions.
# ══════════════════════════════════════════════════════════════

COMMAND_GROUPS = [
    {
        "group": "Core",
        "icon": "🏠",
        "commands": [
            {"label": "help",                     "cmd": "help",           "desc": "Show all commands"},
            {"label": "time",                     "cmd": "time",           "desc": "Show current time"},
            {"label": "status",                   "cmd": "status",         "desc": "System status"},
            {"label": "health",                   "cmd": "health",         "desc": "Comprehensive health check"},
            {"label": "metrics",                  "cmd": "metrics",        "desc": "Performance metrics"},
            {"label": "dump",                     "cmd": "dump",           "desc": "Show dump loop stats"},
        ],
    },
    {
        "group": "Memory & Learning",
        "icon": "📝",
        "commands": [
            {"label": "remember key:value",       "cmd": "remember ",      "desc": "Store a fact",              "has_input": True},
            {"label": "learn about <topic>",      "cmd": "learn about ",   "desc": "Queue topic for research",  "has_input": True},
            {"label": "ideas about <topic>",      "cmd": "ideas about ",   "desc": "Get creative ideas",        "has_input": True},
        ],
    },
    {
        "group": "Knowledge & Recall",
        "icon": "🧠",
        "commands": [
            {"label": "recall <topic>",           "cmd": "recall ",        "desc": "Search KnowledgeDB for stored facts",  "has_input": True},
            {"label": "acquired data",            "cmd": "acquired data",  "desc": "Browse all ALE-acquired facts"},
            {"label": "acquired data <category>", "cmd": "acquired data ", "desc": "Filter: research/ideas/code/…",        "has_input": True},
            {"label": "knowledge stats",          "cmd": "knowledge stats","desc": "Full KnowledgeDB summary"},
            {"label": "ale processes",            "cmd": "ale processes",  "desc": "Explain all 12 ALE steps + status"},
        ],
    },
    {
        "group": "Autonomous Learning",
        "icon": "🤖",
        "commands": [
            {"label": "autonomous-learn start",   "cmd": "autonomous-learn start",          "desc": "Start background learning (incl. code loop)"},
            {"label": "autonomous-learn stop",    "cmd": "autonomous-learn stop",           "desc": "Stop background learning"},
            {"label": "autonomous-learn status",  "cmd": "autonomous-learn status",         "desc": "View full learning statistics"},
            {"label": "add-topic <topic>",        "cmd": "autonomous-learn add-topic ",     "desc": "Add a research topic", "has_input": True},
            {"label": "code-status",              "cmd": "autonomous-learn code-status",    "desc": "Programming literacy loop status"},
        ],
    },
    {
        "group": "Self-Improvement",
        "icon": "⚡",
        "commands": [
            {"label": "show improvements",        "cmd": "show improvements",       "desc": "View all 10 improvements"},
            {"label": "run improvement-cycle",    "cmd": "run improvement-cycle",   "desc": "Execute improvement cycle"},
            {"label": "improvement-status",       "cmd": "improvement-status",      "desc": "View improvement status"},
        ],
    },
    {
        "group": "Research & Internet",
        "icon": "🔍",
        "commands": [
            {"label": "search <query>",           "cmd": "search ",        "desc": "Search the internet",                   "has_input": True, "is_search": True},
            {"label": "summary <query>",          "cmd": "summary ",       "desc": "Get quick internet summary",             "has_input": True},
            {"label": "self-research <topic>",    "cmd": "self-research ", "desc": "Research autonomously",                  "has_input": True},
            {"label": "research code <lang>",     "cmd": "research code ", "desc": "Research language → CodeGenerator",      "has_input": True},
        ],
    },
    {
        "group": "Brain & Self-Improvement",
        "icon": "🧬",
        "commands": [
            {"label": "self-idea <prompt>",       "cmd": "self-idea ",     "desc": "Generate & implement idea",              "has_input": True},
            {"label": "self-implement <plan>",    "cmd": "self-implement ","desc": "Enqueue plan to SelfImplementer",         "has_input": True},
            {"label": "self-teach <topic>",       "cmd": "self-teach ",    "desc": "Teach topic via SelfTeacher + research", "has_input": True},
            {"label": "idea-implement <prompt>",  "cmd": "idea-implement ","desc": "Generate and implement ideas",            "has_input": True},
            {"label": "reflect <text>",           "cmd": "reflect ",       "desc": "Reflect on topic via ReflectModule",      "has_input": True},
            {"label": "auto-reflect",             "cmd": "auto-reflect",   "desc": "Auto-reflect on recent interactions"},
            {"label": "self-heal",                "cmd": "self-heal",      "desc": "Run self-healing"},
        ],
    },
    {
        "group": "Evolution Engine",
        "icon": "🌱",
        "commands": [
            {"label": "evolve",                   "cmd": "evolve",             "desc": "Run one self-evolution step"},
            {"label": "evolve start",             "cmd": "evolve start",       "desc": "Start continuous background evolution"},
            {"label": "evolve stop",              "cmd": "evolve stop",        "desc": "Stop background evolution"},
            {"label": "evolve status",            "cmd": "evolve status",      "desc": "Show evolution status"},
            {"label": "evolve history",           "cmd": "evolve history",     "desc": "Show recent evolution steps"},
        ],
    },
    {
        "group": "Code Generation",
        "icon": "💻",
        "commands": [
            {"label": "generate code <lang>",     "cmd": "generate code ",   "desc": "Generate code (lang + optional template)", "has_input": True},
            {"label": "run code <lang> <code>",   "cmd": "run code ",        "desc": "Execute code inline",                     "has_input": True},
            {"label": "validate <lang> <code>",   "cmd": "validate ",        "desc": "Validate code syntax",                    "has_input": True},
            {"label": "execute file <path>",      "cmd": "execute file ",    "desc": "Execute a script file",                   "has_input": True},
            {"label": "code templates [lang]",    "cmd": "code templates",   "desc": "List available templates"},
            {"label": "study language <lang>",    "cmd": "study language ",  "desc": "Best practices for language",             "has_input": True},
            {"label": "available languages",      "cmd": "available languages","desc": "Show supported languages"},
        ],
    },
    {
        "group": "File Manager",
        "icon": "📁",
        "commands": [
            {"label": "read file <path>",         "cmd": "read file ",     "desc": "Read a file",                "has_input": True},
            {"label": "write file <path> <content>","cmd": "write file ", "desc": "Write a file",               "has_input": True},
            {"label": "list files [dir]",         "cmd": "list files",     "desc": "List directory contents"},
            {"label": "file environment",         "cmd": "file environment","desc": "Filesystem info"},
        ],
    },
    {
        "group": "Software Study",
        "icon": "📚",
        "commands": [
            {"label": "study software <cat>",     "cmd": "study software ",  "desc": "Study a software category",       "has_input": True},
            {"label": "software categories",      "cmd": "software categories","desc": "List all study categories"},
            {"label": "analyze architecture <n>", "cmd": "analyze architecture ","desc": "Analyze architecture pattern","has_input": True},
            {"label": "design software <desc>",   "cmd": "design software ", "desc": "Generate a software design",      "has_input": True},
            {"label": "what have i studied",      "cmd": "what have i studied","desc": "Show studied this session"},
        ],
    },
    {
        "group": "Introspection",
        "icon": "🔬",
        "commands": [
            {"label": "my structure",             "cmd": "my structure",      "desc": "Full component inventory"},
            {"label": "my threads",               "cmd": "my threads",        "desc": "All active threads"},
            {"label": "my loops",                 "cmd": "my loops",          "desc": "Background loop status"},
            {"label": "my modules",               "cmd": "my modules",        "desc": "Loaded modules"},
            {"label": "my commands",              "cmd": "my commands",       "desc": "All registered commands"},
            {"label": "dashboard",                "cmd": "dashboard",         "desc": "Full runtime dashboard"},
            {"label": "operational flow",         "cmd": "operational flow",  "desc": "How loops & routing work"},
            {"label": "resource usage",           "cmd": "resource usage",    "desc": "RAM, CPU, uptime"},
        ],
    },
    {
        "group": "SLSA Engine",
        "icon": "🛡️",
        "commands": [
            {"label": "slsa-status",              "cmd": "slsa-status",         "desc": "SLSA engine status"},
            {"label": "start_slsa [topics]",      "cmd": "start_slsa",          "desc": "Start SLSA engine"},
            {"label": "stop_slsa",                "cmd": "stop_slsa",           "desc": "Stop SLSA engine"},
            {"label": "restart_slsa [topics]",    "cmd": "restart_slsa",        "desc": "Restart SLSA engine"},
        ],
    },
    {
        "group": "Live Update",
        "icon": "🔄",
        "commands": [
            {"label": "reload <module>",          "cmd": "reload ",        "desc": "Hot-reload a module",      "has_input": True},
            {"label": "upgrade",                  "cmd": "upgrade",        "desc": "Reload all changed modules"},
            {"label": "update-history",           "cmd": "update-history", "desc": "Show reload history"},
        ],
    },
    {
        "group": "Settings",
        "icon": "⚙️",
        "commands": [
            {"label": "toggle-llm on",            "cmd": "toggle-llm on",  "desc": "Enable LLM (use AI)"},
            {"label": "toggle-llm off",           "cmd": "toggle-llm off", "desc": "Disable LLM (research mode)"},
            {"label": "shutdown",                 "cmd": "shutdown",        "desc": "Graceful shutdown"},
        ],
    },
    {
        "group": "Diagnostics",
        "icon": "🩺",
        "commands": [
            {"label": "run-diagnostics",          "cmd": "run-diagnostics","desc": "Run full diagnostic suite"},
            {"label": "run-live-test",            "cmd": "run-live-test",  "desc": "Run live command tester"},
            {"label": "loop-errors",              "cmd": "loop-errors",    "desc": "Background loop error summary"},
        ],
    },
    {
        "group": "Orchestrator",
        "icon": "🎛️",
        "commands": [
            {"label": "orchestrate audit",        "cmd": "orchestrate audit",      "desc": "Run repository audit"},
            {"label": "orchestrate self-heal",    "cmd": "orchestrate self-heal",  "desc": "Run orchestrated self-healing"},
            {"label": "orchestrate fix-guide",    "cmd": "orchestrate fix-guide",  "desc": "Generate fix guide"},
            {"label": "orchestrate verify",       "cmd": "orchestrate verify",     "desc": "Verify imports"},
            {"label": "orchestrate pipeline",     "cmd": "orchestrate pipeline",   "desc": "Run full pipeline"},
            {"label": "hf-task <prompt>",         "cmd": "hf-task ",               "desc": "Execute HF task",     "has_input": True},
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
  <title>Niblit AIOS</title>
  <style>
    /* ── design tokens ── */
    :root{
      --clr-bg:#f0f2f5;--clr-surface:#ffffff;--clr-sidebar:#1e2533;
      --clr-sidebar-text:#c8cfe0;--clr-sidebar-hover:rgba(255,255,255,.08);
      --clr-sidebar-active:rgba(255,255,255,.14);
      --clr-primary:#2563eb;--clr-primary-dark:#1d4ed8;
      --clr-accent:#0ea5a4;--clr-accent-dark:#0d9090;
      --clr-text:#111827;--clr-text-muted:#6b7280;
      --clr-border:#e5e7eb;--clr-danger:#ef4444;--clr-warn:#f59e0b;
      --clr-success:#10b981;--clr-code-bg:#1e2533;--clr-code-text:#e2e8f0;
      --radius:10px;--shadow:0 2px 12px rgba(0,0,0,.08);
      --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
      --font-mono:"SFMono-Regular","Cascadia Code",Consolas,"Liberation Mono",monospace;
      --sidebar-w:270px;--topbar-h:56px;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html,body{height:100%;background:var(--clr-bg);color:var(--clr-text);
              font-family:var(--font-sans);font-size:14px}
    a{color:var(--clr-primary);text-decoration:none}

    /* ── scrollbars ── */
    ::-webkit-scrollbar{width:6px;height:6px}
    ::-webkit-scrollbar-thumb{background:#c1c8d4;border-radius:3px}
    ::-webkit-scrollbar-track{background:transparent}

    /* ══════ TOP BAR ══════ */
    #topbar{
      position:fixed;top:0;left:0;right:0;height:var(--topbar-h);z-index:100;
      background:var(--clr-surface);border-bottom:1px solid var(--clr-border);
      display:flex;align-items:center;padding:0 16px;gap:12px;
      box-shadow:0 1px 4px rgba(0,0,0,.06);
    }
    #menu-btn{background:none;border:none;cursor:pointer;padding:6px;
              color:var(--clr-text-muted);font-size:20px;border-radius:6px;
              display:flex;align-items:center}
    #menu-btn:hover{background:var(--clr-bg);color:var(--clr-text)}
    .brand{display:flex;align-items:center;gap:8px}
    .brand-logo{width:32px;height:32px;background:linear-gradient(135deg,var(--clr-primary),var(--clr-accent));
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                color:#fff;font-weight:800;font-size:14px;letter-spacing:-.5px;flex-shrink:0}
    .brand-name{font-weight:700;font-size:16px;color:var(--clr-text);letter-spacing:-.3px}
    .brand-tag{font-size:11px;color:var(--clr-text-muted);font-weight:400}
    #topbar-mid{flex:1;max-width:480px;margin:0 auto}
    #search-bar-top{
      display:flex;align-items:center;background:var(--clr-bg);
      border:1px solid var(--clr-border);border-radius:20px;padding:6px 14px;gap:8px;
    }
    #search-bar-top input{
      border:none;background:transparent;outline:none;flex:1;font-size:13px;
      color:var(--clr-text);font-family:var(--font-sans);
    }
    #search-bar-top input::placeholder{color:var(--clr-text-muted)}
    #search-bar-top .s-icon{color:var(--clr-text-muted);font-size:15px;flex-shrink:0}
    #topbar-right{display:flex;align-items:center;gap:8px;margin-left:auto}
    #status-badge{
      display:flex;align-items:center;gap:6px;padding:5px 12px;
      border-radius:20px;font-size:12px;font-weight:600;
      background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;
      cursor:default;user-select:none;
    }
    #status-badge.degraded{background:#fef3c7;color:#92400e;border-color:#fcd34d}
    #status-badge.offline{background:#fef2f2;color:#991b1b;border-color:#fecaca}
    #status-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;flex-shrink:0}
    #status-badge.degraded #status-dot{background:#f59e0b}
    #status-badge.offline #status-dot{background:#ef4444}
    .tb-btn{
      background:none;border:1px solid var(--clr-border);color:var(--clr-text-muted);
      padding:6px 13px;border-radius:7px;cursor:pointer;font-size:12px;font-weight:500;
      display:flex;align-items:center;gap:5px;
    }
    .tb-btn:hover{border-color:var(--clr-primary);color:var(--clr-primary)}
    .tb-btn.primary{background:var(--clr-primary);color:#fff;border-color:var(--clr-primary)}
    .tb-btn.primary:hover{background:var(--clr-primary-dark);border-color:var(--clr-primary-dark)}

    /* ══════ LAYOUT ══════ */
    #layout{display:flex;height:100vh;padding-top:var(--topbar-h)}

    /* ══════ SIDEBAR ══════ */
    #sidebar{
      width:var(--sidebar-w);background:var(--clr-sidebar);
      display:flex;flex-direction:column;flex-shrink:0;
      overflow:hidden;transition:width .22s ease;
      border-right:1px solid rgba(255,255,255,.05);
    }
    #sidebar.collapsed{width:0}
    #sidebar-inner{width:var(--sidebar-w);overflow-y:auto;height:100%;padding-bottom:16px}

    .sb-section-label{
      padding:20px 16px 6px;font-size:10px;font-weight:700;letter-spacing:.1em;
      color:rgba(200,207,224,.4);text-transform:uppercase;
    }
    .sb-group{margin-bottom:2px}
    .sb-toggle{
      width:100%;background:none;border:none;color:var(--clr-sidebar-text);
      padding:8px 16px;text-align:left;cursor:pointer;font-size:12.5px;font-weight:600;
      display:flex;align-items:center;gap:9px;border-radius:0;
      transition:background .15s;
    }
    .sb-toggle:hover{background:var(--clr-sidebar-hover)}
    .sb-toggle .g-icon{font-size:14px;flex-shrink:0;width:18px;text-align:center}
    .sb-toggle .g-arr{margin-left:auto;font-size:10px;opacity:.5;
                      transition:transform .2s;transform:rotate(0)}
    .sb-toggle.open .g-arr{transform:rotate(90deg)}
    .sb-list{display:none;margin:0 8px}
    .sb-list.vis{display:block}
    .sb-item{
      padding:6px 10px 6px 16px;color:rgba(200,207,224,.7);cursor:pointer;
      font-size:12px;border-radius:6px;display:flex;align-items:baseline;gap:6px;
      transition:background .12s,color .12s;
    }
    .sb-item:hover{background:var(--clr-sidebar-hover);color:#fff}
    .sb-item .i-label{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .sb-item .i-desc{font-size:10px;color:rgba(200,207,224,.4);flex-shrink:0;
                     max-width:90px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

    /* ══════ MAIN AREA ══════ */
    #main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}

    /* ══════ CHAT AREA ══════ */
    #chat-area{
      flex:1;overflow-y:auto;padding:24px 0;
      display:flex;flex-direction:column;gap:0;
    }

    /* ── welcome / boot banner ── */
    #boot-banner{
      max-width:680px;margin:0 auto 8px;padding:0 20px;
      display:flex;flex-direction:column;gap:12px;
    }
    .boot-card{
      background:var(--clr-code-bg);color:var(--clr-code-text);
      border-radius:var(--radius);padding:16px 20px;font-family:var(--font-mono);
      font-size:12px;line-height:1.7;border-left:3px solid var(--clr-accent);
    }
    .boot-line.dim{color:#8892a4}
    .boot-line.ok{color:#4ade80}
    .boot-line.warn{color:#fbbf24}

    /* ── message rows ── */
    .msg-row{max-width:760px;margin:0 auto;padding:8px 20px;width:100%;display:flex;gap:12px}
    .msg-row.user-row{flex-direction:row-reverse}
    .msg-avatar{
      width:34px;height:34px;border-radius:50%;flex-shrink:0;
      display:flex;align-items:center;justify-content:center;font-size:15px;
      font-weight:700;user-select:none;
    }
    .msg-avatar.niblit{
      background:linear-gradient(135deg,var(--clr-primary),var(--clr-accent));
      color:#fff;font-size:13px;letter-spacing:-.3px;
    }
    .msg-avatar.user{background:#e0e7ff;color:var(--clr-primary);font-size:15px}
    .msg-body{flex:1;min-width:0}
    .msg-meta{font-size:11px;color:var(--clr-text-muted);margin-bottom:4px;display:flex;gap:8px}
    .msg-row.user-row .msg-meta{justify-content:flex-end}
    .msg-bubble{
      background:var(--clr-surface);border:1px solid var(--clr-border);
      border-radius:12px;padding:12px 16px;font-size:13.5px;line-height:1.7;
      box-shadow:var(--shadow);white-space:pre-wrap;word-break:break-word;
    }
    .msg-row.user-row .msg-bubble{
      background:var(--clr-primary);color:#fff;border-color:var(--clr-primary);
    }
    .msg-bubble.err{background:#fef2f2;border-color:#fecaca;color:#991b1b}
    .msg-bubble code{
      background:var(--clr-code-bg);color:var(--clr-code-text);
      padding:2px 6px;border-radius:4px;font-family:var(--font-mono);font-size:12px;
    }
    .msg-bubble pre{
      background:var(--clr-code-bg);color:var(--clr-code-text);
      border-radius:8px;padding:14px 16px;margin-top:8px;overflow-x:auto;
      font-family:var(--font-mono);font-size:12px;line-height:1.6;
    }
    .msg-debug{
      font-size:11px;color:var(--clr-text-muted);font-family:var(--font-mono);
      padding:4px 0 0;display:flex;flex-direction:column;gap:1px;
    }
    .msg-suggestion{
      font-size:12px;color:var(--clr-accent-dark);margin-top:6px;font-style:italic;
    }

    /* ── thinking indicator ── */
    #thinking-row{max-width:760px;margin:0 auto;padding:4px 20px;
                  display:none;align-items:center;gap:12px;width:100%}
    .thinking-dots{display:flex;gap:5px;padding:10px 0}
    .thinking-dots span{width:7px;height:7px;border-radius:50%;background:var(--clr-primary);
                        animation:bounce .9s ease-in-out infinite}
    .thinking-dots span:nth-child(2){animation-delay:.2s}
    .thinking-dots span:nth-child(3){animation-delay:.4s}
    @keyframes bounce{0%,100%{transform:translateY(0);opacity:.4}
                      50%{transform:translateY(-4px);opacity:1}}

    /* ══════ INPUT BAR ══════ */
    #input-bar{
      background:var(--clr-surface);border-top:1px solid var(--clr-border);
      padding:12px 20px 14px;display:flex;align-items:flex-end;gap:10px;
      max-width:760px;width:100%;margin:0 auto;align-self:center;
    }
    #chat-input{
      flex:1;border:1.5px solid var(--clr-border);border-radius:10px;
      padding:10px 14px;font-size:13.5px;font-family:var(--font-sans);
      outline:none;resize:none;min-height:44px;max-height:140px;
      line-height:1.55;color:var(--clr-text);background:var(--clr-bg);
      transition:border-color .15s;
    }
    #chat-input:focus{border-color:var(--clr-primary)}
    #chat-input::placeholder{color:var(--clr-text-muted)}
    #send-btn{
      background:var(--clr-primary);color:#fff;border:none;
      border-radius:10px;padding:10px 20px;cursor:pointer;font-size:14px;
      font-weight:600;font-family:var(--font-sans);white-space:nowrap;
      align-self:flex-end;min-height:44px;transition:background .15s;
    }
    #send-btn:hover:not(:disabled){background:var(--clr-primary-dark)}
    #send-btn:disabled{opacity:.4;cursor:not-allowed}
    .input-hint{
      max-width:760px;margin:0 auto;padding:0 20px 10px;
      font-size:11px;color:var(--clr-text-muted);text-align:center;
    }

    /* ══════ QUICK ACTIONS CHIPS ══════ */
    #quick-chips{
      max-width:760px;margin:0 auto;padding:0 20px 6px;
      display:flex;flex-wrap:wrap;gap:6px;
    }
    .chip{
      padding:5px 12px;border-radius:20px;font-size:12px;font-weight:500;
      border:1px solid var(--clr-border);background:var(--clr-surface);
      color:var(--clr-text-muted);cursor:pointer;transition:all .15s;white-space:nowrap;
    }
    .chip:hover{border-color:var(--clr-primary);color:var(--clr-primary);
                background:#eff6ff}

    /* ══════ MOBILE ══════ */
    @media(max-width:640px){
      :root{--sidebar-w:240px}
      #sidebar{position:fixed;top:var(--topbar-h);left:0;bottom:0;z-index:90;
               width:0!important}
      #sidebar.mobile-open{width:var(--sidebar-w)!important}
      #topbar-mid{display:none}
    }
  </style>
</head>
<body>

<!-- ══ TOP BAR ══ -->
<div id="topbar">
  <button id="menu-btn" title="Toggle sidebar" onclick="toggleSidebar()">☰</button>
  <div class="brand">
    <div class="brand-logo">N</div>
    <div>
      <div class="brand-name">Niblit AIOS</div>
    </div>
  </div>
  <div id="topbar-mid">
    <div id="search-bar-top">
      <span class="s-icon">🔍</span>
      <input id="top-search" type="text" placeholder="Search via Niblit…" autocomplete="off"/>
    </div>
  </div>
  <div id="topbar-right">
    <div id="status-badge" title="Niblit core status">
      <span id="status-dot"></span>
      <span id="status-text">booting…</span>
    </div>
    <button class="tb-btn" onclick="sendText('help')" title="Show all commands">📋 Commands</button>
  </div>
</div>

<!-- ══ LAYOUT ══ -->
<div id="layout">

  <!-- ══ SIDEBAR ══ -->
  <nav id="sidebar">
    <div id="sidebar-inner">
      <div class="sb-section-label">Niblit Commands</div>
      <!-- populated by JS from COMMAND_GROUPS -->
    </div>
  </nav>

  <!-- ══ MAIN ══ -->
  <div id="main">

    <!-- chat / output -->
    <div id="chat-area">
      <div id="boot-banner"><!-- boot sequence injected here --></div>
      <!-- messages appended here -->
    </div>

    <!-- thinking -->
    <div id="thinking-row">
      <div class="msg-avatar niblit">N</div>
      <div class="thinking-dots">
        <span></span><span></span><span></span>
      </div>
    </div>

    <!-- quick chips -->
    <div id="quick-chips">
      <span class="chip" onclick="sendText('status')">⚡ status</span>
      <span class="chip" onclick="sendText('help')">📋 help</span>
      <span class="chip" onclick="sendText('my structure')">🔬 my structure</span>
      <span class="chip" onclick="sendText('autonomous-learn status')">🤖 ale status</span>
      <span class="chip" onclick="sendText('knowledge stats')">🧠 kb stats</span>
      <span class="chip" onclick="sendText('evolve status')">🌱 evolve status</span>
    </div>

    <!-- input bar -->
    <div id="input-bar">
      <textarea id="chat-input" rows="1" placeholder="Type a command or ask Niblit anything…" autocomplete="off" spellcheck="false"></textarea>
      <button id="send-btn" onclick="sendChat()">Send ↩</button>
    </div>
    <div class="input-hint">Enter to send · Shift+Enter for new line · <a onclick="sendText('help')" href="#">view all commands</a></div>

  </div><!-- /main -->
</div><!-- /layout -->

<script>
// ════════════════════════════════════════════════
// DATA — command groups injected by Flask
// ════════════════════════════════════════════════
const GROUPS = __JSON_GROUPS__;

// ════════════════════════════════════════════════
// BUILD SIDEBAR
// ════════════════════════════════════════════════
(function buildSidebar(){
  const sbEl = document.getElementById('sidebar-inner');
  GROUPS.forEach((g, gi)=>{
    const wrap = document.createElement('div');
    wrap.className = 'sb-group';

    const tog = document.createElement('button');
    tog.className = 'sb-toggle' + (gi < 3 ? ' open' : '');
    tog.innerHTML = `<span class="g-icon">${g.icon}</span><span>${g.group}</span><span class="g-arr">▶</span>`;

    const lst = document.createElement('div');
    lst.className = 'sb-list' + (gi < 3 ? ' vis' : '');

    tog.onclick = ()=>{
      tog.classList.toggle('open');
      lst.classList.toggle('vis');
    };

    g.commands.forEach(c=>{
      const item = document.createElement('div');
      item.className = 'sb-item';
      item.title = c.desc;
      item.innerHTML = `<span class="i-label">${c.label}</span><span class="i-desc">${c.desc}</span>`;
      item.onclick = ()=>{
        if(c.is_search){
          document.getElementById('top-search').focus();
        } else if(c.has_input){
          const ta = document.getElementById('chat-input');
          ta.value = c.cmd;
          ta.focus();
          autoResize(ta);
        } else {
          sendText(c.cmd);
        }
        // close sidebar on mobile
        if(window.innerWidth <= 640)
          document.getElementById('sidebar').classList.remove('mobile-open');
      };
      lst.appendChild(item);
    });
    wrap.appendChild(tog);
    wrap.appendChild(lst);
    sbEl.appendChild(wrap);
  });
})();

// ════════════════════════════════════════════════
// SIDEBAR TOGGLE
// ════════════════════════════════════════════════
function toggleSidebar(){
  const sb = document.getElementById('sidebar');
  if(window.innerWidth <= 640){
    sb.classList.toggle('mobile-open');
  } else {
    sb.classList.toggle('collapsed');
  }
}

// ════════════════════════════════════════════════
// TOP SEARCH BAR
// ════════════════════════════════════════════════
document.getElementById('top-search').addEventListener('keydown', e=>{
  if(e.key === 'Enter'){
    e.preventDefault();
    const q = e.target.value.trim();
    if(q){ e.target.value=''; sendText('search ' + q); }
  }
});

// ════════════════════════════════════════════════
// BOOT SEQUENCE
// ════════════════════════════════════════════════
async function runBoot(){
  const banner = document.getElementById('boot-banner');
  setStatus('booting…', '');

  const card = document.createElement('div');
  card.className = 'boot-card';
  card.innerHTML = '<div class="boot-line dim">Niblit AIOS — True Autonomous Intelligence</div>';
  banner.appendChild(card);

  setThinking(true);
  try {
    const r = await fetch('/api/boot');
    const j = await r.json();
    (j.messages||[]).forEach(m=>{
      const d = document.createElement('div');
      d.className = 'boot-line' + (m.includes('[DEBUG]')?' dim': m.includes('[WARN]')?' warn':' ok');
      d.textContent = m;
      card.appendChild(d);
    });
    if(j.ready){
      setStatus('online', 'ok');
    } else {
      setStatus('degraded', 'degraded');
    }
  } catch(ex){
    const d = document.createElement('div');
    d.className='boot-line warn';
    d.textContent = '[boot error] '+ex.message;
    card.appendChild(d);
    setStatus('offline','offline');
  } finally {
    setThinking(false);
  }
}

// ════════════════════════════════════════════════
// STATUS BADGE
// ════════════════════════════════════════════════
function setStatus(label, state){
  const badge = document.getElementById('status-badge');
  document.getElementById('status-text').textContent = label;
  badge.className = state ? 'status-badge '+state : '';
  badge.id = 'status-badge';
  if(state) badge.classList.add(state);
}

async function pollStatus(){
  try {
    const r = await fetch('/ping');
    const j = await r.json();
    const mood = j.personality&&j.personality.mood ? ' · '+j.personality.mood : '';
    if(j.status==='ok'){
      setStatus('online'+mood, 'ok'); // 'ok' class applied → green badge styling
    } else {
      setStatus(j.status||'degraded','degraded');
    }
  } catch(_){
    setStatus('offline','offline');
  }
}
setInterval(pollStatus, 10000);

// ════════════════════════════════════════════════
// MESSAGE RENDERING
// ════════════════════════════════════════════════
const chatArea = document.getElementById('chat-area');

function fmtTime(){
  return new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}

// Minimal markdown: wrap ```...``` in <pre><code>, inline `x` → <code>x</code>
function renderMd(text){
  let s = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // fenced code blocks
  s = s.replace(/```([^`]*?)```/gs, (_,c)=>`<pre><code>${c}</code></pre>`);
  // inline code
  s = s.replace(/`([^`]+?)`/g, (_,c)=>`<code>${c}</code>`);
  return s;
}

function addMsg(who, text, debugLines, suggestion){
  const isUser = who==='user';
  const isErr  = who==='err';
  const row = document.createElement('div');
  row.className = 'msg-row' + (isUser?' user-row':'');

  const av = document.createElement('div');
  av.className = 'msg-avatar ' + (isUser?'user':'niblit');
  av.textContent = isUser ? '👤' : 'N';

  const body = document.createElement('div');
  body.className = 'msg-body';

  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.textContent = (isUser?'You':'Niblit') + ' · ' + fmtTime();
  body.appendChild(meta);

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble' + (isErr?' err':'');
  bubble.innerHTML = isUser
    ? text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    : renderMd(text);
  body.appendChild(bubble);

  if(debugLines && debugLines.length){
    const dblock = document.createElement('div');
    dblock.className = 'msg-debug';
    debugLines.forEach(l=>{ const s=document.createElement('span'); s.textContent=l; dblock.appendChild(s); });
    body.appendChild(dblock);
  }
  if(suggestion){
    const sg = document.createElement('div');
    sg.className = 'msg-suggestion';
    sg.textContent = suggestion;
    body.appendChild(sg);
  }

  if(isUser){ row.appendChild(body); row.appendChild(av); }
  else       { row.appendChild(av);  row.appendChild(body); }

  chatArea.appendChild(row);
  chatArea.scrollTop = chatArea.scrollHeight;
}

// ════════════════════════════════════════════════
// THINKING INDICATOR
// ════════════════════════════════════════════════
function setThinking(on){
  const tr = document.getElementById('thinking-row');
  tr.style.display = on ? 'flex' : 'none';
  document.getElementById('send-btn').disabled = on;
  document.getElementById('chat-input').disabled = on;
  if(on) chatArea.scrollTop = chatArea.scrollHeight;
}

// ════════════════════════════════════════════════
// INPUT AUTO-RESIZE
// ════════════════════════════════════════════════
function autoResize(el){
  el.style.height='auto';
  el.style.height=Math.min(el.scrollHeight, 140)+'px';
}
document.getElementById('chat-input').addEventListener('input', function(){ autoResize(this); });
document.getElementById('chat-input').addEventListener('keydown', function(e){
  if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendChat(); }
});

// ════════════════════════════════════════════════
// SEND MESSAGE
// ════════════════════════════════════════════════
function sendChat(){
  const ta = document.getElementById('chat-input');
  const text = ta.value.trim();
  if(!text) return;
  ta.value='';
  autoResize(ta);
  sendText(text);
}

async function sendText(text){
  addMsg('user', text);
  setThinking(true);
  try {
    const resp = await fetch('/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text})
    });
    const j = await resp.json();
    if(j.error){
      addMsg('err', j.error);
    } else {
      addMsg('niblit', j.reply||'[no reply]', j.debug_lines||[], j.suggestion||null);
    }
  } catch(ex){
    addMsg('err', 'Network error: ' + ex.message);
  } finally {
    setThinking(false);
    document.getElementById('chat-input').focus();
  }
}

// ════════════════════════════════════════════════
// START
// ════════════════════════════════════════════════
runBoot();
</script>
</body>
</html>
"""


def _build_dashboard():
    """Inject Python-side data (COMMAND_GROUPS) into the dashboard HTML template."""
    groups_json = _json.dumps(COMMAND_GROUPS)
    return DASHBOARD_HTML.replace("__JSON_GROUPS__", groups_json)
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
