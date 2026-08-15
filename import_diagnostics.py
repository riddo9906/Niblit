#!/usr/bin/env python3
"""
DETAILED MODULE-LEVEL IMPORT DIAGNOSTICS
Identify exactly which import at module level causes the 3.5 minute hang.
"""

import time
import sys
import os
import datetime
import logging
import threading

# Set up a dedicated logger for diagnostics
DIAG_LOG = logging.getLogger("ModuleImportDiag")
DIAG_LOG.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
DIAG_LOG.addHandler(_handler)

# Checkpoint counter
_checkpoint_count = 0

def _checkpoint(msg: str):
    """Log a numbered checkpoint."""
    global _checkpoint_count
    _checkpoint_count += 1
    t = time.time()
    DIAG_LOG.info(f"[IMPORT {_checkpoint_count:03d}] {msg} (t={t:.1f})")


def _instrumented_niblit_config_import():
    """Instrument the NiblitConfig import path."""
    
    # First, let's see what happens when we try to import niblit_core
    _checkpoint("starting niblit_core package import")
    
    # This import uses __getattr__ lazy loading from niblit_core/__init__.py
    _checkpoint("importing niblit_core package (triggers lazy load)")
    import niblit_core
    _checkpoint("niblit_core package imported (not NiblitConfig yet)")
    
    _checkpoint("importing NiblitConfig from niblit_core")
    from niblit_core import NiblitConfig  # This triggers the actual niblit_core.py load
    _checkpoint("NiblitConfig imported successfully")
    
    return NiblitConfig


if __name__ == "__main__":
    try:
        start_time = time.time()
        t = _instrumented_niblit_config_import()
        elapsed = time.time() - start_time
        _checkpoint(f"completed in {elapsed:.1f}s")
        print(f"NiblitConfig ready: {t is not None}")
    except Exception as e:
        _checkpoint(f"Import FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)