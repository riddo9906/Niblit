#!/usr/bin/env python3
"""
ENTERPRISE UTILITY MODULE
Audit logging, health-check aggregation, SLA tracking, and operational tooling
for production-grade AI deployments.
"""

import logging
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("EnterpriseUtility")


class AuditEntry:
    """Immutable record of an enterprise-relevant event."""

    __slots__ = ("ts", "event_type", "actor", "resource", "outcome", "details")

    def __init__(self, event_type: str, actor: str = "system",
                 resource: str = "", outcome: str = "ok", details: str = ""):
        self.ts = datetime.now(timezone.utc).isoformat()
        self.event_type = event_type
        self.actor = actor
        self.resource = resource
        self.outcome = outcome
        self.details = details

    def to_dict(self) -> Dict[str, str]:
        return {
            "ts": self.ts,
            "event_type": self.event_type,
            "actor": self.actor,
            "resource": self.resource,
            "outcome": self.outcome,
            "details": self.details,
        }


class EnterpriseUtility:
    """
    Enterprise-grade operational utilities:
    - Audit log   (immutable chronological record of events)
    - Health registry  (components report their health status)
    - SLA tracker (latency & error-rate counters)
    - Operational summary  (single-pane-of-glass status view)
    """

    MAX_AUDIT_ENTRIES = 1000
    MAX_LATENCY_SAMPLES = 500

    def __init__(self, db=None):
        self.db = db
        self._lock = threading.Lock()

        # Audit log (deque with capped size)
        self._audit_log: deque = deque(maxlen=self.MAX_AUDIT_ENTRIES)

        # Health registry: {component_name: {"status": str, "detail": str, "ts": str}}
        self._health: Dict[str, Dict[str, str]] = {}

        # SLA counters: {operation: {"ok": int, "error": int, "latencies": deque}}
        self._sla: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"ok": 0, "error": 0, "latencies": deque(maxlen=self.MAX_LATENCY_SAMPLES)}
        )

        # Session start
        self._start_time = time.monotonic()

        self._register_self_health()
        log.info("[ENTERPRISE] EnterpriseUtility initialised")

    # ─────────────────────────────────────────────────────
    # Audit log
    # ─────────────────────────────────────────────────────

    def audit(self, event_type: str, actor: str = "system",
              resource: str = "", outcome: str = "ok", details: str = "") -> None:
        """Record an auditable event."""
        entry = AuditEntry(event_type, actor, resource, outcome, details)
        with self._lock:
            self._audit_log.append(entry)
        log.debug(f"[AUDIT] {event_type} | {actor} | {resource} | {outcome}")

    def get_audit_log(self, limit: int = 20, event_type: Optional[str] = None) -> List[Dict[str, str]]:
        """Return the most recent audit entries (newest first)."""
        with self._lock:
            entries = list(self._audit_log)
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]
        return [e.to_dict() for e in reversed(entries[-limit:])]

    # ─────────────────────────────────────────────────────
    # Health registry
    # ─────────────────────────────────────────────────────

    def register_health(self, component: str, status: str = "healthy", detail: str = "") -> None:
        """Register or update a component's health status."""
        with self._lock:
            self._health[component] = {
                "status": status,
                "detail": detail,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

    def get_health_report(self) -> Dict[str, Any]:
        """Return aggregated health of all registered components."""
        with self._lock:
            components = dict(self._health)

        total = len(components)
        healthy = sum(1 for c in components.values() if c["status"] == "healthy")
        degraded = sum(1 for c in components.values() if c["status"] == "degraded")
        unhealthy = total - healthy - degraded

        overall = "healthy" if unhealthy == 0 and degraded == 0 else ("degraded" if unhealthy == 0 else "unhealthy")

        return {
            "overall": overall,
            "total_components": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "components": components,
        }

    # ─────────────────────────────────────────────────────
    # SLA tracker
    # ─────────────────────────────────────────────────────

    def record_operation(self, operation: str, latency_ms: float, success: bool = True) -> None:
        """Record an operation result for SLA tracking."""
        with self._lock:
            slot = self._sla[operation]
            if success:
                slot["ok"] += 1
            else:
                slot["error"] += 1
            slot["latencies"].append(latency_ms)

    def get_sla_report(self) -> Dict[str, Any]:
        """Return SLA metrics for all tracked operations."""
        with self._lock:
            operations = {op: dict(data) for op, data in self._sla.items()}

        report: Dict[str, Any] = {}
        for op, data in operations.items():
            latencies = list(data["latencies"])
            total = data["ok"] + data["error"]
            avg_lat = sum(latencies) / len(latencies) if latencies else None
            max_lat = max(latencies) if latencies else None
            error_rate = data["error"] / total if total else 0.0
            report[op] = {
                "total": total,
                "ok": data["ok"],
                "error": data["error"],
                "error_rate_pct": round(error_rate * 100, 2),
                "avg_latency_ms": round(avg_lat, 2) if avg_lat is not None else None,
                "max_latency_ms": round(max_lat, 2) if max_lat is not None else None,
            }
        return report

    # ─────────────────────────────────────────────────────
    # Operational summary
    # ─────────────────────────────────────────────────────

    def operational_summary(self) -> Dict[str, Any]:
        """Single-pane-of-glass operational status."""
        uptime_s = time.monotonic() - self._start_time
        hours, rem = divmod(int(uptime_s), 3600)
        minutes, seconds = divmod(rem, 60)

        health = self.get_health_report()
        sla = self.get_sla_report()

        with self._lock:
            audit_count = len(self._audit_log)

        return {
            "uptime": f"{hours}h {minutes}m {seconds}s",
            "health": health["overall"],
            "components": health["total_components"],
            "healthy_components": health["healthy"],
            "audit_entries": audit_count,
            "tracked_operations": len(sla),
            "sla": sla,
            "capability": "Enterprise audit, health, and SLA tracking",
            "status": "Operational",
        }

    def format_summary(self) -> str:
        """Human-readable operational summary."""
        summary = self.operational_summary()
        health = self.get_health_report()
        sla = self.get_sla_report()

        lines = [
            "🏢 **ENTERPRISE UTILITY — OPERATIONAL SUMMARY**",
            f"Uptime: {summary['uptime']}",
            f"System Health: {summary['health'].upper()}",
            f"Components: {summary['healthy_components']}/{summary['components']} healthy",
            f"Audit Entries: {summary['audit_entries']}",
            "",
            "📊 **COMPONENT HEALTH:**",
        ]
        for comp, info in health["components"].items():
            icon = "✅" if info["status"] == "healthy" else ("⚠️" if info["status"] == "degraded" else "❌")
            lines.append(f"  {icon} {comp}: {info['status']}" + (f" — {info['detail']}" if info["detail"] else ""))

        if sla:
            lines.append("")
            lines.append("📈 **SLA METRICS:**")
            for op, metrics in sla.items():
                lines.append(f"  • {op}: {metrics['total']} ops | "
                             f"err={metrics['error_rate_pct']}% | "
                             f"avg={metrics['avg_latency_ms']}ms")

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────

    def _register_self_health(self) -> None:
        self.register_health("enterprise_utility", "healthy", "Initialised successfully")
        self.audit("system_start", resource="enterprise_utility", details="EnterpriseUtility online")
