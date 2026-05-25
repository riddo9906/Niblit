#!/usr/bin/env python3
"""EventBus subscriber for NiblitDevAgent runtime awareness."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.event_bus import Event, EventBus

log = logging.getLogger("NiblitDevAgent.EventSubscriber")


class EventSubscriber:
    """Observes EventBus traffic without introducing new event infrastructure."""

    def __init__(self, event_bus: EventBus | None, telemetry: DevAgentTelemetryHooks) -> None:
        self._event_bus = event_bus
        self._telemetry = telemetry
        self._subscribed = False
        self._event_counts: dict[str, int] = defaultdict(int)
        self._category_counts: dict[str, int] = defaultdict(int)

    def subscribe(self) -> bool:
        if self._event_bus is None or self._subscribed:
            return False
        self._event_bus.subscribe_all(self._handle_event)
        self._subscribed = True
        return True

    def _handle_event(self, event: Event) -> None:
        etype = event.type.value
        self._event_counts[etype] += 1
        category = self._categorize_event(etype)
        self._category_counts[category] += 1

        self._telemetry.increment("dev_agent_events_total", 1)
        self._telemetry.increment(f"dev_agent_events_{category}_total", 1)
        self._telemetry.gauge("dev_agent_event_types_seen", float(len(self._event_counts)))

    @staticmethod
    def _categorize_event(event_type: str) -> str:
        et = event_type.lower()
        if "provider" in et or "llm" in et:
            return "provider"
        if et.startswith("system_") or "boot" in et or "runtime" in et:
            return "runtime"
        if "deploy" in et or "environment" in et or "profile" in et:
            return "deployment"
        if "metric" in et or "telemetry" in et:
            return "telemetry"
        if "task" in et or "plan" in et or "orchestr" in et:
            return "orchestration"
        if "error" in et or "warn" in et:
            return "warning"
        return "other"

    def metrics(self) -> dict[str, Any]:
        return {
            "subscribed": self._subscribed,
            "events_total": int(sum(self._event_counts.values())),
            "event_types": dict(self._event_counts),
            "categories": dict(self._category_counts),
        }
