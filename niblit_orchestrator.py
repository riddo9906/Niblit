#!/usr/bin/env python3
"""
niblit_orchestrator.py — Niblit Orchestration & Diagnostic Hub

Provides:
  - Repo audit (via tools/repo_audit.py)
  - Self-heal (via tools/self_heal_auto.py)
  - Fix guide generation and execution
  - Import verification
  - Full diagnostics (via run_diagnostics.py)
  - Live command tester (via live_command_tester.py)
  - HuggingFace task integration
  - Full diagnostic pipeline that wires all of the above

All functions print output in real-time (streaming) so progress is visible
during long-running operations.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

# Repo root
REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from tools.repo_audit import RepoAuditor
except Exception as _e:
    RepoAuditor = None

try:
    from tools.self_heal_auto import main as self_heal_main
except Exception as _e:
    self_heal_main = None

try:
    from tools.FixGuideGenerator import FixGuideGenerator
except Exception as _e:
    FixGuideGenerator = None

try:
    from modules.db import LocalDB
except Exception as _e:
    LocalDB = None

# HF query — optional, provided as a stub if niblit_brain doesn't export it
try:
    from niblit_brain import hf_query
except Exception as _e:
    import logging as _log
    _log.getLogger("NiblitOrchestrator").warning(f"hf_query unavailable: {_e}")
    def hf_query(prompt):
        return "[HF query unavailable]"

LOG_FILE = os.path.join(REPO_ROOT, "niblit_orchestrator.log")


def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(msg)


def _run_subprocess_streaming(label: str, script_path: str, timeout: int = 180) -> int:
    """
    Run *script_path* as a subprocess and stream its stdout/stderr to the
    console (and the orchestrator log) line-by-line in real time.

    Returns the process exit code.
    """
    log(f">>> [{label}] Starting: {script_path}")
    try:
        proc = subprocess.Popen(
            [sys.executable, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip("\n")
            print(line)
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        proc.wait(timeout=timeout)
        log(f">>> [{label}] Finished with exit code {proc.returncode}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        log(f">>> [{label}] Timed out after {timeout} s")
        return -1
    except Exception as exc:
        log(f">>> [{label}] Error: {exc}")
        return -1


# ─────────────────────────────────────────────────────
# STEP 1: Repo Audit
# ─────────────────────────────────────────────────────

def run_audit():
    log("=== Step 1: Repo Audit Started ===")
    if RepoAuditor is None:
        log("RepoAuditor unavailable, skipping audit.")
        return None
    auditor = RepoAuditor(REPO_ROOT)
    report = auditor.run_audit()
    log("=== Step 1: Repo Audit Completed ===")
    return report


# ─────────────────────────────────────────────────────
# STEP 2: Self-Heal
# ─────────────────────────────────────────────────────

def run_self_heal():
    log("=== Step 2: Self-Heal Auto Started ===")
    if self_heal_main is None:
        log("self_heal_main unavailable, skipping.")
        return
    try:
        self_heal_main()
        log("=== Step 2: Self-Heal Auto Completed ===")
    except Exception as e:
        log(f"Self-Heal failed: {e}")


# ─────────────────────────────────────────────────────
# STEP 3: Fix Guide
# ─────────────────────────────────────────────────────

def generate_fix_guide():
    log("=== Step 3: Generating Fix Guide ===")
    if FixGuideGenerator is None or LocalDB is None:
        log("FixGuideGenerator or LocalDB unavailable, skipping.")
        return None
    db = LocalDB()
    fg = FixGuideGenerator(db)
    fix_guide_path = os.path.join(REPO_ROOT, "Fix_Guide.txt")
    msg = fg.generate_fix_guide(fix_guide_path)
    log(msg)
    return fix_guide_path


def execute_fix_guide(fix_guide_path):
    log("=== Step 4: Executing Fix Guide ===")
    if not fix_guide_path:
        log("Fix Guide path not provided, skipping.")
        return
    if os.path.exists(fix_guide_path):
        try:
            subprocess.run(["bash", fix_guide_path], check=True)
            log("Fix Guide executed successfully.")
        except Exception as e:
            log(f"Error executing Fix Guide: {e}")
    else:
        log("Fix Guide not found.")


# ─────────────────────────────────────────────────────
# STEP 5: Verify Imports
# ─────────────────────────────────────────────────────

def verify_imports():
    log("=== Step 5: Verifying Module Imports ===")
    modules_to_check = [
        "modules.analytics",
        "modules.bios",
        "modules.control_panel",
        "modules.counter_active_membrane",
        "modules.db",
        "modules.device_manager",
        "modules.evolve",
        "modules.firmware",
        "modules.hf_adapter",
        "modules.idea_generator",
        "modules.internet_manager",
        "modules.llm_adapter",
        "modules.llm_module",
        "modules.local_llm_adapter",
        "modules.market_researcher",
        "modules.orphan_imports",
        "modules.permission_manager",
        "modules.reflect",
        "modules.self_healer",
        "modules.self_idea_implementation",
        "modules.self_maintenance",
        "modules.self_researcher",
        "modules.self_teacher",
        "modules.slsa_generator",
        "modules.storage",
        "modules.terminal_tools",
    ]
    success = 0
    fail = 0
    for mod in modules_to_check:
        try:
            __import__(mod)
            log(f"  ✓  {mod}")
            success += 1
        except Exception as e:
            log(f"  ✗  {mod}: {e}")
            fail += 1
    log(f"Verification completed: {success} success, {fail} failed.")
    return success, fail


# ─────────────────────────────────────────────────────
# STEP 6: Full Diagnostics (run_diagnostics.py)
# ─────────────────────────────────────────────────────

def run_diagnostics():
    """
    Run run_diagnostics.py as a subprocess, streaming all output in real time.
    Returns the exit code (0 = all clear, non-zero = errors found).
    """
    log("=== Step 6: Full Diagnostics Started ===")
    script = os.path.join(REPO_ROOT, "run_diagnostics.py")
    if not os.path.exists(script):
        log(f"run_diagnostics.py not found at {script}, skipping.")
        return -1
    rc = _run_subprocess_streaming("Diagnostics", script, timeout=120)
    log(f"=== Step 6: Full Diagnostics Completed (exit={rc}) ===")
    return rc


# ─────────────────────────────────────────────────────
# STEP 7: Live Command Tester (live_command_tester.py)
# ─────────────────────────────────────────────────────

def run_live_test():
    """
    Run live_command_tester.py as a subprocess, streaming all output in real
    time.  Returns the exit code (0 = all passed, non-zero = failures).
    """
    log("=== Step 7: Live Command Tester Started ===")
    script = os.path.join(REPO_ROOT, "live_command_tester.py")
    if not os.path.exists(script):
        log(f"live_command_tester.py not found at {script}, skipping.")
        return -1
    rc = _run_subprocess_streaming("LiveTest", script, timeout=180)
    log(f"=== Step 7: Live Command Tester Completed (exit={rc}) ===")
    return rc


# ─────────────────────────────────────────────────────
# HF Task
# ─────────────────────────────────────────────────────

def hf_task_example(task_prompt):
    log(f"[HF TASK] Sending prompt: {task_prompt}")
    response = hf_query(task_prompt)
    log(f"[HF TASK] Response: {response}")
    return response


# ─────────────────────────────────────────────────────
# FULL DIAGNOSTIC PIPELINE
# ─────────────────────────────────────────────────────

def run_full_pipeline():
    """
    Execute the complete Niblit orchestration + diagnostic pipeline:
      1. Repo Audit
      2. Self-Heal
      3. Fix Guide generation (+ execution)
      4. Import Verification
      5. Full Diagnostics
      6. Live Command Tester

    Returns a summary dict: {step: exit_code_or_status, ...}
    """
    log("╔══════════════════════════════════════════════════╗")
    log("║         NIBLIT FULL DIAGNOSTIC PIPELINE          ║")
    log("╚══════════════════════════════════════════════════╝")
    summary = {}

    run_audit()
    summary["repo_audit"] = "completed"

    run_self_heal()
    summary["self_heal"] = "completed"

    fix_guide = generate_fix_guide()
    execute_fix_guide(fix_guide)
    summary["fix_guide"] = "completed"

    ok, fail = verify_imports()
    summary["verify_imports"] = f"{ok} ok / {fail} failed"

    diag_rc = run_diagnostics()
    summary["diagnostics"] = "ok" if diag_rc == 0 else f"exit={diag_rc}"

    test_rc = run_live_test()
    summary["live_test"] = "ok" if test_rc == 0 else f"exit={test_rc}"

    # Dynamic column widths
    w_step = max(len(k) for k in summary) + 2
    w_status = max(len(str(v)) for v in summary.values()) + 2
    border = "═" * (w_step + w_status + 6)
    log(f"╔{border}╗")
    log(f"║{'  PIPELINE SUMMARY':<{w_step + w_status + 4}}  ║")
    log(f"╠{border}╣")
    for step, status in summary.items():
        log(f"║  {step:<{w_step}} {str(status):<{w_status}}║")
    log(f"╚{border}╝")
    return summary


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

def main():
    log("=== Niblit Orchestrator Started ===")
    run_audit()
    run_self_heal()

    # Optional: run HF task example
    hf_task_example("Collect factual info from the internet and learn to understand how to think.")

    fix_guide = generate_fix_guide()
    execute_fix_guide(fix_guide)
    verify_imports()

    run_diagnostics()

    log("=== Niblit Orchestrator Completed ===")


if __name__ == "__main__":
    main()
