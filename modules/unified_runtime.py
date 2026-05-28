#!/usr/bin/env python3
"""Unified cognitive runtime composition layer for Niblit.

This module does not replace existing subsystems. It composes them behind one
runtime-facing abstraction so UI, API, orchestration, providers, telemetry,
and state can interact through normalized contracts.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from modules.cognitive_episode import CognitiveEpisodeManager, RuntimeSignificanceEngine

log = logging.getLogger("Niblit.UnifiedRuntime")
_DEFAULT_PROVIDER_MAX_TOKENS = int(
    os.getenv("NIBLIT_PROVIDER_MAX_TOKENS", os.getenv("NIBLIT_LOCAL_MAX_NEW", "512"))
)

MAX_EVENT_BUFFER = 2000
MAX_TELEMETRY_HISTORY = 200
MAX_COMMAND_HISTORY = 500
CMD_PREFIX_RUNTIME_PROVIDER = "runtime provider "
CMD_PREFIX_RUNTIME_INFER = "runtime infer "


def _utc_ts() -> float:
    return time.time()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class RuntimeEvent:
    id: int
    type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=_utc_ts)
    significance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["timestamp"] = _iso_now()
        return out


@dataclass
class RuntimeState:
    active_provider: str = "qwen"
    runtime_mode: str = "api"
    loaded_models: list[str] = field(default_factory=list)
    active_agents: list[str] = field(default_factory=list)
    cognitive_sessions: list[dict[str, Any]] = field(default_factory=list)
    sidebar_state: dict[str, Any] = field(default_factory=dict)
    command_history: list[str] = field(default_factory=list)
    telemetry_snapshots: list[dict[str, Any]] = field(default_factory=list)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    deployment: dict[str, Any] = field(default_factory=dict)
    cognitive_episodes: list[dict[str, Any]] = field(default_factory=list)
    cognitive_reflections: list[dict[str, Any]] = field(default_factory=list)
    cognitive_compression: dict[str, Any] = field(default_factory=dict)
    cognitive_datasets: dict[str, Any] = field(default_factory=dict)
    confidence_summary: dict[str, Any] = field(default_factory=dict)
    last_updated_at: float = field(default_factory=_utc_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeState:
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in keys})


class RuntimeEventBus:
    """Thread-safe event bus with replay for UI/runtime consumers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[RuntimeEvent] = []
        self._seq = 0
        self._counts: dict[str, int] = {}
        self._handlers: list[Any] = []
        self._dropped_events = 0
        self._unconsumed_events = 0
        self._timestamps: deque[float] = deque(maxlen=1024)
        self._significance = RuntimeSignificanceEngine()

    def subscribe(self, handler: Any) -> None:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def emit(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> RuntimeEvent:
        with self._lock:
            signaled_payload = dict(payload or {})
            significance = self._significance.score_event(event_type, source, signaled_payload)
            self._seq += 1
            event = RuntimeEvent(
                id=self._seq,
                type=event_type,
                source=source,
                payload=signaled_payload,
                significance=significance,
            )
            self._events.append(event)
            if len(self._events) > MAX_EVENT_BUFFER:
                self._events = self._events[-MAX_EVENT_BUFFER:]
            self._counts[event_type] = self._counts.get(event_type, 0) + 1
            handlers = list(self._handlers)
            self._timestamps.append(time.time())
            if not handlers:
                self._unconsumed_events += 1

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                with self._lock:
                    self._dropped_events += 1
                log.debug("RuntimeEventBus handler error: %s", exc)
        return event

    def events(self, *, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            filtered = [e.to_dict() for e in self._events if e.id > since]
        return filtered[: max(1, min(limit, 500))]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            throughput = sum(1 for ts in self._timestamps if now - ts <= 60.0)
            return {
                "event_counts": dict(self._counts),
                "last_event_id": self._seq,
                "dropped_events": self._dropped_events,
                "unconsumed_events": self._unconsumed_events,
                "throughput_last_minute": throughput,
                "significance": self._significance.summary(),
            }


class ProviderRuntimeManager:
    """Provider-agnostic runtime manager with normalized outputs."""

    _DEFAULT_CAPS: dict[str, dict[str, Any]] = {
        "qwen": {
            "local": True,
            "streaming": False,
            "reasoning": "medium",
            "cost_tier": "low",
            "max_context": 16384,
            "provider_type": "local",
        },
        "local_llama": {
            "local": True,
            "streaming": False,
            "reasoning": "medium",
            "cost_tier": "low",
            "max_context": 16384,
            "provider_type": "local",
        },
        "hf": {
            "local": False,
            "streaming": False,
            "reasoning": "medium",
            "cost_tier": "medium",
            "max_context": 8192,
            "provider_type": "cloud",
        },
        "anthropic": {
            "local": False,
            "streaming": True,
            "reasoning": "high",
            "cost_tier": "high",
            "max_context": 200000,
            "provider_type": "cloud",
        },
        "ruflo": {
            "local": False,
            "streaming": True,
            "reasoning": "high",
            "cost_tier": "medium",
            "max_context": 32768,
            "provider_type": "bridge",
        },
        "openai_compatible": {
            "local": False,
            "streaming": True,
            "reasoning": "high",
            "cost_tier": "medium",
            "max_context": 128000,
            "provider_type": "openai_compatible",
        },
    }

    def __init__(self, event_bus: RuntimeEventBus) -> None:
        self._lock = threading.RLock()
        self._event_bus = event_bus
        self._providers: dict[str, dict[str, Any]] = {
            name: dict(caps) for name, caps in self._DEFAULT_CAPS.items()
        }
        self._health: dict[str, dict[str, Any]] = {
            name: {"healthy": True, "latency_ms": None, "last_error": None}
            for name in self._providers
        }
        self._active_provider = os.environ.get("NIBLIT_LLM_PROVIDER", "qwen").strip().lower() or "qwen"

    def register_provider(self, name: str, capabilities: dict[str, Any]) -> None:
        pname = name.strip().lower()
        if not pname:
            return
        with self._lock:
            self._providers[pname] = dict(capabilities or {})
            self._health.setdefault(pname, {"healthy": True, "latency_ms": None, "last_error": None})
        self._event_bus.emit("provider.registered", "ProviderRuntimeManager", {"provider": pname, "capabilities": capabilities})

    def set_active(self, provider: str) -> str:
        p = provider.strip().lower()
        if p not in self._providers:
            return f"❌ Unknown provider '{provider}'"
        with self._lock:
            self._active_provider = p
        self._event_bus.emit("provider.switched", "ProviderRuntimeManager", {"active_provider": p})
        try:
            from modules.llm_provider_manager import get_llm_provider_manager

            mgr = get_llm_provider_manager()
            if p in {"qwen", "hf", "anthropic", "ruflo"}:
                mgr.switch(p)
        except Exception:
            pass
        return f"✅ Active provider set to **{p}**"

    def _manager_status(self) -> dict[str, Any]:
        try:
            from modules.llm_provider_manager import get_llm_provider_manager

            s = get_llm_provider_manager().status()
            return dict(s or {})
        except Exception:
            return {}

    def status(self) -> dict[str, Any]:
        s = self._manager_status()
        with self._lock:
            active = s.get("active", self._active_provider)
            self._active_provider = active
            for p in ("qwen", "hf", "anthropic", "ruflo"):
                if p in self._health:
                    ok = bool(s.get(p, True))
                    self._health[p]["healthy"] = ok
                    if not ok and not self._health[p].get("last_error"):
                        self._health[p]["last_error"] = "unavailable"
            return {
                "active_provider": self._active_provider,
                "providers": {k: dict(v) for k, v in self._providers.items()},
                "health": {k: dict(v) for k, v in self._health.items()},
                "manager_status": s,
            }

    def _route_provider(
        self,
        *,
        task_type: str,
        local_first: bool,
        offline_mode: bool,
        context_window: int | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        scores: list[dict[str, Any]] = []
        status = self.status()
        active = status["active_provider"]

        for name, caps in status["providers"].items():
            health = status["health"].get(name, {})
            score = 0.0
            if name == active:
                score += 1.0
            if health.get("healthy", True):
                score += 1.0
            if local_first and caps.get("local"):
                score += 2.0
            if offline_mode and caps.get("local"):
                score += 4.0
            if task_type in {"fast", "simple"} and caps.get("cost_tier") == "low":
                score += 1.2
            if task_type in {"deep", "reasoning"} and caps.get("reasoning") == "high":
                score += 2.0
            if context_window and int(caps.get("max_context", 0)) >= context_window:
                score += 1.5
            if context_window and int(caps.get("max_context", 0)) < context_window:
                score -= 1.0
            scores.append({"provider": name, "score": round(score, 3)})

        scores.sort(key=lambda x: x["score"], reverse=True)
        selected = scores[0]["provider"] if scores else active
        return selected, scores

    def generate(
        self,
        prompt: str,
        *,
        task_type: str = "general",
        context: str = "",
        context_window: int | None = None,
        local_first: bool = True,
        offline_mode: bool = False,
        max_tokens: int = _DEFAULT_PROVIDER_MAX_TOKENS,
    ) -> dict[str, Any]:
        selected, scores = self._route_provider(
            task_type=task_type,
            local_first=local_first,
            offline_mode=offline_mode,
            context_window=context_window,
        )
        started = time.perf_counter()
        self._event_bus.emit("provider.started", "ProviderRuntimeManager", {"provider": selected, "task_type": task_type})
        self._event_bus.emit(
            "routing.decision",
            "ProviderRuntimeManager",
            {
                "provider": selected,
                "scores": scores,
                "local_first": local_first,
                "offline_mode": offline_mode,
                "context_window": context_window,
            },
        )

        text = ""
        error = None
        try:
            if selected in {"qwen", "local_llama"}:
                try:
                    from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2

                    rr = NiblitUnifiedRuntimeRouterV2()
                    sig = inspect.signature(rr.generate)
                    kwargs: dict[str, Any] = {"prompt": prompt, "context": context}
                    if "max_tokens" in sig.parameters:
                        kwargs["max_tokens"] = max_tokens
                    if "context_policy" in sig.parameters:
                        kwargs["context_policy"] = {
                            "target_context_window": context_window
                            or int(
                                os.getenv(
                                    "NIBLIT_RUNTIME_CONTEXT_TARGET",
                                    os.getenv("NIBLIT_GGUF_N_CTX", "16384"),
                                )
                            ),
                            "runtime_source": "unified_runtime",
                        }
                    text = rr.generate(**kwargs)
                except Exception:
                    text = ""
            if not text:
                try:
                    from modules.llm_provider_manager import get_llm_provider_manager

                    mgr = get_llm_provider_manager()
                    if selected in {"qwen", "hf", "anthropic", "ruflo"}:
                        mgr.switch(selected)
                    text = mgr.ask(prompt=prompt, system=context, max_tokens=max_tokens) or ""
                except Exception:
                    text = ""
            if not text:
                raise RuntimeError("no provider returned a response")
        except Exception as exc:
            error = str(exc)

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        with self._lock:
            health = self._health.setdefault(selected, {"healthy": True, "latency_ms": None, "last_error": None})
            health["latency_ms"] = latency_ms
            health["healthy"] = error is None
            health["last_error"] = error

        if error:
            self._event_bus.emit("provider.failed", "ProviderRuntimeManager", {"provider": selected, "error": error})
        else:
            self._event_bus.emit("provider.completed", "ProviderRuntimeManager", {"provider": selected, "latency_ms": latency_ms})

        return {
            "stream_format": "niblit.runtime.stream.v1",
            "type": "inference.result",
            "provider": selected,
            "status": "ok" if error is None else "error",
            "text": text if error is None else "",
            "error": error,
            "telemetry": {
                "latency_ms": latency_ms,
                "provider_health": self._health.get(selected, {}),
                "task_type": task_type,
            },
            "tokens": {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            },
            "scores": scores,
            "timestamp": _iso_now(),
        }


class RuntimeTelemetryManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: list[dict[str, Any]] = []

    def snapshot(
        self,
        *,
        core: Any,
        state: RuntimeState,
        provider_status: dict[str, Any],
        event_stats: dict[str, Any],
        cognitive_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import threading as _threading

        facts_count = None
        if core is not None:
            try:
                facts_count = len(core.db.list_facts(limit=500))
            except Exception:
                facts_count = None

        ale_data: dict[str, Any] | None = None
        event_observability: dict[str, Any] = {}
        module_event_observability: dict[str, Any] = {}
        cognition_metrics: dict[str, Any] = {}
        live_ingestion: dict[str, Any] = {}
        if core is not None:
            ale = getattr(core, "autonomous_engine", None)
            if ale is not None:
                ale_data = {
                    "running": bool(getattr(ale, "running", False)),
                    "cycle": int(getattr(ale, "_cycle_count", 0)),
                    "topic": ale.get_current_topic() if hasattr(ale, "get_current_topic") else None,
                }
            try:
                rm = getattr(core, "runtime_manager", None)
                if rm is not None and hasattr(rm, "event_bus") and hasattr(rm.event_bus, "observability_report"):
                    event_observability = rm.event_bus.observability_report()
            except Exception:
                event_observability = {}
        try:
            from modules.event_bus import get_event_bus

            bus = get_event_bus()
            if hasattr(bus, "observability_report"):
                module_event_observability = bus.observability_report()
        except Exception:
            module_event_observability = {}
        try:
            from modules.knowledge_gap_cognition import get_cognition_escalation_layer

            cognition_metrics = get_cognition_escalation_layer().metrics()
        except Exception:
            cognition_metrics = {}
        try:
            from modules.governed_live_cognition import get_governed_live_cognition_collector

            live_ingestion = get_governed_live_cognition_collector().status()
        except Exception:
            live_ingestion = {}

        snap = {
            "stream_format": "niblit.runtime.stream.v1",
            "type": "telemetry.update",
            "timestamp": _iso_now(),
            "runtime_mode": state.runtime_mode,
            "active_provider": state.active_provider,
            "threads": len(_threading.enumerate()),
            "facts_count": facts_count,
            "ale": ale_data,
            "event_bus": event_stats,
            "event_observability": event_observability,
            "module_event_observability": module_event_observability,
            "provider_health": provider_status.get("health", {}),
            "cognition": cognition_metrics,
            "cognitive_runtime": dict(cognitive_status or {}),
            "live_ingestion": live_ingestion,
            "deployment": dict(state.deployment),
        }
        with self._lock:
            self._history.append(dict(snap))
            if len(self._history) > 200:
                self._history = self._history[-200:]
        return snap

    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            return self._history[-max(1, min(limit, 200)) :]


class DeploymentRuntimeManager:
    """Detect runtime topology/environment in a single normalized contract."""

    def detect(self) -> dict[str, Any]:
        env = "local"
        if os.environ.get("FLY_APP_NAME"):
            env = "fly"
        elif os.environ.get("RENDER"):
            env = "render"
        elif os.environ.get("VERCEL"):
            env = "vercel"
        elif os.environ.get("TERMUX_VERSION"):
            env = "termux"
        elif os.environ.get("WSL_DISTRO_NAME"):
            env = "wsl"

        mode = os.environ.get("NIBLIT_RUNTIME_MODE", "api").strip().lower() or "api"
        return {
            "environment": env,
            "runtime_mode": mode,
            "profile": os.environ.get("NIBLIT_RUNTIME_PROFILE", ""),
            "llm_backend": os.environ.get("NIBLIT_GGUF_BACKEND", ""),
            "llama_server_url": os.environ.get("NIBLIT_LLAMA_SERVER_URL", ""),
            "cloud_runtime_url": os.environ.get("NIBLIT_CLOUD_RUNTIME_URL", ""),
            "host": os.environ.get("HOSTNAME", ""),
        }


class CommandRuntime:
    """Central runtime-native command dispatcher."""

    def __init__(self, event_bus: RuntimeEventBus, provider_runtime: ProviderRuntimeManager) -> None:
        self._event_bus = event_bus
        self._provider_runtime = provider_runtime

    def dispatch(self, *, command: str, core: Any, state: RuntimeState) -> str:
        text = command.strip()
        if not text:
            return ""
        state.command_history.append(text)
        if len(state.command_history) > MAX_COMMAND_HISTORY:
            state.command_history = state.command_history[-MAX_COMMAND_HISTORY:]
        self._event_bus.emit("command.executed", "CommandRuntime", {"command": text})

        lower = text.lower()
        if lower.startswith(CMD_PREFIX_RUNTIME_PROVIDER):
            target = text[len(CMD_PREFIX_RUNTIME_PROVIDER) :].strip().lower()
            result = self._provider_runtime.set_active(target)
            state.active_provider = self._provider_runtime.status().get("active_provider", state.active_provider)
            return result
        if lower == "runtime status":
            return json.dumps(
                {
                    "runtime_mode": state.runtime_mode,
                    "active_provider": state.active_provider,
                    "deployment": state.deployment,
                    "commands": len(state.command_history),
                },
                indent=2,
                sort_keys=True,
            )
        if lower.startswith(CMD_PREFIX_RUNTIME_INFER):
            prompt = text[len(CMD_PREFIX_RUNTIME_INFER) :].strip()
            result = self._provider_runtime.generate(prompt=prompt, task_type="general", local_first=True)
            return result.get("text") or f"[runtime error] {result.get('error', 'inference failed')}"

        if core is None:
            return "[error] core unavailable"
        return str(core.handle(text))


class NiblitUnifiedRuntime:
    """One unified cognitive operating runtime for UI/API integration."""

    def __init__(self, state_file: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.runtime_id = f"unified-{uuid.uuid4().hex[:12]}"
        self._event_bus = RuntimeEventBus()
        self._module_bus_bridge_installed = False
        self.provider_runtime = ProviderRuntimeManager(self._event_bus)
        self.telemetry_runtime = RuntimeTelemetryManager()
        self.deployment_runtime = DeploymentRuntimeManager()
        self.command_runtime = CommandRuntime(self._event_bus, self.provider_runtime)
        self.cognitive_runtime = CognitiveEpisodeManager(runtime_id=self.runtime_id)
        self._state_file = state_file or Path(
            os.environ.get("NIBLIT_UNIFIED_RUNTIME_STATE", os.path.join(os.getcwd(), "niblit_unified_runtime_state.json"))
        )
        self._state = RuntimeState()
        self._load_state()
        self._event_bus.subscribe(self._observe_runtime_event)
        self._bridge_module_event_bus()
        self._event_bus.emit(
            "boot.sequence",
            "NiblitUnifiedRuntime",
            {"state_file": str(self._state_file), "runtime_id": self.runtime_id, "trace_id": f"{self.runtime_id}:boot"},
        )

    def _load_state(self) -> None:
        try:
            if self._state_file.exists():
                raw = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._state = RuntimeState.from_dict(raw)
        except Exception as exc:
            log.debug("Failed loading unified runtime state: %s", exc)

    def _save_state(self) -> None:
        try:
            self._state.last_updated_at = _utc_ts()
            self._state_file.write_text(json.dumps(self._state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            log.debug("Failed saving unified runtime state: %s", exc)

    def _update_from_status(self, *, core: Any) -> dict[str, Any]:
        with self._lock:
            provider_status = self.provider_runtime.status()
            self._state.active_provider = provider_status.get("active_provider", self._state.active_provider)
            self._state.deployment = self.deployment_runtime.detect()
            self._state.runtime_mode = self._state.deployment.get("runtime_mode", self._state.runtime_mode)
            cognitive_status = self.cognitive_runtime.status()
            self._state.cognitive_episodes = list(cognitive_status.get("episodes", []))
            self._state.cognitive_reflections = list(cognitive_status.get("reflections", []))
            self._state.cognitive_compression = dict(cognitive_status.get("compression", {}))
            self._state.cognitive_datasets = dict(cognitive_status.get("datasets", {}))
            self._state.confidence_summary = dict(cognitive_status.get("confidence_summary", {}))
            ms = provider_status.get("manager_status", {})
            loaded_models = [
                str(ms.get("qwen_model", "")),
                str(ms.get("hf_model", "")),
                str(ms.get("anthropic_model", "")),
                str(ms.get("ruflo_model", "")),
            ]
            self._state.loaded_models = [m for m in loaded_models if m and m != "n/a"]
            telemetry = self.telemetry_runtime.snapshot(
                core=core,
                state=self._state,
                provider_status=provider_status,
                event_stats=self._event_bus.stats(),
                cognitive_status=cognitive_status,
            )
            self._state.telemetry_snapshots.append(dict(telemetry))
            if len(self._state.telemetry_snapshots) > MAX_TELEMETRY_HISTORY:
                self._state.telemetry_snapshots = self._state.telemetry_snapshots[-MAX_TELEMETRY_HISTORY:]
            self._event_bus.emit("telemetry.update", "RuntimeTelemetryManager", telemetry)
            self._save_state()
            return {
                "state": self._state.to_dict(),
                "providers": provider_status,
                "telemetry": telemetry,
                "events": self._event_bus.stats(),
                "cognition": cognitive_status,
            }

    def boot(self, core: Any | None = None) -> dict[str, Any]:
        out = self._update_from_status(core=core)
        self._event_bus.emit(
            "runtime.ready",
            "NiblitUnifiedRuntime",
            {
                "active_provider": out["state"]["active_provider"],
                "runtime_id": self.runtime_id,
                "trace_id": f"{self.runtime_id}:ready",
                "runtime_mode": out["state"]["runtime_mode"],
            },
        )
        return out

    def _observe_runtime_event(self, event: RuntimeEvent) -> None:
        try:
            event_dict = event.to_dict()
            payload = dict(event_dict.get("payload", {}) or {})
            payload.setdefault("runtime_id", self.runtime_id)
            if not payload.get("trace_id"):
                payload["trace_id"] = f"{self.runtime_id}:{event.type}:{event.id}"
            payload.setdefault("runtime_mode", self._state.runtime_mode)
            event_dict["payload"] = payload
            episode = self.cognitive_runtime.observe_event(event_dict, runtime_mode=self._state.runtime_mode)
            if episode:
                with self._lock:
                    self._state.cognitive_sessions.append(
                        {
                            "episode_id": episode.get("episode_id"),
                            "topic": episode.get("topic"),
                            "confidence_score": episode.get("confidence_score"),
                            "timestamp": episode.get("timestamp_lineage", {}).get("closed_at"),
                        }
                    )
                    self._state.cognitive_sessions = self._state.cognitive_sessions[-60:]
        except Exception as exc:
            log.debug("Failed observing runtime event: %s", exc)

    def _bridge_module_event_bus(self) -> None:
        if self._module_bus_bridge_installed:
            return
        try:
            from modules.event_bus import get_event_bus

            def _handle(event: Any) -> None:
                payload = dict(getattr(event, "payload", {}) or {})
                if payload.get("_runtime_unified_seen"):
                    return
                payload["_runtime_unified_seen"] = True
                payload.setdefault("runtime_id", self.runtime_id)
                payload.setdefault("runtime_mode", self._state.runtime_mode)
                payload.setdefault(
                    "trace_id",
                    payload.get("trace_id") or f"{self.runtime_id}:{getattr(event, 'type', 'event')}:{int(time.time() * 1000)}",
                )
                self._event_bus.emit(str(getattr(event, "type", "event")), str(getattr(event, "source", "modules")), payload)

            get_event_bus().subscribe_all(_handle)
            self._module_bus_bridge_installed = True
        except Exception as exc:
            log.debug("Failed installing module event bus bridge: %s", exc)

    def dispatch_command(self, *, command: str, core: Any | None) -> str:
        with self._lock:
            out = self.command_runtime.dispatch(command=command, core=core, state=self._state)
            self._save_state()
            return out

    def state(self, *, core: Any | None = None) -> dict[str, Any]:
        return self._update_from_status(core=core)

    def events(self, *, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        return self._event_bus.events(since=since, limit=limit)

    def episodes(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.cognitive_runtime.episodes(limit=limit)

    def reflections(self) -> list[dict[str, Any]]:
        return self.cognitive_runtime.status().get("reflections", [])

    def ingest_external_event(self, *, event_type: str, source: str, payload: dict[str, Any] | None = None) -> None:
        enriched = dict(payload or {})
        enriched.setdefault("runtime_id", self.runtime_id)
        enriched.setdefault("runtime_mode", self._state.runtime_mode)
        enriched.setdefault("trace_id", enriched.get("trace_id") or f"{self.runtime_id}:{event_type}:{int(time.time() * 1000)}")
        self._event_bus.emit(event_type, source, enriched)

    def stream_frame(self, *, core: Any | None = None, since: int = 0) -> dict[str, Any]:
        status = self._update_from_status(core=core)
        return {
            "stream_format": "niblit.runtime.stream.v1",
            "type": "runtime.frame",
            "timestamp": _iso_now(),
            "state": status["state"],
            "telemetry": status["telemetry"],
            "events": self._event_bus.events(since=since, limit=200),
            "provider": status["providers"],
            "episodes": status["cognition"].get("episodes", []),
            "reflections": status["cognition"].get("reflections", []),
            "dataset": status["cognition"].get("datasets", {}),
            "compression": status["cognition"].get("compression", {}),
            "confidence": status["cognition"].get("confidence_summary", {}),
        }


_unified_runtime: NiblitUnifiedRuntime | None = None
_unified_runtime_lock = threading.Lock()


def get_unified_runtime() -> NiblitUnifiedRuntime:
    global _unified_runtime  # pylint: disable=global-statement
    if _unified_runtime is None:
        with _unified_runtime_lock:
            if _unified_runtime is None:
                _unified_runtime = NiblitUnifiedRuntime()
    return _unified_runtime
