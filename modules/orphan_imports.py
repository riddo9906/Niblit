#!/usr/bin/env python3
import importlib
import traceback
import datetime
import os

LOG_FILE = "niblit_orphan_fix.log"


def log(msg):
    timestamp = datetime.datetime.now()
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {msg}\n")


def try_import(module_name):
    """Attempt to import a module and log success or failure."""
    try:
        importlib.import_module(module_name)
        log(f"SUCCESS: Loaded {module_name}")
        return True
    except Exception as e:
        log(f"FAILED: {module_name} — {str(e)}")
        log(traceback.format_exc())
        return False


def run_orphan_fix():
    log("===== NIBLIT ORPHAN + MISSING MODULE FIX STARTED =====")

    # ------------------------------------------------------
    # MODULES THAT MUST EXIST EXACTLY AS PER YOUR TREE
    # ------------------------------------------------------
    missing_modules = [
        "modules.db",                 # FIXED
        "tools.structural_helper",    # FIXED
    ]

    # ------------------------------------------------------
    # MODULES THAT SHOULD AUTO-LOAD AS PART OF NIBLIT
    # ------------------------------------------------------
    orphan_modules = [
        "main",
        "niblit_net",
        "server",
        "niblit_memory",
        "app",
        "hf_test",
        "modules.llm_adapter",
        "modules.internet_manager",
        "modules.evolve",
        "tools.repo_audit",
        "tools.structural_helper",
        "tools.FixGuideGenerator"
    ]

    log("Checking missing modules...")
    for module in missing_modules:
        try_import(module)

    log("Checking orphan modules...")
    for module in orphan_modules:
        try_import(module)

    log("===== NIBLIT ORPHAN + MISSING MODULE FIX COMPLETED =====")


if __name__ == "__main__":
    run_orphan_fix()
