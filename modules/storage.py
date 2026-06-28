# modules/storage.py
"""Compatibility shim that routes legacy storage imports to the authoritative runtime-owned KnowledgeDB."""

from niblit_memory import KnowledgeDB as KnowledgeDB


__all__ = ["KnowledgeDB"]

if __name__ == "__main__":
    print('Running storage.py')
