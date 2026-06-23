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

# Explicit re-export declaration so that tools (mypy --no-implicit-reexport,
# linters) understand this file intentionally exposes these names.
__all__ = ["FusedMemory", "get_fused_memory", "FusedMemoryPrimary"]


if __name__ == "__main__":
    print('Running fused_memory.py')
