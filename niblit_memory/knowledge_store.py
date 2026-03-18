"""
niblit_memory/knowledge_store.py — backward-compatibility shim.

The canonical implementation of KnowledgeStore now lives in
``niblit_memory/__init__.py``.  This shim re-exports it so that
``from niblit_memory.knowledge_store import KnowledgeStore`` keeps working.
"""
from niblit_memory import KnowledgeStore  # noqa: F401

__all__ = ["KnowledgeStore"]

if __name__ == "__main__":
    print("Running niblit_memory/knowledge_store.py")
