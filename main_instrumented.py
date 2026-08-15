#!/usr/bin/env python3
"""
MAIN — Niblit AIOS (INSTRUMENTED VERSION)
With detailed execution tracing to identify startup hang location.
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

# Import after path bootstrap
from modules.runtime_bootstrap import bootstrap_runtime_environment

BASE_DIR = str(bootstrap_runtime_environment(__file__))

# Instrumentation logger - set up FIRST before any imports
_INST_LOG = logging.getLogger("BootstrapTrace")
_INST_LOG.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[% (asctime)s][%(levelname)s] %(message)s"))
_INST_LOG.addHandler(_handler)

# ── Path bootstrap before importing local modules ─────────────────────────
_BOOT_STATUS = None
_INST_LOG.info("ENTER: main module import phase")

from modules.resilient_boot import (
    BootStatus,
    load_environment,
    print_boot_status_report,
    probe_event_bus_health,
    scan_optional_dependencies,
)

_INST_LOG.info("ENTER: load_environment")
_BOOT_STATUS = BootStatus()
load_environment(BASE_DIR, _BOOT_STATUS)
_INST_LOG.info("EXIT: load_environment")

_INST_LOG.info("ENTER: scan_optional_dependencies")
scan_optional_dependencies(_BOOT_STATUS)
_INST_LOG.info("EXIT: scan_optional_dependencies")

_INST_LOG.info("ENTER: probe_event_bus_health")
probe_event_bus_health(_BOOT_STATUS)
_INST_LOG.info("EXIT: probe_event_bus_health")

# ── These imports are intentionally placed after environment loading ───
_INST_LOG.info("ENTER: niblit_core import")
from niblit_core import NiblitCore  # pylint: disable=import-outside-toplevel
_INST_LOG.info("EXIT: niblit_core import (complete)")

_INST_LOG.info("ENTER: niblit_io import")
from niblit_io import NiblitIO  # pylint: disable=import-outside-toplevel
_INST_LOG.info("EXIT: niblit_io import (complete)")

_INST_LOG.info("ENTER: structured_logging import")
from modules.structured_logging import configure_runtime_logging, log_exception  # pylint: disable=import-outside-toplevel
_INST_LOG.info("EXIT: structured_logging import (complete)")

# ── Logging configuration ───────────────────────────────────────
_INST_LOG.info("ENTER: logging.basicConfig")
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
)
_INST_LOG.info("EXIT: logging.basicConfig (complete)")

RUNTIME_LOG_FILE = os.getenv("NIBLIT_RUNTIME_LOG_FILE") or os.path.join(BASE_DIR, "runtime.jsonl")
_INST_LOG.info("ENTER: configure_runtime_logging")
RUNTIME_LOGGER = configure_runtime_logging(log_file=RUNTIME_LOG_FILE, level=logging.INFO, name="NiblitRuntime")
_INST_LOG.info("EXIT: configure_runtime_logging (complete)")
_INST_LOG.info("Bootstrap import phase complete")

# ── MAIN WITH INSTRUMENTATION ───────────────────────────────────
_INST_LOG.info("ENTER: boot function")

def boot():
    _INST_LOG.info("ENTER: boot: NiblitCore creation")
    io = NiblitIO()
    _INST_LOG.info("ENTER: NiblitIO created, now NiblitCore()")
    core = NiblitCore()
    _INST_LOG.info("EXIT: NiblitCore() returned (core ready)")
    io.out(f"{datetime.datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')} 🔷 Phase 0 (fast-start) complete — CORE READY")
    _INST_LOG.info("ENTER: _run_staged_runtime_bootstrap")
    from main import _run_staged_runtime_bootstrap
    staged_report = _run_staged_runtime_bootstrap(core, io)
    _INST_LOG.info("EXIT: _run_staged_runtime_bootstrap (complete)")
    return core, io

def main(argv=None):
    _INST_LOG.info("ENTER: main function")
    
    # ── Parse CLI arguments ─────────────────────────────
    _INST_LOG.info("ENTER: parse_args")
    _args = parse_args(argv)
    _INST_LOG.info("EXIT: parse_args (complete)")

    try:
        core, io = boot()
        _INST_LOG.info("ENTER: boot returned successfully")
    except Exception as exc:
        _INST_LOG.error("EXIT: boot FAILED with exception: %s", exc)
        print_boot_status_report(None, _BOOT_STATUS)
        raise

    # ── Block until Phase-1 deferred init is complete ──────────────────
    _INST_LOG.info("ENTER: Phase-1 wait loop")
    _skip_wait = os.getenv("NIBLIT_SKIP_INIT_WAIT", "0").strip() in ("1", "true", "yes")
    
    if not _skip_wait and hasattr(core, "wait_for_ready"):
        _wait_started_at = time.monotonic()
        _max_wait_s = 600.0  # 10 minutes
        
        while True:
            _INST_LOG.info("ENTER: wait_for_ready(timeout=2.0)")
            core.wait_for_ready(timeout=2.0)
            _INST_LOG.info("EXIT: wait_for_ready returned")
            
            _phase = getattr(core, "_deferred_init_phase", "complete")
            _INST_LOG.info("Phase check: _deferred_init_phase = %s", _phase)
            
            if _phase in ("complete", "failed"):
                _INST_LOG.info("Phase %s — breaking wait loop", _phase)
                break
            
            if (time.monotonic() - _wait_started_at) >= _max_wait_s:
                _INST_LOG.warning("Timeout reached in Phase-1 wait loop")
                break
                
            _INST_LOG.info("Waiting for Phase-1... (heartbeat)")
    
    _INST_LOG.info("EXIT: Phase-1 wait loop complete")
    
    # ── Boot status report ─────────────────────────────
    _INST_LOG.info("ENTER: print_boot_status_report")
    print_boot_status_report(io, _BOOT_STATUS)
    _INST_LOG.info("EXIT: print_boot_status_report (complete)")
    
    # ── Desktop/UI check ─────────────────────────────
    _INST_LOG.info("ENTER: _should_launch_desktop check")
    _should_launch = _should_launch_desktop(_args)
    _INST_LOG.info("EXIT: _should_launch_desktop = %s", _should_launch)
    
    if _should_launch:
        _INST_LOG.info("ENTER: Desktop UI launch path")
        try:
            from modules.niblit_ui_launcher import launch_primary_ui
            ui_result = launch_primary_ui(core, io=io, on_status=lambda msg: io.out(f"{datetime.datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')} {msg}"))
            _INST_LOG.info("EXIT: launch_primary_ui (success=%s)", ui_result.success)
        except Exception as _ui_exc:
            _INST_LOG.error("launch_primary_ui FAILED: %s", _ui_exc)
    else:
        _INST_LOG.info("ENTER: CLI shell path (no desktop UI)")
        try:
            run_shell(core, io)
            _INST_LOG.info("EXIT: run_shell (complete)")
        except Exception as e:
            _INST_LOG.error("run_shell FAILED: %s", e)
            traceback.print_exc()
        finally:
            _INST_LOG.info("ENTER: final shutdown")
            if core and getattr(core, "running", False):
                core.shutdown()
            _INST_LOG.info("EXIT: final shutdown (complete)")
    
    _INST_LOG.info("ENTER: stop_sidecar")
    try:
        from modules.niblit_sidecar import stop_sidecar
        stop_sidecar()
    except Exception:
        pass
    _INST_LOG.info("EXIT: stop_sidecar (complete)")
    
    _INST_LOG.info("ENTER: main function complete")
    return 0

# Required functions that main.py has
def _should_launch_desktop(args, *, ui_supported=None) -> bool:
    from main import _should_launch_desktop as real_func
    return real_func(args, ui_supported=ui_supported)

def run_shell(core, io):
    from main import run_shell as real_func
    return real_func(core, io)

def parse_args(argv=None):
    from main import parse_args as real_func
    return real_func(argv)

if __name__ == "__main__":
    main()