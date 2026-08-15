#!/usr/bin/env python3
"""
NIBLIT STARTUP DIAGNOSTICS - Instrumented startup sequence

This file instruments the main.py boot() function to diagnose where startup hangs occur.
Add timing and logging around every major initialization stage.
"""

import time
import sys
import os
import datetime
import logging
import threading

# Set up a dedicated logger for diagnostics
DIAGNOSTIC_LOG = logging.getLogger("NiblitDiagnostics")
DIAGNOSTIC_LOG.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
DIAGNOSTIC_LOG.addHandler(_handler)


def _instrumented_boot():
    """Instrumented boot sequence with detailed timing and logging."""
    
    # Stage 1: Bootstrap
    start_time = time.perf_counter()
    DIAGNOSTIC_LOG.info("=" * 60)
    DIAGNOSTIC_LOG.info("START: bootstrap_runtime_environment")
    DIAGNOSTIC_LOG.info("=" * 60)
    try:
        from modules.runtime_bootstrap import bootstrap_runtime_environment
        BASE_DIR = str(bootstrap_runtime_environment(__file__))
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.info("=" * 60)
        DIAGNOSTIC_LOG.info("END: bootstrap_runtime_environment")
        DIAGNOSTIC_LOG.info(f"Elapsed: {elapsed:.3f}s")
        DIAGNOSTIC_LOG.info("=" * 60)
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.error("bootstrap_runtime_environment FAILED after %.3fs: %s", elapsed, e)
        raise

    # Stage 2: Environment loading
    start_time = time.perf_counter()
    DIAGNOSTIC_LOG.info("=" * 60)
    DIAGNOSTIC_LOG.info("START: load_environment")
    DIAGNOSTIC_LOG.info("=" * 60)
    try:
        from modules.resilient_boot import (
            BootStatus,
            load_environment,
            print_boot_status_report,
            probe_event_bus_health,
            scan_optional_dependencies,
        )
        _BOOT_STATUS = BootStatus()
        load_environment(BASE_DIR, _BOOT_STATUS)
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.info("=" * 60)
        DIAGNOSTIC_LOG.info("END: load_environment")
        DIAGNOSTIC_LOG.info(f"Elapsed: {elapsed:.3f}s")
        DIAGNOSTIC_LOG.info("=" * 60)
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.error("load_environment FAILED after %.3fs: %s", elapsed, e)
        raise

    # Stage 3: NiblitCore construction
    start_time = time.perf_counter()
    DIAGNOSTIC_LOG.info("=" * 60)
    DIAGNOSTIC_LOG.info("START: NiblitCore construction")
    DIAGNOSTIC_LOG.info("=" * 60)
    try:
        # These imports are intentionally placed after environment loading
        from niblit_core import NiblitCore
        from niblit_io import NiblitIO
        from modules.structured_logging import configure_runtime_logging, log_exception
        
        core = NiblitCore()
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.info("=" * 60)
        DIAGNOSTIC_LOG.info("END: NiblitCore construction")
        DIAGNOSTIC_LOG.info(f"Elapsed: {elapsed:.3f}s")
        DIAGNOSTIC_LOG.info("=" * 60)
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.error("NiblitCore construction FAILED after %.3fs: %s", elapsed, e)
        raise

    # Stage 4: Sidecar startup
    start_time = time.perf_counter()
    DIAGNOSTIC_LOG.info("=" * 60)
    DIAGNOSTIC_LOG.info("START: sidecar startup")
    DIAGNOSTIC_LOG.info("=" * 60)
    try:
        from modules.niblit_sidecar import start_sidecar as _start_sidecar
        _sidecar = _start_sidecar(core_getter=lambda: core)
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.info("=" * 60)
        DIAGNOSTIC_LOG.info("END: sidecar startup")
        DIAGNOSTIC_LOG.info(f"Elapsed: {elapsed:.3f}s")
        DIAGNOSTIC_LOG.info("=" * 60)
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        DIAGNOSTIC_LOG.error("sidecar startup FAILED after %.3fs: %s", elapsed, e)
        raise

    return core


if __name__ == "__main__":
    try:
        core = _instrumented_boot()
        print(f"Core ready: {core is not None}")
    except Exception as e:
        print(f"Startup failed: {e}")
        sys.exit(1)