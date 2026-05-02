#!/usr/bin/env python3
"""
nibblebots/observation_collector.py — Phase 4 Unified Observation Layer

The "senses" layer of the Observe → Understand → Decide → Act → Measure → Learn
loop.  All raw signals flow through here and are normalised into a standard
``Observation`` struct before being passed to the semantic engine and impact engine.

Signal sources (all optional — graceful degradation when absent):
  * GitHub Actions failure logs  (already used by get_log_priority_files())
  * events.jsonl                 (runtime event stream)
  * fortress_cycles.jsonl        (fortress execution cycles)
  * niblit_audit_report.json     (static audit signals)
  * niblit_self_heal.log         (self-healing events)

Public API
----------
``Observation``
    NamedTuple: domain, signal_type, severity (0–1), timestamp (ISO), raw (str)

``collect(workspace) → List[Observation]``
    Collect observations from every available source in the workspace.

``collect_from_file(path) → List[Observation]``
    Collect observations from a single file.

``ObservationCollector``
    Stateful collector that caches results and merges new signals.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Observation data structure
# ---------------------------------------------------------------------------

class Observation(NamedTuple):
    domain: str        # e.g. "code", "runtime", "ci", "audit", "self_heal"
    signal_type: str   # e.g. "ci_failure", "exception", "performance_warning"
    severity: float    # 0.0–1.0
    timestamp: str     # ISO-8601
    raw: str           # original text / JSON fragment


# ---------------------------------------------------------------------------
# Severity tables
# ---------------------------------------------------------------------------

_CI_SEVERITY: Dict[str, float] = {
    "failure":   0.80,
    "cancelled": 0.40,
    "skipped":   0.10,
    "success":   0.00,
}

_SELF_HEAL_SEVERITY: Dict[str, float] = {
    "critical": 0.90,
    "error":    0.70,
    "warning":  0.45,
    "info":     0.15,
}

# Regex patterns for log / event parsing
_EXCEPTION_RE = re.compile(
    r"(Traceback|Error|Exception|FAILED|CRITICAL|assertion|ImportError|"
    r"ModuleNotFoundError|TimeoutError|ConnectionError)",
    re.IGNORECASE,
)
_PERF_RE = re.compile(
    r"(timeout|slow|latency|memory|leak|OOM|out.of.memory|performance)",
    re.IGNORECASE,
)
_HEAL_LEVEL_RE = re.compile(
    r"\[(CRITICAL|ERROR|WARNING|INFO)\]", re.IGNORECASE
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Source-specific collectors
# ---------------------------------------------------------------------------

def _collect_events_jsonl(path: Path) -> List[Observation]:
    """Parse runtime events from a JSON-lines event stream file."""
    obs: List[Observation] = []
    if not path.exists():
        return obs
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry: Dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = entry.get("type", entry.get("event", "unknown"))
            ts = entry.get("timestamp", entry.get("ts", _now_iso()))

            # Detect severity from content
            raw_str = json.dumps(entry)
            sev = 0.15
            if _EXCEPTION_RE.search(raw_str):
                sev = 0.70
            elif _PERF_RE.search(raw_str):
                sev = 0.45

            signal = "runtime_exception" if sev >= 0.65 else (
                "performance_warning" if sev >= 0.40 else "runtime_event"
            )

            obs.append(Observation(
                domain="runtime",
                signal_type=signal,
                severity=round(sev, 3),
                timestamp=str(ts),
                raw=raw_str[:512],
            ))
    except OSError:
        pass
    return obs


def _collect_fortress_cycles(path: Path) -> List[Observation]:
    """Parse fortress execution cycle results."""
    obs: List[Observation] = []
    if not path.exists():
        return obs
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry: Dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue

            status = str(entry.get("status", "unknown")).lower()
            sev = 0.30 if status in ("fail", "error") else 0.05
            ts = entry.get("timestamp", _now_iso())

            obs.append(Observation(
                domain="runtime",
                signal_type="fortress_cycle",
                severity=round(sev, 3),
                timestamp=str(ts),
                raw=json.dumps(entry)[:512],
            ))
    except OSError:
        pass
    return obs


def _collect_audit_report(path: Path) -> List[Observation]:
    """Parse niblit_audit_report.json static audit findings."""
    obs: List[Observation] = []
    if not path.exists():
        return obs
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return obs

    # The audit report may have a flat or nested structure; handle both
    issues: List[Any] = []
    if isinstance(data, list):
        issues = data
    elif isinstance(data, dict):
        issues = data.get("issues", data.get("findings", [data]))

    for item in issues:
        if not isinstance(item, dict):
            continue
        severity_str = str(item.get("severity", item.get("level", "low"))).lower()
        sev_map = {"critical": 0.90, "high": 0.70, "medium": 0.45, "low": 0.20, "info": 0.10}
        sev = sev_map.get(severity_str, 0.20)
        ts = item.get("timestamp", _now_iso())
        obs.append(Observation(
            domain="audit",
            signal_type="static_audit_finding",
            severity=round(sev, 3),
            timestamp=str(ts),
            raw=json.dumps(item)[:512],
        ))
    return obs


def _collect_self_heal_log(path: Path) -> List[Observation]:
    """Parse niblit_self_heal.log for structured healing events."""
    obs: List[Observation] = []
    if not path.exists():
        return obs
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue

            m = _HEAL_LEVEL_RE.search(line)
            level = m.group(1).lower() if m else "info"
            sev = _SELF_HEAL_SEVERITY.get(level, 0.15)

            signal = "self_heal_error" if sev >= 0.65 else (
                "self_heal_warning" if sev >= 0.40 else "self_heal_info"
            )

            obs.append(Observation(
                domain="self_heal",
                signal_type=signal,
                severity=round(sev, 3),
                timestamp=_now_iso(),
                raw=line[:512],
            ))
    except OSError:
        pass
    return obs


# ---------------------------------------------------------------------------
# Top-level collection
# ---------------------------------------------------------------------------

def collect(workspace: Optional[Path] = None) -> List[Observation]:
    """Collect observations from every available source in *workspace*.

    Returns a list of :class:`Observation` objects sorted by severity descending.
    """
    ws = workspace or Path(".")
    all_obs: List[Observation] = []

    # events.jsonl (runtime event stream)
    all_obs.extend(_collect_events_jsonl(ws / "events.jsonl"))
    # fortress_cycles.jsonl
    all_obs.extend(_collect_fortress_cycles(ws / "fortress_cycles.jsonl"))
    # niblit_audit_report.json
    all_obs.extend(_collect_audit_report(ws / "niblit_audit_report.json"))
    # niblit_self_heal.log
    all_obs.extend(_collect_self_heal_log(ws / "niblit_self_heal.log"))

    all_obs.sort(key=lambda o: o.severity, reverse=True)
    return all_obs


def collect_from_file(path: Path) -> List[Observation]:
    """Collect observations from a single file (auto-detects format)."""
    name = path.name.lower()
    if name.endswith(".jsonl"):
        if "fortress" in name:
            return _collect_fortress_cycles(path)
        return _collect_events_jsonl(path)
    if name.endswith(".json"):
        return _collect_audit_report(path)
    if name.endswith(".log"):
        return _collect_self_heal_log(path)
    return []


# ---------------------------------------------------------------------------
# Stateful collector class
# ---------------------------------------------------------------------------

class ObservationCollector:
    """Stateful collector that merges signals across multiple collection runs.

    Usage::

        collector = ObservationCollector(workspace=Path("."))
        snapshot = collector.snapshot()          # collect all sources now
        high_sev = collector.filter(min_severity=0.60)  # high-severity only
        summary  = collector.summary()           # aggregate stats
    """

    def __init__(self, workspace: Optional[Path] = None) -> None:
        self._workspace = workspace or Path(".")
        self._observations: List[Observation] = []

    def snapshot(self) -> List[Observation]:
        """Collect fresh observations and cache them.  Returns all collected."""
        self._observations = collect(self._workspace)
        return list(self._observations)

    def filter(
        self,
        min_severity: float = 0.0,
        domain: Optional[str] = None,
        signal_type: Optional[str] = None,
    ) -> List[Observation]:
        """Return observations matching the given filters."""
        result = self._observations
        if min_severity > 0.0:
            result = [o for o in result if o.severity >= min_severity]
        if domain:
            result = [o for o in result if o.domain == domain]
        if signal_type:
            result = [o for o in result if o.signal_type == signal_type]
        return result

    def summary(self) -> Dict[str, Any]:
        """Return aggregate statistics about the current observation set."""
        obs = self._observations
        if not obs:
            return {"total": 0}

        domain_counts: Dict[str, int] = {}
        signal_counts: Dict[str, int] = {}
        for o in obs:
            domain_counts[o.domain] = domain_counts.get(o.domain, 0) + 1
            signal_counts[o.signal_type] = signal_counts.get(o.signal_type, 0) + 1

        high_sev = [o for o in obs if o.severity >= 0.65]
        avg_sev = sum(o.severity for o in obs) / len(obs)

        return {
            "total": len(obs),
            "high_severity_count": len(high_sev),
            "avg_severity": round(avg_sev, 3),
            "by_domain": domain_counts,
            "by_signal_type": signal_counts,
        }
