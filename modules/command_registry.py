#!/usr/bin/env python3
"""Canonical runtime capability registry for Niblit."""

from __future__ import annotations

import difflib
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("CommandRegistry")

AvailabilityEvaluator = Callable[[dict[str, Any]], bool | tuple[bool, str]]
EventEmitter = Callable[[str, dict[str, Any]], None]

DEFAULT_SURFACES = frozenset({"cli", "api", "desktop", "runtime", "help", "discoverability"})


@dataclass
class CommandMetadata:
    """Metadata about a registered runtime capability."""

    prefix: str
    handler: Callable | None
    description: str
    category: str
    priority: int
    aliases: tuple[str, ...] = ()
    runtime_modes: tuple[str, ...] = ()
    provider_requirements: tuple[str, ...] = ()
    governance_requirements: tuple[str, ...] = ()
    cognition_classification: str = "operational"
    execution_authority: str = "registry"
    source_authority: str = "unknown"
    visibility_surfaces: frozenset[str] = DEFAULT_SURFACES
    desktop_visible: bool = True
    cloud_available: bool | None = None
    deprecated: bool = False
    deprecation_message: str = ""
    dynamic_availability: AvailabilityEvaluator | None = None
    runtime_availability: str = "dynamic"
    adaptive_hints: tuple[str, ...] = ()
    ui_metadata: dict[str, Any] = field(default_factory=dict)

    def all_names(self) -> tuple[str, ...]:
        return (self.prefix, *self.aliases)

    def primary_name(self) -> str:
        return self.prefix

    def to_dict(self, *, available: bool = True, reason: str = "") -> dict[str, Any]:
        return {
            "name": self.prefix,
            "aliases": list(self.aliases),
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "runtime_modes": list(self.runtime_modes),
            "provider_requirements": list(self.provider_requirements),
            "governance_requirements": list(self.governance_requirements),
            "cognition_classification": self.cognition_classification,
            "execution_authority": self.execution_authority,
            "source_authority": self.source_authority,
            "visibility_surfaces": sorted(self.visibility_surfaces),
            "desktop_visible": self.desktop_visible,
            "cloud_available": self.cloud_available,
            "deprecated": self.deprecated,
            "deprecation_message": self.deprecation_message,
            "runtime_availability": self.runtime_availability,
            "adaptive_hints": list(self.adaptive_hints),
            "ui_metadata": dict(self.ui_metadata),
            "available": available,
            "availability_reason": reason,
            "executable": callable(self.handler),
        }


class CanonicalRuntimeCapabilityRegistry:
    """Single source of truth for command execution + discoverability."""

    def __init__(
        self,
        *,
        event_emitter: EventEmitter | None = None,
        context_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.commands: dict[str, CommandMetadata] = {}
        self.stats = {
            "total_executed": 0,
            "total_failed": 0,
            "by_category": {},
        }
        self._event_emitter = event_emitter
        self._context_provider = context_provider
        self._availability_cache: dict[tuple[str, str], bool] = {}
        log.debug("CanonicalRuntimeCapabilityRegistry initialized")

    def set_event_emitter(self, emitter: EventEmitter | None) -> None:
        self._event_emitter = emitter

    def set_context_provider(self, provider: Callable[[], dict[str, Any]] | None) -> None:
        self._context_provider = provider

    def register(
        self,
        prefix: str,
        handler: Callable | None,
        description: str = "",
        category: str = "core",
        priority: int = 0,
        *,
        aliases: list[str] | tuple[str, ...] | None = None,
        runtime_modes: list[str] | tuple[str, ...] | None = None,
        provider_requirements: list[str] | tuple[str, ...] | None = None,
        governance_requirements: list[str] | tuple[str, ...] | None = None,
        cognition_classification: str = "operational",
        execution_authority: str | None = None,
        source_authority: str = "unknown",
        visibility_surfaces: list[str] | tuple[str, ...] | set[str] | None = None,
        desktop_visible: bool = True,
        cloud_available: bool | None = None,
        deprecated: bool = False,
        deprecation_message: str = "",
        dynamic_availability: AvailabilityEvaluator | None = None,
        runtime_availability: str = "dynamic",
        adaptive_hints: list[str] | tuple[str, ...] | None = None,
        ui_metadata: dict[str, Any] | None = None,
    ) -> None:
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return
        metadata = CommandMetadata(
            prefix=prefix,
            handler=handler,
            description=(description or "").strip() or "No description",
            category=(category or "core").strip().lower(),
            priority=int(priority),
            aliases=tuple(self._normalize_many(aliases)),
            runtime_modes=tuple(self._normalize_many(runtime_modes)),
            provider_requirements=tuple(self._normalize_many(provider_requirements)),
            governance_requirements=tuple(self._normalize_many(governance_requirements)),
            cognition_classification=(cognition_classification or "operational").strip().lower(),
            execution_authority=execution_authority or (
                getattr(handler, "__qualname__", "external") if callable(handler) else "external"
            ),
            source_authority=(
                source_authority
                if source_authority != "unknown"
                else f"{getattr(handler, '__module__', 'unknown')}.py"
            ),
            visibility_surfaces=frozenset(self._normalize_many(visibility_surfaces) or DEFAULT_SURFACES),
            desktop_visible=bool(desktop_visible),
            cloud_available=cloud_available,
            deprecated=bool(deprecated),
            deprecation_message=deprecation_message.strip(),
            dynamic_availability=dynamic_availability,
            runtime_availability=(runtime_availability or "dynamic").strip().lower(),
            adaptive_hints=tuple(str(v).strip() for v in (adaptive_hints or ()) if str(v).strip()),
            ui_metadata=dict(ui_metadata or {}),
        )
        self.commands[prefix] = metadata
        self._emit(
            "command.registered",
            {
                "command": prefix,
                "aliases": list(metadata.aliases),
                "category": metadata.category,
                "source_authority": metadata.source_authority,
                "execution_authority": metadata.execution_authority,
            },
        )
        if metadata.deprecated:
            self._emit(
                "command.deprecated",
                {
                    "command": prefix,
                    "message": metadata.deprecation_message,
                    "source_authority": metadata.source_authority,
                },
            )
        log.info("Registered capability: %s (priority=%s, category=%s)", prefix, priority, category)

    def can_handle(self, text: str, *, context: dict[str, Any] | None = None, surface: str = "cli") -> bool:
        resolved = self.resolve(text, context=context, surface=surface, include_unavailable=False, executable_only=True)
        return resolved is not None

    def resolve(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "cli",
        include_unavailable: bool = True,
        executable_only: bool = False,
    ) -> tuple[CommandMetadata, str] | None:
        ltext = (text or "").lower().strip()
        if not ltext:
            return None
        effective_context = self._effective_context(context, surface=surface)
        matches: list[tuple[int, int, CommandMetadata, str]] = []
        for metadata in self.commands.values():
            if executable_only and not callable(metadata.handler):
                continue
            for name in metadata.all_names():
                if ltext == name or ltext.startswith(name + " "):
                    availability = self._availability(metadata, effective_context, surface=surface)
                    if not include_unavailable and not availability["available"]:
                        continue
                    matches.append((metadata.priority, len(name), metadata, name))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        metadata, matched_name = matches[0][2], matches[0][3]
        return metadata, matched_name

    def execute(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "cli",
    ) -> str | None:
        resolved = self.resolve(text, context=context, surface=surface, include_unavailable=True, executable_only=False)
        if resolved is None:
            return None
        metadata, matched_name = resolved
        availability = self._availability(metadata, self._effective_context(context, surface=surface), surface=surface)
        if not availability["available"]:
            reason = availability["reason"] or "Capability unavailable in the current runtime."
            return f"[UNAVAILABLE] {metadata.prefix} — {reason}"
        if not callable(metadata.handler):
            return None
        try:
            remaining = (text or "")[len(matched_name):].strip()
            result = metadata.handler(remaining)
            self.stats["total_executed"] += 1
            self.stats["by_category"][metadata.category] = self.stats["by_category"].get(metadata.category, 0) + 1
            return result
        except Exception as exc:
            log.error("Command execution failed: %s", exc, exc_info=True)
            self.stats["total_executed"] += 1
            self.stats["total_failed"] += 1
            self.stats["by_category"][metadata.category] = self.stats["by_category"].get(metadata.category, 0) + 1
            return f"[ERROR] Command failed: {exc}"

    def get_help(
        self,
        category: str | None = None,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "help",
        include_unavailable: bool = True,
    ) -> str:
        lines = ["=== NIBLIT CAPABILITY REFERENCE ===", ""]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self.capability_snapshot(
            context=context,
            surface=surface,
            include_unavailable=include_unavailable,
        ):
            if category and item["category"] != category:
                continue
            grouped[item["category"]].append(item)
        for cat in sorted(grouped.keys()):
            lines.append(f"--- {cat.replace('_', ' ').upper()} ---")
            for item in sorted(grouped[cat], key=lambda entry: (-int(entry["priority"]), entry["name"])):
                suffix = ""
                if item["deprecated"]:
                    suffix += " [deprecated]"
                if not item["available"]:
                    suffix += f" [unavailable: {item['availability_reason'] or 'runtime gated'}]"
                alias_suffix = f" (aliases: {', '.join(item['aliases'])})" if item["aliases"] else ""
                lines.append(f"{item['name']:<28} — {item['description']}{alias_suffix}{suffix}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def get_stats(self) -> dict[str, Any]:
        executed = self.stats["total_executed"]
        failed = self.stats["total_failed"]
        success_rate = 1.0 if executed == 0 else (executed - failed) / executed
        return {
            **self.stats,
            "registered_commands": len(self.commands),
            "success_rate": success_rate,
        }

    def list_commands(
        self,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "discoverability",
        include_unavailable: bool = True,
    ) -> list[CommandMetadata]:
        allowed: list[CommandMetadata] = []
        effective_context = self._effective_context(context, surface=surface)
        for metadata in self.commands.values():
            availability = self._availability(metadata, effective_context, surface=surface)
            if include_unavailable or availability["available"]:
                allowed.append(metadata)
        return sorted(allowed, key=lambda metadata: (-metadata.priority, metadata.prefix))

    def detailed_report(
        self,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "discoverability",
        include_unavailable: bool = True,
    ) -> str:
        lines = ["📋 **Canonical Runtime Capabilities**\n"]
        for item in self.capability_snapshot(context=context, surface=surface, include_unavailable=include_unavailable):
            status = "available" if item["available"] else f"unavailable:{item['availability_reason'] or 'runtime gated'}"
            aliases = f" aliases={item['aliases']}" if item["aliases"] else ""
            lines.append(
                f"  • {item['name']:<32} — {item['description']} "
                f"[cat={item['category']}, priority={item['priority']}, "
                f"source={item['source_authority']}, exec={item['execution_authority']}, "
                f"status={status}{aliases}]"
            )
        return "\n".join(lines)

    def capability_snapshot(
        self,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "discoverability",
        include_unavailable: bool = True,
    ) -> list[dict[str, Any]]:
        effective_context = self._effective_context(context, surface=surface)
        snapshot: list[dict[str, Any]] = []
        for metadata in self.list_commands(
            context=effective_context,
            surface=surface,
            include_unavailable=include_unavailable,
        ):
            availability = self._availability(metadata, effective_context, surface=surface)
            if include_unavailable or availability["available"]:
                snapshot.append(metadata.to_dict(available=availability["available"], reason=availability["reason"]))
        return snapshot

    def command_names(
        self,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "discoverability",
        include_aliases: bool = True,
        include_unavailable: bool = False,
    ) -> list[str]:
        names: list[str] = []
        for metadata in self.list_commands(context=context, surface=surface, include_unavailable=include_unavailable):
            names.append(metadata.prefix)
            if include_aliases:
                names.extend(metadata.aliases)
        return sorted({name for name in names if name})

    def suggestions(
        self,
        user_input: str,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "discoverability",
        include_unavailable: bool = False,
    ) -> list[str]:
        names = self.command_names(
            context=context,
            surface=surface,
            include_aliases=True,
            include_unavailable=include_unavailable,
        )
        matches = difflib.get_close_matches((user_input or "").strip().lower(), names, n=3, cutoff=0.5)
        return [match for match in matches if match != (user_input or "").strip().lower()]

    def grouped_catalog(
        self,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "desktop",
        include_unavailable: bool = False,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self.capability_snapshot(context=context, surface=surface, include_unavailable=include_unavailable):
            grouped[item["category"]].append(item)
        return [
            {
                "category": category,
                "capabilities": sorted(entries, key=lambda entry: (-int(entry["priority"]), entry["name"])),
            }
            for category, entries in sorted(grouped.items())
        ]

    def ui_catalog(
        self,
        *,
        context: dict[str, Any] | None = None,
        surface: str = "desktop",
        include_unavailable: bool = False,
    ) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for group in self.grouped_catalog(context=context, surface=surface, include_unavailable=include_unavailable):
            commands = []
            for item in group["capabilities"]:
                ui_metadata = dict(item.get("ui_metadata", {}))
                commands.append(
                    {
                        "label": ui_metadata.get("label", item["name"]),
                        "cmd": ui_metadata.get("cmd", item["name"]),
                        "desc": item["description"],
                        "category": item["category"],
                        "available": item["available"],
                        "availability_reason": item["availability_reason"],
                        "aliases": item["aliases"],
                        "has_input": bool(ui_metadata.get("has_input", False)),
                    }
                )
            catalog.append({"group": group["category"], "commands": commands})
        return catalog

    def _availability(self, metadata: CommandMetadata, context: dict[str, Any], *, surface: str) -> dict[str, Any]:
        visible = surface in metadata.visibility_surfaces
        if surface == "desktop" and not metadata.desktop_visible:
            visible = False
        reason = "" if visible else f"not visible on surface '{surface}'"
        available = visible
        if available and metadata.runtime_modes:
            runtime_mode = str(context.get("runtime_mode", "") or "").lower()
            if runtime_mode and runtime_mode not in metadata.runtime_modes:
                available = False
                reason = f"mode={runtime_mode}"
        if available and metadata.provider_requirements:
            active_provider = str(context.get("active_provider", "") or "").lower()
            provider_health = context.get("provider_health", {}) or {}
            if active_provider and active_provider not in metadata.provider_requirements:
                available = False
                reason = f"provider={active_provider}"
            for provider in metadata.provider_requirements:
                if provider_health and not provider_health.get(provider, {}).get("healthy", True):
                    available = False
                    reason = f"provider {provider} unavailable"
                    break
        if available and metadata.dynamic_availability is not None:
            try:
                evaluated = metadata.dynamic_availability(context)
                if isinstance(evaluated, tuple):
                    available = bool(evaluated[0])
                    reason = str(evaluated[1] or "")
                else:
                    available = bool(evaluated)
                    if not available and not reason:
                        reason = "runtime gated"
            except Exception as exc:
                available = False
                reason = f"availability error: {exc}"
        cache_key = (metadata.prefix, surface)
        previous = self._availability_cache.get(cache_key)
        if previous is None or previous != available:
            self._availability_cache[cache_key] = available
            self._emit(
                "capability.available" if available else "capability.unavailable",
                {
                    "command": metadata.prefix,
                    "surface": surface,
                    "category": metadata.category,
                    "reason": reason,
                    "source_authority": metadata.source_authority,
                },
            )
        return {"available": available, "reason": reason}

    def _effective_context(self, context: dict[str, Any] | None, *, surface: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if self._context_provider is not None:
            try:
                merged.update(self._context_provider() or {})
            except Exception as exc:
                log.debug("Command registry context provider failed: %s", exc)
        if context:
            merged.update(context)
        merged.setdefault("surface", surface)
        return merged

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        try:
            self._event_emitter(event_type, payload)
        except Exception as exc:
            log.debug("Command registry event emission failed: %s", exc)

    @staticmethod
    def _normalize_many(values: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
        if not values:
            return []
        out: list[str] = []
        for value in values:
            normalized = str(value or "").strip().lower()
            if normalized and normalized not in out:
                out.append(normalized)
        return out


CommandRegistry = CanonicalRuntimeCapabilityRegistry


if __name__ == "__main__":
    print("Running command_registry.py")
