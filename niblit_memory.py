#!/usr/bin/env python3
"""
niblit_memory.py — backward-compatibility shim.

The canonical implementation now lives in the ``niblit_memory/`` package
(``niblit_memory/__init__.py``).  This file re-exports every public symbol so
that any code that once imported from this top-level module file continues to
work without change.

Prefer direct imports from the package going forward::

    from niblit_memory import NiblitMemory        # canonical hub
    from niblit_memory import KnowledgeDB         # unified knowledge DB
    from niblit_memory import KnowledgeStore      # SQLite + Qdrant store
    from niblit_memory import FusedMemory         # SQLite + Qdrant backend
    from niblit_memory import FusedMemoryPrimary  # raw-vector extension
    from niblit_memory import LocalDB             # JSON-backed DB
    from niblit_memory import event, canonicalize, ingest  # ingestion helpers
"""

# Re-export the entire public surface from the canonical package.
from niblit_memory import (  # noqa: F401
    NiblitMemory,
    MemoryManager,
    GLOBAL_MEMORY,
    FusedMemory,
    FusedMemoryPrimary,
    get_fused_memory,
    get_primary,
    KnowledgeDB,
    KnowledgeStore,
    GLOBAL_KNOWLEDGE,
    LocalDB,
    event,
    canonicalize,
    ingest,
)

__all__ = [
    "NiblitMemory",
    "MemoryManager",
    "GLOBAL_MEMORY",
    "FusedMemory",
    "FusedMemoryPrimary",
    "get_fused_memory",
    "get_primary",
    "KnowledgeDB",
    "KnowledgeStore",
    "GLOBAL_KNOWLEDGE",
    "LocalDB",
    "event",
    "canonicalize",
    "ingest",
]



if __name__ == "__main__":
    print('Running niblit_memory.py')
