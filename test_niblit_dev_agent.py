#!/usr/bin/env python3
"""Focused tests for the current NiblitDevAgent APIs."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from agents.niblit_dev_agent.agent import NiblitDevAgent
from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.event_subscriber import EventSubscriber
from agents.niblit_dev_agent.memory_bridge import MemoryBridge
from agents.niblit_dev_agent.provider_awareness import ProviderAwareness
from agents.niblit_dev_agent.runtime_awareness import RuntimeAwareness
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.event_bus import Event, EventBus, EventType


class _FakeTelemetry:
    def __init__(self):
        self.counters = {}
        self.timings = {}
        self.gauges = {}

    def increment_counter(self, name, value=1):
        self.counters[name] = self.counters.get(name, 0) + value

    def record_timing(self, name, value):
        self.timings[name] = value

    def set_gauge(self, name, value):
        self.gauges[name] = value

    def get_stats(self):
        return {
            "counters": dict(self.counters),
            "timings": dict(self.timings),
            "gauges": dict(self.gauges),
        }


class TestTelemetryHooks(unittest.TestCase):
    def test_records_metrics_via_existing_telemetry_contract(self):
        telemetry = _FakeTelemetry()
        hooks = DevAgentTelemetryHooks(telemetry)

        hooks.increment("dev_agent_events_total", 2)
        hooks.gauge("dev_agent_event_types_seen", 1.0)
        hooks.record_timing("dev_agent_runtime_snapshot_ms", 5.5)

        snapshot = hooks.snapshot()
        self.assertEqual(snapshot["counters"]["dev_agent_events_total"], 2)
        self.assertEqual(snapshot["gauges"]["dev_agent_event_types_seen"], 1.0)
        self.assertEqual(snapshot["timings"]["dev_agent_runtime_snapshot_ms"], 5.5)


class TestRuntimeSnapshot(unittest.TestCase):
    def test_no_core_graceful(self):
        snapshot = RuntimeAwareness(core=None).get_runtime_snapshot()
        self.assertIn("deployment_mode", snapshot)
        self.assertEqual(snapshot["loaded_memory_systems"], [])
        self.assertEqual(snapshot["runtime_topology"]["runtime_mode"], "normal")

    def test_with_mock_core(self):
        core = MagicMock()
        runtime_manager = MagicMock()
        runtime_manager.get_stats.return_value = {"workers": 1}
        runtime_manager.event_bus = EventBus()

        local_brain = MagicMock()
        local_brain.status.return_value = {"backend_in_use": "mock"}

        core.runtime_manager = runtime_manager
        core.local_brain = local_brain
        core.db = object()
        core.memory = None
        core.fused_memory = None
        core.memory_store = None
        core.runtime_coordinator = None

        snapshot = RuntimeAwareness(core=core).get_runtime_snapshot()
        self.assertTrue(snapshot["runtime_topology"]["runtime_manager_available"])
        self.assertTrue(snapshot["runtime_topology"]["event_bus_available"])
        self.assertTrue(snapshot["runtime_topology"]["local_brain_available"])
        self.assertIn("db", snapshot["loaded_memory_systems"])


class TestProviderAwareness(unittest.TestCase):
    def test_inspects_existing_provider_surfaces(self):
        manager = MagicMock()
        manager.status.return_value = {"active": "qwen", "qwen": True, "hf": True}

        local_brain = MagicMock()
        local_brain.status.return_value = {
            "backend_in_use": "local",
            "model_name": "qwen-test",
            "llama_server_url": "",
        }

        router = MagicMock()
        router.last_route.return_value = {"provider": "qwen"}

        snapshot = ProviderAwareness(
            local_brain=local_brain,
            router_v2=router,
            llm_provider_manager=manager,
        ).get_provider_snapshot()

        self.assertEqual(snapshot["active_provider"], "qwen")
        self.assertTrue(snapshot["fallback_available"])
        self.assertEqual(snapshot["router_last_route"]["provider"], "qwen")
        self.assertEqual(snapshot["backend_metadata"]["local_backend"], "local")


class TestArchitectureIndexer(unittest.TestCase):
    def test_lightweight_index(self):
        summary = ArchitectureIndexer(repo_root=BASE).index()
        self.assertIn("indexed_at", summary)
        self.assertIn("niblit_core.py", summary["runtime_modules"])
        self.assertTrue(summary["provider_flow"])
        self.assertTrue(summary["memory_flow"])


class TestEventSubscriber(unittest.TestCase):
    def test_tracks_events_and_emits_test_failure_workflow(self):
        telemetry = DevAgentTelemetryHooks(_FakeTelemetry())
        bus = EventBus()
        subscriber = EventSubscriber(bus, telemetry)
        self.assertTrue(subscriber.subscribe())

        bus.publish(Event(type=EventType.TEST_FAILED, payload={"err": "x"}, source="t"))
        bus.publish(Event(type=EventType.RESEARCH_REQUEST, payload={"topic": "y"}, source="t"))

        metrics = subscriber.metrics()
        self.assertEqual(metrics["event_types"].get("test_failed", 0), 1)
        self.assertEqual(metrics["event_types"].get("research_request", 0), 1)
        self.assertEqual(metrics["workflow_suggestions_total"], 1)
        self.assertEqual(subscriber.workflow_suggestions()[0]["workflow"], "test_failure_triage")


class TestNiblitDevAgent(unittest.TestCase):
    def test_cli_status_without_runtime(self):
        agent = NiblitDevAgent()
        output = agent.handle_cli("status")
        self.assertIn("NiblitDevAgent", output)
        self.assertIn("deployment_mode", output)
        self.assertEqual(agent.get_status()["state"], "idle")


class TestMemoryBridgeReadOnly(unittest.TestCase):
    def test_topology_snapshot_is_governed_and_valid(self):
        payload = MemoryBridge().build_topology_snapshot(
            {
                "deployment_mode": "local",
                "runtime_topology": {
                    "runtime_mode": "normal",
                    "event_bus_available": True,
                },
            },
            {"active_provider": "qwen"},
        )
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["authority"], "niblit_dev_agent")


if __name__ == "__main__":
    unittest.main()
