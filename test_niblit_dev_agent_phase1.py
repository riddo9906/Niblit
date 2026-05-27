#!/usr/bin/env python3

from __future__ import annotations

import tempfile
from pathlib import Path

from agents.niblit_dev_agent.agent import NiblitDevAgent
from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.event_subscriber import EventSubscriber
from agents.niblit_dev_agent.provider_awareness import ProviderAwareness
from agents.niblit_dev_agent.runtime_awareness import RuntimeAwareness
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.event_bus import Event, EventBus, EventType
from niblit_core import NiblitCore


class _StubTelemetry:
    def __init__(self):
        self.counters = {}
        self.gauges = {}
        self.timings = {}

    def increment_counter(self, name, value=1):
        self.counters[name] = self.counters.get(name, 0) + value

    def set_gauge(self, name, value):
        self.gauges[name] = value

    def record_timing(self, name, value):
        self.timings.setdefault(name, []).append(value)

    def get_stats(self):
        return {
            "counters": self.counters,
            "gauges": self.gauges,
            "histograms": self.timings,
        }


class _StubProviderManager:
    def status(self):
        return {
            "active": "qwen",
            "qwen": True,
            "hf": False,
            "anthropic": False,
            "ruflo": True,
        }


class _StubRouterV2:
    def last_route(self):
        return {"backend": "http", "error": None}


class _StubLocalBrain:
    def status(self):
        return {
            "backend_in_use": "http",
            "model_name": "qwen2.5",
            "llama_server_url": "http://127.0.0.1:8000",
        }


class _StartupReport:
    def __init__(self):
        self.entries = []

    def add(self, name, status, detail=""):
        self.entries.append((name, status, detail))


def test_provider_awareness_snapshot_uses_existing_abstractions():
    pa = ProviderAwareness(
        local_brain=_StubLocalBrain(),
        router_v2=_StubRouterV2(),
        llm_provider_manager=_StubProviderManager(),
    )
    snapshot = pa.get_provider_snapshot()

    assert snapshot["active_provider"] == "qwen"
    assert snapshot["provider_health"]["qwen"] is True
    assert snapshot["fallback_available"] is True
    assert snapshot["router_last_route"]["backend"] == "http"


def test_event_subscriber_captures_event_bus_throughput():
    bus = EventBus()
    telemetry = DevAgentTelemetryHooks(_StubTelemetry())
    sub = EventSubscriber(bus, telemetry)
    assert sub.subscribe() is True

    bus.publish(Event(type=EventType.TASK_CREATED, payload={"x": 1}, source="test"))
    bus.publish(Event(type=EventType.SYSTEM_STARTED, payload={}, source="test"))

    metrics = sub.metrics()
    assert metrics["subscribed"] is True
    assert metrics["events_total"] >= 2
    assert "task_created" in metrics["event_types"]


def test_runtime_awareness_snapshot_graceful_without_core():
    ra = RuntimeAwareness(core=None, runtime_manager=None, event_bus=None, telemetry=None, local_brain=None)
    snapshot = ra.get_runtime_snapshot()

    assert "deployment_mode" in snapshot
    assert snapshot["runtime_topology"]["runtime_manager_available"] is False
    assert isinstance(snapshot["loaded_memory_systems"], list)


def test_architecture_indexer_lightweight_summary():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "niblit_core.py").write_text("# core\n", encoding="utf-8")
        (root / "core").mkdir()
        (root / "core" / "event_bus.py").write_text("# bus\n", encoding="utf-8")
        (root / "modules").mkdir()
        (root / "modules" / "runtime_router_v2.py").write_text("# rr\n", encoding="utf-8")

        idx = ArchitectureIndexer(root)
        summary = idx.index()

        assert "niblit_core.py" in summary["runtime_modules"]
        assert "scan_duration_ms" in summary
        assert isinstance(summary["provider_flow"], dict)


def test_niblit_dev_agent_cli_status_and_runtime_snapshot():
    telemetry = _StubTelemetry()
    bus = EventBus()
    agent = NiblitDevAgent(
        core=None,
        runtime_manager=None,
        event_bus=bus,
        telemetry=telemetry,
        local_brain=_StubLocalBrain(),
        router_v2=_StubRouterV2(),
        llm_provider_manager=_StubProviderManager(),
        repo_root=str(Path(__file__).resolve().parent),
    )

    status_text = agent.handle_cli("status")
    runtime_text = agent.handle_cli("runtime")
    providers_text = agent.handle_cli("providers")

    assert "NiblitDevAgent" in status_text
    assert "deployment_mode" in runtime_text
    assert "active: qwen" in providers_text


def test_niblit_core_dev_agent_command_graceful_without_registration():
    core = NiblitCore.__new__(NiblitCore)
    core.niblit_dev_agent = None

    msg = core._cmd_dev_agent("status")
    assert "not initialised" in msg.lower()


def test_niblit_core_init_agents_registers_niblit_dev_agent():
    import niblit_core as nc

    core = NiblitCore.__new__(NiblitCore)
    core.brain = None
    core.db = None
    core.build_scanner = None
    core.github_code_search = None
    core.code_generator = None
    core.code_compiler = None
    core.code_error_fixer = None
    core.local_brain = _StubLocalBrain()
    core.telemetry = _StubTelemetry()
    core.phase2_agents = {}
    core.startup_report = _StartupReport()
    core.niblit_dev_agent = None

    old_runtime_manager_flag = nc._RUNTIME_MANAGER_AVAILABLE
    old_runtime_manager = nc._RuntimeManager
    old_planner = nc._PlannerAgent
    old_research = nc._ResearchAgent
    old_coding = nc._CodingAgent
    old_testing = nc._TestingAgent
    old_reflection = nc._ReflectionAgent
    old_arch = nc._ArchitectureAgent

    try:
        from core.runtime_manager import RuntimeManager

        nc._RUNTIME_MANAGER_AVAILABLE = True
        nc._RuntimeManager = RuntimeManager
        nc._PlannerAgent = None
        nc._ResearchAgent = None
        nc._CodingAgent = None
        nc._TestingAgent = None
        nc._ReflectionAgent = None
        nc._ArchitectureAgent = None

        core._init_agents()

        assert core.runtime_manager is not None
        assert core.niblit_dev_agent is not None
        assert "dev_agent_inspect" in core.runtime_manager.orchestrator.registered_task_types
    finally:
        if getattr(core, "runtime_manager", None) is not None:
            core.runtime_manager.stop_loop()
        nc._RUNTIME_MANAGER_AVAILABLE = old_runtime_manager_flag
        nc._RuntimeManager = old_runtime_manager
        nc._PlannerAgent = old_planner
        nc._ResearchAgent = old_research
        nc._CodingAgent = old_coding
        nc._TestingAgent = old_testing
        nc._ReflectionAgent = old_reflection
        nc._ArchitectureAgent = old_arch
