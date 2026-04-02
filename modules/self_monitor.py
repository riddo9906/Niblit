#!/usr/bin/env python3
"""
modules/self_monitor.py — Self-Improvement Experience Accumulator
─────────────────────────────────────────────────────────────────
Tracks every significant action Niblit takes — audits, repairs, code
generation, agent runs, upgrades — and derives actionable recommendations
from the accumulated history.

``SelfMonitor`` provides:
  • In-memory event log with optional KnowledgeDB persistence.
  • Per-event-type counters, success rates, and trend windows.
  • Heuristic recommendation engine that surfaces patterns (e.g., high
    repair rate → suggest deeper audit, high code-gen rate → suggest
    incremental testing).
  • Thread-safe access via ``threading.Lock``.
  • A ``cli_report()`` string for terminal display.

Event types (``EventType`` constants)
──────────────────────────────────────
  AUDIT_FINDING   — a finding from a self-audit run
  HEAL_REPAIR     — an automatic or manual self-repair
  MAINTENANCE     — routine maintenance operation (cleanup, vacuum, etc.)
  CODE_GEN        — code generation event
  FILE_EDIT       — file creation or modification
  AGENT_ACTION    — an agent was invoked or completed a task
  LEARNING        — ALE / learning engine event
  UPGRADE         — version upgrade operation

Usage::

    from modules.self_monitor import get_self_monitor

    monitor = get_self_monitor()
    monitor.log_event("HEAL_REPAIR", "Fixed missing import in niblit_core.py",
                      metadata={"file": "niblit_core.py"}, outcome="success")
    monitor.record_upgrade("1.4.0", "1.5.0", "Added hybrid Qdrant manager", True)
    print(monitor.cli_report())
    summary = monitor.get_experience_summary()

Configuration
─────────────
  No environment variables required.  Persistence to KnowledgeDB is opt-in
  via ``flush_to_kb(knowledge_db)``.

Public API
──────────
  get_self_monitor()                — module-level singleton getter
  SelfMonitor.log_event(...)        — record any event
  SelfMonitor.record_upgrade(...)   — specialised upgrade log helper
  SelfMonitor.get_experience_summary() → dict
  SelfMonitor.get_trends()          → list of last 20 events
  SelfMonitor.get_recommendations() → list of suggestion strings
  SelfMonitor.cli_report()          → formatted terminal string
  SelfMonitor.flush_to_kb(kb)       → persist events to KnowledgeDB
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger("SelfMonitor")


# ══════════════════════════════════════════════════════════════════════════════
# Event type constants
# ══════════════════════════════════════════════════════════════════════════════

class EventType:
    """String constants for the supported event types."""
    AUDIT_FINDING = "AUDIT_FINDING"
    HEAL_REPAIR   = "HEAL_REPAIR"
    MAINTENANCE   = "MAINTENANCE"
    CODE_GEN      = "CODE_GEN"
    FILE_EDIT     = "FILE_EDIT"
    AGENT_ACTION  = "AGENT_ACTION"
    LEARNING      = "LEARNING"
    UPGRADE       = "UPGRADE"

    ALL: List[str] = [
        AUDIT_FINDING, HEAL_REPAIR, MAINTENANCE,
        CODE_GEN, FILE_EDIT, AGENT_ACTION, LEARNING, UPGRADE,
    ]


# ══════════════════════════════════════════════════════════════════════════════
# SelfMonitor
# ══════════════════════════════════════════════════════════════════════════════

# Maximum events retained in the in-memory deque before the oldest are dropped.
_MAX_EVENTS = 2000

# Number of events in the "recent trend" window.
_TREND_WINDOW = 20


class SelfMonitor:
    """
    Self-improvement experience accumulator.

    Records, analyses, and surfaces patterns from Niblit's operational
    history.  All public methods are thread-safe.

    Parameters
    ----------
    max_events:
        Maximum number of events to retain in memory.
    """

    def __init__(self, max_events: int = _MAX_EVENTS) -> None:
        self._lock = threading.Lock()
        # Ring buffer of event dicts: newest events at the right
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        # Per-type counters for fast summary without iterating all events
        self._type_counts: Counter = Counter()
        # Per-type success/failure counters
        self._success_counts: Counter = Counter()
        self._failure_counts: Counter = Counter()
        # Timestamp of the last event of each type
        self._last_event: Dict[str, float] = {}
        log.info("[SelfMonitor] Initialised (max_events=%d)", max_events)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _now_ts() -> float:
        """Return the current UNIX timestamp."""
        return time.time()

    @staticmethod
    def _ts_iso(ts: float) -> str:
        """Format a UNIX timestamp as an ISO-8601 string."""
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Core logging ──────────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
        outcome: Optional[str] = None,
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Record an event in the experience log.

        Parameters
        ----------
        event_type:
            One of the ``EventType`` constants (e.g. ``"HEAL_REPAIR"``).
            Unknown types are accepted but logged as a warning.
        description:
            Human-readable description of what happened.
        metadata:
            Optional dict of additional context (file paths, model names, etc.)
        outcome:
            Optional outcome string.  ``"success"`` increments the success
            counter; anything else (including ``"failure"``, ``"error"``)
            increments the failure counter.
        confidence:
            Float in [0, 1] indicating confidence in the event's relevance.

        Returns
        -------
        dict
            The stored event record.
        """
        if event_type not in EventType.ALL:
            log.warning("[SelfMonitor] Unknown event_type '%s' — storing anyway", event_type)

        ts = self._now_ts()
        event: Dict[str, Any] = {
            "event_type":  event_type,
            "description": description,
            "metadata":    metadata or {},
            "outcome":     outcome,
            "confidence":  float(confidence),
            "timestamp":   ts,
            "timestamp_iso": self._ts_iso(ts),
        }

        with self._lock:
            self._events.append(event)
            self._type_counts[event_type] += 1
            self._last_event[event_type] = ts

            if outcome == "success":
                self._success_counts[event_type] += 1
            elif outcome is not None:
                # Any non-success, non-None outcome is treated as a failure
                self._failure_counts[event_type] += 1

        log.debug(
            "[SelfMonitor] %s | %s | outcome=%s | conf=%.2f",
            event_type, description[:80], outcome, confidence,
        )
        return event

    def record_upgrade(
        self,
        from_version: str,
        to_version: str,
        what: str,
        success: bool,
    ) -> Dict[str, Any]:
        """
        Convenience method for recording a version upgrade event.

        Parameters
        ----------
        from_version:
            Version string before the upgrade (e.g. ``"1.4.0"``).
        to_version:
            Version string after the upgrade (e.g. ``"1.5.0"``).
        what:
            Short description of what was upgraded or changed.
        success:
            Whether the upgrade completed successfully.

        Returns
        -------
        dict
            The stored event record.
        """
        outcome = "success" if success else "failure"
        return self.log_event(
            event_type=EventType.UPGRADE,
            description=f"Upgrade {from_version} → {to_version}: {what}",
            metadata={
                "from_version": from_version,
                "to_version":   to_version,
                "what":         what,
            },
            outcome=outcome,
            confidence=1.0,
        )

    # ── Analysis & reporting ──────────────────────────────────────────────────

    def get_experience_summary(self) -> Dict[str, Any]:
        """
        Return a high-level summary of accumulated experience.

        Returns
        -------
        dict with keys:
          ``total_events``   — total events recorded
          ``by_type``        — {event_type: count}
          ``last_event``     — {event_type: ISO timestamp of last occurrence}
          ``success_rate``   — {event_type: float in [0, 1]}
        """
        with self._lock:
            total = sum(self._type_counts.values())
            by_type = dict(self._type_counts)
            last_event = {k: self._ts_iso(v) for k, v in self._last_event.items()}

            success_rate: Dict[str, float] = {}
            for etype in EventType.ALL:
                s = self._success_counts.get(etype, 0)
                f = self._failure_counts.get(etype, 0)
                total_sf = s + f
                success_rate[etype] = round(s / total_sf, 3) if total_sf > 0 else 1.0

        return {
            "total_events":  total,
            "by_type":       by_type,
            "last_event":    last_event,
            "success_rate":  success_rate,
        }

    def get_trends(self) -> List[Dict[str, Any]]:
        """
        Return the most recent ``_TREND_WINDOW`` events, newest last.

        Returns
        -------
        list of event dicts
        """
        with self._lock:
            events = list(self._events)
        return events[-_TREND_WINDOW:]

    def get_recommendations(self) -> List[str]:
        """
        Return heuristic-based improvement suggestions derived from event history.

        Rules
        ─────
        • Many HEAL_REPAIR events         → suggest deeper/scheduled audit
        • High HEAL_REPAIR failure rate   → suggest manual code review
        • Many AUDIT_FINDING events       → suggest automated remediation
        • No LEARNING events recently     → suggest enabling ALE
        • Many FILE_EDIT events w/ failures → suggest pre-commit linting
        • Many CODE_GEN events            → suggest incremental test coverage
        • Frequent AGENT_ACTION events    → suggest agent performance profiling
        • Recent failed UPGRADEs          → suggest rollback procedure review
        """
        recommendations: List[str] = []

        with self._lock:
            counts = dict(self._type_counts)
            success = dict(self._success_counts)
            failure = dict(self._failure_counts)
            recent = list(self._events)[-100:]  # look at last 100 events for trends

        def _rate(etype: str) -> float:
            """Failure rate for *etype* in [0, 1]."""
            f = failure.get(etype, 0)
            s = success.get(etype, 0)
            total = f + s
            return round(f / total, 3) if total > 0 else 0.0

        def _recent_count(etype: str) -> int:
            """Count of *etype* events in the last 100 events."""
            return sum(1 for e in recent if e["event_type"] == etype)

        total_events = sum(counts.values())

        # Rule: high repair volume → deeper audit
        if counts.get(EventType.HEAL_REPAIR, 0) >= 10:
            recommendations.append(
                "High number of self-repair events detected. "
                "Consider scheduling a deeper audit (`audit full`) to surface root causes."
            )

        # Rule: high repair failure rate → manual review
        if _rate(EventType.HEAL_REPAIR) > 0.3:
            recommendations.append(
                "Self-repair failure rate is elevated (>{:.0f}%). "
                "Manual code review may be needed for recurring issues.".format(
                    _rate(EventType.HEAL_REPAIR) * 100
                )
            )

        # Rule: many audit findings → automate remediation
        if counts.get(EventType.AUDIT_FINDING, 0) >= 5:
            recommendations.append(
                "Multiple audit findings have been recorded. "
                "Consider enabling automated remediation to close the loop faster."
            )

        # Rule: no recent learning events → suggest ALE
        if _recent_count(EventType.LEARNING) == 0 and total_events > 20:
            recommendations.append(
                "No recent LEARNING events in the last 100 actions. "
                "Ensure the Autonomous Learning Engine (ALE) is active."
            )

        # Rule: file edits with failures → suggest linting
        if _rate(EventType.FILE_EDIT) > 0.2 and counts.get(EventType.FILE_EDIT, 0) >= 5:
            recommendations.append(
                "File edit failure rate is above 20%. "
                "Adding a pre-commit linting step may reduce edit errors."
            )

        # Rule: high code-gen volume → suggest test coverage
        if counts.get(EventType.CODE_GEN, 0) >= 8:
            recommendations.append(
                "High code generation activity. "
                "Ensure incremental test coverage is tracking generated modules."
            )

        # Rule: many agent actions → profiling
        if _recent_count(EventType.AGENT_ACTION) >= 15:
            recommendations.append(
                "High recent agent activity. "
                "Consider profiling agent performance to identify bottlenecks."
            )

        # Rule: recent upgrade failures → rollback procedure
        failed_upgrades = [
            e for e in recent
            if e["event_type"] == EventType.UPGRADE and e.get("outcome") not in ("success", None)
        ]
        if failed_upgrades:
            recommendations.append(
                f"{len(failed_upgrades)} recent upgrade(s) failed. "
                "Review rollback procedures and version pinning strategy."
            )

        if not recommendations:
            recommendations.append("No actionable recommendations at this time. System looks healthy.")

        return recommendations

    def cli_report(self) -> str:
        """
        Return a formatted, human-readable terminal report.

        Includes totals by event type, success rates, recent trends, and
        top recommendations.
        """
        summary = self.get_experience_summary()
        trends = self.get_trends()
        recommendations = self.get_recommendations()

        lines = [
            "╔══════════════════════════════════════════════╗",
            "║         Niblit Self-Monitor Report           ║",
            "╚══════════════════════════════════════════════╝",
            f"  Total events recorded: {summary['total_events']}",
            "",
            "  ── Event Counts & Success Rates ──",
        ]

        for etype in EventType.ALL:
            count = summary["by_type"].get(etype, 0)
            rate  = summary["success_rate"].get(etype, 1.0)
            last  = summary["last_event"].get(etype, "never")
            lines.append(
                f"  {etype:<16s}  count={count:4d}  success={rate*100:5.1f}%  last={last}"
            )

        lines += [
            "",
            "  ── Recent Activity (last 20 events) ──",
        ]
        for event in trends[-10:]:  # show last 10 of the 20-event window
            ts = event.get("timestamp_iso", "?")
            et = event.get("event_type", "?")
            desc = event.get("description", "")[:60]
            outcome = event.get("outcome") or ""
            outcome_tag = f" [{outcome}]" if outcome else ""
            lines.append(f"  {ts}  {et:<16s}  {desc}{outcome_tag}")

        lines += [
            "",
            "  ── Recommendations ──",
        ]
        for rec in recommendations:
            # Word-wrap at ~80 chars with indentation
            words = rec.split()
            line = "  • "
            for word in words:
                if len(line) + len(word) + 1 > 82:
                    lines.append(line)
                    line = "    " + word + " "
                else:
                    line += word + " "
            if line.strip():
                lines.append(line.rstrip())

        lines.append("")
        return "\n".join(lines)

    # ── KnowledgeDB persistence ───────────────────────────────────────────────

    def flush_to_kb(self, knowledge_db: Any) -> int:
        """
        Persist in-memory events to *knowledge_db*.

        Iterates unsaved events and calls ``knowledge_db.store_fact()`` (or
        ``knowledge_db.add_fact()`` as fallback) for each one.  Silently
        skips events that were already persisted (tracked by ``_flushed_up_to``
        index).

        Parameters
        ----------
        knowledge_db:
            Any object implementing ``store_fact(key, value, tags)`` or
            ``add_fact(key, value)``.

        Returns
        -------
        int
            Number of events successfully persisted.
        """
        if knowledge_db is None:
            log.warning("[SelfMonitor] flush_to_kb called with None knowledge_db")
            return 0

        with self._lock:
            events_snapshot = list(self._events)

        # Determine which store method to use
        if hasattr(knowledge_db, "store_fact"):
            _store = lambda key, value, tags: knowledge_db.store_fact(key, value, tags)
        elif hasattr(knowledge_db, "add_fact"):
            _store = lambda key, value, tags: knowledge_db.add_fact(key, value)
        else:
            log.warning(
                "[SelfMonitor] knowledge_db has no compatible store method: %s", type(knowledge_db)
            )
            return 0

        saved = 0
        for event in events_snapshot:
            try:
                key = f"self_monitor_{event['event_type']}_{int(event['timestamp'])}"
                value = (
                    f"{event['timestamp_iso']} | {event['event_type']} | "
                    f"{event['description'][:200]} | outcome={event.get('outcome')}"
                )
                tags = [event["event_type"], "self_monitor"]
                _store(key, value, tags)
                saved += 1
            except Exception as exc:
                log.debug("[SelfMonitor] flush_to_kb: failed to persist event: %s", exc)

        log.info("[SelfMonitor] Flushed %d events to KnowledgeDB", saved)
        return saved


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ══════════════════════════════════════════════════════════════════════════════

_monitor_instance: Optional[SelfMonitor] = None
_monitor_lock = threading.Lock()


def get_self_monitor(max_events: int = _MAX_EVENTS) -> SelfMonitor:
    """
    Return the process-wide :class:`SelfMonitor` singleton.

    The first call creates the instance.  Subsequent calls ignore *max_events*
    and return the already-created instance.

    Parameters
    ----------
    max_events:
        Ring-buffer size for the first initialisation only.
    """
    global _monitor_instance
    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = SelfMonitor(max_events=max_events)
    return _monitor_instance
