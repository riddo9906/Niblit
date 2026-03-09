#!/usr/bin/env python3
import os
import subprocess
import sys
from datetime import datetime

# Repo root
REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.repo_audit import RepoAuditor
from tools.self_heal_auto import main as self_heal_main
from tools.FixGuideGenerator import FixGuideGenerator
from modules.db import LocalDB

# NEW HF query import
from niblit_brain import hf_query

LOG_FILE = os.path.join(REPO_ROOT, "niblit_orchestrator.log")

def log(msg):
    ts = datetime.utcnow().isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(msg)

# Audit
def run_audit():
    log("=== Step 1: Repo Audit Started ===")
    auditor = RepoAuditor(REPO_ROOT)
    report = auditor.run_audit()
    log("=== Step 1: Repo Audit Completed ===")
    return report

# Self-Heal
def run_self_heal():
    log("=== Step 2: Self-Heal Auto Started ===")
    try:
        self_heal_main()
        log("=== Step 2: Self-Heal Auto Completed ===")
    except Exception as e:
        log(f"Self-Heal failed: {e}")

# Fix Guide
def generate_fix_guide():
    log("=== Step 3: Generating Fix Guide ===")
    db = LocalDB()
    fg = FixGuideGenerator(db)
    fix_guide_path = os.path.join(REPO_ROOT, "Fix_Guide.txt")
    msg = fg.generate_fix_guide(fix_guide_path)
    log(msg)
    return fix_guide_path

def execute_fix_guide(fix_guide_path):
    log("=== Step 4: Executing Fix Guide ===")
    if os.path.exists(fix_guide_path):
        try:
            subprocess.run(["bash", fix_guide_path], check=True)
            log("Fix Guide executed successfully.")
        except Exception as e:
            log(f"Error executing Fix Guide: {e}")
    else:
        log("Fix Guide not found.")

# Verification
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
        "modules.terminal_tools"
    ]
    success = 0
    fail = 0
    for mod in modules_to_check:
        try:
            __import__(mod)
            log(f"SUCCESS: Imported {mod}")
            success += 1
        except Exception as e:
            log(f"FAILED: Import {mod}: {e}")
            fail += 1
    log(f"Verification completed: {success} success, {fail} failed.")

# -----------------------------
# Example HF integration point in orchestrator
# -----------------------------
def hf_task_example(task_prompt):
    log(f"[HF TASK] Sending prompt: {task_prompt}")
    response = hf_query(task_prompt)
    log(f"[HF TASK] Response: {response}")
    return response

# Main
def main():
    log("=== Niblit Orchestrator Started ===")
    run_audit()
    run_self_heal()

    # Optional: run HF task example
    hf_task_example("Collect factual info from the internet and learn to understand how to think.")

    fix_guide = generate_fix_guide()
    execute_fix_guide(fix_guide)
    verify_imports()
    log("=== Niblit Orchestrator Completed ===")

if __name__ == "__main__":
    main()
