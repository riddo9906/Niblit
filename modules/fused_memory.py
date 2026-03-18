#!/usr/bin/env python3
"""
modules/fused_memory.py — backward-compatibility shim.

The canonical implementation of FusedMemory now lives in the
``niblit_memory`` package (``niblit_memory/__init__.py``).
This shim re-exports every public symbol so existing imports keep working.
"""
from niblit_memory import (  # noqa: F401
    FusedMemory,
    get_fused_memory,
    FusedMemoryPrimary,
)
