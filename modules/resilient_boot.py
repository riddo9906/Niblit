#!/usr/bin/env python3
"""Resilient boot helpers for Niblit main.py — environment, deps, and status."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional

from modules.platform_compat import platform_mode

log = logging.getLogger("ResilientBoot")

_OPTIONAL_PACKAGES = (
    "requests",
    "dotenv",
    "httpx",
    "aiohttp",
    "duckduckgo_search",
)


@dataclass
class BootStatus:
    """Structured boot-time state for the final status report."""

    environment_loaded: bool = False
    env_sources: List[str] = field(default_factory=list)
    platform_mode: str = "fallback"
    event_bus_status: str = "unknown"
    sidecar_status: str = "disabled"  # active | degraded | disabled
    optional_missing: List[str] = field(default_factory=list)
    runtime_mode: str = "full"  # full | degraded
    warnings: List[str] = field(default_factory=list)
    core_init_error: Optional[str] = None

    def mark_degraded(self, reason: str) -> None:
        self.runtime_mode = "degraded"
        if reason and reason not in self.warnings:
            self.warnings.append(reason)


def load_environment(project_root: str, status: Optional[BootStatus] = None) -> bool:
    """Load ``.env`` from project root and cwd before subsystem imports.

    Never raises.  Returns True when at least one ``.env`` file was loaded.
    """
    if status is None:
        status = BootStatus()

    status.platform_mode = platform_mode()
    loaded_any = False
    candidates = [
        os.path.join(project_root, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]

    dotenv_spec = importlib.util.find_spec("dotenv")
    if dotenv_spec is None:
        msg = "Niblit running without local .env file — using system environment"
        log.warning(msg)
        if status is not None:
            status.warnings.append(msg)
        status.environment_loaded = bool(os.environ)
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:
        msg = "Niblit running without local .env file — using system environment"
        log.warning(msg)
        status.warnings.append(msg)
        status.environment_loaded = bool(os.environ)
        return False

    seen: set[str] = set()
    for path in candidates:
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if not os.path.isfile(norm):
            continue
        try:
            if load_dotenv(norm, override=False):
                loaded_any = True
                status.env_sources.append(norm)
        except OSError as exc:
            log.warning("Failed loading .env from %s: %s", norm, exc)
            status.warnings.append(f".env load failed: {norm}")

    status.environment_loaded = loaded_any or bool(os.environ)
    if not loaded_any:
        msg = "Niblit running without local .env file — using system environment"
        log.warning(msg)
        status.warnings.append(msg)
    return loaded_any


def scan_optional_dependencies(status: Optional[BootStatus] = None) -> List[str]:
    """Return package names that are not importable; log degraded-mode warnings."""
    if status is None:
        status = BootStatus()

    missing: List[str] = []
    for package in _OPTIONAL_PACKAGES:
        spec = importlib.util.find_spec(package)
        if spec is None:
            missing.append(package)
            log.warning(
                "Optional dependency missing: %s — module running in degraded mode",
                package,
            )
    status.optional_missing = list(missing)
    if missing:
        status.mark_degraded(f"{len(missing)} optional package(s) missing")
    return missing


def probe_event_bus_health(status: Optional[BootStatus] = None) -> str:
    """Exercise the core EventBus with enum and string event types."""
    if status is None:
        status = BootStatus()

    try:
        from core.event_bus import Event, EventBus, EventType

        bus = EventBus()
        received: list[str] = []

        def _handler(event: Event) -> None:
            received.append(event.type_name)

        bus.subscribe(EventType.SYSTEM_STARTED, _handler)
        bus.subscribe("runtime.probe", _handler)
        bus.publish(Event(type=EventType.SYSTEM_STARTED, source="boot_probe"))
        bus.publish(Event(type="runtime.probe", source="boot_probe", payload={}))

        if len(received) == 2:
            status.event_bus_status = "healthy"
        else:
            status.event_bus_status = "warning"
            status.warnings.append("EventBus probe delivered fewer handlers than expected")
    except Exception as exc:
        status.event_bus_status = "warning"
        status.warnings.append(f"EventBus probe failed: {exc}")
        log.warning("[Boot] EventBus health probe failed: %s", exc)

    return status.event_bus_status


def print_boot_status_report(io: Any, status: BootStatus) -> None:
    """Print the structured post-boot summary."""
    lines = [
        "",
        "──────── Niblit Boot Status ────────",
        f"  environment loaded : {str(status.environment_loaded).lower()}",
    ]
    if status.env_sources:
        lines.append(f"  env sources        : {', '.join(status.env_sources)}")
    lines.append(f"  platform mode      : {status.platform_mode}")
    lines.append(f"  event bus status   : {status.event_bus_status}")
    lines.append(f"  sidecar status     : {status.sidecar_status}")
    if status.optional_missing:
        lines.append(f"  optional deps      : missing {', '.join(status.optional_missing)}")
    else:
        lines.append("  optional deps      : all checked packages present")
    lines.append(f"  runtime mode       : {status.runtime_mode}")
    if status.core_init_error:
        lines.append(f"  core init note     : {status.core_init_error}")
    if status.warnings:
        lines.append("  warnings:")
        for warning in status.warnings[:8]:
            lines.append(f"    - {warning}")
        if len(status.warnings) > 8:
            lines.append(f"    … and {len(status.warnings) - 8} more")
    lines.append("────────────────────────────────────")
    output = "\n".join(lines)
    if io is not None and hasattr(io, "out"):
        io.out(output)
    else:
        print(output, flush=True)
