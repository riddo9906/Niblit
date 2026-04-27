"""
niblit_memory/knowledge_store.py — backward-compatibility shim.

The canonical implementation of KnowledgeStore now lives in
``niblit_memory/__init__.py``.  This shim re-exports it so that
``from niblit_memory.knowledge_store import KnowledgeStore`` keeps working.
"""
from __future__ import annotations

__all__ = ["KnowledgeStore"]


def __getattr__(name: str):  # PEP 562 module-level __getattr__
    """Lazy re-export of KnowledgeStore to avoid package self-import cycle."""
    if name == "KnowledgeStore":
        from niblit_memory import KnowledgeStore as _KS  # noqa: PLC0415
        # Cache in module globals so subsequent attribute lookups are fast.
        globals()["KnowledgeStore"] = _KS
        return _KS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

if __name__ == "__main__":
    print("Running niblit_memory/knowledge_store.py")
