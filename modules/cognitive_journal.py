#!/usr/bin/env python3
"""Phase 11 — Human-Readable Cognitive Memory Journal.

Memory should no longer primarily store raw runtime state.  Instead each
entry is a structured factual record that explains:

    - *what* happened
    - *why* it happened
    - *how* it happened
    - *where* the information came from
    - *how reliable* it is
    - *how* it changed understanding
    - *which modules* participated
    - *which decisions* were influenced
    - *how future behaviour* changed

The journal reads like an explainable knowledge record rather than a
debug log.  Every entry has a plain-English narrative form as well as a
machine-readable dict for downstream indexing.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("Niblit.CognitiveJournal")


@dataclass
class JournalEntry:
    """One structured cognitive memory entry."""

    entry_id: str
    timestamp: float
    trace_id: str

    # What
    what_happened: str
    event_type: str
    source_module: str

    # Why
    why_it_happened: str
    intent: str
    trigger: str

    # How
    how_it_happened: str
    modules_participated: list[str] = field(default_factory=list)
    functions_called: list[str] = field(default_factory=list)

    # Where
    information_source: str = ""
    reliability: float = 0.5

    # Impact
    understanding_changed: list[str] = field(default_factory=list)
    decisions_influenced: list[str] = field(default_factory=list)
    behaviour_changed: list[str] = field(default_factory=list)
    knowledge_created: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_narrative(self) -> str:
        """Return a plain-English summary of this journal entry."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self.timestamp))
        lines = [
            f"[{ts}] {self.what_happened}",
            f"  Why: {self.why_it_happened or 'not recorded'}",
            f"  How: {self.how_it_happened or 'not recorded'}",
        ]
        if self.modules_participated:
            lines.append(
                f"  Participants: {', '.join(self.modules_participated)}"
            )
        if self.understanding_changed:
            lines.append(
                f"  Understanding updated: {', '.join(self.understanding_changed)}"
            )
        if self.knowledge_created:
            lines.append(
                f"  Knowledge created: {', '.join(self.knowledge_created)}"
            )
        if self.behaviour_changed:
            lines.append(
                f"  Behaviour changed: {', '.join(self.behaviour_changed)}"
            )
        if self.reliability < 0.5:
            lines.append(
                f"  ⚠ Reliability low ({self.reliability:.0%}): "
                "treat with caution."
            )
        return "\n".join(lines)


class CognitiveJournal:
    """Maintains the human-readable cognitive memory journal.

    Each entry explains a cognitive event in structured natural language,
    making the runtime's reasoning history comprehensible and auditable.
    The journal is the observable record of Niblit's cognitive life.

    It can optionally persist entries to a JSONL file when a
    *persistence_manager* with ``append_jsonl_record`` is provided.
    """

    def __init__(self, persistence_manager: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._entries: list[JournalEntry] = []
        self._persistence_manager = persistence_manager
        self._entry_counter = 0

    # ── writing ─────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        trace_id: str,
        what_happened: str,
        event_type: str,
        source_module: str,
        why_it_happened: str = "",
        intent: str = "",
        trigger: str = "",
        how_it_happened: str = "",
        modules_participated: list[str] | None = None,
        functions_called: list[str] | None = None,
        information_source: str = "",
        reliability: float = 0.5,
        understanding_changed: list[str] | None = None,
        decisions_influenced: list[str] | None = None,
        behaviour_changed: list[str] | None = None,
        knowledge_created: list[str] | None = None,
    ) -> JournalEntry:
        """Create and persist a new journal entry."""
        self._entry_counter += 1
        entry = JournalEntry(
            entry_id=f"journal-{self._entry_counter:07d}",
            timestamp=time.time(),
            trace_id=trace_id,
            what_happened=str(what_happened)[:480],
            event_type=str(event_type),
            source_module=str(source_module),
            why_it_happened=str(why_it_happened)[:360],
            intent=str(intent)[:240],
            trigger=str(trigger)[:240],
            how_it_happened=str(how_it_happened)[:360],
            modules_participated=list(modules_participated or []),
            functions_called=list(functions_called or []),
            information_source=str(information_source)[:240],
            reliability=round(min(1.0, max(0.0, float(reliability))), 3),
            understanding_changed=list(understanding_changed or []),
            decisions_influenced=list(decisions_influenced or []),
            behaviour_changed=list(behaviour_changed or []),
            knowledge_created=list(knowledge_created or []),
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > 1000:
                self._entries[:] = self._entries[-1000:]
        self._persist(entry)
        return entry

    def record_from_event(self, event: dict[str, Any]) -> JournalEntry:
        """Create a journal entry directly from a runtime event dict."""
        payload = dict(event.get("payload", {}) or {})
        reliability_raw = (
            payload.get("confidence")
            or payload.get("confidence_score")
            or payload.get("evaluation_score")
            or 0.5
        )
        try:
            reliability = float(reliability_raw)
        except (TypeError, ValueError):
            reliability = 0.5

        return self.record(
            trace_id=str(payload.get("trace_id") or ""),
            what_happened=str(
                payload.get("summary")
                or payload.get("output")
                or payload.get("response")
                or event.get("type", "runtime.event")
            ),
            event_type=str(event.get("type", "runtime.event")),
            source_module=str(event.get("source", "unknown")),
            why_it_happened=str(payload.get("intent") or payload.get("reason") or ""),
            intent=str(payload.get("intent") or payload.get("topic") or ""),
            trigger=str(payload.get("trigger") or event.get("type", "")),
            how_it_happened=str(
                payload.get("selected_function")
                or payload.get("function")
                or payload.get("method")
                or ""
            ),
            modules_participated=[
                m
                for m in [
                    payload.get("source_module"),
                    payload.get("selected_module"),
                    payload.get("provider"),
                ]
                if m
            ],
            information_source=str(
                payload.get("source_url")
                or payload.get("source")
                or event.get("source", "")
            ),
            reliability=reliability,
        )

    # ── reading ──────────────────────────────────────────────────────────────

    def recent_entries(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._entries[-max(1, limit) :]]

    def recent_narratives(self, limit: int = 5) -> list[str]:
        with self._lock:
            return [e.to_narrative() for e in self._entries[-max(1, limit) :]]

    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entry_count": len(self._entries),
                "purpose": "human_readable_cognitive_memory",
                "format": "structured_factual_records",
                "fields": [
                    "what_happened",
                    "why_it_happened",
                    "how_it_happened",
                    "information_source",
                    "reliability",
                    "understanding_changed",
                    "decisions_influenced",
                    "behaviour_changed",
                    "knowledge_created",
                ],
            }

    # ── persistence ──────────────────────────────────────────────────────────

    def _persist(self, entry: JournalEntry) -> None:
        if self._persistence_manager is None or not hasattr(
            self._persistence_manager, "append_jsonl_record"
        ):
            return
        try:
            root = getattr(self._persistence_manager, "root_dir", "")
            path = (
                f"{root}/cognitive/cognitive_journal.jsonl"
                if root
                else "cognitive/cognitive_journal.jsonl"
            )
            self._persistence_manager.append_jsonl_record(path, entry.to_dict())
        except Exception:
            return
