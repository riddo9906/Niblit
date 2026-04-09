#!/usr/bin/env python3
"""
modules/ingestion.py — backward-compatibility shim.

The canonical ingestion helpers (event, canonicalize, ingest) now live in
the ``niblit_memory`` package (``niblit_memory/__init__.py``).
This shim re-exports every public symbol so existing imports keep working.
"""
from niblit_memory import event, canonicalize, ingest  # noqa: F401

__all__ = ["event", "canonicalize", "ingest"]


if __name__ == "__main__":
    print('Running ingestion.py')
