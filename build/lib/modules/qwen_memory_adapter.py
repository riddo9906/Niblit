#!/usr/bin/env python3
"""modules/qwen_memory_adapter.py — Qwen-powered KnowledgeDB manager.

QwenMemoryAdapter gives the local Qwen brain (QwenLocalBrain) the ability to:

  1. **Read** Niblit's KnowledgeDB facts and learning log.
  2. **Audit** individual facts — decide KEEP | REWRITE | REMOVE for each one.
  3. **Fix** the KB in-place by updating or deleting low-quality entries.
  4. **Coach** Niblit — produce an improvement report based on memory state.
  5. **Summarise** memory — return a compact view of what Niblit currently knows.

This makes Qwen the "manager, coach, and trainer" role described in the
problem statement, operating purely on local resources with no cloud calls.

Public API
----------
::

    adapter = QwenMemoryAdapter(local_brain, knowledge_db)
    adapter.get_memory_summary(limit=20)   -> str
    adapter.review_fact(fact)              -> {"action": "keep"|"rewrite"|"remove",
                                               "new_value": str, "reason": str}
    adapter.run_memory_audit(max_facts=30) -> str
    adapter.coach_niblit()                 -> str

    # Singleton accessor
    get_qwen_memory_adapter(local_brain, knowledge_db) -> QwenMemoryAdapter
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("Niblit.QwenMemoryAdapter")

try:
    from niblit_memory import KnowledgeDB  # type: ignore[import]
except Exception:  # pragma: no cover
    KnowledgeDB = None  # type: ignore[assignment,misc]

# Max chars of a single fact value passed to Qwen for review.
_FACT_REVIEW_MAX_CHARS: int = 400
# Max chars of the full memory summary Qwen sees when coaching.
_COACH_CONTEXT_MAX_CHARS: int = 1800
# Number of facts audited per batch (keeps individual prompts small).
_AUDIT_BATCH_SIZE: int = 5
# Tags that mark internal Niblit metadata — skip these during audit.
_SKIP_TAGS: frozenset = frozenset({
    "routing", "loop", "tick", "counter", "step", "system", "meta", "diagnostic",
})

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fact_text(fact: Dict[str, Any]) -> str:
    """Return a readable string representation of a KB fact value."""
    val = fact.get("value", "")
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)[:_FACT_REVIEW_MAX_CHARS]
    return str(val)[:_FACT_REVIEW_MAX_CHARS]


def _is_internal_fact(fact: Dict[str, Any]) -> bool:
    """Return True if the fact is system-internal metadata that should be skipped."""
    tags = {str(t).lower() for t in fact.get("tags", [])}
    if tags & _SKIP_TAGS:
        return True
    key = str(fact.get("key", "")).lower()
    # ALE internal counters / step markers
    if re.match(r"^(ale_step|cycle_|niblit_tick|metric_|loop_|routing_)", key):
        return True
    return False


def _parse_audit_decision(response: str) -> Tuple[str, str, str]:
    """Parse a Qwen audit response into (action, new_value, reason).

    Expected format (any of):
      KEEP
      REWRITE: <new concise fact text>
      REMOVE: <short reason>

    Falls back to KEEP if format is unrecognised.
    """
    text = (response or "").strip()
    upper = text.upper()

    # REMOVE
    m = re.match(r"REMOVE\s*:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return "remove", "", m.group(1).strip()[:200]

    # REWRITE
    m = re.match(r"REWRITE\s*:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        new_text = m.group(1).strip()[:_FACT_REVIEW_MAX_CHARS]
        return "rewrite", new_text, "Qwen rewrote for clarity"

    # KEEP (explicit or implicit)
    if upper.startswith("KEEP") or not text:
        return "keep", "", ""

    # Unrecognised — treat as KEEP to be safe
    return "keep", "", f"unrecognised response: {text[:80]}"


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class QwenMemoryAdapter:
    """Qwen-powered read/audit/fix interface for Niblit's KnowledgeDB.

    Parameters
    ----------
    local_brain:
        A ``QwenLocalBrain`` instance (or any object with a compatible
        ``ask(prompt, system_prompt=None) -> str`` method).
    knowledge_db:
        A ``KnowledgeDB`` instance (or any object with ``list_facts``,
        ``add_fact``, and optionally ``get_learning_log``).
    """

    def __init__(
        self,
        local_brain: Any,
        knowledge_db: Optional[Any] = None,
    ) -> None:
        self.local_brain = local_brain
        self.knowledge_db = knowledge_db
        self._stats: Dict[str, int] = {
            "audits_run": 0,
            "facts_reviewed": 0,
            "facts_kept": 0,
            "facts_rewritten": 0,
            "facts_removed": 0,
            "coach_runs": 0,
        }
        log.debug("[QwenMemoryAdapter] Initialized (brain=%s, kb=%s)",
                  type(local_brain).__name__, type(knowledge_db).__name__)

    # ── KnowledgeDB resolution ────────────────────────────────────────────────

    def _get_kb(self) -> Optional[Any]:
        """Return the KnowledgeDB, falling back to the process-level singleton."""
        if self.knowledge_db is not None:
            return self.knowledge_db
        try:
            if KnowledgeDB is None:
                return None
            return KnowledgeDB()
        except Exception:
            return None

    # ── Memory reading ────────────────────────────────────────────────────────

    def get_memory_summary(self, limit: int = 20) -> str:
        """Return a compact, human-readable snapshot of Niblit's current knowledge.

        Parameters
        ----------
        limit:
            Maximum number of recent facts to include.
        """
        kb = self._get_kb()
        if kb is None:
            return "[QwenMemoryAdapter] KnowledgeDB not available."

        try:
            facts = kb.list_facts(limit) if hasattr(kb, "list_facts") else []
        except Exception:
            facts = []

        if not facts:
            return "📭 KnowledgeDB is empty — no facts stored yet."

        lines = [f"📚 **Niblit Memory Snapshot** ({len(facts)} recent facts)\n"]
        for i, fact in enumerate(facts[:limit], 1):
            key = str(fact.get("key", "?"))[:60]
            val_text = _fact_text(fact)[:120]
            tags = ", ".join(str(t) for t in fact.get("tags", [])[:4])
            lines.append(f"  {i:2d}. [{key}] {val_text}" + (f"  ({tags})" if tags else ""))

        # Learning log count
        try:
            ll = kb.get_learning_log() if hasattr(kb, "get_learning_log") else []
            lines.append(f"\n  📖 Learning log entries: {len(ll)}")
        except Exception:
            pass

        # Queue count
        try:
            queue = kb.get_learning_queue() if hasattr(kb, "get_learning_queue") else []
            pending = sum(1 for q in queue if isinstance(q, dict) and q.get("status") == "queued")
            lines.append(f"  🔄 Queued topics: {pending}")
        except Exception:
            pass

        return "\n".join(lines)

    # ── Fact review ───────────────────────────────────────────────────────────

    def review_fact(self, fact: Dict[str, Any]) -> Dict[str, Any]:
        """Ask Qwen whether a single KB fact should be kept, rewritten, or removed.

        Returns a dict with keys:
          ``action``   — "keep" | "rewrite" | "remove"
          ``new_value``— replacement text (only when action == "rewrite")
          ``reason``   — short explanation
        """
        if not self.local_brain:
            return {"action": "keep", "new_value": "", "reason": "local brain unavailable"}

        key = str(fact.get("key", "?"))[:80]
        val_text = _fact_text(fact)
        tags = ", ".join(str(t) for t in fact.get("tags", [])[:5])

        prompt = (
            f"Review this Niblit KnowledgeDB entry and decide what to do with it.\n\n"
            f"Key : {key}\n"
            f"Tags: {tags or 'none'}\n"
            f"Value:\n{val_text}\n\n"
            "Reply with EXACTLY one of:\n"
            "  KEEP                      — entry is accurate and concise\n"
            "  REWRITE: <new concise text> — entry needs improvement (provide improved text)\n"
            "  REMOVE: <reason>           — entry is wrong, irrelevant, or duplicate\n\n"
            "Use no other format. One-line answer only."
        )
        system = (
            "You are Niblit's memory manager. Your job is to keep the KnowledgeDB "
            "concise, accurate, and free of duplicates, internal system counters, "
            "and low-quality content. Be decisive."
        )
        try:
            raw = self.local_brain.ask(prompt, system_prompt=system)
            action, new_value, reason = _parse_audit_decision(raw)
        except Exception as exc:
            log.debug("[QwenMemoryAdapter] review_fact failed: %s", exc)
            action, new_value, reason = "keep", "", str(exc)

        return {"action": action, "new_value": new_value, "reason": reason, "key": key}

    # ── Batch audit ───────────────────────────────────────────────────────────

    def audit_batch(self, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Review a batch of facts and return a list of audit decisions.

        Parameters
        ----------
        facts:
            List of KnowledgeDB fact dicts (each with 'key', 'value', 'tags').

        Returns
        -------
        List of decision dicts, each containing:
            ``action``        — "keep" | "rewrite" | "remove"
            ``new_value``     — replacement text (when action == "rewrite")
            ``reason``        — short explanation
            ``original_fact`` — the input fact dict
        """
        results = []
        for fact in facts:
            decision = self.review_fact(fact)
            decision["original_fact"] = fact
            results.append(decision)
            self._stats["facts_reviewed"] += 1
            action = decision["action"]
            if action == "keep":
                self._stats["facts_kept"] += 1
            elif action == "rewrite":
                self._stats["facts_rewritten"] += 1
            elif action == "remove":
                self._stats["facts_removed"] += 1
        return results

    # ── Full KB audit (read-only report mode) ─────────────────────────────────

    def run_memory_audit(
        self,
        max_facts: int = 30,
        apply_changes: bool = True,
    ) -> str:
        """Audit up to *max_facts* KB entries with Qwen.

        When *apply_changes* is True (the default), rewrites and removals are
        applied to the live KnowledgeDB.  Set to False for a dry-run report.

        Returns a human-readable audit report.
        """
        kb = self._get_kb()
        if kb is None:
            return "[QwenMemoryAdapter] KnowledgeDB not available — cannot audit."
        if not self.local_brain:
            return "[QwenMemoryAdapter] Qwen local brain unavailable — cannot audit."

        try:
            all_facts = kb.list_facts(max_facts * 2) if hasattr(kb, "list_facts") else []
        except Exception as exc:
            return f"[QwenMemoryAdapter] Could not read facts: {exc}"

        # Filter out internal system metadata
        auditable = [f for f in all_facts if not _is_internal_fact(f)][:max_facts]
        if not auditable:
            return "✅ No auditable facts found (all entries are internal metadata)."

        self._stats["audits_run"] += 1
        kept_count = rewrite_count = remove_count = 0
        report_lines = [
            f"🔍 **Qwen KB Audit** — reviewing {len(auditable)} fact(s)\n"
        ]

        for i in range(0, len(auditable), _AUDIT_BATCH_SIZE):
            batch = auditable[i: i + _AUDIT_BATCH_SIZE]
            decisions = self.audit_batch(batch)

            for dec in decisions:
                action = dec["action"]
                key = dec["key"]
                orig = dec.get("original_fact", {})

                if action == "keep":
                    kept_count += 1
                    report_lines.append(f"  ✅ KEEP    [{key[:60]}]")

                elif action == "rewrite" and dec.get("new_value"):
                    rewrite_count += 1
                    new_val = dec["new_value"]
                    report_lines.append(
                        f"  ✏️  REWRITE [{key[:60]}]\n"
                        f"       → {new_val[:100]}"
                    )
                    if apply_changes and hasattr(kb, "add_fact"):
                        try:
                            kb.add_fact(
                                key,
                                new_val,
                                tags=list(orig.get("tags", [])) + ["qwen_rewritten"],
                            )
                        except Exception as exc:
                            log.debug("[QwenMemoryAdapter] rewrite failed: %s", exc)

                elif action == "remove":
                    remove_count += 1
                    reason = dec.get("reason", "")
                    report_lines.append(
                        f"  🗑️  REMOVE  [{key[:60]}]  ({reason[:80]})"
                    )
                    if apply_changes:
                        self._remove_fact(kb, key)

                # Note: self._stats are updated by audit_batch() above.
                # kept_count / rewrite_count / remove_count are local-only
                # counters used to compose the per-run text report.

        report_lines.append(
            f"\n📊 **Audit Summary**: "
            f"kept={kept_count}  rewritten={rewrite_count}  removed={remove_count}"
            + ("  (changes applied)" if apply_changes else "  (dry run — no changes)")
        )
        return "\n".join(report_lines)

    # ── Coaching ──────────────────────────────────────────────────────────────

    def coach_niblit(self) -> str:
        """Ask Qwen to review Niblit's memory and produce a coaching report.

        The report identifies:
        - Knowledge gaps
        - Stale or duplicate topics
        - Suggested next learning priorities
        - Overall KB health assessment
        """
        if not self.local_brain:
            return "[QwenMemoryAdapter] Qwen local brain unavailable."

        kb = self._get_kb()
        summary = self.get_memory_summary(limit=15)
        if kb:
            try:
                queue = kb.get_learning_queue() if hasattr(kb, "get_learning_queue") else []
                pending_topics = [
                    q["topic"] for q in queue
                    if isinstance(q, dict) and q.get("status") == "queued"
                ][:5]
            except Exception:
                pending_topics = []
        else:
            pending_topics = []

        pending_str = ", ".join(pending_topics) if pending_topics else "none"
        context = (summary[:_COACH_CONTEXT_MAX_CHARS] +
                   f"\n\nPending research queue: {pending_str}")

        prompt = (
            "Based on Niblit's current knowledge snapshot below, provide a concise coaching report:\n\n"
            "1. **KB Health** — rate the quality of stored facts (1-5) and note issues\n"
            "2. **Knowledge Gaps** — list 3-5 important topics Niblit should learn\n"
            "3. **Stale/Duplicate** — identify any obvious stale or duplicate entries\n"
            "4. **Next Steps** — recommend 3 concrete improvement actions\n\n"
            f"{context}"
        )
        system = (
            "You are Niblit's AI coach and trainer. Give direct, actionable advice "
            "in bullet-point format. Be specific about what Niblit should learn next "
            "and what KB entries need fixing."
        )
        try:
            report = self.local_brain.ask(prompt, system_prompt=system)
            self._stats["coach_runs"] += 1
            return f"🎓 **Qwen Coaching Report**\n\n{report}"
        except Exception as exc:
            return f"[QwenMemoryAdapter] Coach query failed: {exc}"

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_fact(self, kb: Any, key: str) -> None:
        """Remove a fact from the KB by key, if the KB supports it."""
        try:
            # KnowledgeDB stores facts as a list — filter out the matching key
            with kb.lock:
                before = len(kb.data.get("facts", []))
                kb.data["facts"] = [
                    f for f in kb.data.get("facts", [])
                    if str(f.get("key", "")) != key
                ]
                removed = before - len(kb.data["facts"])
            if removed:
                kb._save(blocking=False)
                log.debug("[QwenMemoryAdapter] Removed fact: %s", key)
        except Exception as exc:
            log.debug("[QwenMemoryAdapter] _remove_fact failed for %r: %s", key, exc)

    def get_stats(self) -> Dict[str, int]:
        """Return accumulated audit statistics."""
        return dict(self._stats)


# ── Singleton ─────────────────────────────────────────────────────────────────

_adapter_instance: Optional[QwenMemoryAdapter] = None
_adapter_lock = threading.Lock()


def get_qwen_memory_adapter(
    local_brain: Optional[Any] = None,
    knowledge_db: Optional[Any] = None,
) -> QwenMemoryAdapter:
    """Return the process-level ``QwenMemoryAdapter`` singleton.

    On first call, creates the instance using *local_brain* and *knowledge_db*.
    On subsequent calls the existing instance is returned (arguments are ignored).
    If no *local_brain* is provided, the module lazily resolves it from
    ``modules.local_brain.get_local_brain()``.
    """
    global _adapter_instance
    with _adapter_lock:
        if _adapter_instance is None:
            if local_brain is None:
                try:
                    from modules.local_brain import get_local_brain
                    local_brain = get_local_brain()
                except Exception as exc:
                    log.debug("[QwenMemoryAdapter] local_brain auto-resolve failed: %s", exc)
            if knowledge_db is None:
                try:
                    from niblit_memory import KnowledgeDB
                    knowledge_db = KnowledgeDB()
                except Exception as exc:
                    log.debug("[QwenMemoryAdapter] knowledge_db auto-resolve failed: %s", exc)
            _adapter_instance = QwenMemoryAdapter(
                local_brain=local_brain,
                knowledge_db=knowledge_db,
            )
    return _adapter_instance


def reset_qwen_memory_adapter() -> None:
    """Reset the singleton (for testing / re-wiring)."""
    global _adapter_instance
    with _adapter_lock:
        _adapter_instance = None


if __name__ == "__main__":
    print('Running qwen_memory_adapter.py')
