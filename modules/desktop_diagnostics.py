"""Read-only desktop views of the governing Core and its real service layers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.request import urlopen


def service_snapshot(service, path="/health"):
    if service == "cloud":
        root = os.getenv("NIBLIT_CLOUD_SERVER_URL") or f"http://127.0.0.1:{os.getenv('NIBLIT_CLOUD_SERVER_PRIMARY_PORT', '8000')}"
    elif service == "trading":
        root = f"http://127.0.0.1:{int(os.getenv('NIBLIT_TRADING_API_PORT', '8100'))}"
    else:
        raise ValueError("Unknown service")
    try:
        with urlopen(root.rstrip("/") + path, timeout=1) as response:
            return {"available": True, "data": json.load(response)}
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__}


def _call(owner, method, default=None, **kwargs):
    callback = getattr(owner, method, None)
    if not callable(callback):
        return default
    try:
        return callback(**kwargs)
    except Exception as exc:
        return {"unavailable": True, "error": type(exc).__name__}


def desktop_snapshot(core, section, *, query="", limit=20, unified_runtime=None):
    if section not in {"overview", "architecture", "cognitive", "memory", "conversation", "inference", "execution", "trading", "settings"}:
        raise ValueError("Unknown desktop section")
    limit = max(1, min(int(limit), 100))
    manager = getattr(core, "runtime_manager", None)
    database = getattr(core, "db", None)
    result = {"section": section, "checked_at": datetime.now(timezone.utc).isoformat(), "core_available": core is not None}
    if core is None:
        return {**result, "available": False, "error": "Core has not initialized"}
    if section == "conversation":
        from modules.llm_chat_memory import get_llm_chat_memory
        return {**result, "messages": get_llm_chat_memory().load_messages(limit=40)}
    if section in {"overview", "architecture", "cognitive"}:
        result["core"] = _call(manager, "get_runtime_health", {"status": "unavailable"})
        result["readiness"] = _call(core, "readiness_status", {})
        result["startup_stages"] = getattr(core, "_staged_bootstrap_report", {})
    if section in {"overview", "memory"}:
        data = getattr(database, "data", {})
        lock = getattr(database, "lock", None)
        if lock is not None:
            with lock:
                counts = {key: len(data.get(key, [])) for key in ("facts", "interactions", "learning_log", "events")}
        else:
            counts = {key: None for key in ("facts", "interactions", "learning_log", "events")}
        result["memory"] = {"backend": type(database).__name__ if database else "unavailable", "counts": counts}
        if section == "memory":
            result["records"] = (_call(database, "recall", [], query=query[:300], limit=limit)
                                 if query.strip() else _call(database, "list_facts", [], limit=limit))
            from modules.llm_chat_memory import get_llm_chat_memory
            result["conversation"] = get_llm_chat_memory().status()
    if section in {"overview", "architecture", "inference"}:
        result["cloud"] = service_snapshot("cloud")
        if section == "inference":
            result["models"] = service_snapshot("cloud", "/v1/models")
            result["model_runtime"] = service_snapshot("cloud", "/v1/runtime/status")
    if section in {"overview", "architecture", "trading"}:
        result["trading"] = service_snapshot("trading")
        if section == "trading":
            result["portfolio"] = service_snapshot("trading", "/v1/runtime/snapshot")
            result["runtime"] = service_snapshot("trading", "/v1/runtime/status")
    if section in {"architecture", "execution"}:
        from modules.multi_repo_orchestrator import get_multi_repo_orchestrator
        orchestrator = get_multi_repo_orchestrator()
        result["repositories"] = orchestrator.get_runtime_status()
        result["processes"] = orchestrator.get_supervision_status()
        result["services"] = _call(manager, "get_runtime_services", {})
        result["threads"] = _call(manager, "get_runtime_threads", {})
        if section == "execution":
            result["events"] = _call(manager, "get_runtime_events", [], limit=limit)
        else:
            checks = {
                "governing_core_bound": core is not None,
                "memory_is_persistent": database is not None and type(database).__name__ != "_FallbackDB",
                "runtime_manager_present": manager is not None,
                "core_bus_identity": manager is not None and getattr(core, "event_bus", None) is getattr(manager, "event_bus", None),
                "module_event_bridge": bool(getattr(manager, "_module_bus_attached", False)),
                "ui_event_bridge": bool(getattr(unified_runtime, "_module_bus_bridge_installed", False)),
                "cloud_reachable": result["cloud"]["available"],
                "lean_ready": result["trading"]["available"] and result["trading"].get("data", {}).get("healthy") is True,
            }
            result["wiring_checks"] = checks
            result["all_checked_connections_ready"] = all(checks.values())
            result["service_transport"] = "Core-owned HTTP boundaries; in-process event buses use explicit bridges"
    if section == "settings":
        result["runtime_configuration"] = {
            "provider": os.getenv("NIBLIT_LLM_PROVIDER", "default"),
            "workspace_root": os.getenv("NIBLIT_WORKSPACE_ROOT", os.getcwd()),
            "memory_path": str(getattr(database, "path", "unavailable")),
            "core_port": int(os.getenv("NIBLIT_API_PORT", "5000")),
            "cloud_port": int(os.getenv("NIBLIT_CLOUD_SERVER_PRIMARY_PORT", "8000")),
            "trading_port": int(os.getenv("NIBLIT_TRADING_API_PORT", "8100")),
            "trading_mode": os.getenv("NIBLIT_TRADING_MODE", "observe"),
        }
    return result
