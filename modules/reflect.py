#!/usr/bin/env python3
"""
modules/reflect.py — ReflectModule v2.

Upgraded to work with Niblit's full modern stack:

* **KnowledgeDB** — reflection results stored under ``ale_reflection:``,
  ``ale_code_reflection:``, ``ale_trading_reflection:``, and
  ``ale_learned:`` keys so every ALE cycle can build on past reflections.
* **BrainTrainer** — reflections are ingested via ``ingest_research()`` so
  that ``get_context_for()`` surfaces them in future LLM prompts.
* **TradingBrain** — ``reflect_on_trading()`` reads the latest market state
  decision from the brain and stores a structured understanding entry.
* **LLM adapter** — when a ``generate_code``-capable LLM is wired in,
  ``collect_and_summarize()`` uses it for richer narrative summaries.
* **SelfTeacher / Learner** — backward-compatible; still called when wired.

Backward compatibility
-----------------------
All original method signatures are preserved so existing call-sites in
``niblit_core``, ``niblit_router``, and the ALE engine keep working without
change.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("ReflectModule")

# Maximum length of a reflection narrative stored in the knowledge base.
_MAX_REFLECT_LEN = 600
# Maximum characters taken from a raw entry when building LLM prompt context.
_MAX_ENTRY_CTX = 400
# Maximum characters taken from a KB recall result.
_MAX_KB_SNIPPET = 300

_default_instance: Optional["ReflectModule"] = None

# ── Utility: extract a clean, searchable topic from a compound reflection entry ──
# Entries fed to collect_and_summarize() often look like:
#   "Research Query: <topic>\n\nInsights: <long text>"
#   "Auto-research topic: <topic>\n\nFindings:\n['...']"
#   "Research topic: <topic>\n\nResearch findings:\n..."
# We want only the <topic> part so self_teacher / learner don't re-search with
# the full compound string (which contaminates search_web calls).
import re as _re
_COMPOUND_PREFIX_RE = _re.compile(
    r"^\s*(Research Query|Auto-research topic|Research topic|Learned about|Review-learned about)\s*:?\s*",
    _re.I,
)


def _topic_from_entry(entry: str) -> str:
    """Return the clean topic portion of a (possibly compound) reflection entry.

    Strips well-known prefixes and truncates at the first blank line so that
    only the genuine topic string (not findings or insights) is returned.
    """
    if not entry:
        return entry
    # Take only the first non-empty paragraph (before first double newline)
    first_block = entry.split("\n\n")[0].strip()
    # Remove well-known label prefixes
    first_block = _COMPOUND_PREFIX_RE.sub("", first_block).strip()
    # Final safety: if still very long or contains newlines, take first line only
    first_line = first_block.split("\n")[0].strip()
    return first_line[:200] if first_line else first_block[:200]


class ReflectModule:
    """Unified reflection engine for Niblit.

    Args:
        db:             KnowledgeDB / NiblitMemory instance (primary store).
        self_teacher:   Optional SelfTeacher module.
        learner:        Optional SelfIdeaImplementation module.
        knowledge_db:   Alias for ``db`` — accepted for forward-compat with
                        callers that pass by name.
        brain_trainer:  Optional BrainTrainer for cognitive domain updates.
        trading_brain:  Optional TradingBrain for market-state reflections.
        llm:            Optional HFLLMAdapter / LLMAdapter for richer summaries.
        internet:       Optional InternetManager (reserved for future use).
        vector_store:   Optional VectorStore / FusedStorage.
        searchcode_search: Optional SearchcodeSearch (reserved).
    """

    def __init__(
        self,
        db: Optional[Any] = None,
        self_teacher: Optional[Any] = None,
        learner: Optional[Any] = None,
        *,
        knowledge_db: Optional[Any] = None,
        brain_trainer: Optional[Any] = None,
        trading_brain: Optional[Any] = None,
        llm: Optional[Any] = None,
        internet: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        searchcode_search: Optional[Any] = None,
    ) -> None:
        # Accept both positional ``db`` and keyword ``knowledge_db``
        self.db: Optional[Any] = db or knowledge_db
        self.self_teacher = self_teacher
        self.learner = learner
        self.brain_trainer = brain_trainer
        self.trading_brain = trading_brain
        self.llm = llm
        self.internet = internet
        self.vector_store = vector_store
        self.searchcode_search = searchcode_search

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ts(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def _epoch(self) -> int:
        return int(time.time())

    @staticmethod
    def _extract_themes(text: str, n: int = 5) -> str:
        """Return the *n* most-frequent meaningful words in *text*.

        Pure-numeric tokens (timestamps, IDs) and internal key fragments
        (e.g. ``gap_learned:topic:1775212073``) are excluded so that
        implementation details never surface as apparent topics.
        """
        import re as _re
        _noise = _re.compile(r"^\d+$|.*\d{8,}.*|^[a-z_]+:[a-z_:0-9]+$")
        words = [
            w.strip(".,!?;:()[]{}\"'")
            for w in text.split()
            if len(w) > 3 and not _noise.match(w.strip(".,!?;:()[]{}\"'").lower())
        ]
        if not words:
            return "(no themes)"
        top = sorted(set(words), key=lambda x: words.count(x), reverse=True)
        return ", ".join(top[:n])

    def _store_reflection(
        self,
        key: str,
        text: str,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Persist a reflection entry to the knowledge base."""
        if not self.db:
            return
        _tags = list(tags or []) + ["reflect"]
        try:
            self.db.add_fact(key, text[:_MAX_REFLECT_LEN], tags=_tags)
        except Exception:
            try:
                self.db.store_knowledge(key, text[:_MAX_REFLECT_LEN])
            except Exception:
                pass

    def _ingest_brain(self, topic: str, text: str) -> None:
        """Feed a reflection snippet into BrainTrainer for cognitive context."""
        if not self.brain_trainer:
            return
        try:
            self.brain_trainer.ingest_research(topic, text[:_MAX_REFLECT_LEN])
        except Exception:
            pass

    def _llm_summarize(self, prompt: str) -> Optional[str]:
        """Ask the LLM for a narrative summary.  Returns *None* on any failure."""
        if not self.llm:
            return None
        try:
            if hasattr(self.llm, "generate_code"):
                return self.llm.generate_code(
                    language="text",
                    purpose=f"Write a 2-3 sentence reflective summary: {prompt[:300]}",
                    context="",
                    max_tokens=200,
                )
        except Exception:
            pass
        return None

    # ── primary public API (backward-compatible) ──────────────────────────

    def collect_and_summarize(self, entry: Optional[str] = None) -> str:
        """Reflect on *entry*, store in KB, update BrainTrainer, feed teachers.

        This is the primary method called by the ALE engine (step 4 and
        step 11) and by the router ``reflect`` command.

        Returns a human-readable summary string.
        """
        if not entry:
            return "No reflection entry."

        ts = self._epoch()
        key = f"ale_reflection:{ts}"
        tags = ["reflect", "ale_step4", "autonomous"]

        # ── Attempt LLM-enhanced narrative ──────────────────────────────
        llm_summary = self._llm_summarize(entry[:_MAX_ENTRY_CTX])

        # ── Compose final reflection text ────────────────────────────────
        themes = self._extract_themes(entry)
        if llm_summary:
            reflection = (
                f"Themes: {themes}\n"
                f"Summary: {llm_summary.strip()}\n"
                f"Raw: {entry[:_MAX_ENTRY_CTX]}"
            )
        else:
            reflection = f"Themes: {themes}\n{entry[:_MAX_REFLECT_LEN]}"

        # ── Persist to KB ────────────────────────────────────────────────
        self._store_reflection(key, reflection, tags=tags)

        # ── Feed BrainTrainer ────────────────────────────────────────────
        topic_word = entry.split()[0].lower() if entry.split() else "reflect"
        self._ingest_brain(f"reflect:{topic_word}", reflection)

        # ── Feed SelfTeacher ────────────────────────────────────────────
        # Pass only the clean topic, not the full compound entry, so that
        # self_teacher.teach() → researcher.search() → search_web() is never
        # called with an "Insights: {...}" or "Findings: ['...']" blob string.
        if self.self_teacher:
            try:
                self.self_teacher.teach(_topic_from_entry(entry))
            except Exception:
                pass

        # ── Feed Learner module ──────────────────────────────────────────
        if self.learner:
            try:
                self.learner.learn(_topic_from_entry(entry))
            except Exception:
                pass

        return f"Reflection saved. Themes: {themes}"

    # ── domain-specific reflection methods ───────────────────────────────

    def reflect_on_research(
        self,
        topic: str,
        research_text: str,
        idea: str = "",
    ) -> str:
        """Reflect on a completed research cycle and store structured insights.

        Called after new facts are ingested from Serpex, Searchcode, GitHub,
        or internet searches so the understanding of those facts is properly
        consolidated.

        Returns a summary string.
        """
        if not research_text:
            return "[reflect_on_research] No research text supplied."

        prompt = (
            f"Research topic: {topic}\n"
            f"Findings: {research_text[:_MAX_ENTRY_CTX]}\n"
            + (f"Generated idea: {idea}" if idea else "")
        )

        llm_summary = self._llm_summarize(prompt)
        themes = self._extract_themes(research_text)

        reflection = (
            f"[Research reflection — {topic}]\n"
            f"Themes: {themes}\n"
        )
        if llm_summary:
            reflection += f"Understanding: {llm_summary.strip()}\n"
        reflection += f"Source snippet: {research_text[:200]}"

        key = f"ale_learned:{topic.replace(' ', '_')}:{self._epoch()}"
        self._store_reflection(
            key, reflection,
            tags=["ale_learned", "research", "reflect", topic.split()[0].lower()],
        )
        self._ingest_brain(f"research:{topic}", reflection)

        log.info("[ReflectModule] research reflection stored → %s", key)
        return f"Research reflection stored. Themes: {themes}"

    def reflect_on_code(
        self,
        language: str,
        topic: str,
        code: str,
        output: str = "",
        error: str = "",
        success: bool = False,
    ) -> str:
        """Reflect on compiled/generated code and store actionable learnings.

        Mirrors the logic used by ALE step 11 (*_autonomous_code_reflection*)
        but provides a richer interface that can be called from anywhere in
        the stack.

        Returns a summary string.
        """
        result_tag = "success" if success else "error"
        snippet = (
            f"Compiled {language} code for '{topic}'. "
            f"Success: {success}. "
            f"Output: {output[:150] if output else 'none'}. "
            f"Error: {error[:100] if error else 'none'}. "
            f"Code: {code[:200]}"
        )

        # Store general code reflection
        key = f"ale_code_reflection:{language}:{topic}:{self._epoch()}"
        self._store_reflection(
            key, snippet,
            tags=["reflection", "code", language, result_tag],
        )
        self._ingest_brain(f"code:{language}:{topic}", snippet)

        # Store actionable learning for the next generation cycle
        if success and output:
            learning = (
                f"Successful {language} pattern for '{topic}': "
                f"output='{output[:120]}'. Code: {code[:120]}"
            )
        elif not success and error:
            learning = (
                f"Fix needed for {language} '{topic}': "
                f"error='{error[:120]}'. Avoid: {code[:120]}"
            )
        else:
            learning = None

        if learning:
            learn_key = f"ale_code_learning:{language}:{topic}:{self._epoch()}"
            self._store_reflection(
                learn_key, learning,
                tags=["code_learning", "autonomous", language],
            )
            self._ingest_brain(f"code_learning:{language}", learning)

        log.info("[ReflectModule] code reflection stored → %s (%s)", key, result_tag)
        return f"Code reflection: {language}/{topic} — {result_tag}"

    def reflect_on_trading(
        self,
        symbol: Optional[str] = None,
        decision: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Reflect on the current trading brain state and store market understanding.

        Can be called with explicit values or will pull live state from
        ``self.trading_brain.status()`` when no arguments are supplied.

        Returns a human-readable summary string.
        """
        # ── Pull live state from TradingBrain if not supplied ────────────
        if self.trading_brain and (symbol is None or decision is None):
            try:
                st = self.trading_brain.status()
                symbol = symbol or st.get("symbol", "UNKNOWN")
                decision = decision or st.get("last_decision", "HOLD")
                if metadata is None:
                    metadata = {
                        "cycle_count": st.get("cycle_count", 0),
                        "last_cycle_ts": st.get("last_cycle_ts", "—"),
                        "interval": st.get("interval", "1m"),
                        "running": st.get("running", False),
                    }
            except Exception as exc:
                log.debug("[ReflectModule] trading_brain.status() failed: %s", exc)

        symbol = symbol or "UNKNOWN"
        decision = decision or "HOLD"
        meta_str = json.dumps(metadata or {}, default=str)[:200]

        prompt = (
            f"Market state for {symbol}: decision={decision}. "
            f"Context: {meta_str}"
        )
        llm_summary = self._llm_summarize(prompt)

        reflection = (
            f"[Trading reflection — {symbol}]\n"
            f"Decision: {decision}\n"
            f"Metadata: {meta_str}\n"
        )
        if llm_summary:
            reflection += f"Analysis: {llm_summary.strip()}"

        key = f"ale_trading_reflection:{symbol}:{self._epoch()}"
        self._store_reflection(
            key, reflection,
            tags=["trading", "reflect", "market", symbol.lower()],
        )
        self._ingest_brain(f"trading:{symbol}", reflection)

        # Feed cognitive domain so LLM knows about market awareness
        if self.brain_trainer:
            try:
                self.brain_trainer.update_cognitive_domain(
                    "calculating",
                    f"Market {symbol}: {decision} — {meta_str}",
                )
            except Exception:
                pass

        log.info("[ReflectModule] trading reflection stored → %s", key)
        return f"Trading reflection stored — {symbol}: {decision}"

    # ── auto-reflect (backward-compatible + enhanced) ────────────────────

    def auto_reflect(self, recent_events: Any) -> str:
        """Auto-reflect on recent events, interactions and stored KB facts.

        Accepts a list of events (dicts or strings).  In addition to the
        original behaviour it now:

        * Pulls recent ``ale_learned``, ``ale_code_reflection`` and
          ``ale_trading_reflection`` facts from the KB and incorporates them.
        * Calls ``reflect_on_trading()`` to keep market understanding current
          when a TradingBrain is wired in.

        Returns a summary string.
        """
        if not recent_events:
            recent_events = []

        # ── Normalise events to strings ──────────────────────────────────
        events_text: List[str] = []
        for event in recent_events:
            try:
                if isinstance(event, dict):
                    text = (
                        event.get("input")
                        or event.get("response")
                        or event.get("event")
                        or json.dumps(event)[:100]
                    )
                    events_text.append(str(text))
                else:
                    events_text.append(str(event))
            except Exception:
                pass

        # ── Pull recent KB facts for enriched context ────────────────────
        if self.db:
            for prefix in ("ale_learned", "ale_code_reflection", "ale_trading_reflection"):
                try:
                    if hasattr(self.db, "recall"):
                        facts = self.db.recall(prefix, limit=2) or []
                    elif hasattr(self.db, "search"):
                        facts = self.db.search(prefix, limit=2) or []
                    else:
                        facts = []
                    for f in facts:
                        val = (
                            f.get("value") or f.get("content") or f.get("input")
                            if isinstance(f, dict) else str(f)
                        )
                        if val:
                            events_text.append(f"[{prefix}] {str(val)[:200]}")
                except Exception:
                    pass

        # ── Reflect on live trading state ─────────────────────────────────
        if self.trading_brain:
            try:
                self.reflect_on_trading()
            except Exception:
                pass

        if not events_text:
            return "Nothing to reflect on."

        text = " | ".join(events_text[:8])
        return self.collect_and_summarize(f"System reflection: {text}")

    def reflect_on_all(self) -> str:
        """Run a comprehensive reflection pass across all major subsystems.

        Useful as a scheduled maintenance call — pulls recent data from each
        domain (research, code, trading) and stores consolidated insights.

        Returns a multi-line summary string.
        """
        results: List[str] = []

        # Research
        if self.db:
            try:
                facts = []
                if hasattr(self.db, "recall"):
                    facts = self.db.recall("ale_learned", limit=3) or []
                for f in facts:
                    val = (
                        f.get("value") or f.get("content") or ""
                        if isinstance(f, dict) else str(f)
                    )
                    topic = f.get("key", "general") if isinstance(f, dict) else "general"
                    if val:
                        results.append(self.reflect_on_research(str(topic), str(val)))
            except Exception:
                pass

        # Code
        if self.db:
            try:
                code_facts = []
                if hasattr(self.db, "recall"):
                    code_facts = self.db.recall("ale_code_reflection", limit=3) or []
                for f in code_facts:
                    val = (
                        f.get("value") or f.get("content") or ""
                        if isinstance(f, dict) else str(f)
                    )
                    if val:
                        results.append(self.reflect_on_code("python", "general", val))
            except Exception:
                pass

        # Trading
        trading_result = self.reflect_on_trading()
        results.append(trading_result)

        if not results:
            return "Comprehensive reflection completed — no data to process."
        return "Comprehensive reflection:\n" + "\n".join(f"  • {r}" for r in results)


# ── Router compatibility function (module-level) ─────────────────────────────

def collect_and_summarize(entry: Optional[str] = None, db: Optional[Any] = None) -> str:
    """Router-safe module-level wrapper around :class:`ReflectModule`.

    Allows the router to call ``reflect.collect_and_summarize(...)``
    without constructing a full instance.
    """
    global _default_instance
    if _default_instance is None:
        _default_instance = ReflectModule(db)
    return _default_instance.collect_and_summarize(entry)


if __name__ == "__main__":
    print("Running reflect.py")
