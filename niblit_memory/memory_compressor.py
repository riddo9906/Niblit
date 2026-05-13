#!/usr/bin/env python3
"""
niblit_memory/memory_compressor.py — Phase 21 Memory Compression Layer

As Niblit's runtime grows, unbounded memory leads to context drift, slow
retrieval, recursive noise, and degraded evolution quality.  This module
provides periodic memory hygiene functions:

Functions
---------
``summarise_old_epochs(kb, max_age_days)``
    Compress interactions older than *max_age_days* into a single summary
    KB fact, removing the originals.

``merge_redundant_patterns(kb, similarity_threshold)``
    Find KB facts whose text is near-duplicate (above similarity threshold)
    and merge them into a single canonical fact.

``importance_decay(kb, decay_factor, min_score)``
    Reduce the relevance weight of low-access facts over time.  Facts
    that fall below *min_score* are pruned.

``preserve_anchor_memories(kb, anchors)``
    Mark a list of fact keys as permanent (protected from decay/pruning).

``run_compression_cycle(kb)``
    Run all four functions in the recommended order.

Configuration (env vars)
------------------------
    NIBLIT_MC_ENABLED          — "0" to disable (default 1)
    NIBLIT_MC_MAX_AGE_DAYS     — epoch summarisation threshold (default 30)
    NIBLIT_MC_DECAY_FACTOR     — per-cycle decay multiplier (default 0.9)
    NIBLIT_MC_MIN_SCORE        — prune threshold (default 0.05)
    NIBLIT_MC_SIM_THRESHOLD    — near-duplicate cosine sim threshold (default 0.92)

Usage::

    from niblit_memory.memory_compressor import run_compression_cycle

    run_compression_cycle(kb=None)   # uses NiblitMemory singleton if kb is None
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_MC_ENABLED", "1").strip() not in ("0", "false")
_MAX_AGE_DAYS: float = float(os.getenv("NIBLIT_MC_MAX_AGE_DAYS", "30"))
_DECAY_FACTOR: float = float(os.getenv("NIBLIT_MC_DECAY_FACTOR", "0.9"))
_MIN_SCORE: float = float(os.getenv("NIBLIT_MC_MIN_SCORE", "0.05"))
_SIM_THRESHOLD: float = float(os.getenv("NIBLIT_MC_SIM_THRESHOLD", "0.92"))

# Keys that should never be pruned
_ANCHOR_KEYS: Set[str] = {
    "niblit_identity",
    "niblit_purpose",
    "niblit_core_goals",
    "niblit_constitutional_rules",
}


# ── Text similarity helper (pure stdlib, no heavy dependencies) ───────────────

def _token_set(text: str) -> set:
    """Return a normalised token set from *text*."""
    return set(text.lower().split())


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# ── Core compression functions ────────────────────────────────────────────────

def summarise_old_epochs(kb: Any = None, max_age_days: float = _MAX_AGE_DAYS) -> Dict:
    """Compress old interaction epochs into single summary KB facts.

    Finds facts whose keys match ``interaction:*`` or ``ale_*`` patterns and
    are older than *max_age_days*, groups them by day, writes a summary
    fact per group, and deletes the originals.

    Args:
        kb:           Knowledge base object exposing ``list_facts()``,
                      ``store_fact()``, and ``delete_fact()`` methods.
                      If ``None``, the NiblitMemory singleton is used.
        max_age_days: Facts older than this many days are eligible.

    Returns:
        Dict with keys: ``summarised``, ``deleted``, ``skipped``.
    """
    result = {"summarised": 0, "deleted": 0, "skipped": 0}
    if not _ENABLED:
        return result

    kb = _resolve_kb(kb)
    if kb is None:
        return result

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
    cutoff_ts = cutoff.isoformat()

    try:
        facts = kb.list_facts(limit=500) if hasattr(kb, "list_facts") else []
    except Exception as exc:
        log.debug("[MemoryCompressor] list_facts failed: %s", exc)
        return result

    # Group old interaction facts by date prefix
    epoch_groups: Dict[str, List[dict]] = {}
    for fact in facts:
        key = fact.get("key") or fact.get("fact") or ""
        ts = fact.get("ts") or fact.get("timestamp") or ""
        if not ts or ts > cutoff_ts:
            result["skipped"] += 1
            continue
        if not (key.startswith("interaction:") or key.startswith("ale_")):
            result["skipped"] += 1
            continue
        day = ts[:10]  # YYYY-MM-DD
        epoch_groups.setdefault(day, []).append(fact)

    for day, group in epoch_groups.items():
        if len(group) < 2:
            continue
        summary_key = f"epoch_summary:{day}"
        texts = [f.get("value") or f.get("text") or "" for f in group]
        summary_text = f"[{day}] {len(group)} interactions. Topics: " + "; ".join(
            t[:60] for t in texts[:5]
        )
        try:
            if hasattr(kb, "store_fact"):
                kb.store_fact(summary_key, summary_text)
            for f in group:
                fkey = f.get("key") or f.get("fact") or ""
                if fkey and hasattr(kb, "delete_fact"):
                    kb.delete_fact(fkey)
                    result["deleted"] += 1
            result["summarised"] += 1
            log.info("[MemoryCompressor] Epoch %s summarised (%d facts)", day, len(group))
        except Exception as exc:
            log.debug("[MemoryCompressor] summarise epoch %s failed: %s", day, exc)

    return result


def merge_redundant_patterns(kb: Any = None, sim_threshold: float = _SIM_THRESHOLD) -> Dict:
    """Merge near-duplicate KB facts into a single canonical entry.

    Uses Jaccard token similarity to find pairs of facts with text overlap
    above *sim_threshold*.  The longer / more recent fact is kept; the
    other is deleted.

    Args:
        kb:             Knowledge base (same interface as above).
        sim_threshold:  Minimum Jaccard similarity to consider facts duplicates.

    Returns:
        Dict with keys: ``merged``, ``evaluated``.
    """
    result = {"merged": 0, "evaluated": 0}
    if not _ENABLED:
        return result

    kb = _resolve_kb(kb)
    if kb is None:
        return result

    try:
        facts = kb.list_facts(limit=300) if hasattr(kb, "list_facts") else []
    except Exception:
        return result

    # Build list of (key, text, token_set) tuples
    entries = []
    for f in facts:
        key = f.get("key") or f.get("fact") or ""
        text = f.get("value") or f.get("text") or ""
        if key and text and key not in _ANCHOR_KEYS:
            entries.append((key, text, _token_set(text)))

    to_delete: Set[str] = set()
    for i in range(len(entries)):
        if entries[i][0] in to_delete:
            continue
        for j in range(i + 1, len(entries)):
            if entries[j][0] in to_delete:
                continue
            sim = _jaccard(entries[i][2], entries[j][2])
            result["evaluated"] += 1
            if sim >= sim_threshold:
                # Keep the longer text (more informative)
                if len(entries[i][1]) >= len(entries[j][1]):
                    to_delete.add(entries[j][0])
                else:
                    to_delete.add(entries[i][0])
                    break

    for key in to_delete:
        try:
            if hasattr(kb, "delete_fact"):
                kb.delete_fact(key)
            result["merged"] += 1
        except Exception:
            pass

    if to_delete:
        log.info("[MemoryCompressor] Merged %d redundant patterns", len(to_delete))
    return result


def importance_decay(
    kb: Any = None,
    decay_factor: float = _DECAY_FACTOR,
    min_score: float = _MIN_SCORE,
) -> Dict:
    """Apply temporal decay to knowledge scores, pruning below *min_score*.

    For each fact, reduces its internal ``score`` field by *decay_factor*.
    Facts (other than anchors) whose score falls below *min_score* are pruned.

    Args:
        kb:           Knowledge base.
        decay_factor: Multiplier applied to each fact's score (default 0.9).
        min_score:    Minimum score before pruning (default 0.05).

    Returns:
        Dict with keys: ``decayed``, ``pruned``, ``protected``.
    """
    result = {"decayed": 0, "pruned": 0, "protected": 0}
    if not _ENABLED:
        return result

    kb = _resolve_kb(kb)
    if kb is None:
        return result

    try:
        facts = kb.list_facts(limit=500) if hasattr(kb, "list_facts") else []
    except Exception:
        return result

    for fact in facts:
        key = fact.get("key") or fact.get("fact") or ""
        if key in _ANCHOR_KEYS:
            result["protected"] += 1
            continue

        score = float(fact.get("score", 1.0))
        new_score = score * decay_factor
        result["decayed"] += 1

        if new_score < min_score:
            try:
                if hasattr(kb, "delete_fact"):
                    kb.delete_fact(key)
                result["pruned"] += 1
                log.debug("[MemoryCompressor] Pruned low-score fact: %s (score=%.4f)", key, new_score)
            except Exception:
                pass

    return result


def preserve_anchor_memories(kb: Any = None, anchors: Optional[List[str]] = None) -> int:
    """Register additional fact keys as permanent anchors.

    Args:
        kb:      Knowledge base (used to confirm the facts exist).
        anchors: Extra key strings to protect from decay.

    Returns:
        Number of new anchors registered.
    """
    added = 0
    if anchors:
        for key in anchors:
            if key not in _ANCHOR_KEYS:
                _ANCHOR_KEYS.add(key)
                added += 1
    return added


def run_compression_cycle(kb: Any = None) -> Dict:
    """Run the full compression pipeline: summarise → merge → decay.

    Args:
        kb: Knowledge base to compress.  ``None`` → use NiblitMemory singleton.

    Returns:
        Combined result dict from all three steps.
    """
    if not _ENABLED:
        return {"skipped": True}

    kb = _resolve_kb(kb)
    result: Dict = {"timestamp": datetime.now(tz=timezone.utc).isoformat()}

    result["epochs"] = summarise_old_epochs(kb)
    result["merge"]  = merge_redundant_patterns(kb)
    result["decay"]  = importance_decay(kb)

    log.info(
        "[MemoryCompressor] Cycle complete: epochs=%s merge=%s decay=%s",
        result["epochs"], result["merge"], result["decay"],
    )
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_kb(kb: Any) -> Any:
    """Return *kb* unchanged, or the NiblitMemory singleton if *kb* is None."""
    if kb is not None:
        return kb
    try:
        from niblit_memory import NiblitMemory
        return NiblitMemory()
    except Exception as exc:
        log.debug("[MemoryCompressor] Could not resolve KB: %s", exc)
        return None
