#!/usr/bin/env python3
"""modules/llama3_memory_adapter.py — Llama 3.2-powered KnowledgeDB manager.

Llama3MemoryAdapter gives Niblit's local brain—when loaded with the ``llama3``
model preset—the ability to:

  1. **Read** Niblit's KnowledgeDB facts and learning log.
  2. **Audit** individual facts — decide KEEP | REWRITE | REMOVE for each one.
  3. **Fix** the KB in-place by updating or deleting low-quality entries.
  4. **Coach** Niblit — produce an improvement report based on memory state.
  5. **Summarise** memory — return a compact view of what Niblit currently knows.
  6. **Tool-audit** — use Llama 3.2's function-calling to inspect and edit the KB
     through the ``NIBLIT_KB_TOOLS`` schema for more reliable structured output.

This mirrors the capabilities of ``QwenMemoryAdapter`` but targets the Llama 3.2
1B Instruct model, which uses the ``llama3`` chat template and natively supports
OpenAI-compatible function calling.

Public API
----------
::

    adapter = Llama3MemoryAdapter(local_brain, knowledge_db)
    adapter.get_memory_summary(limit=20)             -> str
    adapter.review_fact(fact)                        -> {"action": ..., "new_value": ..., "reason": ...}
    adapter.run_memory_audit(max_facts=30)            -> str  # cursor-driven, covers full KB over time
    adapter.coach_niblit()                           -> str
    adapter.tool_audit(max_facts=30, apply_changes)  -> str  # uses function-calling
    adapter.get_audit_coverage_report()              -> dict  # cursor progress summary

    # Singleton accessor
    get_llama3_memory_adapter(local_brain, knowledge_db) -> Llama3MemoryAdapter

Environment variables
---------------------
LLAMA3_AUDIT_MAX_FACTS      — facts audited per run (default: 30)
NIBLIT_AUDIT_CURSOR_PATH    — path to audit cursor JSON file
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("Niblit.Llama3MemoryAdapter")

# Max chars of a single fact value passed to Llama for review.
_FACT_REVIEW_MAX_CHARS: int = 400
# Max chars of the full memory summary Llama sees when coaching.
_COACH_CONTEXT_MAX_CHARS: int = 1800
# Number of facts audited per batch.
_AUDIT_BATCH_SIZE: int = 5
# Max facts audited per run (override via LLAMA3_AUDIT_MAX_FACTS env var).
_AUDIT_MAX_FACTS_DEFAULT: int = int(os.environ.get("LLAMA3_AUDIT_MAX_FACTS", "30"))
# Tags that mark internal Niblit metadata — skip during audit.
_SKIP_TAGS: frozenset = frozenset({
    "routing", "loop", "tick", "counter", "step", "system", "meta", "diagnostic",
})


def _audit_cursor_path() -> str:
    """Return a writable path for the persistent audit cursor file."""
    env_val = os.environ.get("NIBLIT_AUDIT_CURSOR_PATH", "").strip()
    if env_val:
        return env_val
    cwd = os.getcwd()
    if os.access(cwd, os.W_OK):
        return os.path.join(cwd, "niblit_audit_cursor.json")
    return os.path.join(tempfile.gettempdir(), "niblit_audit_cursor.json")

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
    if re.match(r"^(ale_step|cycle_|niblit_tick|metric_|loop_|routing_)", key):
        return True
    return False


def _parse_audit_decision(response: str) -> Tuple[str, str, str]:
    """Parse a Llama audit response into (action, new_value, reason).

    Expected format (any of):
      KEEP
      REWRITE: <new concise fact text>
      REMOVE: <short reason>

    Falls back to KEEP if format is unrecognised.
    """
    text = (response or "").strip()

    # REMOVE
    m = re.match(r"REMOVE\s*:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return "remove", "", m.group(1).strip()[:200]

    # REWRITE
    m = re.match(r"REWRITE\s*:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        new_text = m.group(1).strip()[:_FACT_REVIEW_MAX_CHARS]
        return "rewrite", new_text, "Llama3 rewrote for clarity"

    # KEEP (explicit or implicit)
    upper = text.upper()
    if upper.startswith("KEEP") or not text:
        return "keep", "", ""

    # Unrecognised — treat as KEEP to be safe
    return "keep", "", f"unrecognised response: {text[:80]}"


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class Llama3MemoryAdapter:
    """Llama 3.2-powered read/audit/fix interface for Niblit's KnowledgeDB.

    Parameters
    ----------
    local_brain:
        Niblit's local brain instance loaded with the ``llama3`` model preset
        (or any object with a compatible ``ask(prompt, system_prompt=None) -> str``
        and optionally ``generate_with_tools(prompt, tools, ...) -> (str, list)``
        method).  The brain class is ``QwenLocalBrain`` regardless of the active
        model preset — "Llama3" here refers to the preset, not a different class.
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
            "tool_audits_run": 0,
        }
        self._last_audit_offset: int = 0
        self._last_audit_total: int = 0
        log.debug(
            "[Llama3MemoryAdapter] Initialized (brain=%s, kb=%s)",
            type(local_brain).__name__,
            type(knowledge_db).__name__,
        )

    # ── KnowledgeDB resolution ────────────────────────────────────────────────

    def _get_kb(self) -> Optional[Any]:
        """Return the KnowledgeDB, falling back to the process-level singleton."""
        if self.knowledge_db is not None:
            return self.knowledge_db
        try:
            from niblit_memory import KnowledgeDB
            return KnowledgeDB()
        except Exception:
            return None

    # ── Audit cursor (persistent progress across runs) ────────────────────────

    def _load_cursor(self) -> Dict[str, int]:
        """Load the persistent audit cursor from disk.

        Returns a dict with keys ``last_offset``, ``total_audited``, and
        ``run_count``.  Missing keys default to 0.
        """
        try:
            with open(_audit_cursor_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {
                "last_offset":   int(data.get("last_offset", 0)),
                "total_audited": int(data.get("total_audited", 0)),
                "run_count":     int(data.get("run_count", 0)),
            }
        except Exception:
            return {"last_offset": 0, "total_audited": 0, "run_count": 0}

    def _save_cursor(self, cursor: Dict[str, int]) -> None:
        """Persist the audit cursor to disk (best-effort)."""
        try:
            with open(_audit_cursor_path(), "w", encoding="utf-8") as fh:
                json.dump(cursor, fh)
        except Exception as exc:
            log.debug("[Llama3MemoryAdapter] Could not save audit cursor: %s", exc)

    def _count_facts(self, kb: Any) -> int:
        """Return the total number of facts in *kb* as efficiently as possible.

        Tries, in order:
        1. ``kb.count_facts()``          — dedicated count method (O(1) for SQL).
        2. SQL ``COUNT(*)``              — when *kb* exposes a ``_conn()`` method.
        3. ``len(kb.list_facts(99999))`` — fallback for JSON-backed stores.
        """
        # 1. Dedicated count method
        if hasattr(kb, "count_facts"):
            try:
                return int(kb.count_facts())
            except Exception:
                pass

        # 2. SQL COUNT — avoids fetching rows
        if hasattr(kb, "_conn"):
            try:
                conn = kb._conn()
                row = conn.execute("SELECT COUNT(*) FROM facts").fetchone()
                if row:
                    return int(row[0])
            except Exception:
                pass

        # 3. Fallback: load all facts (JSON-backed stores are small enough)
        try:
            return len(kb.list_facts(99999))
        except Exception:
            return 0

    # ── Memory reading ────────────────────────────────────────────────────────

    def get_memory_summary(self, limit: int = 20) -> str:
        """Return a compact, human-readable snapshot of Niblit's current knowledge."""
        kb = self._get_kb()
        if kb is None:
            return "[Llama3MemoryAdapter] KnowledgeDB not available."

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
            lines.append(
                f"  {i:2d}. [{key}] {val_text}" + (f"  ({tags})" if tags else "")
            )

        try:
            ll = kb.get_learning_log() if hasattr(kb, "get_learning_log") else []
            lines.append(f"\n  📖 Learning log entries: {len(ll)}")
        except Exception:
            pass

        try:
            queue = kb.get_learning_queue() if hasattr(kb, "get_learning_queue") else []
            pending = sum(
                1 for q in queue if isinstance(q, dict) and q.get("status") == "queued"
            )
            lines.append(f"  🔄 Queued topics: {pending}")
        except Exception:
            pass

        return "\n".join(lines)

    # ── Fact review ───────────────────────────────────────────────────────────

    def review_fact(self, fact: Dict[str, Any]) -> Dict[str, Any]:
        """Ask Llama whether a single KB fact should be kept, rewritten, or removed.

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
            "  KEEP                        — entry is accurate and concise\n"
            "  REWRITE: <new concise text> — entry needs improvement (provide improved text)\n"
            "  REMOVE: <reason>            — entry is wrong, irrelevant, or duplicate\n\n"
            "Use no other format. One-line answer only."
        )
        system = (
            "You are Niblit's memory manager. Your job is to keep the KnowledgeDB "
            "concise, accurate, and free of duplicates, internal system counters, "
            "and low-quality content. Be decisive. Reply with exactly KEEP, "
            "REWRITE: <text>, or REMOVE: <reason> — nothing else."
        )
        try:
            raw = self.local_brain.ask(prompt, system_prompt=system)
            action, new_value, reason = _parse_audit_decision(raw)
        except Exception as exc:
            log.debug("[Llama3MemoryAdapter] review_fact failed: %s", exc)
            action, new_value, reason = "keep", "", str(exc)

        return {"action": action, "new_value": new_value, "reason": reason, "key": key}

    # ── Batch audit ───────────────────────────────────────────────────────────

    def audit_batch(self, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Review a batch of facts and return a list of audit decisions."""
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

    # ── Full KB audit (plain ask mode) ────────────────────────────────────────

    def run_memory_audit(
        self,
        max_facts: int = _AUDIT_MAX_FACTS_DEFAULT,
        apply_changes: bool = True,
    ) -> str:
        """Audit up to *max_facts* KB entries with Llama.

        Uses a persistent cursor (``niblit_audit_cursor.json``) so that each
        run processes a **different slice** of the KB, cycling through all
        facts over multiple runs.  The cursor wraps around when the end of
        the KB is reached.

        When *apply_changes* is True (the default), rewrites and removals are
        applied to the live KnowledgeDB.  Set to False for a dry-run report.

        The default for *max_facts* is controlled by the ``LLAMA3_AUDIT_MAX_FACTS``
        environment variable (default: 30).

        Returns a human-readable audit report.
        """
        kb = self._get_kb()
        if kb is None:
            return "[Llama3MemoryAdapter] KnowledgeDB not available — cannot audit."
        if not self.local_brain:
            return "[Llama3MemoryAdapter] Llama3 local brain unavailable — cannot audit."

        # ── Determine total fact count ─────────────────────────────────────
        try:
            total_facts = self._count_facts(kb) if hasattr(kb, "list_facts") else 0
        except Exception as exc:
            return f"[Llama3MemoryAdapter] Could not count facts: {exc}"

        if total_facts == 0:
            return "✅ KnowledgeDB is empty — nothing to audit."

        # ── Load + advance cursor ──────────────────────────────────────────
        cursor = self._load_cursor()
        offset = cursor["last_offset"]

        # Wrap around if the KB shrank or we've reached the end.
        if offset >= total_facts:
            offset = 0

        # Fetch 3× max_facts facts starting at the cursor offset.  The
        # multiplier accounts for internal metadata facts that will be filtered
        # out, ensuring we have enough candidates to fill the max_facts quota.
        fetch_window = max_facts * 3
        try:
            window = kb.list_facts(fetch_window, offset=offset)
        except TypeError:
            # Older KB implementation without offset support — fall back.
            window = kb.list_facts(fetch_window)

        auditable = [f for f in window if not _is_internal_fact(f)][:max_facts]
        if not auditable:
            return "✅ No auditable facts found in current window (all entries are internal metadata)."

        # ── Run audit ─────────────────────────────────────────────────────
        self._stats["audits_run"] += 1
        kept_count = rewrite_count = remove_count = 0
        report_lines = [
            f"🔍 **Llama3 KB Audit** — reviewing {len(auditable)} fact(s)"
            f"  (offset {offset}/{total_facts})\n"
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
                                tags=list(orig.get("tags", [])) + ["llama3_rewritten"],
                            )
                        except Exception as exc:
                            log.debug("[Llama3MemoryAdapter] rewrite failed: %s", exc)

                elif action == "remove":
                    remove_count += 1
                    reason = dec.get("reason", "")
                    report_lines.append(
                        f"  🗑️  REMOVE  [{key[:60]}]  ({reason[:80]})"
                    )
                    if apply_changes:
                        self._remove_fact(kb, key)

        # ── Save cursor ────────────────────────────────────────────────────
        new_offset = offset + len(auditable)
        if new_offset >= total_facts:
            new_offset = 0  # wrap — full cycle complete
        new_total_audited = cursor["total_audited"] + len(auditable)
        new_cursor = {
            "last_offset":   new_offset,
            "total_audited": new_total_audited,
            "run_count":     cursor["run_count"] + 1,
        }
        self._save_cursor(new_cursor)

        # Store for get_audit_coverage_report()
        self._last_audit_offset = offset
        self._last_audit_total = total_facts

        cycle_pct = min(100, round(new_total_audited / max(total_facts, 1) * 100))
        runs_to_cycle = max(1, round(total_facts / max(len(auditable), 1)))
        report_lines.append(
            f"\n📊 **Audit Summary**: "
            f"kept={kept_count}  rewritten={rewrite_count}  removed={remove_count}"
            + ("  (changes applied)" if apply_changes else "  (dry run — no changes)")
        )
        report_lines.append(
            f"📈 **Coverage**: {new_total_audited} cumulative facts audited "
            f"({cycle_pct}% of current KB)  |  "
            f"~{runs_to_cycle} runs/full cycle  |  "
            f"next offset: {new_offset}/{total_facts}"
        )
        return "\n".join(report_lines)

    # ── Function-calling tool audit (Llama 3.2 specific) ─────────────────────

    def tool_audit(
        self,
        max_facts: int = 20,
        apply_changes: bool = True,
    ) -> str:
        """Use Llama 3.2's function-calling to audit the KB via structured tools.

        This method calls ``generate_with_tools()`` so the model can use the
        ``NIBLIT_KB_TOOLS`` schema to list, read, and optionally delete/rewrite
        facts.  Requires the local brain to support function-calling (Llama 3.2
        loaded via HTTP backend).

        When *apply_changes* is False the model's proposed edits are reported
        but not executed.
        """
        if not self.local_brain:
            return "[Llama3MemoryAdapter] Llama3 local brain unavailable."

        if not hasattr(self.local_brain, "generate_with_tools"):
            return (
                "[Llama3MemoryAdapter] generate_with_tools() not available — "
                "run `llama3 audit-kb` for plain-text audit instead."
            )

        try:
            from modules.local_brain import NIBLIT_KB_TOOLS
        except ImportError:
            return "[Llama3MemoryAdapter] NIBLIT_KB_TOOLS schema unavailable."

        try:
            from modules.kb_tool_executor import KBToolExecutor
            executor = KBToolExecutor(apply_changes=apply_changes)
        except Exception as exc:
            return f"[Llama3MemoryAdapter] KBToolExecutor unavailable: {exc}"

        prompt = (
            f"Audit the Niblit KnowledgeDB. "
            f"Use list_kb_facts to survey up to {max_facts} facts, then read and "
            "evaluate each one. For facts that are incomplete, use complete_slsa_artifact. "
            "For facts that are corrupt or empty, use delete_kb_fact. "
            "Summarise what you found and what actions you took."
        )
        system = (
            "You are Niblit's internal KB auditor. "
            "Inspect the knowledge base using the provided tools. "
            "Do not delete facts unless they are empty or provably corrupt. "
            "Always call list_kb_facts first. Be concise in your final summary."
        )

        try:
            self._stats["tool_audits_run"] += 1
            response_text, tool_calls = self.local_brain.generate_with_tools(
                prompt,
                tools=NIBLIT_KB_TOOLS,
                system_prompt=system,
                max_new_tokens=800,
            )
            # Execute any tool calls the model made
            tool_results: List[str] = []
            for call in tool_calls:
                fn_name = call.get("name", "")
                fn_args = call.get("arguments", {})
                result = executor.execute(fn_name, fn_args)
                tool_results.append(f"  [{fn_name}] → {result[:200]}")
                log.debug("[Llama3MemoryAdapter] tool_audit call: %s(%s) → %s",
                          fn_name, fn_args, result[:80])

            lines = [f"🔧 **Llama3 Tool-Audit**\n"]
            if tool_results:
                lines.append("Tool calls executed:")
                lines.extend(tool_results)
                lines.append("")
            lines.append(f"Model summary:\n{response_text.strip()}")
            if not apply_changes:
                lines.append("\n⚠️  Dry run — no changes were persisted to the KB.")
            return "\n".join(lines)
        except Exception as exc:
            log.debug("[Llama3MemoryAdapter] tool_audit failed: %s", exc)
            return f"[Llama3MemoryAdapter] Tool-audit error: {exc}"

    # ── Coaching ──────────────────────────────────────────────────────────────

    def coach_niblit(self) -> str:
        """Ask Llama to review Niblit's memory and produce a coaching report.

        The report identifies:
        - Knowledge gaps
        - Stale or duplicate topics
        - Suggested next learning priorities
        - Overall KB health assessment
        """
        if not self.local_brain:
            return "[Llama3MemoryAdapter] Llama3 local brain unavailable."

        kb = self._get_kb()
        summary = self.get_memory_summary(limit=15)
        pending_topics: List[str] = []
        if kb:
            try:
                queue = kb.get_learning_queue() if hasattr(kb, "get_learning_queue") else []
                pending_topics = [
                    q["topic"]
                    for q in queue
                    if isinstance(q, dict) and q.get("status") == "queued"
                ][:5]
            except Exception:
                pass

        pending_str = ", ".join(pending_topics) if pending_topics else "none"
        context = (
            summary[:_COACH_CONTEXT_MAX_CHARS]
            + f"\n\nPending research queue: {pending_str}"
        )

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
            return f"🎓 **Llama3 Coaching Report**\n\n{report}"
        except Exception as exc:
            return f"[Llama3MemoryAdapter] Coach query failed: {exc}"

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_fact(self, kb: Any, key: str) -> None:
        """Remove a fact from the KB by key, if the KB supports it."""
        try:
            with kb.lock:
                before = len(kb.data.get("facts", []))
                kb.data["facts"] = [
                    f for f in kb.data.get("facts", [])
                    if str(f.get("key", "")) != key
                ]
                removed = before - len(kb.data["facts"])
            if removed:
                kb._save(blocking=False)
                log.debug("[Llama3MemoryAdapter] Removed fact: %s", key)
        except Exception as exc:
            log.debug("[Llama3MemoryAdapter] _remove_fact failed for %r: %s", key, exc)

    def get_audit_coverage_report(self) -> Dict[str, Any]:
        """Return a coverage summary for the persistent audit cursor.

        Returns a dict with:
            ``total_facts``            — current fact count in the KB
            ``facts_audited_this_run`` — facts reviewed in the last audit run
            ``cumulative_audited``     — total facts reviewed across all runs
            ``run_count``              — number of audit runs completed
            ``current_offset``         — next offset for the following run
            ``estimated_full_cycle_runs`` — approximate runs to cover the whole KB
                                           (based on the default batch size)
        """
        cursor = self._load_cursor()
        total = self._last_audit_total

        # If no audit has been run yet in this session, try to get total from KB.
        if total == 0:
            try:
                kb = self._get_kb()
                if kb and hasattr(kb, "list_facts"):
                    total = self._count_facts(kb)
            except Exception:
                pass

        batch = max(1, _AUDIT_MAX_FACTS_DEFAULT)
        estimated_cycle = max(1, round(total / batch)) if total else 0

        return {
            "total_facts":               total,
            "facts_audited_this_run":    self._stats.get("facts_reviewed", 0),
            "cumulative_audited":        cursor["total_audited"],
            "run_count":                 cursor["run_count"],
            "current_offset":            cursor["last_offset"],
            "estimated_full_cycle_runs": estimated_cycle,
        }

    def get_stats(self) -> Dict[str, int]:
        """Return accumulated audit statistics."""
        return dict(self._stats)


# ── Singleton ─────────────────────────────────────────────────────────────────

_adapter_instance: Optional[Llama3MemoryAdapter] = None
_adapter_lock = threading.Lock()


def get_llama3_memory_adapter(
    local_brain: Optional[Any] = None,
    knowledge_db: Optional[Any] = None,
) -> Llama3MemoryAdapter:
    """Return the process-level ``Llama3MemoryAdapter`` singleton.

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
                    log.debug("[Llama3MemoryAdapter] local_brain auto-resolve failed: %s", exc)
            if knowledge_db is None:
                try:
                    from niblit_memory import KnowledgeDB
                    knowledge_db = KnowledgeDB()
                except Exception as exc:
                    log.debug("[Llama3MemoryAdapter] knowledge_db auto-resolve failed: %s", exc)
            _adapter_instance = Llama3MemoryAdapter(
                local_brain=local_brain,
                knowledge_db=knowledge_db,
            )
    return _adapter_instance


def reset_llama3_memory_adapter() -> None:
    """Reset the singleton (for testing / re-wiring)."""
    global _adapter_instance
    with _adapter_lock:
        _adapter_instance = None


if __name__ == "__main__":
    print("Running llama3_memory_adapter.py")
