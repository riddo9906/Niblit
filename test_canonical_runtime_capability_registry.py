from __future__ import annotations

from pathlib import Path

from modules.command_registry import CanonicalRuntimeCapabilityRegistry
from modules.unified_runtime import NiblitUnifiedRuntime


def test_registry_executes_alias_with_original_payload() -> None:
    seen: list[str] = []
    registry = CanonicalRuntimeCapabilityRegistry()

    def handler(text: str) -> str:
        seen.append(text)
        return text

    registry.register("runtime infer", handler, "runtime infer", "runtime", aliases=("infer runtime",))
    out = registry.execute("infer runtime Keep CASE", context={"surface": "cli"}, surface="cli")
    assert out == "Keep CASE"
    assert seen == ["Keep CASE"]


def test_registry_filters_by_surface_and_dynamic_availability() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "dev-agent status",
        lambda _text="": "ok",
        "status",
        "dev_agent",
        visibility_surfaces={"cli", "desktop"},
        dynamic_availability=lambda ctx: (bool(ctx.get("dev_agent_available")), "dev-agent unavailable"),
    )
    cli_snapshot = registry.capability_snapshot(
        context={"dev_agent_available": False, "surface": "cli"},
        surface="cli",
        include_unavailable=True,
    )
    assert cli_snapshot[0]["available"] is False
    assert "dev-agent unavailable" in cli_snapshot[0]["availability_reason"]
    api_snapshot = registry.capability_snapshot(
        context={"dev_agent_available": True, "surface": "api"},
        surface="api",
        include_unavailable=True,
    )
    assert api_snapshot[0]["available"] is False


def test_registry_allows_discoverability_without_execution() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "router only",
        None,
        "discoverable router capability",
        "routing",
        source_authority="niblit_router.py",
        execution_authority="NiblitRouter.handle_command",
    )
    assert registry.execute("router only", context={"surface": "cli"}, surface="cli") is None
    snapshot = registry.capability_snapshot(context={"surface": "cli"}, surface="cli", include_unavailable=True)
    assert snapshot[0]["executable"] is False
    assert snapshot[0]["source_authority"] == "niblit_router.py"


def test_unified_runtime_includes_capability_snapshot(tmp_path: Path) -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("help", lambda _text="": "ok", "help", "core", priority=100)

    class DummyCore:
        command_registry = registry

        @staticmethod
        def _command_registry_context() -> dict:
            return {"runtime_mode": "api", "active_provider": "qwen", "surface": "runtime"}

    runtime = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    state = runtime.state(core=DummyCore())["state"]
    assert state["capability_summary"]["total"] >= 1
    assert any(item["name"] == "help" for item in state["capabilities"])
