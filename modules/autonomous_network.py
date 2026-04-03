"""
modules/autonomous_network.py — Self-evolving intelligent network for Niblit.

Manages all of Niblit's outbound/inbound connectivity autonomously.  The
network uses Niblit's own research, learning, self-teaching, training, and
reflection capabilities to continuously improve how it collects data and
communicates.

Key goals:
  1. Robustness  — reconnect silently, circuit-break failing endpoints
  2. Intelligence — prioritise sources by historical yield
  3. Independence — adapt strategies without human intervention
  4. Data quality — improve raw data collection efficiency over time
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("AutonomousNetwork")

try:
    from niblit_memory import _writable_path as _mem_writable_path  # type: ignore[import]
except Exception:
    def _mem_writable_path(fn: str, env_var: Optional[str] = None) -> str:  # type: ignore[misc]
        if env_var:
            v = os.environ.get(env_var, "").strip()
            if v:
                return v
        cwd = os.getcwd()
        return os.path.join(cwd, fn) if os.access(cwd, os.W_OK) else os.path.join(tempfile.gettempdir(), fn)

_NET_STATE_FILE = _mem_writable_path("niblit_net_state.json", "NIBLIT_NET_STATE_PATH")

# ── constants ────────────────────────────────────────────────────────────────

_EVOLVE_INTERVAL_SECS = int(os.getenv("NIBLIT_NET_EVOLVE_INTERVAL", "300"))   # 5 min
_HEALTH_INTERVAL_SECS = int(os.getenv("NIBLIT_NET_HEALTH_INTERVAL", "60"))    # 1 min
_MAX_ENDPOINT_FAILURES = int(os.getenv("NIBLIT_NET_MAX_FAILURES", "5"))


class EndpointStats:
    """Track per-endpoint success/failure/yield metrics."""

    __slots__ = ("url", "successes", "failures", "total_bytes", "avg_latency_ms",
                 "last_used", "last_error", "tags")

    def __init__(self, url: str, tags: Optional[List[str]] = None) -> None:
        self.url = url
        self.successes = 0
        self.failures = 0
        self.total_bytes = 0
        self.avg_latency_ms: float = 0.0
        self.last_used: Optional[str] = None
        self.last_error: Optional[str] = None
        self.tags: List[str] = tags or []

    @property
    def total_calls(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        return self.successes / self.total_calls if self.total_calls else 0.0

    @property
    def yield_score(self) -> float:
        """Higher is better — combines success rate and data volume."""
        volume_norm = min(self.total_bytes / 1_000_000, 1.0)  # cap at 1 MB
        return 0.7 * self.success_rate + 0.3 * volume_norm

    def record_success(self, bytes_received: int = 0, latency_ms: float = 0.0) -> None:
        self.successes += 1
        self.total_bytes += bytes_received
        # Exponential moving average
        self.avg_latency_ms = 0.8 * self.avg_latency_ms + 0.2 * latency_ms
        self.last_used = datetime.now(timezone.utc).isoformat()

    def record_failure(self, error: str = "") -> None:
        self.failures += 1
        self.last_error = error
        self.last_used = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url, "successes": self.successes, "failures": self.failures,
            "total_bytes": self.total_bytes, "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_used": self.last_used, "last_error": self.last_error,
            "success_rate": round(self.success_rate, 4),
            "yield_score": round(self.yield_score, 4),
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EndpointStats":
        obj = cls(d["url"], d.get("tags", []))
        obj.successes = d.get("successes", 0)
        obj.failures = d.get("failures", 0)
        obj.total_bytes = d.get("total_bytes", 0)
        obj.avg_latency_ms = d.get("avg_latency_ms", 0.0)
        obj.last_used = d.get("last_used")
        obj.last_error = d.get("last_error")
        return obj


class AutonomousNetworkBuilder:
    """Self-evolving network manager.

    Maintains a registry of data endpoints (search APIs, knowledge sources,
    research backends) with per-endpoint performance statistics.  A background
    evolution loop uses Niblit's own learning pipeline to:

    - Promote high-yield endpoints to "priority" tier
    - Demote or quarantine repeatedly-failing endpoints
    - Discover new endpoints via research (when a ResearchAgent is available)
    - Adapt request patterns (rate, concurrency) based on latency feedback
    """

    def __init__(self, core: Optional[Any] = None) -> None:
        self.core = core
        self._endpoints: Dict[str, EndpointStats] = {}
        self._quarantine: Dict[str, str] = {}   # url → reason
        self._lock = threading.Lock()
        self._running = False
        self._health_thread: Optional[threading.Thread] = None
        self._evolve_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._cycle_count = 0
        self._last_evolve: Optional[str] = None
        self._insights: List[str] = []
        self._load_state()
        log.info("[AutNet] Initialised with %d known endpoints", len(self._endpoints))

    # ── endpoint registry ────────────────────────────────────────────────────

    def register(self, url: str, tags: Optional[List[str]] = None) -> None:
        with self._lock:
            if url not in self._endpoints:
                self._endpoints[url] = EndpointStats(url, tags)
                log.debug("[AutNet] Registered endpoint: %s", url)

    def record_call(self, url: str, success: bool, bytes_received: int = 0,
                    latency_ms: float = 0.0, error: str = "") -> None:
        with self._lock:
            if url not in self._endpoints:
                self._endpoints[url] = EndpointStats(url)
            ep = self._endpoints[url]
            if success:
                ep.record_success(bytes_received, latency_ms)
            else:
                ep.record_failure(error)
                if ep.failures >= _MAX_ENDPOINT_FAILURES and ep.success_rate < 0.1:
                    self._quarantine[url] = f"failure_rate>{1-ep.success_rate:.0%}"
                    log.info("[AutNet] Quarantined: %s (%d failures)", url, ep.failures)

    def is_quarantined(self, url: str) -> bool:
        return url in self._quarantine

    def unquarantine(self, url: str) -> None:
        with self._lock:
            self._quarantine.pop(url, None)
            if url in self._endpoints:
                self._endpoints[url].failures = 0

    # ── prioritised endpoint selection ───────────────────────────────────────

    def best_endpoints(self, tag: Optional[str] = None, top_k: int = 5) -> List[str]:
        """Return endpoints sorted by yield_score, excluding quarantined ones."""
        with self._lock:
            eps = [ep for url, ep in self._endpoints.items()
                   if url not in self._quarantine
                   and (tag is None or tag in ep.tags)]
        return [ep.url for ep in sorted(eps, key=lambda e: e.yield_score, reverse=True)[:top_k]]

    # ── background loops ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="NiblitNetHealth")
        self._evolve_thread = threading.Thread(
            target=self._evolve_loop, daemon=True, name="NiblitNetEvolve")
        self._health_thread.start()
        self._evolve_thread.start()
        log.info("[AutNet] Background loops started")

    def stop(self) -> None:
        self._stop.set()
        self._running = False

    def _health_loop(self) -> None:
        while not self._stop.wait(_HEALTH_INTERVAL_SECS):
            try:
                self._health_check()
            except Exception as exc:
                log.debug("[AutNet] Health check error: %s", exc)

    def _evolve_loop(self) -> None:
        while not self._stop.wait(_EVOLVE_INTERVAL_SECS):
            try:
                self._evolve()
                self._save_state()
            except Exception as exc:
                log.debug("[AutNet] Evolve error: %s", exc)

    # ── health check ─────────────────────────────────────────────────────────

    def _health_check(self) -> None:
        """Review quarantine list; attempt to unquarantine if endpoint may recover."""
        with self._lock:
            candidates = list(self._quarantine.items())
        for url, reason in candidates:
            ep = self._endpoints.get(url)
            if ep is None:
                continue
            # Re-admit after 5x the max-failures window if last error is old
            if ep.last_used is None:
                self.unquarantine(url)
                continue
            try:
                last = datetime.fromisoformat(ep.last_used)
                elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                if elapsed > _MAX_ENDPOINT_FAILURES * 60:
                    log.info("[AutNet] Attempting re-admission: %s", url)
                    self.unquarantine(url)
            except Exception:
                pass

    # ── evolution cycle ───────────────────────────────────────────────────────

    def _evolve(self) -> None:
        self._cycle_count += 1
        self._last_evolve = datetime.now(timezone.utc).isoformat()
        log.debug("[AutNet] Evolve cycle %d", self._cycle_count)

        # 1. Analyse endpoint performance and record insight
        with self._lock:
            sorted_eps = sorted(self._endpoints.values(),
                                key=lambda e: e.yield_score, reverse=True)
        if sorted_eps:
            best = sorted_eps[0]
            worst_active = [e for e in sorted_eps if e.url not in self._quarantine][-1] if len(sorted_eps) > 1 else None
            insight = (f"Cycle {self._cycle_count}: best endpoint yield={best.yield_score:.2f} ({best.url})")
            if worst_active:
                insight += f"; lowest active={worst_active.yield_score:.2f} ({worst_active.url})"
            self._insights = (self._insights + [insight])[-50:]

        # 2. If a learning/memory core is available, store insight as a fact
        db = getattr(self.core, "db", None)
        if db is not None and sorted_eps:
            try:
                db.add_fact(
                    key=f"net_evolve_cycle_{self._cycle_count}",
                    value={"best_url": sorted_eps[0].url,
                           "best_yield": sorted_eps[0].yield_score,
                           "quarantined": len(self._quarantine),
                           "total_endpoints": len(self._endpoints)},
                    tags=["network", "evolve"],
                )
            except Exception:
                pass

        # 3. Trigger research for new endpoints when the core has a researcher
        researcher = getattr(self.core, "self_researcher", None)
        if researcher is not None and self._cycle_count % 3 == 0:
            try:
                researcher.add_topic("network_data_sources")
            except Exception:
                pass

        # 4. Emit event
        _bus = None
        try:
            from core.event_bus import get_event_bus, EventType  # type: ignore[import]
            _bus = get_event_bus()
        except Exception:
            pass
        if _bus:
            try:
                _bus.publish(EventType.SYSTEM_UPDATE,  # type: ignore[arg-type]
                             {"source": "AutonomousNetworkBuilder",
                              "cycle": self._cycle_count,
                              "quarantined": len(self._quarantine)})
            except Exception:
                pass

    # ── reflect / improve integration ────────────────────────────────────────

    def reflect(self) -> str:
        """Use ReflectModule to analyse network performance and return advice."""
        reflect_mod = getattr(self.core, "reflect", None)
        if reflect_mod is None:
            return self._basic_reflection()
        try:
            summary = self.status()
            prompt = (f"Network status:\n{summary}\n\n"
                      "What improvements should be made to the network strategy?")
            return str(reflect_mod.reflect(prompt))
        except Exception:
            return self._basic_reflection()

    def _basic_reflection(self) -> str:
        with self._lock:
            total = len(self._endpoints)
            q = len(self._quarantine)
            active = total - q
        return (f"[AutNet Reflection] {active}/{total} endpoints active, "
                f"{q} quarantined. Evolve cycle: {self._cycle_count}.")

    # ── persistence ───────────────────────────────────────────────────────────

    def _save_state(self) -> None:
        state = {
            "cycle_count": self._cycle_count,
            "last_evolve": self._last_evolve,
            "endpoints": {url: ep.to_dict() for url, ep in self._endpoints.items()},
            "quarantine": self._quarantine,
            "insights": self._insights[-20:],
        }
        try:
            with open(_NET_STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            log.debug("[AutNet] State save error: %s", exc)

    def _load_state(self) -> None:
        try:
            if os.path.exists(_NET_STATE_FILE):
                with open(_NET_STATE_FILE, "r", encoding="utf-8") as fh:
                    state = json.load(fh)
                self._cycle_count = state.get("cycle_count", 0)
                self._last_evolve = state.get("last_evolve")
                self._insights = state.get("insights", [])
                self._quarantine = state.get("quarantine", {})
                for url, ep_dict in state.get("endpoints", {}).items():
                    self._endpoints[url] = EndpointStats.from_dict(ep_dict)
        except Exception as exc:
            log.debug("[AutNet] State load error: %s", exc)

    # ── status / commands ─────────────────────────────────────────────────────

    def status(self) -> str:
        with self._lock:
            eps = sorted(self._endpoints.values(), key=lambda e: e.yield_score, reverse=True)
            q_count = len(self._quarantine)
        lines = [
            f"🌐 **AutonomousNetworkBuilder** (cycle {self._cycle_count})",
            f"  Endpoints   : {len(eps)} total, {q_count} quarantined",
            f"  Running     : {'✅' if self._running else '⚫'}",
            f"  Last evolve : {self._last_evolve or 'never'}",
        ]
        if eps:
            lines.append("\n  Top 5 endpoints by yield:")
            for ep in eps[:5]:
                qflag = " ⚠️ QUARANTINED" if ep.url in self._quarantine else ""
                lines.append(f"    [{ep.yield_score:.2f}] {ep.url}{qflag}")
        if self._insights:
            lines.append(f"\n  Latest insight: {self._insights[-1]}")
        return "\n".join(lines)


# ── singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[AutonomousNetworkBuilder] = None


def get_autonomous_network(core: Optional[Any] = None) -> AutonomousNetworkBuilder:
    global _instance
    if _instance is None:
        _instance = AutonomousNetworkBuilder(core=core)
    elif core is not None and _instance.core is None:
        _instance.core = core
    return _instance


if __name__ == "__main__":
    print("Running autonomous_network.py")
    net = get_autonomous_network()
    net.register("https://api.example.com/search", tags=["search"])
    net.record_call("https://api.example.com/search", success=True, bytes_received=1024, latency_ms=120)
    print(net.status())
