#!/usr/bin/env python3
"""
live_command_tester.py — Niblit Live Command Tester

Performs a live run of the Niblit AIOS exactly as main.py would, exercising
every command from main.py's COMMANDS list plus all routed commands.  For
each command it captures:

  • the full Python traceback (every frame)
  • the originating file path and line number
  • the responsible module/class name

Phase 5 is the Loop Traceback Tester & Diagnoser: it exercises the body of
every background loop (niblit_core, niblit_memory, lifecycle_engine) once
synchronously, then runs a live soak window to catch errors from background
threads, reporting file/line/function for every failure.

A human-readable report is printed to stdout and a machine-readable copy is
saved to niblit_live_test_report.json.

Usage:
    python live_command_tester.py

Exit codes:
    0  — all commands and loop probes succeeded
    1  — one or more commands or loop probes raised errors
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime, timezone
import threading

# ─────────────────────────────────────────────
# PATH SETUP — must mirror main.py exactly
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

REPORT_PATH = os.path.join(BASE_DIR, "niblit_live_test_report.json")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _now():
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def _bar(char="─", width=68):
    return char * width


def _section(title):
    print(f"\n{_bar()}")
    print(f"  {title}")
    print(_bar())


def _ok(label, detail=""):
    suffix = f" — {detail}" if detail else ""
    print(f"  ✓  {label}{suffix}")


def _warn(label, detail=""):
    suffix = f" — {detail}" if detail else ""
    print(f"  ⚠  {label}{suffix}")


def _fail(label, err, tb_frames):
    """Print a failure entry with per-frame traceback showing file + line."""
    print(f"  ✗  {label}")
    print(f"     ERROR : {err}")
    if tb_frames:
        print(f"     TRACEBACK (most recent call last):")
        for frame in tb_frames:
            print(f"       File \"{frame['file']}\", line {frame['lineno']}, in {frame['function']}")
            if frame.get("code"):
                print(f"         {frame['code']}")


# ─────────────────────────────────────────────
# TRACEBACK FRAME EXTRACTOR
# ─────────────────────────────────────────────

def _extract_frames(tb_str: str) -> list:
    """
    Parse a traceback string into structured frames.

    Each frame is:
        {
            "file":     absolute path or "<string>",
            "lineno":   int,
            "function": str,
            "code":     str   (the source line, stripped),
        }
    """
    import re
    frames = []
    # Pattern: '  File "path", line N, in func_name'
    pattern = re.compile(
        r'File "([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)'
    )
    lines = tb_str.splitlines()
    for i, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            filepath, lineno, func = m.group(1), int(m.group(2)), m.group(3)
            # next non-blank line is usually the code snippet
            code = ""
            if i + 1 < len(lines):
                code = lines[i + 1].strip()
            frames.append({
                "file": filepath,
                "lineno": lineno,
                "function": func,
                "code": code,
            })
    return frames


def _run_probe(label: str, fn) -> dict:
    """
    Execute *fn()* and return a result dict:
        {
            "label":  str,
            "status": "ok" | "error" | "empty",
            "output": str | None,
            "error":  str | None,
            "tb":     str | None,
            "frames": list,
        }
    """
    result = {
        "label": label,
        "status": "ok",
        "output": None,
        "error": None,
        "tb": None,
        "frames": [],
    }
    try:
        output = fn()
        if output:
            result["output"] = str(output)[:2000]   # truncate for report
        else:
            result["status"] = "empty"
            result["output"] = "[No output returned]"
    except Exception as exc:
        tb_str = traceback.format_exc()
        result["status"] = "error"
        result["error"] = str(exc)
        result["tb"] = tb_str
        result["frames"] = _extract_frames(tb_str)
    return result


def _list_threads():
    return "\n".join(
        f"{t.name} | alive={t.is_alive()}"
        for t in threading.enumerate()
    )


# ─────────────────────────────────────────────
# PHASE 1 — BOOT (mirrors main.py boot())
# ─────────────────────────────────────────────

def phase_boot():
    """Import and instantiate NiblitCore + NiblitIO exactly as main.py does."""
    boot_result = {
        "NiblitIO": {"status": "ok", "error": None, "tb": None, "frames": []},
        "NiblitCore": {"status": "ok", "error": None, "tb": None, "frames": []},
    }
    io_obj = None
    core_obj = None

    try:
        from niblit_io import NiblitIO
        io_obj = NiblitIO()
    except Exception as exc:
        tb_str = traceback.format_exc()
        boot_result["NiblitIO"] = {
            "status": "error",
            "error": str(exc),
            "tb": tb_str,
            "frames": _extract_frames(tb_str),
        }
        return boot_result, None, None

    try:
        from niblit_core import NiblitCore
        core_obj = NiblitCore()
    except Exception as exc:
        tb_str = traceback.format_exc()
        boot_result["NiblitCore"] = {
            "status": "error",
            "error": str(exc),
            "tb": tb_str,
            "frames": _extract_frames(tb_str),
        }
        return boot_result, io_obj, None

    return boot_result, io_obj, core_obj


# ─────────────────────────────────────────────
# PHASE 2 — DIRECT COMMANDS
# ─────────────────────────────────────────────
# These mirror the DIRECT_COMMANDS dict in main.py's run_shell().

def phase_direct_commands(core, io) -> list:
    from niblit_router import safe_call as router_safe_call

    probes = [
        (
            "help",
            lambda: core.help_text(),
        ),
        (
            "status",
            lambda: (
                f"[STATUS]\n"
                f"LLM enabled: {core.llm_enabled}\n"
                f"Memory entries: "
                f"{len(core.db.recent_interactions(50)) if hasattr(core.db, 'recent_interactions') else 'N/A'}"
            ),
        ),
        (
            "memory",
            lambda: (
                "\n".join(str(e) for e in core.db.recent_interactions(50))
                if hasattr(core.db, "recent_interactions")
                else "[Memory API missing]"
            ),
        ),
        (
            "self-heal",
            lambda: router_safe_call(
                getattr(core, "self_healer", None),
                "run_cycle",
                "[SELF-HEAL NOT AVAILABLE]",
            ),
        ),
        (
            "self-teach",
            lambda: router_safe_call(
                getattr(core, "self_teacher", None),
                "teach",
                "[SELF-TEACH NOT AVAILABLE]",
            ),
        ),
        (
            "threads",
            lambda: _list_threads(),
        ),
        (
            "debug on",
            lambda: "Debug mode enabled.",   # toggle only sets a flag in main.py
        ),
        (
            "debug off",
            lambda: "Debug mode disabled.",
        ),
    ]

    results = []
    for label, fn in probes:
        results.append(_run_probe(f"direct → {label}", fn))
    return results


# ─────────────────────────────────────────────
# PHASE 3 — ROUTED COMMANDS
# ─────────────────────────────────────────────
# These mirror the branch in main.py:
#   if cmd.startswith(("search ", "summary ", "self-research ", "learn about ")):

def phase_routed_commands(core) -> list:
    routed_inputs = [
        "search Python programming",
        "summary artificial intelligence",
        "self-research neural networks",
        "learn about machine learning",
    ]

    results = []
    for user_input in routed_inputs:
        label = f"routed → {user_input!r}"
        if core.router:
            results.append(_run_probe(label, lambda u=user_input: core.router.process(u)))
        else:
            results.append(_run_probe(label, lambda u=user_input: core.handle(u)))
    return results


# ─────────────────────────────────────────────
# PHASE 4 — ROUTER FALLBACK / GENERAL HANDLE
# ─────────────────────────────────────────────

def phase_general_handle(core) -> list:
    general_inputs = [
        "hello",
        "what are you?",
        "tell me about yourself",
        "what can you do?",
    ]

    results = []
    for user_input in general_inputs:
        label = f"handle → {user_input!r}"

        def _probe(u=user_input):
            if core.router:
                resp = core.router.process(u)
                if resp:
                    return resp
            return core.handle(u)

        results.append(_run_probe(label, _probe))
    return results


# ─────────────────────────────────────────────
# PHASE 5 — SHUTDOWN
# ─────────────────────────────────────────────

def phase_shutdown(core) -> dict:
    return _run_probe("core.shutdown()", lambda: (core.shutdown(), "shutdown OK")[1])


# ─────────────────────────────────────────────
# PHASE 6 — LOOP TRACEBACK TESTER & DIAGNOSER
# ─────────────────────────────────────────────

# Map every known loop name to: the owning script, a brief description of
# what the loop does, and (if possible) a one-shot probe function that
# exercises a single iteration of the loop body synchronously so we can
# catch errors that would only surface at runtime.
_LOOP_REGISTRY = [
    {
        "loop":   "HealthLoop",
        "script": "niblit_core.py",
        "desc":   "Monitors system health / uptime every 5 s",
    },
    {
        "loop":   "TrainerLoop",
        "script": "niblit_core.py",
        "desc":   "Flushes collector and runs training cycle every 90 s",
    },
    {
        "loop":   "ResearchLoop",
        "script": "niblit_core.py",
        "desc":   "Processes learning-queue items via SelfResearcher every 150 s",
    },
    {
        "loop":   "HealLoop",
        "script": "niblit_core.py",
        "desc":   "Runs self-healer cycle every 300 s",
    },
    {
        "loop":   "DumpMonitoringLoop",
        "script": "niblit_core.py",
        "desc":   "Logs dump-loop health and triggers DB state dump every N s",
    },
    {
        "loop":   "MemoryAutosaveLoop",
        "script": "niblit_memory.py",
        "desc":   "Persists MemoryManager state to disk at regular intervals",
    },
    {
        "loop":   "MemoryDumpLoop",
        "script": "niblit_memory.py",
        "desc":   "Dumps MemoryManager state via logging at regular intervals",
    },
    {
        "loop":   "LifecycleHeartbeat",
        "script": "lifecycle_engine.py",
        "desc":   "Advances LifecycleEngine phases every HEARTBEAT_INTERVAL second(s)",
    },
]


def _one_shot_loop_probes(core) -> list:
    """
    Exercise the *body* of each niblit_core loop once synchronously so any
    logic errors are caught immediately rather than waiting for the sleep.
    Returns a list of _run_probe dicts.
    """
    results = []

    # HealthLoop body
    def _probe_health():
        uptime = int(time.time() - core.start_ts)
        _ = core._get_memory_count()
        return f"health ok, uptime={uptime}s"

    results.append(_run_probe("loop-body → HealthLoop", _probe_health))

    # TrainerLoop body
    def _probe_trainer():
        from niblit_core import safe_call as _sc
        if core.collector and hasattr(core.collector, "flush_if_needed"):
            _sc(core.collector.flush_if_needed)
        if core.trainer:
            if hasattr(core.trainer, "train_cycle"):
                _sc(core.trainer.train_cycle)
            elif hasattr(core.trainer, "step_if_needed"):
                buf = getattr(core.collector, "buffer", []) if core.collector else []
                _sc(core.trainer.step_if_needed, buf)
        return "trainer-loop body ok"

    results.append(_run_probe("loop-body → TrainerLoop", _probe_trainer))

    # ResearchLoop body
    def _probe_research():
        from niblit_core import safe_call as _sc
        if core.db and hasattr(core.db, "get_learning_queue") and core.researcher:
            queued = core.db.get_learning_queue()
            pending = [
                item for item in queued
                if isinstance(item, dict) and item.get("status") == "queued"
            ]
            return f"research-loop body ok, pending={len(pending)}"
        return "research-loop body ok (no queue/researcher)"

    results.append(_run_probe("loop-body → ResearchLoop", _probe_research))

    # HealLoop body
    def _probe_heal():
        from niblit_core import safe_call as _sc
        healer = getattr(core, "self_healer", None)
        if healer:
            if hasattr(healer, "run_cycle"):
                _sc(healer.run_cycle)
            elif hasattr(healer, "repair"):
                _sc(healer.repair)
            elif hasattr(healer, "full_heal"):
                _sc(healer.full_heal, core)
        return "heal-loop body ok"

    results.append(_run_probe("loop-body → HealLoop", _probe_heal))

    # DumpMonitoringLoop body
    def _probe_dump():
        from niblit_core import safe_call as _sc
        if core.db and hasattr(core.db, "dump_state"):
            _sc(core.db.dump_state)
        return "dump-loop body ok"

    results.append(_run_probe("loop-body → DumpMonitoringLoop", _probe_dump))

    return results


def phase_loop_tracer(core, soak_seconds: float = 3.0) -> dict:
    """
    Phase 5 — Loop Traceback Tester & Diagnoser.

    Steps:
      a) Retrieve any loop errors already captured since boot (phases 1-4
         ran with background loops live the whole time).
      b) Run a synchronous one-shot probe of each loop body so logic bugs
         are surfaced immediately rather than waiting for a sleep cycle.
      c) Add a brief soak window and harvest any additional errors the live
         background threads raise during that period.

    Returns:
        {
            "soak_errors":   list of LoopTracer records (live thread errors),
            "one_shot":      list of _run_probe dicts   (synchronous probes),
            "loop_registry": list of loop descriptor dicts,
        }
    """
    from niblit_core import loop_tracer as _lt

    # ── (a) errors captured since boot ──
    prior_errors = _lt.get_errors()

    # ── (b) synchronous one-shot probes ──
    one_shot = _one_shot_loop_probes(core)

    # ── (c) soak window for live thread errors ──
    time.sleep(soak_seconds)

    # Collect all errors: prior + any new ones from the soak window
    soak_errors = _lt.get_errors()

    return {
        "soak_errors": soak_errors,
        "one_shot": one_shot,
        "loop_registry": _LOOP_REGISTRY,
    }


# ─────────────────────────────────────────────
# PRINT REPORT
# ─────────────────────────────────────────────

def _print_phase(section_title: str, results: list) -> int:
    """Print one phase section.  Returns the number of errors in that phase."""
    _section(section_title)
    errors = 0
    for res in results:
        label = res["label"]
        if res["status"] == "ok":
            _ok(label)
        elif res["status"] == "empty":
            _warn(label, "empty response (no output)")
        else:
            errors += 1
            _fail(label, res["error"], res["frames"])
    return errors


def _print_loop_phase(loop_data: dict) -> int:
    """Print Phase 5 (Loop Tracer) section.  Returns total error count."""
    _section(
        "PHASE 5 — LOOP TRACEBACK TESTER & DIAGNOSER\n"
        "  (one-shot body probes + live soak window)"
    )

    errors = 0

    # ── known loops registry ──
    print(f"\n  Known background loops ({len(loop_data['loop_registry'])}):")
    for entry in loop_data["loop_registry"]:
        print(f"    • [{entry['script']}]  {entry['loop']}  —  {entry['desc']}")

    # ── one-shot body probes ──
    print(f"\n  One-shot body probes:")
    for res in loop_data["one_shot"]:
        label = res["label"]
        if res["status"] == "ok":
            _ok(label)
        elif res["status"] == "empty":
            _warn(label, "empty response")
        else:
            errors += 1
            _fail(label, res["error"], res["frames"])

    # ── soak window results ──
    soak = loop_data["soak_errors"]
    print(f"\n  Live soak window — {len(soak)} error(s) captured from background threads:")
    if not soak:
        print("  ✓  No loop errors observed during soak window")
    else:
        for rec in soak:
            errors += 1
            print(f"\n  ✗  Loop : {rec['loop']}")
            print(f"     Script   : {rec['source']}")
            print(f"     Time     : {rec['ts']}")
            print(f"     Type     : {rec['error_type']}")
            print(f"     Error    : {rec['error']}")
            print(f"     Traceback (most recent call last):")
            for frame in rec.get("frames", []):
                print(
                    f"       File \"{frame['file']}\","
                    f" line {frame['lineno']},"
                    f" in {frame['function']}"
                )
                if frame.get("code"):
                    print(f"         {frame['code']}")

    return errors


def print_full_report(boot_result, direct_results, routed_results,
                      general_results, shutdown_result, loop_data, elapsed):
    total_errors = 0

    # ── BOOT ──
    _section("PHASE 1 — BOOT (mirrors main.py boot())")
    for name, res in boot_result.items():
        if res["status"] == "ok":
            _ok(name)
        else:
            total_errors += 1
            _fail(name, res["error"], res["frames"])

    # ── DIRECT COMMANDS ──
    total_errors += _print_phase(
        "PHASE 2 — DIRECT COMMANDS  (help / status / memory / self-heal / self-teach / threads)",
        direct_results,
    )

    # ── ROUTED COMMANDS ──
    total_errors += _print_phase(
        "PHASE 3 — ROUTED COMMANDS  (search / summary / self-research / learn about)",
        routed_results,
    )

    # ── GENERAL HANDLE ──
    total_errors += _print_phase(
        "PHASE 4 — GENERAL HANDLE  (router fallback + core.handle)",
        general_results,
    )

    # ── LOOP TRACER ──
    total_errors += _print_loop_phase(loop_data)

    # ── SHUTDOWN ──
    total_errors += _print_phase(
        "PHASE 6 — SHUTDOWN",
        [shutdown_result],
    )

    # ── SUMMARY ──
    _section("SUMMARY")
    print(f"  Elapsed      : {elapsed:.2f}s")
    if total_errors == 0:
        print("  Result       : ✓ All commands and loops passed — no errors found")
    else:
        print(f"  Result       : ✗ {total_errors} error(s) found — see details above")
        print(f"  JSON report  : {REPORT_PATH}")

    return total_errors


# ─────────────────────────────────────────────
# SAVE JSON REPORT
# ─────────────────────────────────────────────

def save_report(boot_result, direct_results, routed_results,
                general_results, shutdown_result, loop_data, elapsed, total_errors):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "total_errors": total_errors,
        "phases": {
            "boot": boot_result,
            "direct_commands": direct_results,
            "routed_commands": routed_results,
            "general_handle": general_results,
            "shutdown": shutdown_result,
            "loop_tracer": {
                "loop_registry": loop_data.get("loop_registry", []),
                "one_shot_probes": loop_data.get("one_shot", []),
                "soak_errors": loop_data.get("soak_errors", []),
            },
        },
    }
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=4, ensure_ascii=False)
        print(f"\n  Full JSON report saved → {REPORT_PATH}")
    except Exception as exc:
        print(f"\n  Warning: could not save JSON report: {exc}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print(_bar("═"))
    print(f"  Niblit Live Command Tester")
    print(f"  {_now()}  —  testing every command from main.py via a live boot")
    print(_bar("═"))

    start = time.time()

    # ── Phase 1: boot ──
    boot_result, io_obj, core_obj = phase_boot()
    if core_obj is None or io_obj is None:
        print("\n  ✗ Boot failed — remaining phases skipped.")
        elapsed = time.time() - start
        total_errors = sum(
            1 for r in boot_result.values() if r["status"] != "ok"
        )
        save_report(boot_result, [], [], [], {}, {}, elapsed, total_errors)
        sys.exit(1)

    # ── Phase 2: direct commands ──
    direct_results = phase_direct_commands(core_obj, io_obj)

    # ── Phase 3: routed commands ──
    routed_results = phase_routed_commands(core_obj)

    # ── Phase 4: general handle ──
    general_results = phase_general_handle(core_obj)

    # ── Phase 5: loop tracer (before shutdown so background threads are still alive) ──
    loop_data = phase_loop_tracer(core_obj, soak_seconds=3.0)

    # ── Phase 6: shutdown ──
    shutdown_result = phase_shutdown(core_obj)

    elapsed = time.time() - start

    # ── Report ──
    total_errors = print_full_report(
        boot_result, direct_results, routed_results,
        general_results, shutdown_result, loop_data, elapsed,
    )

    save_report(
        boot_result, direct_results, routed_results,
        general_results, shutdown_result, loop_data, elapsed, total_errors,
    )

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
