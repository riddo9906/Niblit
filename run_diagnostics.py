#!/usr/bin/env python3
"""
run_diagnostics.py — Niblit Error Diagnostic Runner

Seeks out runtime errors by attempting to import and boot all core components
from main.py (non-interactively), then reports exactly what is broken.

Usage:
    python run_diagnostics.py

Output:
    - Prints a structured error report to stdout/stderr
    - Saves niblit_diagnostics.json with full details
    - Exits with code 0 (all clear) or 1 (errors found)
"""

import os
import sys
import json
import time
import traceback
import datetime

# ─────────────────────────────
# PATH SETUP (matches main.py)
# ─────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

REPORT_PATH = os.path.join(BASE_DIR, "niblit_diagnostics.json")

# ─────────────────────────────
# HELPERS
# ─────────────────────────────
def timestamp():
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

def _section(title):
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)

def _ok(label):
    print(f"  ✓  {label}")

def _fail(label, err, tb=""):
    print(f"  ✗  {label}")
    print(f"     ERROR: {err}")
    if tb:
        for line in tb.strip().splitlines():
            print(f"       {line}")

# ─────────────────────────────
# CORE IMPORT PROBES
# ─────────────────────────────
CORE_IMPORTS = [
    ("NiblitCore",    "niblit_core",   "NiblitCore"),
    ("NiblitIO",      "niblit_io",     "NiblitIO"),
    ("NiblitRouter",  "niblit_router", "NiblitRouter"),
    ("NiblitBrain",   "niblit_brain",  "NiblitBrain"),
    ("NiblitMemory",  "niblit_memory", "NiblitMemory"),
    ("NiblitGuard",   "niblit_guard",  "NiblitGuard"),
    ("NiblitIdentity","niblit_identity","NiblitIdentity"),
    ("NiblitActions", "niblit_actions","NiblitActions"),
    ("NiblitTasks",   "niblit_tasks",  "NiblitTasks"),
    ("NiblitManager", "niblit_manager","NiblitManager"),
    ("safe_call",     "niblit_router", "safe_call"),
]

def probe_imports():
    """Try importing every core component and record successes/failures."""
    results = {}
    for label, module_name, attr in CORE_IMPORTS:
        try:
            mod = __import__(module_name)
            if hasattr(mod, attr):
                results[label] = {"status": "ok", "error": None, "tb": None}
            else:
                results[label] = {
                    "status": "missing_attr",
                    "error": f"Module '{module_name}' imported but '{attr}' not found",
                    "tb": None,
                }
        except Exception as exc:
            results[label] = {
                "status": "import_error",
                "error": str(exc),
                "tb": traceback.format_exc(),
            }
    return results

# ─────────────────────────────
# BOOT PROBE (mirrors main.py boot())
# ─────────────────────────────
def probe_boot():
    """
    Mirrors the boot() function from main.py:
        io  = NiblitIO()
        core = NiblitCore()
    Captures any exception raised during construction.
    """
    result = {"io": None, "core": None, "error": None, "tb": None}
    io_obj = None
    core_obj = None
    try:
        from niblit_io import NiblitIO
        io_obj = NiblitIO()
        result["io"] = "ok"
    except Exception as exc:
        result["io"] = "error"
        result["error"] = str(exc)
        result["tb"] = traceback.format_exc()
        return result, None, None

    try:
        from niblit_core import NiblitCore
        core_obj = NiblitCore()
        result["core"] = "ok"
    except Exception as exc:
        result["core"] = "error"
        result["error"] = str(exc)
        result["tb"] = traceback.format_exc()

    return result, io_obj, core_obj

# ─────────────────────────────
# RUNTIME PROBES
# ─────────────────────────────
def probe_runtime(core, io):
    """
    Exercise the core object with the same calls main.py makes during a
    typical session, without blocking on user input.
    """
    checks = {}

    # help_text()
    try:
        out = core.help_text()
        checks["core.help_text()"] = {"status": "ok", "error": None, "tb": None}
    except Exception as exc:
        checks["core.help_text()"] = {
            "status": "error", "error": str(exc), "tb": traceback.format_exc()
        }

    # core.db.recent_interactions()
    try:
        if hasattr(core, "db") and hasattr(core.db, "recent_interactions"):
            entries = core.db.recent_interactions(5)
            checks["core.db.recent_interactions()"] = {"status": "ok", "error": None, "tb": None}
        else:
            checks["core.db.recent_interactions()"] = {
                "status": "missing",
                "error": "core.db or recent_interactions() not available",
                "tb": None,
            }
    except Exception as exc:
        checks["core.db.recent_interactions()"] = {
            "status": "error", "error": str(exc), "tb": traceback.format_exc()
        }

    # core.handle() with a benign query
    try:
        resp = core.handle("hello")
        checks["core.handle('hello')"] = {"status": "ok", "error": None, "tb": None}
    except Exception as exc:
        checks["core.handle('hello')"] = {
            "status": "error", "error": str(exc), "tb": traceback.format_exc()
        }

    # core.router presence
    try:
        has_router = core.router is not None
        checks["core.router"] = {
            "status": "ok" if has_router else "missing",
            "error": None if has_router else "core.router is None",
            "tb": None,
        }
    except Exception as exc:
        checks["core.router"] = {
            "status": "error", "error": str(exc), "tb": traceback.format_exc()
        }

    # self_healer presence
    try:
        healer = getattr(core, "self_healer", None)
        checks["core.self_healer"] = {
            "status": "ok" if healer else "missing",
            "error": None if healer else "core.self_healer is None/Stub",
            "tb": None,
        }
    except Exception as exc:
        checks["core.self_healer"] = {
            "status": "error", "error": str(exc), "tb": traceback.format_exc()
        }

    # core.shutdown()
    try:
        core.shutdown()
        checks["core.shutdown()"] = {"status": "ok", "error": None, "tb": None}
    except Exception as exc:
        checks["core.shutdown()"] = {
            "status": "error", "error": str(exc), "tb": traceback.format_exc()
        }

    return checks

# ─────────────────────────────
# MODULE-LEVEL IMPORTS (modules/)
# ─────────────────────────────
MODULE_IMPORTS = [
    ("modules.knowledge_db",  "KnowledgeDB"),
    ("modules.hf_brain",      "HFBrain"),
    ("modules.self_healer",   "SelfHealer"),
    ("modules.self_teacher",  "SelfTeacher"),
    ("modules.self_researcher","SelfResearcher"),
    ("modules.llm_adapter",   "LLMAdapter"),
    ("modules.reflect",       "ReflectModule"),
    ("modules.circuit_breaker","CircuitBreaker"),
    ("modules.rate_limiting",  "RateLimiter"),
    ("modules.metrics_observability","TelemetryCollector"),
    ("modules.event_sourcing", "EventStore"),
    ("modules.db",             "LocalDB"),
    ("modules.storage",        "KnowledgeDB"),
    ("modules.analytics",      "AnalyticsModule"),
    # Code tools
    ("modules.code_compiler",  "CodeCompiler"),
    ("modules.code_generator", "CodeGenerator"),
    ("modules.code_error_fixer", "CodeErrorFixer"),
]

def probe_code_autofix():
    """Probe that CodeErrorFixer can fix a simple broken Python snippet."""
    result = {}
    try:
        import importlib
        fixer_mod = importlib.import_module("modules.code_error_fixer")
        compiler_mod = importlib.import_module("modules.code_compiler")
        fixer = fixer_mod.CodeErrorFixer()
        compiler = compiler_mod.CodeCompiler()
        broken = "def foo()\n    return 1\n"
        fixed_code, ok, explanation = fixer.fix_syntax_errors("python", broken, "SyntaxError", compiler)
        result["code_autofix"] = {
            "status": "ok" if ok else "warning",
            "error": None if ok else f"Auto-fix did not succeed: {explanation}",
            "tb": None,
        }
    except Exception as exc:
        result["code_autofix"] = {
            "status": "error",
            "error": str(exc),
            "tb": traceback.format_exc(),
        }
    return result

def probe_modules():
    results = {}
    for module_name, attr in MODULE_IMPORTS:
        try:
            import importlib
            mod = importlib.import_module(module_name)
            if hasattr(mod, attr):
                results[f"{module_name}.{attr}"] = {"status": "ok", "error": None, "tb": None}
            else:
                results[f"{module_name}.{attr}"] = {
                    "status": "missing_attr",
                    "error": f"Attribute '{attr}' not in '{module_name}'",
                    "tb": None,
                }
        except Exception as exc:
            results[f"{module_name}.{attr}"] = {
                "status": "import_error",
                "error": str(exc),
                "tb": traceback.format_exc(),
            }
    return results

# ─────────────────────────────
# PRINT REPORT
# ─────────────────────────────
def print_report(import_results, boot_result, runtime_checks, module_results, autofix_results, elapsed):
    total_errors = 0

    _section("1. CORE IMPORT CHECKS")
    for label, res in import_results.items():
        if res["status"] == "ok":
            _ok(label)
        else:
            total_errors += 1
            _fail(label, res["error"], res.get("tb", ""))

    _section("2. BOOT SEQUENCE (mirrors main.py boot())")
    if boot_result["io"] == "ok":
        _ok("NiblitIO()")
    else:
        total_errors += 1
        _fail("NiblitIO()", boot_result["error"], boot_result.get("tb", ""))

    if boot_result["core"] == "ok":
        _ok("NiblitCore()")
    elif boot_result["core"] is None:
        print("  -  NiblitCore() — skipped (IO failed first)")
    else:
        total_errors += 1
        _fail("NiblitCore()", boot_result["error"], boot_result.get("tb", ""))

    _section("3. RUNTIME CHECKS (post-boot)")
    if runtime_checks:
        for label, res in runtime_checks.items():
            if res["status"] == "ok":
                _ok(label)
            elif res["status"] == "missing":
                print(f"  ⚠  {label} — {res['error']}")
            else:
                total_errors += 1
                _fail(label, res["error"], res.get("tb", ""))
    else:
        print("  -  Skipped (boot failed)")

    _section("4. MODULE IMPORT CHECKS (modules/)")
    for label, res in module_results.items():
        if res["status"] == "ok":
            _ok(label)
        else:
            total_errors += 1
            _fail(label, res["error"], res.get("tb", ""))

    _section("5. CODE AUTO-FIX PROBE")
    for label, res in autofix_results.items():
        if res["status"] == "ok":
            _ok(label)
        elif res["status"] == "warning":
            print(f"  ⚠  {label} — {res['error']}")
        else:
            total_errors += 1
            _fail(label, res["error"], res.get("tb", ""))

    _section("SUMMARY")
    print(f"  Elapsed : {elapsed:.2f}s")
    if total_errors == 0:
        print("  Result  : ✓ All checks passed — no errors found")
    else:
        print(f"  Result  : ✗ {total_errors} error(s) found — see details above")

    return total_errors

# ─────────────────────────────
# SAVE JSON REPORT
# ─────────────────────────────
def save_report(import_results, boot_result, runtime_checks, module_results, autofix_results, elapsed, total_errors):
    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "total_errors": total_errors,
        "core_imports": import_results,
        "boot_sequence": boot_result,
        "runtime_checks": runtime_checks or {},
        "module_imports": module_results,
        "code_autofix_probe": autofix_results,
    }
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
        print(f"\n  Report saved → {REPORT_PATH}")
    except Exception as exc:
        print(f"\n  Warning: could not save JSON report: {exc}")

# ─────────────────────────────
# MAIN
# ─────────────────────────────
def main():
    print(f"{timestamp()} Niblit Diagnostic Runner — seeking runtime errors in main.py components")

    start = time.time()

    # 1. Import probes
    import_results = probe_imports()

    # 2. Boot probe
    boot_result, io_obj, core_obj = probe_boot()

    # 3. Runtime probes (only if boot succeeded)
    runtime_checks = None
    if boot_result["core"] == "ok" and core_obj is not None and io_obj is not None:
        runtime_checks = probe_runtime(core_obj, io_obj)

    # 4. Module import probes
    module_results = probe_modules()

    # 5. Code auto-fix probe
    autofix_results = probe_code_autofix()

    elapsed = time.time() - start

    # 6. Print structured report
    total_errors = print_report(import_results, boot_result, runtime_checks, module_results, autofix_results, elapsed)

    # 7. Save JSON report
    save_report(import_results, boot_result, runtime_checks, module_results, autofix_results, elapsed, total_errors)

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
