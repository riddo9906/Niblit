#!/usr/bin/env python3
"""Cross-repo distributed runtime coordination layer (Niblit ↔ cloud ↔ lean).

Unifies runtime contracts across:
- riddo9906/Niblit (core cognition/governance authority)
- riddo9906/Niblit-cloud-server (cloud runtime node)
- riddo9906/niblit-lean-algos (governed execution substrate)

The coordinator is additive and best-effort: failures in external runtimes never
block local cognition. It emits canonical Ω.7 events and maintains a replay-safe
coordination trace.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.governance_contract import (
    anti_drift_report,
    compatibility_metadata,
    normalize_runtime_mode,
    validate_runtime_contract,
)
from shared.governance_contract.event_constants import (
    EVENT_EXECUTION_ENVELOPE_PUBLISHED,
    EVENT_MARKET_EPISODE_INGESTED,
    EVENT_RUNTIME_MODE_CHANGED,
    EVENT_TRADE_REFLECTION_INGESTED,
)

log = logging.getLogger("DistributedRuntimeCoordinator")

_SCHEMA_VERSION = "2.0"

_CLOUD_URL = os.environ.get("NIBLIT_CLOUD_RUNTIME_URL", "").strip()
_CLOUD_STATUS_PATH = os.environ.get("NIBLIT_CLOUD_RUNTIME_STATUS_PATH", "/v1/runtime/status").strip() or "/v1/runtime/status"
_CLOUD_BRIDGE_PATH = os.environ.get("NIBLIT_CLOUD_RUNTIME_BRIDGE_PATH", "/niblit/runtime").strip() or "/niblit/runtime"
_CLOUD_TIMEOUT = float(os.environ.get("NIBLIT_CLOUD_RUNTIME_TIMEOUT", "2.5"))

_SIGNAL_FILE = Path(
    os.environ.get(
        "NIBLIT_SIGNAL_FILE",
        os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_lean_signal.json"),
    )
)
_REFLECTION_FILE = Path(
    os.environ.get(
        "NIBLIT_REFLECTION_FILE",
        os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_trade_reflection.jsonl"),
    )
)
_EPISODES_FILE = Path(
    os.environ.get(
        "NIBLIT_EPISODES_FILE",
        os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_market_episodes.jsonl"),
    )
)

_TRACE_FILE = Path(
    os.environ.get(
        "NIBLIT_COORD_TRACE_FILE",
        os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_runtime_coord_trace.jsonl"),
    )
)

_COMPATIBILITY = compatibility_metadata()


@dataclass
class CoordinationState:
    runtime_contract: dict[str, Any]
    source: str
    refreshed_at: float = field(default_factory=time.time)
    cloud_reachable: bool = False
    cloud_status_code: int | None = None
    reflection_ingested: int = 0
    episodes_ingested: int = 0
    node_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_contract": dict(self.runtime_contract),
            "source": self.source,
            "refreshed_at": self.refreshed_at,
            "cloud_reachable": self.cloud_reachable,
            "cloud_status_code": self.cloud_status_code,
            "reflection_ingested": self.reflection_ingested,
            "episodes_ingested": self.episodes_ingested,
            "node_count": self.node_count,
        }


class DistributedRuntimeCoordinator:
    """Canonical unification layer for runtime contracts and federation posture."""

    def __init__(
        self,
        *,
        cloud_url: str = _CLOUD_URL,
        cloud_status_path: str = _CLOUD_STATUS_PATH,
        cloud_bridge_path: str = _CLOUD_BRIDGE_PATH,
        cloud_timeout_s: float = _CLOUD_TIMEOUT,
        signal_file: Path = _SIGNAL_FILE,
        reflection_file: Path = _REFLECTION_FILE,
        episodes_file: Path = _EPISODES_FILE,
        trace_file: Path = _TRACE_FILE,
    ) -> None:
        self.cloud_url = (cloud_url or "").rstrip("/")
        self.cloud_status_path = cloud_status_path
        self.cloud_bridge_path = cloud_bridge_path
        self.cloud_timeout_s = cloud_timeout_s
        self.signal_file = Path(signal_file)
        self.reflection_file = Path(reflection_file)
        self.episodes_file = Path(episodes_file)
        self.trace_file = Path(trace_file)

        self._lock = threading.Lock()
        self._last_state = CoordinationState(runtime_contract=self._default_contract(), source="default")
        self._last_runtime_mode = "normal"
        self._reflection_cursor = 0
        self._episodes_cursor = 0
        self._refresh_count = 0

        self._registry = self._create_node_registry()
        self._register_static_nodes()

    # ── public API ───────────────────────────────────────────────────────────

    def refresh(self) -> CoordinationState:
        cloud_payload, cloud_ok, cloud_code = self._read_cloud_contract()
        local_payload = self._read_local_signal()

        contract, source = self._compose_contract(cloud_payload=cloud_payload, local_payload=local_payload)
        runtime_mode = self._normalize_runtime_mode(
            (contract.get("runtime") or {}).get("mode")
            or (contract.get("governance") or {}).get("governance_mode")
            or "normal"
        )

        reflections = self._read_jsonl_since(self.reflection_file, cursor=self._reflection_cursor, limit=200)
        episodes = self._read_jsonl_since(self.episodes_file, cursor=self._episodes_cursor, limit=200)

        with self._lock:
            self._refresh_count += 1
            self._reflection_cursor += len(reflections)
            self._episodes_cursor += len(episodes)
            self._emit_ingestion_events(reflections=reflections, episodes=episodes)

            if runtime_mode != self._last_runtime_mode:
                self._emit_runtime_mode_change(prev=self._last_runtime_mode, new=runtime_mode)
                self._last_runtime_mode = runtime_mode

            self._emit_envelope_published(contract)
            self._append_trace(contract=contract, source=source, reflections=len(reflections), episodes=len(episodes))

            self._register_dynamic_nodes(cloud_payload=cloud_payload, local_payload=local_payload)
            node_count = self._node_count()

            self._last_state = CoordinationState(
                runtime_contract=contract,
                source=source,
                cloud_reachable=cloud_ok,
                cloud_status_code=cloud_code,
                reflection_ingested=self._reflection_cursor,
                episodes_ingested=self._episodes_cursor,
                node_count=node_count,
            )
            return self._last_state

    def runtime_contract(self) -> dict[str, Any]:
        """Return latest normalized runtime contract (refreshes first)."""
        return self.refresh().runtime_contract

    def status(self) -> dict[str, Any]:
        state = self._last_state
        runtime_validation = validate_runtime_contract(state.runtime_contract)
        drift = anti_drift_report(
            contract=state.runtime_contract,
            compatibility=_COMPATIBILITY,
            observed_events=[
                EVENT_EXECUTION_ENVELOPE_PUBLISHED,
                EVENT_TRADE_REFLECTION_INGESTED,
                EVENT_MARKET_EPISODE_INGESTED,
                EVENT_RUNTIME_MODE_CHANGED,
            ],
        )
        federation_status: dict[str, Any] = {}
        try:
            from modules.federation_foundation import get_federation_foundation

            federation = get_federation_foundation()
            federation_status = federation.status()
        except Exception:
            federation_status = {}

        out = {
            "schema_version": _SCHEMA_VERSION,
            "refresh_count": self._refresh_count,
            "source": state.source,
            "compatibility": dict(_COMPATIBILITY),
            "cloud": {
                "url": self.cloud_url,
                "reachable": state.cloud_reachable,
                "status_code": state.cloud_status_code,
            },
            "local_paths": {
                "signal_file": str(self.signal_file),
                "reflection_file": str(self.reflection_file),
                "episodes_file": str(self.episodes_file),
                "trace_file": str(self.trace_file),
            },
            "runtime_mode": (state.runtime_contract.get("runtime") or {}).get("mode", "normal"),
            "governance_mode": (state.runtime_contract.get("governance") or {}).get("governance_mode", "normal"),
            "coherence_score": (state.runtime_contract.get("temporal") or {}).get("coherence_score", 1.0),
            "epoch_id": (state.runtime_contract.get("temporal") or {}).get("epoch_id", 0),
            "reflection_ingested": state.reflection_ingested,
            "episodes_ingested": state.episodes_ingested,
            "node_count": state.node_count,
            "nodes": self._list_nodes(),
            "runtime_validation": runtime_validation,
            "drift_report": drift,
            "federation": federation_status,
        }
        return out

    def cluster_status(self) -> dict[str, Any]:
        """Federation-readiness cluster status (standalone-compatible)."""
        st = self.status()
        return {
            "status": "standalone_with_federation_readiness",
            "federation_ready": True,
            "federation_mode": "passive",
            "node_count": st.get("node_count", 0),
            "nodes": st.get("nodes", []),
            "runtime_mode": st.get("runtime_mode", "normal"),
            "governance_mode": st.get("governance_mode", "normal"),
            "coherence_score": st.get("coherence_score", 1.0),
            "epoch_id": st.get("epoch_id", 0),
        }

    def federation_peers(self) -> list[dict[str, Any]]:
        """Expose known nodes as federation peers."""
        nodes = self._list_nodes()
        peers: list[dict[str, Any]] = []
        for node in nodes:
            peers.append(
                {
                    "node_id": node.get("node_id"),
                    "node_type": node.get("node_type"),
                    "status": node.get("status", "unknown"),
                    "capabilities": node.get("capabilities", {}),
                }
            )
        return peers

    # ── normalization helpers ────────────────────────────────────────────────

    @staticmethod
    def _normalize_runtime_mode(mode: Any) -> str:
        return normalize_runtime_mode(mode)

    @staticmethod
    def _default_contract() -> dict[str, Any]:
        now = int(time.time())
        return {
            "schema_version": _SCHEMA_VERSION,
            "compatibility": dict(_COMPATIBILITY),
            "timestamp": now,
            "epoch": now,
            "signal": "HOLD",
            "confidence": 0.5,
            "market_regime": "ranging",
            "forecast_consensus": {
                "direction": "NEUTRAL",
                "agreement": 0.5,
                "uncertainty": 0.5,
            },
            "governance": {
                "constitution_passed": True,
                "governance_mode": "normal",
                "survival_mode": False,
                "governance_stability": 1.0,
                "risk_tier": "medium",
                "authority": "niblit_core",
                "current_drawdown_pct": 0.0,
                "max_drawdown_pct": 0.12,
            },
            "execution": {
                "max_position_size": 0.02,
                "stoploss_override": None,
                "allow_scale_in": False,
                "hold_only": False,
                "runtime_stability": 1.0,
                "execution_priority": "normal",
            },
            "runtime": {
                "mode": "normal",
                "health": "ok",
                "instability": 0.0,
                "attention_pressure": 0.0,
                "runtime_health": 1.0,
                "runtime_pressure": 0.0,
                "model_orchestration_state": "standalone",
            },
            "temporal": {
                "epoch_id": now,
                "coherence_score": 1.0,
                "coherence_drift": 0.0,
                "epoch_alignment": "aligned",
                "temporal_epoch": now,
            },
            "resources": {
                "cognitive_budget": 1.0,
                "attention_available": 1.0,
            },
            "reflection": {
                "reflection_confidence": 0.5,
            },
            "trace": {
                "causal_trace_id": f"runtime-{now}",
                "memory_reference_ids": [],
                "subsystem_authority": "niblit_core",
            },
            "model_consensus": 0.5,
            "strategy_disagreement": 0.0,
            "coherence_drift": 0.0,
            "governance_confidence": 0.5,
            "model_trust": 0.5,
            "execution_risk": 0.0,
            "resource_state": {
                "cognitive_budget": 1.0,
                "attention_available": 1.0,
            },
        }

    def _compose_contract(
        self,
        *,
        cloud_payload: dict[str, Any] | None,
        local_payload: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str]:
        contract = self._default_contract()
        source = "default"

        if isinstance(local_payload, dict):
            source = "local"
            contract = self._deep_merge(contract, local_payload)

        if isinstance(cloud_payload, dict):
            source = "cloud"
            contract = self._deep_merge(contract, cloud_payload)

        # canonical mode normalization across all repos
        runtime = dict(contract.get("runtime") or {})
        governance = dict(contract.get("governance") or {})
        mode = self._normalize_runtime_mode(runtime.get("mode") or governance.get("governance_mode") or "normal")
        runtime["mode"] = mode
        governance["governance_mode"] = mode
        governance["survival_mode"] = bool(mode in {"survival", "lockdown"} or governance.get("survival_mode", False))

        contract["runtime"] = runtime
        contract["governance"] = governance

        temporal = dict(contract.get("temporal") or {})
        if "coherence_drift" not in temporal:
            temporal["coherence_drift"] = float(contract.get("coherence_drift", 0.0))
        contract["temporal"] = temporal

        # runtime_adapter compatibility aliases
        contract["governance_mode"] = mode
        contract["compatibility"] = dict(_COMPATIBILITY)
        contract["resource_state"] = {
            "cognitive_budget": float((contract.get("resources") or {}).get("cognitive_budget", 1.0)),
            "attention_available": float((contract.get("resources") or {}).get("attention_available", 1.0)),
        }
        contract["coherence_drift"] = float((contract.get("temporal") or {}).get("coherence_drift", contract.get("coherence_drift", 0.0)))

        return contract, source

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        out = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = DistributedRuntimeCoordinator._deep_merge(out[key], value)
            else:
                out[key] = value
        return out

    # ── source readers ───────────────────────────────────────────────────────

    def _read_cloud_contract(self) -> tuple[dict[str, Any] | None, bool, int | None]:
        if not self.cloud_url:
            return None, False, None

        for path in (self.cloud_status_path, self.cloud_bridge_path):
            url = f"{self.cloud_url}{path}"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=self.cloud_timeout_s) as resp:
                    code = getattr(resp, "status", 200)
                    raw = resp.read().decode("utf-8", errors="replace")
                    payload = json.loads(raw) if raw else {}

                    if isinstance(payload, dict):
                        if path == self.cloud_status_path:
                            payload = self._from_cloud_status(payload)
                        return payload, True, code
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
                continue
        return None, False, None

    def _from_cloud_status(self, status: dict[str, Any]) -> dict[str, Any]:
        """Map cloud /v1/runtime/status payload to contract shape."""
        now = int(time.time())
        runtime = dict(status.get("runtime") or {})
        governance = dict(status.get("governance") or {})
        coherence = dict(status.get("coherence") or {})
        attention = dict(status.get("attention") or {})
        temporal = dict(status.get("epoch") or {})
        models = dict(status.get("models") or {})
        trading = dict(status.get("trading") or {})

        mode = self._normalize_runtime_mode(runtime.get("mode") or governance.get("governance_mode") or "normal")
        coherence_score = float(coherence.get("score", coherence.get("coherence_ema", 1.0)))
        attention_pressure = float(attention.get("pressure", attention.get("attention_pressure", 0.0)))
        runtime_health = float(runtime.get("health_score", runtime.get("runtime_health", 1.0)))
        cognitive_budget = float(attention.get("budget", attention.get("cognitive_budget", 1.0)))
        agreement = float((trading.get("forecast_consensus") or {}).get("agreement", 0.5))
        uncertainty = float((trading.get("forecast_consensus") or {}).get("uncertainty", 0.5))
        direction = str((trading.get("forecast_consensus") or {}).get("direction", "NEUTRAL")).upper()

        return {
            "schema_version": _SCHEMA_VERSION,
            "timestamp": now,
            "epoch": int(temporal.get("current", temporal.get("epoch_id", now))),
            "signal": str(trading.get("signal", "HOLD")).upper(),
            "confidence": float(trading.get("confidence", 0.5)),
            "market_regime": str(trading.get("market_regime", "ranging")),
            "forecast_consensus": {
                "direction": direction,
                "agreement": max(0.0, min(1.0, agreement)),
                "uncertainty": max(0.0, min(1.0, uncertainty)),
            },
            "governance": {
                "constitution_passed": bool(governance.get("constitution_passed", True)),
                "governance_mode": mode,
                "survival_mode": bool(governance.get("survival_mode", mode in {"survival", "lockdown"})),
                "governance_stability": max(0.0, min(1.0, float(governance.get("stability", 1.0)))),
                "risk_tier": str(governance.get("risk_tier", "medium")),
                "authority": "cloud_runtime",
                "current_drawdown_pct": float(governance.get("current_drawdown_pct", 0.0)),
                "max_drawdown_pct": float(governance.get("max_drawdown_pct", 0.12)),
            },
            "runtime": {
                "mode": mode,
                "health": str(runtime.get("health", "ok")),
                "instability": max(0.0, min(1.0, float(runtime.get("instability", 0.0)))),
                "attention_pressure": max(0.0, min(1.0, attention_pressure)),
                "runtime_health": max(0.0, min(1.0, runtime_health)),
                "runtime_pressure": max(0.0, min(1.0, float(runtime.get("pressure", attention_pressure)))),
                "model_orchestration_state": str(models.get("state", "unknown")),
            },
            "temporal": {
                "epoch_id": int(temporal.get("current", temporal.get("epoch_id", now))),
                "coherence_score": max(0.0, min(1.0, coherence_score)),
                "coherence_drift": max(0.0, min(1.0, float(coherence.get("drift", 0.0)))),
                "epoch_alignment": str(temporal.get("alignment", "aligned")),
                "temporal_epoch": int(temporal.get("current", temporal.get("epoch_id", now))),
            },
            "resources": {
                "cognitive_budget": max(0.0, min(1.0, cognitive_budget)),
                "attention_available": max(0.0, min(1.0, float(attention.get("available", cognitive_budget)))),
            },
            "model_consensus": max(0.0, min(1.0, float(trading.get("model_consensus", agreement)))),
            "strategy_disagreement": max(0.0, min(1.0, float(trading.get("strategy_disagreement", 0.0)))),
            "model_trust": max(0.0, min(1.0, float(models.get("trust", 0.5)))),
            "execution_risk": max(0.0, min(1.0, float(trading.get("execution_risk", 0.0)))),
        }

    def _read_local_signal(self) -> dict[str, Any] | None:
        try:
            if not self.signal_file.exists():
                return None
            with self.signal_file.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, dict):
                return None
            return payload
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _read_jsonl_since(path: Path, *, cursor: int, limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            if not path.exists():
                return out
            with path.open("r", encoding="utf-8") as fh:
                for idx, line in enumerate(fh):
                    if idx < cursor:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        out.append(payload)
                        if len(out) >= limit:
                            break
        except OSError:
            return out
        return out

    # ── events / traces ───────────────────────────────────────────────────────

    def _emit_runtime_mode_change(self, *, prev: str, new: str) -> None:
        try:
            from modules.event_bus import EVENT_RUNTIME_MODE_CHANGED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_RUNTIME_MODE_CHANGED,  # canonical value preserved by shared contract
                    source="distributed_runtime_coordinator",
                    payload={"previous_mode": prev, "new_mode": new, "timestamp": int(time.time())},
                )
            )
        except Exception:
            pass

    def _emit_envelope_published(self, contract: dict[str, Any]) -> None:
        try:
            from modules.event_bus import EVENT_EXECUTION_ENVELOPE_PUBLISHED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_EXECUTION_ENVELOPE_PUBLISHED,  # canonical value preserved by shared contract
                    source="distributed_runtime_coordinator",
                    payload={
                        "schema_version": contract.get("schema_version", _SCHEMA_VERSION),
                        "runtime_mode": (contract.get("runtime") or {}).get("mode", "normal"),
                        "epoch_id": (contract.get("temporal") or {}).get("epoch_id", 0),
                    },
                )
            )
        except Exception:
            pass

    def _emit_ingestion_events(self, *, reflections: list[dict[str, Any]], episodes: list[dict[str, Any]]) -> None:
        try:
            from modules.event_bus import (
                EVENT_MARKET_EPISODE_INGESTED,
                EVENT_TRADE_REFLECTION_INGESTED,
                NiblitEvent,
                get_event_bus,
            )

            bus = get_event_bus()
            for item in reflections:
                bus.publish(
                    NiblitEvent(
                        type=EVENT_TRADE_REFLECTION_INGESTED,
                        source="distributed_runtime_coordinator",
                        payload=item,
                    )
                )
            for item in episodes:
                bus.publish(
                    NiblitEvent(
                        type=EVENT_MARKET_EPISODE_INGESTED,
                        source="distributed_runtime_coordinator",
                        payload=item,
                    )
                )
        except Exception:
            pass

    def _append_trace(self, *, contract: dict[str, Any], source: str, reflections: int, episodes: int) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "timestamp": int(time.time()),
            "source": source,
            "runtime_mode": (contract.get("runtime") or {}).get("mode", "normal"),
            "governance_mode": (contract.get("governance") or {}).get("governance_mode", "normal"),
            "epoch_id": (contract.get("temporal") or {}).get("epoch_id", 0),
            "coherence_score": (contract.get("temporal") or {}).get("coherence_score", 1.0),
            "coherence_drift": (contract.get("temporal") or {}).get("coherence_drift", 0.0),
            "attention_pressure": (contract.get("runtime") or {}).get("attention_pressure", 0.0),
            "runtime_health": (contract.get("runtime") or {}).get("runtime_health", 1.0),
            "model_trust": contract.get("model_trust", 0.5),
            "execution_risk": contract.get("execution_risk", 0.0),
            "reflections_ingested": reflections,
            "episodes_ingested": episodes,
            "trace_id": (contract.get("trace") or {}).get("causal_trace_id", f"coord-{int(time.time())}"),
        }

        try:
            self.trace_file.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ── federation-ready node registry ───────────────────────────────────────

    @staticmethod
    def _create_node_registry() -> Any:
        try:
            from distributed_niblit.orchestrator.node_registry import NodeRegistry

            return NodeRegistry()
        except Exception:
            return None

    def _register_static_nodes(self) -> None:
        if self._registry is None:
            return
        try:
            self._registry.register_node(
                "niblit-core",
                "cognitive_core",
                {
                    "governance_authority": True,
                    "execution_envelope": True,
                    "event_semantics": "omega.7",
                    "standalone": True,
                },
            )
            self._registry.register_node(
                "niblit-cloud-runtime",
                "cloud_runtime",
                {
                    "inference": True,
                    "federation_stub": True,
                    "envelope_v2": True,
                },
            )
            self._registry.register_node(
                "niblit-lean-execution",
                "governed_execution",
                {
                    "trade_governance": True,
                    "replay_trace": True,
                    "envelope_v2": True,
                },
            )
        except Exception:
            pass

    def _register_dynamic_nodes(
        self,
        *,
        cloud_payload: dict[str, Any] | None,
        local_payload: dict[str, Any] | None,
    ) -> None:
        if self._registry is None:
            return
        try:
            if isinstance(cloud_payload, dict):
                self._registry.update_status("niblit-cloud-runtime", "active")
            else:
                self._registry.update_status("niblit-cloud-runtime", "degraded")
        except Exception:
            pass
        try:
            if isinstance(local_payload, dict):
                self._registry.update_status("niblit-lean-execution", "active")
            else:
                self._registry.update_status("niblit-lean-execution", "degraded")
        except Exception:
            pass

    def _list_nodes(self) -> list[dict[str, Any]]:
        if self._registry is None:
            return []
        try:
            return list(self._registry.list_nodes())
        except Exception:
            return []

    def _node_count(self) -> int:
        return len(self._list_nodes())


_coordinator: DistributedRuntimeCoordinator | None = None
_coord_lock = threading.Lock()


def get_distributed_runtime_coordinator() -> DistributedRuntimeCoordinator:
    global _coordinator
    with _coord_lock:
        if _coordinator is None:
            _coordinator = DistributedRuntimeCoordinator()
    return _coordinator


if __name__ == "__main__":
    print("Running distributed_runtime_coordinator.py")
