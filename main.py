#!/usr/bin/env python3
"""
MAIN — Niblit AIOS
With Advanced Live Instrumentation
Logic Fully Intact
"""

import os
import sys
import signal
import traceback
import difflib
import datetime
import threading

from niblit_core import NiblitCore
from niblit_io import NiblitIO
from niblit_router import safe_call

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
COMMANDS = [
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
    "threads"
]

def timestamp():
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

def suggest_command(user_input):
    return difflib.get_close_matches(user_input, COMMANDS, n=3, cutoff=0.5)

# ─────────────────────────────
# DEBUG PRINT
# ─────────────────────────────
def debug(io, msg):
    if DEBUG_MODE:
        io.out(f"{timestamp()} [DEBUG] {msg}")

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

# ─────────────────────────────
# BOOT
# ─────────────────────────────
def boot():
    io = NiblitIO()
    io.out(f"{timestamp()} TRUE AUTONOMOUS NIBLIT BOOT")

    core = NiblitCore()
    io.out(f"{timestamp()} CORE READY")

    # Report wake-lock status so the user knows whether the background loops
    # will keep running while the screen is off / Termux is in the background.
    if hasattr(core, "wakelock") and core.wakelock is not None:
        io.out(f"{timestamp()} {core.wakelock.status()}")
    else:
        io.out(f"{timestamp()} ⚪ Wake-lock: not available (termux-api not installed)")

    debug(io, "Active Threads After Boot:")
    debug(io, list_threads())

    return core, io

# ─────────────────────────────
# COMMAND SHELL
# ─────────────────────────────
def run_shell(core, io):
    global DEBUG_MODE, _active_core
    _active_core = core  # expose to signal handlers

    io.out(f"{timestamp()} READY\n")

    DIRECT_COMMANDS = {
        "help": lambda: core.help_text(),

        "status": lambda: (
            f"[STATUS]\n"
            f"LLM enabled: {core.llm_enabled}\n"
            f"Memory entries: "
            f"{len(core.db.recent_interactions(50)) if hasattr(core.db, 'recent_interactions') else 'N/A'}"
        ),

        "memory": lambda: (
            "\n".join(str(e) for e in core.db.recent_interactions(50))
            if hasattr(core.db, "recent_interactions")
            else "[Memory API missing]"
        ),

        "self-heal": lambda: safe_call(
            getattr(core, "self_healer", None),
            "run_cycle",
            "[SELF-HEAL NOT AVAILABLE]"
        ),

        "self-teach": lambda: safe_call(
            getattr(core, "self_teacher", None),
            "teach",
            "[SELF-TEACH NOT AVAILABLE]"
        ),

        "threads": lambda: list_threads()
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
                except:
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

            # DIRECT COMMANDS
            if cmd in DIRECT_COMMANDS:
                output = log_command(io, cmd, DIRECT_COMMANDS[cmd])
                io.out(output)
                continue

            # ROUTED COMMANDS
            if cmd.startswith(("search ", "summary ", "self-research ", "learn about ")):
                debug(io, f"ROUTER PROCESS → {cmd}")

                if core.router:
                    resp = core.router.process(user_input)
                else:
                    resp = core.handle(user_input)

                debug(io, "ROUTER RESULT RETURNED")
                io.out(resp)
                continue

            # FINAL TRACE
            debug(io, "Passing to core.handle()")
            response = core.handle(user_input)
            io.out(response)

            # Suggestion engine
            sug = suggest_command(cmd)
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
if __name__ == "__main__":
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
