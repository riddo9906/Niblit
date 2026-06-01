#!/usr/bin/env python3
"""
MAIN — Niblit AIOS
With Advanced Live Instrumentation
Logic Fully Intact

ENHANCEMENT (additive only): Non-blocking background notifications.
All background agents and periodic loops push their output into
core.notification_queue.notif_queue.  The shell loop calls
print_notifications() immediately AFTER input() returns so background
feedback is only shown after the user presses Enter — never overwriting
an in-progress command.  The NotificationQueueHandler installed at
startup silently captures background-thread log records so they no
longer print to the terminal mid-typing.
"""

import argparse
import datetime
import difflib
import json
import logging
import os
import signal
import sys
import threading
import time
import traceback

# ── Centralised logging configuration ──────────────────────────────────────
# Set up the root logger ONCE here, before any module imports.  Individual
# modules should only call ``logging.getLogger(name)`` — never
# ``logging.basicConfig()`` — so that all log output flows through this
# single StreamHandler.  The notification queue handler installed at boot
# adds its own filter to this handler to suppress background-thread output.
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
)

# Load .env file when running locally (e.g. Termux).  niblit_core also calls
# load_dotenv(), but doing it here ensures vars are set before any imports.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on os.environ

from niblit_core import NiblitCore
from niblit_io import NiblitIO

DEFAULT_INIT_WAIT_MAX_SECONDS = 600.0  # 10 min default; override via NIBLIT_INIT_WAIT_MAX_SECONDS
TOOL_NO_OUTPUT_MESSAGE = "[Tool returned no output]"

# ── Non-blocking background notification queue (additive) ──────────────────
# Import the shared notification queue so we can surface background output
# ONLY after the user presses Enter (never during typing).
try:
    from core.notification_queue import install_queue_log_handler, notif_queue
    _NOTIF_QUEUE_AVAILABLE = True
except ImportError:
    notif_queue = None  # type: ignore[assignment]
    install_queue_log_handler = None  # type: ignore[assignment]
    _NOTIF_QUEUE_AVAILABLE = False

# ─────────────────────────────
# SIGNAL HANDLING
# Ensures core.shutdown() is called when Termux closes the session
# (SIGHUP), when the OS requests termination (SIGTERM), or when the
# user presses Ctrl+C from outside the shell loop (SIGINT).
# ─────────────────────────────
_active_core = None  # set by run_shell so signal handlers can reach it


def _shutdown_on_signal(sig, frame):
    """Signal handler: flush autonomous-growth data then exit cleanly."""
    try:
        sig_name = signal.strsignal(sig) or str(sig)
    except (ValueError, AttributeError):
        sig_name = str(sig)
    print(f"\n{timestamp()} [SIGNAL] {sig_name} received — saving state and exiting...",
          flush=True)
    if _active_core is not None:
        try:
            _active_core.shutdown()
        except Exception:
            pass
    sys.exit(0)

# ─────────────────────────────
# DIRECTORY LOCK
# ─────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ─────────────────────────────
# GLOBAL DEBUG FLAG
# ─────────────────────────────
DEBUG_MODE = True

# ─────────────────────────────
# COMMAND LIST (for suggestions only)
# ─────────────────────────────
LEGACY_COMMANDS = [
    "help",
    "status",
    "memory",
    "search",
    "summary",
    "learn about",
    "self-heal",
    "self-teach",
    "self-research",
    "debug on",
    "debug off",
    "threads",
    # New commands added by background-management enhancement
    "notifications",
    "reload_params",
    "run_selfheal",
    "refresh-topics",
    "dev-agent status",
    "dev-agent runtime",
    "dev-agent providers",
    "dev-agent architecture",
    "dev-agent analyze",
    "dev-agent approve",
    "retrieval status",
    "retrieval inspect",
    "retrieval contradictions",
    "retrieval mastery",
    "retrieval sources",
    "retrieval gaps",
    "retrieval reflections",
    "retrieval curriculum",
    "retrieval lineage",
    "retrieval confidence",
    "retrieval causality",
]

def timestamp():
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

def _command_vocabulary(core=None):
    names = set(LEGACY_COMMANDS)
    names.update({"exit", "quit", "debug on", "debug off", "session summary", "notifications history", "sidecar status", "unified status"})
    registry = getattr(core, "command_registry", None) if core is not None else None
    if registry is not None and hasattr(registry, "command_names"):
        try:
            names.update(
                registry.command_names(
                    context={"surface": "cli"},
                    surface="cli",
                    include_aliases=True,
                    include_unavailable=True,
                )
            )
        except Exception:
            pass
    return sorted(name for name in names if name)


def suggest_command(user_input, core=None):
    matches = difflib.get_close_matches(user_input, _command_vocabulary(core), n=3, cutoff=0.5)
    # Never suggest a command that is identical to what the user already typed —
    # difflib returns exact matches too, which creates spurious "Did you mean X?"
    # messages right after X was successfully executed.
    return [m for m in matches if m != user_input]

# ─────────────────────────────
# CLI ARGUMENT PARSER (Ollama-inspired)
# ─────────────────────────────
def parse_args(argv=None):
    """Parse Niblit AIOS command-line arguments.

    Inspired by the clean CLI design of Ollama, this parser lets users:
    - run a one-shot command without entering the interactive shell
    - suppress verbose startup output in scripts
    - override the debug flag at launch time
    - query the current version

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        :class:`argparse.Namespace` with attributes:
        ``one_shot``, ``quiet``, ``debug``, ``version``.
    """
    try:
        from config import settings as _settings  # type: ignore[import]
        _version = getattr(_settings, "VERSION", None) or "AIOS"
    except Exception:
        _version = "AIOS"

    p = argparse.ArgumentParser(
        prog="niblit",
        description="Niblit AIOS — Neural Integrated Baseline for Learning, Intelligence, and Tasking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  niblit                          Start the interactive shell\n"
            "  niblit -c 'status'              Run one command and exit\n"
            "  niblit -c 'learn about python'  Learn a topic, then exit\n"
            "  niblit --list-tools             List registered function-calling tools\n"
            "  niblit --tool-call my_tool --tool-arguments '{\"x\":1}'\n"
            "                                  Run a registered tool and exit\n"
            "  niblit --quiet                  Start shell without startup banners\n"
            "  niblit --version                Show version information\n"
        ),
    )
    p.add_argument(
        "-c", "--one-shot",
        metavar="CMD",
        default=None,
        help="Run a single command and exit (non-interactive mode)",
    )
    p.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Suppress startup banners and background notifications",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug output from startup",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"Niblit AIOS {_version}",
    )
    p.add_argument(
        "--list-tools",
        action="store_true",
        default=False,
        help="List registered tool-use / function-calling tools and exit",
    )
    p.add_argument(
        "--tool-call",
        metavar="TOOL",
        default=None,
        help="Execute a registered tool by name and exit",
    )
    p.add_argument(
        "--tool-arguments",
        metavar="JSON",
        default="{}",
        help="JSON object arguments for --tool-call (default: '{}')",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Disable desktop UI auto-launch and run CLI only",
    )
    p.add_argument(
        "--cli",
        action="store_true",
        default=False,
        help="Force interactive CLI shell (skip desktop UI)",
    )
    return p.parse_args(argv)


def _parse_tool_arguments(raw: str) -> dict:
    """Parse ``--tool-arguments`` into a JSON-object dict."""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --tool-arguments JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("--tool-arguments must decode to a JSON object")
    return payload


def _run_tool_cli_mode(args, io=None) -> int:
    """Handle ``--list-tools`` / ``--tool-call`` mode. Return process exit code."""
    if not (getattr(args, "list_tools", False) or getattr(args, "tool_call", None)):
        return -1

    from niblit_tools.tool_registry import get_registry
    registry = get_registry()
    if io is not None and hasattr(io, "out") and hasattr(io, "error"):
        out = io.out
        err = io.error
    else:
        out = print

        def err(msg):
            print(msg, file=sys.stderr)

    if getattr(args, "list_tools", False):
        defs = registry.list_tools()
        if not defs:
            out("No tools registered.")
        else:
            lines = ["🔧 Registered tools:"]
            for d in defs:
                name = d.get("name", "<unnamed>")
                desc = (d.get("description") or "").strip() or "No description"
                lines.append(f"  - {name}: {desc}")
            out("\n".join(lines))
        if not getattr(args, "tool_call", None):
            return 0

    try:
        tool_args = _parse_tool_arguments(getattr(args, "tool_arguments", "{}"))
        result = registry.run(args.tool_call, tool_args)
        out(TOOL_NO_OUTPUT_MESSAGE if result is None else str(result))
        return 0
    except Exception as exc:
        err(f"[TOOL-CALL ERROR] {exc}")
        return 2


def _should_launch_desktop(args, *, ui_supported=None) -> bool:
    """Return True when desktop UI should auto-launch for this invocation.

    UI is the primary execution mode.  Pass ``--headless`` / ``--cli`` or set
    ``NIBLIT_HEADLESS=1`` to opt out and use the terminal shell instead.
    """
    if getattr(args, "one_shot", None) is not None:
        return False
    if getattr(args, "list_tools", False) or getattr(args, "tool_call", None):
        return False
    if getattr(args, "headless", False) or getattr(args, "cli", False):
        return False
    if os.getenv("NIBLIT_HEADLESS", "").strip().lower() in ("1", "true", "yes"):
        return False
    if ui_supported is not None:
        return bool(ui_supported)
    try:
        from modules.desktop_runtime_shell import desktop_ui_supported

        return bool(desktop_ui_supported())
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "desktop_ui_supported probe failed; attempting desktop launch anyway: %s",
            exc,
        )
        # If desktop capability probing fails, still attempt UI launch and rely
        # on DesktopRuntimeShell.run() to gracefully fall back to CLI.
        return True

# ─────────────────────────────
# DEBUG PRINT
# ─────────────────────────────
def debug(io, msg):
    if DEBUG_MODE:
        io.out(f"[DEBUG] {msg}")

# ─────────────────────────────
# LIVE LOG WRAPPER
# ─────────────────────────────
def log_command(io, name, handler):
    try:
        debug(io, f"COMMAND RECEIVED → {name}")
        result = handler()

        if result:
            debug(io, f"COMMAND RESULT ← {name}")
            return result
        else:
            debug(io, f"COMMAND EMPTY RESPONSE ← {name}")
            return "[No output]"

    except Exception as e:
        io.error(f"{timestamp()} [COMMAND ERROR] {name} → {e}")
        traceback.print_exc()
        return "[Command failed]"

# ─────────────────────────────
# THREAD MONITOR
# ─────────────────────────────
def list_threads():
    return "\n".join(
        f"{t.name} | alive={t.is_alive()}"
        for t in threading.enumerate()
    )


# ─────────────────────────────────────────────────────────────────────────────
# NON-BLOCKING NOTIFICATION DISPLAY (additive enhancement)
# Called AFTER input() returns so background output never overwrites typing.
# ─────────────────────────────────────────────────────────────────────────────

def print_notifications(core=None, io=None):
    """Print any pending background notifications to the console.

    This is called once per command loop iteration, AFTER ``input()`` returns
    (i.e. after the user presses Enter).  Background threads never print
    directly — they push to the notification queue — so the user's typing is
    NEVER overwritten or interrupted.

    Sources checked (in order):
    1. The global ``notif_queue`` singleton (core/notification_queue.py)
    2. ``core._notifications`` deque (niblit_core.py internal queue)
    """
    import contextlib

    msgs = []

    # Source 1 — global notif_queue (modules and background_jobs push here)
    if _NOTIF_QUEUE_AVAILABLE and notif_queue is not None:
        msgs.extend(notif_queue.pop_all())

    # Source 2 — core._notifications deque (niblit_core internal notifications)
    if core is not None:
        core_notifs = getattr(core, "_notifications", None)
        if core_notifs is not None:
            with getattr(core, "_lock", contextlib.nullcontext()):
                items = list(core_notifs)
                core_notifs.clear()
            msgs.extend(items)

    if msgs:
        output_fn = io.out if io is not None else print
        output_fn("\n--- Background Notifications ---")
        for m in msgs:
            output_fn(f"  > {m}")
        output_fn("--- End Notifications ---\n")

# ─────────────────────────────
# BOOT
# ─────────────────────────────
def boot():
    io = NiblitIO()
    io.out(f"{timestamp()} ═══════════════════════════════════════════")
    io.out(f"{timestamp()} ✨  TRUE AUTONOMOUS NIBLIT AIOS BOOT")
    io.out(f"{timestamp()} ═══════════════════════════════════════════")

    # Print service status table so the user immediately knows which keys are set.
    try:
        from config import Config as _Config
        _Config.validate()
    except Exception:
        pass

    core = NiblitCore()
    io.out(f"{timestamp()} 🔷 Phase 0 (fast-start) complete — CORE READY")

    # ── Sidecar socket server — start immediately after Phase 0 ─────────────
    # This lets niblit_ctl.py connect and queue commands RIGHT NOW, even while
    # the model is still loading in another terminal session (Session 1 of the
    # two-session Termux setup).  The sidecar blocks each incoming command
    # until mark_ready() is called below (after Phase-1 init finishes).
    try:
        from modules.niblit_sidecar import start_sidecar as _start_sidecar
        _sidecar = _start_sidecar(core_getter=lambda: core)
        io.out(
            f"{timestamp()} 🔌 Sidecar socket ready — connect from another terminal:\n"
            f"          python tools/niblit_ctl.py"
        )
    except Exception as _sc_exc:
        _sidecar = None
        io.out(f"{timestamp()} ⚪ Sidecar socket: not available ({_sc_exc})")

    # ── Non-blocking background logging (additive enhancement) ──────────────
    # Install the NotificationQueueHandler so background-thread log records are
    # captured in the notification queue instead of being written to the
    # terminal while the user is typing.  The main thread's log records
    # continue to propagate normally (the handler only captures non-main
    # threads).
    if _NOTIF_QUEUE_AVAILABLE and install_queue_log_handler is not None:
        install_queue_log_handler(level=logging.INFO)
        io.out(f"{timestamp()} ✅ Background log capture active — notifications shown after Enter")

    debug(io, "Active Threads After Boot:")
    debug(io, list_threads())

    return core, io

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: show notifications via direct command (additive)
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_show_notifications(core=None, io=None):
    """Drain the notification queue and return its contents as a string."""
    msgs = []

    # Source 1 — global notif_queue
    if _NOTIF_QUEUE_AVAILABLE and notif_queue is not None:
        msgs.extend(notif_queue.pop_all())

    # Source 2 — core._notifications deque
    if core is not None:
        core_notifs = getattr(core, "_notifications", None)
        if core_notifs is not None:
            items = list(core_notifs)
            core_notifs.clear()
            msgs.extend(items)

    # Source 3 — core._cmd_notifications (existing niblit_core method)
    if core is not None and hasattr(core, "_cmd_notifications"):
        core_notifications_output = core._cmd_notifications()
        if core_notifications_output and core_notifications_output != "No pending notifications":
            msgs.append(core_notifications_output)

    if not msgs:
        return "No pending notifications."

    # Deduplicate repeated identical messages (e.g. repeated serpapi warnings)
    # preserving chronological first-occurrence order.
    _seen_dedup: dict[str, int] = {}
    for m in msgs:
        _seen_dedup[m] = _seen_dedup.get(m, 0) + 1
    deduped: list[str] = []
    _already_added: set[str] = set()
    for m in msgs:
        if m not in _already_added:
            count = _seen_dedup[m]
            deduped.append(f"{m} (×{count})" if count > 1 else m)
            _already_added.add(m)

    return "Background notifications:\n" + "\n".join(f"  > {m}" for m in deduped)


# ─────────────────────────────────────────────────────────────────────────────
# LONG-RESPONSE PAGING (long response chunking)
# Responses longer than RESPONSE_PAGE_SIZE characters are automatically split
# into pages so the user can scroll through them at their own pace.
# ─────────────────────────────────────────────────────────────────────────────

RESPONSE_PAGE_SIZE = 2000  # characters per page


def _paged_out(io, response: str) -> None:
    """Print *response* to the terminal, paginating if it exceeds RESPONSE_PAGE_SIZE.

    Each page is followed by a '[-- more: X/Y --]' indicator.  If the terminal
    is not interactive (e.g. piped output) the full response is printed at once.
    """
    if not response or len(response) <= RESPONSE_PAGE_SIZE:
        io.out(response)
        return

    # Split on newlines to avoid cutting mid-word
    lines = response.splitlines(keepends=True)
    pages: list = []
    current: list = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > RESPONSE_PAGE_SIZE and current:
            pages.append("".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)
    if current:
        pages.append("".join(current))

    total = len(pages)
    for idx, page in enumerate(pages, 1):
        io.out(page.rstrip())
        if idx < total:
            try:
                cont = input(f"\n[-- more: {idx}/{total} — press Enter to continue, 'q' to stop --] ")
                if cont.strip().lower() == "q":
                    io.out(f"[Stopped at page {idx}/{total}]")
                    break
            except (EOFError, KeyboardInterrupt):
                break


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION HISTORY (Enhancement 3 — replay/exportable notification history)
# A fixed-size ring buffer persists up to NOTIF_HISTORY_LIMIT past notifications
# so that 'notifications history' can replay them at any time.
# ─────────────────────────────────────────────────────────────────────────────

NOTIF_HISTORY_LIMIT = 200
_notif_history: "list[str]" = []  # global ring buffer


def _record_notifications(msgs: "list[str]") -> None:
    """Append *msgs* to the notification history ring buffer."""
    _notif_history.extend(msgs)
    # Trim to limit (keep most recent)
    if len(_notif_history) > NOTIF_HISTORY_LIMIT:
        del _notif_history[: len(_notif_history) - NOTIF_HISTORY_LIMIT]


NOTIF_DISPLAY_LIMIT = 50  # how many recent notifications to show in 'notifications history'


def _cmd_notifications_history() -> str:
    """Return a human-readable replay of the notification history."""
    if not _notif_history:
        return "Notification history is empty."
    lines = ["📋 Notification history (most recent last):"]
    for idx, m in enumerate(_notif_history[-NOTIF_DISPLAY_LIMIT:], 1):
        lines.append(f"  {idx:3}. {m}")
    if len(_notif_history) > NOTIF_DISPLAY_LIMIT:
        lines.append(
            f"  … and {len(_notif_history) - NOTIF_DISPLAY_LIMIT} earlier entries "
            f"(total {len(_notif_history)})"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION SUMMARY (session summary/export)
# ─────────────────────────────────────────────────────────────────────────────

_session_history: "list[tuple[str, str]]" = []  # [(user_input, niblit_response)]
# SESSION_START is set when run_shell() opens so the timestamp reflects when the
# interactive session actually began rather than when the module was imported.
SESSION_START: str = ""


def _record_exchange(user_input: str, response: str) -> None:
    """Record one user↔Niblit exchange for the session summary."""
    _session_history.append((user_input, response))


def _cmd_session_summary(export_path: str = "") -> str:
    """Return a summary of this session's commands and responses."""
    if not _session_history:
        return "No session history yet."
    lines = [f"📝 Session summary (started {SESSION_START}):"]
    lines.append(f"   {len(_session_history)} exchange(s) recorded\n")
    for idx, (inp, resp) in enumerate(_session_history, 1):
        lines.append(f"  [{idx}] You: {inp[:120]}")
        resp_preview = (resp[:200] + "…") if len(resp) > 200 else resp
        lines.append(f"       Niblit: {resp_preview}")
        lines.append("")
    summary = "\n".join(lines)
    if export_path:
        try:
            with open(export_path, "w", encoding="utf-8") as fh:
                fh.write(summary)
            summary += f"\n✅ Exported to: {export_path}"
        except OSError as exc:
            summary += f"\n❌ Export failed: {exc}"
    return summary


def _sync_cli_capability_registry(core, io):
    """Register CLI-only capabilities in the canonical capability registry."""
    registry = getattr(core, "command_registry", None)
    if registry is None:
        return
    registry.register(
        "notifications",
        lambda _text="": _cmd_show_notifications(core, io),
        "Drain background notifications captured by the CLI shell",
        "runtime",
        priority=98,
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )
    registry.register(
        "notifications history",
        lambda _text="": _cmd_notifications_history(),
        "Replay recent notification history from the CLI shell",
        "runtime",
        priority=97,
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )
    registry.register(
        "sidecar status",
        lambda _text="": (
            __import__("modules.niblit_sidecar", fromlist=["get_sidecar"]).get_sidecar().status_line()
            if __import__("modules.niblit_sidecar", fromlist=["get_sidecar"]).get_sidecar() is not None
            else "Sidecar not running."
        ),
        "Show sidecar socket readiness for secondary CLI clients",
        "runtime",
        priority=96,
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )
    registry.register(
        "session summary",
        lambda text="": _cmd_session_summary(text),
        "Summarize or export this interactive CLI session",
        "runtime",
        priority=96,
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )
    registry.register(
        "debug on",
        None,
        "Enable verbose CLI debug output for the current session",
        "runtime",
        priority=95,
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )
    registry.register(
        "debug off",
        None,
        "Disable verbose CLI debug output for the current session",
        "runtime",
        priority=95,
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )
    registry.register(
        "exit",
        None,
        "Exit the interactive CLI shell",
        "runtime",
        priority=95,
        aliases=("quit",),
        source_authority="main.py",
        execution_authority="main.run_shell",
        visibility_surfaces={"cli", "help", "discoverability"},
    )


# ─────────────────────────────
# COMMAND SHELL
# ─────────────────────────────
def run_shell(core, io):
    global DEBUG_MODE, _active_core, SESSION_START
    _active_core = core  # expose to signal handlers
    SESSION_START = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _sync_cli_capability_registry(core, io)

    io.out(f"{timestamp()} READY\n")

    DIRECT_COMMANDS = {
        # ── Sidecar status (additive) ──────────────────────────────────────
        "sidecar status": lambda: (
            __import__("modules.niblit_sidecar", fromlist=["get_sidecar"])
            .get_sidecar()
            .status_line()
            if __import__("modules.niblit_sidecar", fromlist=["get_sidecar"])
            .get_sidecar() is not None
            else "Sidecar not running."
        ),

        # ── Background management (additive) ──────────────────────────────
        "notifications": lambda: _cmd_show_notifications(core, io),
        "notifications history": lambda: _cmd_notifications_history(),

        # ── Session management (Enhancement 5) ────────────────────────────
        "session summary": lambda: _cmd_session_summary(),

        # ── Param reload / self-heal ───────────────────────────────────────
        "reload_params": lambda: (
            core._cmd_reload_params()
            if hasattr(core, "_cmd_reload_params")
            else "[reload_params not available]"
        ),

        "run_selfheal": lambda: (
            core._cmd_run_selfheal()
            if hasattr(core, "_cmd_run_selfheal")
            else "[run_selfheal not available]"
        ),

        # ── Unified loop status (additive) ────────────────────────────────
        "unified status": lambda: (
            "\n".join([
                "🔗 Unified feedback-loop status:",
                f"  Layers ready  : {core._unified_loop_status.get('ready', '?')}/{core._unified_loop_status.get('total', '?')}",
                f"  Verified      : {'✅ Yes' if core._unified_loop_status.get('verified') else '⚠️  No — some layers degraded'}",
                f"  Degraded      : {', '.join(core._unified_loop_status.get('warnings', [])) or 'none'}",
            ]) if hasattr(core, "_unified_loop_status")
            else "[Unified-loop status not yet available — boot may still be in progress]"
        ),
    }

    while True:
        try:
            user_input = input("Niblit > ").strip()

            if not user_input:
                continue

            cmd = user_input.lower()

            # EXIT
            if cmd in ["exit", "quit"]:
                io.out("Shutdown.")
                try:
                    core.shutdown()
                except Exception:  # noqa: BLE001
                    pass
                break

            # DEBUG TOGGLE
            if cmd == "debug on":
                DEBUG_MODE = True
                io.out("Debug mode enabled.")
                continue

            if cmd == "debug off":
                DEBUG_MODE = False
                io.out("Debug mode disabled.")
                continue

            # SESSION EXPORT (accepts optional path argument)
            if cmd.startswith("session summary"):
                rest = user_input[len("session summary"):].strip()
                output = _cmd_session_summary(rest)
                _paged_out(io, output)
                continue

            # DIRECT COMMANDS (check multi-word commands first)
            _matched_direct = None
            for _key in sorted(DIRECT_COMMANDS.keys(), key=len, reverse=True):
                if cmd == _key or cmd.startswith(_key + " "):
                    _matched_direct = _key
                    break
            if _matched_direct is not None:
                output = log_command(io, _matched_direct, DIRECT_COMMANDS[_matched_direct])
                _record_exchange(user_input, output)
                _paged_out(io, output)
                continue

            # ROUTED COMMANDS
            if cmd.startswith(("search ", "summary ", "self-research ", "learn about ")):
                debug(io, f"ROUTER PROCESS → {cmd}")

                if core.router:
                    resp = core.router.process(user_input)
                else:
                    resp = core.handle(user_input)

                debug(io, "ROUTER RESULT RETURNED")
                _record_exchange(user_input, resp)
                _paged_out(io, resp)
                continue

            # FINAL TRACE
            debug(io, "Passing to core.handle()")
            response = core.handle(user_input)
            _record_exchange(user_input, response)
            _paged_out(io, response)

            # Suggestion engine.
            # Only run when the input is NOT already a known command — suggesting
            # close matches after a command that executed successfully is confusing.
            if cmd not in _command_vocabulary(core):
                sug = suggest_command(cmd, core)
                if sug:
                    io.out(f"Did you mean: {sug[0]} ?")

        except KeyboardInterrupt:
            # Ctrl+C pressed while waiting for input — save state before exit
            io.out(f"\n{timestamp()} [INTERRUPTED] Saving autonomous growth data...")
            try:
                core.shutdown()
            except Exception:
                pass
            break

        except EOFError:
            # stdin closed (e.g. Termux session dropped) — save state before exit
            io.out(f"\n{timestamp()} [EOF] Input stream closed. Saving state and exiting...")
            try:
                core.shutdown()
            except Exception:
                pass
            break

        except Exception as e:
            io.error(f"{timestamp()} [RUNTIME ERROR] {e}")
            traceback.print_exc()

# ─────────────────────────────
# MAIN
# ─────────────────────────────
def main(argv=None):
    """Niblit AIOS entry point.

    This function is registered as the ``niblit`` console-script by
    ``pyproject.toml`` so users can invoke the AIOS from any directory
    with simply::

        niblit
        niblit -c 'status'
        niblit --list-tools

    Args:
        argv: Argument list override (defaults to ``sys.argv[1:]``).
    """
    global DEBUG_MODE

    # ── Parse CLI arguments (Ollama-inspired) ─────────────────────────────────
    try:
        _args = parse_args(argv)
    except SystemExit:
        raise  # --help / --version already printed; honour the exit

    # Apply CLI flags before boot
    if _args.debug:
        DEBUG_MODE = True
    if _args.quiet:
        NiblitIO._quiet = True

    # Tool registry CLI mode (LangChain-style function calling)
    _tool_mode_exit = _run_tool_cli_mode(_args)
    if _tool_mode_exit >= 0:
        sys.exit(_tool_mode_exit)

    # Register OS-level signal handlers so that SIGTERM (system kill) and
    # SIGHUP (Termux session close) also trigger a clean shutdown instead
    # of an abrupt process death that loses autonomous-growth data.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _shutdown_on_signal)
        except (OSError, ValueError):
            # SIGHUP is unavailable on Windows; SIGTERM may be restricted on
            # some platforms — ignore gracefully.
            pass

    core, io = boot()

    # ── Block until Phase-1 deferred init is complete ─────────────────────────
    # With phased init, NiblitCore.__init__ returns in < 2s (Phase 0), but
    # all heavy modules (VectorStore, HFBrain, ALE, CivilizationController,
    # trading systems, 60+ optional services) load in a background thread
    # (Phase 1).  We wait here — blocking the CLI prompt — until Phase 1
    # finishes so that the "READY" prompt only appears when Niblit is truly
    # fully booted.
    #
    # The init thread pushes sub-phase progress messages into
    # core._init_progress_queue.  We poll that queue every 2 s and print
    # each message as it arrives, giving real-time feedback on Termux/proot
    # where module loading can take several minutes.
    #
    # Ctrl+C at any time skips the wait and opens the CLI immediately.
    # NIBLIT_SKIP_INIT_WAIT=1 bypasses the wait entirely (background init
    # continues; some features degrade gracefully until it finishes).
    _skip_wait = os.getenv("NIBLIT_SKIP_INIT_WAIT", "0").strip() in ("1", "true", "yes")
    if not _skip_wait and hasattr(core, "wait_for_ready"):
        _max_wait_s = DEFAULT_INIT_WAIT_MAX_SECONDS
        _timeout_disabled = False
        _init_wait_cfg_warning = ""
        _max_wait_raw = os.getenv("NIBLIT_INIT_WAIT_MAX_SECONDS", "").strip()
        if _max_wait_raw:
            try:
                _max_wait_s = float(_max_wait_raw)
            except ValueError:
                _max_wait_s = DEFAULT_INIT_WAIT_MAX_SECONDS
                _init_wait_cfg_warning = (
                    f"⚠️ Invalid NIBLIT_INIT_WAIT_MAX_SECONDS='{_max_wait_raw}' "
                    f"— using default {int(DEFAULT_INIT_WAIT_MAX_SECONDS)}s"
                )
        if _max_wait_s <= 0:
            _timeout_disabled = True
            _init_wait_cfg_warning = (
                "ℹ️ NIBLIT_INIT_WAIT_MAX_SECONDS<=0 — init wait timeout disabled "
                "(waits until ready, failed, or Ctrl+C)"
            )
        _wait_started_at = time.monotonic()
        io.out(
            f"{timestamp()} ⏳ Niblit initialising — please wait until fully booted\n"
            f"          (Ctrl+C to skip to CLI now, or set NIBLIT_SKIP_INIT_WAIT=1)"
        )
        if _init_wait_cfg_warning:
            io.out(f"{timestamp()} {_init_wait_cfg_warning}")
        _init_pq = getattr(core, "_init_progress_queue", None)
        _heartbeat_ticks = 0
        try:
            while True:
                # Block up to 2 s then wake up to drain progress messages.
                core.wait_for_ready(timeout=2.0)
                _phase = getattr(core, "_deferred_init_phase", "complete")

                # Drain and print any progress messages pushed by the init thread.
                _printed = 0
                if _init_pq is not None:
                    while True:
                        try:
                            _msg = _init_pq.get_nowait()
                            io.out(f"{timestamp()} {_msg}")
                            _printed += 1
                        except Exception:
                            break

                if _phase in ("complete", "failed"):
                    break

                # Safety valve: avoid waiting forever if deferred init gets stuck.
                if not _timeout_disabled and (time.monotonic() - _wait_started_at) >= _max_wait_s:
                    io.out(
                        f"{timestamp()} ⚠️ Init wait timeout reached ({int(_max_wait_s)}s) — "
                        "opening CLI while remaining modules continue in background"
                    )
                    break

                # Show a periodic heartbeat if nothing arrived this tick so
                # the user can see we are still alive on slow hardware.
                if _printed == 0:
                    _heartbeat_ticks += 1
                    if _heartbeat_ticks % 10 == 0:  # every ~20 s — reassure Termux users
                        _cur = getattr(core, "_current_init_phase", "loading…")
                        io.out(f"{timestamp()} ⏳ Still loading… ({_cur})")

        except KeyboardInterrupt:
            io.out(
                f"\n{timestamp()} ⚡ Init wait skipped — CLI opening now "
                "(some modules may still be loading in the background)"
            )

        # Drain any messages that arrived just before/after we broke out.
        if _init_pq is not None:
            while True:
                try:
                    _msg = _init_pq.get_nowait()
                    io.out(f"{timestamp()} {_msg}")
                except Exception:
                    break

        _phase = getattr(core, "_deferred_init_phase", "complete")
        if _phase == "complete":
            _sr = getattr(core, "startup_report", None)
            try:
                _rc = sum(
                    1 for r in _sr.results.values() if r.get("status") == "ready"
                ) if (_sr and hasattr(_sr, "results")) else None
                _tc = len(_sr.results) if (_sr and hasattr(_sr, "results")) else None
                if _rc is not None:
                    io.out(
                        f"{timestamp()} ✅ Niblit fully initialised — "
                        f"{_rc}/{_tc} components ready"
                    )
                else:
                    io.out(f"{timestamp()} ✅ Niblit fully initialised — all modules ready")
            except Exception:
                io.out(f"{timestamp()} ✅ Niblit fully initialised — all modules ready")

            # Unblock sidecar clients that connected while the model was loading
            try:
                from modules.niblit_sidecar import get_sidecar as _get_sidecar
                _sc = _get_sidecar()
                if _sc is not None:
                    _sc.mark_ready()
                    io.out(f"{timestamp()} 🔌 Sidecar: READY — niblit_ctl.py can now run commands")
            except Exception:
                pass

            # Show the unified-loop verification result (written by
            # _verify_unified_loop into the init-progress queue).
            _uls = getattr(core, "_unified_loop_status", None)
            if _uls:
                if _uls.get("verified"):
                    io.out(
                        f"{timestamp()} 🔗 Unified feedback loop CONFIRMED — "
                        f"all {_uls['ready']}/{_uls['total']} layers wired and active"
                    )
                else:
                    _warns = ", ".join(_uls.get("warnings", []))
                    io.out(
                        f"{timestamp()} ⚡ Feedback loop PARTIALLY unified — "
                        f"{_uls['ready']}/{_uls['total']} layers active "
                        f"(degraded: {_warns})"
                    )
        else:
            io.out(
                f"{timestamp()} ⚠️  Background init did not complete cleanly "
                f"(phase={_phase}) — some features may be unavailable"
            )
            # Still mark sidecar ready so queued commands are not lost
            try:
                from modules.niblit_sidecar import get_sidecar as _get_sidecar
                _sc = _get_sidecar()
                if _sc is not None:
                    _sc.mark_ready()
            except Exception:
                pass

    # ── One-shot mode: run a single command then exit ─────────────────────────
    if _args.one_shot is not None:
        cmd = _args.one_shot.strip()
        try:
            cmd_lower = cmd.lower()
            if cmd_lower in ("help",):
                response = core.help_text()
            elif core.router:
                response = core.router.process(cmd)
            else:
                response = core.handle(cmd)
            io.out(response)
        except Exception as exc:
            io.error(f"[ONE-SHOT ERROR] {exc}")
            traceback.print_exc()
        finally:
            try:
                core.shutdown()
            except Exception:
                pass
        sys.exit(0)

    # ── Desktop shell auto-launch (native UI; CLI fallback preserved) ────────
    if _should_launch_desktop(_args):
        try:
            from modules.desktop_runtime_shell import launch_desktop_shell
            launched = launch_desktop_shell(core=core, io=io)
            if launched:
                try:
                    core.shutdown()
                except Exception:
                    pass
                return
        except Exception as _ui_exc:
            io.error(f"{timestamp()} [DESKTOP UI ERROR] {_ui_exc} — falling back to CLI")

    # ── Interactive shell ─────────────────────────────────────────────────────
    try:
        run_shell(core, io)
    except Exception as e:
        print(f"{timestamp()} [FATAL] {e}", file=sys.stderr)
        traceback.print_exc()
    finally:
        # Last-resort shutdown: if run_shell exited without calling
        # core.shutdown() (e.g. an unhandled exception escaped), ensure
        # background threads and the autonomous engine are stopped so the
        # process can exit cleanly and all DB writes are flushed.
        if _active_core is not None and getattr(_active_core, "running", False):
            try:
                _active_core.shutdown()
            except Exception:
                pass
        # Clean up the sidecar socket so it doesn't leave a stale file
        try:
            from modules.niblit_sidecar import stop_sidecar as _stop_sidecar
            _stop_sidecar()
        except Exception:
            pass


if __name__ == "__main__":
    main()
