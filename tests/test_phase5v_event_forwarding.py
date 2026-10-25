"""Regression coverage for Core capability event forwarding."""

from __future__ import annotations

import modules.event_bus as module_event_bus
import modules.unified_runtime as unified_runtime
from niblit_core import NiblitCore


def _fresh_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("NIBLIT_UNIFIED_RUNTIME_STATE", str(tmp_path / "runtime.json"))
    monkeypatch.setattr(module_event_bus, "_bus", None)
    monkeypatch.setattr(unified_runtime, "_unified_runtime", None)
    return NiblitCore.__new__(NiblitCore)


def _capability_events(runtime, command):
    return [
        event
        for event in runtime.events(limit=500)
        if event["type"] == "command.registered"
        and event.get("payload", {}).get("command") == command
    ]


def test_first_capability_event_is_forwarded_once_during_lazy_runtime_creation(
    monkeypatch, tmp_path
):
    core = _fresh_runtime(monkeypatch, tmp_path)
    bus = module_event_bus.get_event_bus()
    core._emit_capability_event("command.registered", {"command": "first-test"})

    runtime = unified_runtime.get_unified_runtime()
    events = _capability_events(runtime, "first-test")
    assert bus.stats().get("command.registered") == 1
    assert len(events) == 1, "first event must neither be lost nor duplicated"


def test_subsequent_capability_events_are_forwarded_once(monkeypatch, tmp_path):
    core = _fresh_runtime(monkeypatch, tmp_path)
    core._emit_capability_event("command.registered", {"command": "first-test"})
    runtime = unified_runtime.get_unified_runtime()
    bus = module_event_bus.get_event_bus()
    core._emit_capability_event("command.registered", {"command": "second-test"})

    events = _capability_events(runtime, "second-test")
    assert bus.stats().get("command.registered") == 2
    assert len(events) == 1, "subsequent event must neither be lost nor duplicated"
