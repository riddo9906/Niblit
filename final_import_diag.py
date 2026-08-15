#!/usr/bin/env python3
"""
FINAL DIAGNOSTIC - Pinpoint exact blocking operation in NiblitCore import
"""

import time
import sys
import os
import datetime
import logging

# Set up a dedicated logger for diagnostics
DIAG_LOG = logging.getLogger("FinalDiag")
DIAG_LOG.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
DIAG_LOG.addHandler(_handler)

_checkpoint_count = 0

def _checkpoint(msg: str):
    """Log a numbered checkpoint."""
    global _checkpoint_count
    _checkpoint_count += 1
    t = time.time()
    DIAG_LOG.info(f"[DIAG {_checkpoint_count:03d}] {msg} (t={t:.1f})")


def trace_module_imports():
    """Trace imports line by line."""
    _checkpoint("starting import trace")
    
    # Check if any of the problematic imports exist and when they load
    _checkpoint("checking modules.vector_store import")
    try:
        import modules.vector_store as vs
        _checkpoint("modules.vector_store import ready (no SentenceTransformer load yet)")
    except Exception as e:
        _checkpoint(f"modules.vector_store import failed: {e}")

    _checkpoint("checking modules.embedding_engine import")
    try:
        import modules.embedding_engine as ee
        _checkpoint("modules.embedding_engine import ready")
    except Exception as e:
        _checkpoint(f"modules.embedding_engine import failed: {e}")

    _checkpoint("checking modules.hybrid_qdrant_manager import")
    try:
        import modules.hybrid_qdrant_manager as hqm
        _checkpoint("modules.hybrid_qdrant_manager import ready")
    except Exception as e:
        _checkpoint(f"modules.hybrid_qdrant_manager import failed: {e}")

    _checkpoint("checking modules.llm_adapter import")
    try:
        import modules.llm_adapter as la
        _checkpoint("modules.llm_adapter import ready (llm instance created at module level)")
    except Exception as e:
        _checkpoint(f"modules.llm_adapter import failed: {e}")

    _checkpoint("checking modules.internet_manager import")
    try:
        import modules.internet_manager as im
        _checkpoint("modules.internet_manager import ready")
    except Exception as e:
        _checkpoint(f"modules.internet_manager import failed: {e}")

    _checkpoint("import trace complete")


if __name__ == "__main__":
    try:
        start_time = time.time()
        trace_module_imports()
        elapsed = time.time() - start_time
        _checkpoint(f"completed in {elapsed:.1f}s")
        print(f"Import trace completed in {elapsed:.1f}s")
    except Exception as e:
        _checkpoint(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)