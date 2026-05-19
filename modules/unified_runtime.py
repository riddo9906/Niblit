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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("Niblit.UnifiedRuntime")

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

    def subscribe(self, handler: Any) -> None:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def emit(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> RuntimeEvent:
        with self._lock:
            self._seq += 1
            event = RuntimeEvent(
                id=self._seq,
                type=event_type,
                source=source,
                payload=dict(payload or {}),
            )
            self._events.append(event)
            if len(self._events) > MAX_EVENT_BUFFER:
                self._events = self._events[-MAX_EVENT_BUFFER:]
            self._counts[event_type] = self._counts.get(event_type, 0) + 1
            handlers = list(self._handlers)

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                log.debug("RuntimeEventBus handler error: %s", exc)
        return event

    def events(self, *, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            filtered = [e.to_dict() for e in self._events if e.id > since]
        return filtered[: max(1, min(limit, 500))]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"event_counts": dict(self._counts), "last_event_id": self._seq}


class ProviderRuntimeManager:
    """Provider-agnostic runtime manager with normalized outputs."""

    _DEFAULT_CAPS: dict[str, dict[str, Any]] = {
        "qwen": {
            "local": True,
            "streaming": False,
            "reasoning": "medium",
            "cost_tier": "low",
            "max_context": 8192,
            "provider_type": "local",
        },
        "local_llama": {
            "local": True,
            "streaming": False,
            "reasoning": "medium",
            "cost_tier": "low",
            "max_context": 8192,
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
        max_tokens: int = 500,
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
                    if "max_tokens" in sig.parameters:
                        text = rr.generate(prompt=prompt, context=context, max_tokens=max_tokens)
                    else:
                        text = rr.generate(prompt=prompt, context=context)
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

    def snapshot(self, *, core: Any, state: RuntimeState, provider_status: dict[str, Any], event_stats: dict[str, Any]) -> dict[str, Any]:
        import threading as _threading

        facts_count = None
        if core is not None:
            try:
                facts_count = len(core.db.list_facts(limit=500))
            except Exception:
                facts_count = None

        ale_data: dict[str, Any] | None = None
        if core is not None:
            ale = getattr(core, "autonomous_engine", None)
            if ale is not None:
                ale_data = {
                    "running": bool(getattr(ale, "running", False)),
                    "cycle": int(getattr(ale, "_cycle_count", 0)),
                    "topic": ale.get_current_topic() if hasattr(ale, "get_current_topic") else None,
                }

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
            "provider_health": provider_status.get("health", {}),
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
        self._event_bus = RuntimeEventBus()
        self.provider_runtime = ProviderRuntimeManager(self._event_bus)
        self.telemetry_runtime = RuntimeTelemetryManager()
        self.deployment_runtime = DeploymentRuntimeManager()
        self.command_runtime = CommandRuntime(self._event_bus, self.provider_runtime)
        self._state_file = state_file or Path(
            os.environ.get("NIBLIT_UNIFIED_RUNTIME_STATE", os.path.join(os.getcwd(), "niblit_unified_runtime_state.json"))
        )
        self._state = RuntimeState()
        self._load_state()
        self._event_bus.emit("boot.sequence", "NiblitUnifiedRuntime", {"state_file": str(self._state_file)})

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
            }

    def boot(self, core: Any | None = None) -> dict[str, Any]:
        out = self._update_from_status(core=core)
        self._event_bus.emit("runtime.ready", "NiblitUnifiedRuntime", {"active_provider": out["state"]["active_provider"]})
        return out

    def dispatch_command(self, *, command: str, core: Any | None) -> str:
        with self._lock:
            out = self.command_runtime.dispatch(command=command, core=core, state=self._state)
            self._save_state()
            return out

    def state(self, *, core: Any | None = None) -> dict[str, Any]:
        return self._update_from_status(core=core)

    def events(self, *, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        return self._event_bus.events(since=since, limit=limit)

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
