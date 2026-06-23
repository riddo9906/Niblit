#!/usr/bin/env python3
"""
modules/knowledge_adapter.py — Knowledge / RAG Adapter
=======================================================
Wraps SelfResearcher, KnowledgeDB / Graph RAG, and search backends so
the :class:`~modules.niblit_cognitive_graph_kernel.CognitiveGraphKernel`
can query and store knowledge during the FortressCycle's ``execute_cycle``
and ``learn_from_results`` phases.

This engine is orchestrated by CognitiveGraphKernel via adapters.
Do not start a standalone infinite loop here.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def query_knowledge(
    query: str,
    universe_id: str = "research_general",
    top_k: int = 5,
    step_timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Query the knowledge base / Graph RAG for *query*.

    Tries (in order):
      1. GraphRAGPipeline.query()
      2. KnowledgeDB.search()
      3. SelfResearcher quick search

    Returns a dict with ``success``, ``facts`` list, ``sources`` list,
    ``elapsed_secs``, ``error``.
    """
    start = time.time()
    facts: List[str] = []
    sources: List[str] = []

    # 1. Graph RAG
    try:
        from modules.graph_rag import get_graph_rag_pipeline
        rag = get_graph_rag_pipeline()
        if hasattr(rag, "query"):
            result = rag.query(query, top_k=top_k)
            if isinstance(result, dict):
                facts.extend(result.get("facts", []) or result.get("results", []))
                sources.extend(result.get("sources", []))
            elif isinstance(result, (list, tuple)):
                facts.extend([str(r) for r in result[:top_k]])
    except Exception:  # noqa: BLE001
        pass

    # 2. KnowledgeDB
    if not facts:
        try:
            from modules.knowledge_db import get_knowledge_db
            db = get_knowledge_db()
            if hasattr(db, "search"):
                rows = db.search(query, limit=top_k)
                facts.extend([str(r) for r in (rows or [])])
            elif hasattr(db, "query"):
                rows = db.query(query)
                facts.extend([str(r) for r in (rows or [])])
        except Exception:  # noqa: BLE001
            pass

    # 3. SelfResearcher fallback
    if not facts:
        try:
            import importlib
            sr = importlib.import_module("SelfResearcher")
            researcher = getattr(sr, "SelfResearcher", None)
            if researcher is not None:
                r = researcher()
                out = r.research(query) if hasattr(r, "research") else None
                if out:
                    facts.append(str(out)[:500])
        except Exception:  # noqa: BLE001
            pass

    elapsed = round(time.time() - start, 2)
    return {
        "success": bool(facts),
        "universe_id": universe_id,
        "query": query,
        "facts": facts[:top_k],
        "sources": sources,
        "elapsed_secs": elapsed,
        "error": None if facts else "No results found",
    }


def store_facts(
    facts: List[str],
    provenance: Optional[str] = None,
    universe_id: str = "research_general",
) -> Dict[str, Any]:
    """
    Store a list of *facts* into KnowledgeDB / Graph RAG.

    Returns a dict with ``success``, ``stored_count``, ``error``.
    """
    stored = 0
    errors: List[str] = []

    for fact in facts:
        try:
            from modules.knowledge_db import get_knowledge_db
            db = get_knowledge_db()
            key = f"fortress:{universe_id}:{hash(fact) & 0xFFFFFF:06x}"
            if hasattr(db, "store_fact"):
                db.store_fact(key, fact)
            elif hasattr(db, "add"):
                db.add(key, fact)
            stored += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc)[:100])

        # Also write to Graph RAG
        try:
            from modules.graph_rag import get_graph_rag_pipeline
            rag = get_graph_rag_pipeline()
            if hasattr(rag, "add_fact"):
                rag.add_fact(fact, source=provenance or "fortress")
        except Exception:  # noqa: BLE001
            pass

    return {
        "success": stored == len(facts),
        "stored_count": stored,
        "total": len(facts),
        "error": "; ".join(errors) if errors else None,
    }


if __name__ == "__main__":
    print('Running knowledge_adapter.py')
