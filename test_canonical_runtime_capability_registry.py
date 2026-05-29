from __future__ import annotations

from pathlib import Path

import pytest

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


# ─── Additional coverage tests ───────────────────────────────────────────────


def test_can_handle_returns_true_for_registered_executable() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("ping", lambda _text="": "pong", "ping", "core")
    assert registry.can_handle("ping", surface="cli") is True
    assert registry.can_handle("unknown command", surface="cli") is False


def test_can_handle_returns_false_for_non_executable() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("discoverable", None, "desc", "core")
    assert registry.can_handle("discoverable", surface="cli") is False


def test_command_names_includes_aliases() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("help", lambda _text="": "ok", "help", "core", aliases=("h", "?"))
    names = registry.command_names(surface="cli", include_aliases=True, include_unavailable=True)
    assert "help" in names
    assert "h" in names
    assert "?" in names


def test_command_names_excludes_aliases_when_requested() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("help", lambda _text="": "ok", "help", "core", aliases=("h",))
    names = registry.command_names(surface="cli", include_aliases=False, include_unavailable=True)
    assert "help" in names
    assert "h" not in names


def test_get_help_returns_formatted_text() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("do thing", lambda _text="": "done", "Does the thing", "tools", priority=5)
    help_text = registry.get_help(surface="help", include_unavailable=True)
    assert "TOOLS" in help_text.upper()
    assert "do thing" in help_text
    assert "Does the thing" in help_text


def test_get_help_filters_by_category() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("cmd a", lambda _text="": "a", "A", "alpha")
    registry.register("cmd b", lambda _text="": "b", "B", "beta")
    help_text = registry.get_help(category="alpha", surface="help", include_unavailable=True)
    assert "cmd a" in help_text
    assert "cmd b" not in help_text


def test_get_help_marks_deprecated_commands() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("old-cmd", lambda _text="": "x", "Old thing", "core", deprecated=True, deprecation_message="use new-cmd")
    help_text = registry.get_help(surface="help", include_unavailable=True)
    assert "deprecated" in help_text


def test_suggestions_returns_close_matches() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("runtime infer", lambda _text="": "ok", "Infer", "runtime")
    registry.register("runtime status", lambda _text="": "ok", "Status", "runtime")
    results = registry.suggestions("runtime infet", surface="discoverability", include_unavailable=True)
    assert any("runtime infer" in r for r in results)


def test_suggestions_excludes_exact_match() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("ping", lambda _text="": "ok", "Ping", "core")
    results = registry.suggestions("ping", surface="discoverability", include_unavailable=True)
    assert "ping" not in results


def test_detailed_report_lists_all_commands() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("cmd-x", lambda _text="": "x", "Description X", "group")
    report = registry.detailed_report(surface="discoverability", include_unavailable=True)
    assert "cmd-x" in report
    assert "Description X" in report


def test_grouped_catalog_organizes_by_category() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("action a", lambda _text="": "a", "A", "alpha")
    registry.register("action b", lambda _text="": "b", "B", "beta")
    catalog = registry.grouped_catalog(surface="desktop", include_unavailable=True)
    categories = {group["category"] for group in catalog}
    assert "alpha" in categories
    assert "beta" in categories


def test_ui_catalog_returns_label_and_cmd() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "my command",
        lambda _text="": "result",
        "Does something",
        "core",
        ui_metadata={"label": "My Command", "cmd": "my command", "has_input": True},
    )
    catalog = registry.ui_catalog(surface="desktop", include_unavailable=True)
    assert len(catalog) >= 1
    commands = catalog[0]["commands"]
    assert commands[0]["label"] == "My Command"
    assert commands[0]["has_input"] is True


def test_get_stats_initial_state_has_full_success_rate() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    stats = registry.get_stats()
    assert stats["total_executed"] == 0
    assert stats["total_failed"] == 0
    assert stats["success_rate"] == 1.0


def test_get_stats_tracks_successes_and_failures() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("good", lambda _text="": "ok", "Good", "core")
    registry.register("bad", lambda _text="": (_ for _ in ()).throw(RuntimeError("boom")), "Bad", "core")

    registry.execute("good", surface="cli")
    registry.execute("good", surface="cli")
    registry.execute("bad", surface="cli")  # will fail

    stats = registry.get_stats()
    assert stats["total_executed"] == 3
    assert stats["total_failed"] == 1
    assert abs(stats["success_rate"] - 2 / 3) < 1e-9


def test_execute_returns_error_string_on_failure() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("explode", lambda _text="": (_ for _ in ()).throw(ValueError("kaboom")), "Explode", "core")
    result = registry.execute("explode", surface="cli")
    assert result is not None
    assert "[ERROR]" in result
    assert "kaboom" in result


def test_execute_returns_unavailable_string_when_not_available() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "gated",
        lambda _text="": "ok",
        "Gated",
        "core",
        dynamic_availability=lambda _ctx: (False, "needs admin"),
    )
    result = registry.execute("gated", surface="cli")
    assert result is not None
    assert "[UNAVAILABLE]" in result
    assert "needs admin" in result


def test_runtime_modes_filter_availability() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "cloud-only",
        lambda _text="": "ok",
        "Cloud only command",
        "cloud",
        runtime_modes=("cloud",),
    )
    snap = registry.capability_snapshot(
        context={"runtime_mode": "local", "surface": "cli"},
        surface="cli",
        include_unavailable=True,
    )
    assert snap[0]["available"] is False
    assert "mode=local" in snap[0]["availability_reason"]


def test_provider_requirements_filter_availability() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "openai-only",
        lambda _text="": "ok",
        "OpenAI only command",
        "llm",
        provider_requirements=("openai",),
    )
    snap = registry.capability_snapshot(
        context={"active_provider": "qwen", "surface": "cli"},
        surface="cli",
        include_unavailable=True,
    )
    assert snap[0]["available"] is False
    assert "provider=qwen" in snap[0]["availability_reason"]


def test_visibility_reason_when_surface_not_in_surfaces() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register(
        "desktop-only",
        lambda _text="": "ok",
        "Desktop only",
        "ui",
        visibility_surfaces={"desktop"},
    )
    snap = registry.capability_snapshot(
        context={"surface": "cli"},
        surface="cli",
        include_unavailable=True,
    )
    assert snap[0]["available"] is False
    assert "cli" in snap[0]["availability_reason"]


def test_event_emitter_called_on_register() -> None:
    events: list[tuple[str, dict]] = []
    registry = CanonicalRuntimeCapabilityRegistry(event_emitter=lambda t, p: events.append((t, p)))
    registry.register("my-cmd", lambda _text="": "ok", "My cmd", "core")
    assert any(e[0] == "command.registered" for e in events)
    registered = next(e for e in events if e[0] == "command.registered")
    assert registered[1]["command"] == "my-cmd"


def test_event_emitter_called_for_deprecated_on_register() -> None:
    events: list[tuple[str, dict]] = []
    registry = CanonicalRuntimeCapabilityRegistry(event_emitter=lambda t, p: events.append((t, p)))
    registry.register("old", lambda _text="": "ok", "Old", "core", deprecated=True, deprecation_message="use new")
    assert any(e[0] == "command.deprecated" for e in events)


def test_resolve_longest_prefix_wins() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("dev", lambda text="": f"dev:{text}", "Generic dev", "core", priority=0)
    registry.register("dev-agent status", lambda text="": f"das:{text}", "Dev status", "core", priority=0)
    result = registry.execute("dev-agent status now", surface="cli")
    assert result == "das:now"


def test_priority_wins_over_shorter_prefix() -> None:
    registry = CanonicalRuntimeCapabilityRegistry()
    registry.register("run test", lambda text="": f"run-test:{text}", "Run test", "core", priority=10)
    registry.register("run", lambda text="": f"run:{text}", "Run", "core", priority=1)
    result = registry.execute("run test extra", surface="cli")
    assert result == "run-test:extra"


def test_context_provider_is_merged() -> None:
    registry = CanonicalRuntimeCapabilityRegistry(
        context_provider=lambda: {"runtime_mode": "cloud"},
    )
    registry.register("cloud-cmd", lambda _text="": "ok", "Cloud cmd", "core", runtime_modes=("cloud",))
    snap = registry.capability_snapshot(surface="cli", include_unavailable=True)
    assert snap[0]["available"] is True
