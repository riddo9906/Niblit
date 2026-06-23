#!/usr/bin/env python3
"""Qdrant adapter proxying all access through HybridQdrantManager."""

from __future__ import annotations


class QdrantAdapter:
    """
    LOCKED ADAPTER LAYER

    This adapter is NO LONGER a Qdrant manager.

    It ONLY proxies through HybridQdrantManager.
    """

    def __init__(self, hybrid_manager):
        self.hybrid = hybrid_manager

    def insert_vector(self, *args, **kwargs):
        return self.hybrid.insert(*args, **kwargs)

    def query(self, *args, **kwargs):
        return self.hybrid.query(*args, **kwargs)


if __name__ == "__main__":
    print("Running qdrant_adapter.py")
