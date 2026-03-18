#!/usr/bin/env python3
"""
modules/knowledge_db.py — backward-compatibility shim.

The canonical implementation of KnowledgeDB now lives in the
``niblit_memory`` package (``niblit_memory/__init__.py``).
This shim re-exports every public symbol so existing imports keep working.
"""
from niblit_memory import KnowledgeDB, GLOBAL_KNOWLEDGE  # noqa: F401

__all__ = ["KnowledgeDB", "GLOBAL_KNOWLEDGE"]
