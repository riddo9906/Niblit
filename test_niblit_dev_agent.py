#!/usr/bin/env python3
"""Focused tests for NiblitDevAgent Phase 1 scaffold."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.event_bus import Event, EventBus, EventType
from core.runtime_manager import RuntimeManager

from agents.niblit_dev_agent.agent import NiblitDevAgent, get_niblit_dev_agent
from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.event_subscriber import EventSubscriber
from agents.niblit_dev_agent.provider_awareness import ProviderAwareness
from agents.niblit_dev_agent.runtime_awareness import RuntimeAwareness, detect_deployment_mode
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetry


class _FakeTelemetry:
    def __init__(self):
        self.counters = {}
        self.timings = {}

    def increment_counter(self, name, value=1):
        self.counters[name] = self.counters.get(name, 0) + value

    def record_timing(self, name, value):
        self.timings[name] = value


class TestRuntimeRegistration(unittest.TestCase):
    def test_register_with_core_wires_event_bus(self):
        agent = NiblitDevAgent()
        rm = RuntimeManager()
        core = MagicMock()
        core.telemetry = _FakeTelemetry()
        core.runtime_manager = rm
        core._deferred_init_phase = "complete"
        core.local_brain = None
        core.db = None
        core.memory = None

        ok = agent.register_with_core(core)
        self.assertTrue(ok)
        self.assertTrue(agent.status.registered)
        self.assertTrue(agent.status.architecture_indexed)

        rm.event_bus.publish(
            Event(type=EventType.SYSTEM_STARTED, payload={"test": True}, source="test")
        )
        self.assertGreaterEqual(agent._events.get_counts().get("system_started", 0), 1)

        agent.shutdown()


class TestRuntimeSnapshot(unittest.TestCase):
    def test_no_core_graceful(self):
        ra = RuntimeAwareness(core=None)
        snap = ra.get_runtime_snapshot()
        self.assertEqual(snap.deployment_mode, detect_deployment_mode())
        self.assertIn("note", snap.extra)

    def test_with_mock_core(self):
        core = MagicMock()
        core._deferred_init_phase = "running"
        core.telemetry = object()
        core.runtime_manager = None
        core.local_brain = object()
        core.db = object()
        core.memory = None
        core.fused_memory = None
        core.hybrid_qdrant = None
        core.memory_store = None
        core.llm_enabled = True
        core.orchestrator_available = True

        snap = RuntimeAwareness(core).to_dict()
        self.assertEqual(snap["deferred_init_phase"], "running")
        self.assertTrue(snap["local_brain_available"])
        self.assertTrue(snap["memory_systems"]["db"])


class TestProviderAwareness(unittest.TestCase):
    @patch("modules.llm_provider_manager.get_llm_provider_manager")
    def test_inspects_manager_without_direct_calls(self, mock_get_mgr):
        mgr = MagicMock()
        mgr.status.return_value = {"active": "qwen", "qwen": True}
        mock_get_mgr.return_value = mgr

        core = MagicMock()
        core.local_brain = None
        core.brain_router = None

        snap = ProviderAwareness(core).to_dict()
        self.assertEqual(snap["llm_provider_manager"]["active"], "qwen")
        mgr.ask.assert_not_called()


class TestArchitectureIndexer(unittest.TestCase):
    def test_lightweight_index(self):
        idx = ArchitectureIndexer(repo_root=BASE)
        summary = idx.index(force=True)
        self.assertTrue(summary.repo_root)
        self.assertIn("niblit_core.py", summary.runtime_modules)
        self.assertTrue(summary.provider_flow)
        self.assertTrue(summary.memory_flow)


class TestEventSubscriber(unittest.TestCase):
    def test_filters_observed_events(self):
        tel = DevAgentTelemetry()
        sub = EventSubscriber(tel)
        bus = EventBus()
        sub.attach(bus)

        bus.publish(Event(type=EventType.TASK_FAILED, payload={"err": "x"}, source="t"))
        bus.publish(Event(type=EventType.RESEARCH_REQUEST, payload={"topic": "y"}, source="t"))

        self.assertEqual(sub.get_counts().get("task_failed", 0), 1)
        self.assertNotIn("research_request", sub.get_counts())
        sub.detach()


class TestOptionalDependencies(unittest.TestCase):
    def test_singleton_factory(self):
        a = get_niblit_dev_agent()
        b = get_niblit_dev_agent()
        self.assertIs(a, b)

    def test_cli_without_registration(self):
        agent = NiblitDevAgent()
        out = agent.format_cli("status")
        self.assertIn("NiblitDevAgent", out)
        self.assertFalse(agent.status.registered)


class TestMemoryBridgeReadOnly(unittest.TestCase):
    def test_read_only_flag(self):
        from agents.niblit_dev_agent.memory_bridge import MemoryBridge

        ctx = MemoryBridge(core=None).get_memory_context()
        self.assertTrue(ctx["read_only"])


if __name__ == "__main__":
    unittest.main()
