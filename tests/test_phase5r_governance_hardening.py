from types import SimpleNamespace

from modules.command_registry import CanonicalRuntimeCapabilityRegistry
from modules.execution_graph import ExecutionGraph


def test_execution_graph_never_dispatches_tools_from_input(monkeypatch):
    import niblit_tools.tool_registry as tool_registry

    calls = []

    class Registry:
        def list_tools(self):
            return [{"name": "workspace_write"}]

        def run(self, name, arguments):
            calls.append((name, arguments))
            return "unexpected dispatch"

    monkeypatch.setattr(tool_registry, "get_registry", lambda: Registry())
    mode = SimpleNamespace(
        mode_name="operational",
        intent="workspace_write",
        use_memory=False,
        use_forecast=False,
        use_tools=True,
        run_governance=False,
    )

    result = ExecutionGraph().run(
        "please workspace_write",
        context={
            "tools_called": ["spoofed_tool"],
            "tool_result_spoofed_tool": "untrusted result",
        },
        mode=mode,
    )

    assert calls == []
    assert "call_tools" not in result.steps_run
    assert result.tools_called == []
    assert "untrusted result" not in result.response


def test_runtime_status_loop_resolves_core_created_after_singleton(monkeypatch):
    from modules import core_tool_runtime

    core_tool_runtime.reset_governed_tool_loop()
    try:
        loop = core_tool_runtime.get_governed_tool_loop(lambda: None)
        core = SimpleNamespace(process=lambda command: f"core handled: {command}")

        assert core_tool_runtime.get_governed_tool_loop(lambda: core) is loop
        assert loop.executor.niblit_status() == {"status": "core handled: status"}
    finally:
        core_tool_runtime.reset_governed_tool_loop()


def test_capability_snapshot_resolves_context_and_availability_once():
    calls = {"context": 0, "availability": 0}

    def context_provider():
        calls["context"] += 1
        return {"runtime_mode": "api"}

    def availability(_context):
        calls["availability"] += 1
        return True

    registry = CanonicalRuntimeCapabilityRegistry(context_provider=context_provider)
    registry.register(
        "sample",
        lambda _text="": "ok",
        dynamic_availability=availability,
    )

    snapshot = registry.capability_snapshot(surface="runtime")

    assert len(snapshot) == 1
    assert snapshot[0]["available"] is True
    assert calls == {"context": 1, "availability": 1}


def test_brain_router_handles_gateway_without_is_available():
    from modules.brain_router import BrainRouter

    class Gateway:
        def status(self):
            return {"healthy": False, "running": False}

    router = BrainRouter(local_brain=Gateway(), cloud_brain=lambda _prompt: "cloud reply")

    assert router.stats()["local_available"] is False
    assert router.route("hello") == "cloud reply"
