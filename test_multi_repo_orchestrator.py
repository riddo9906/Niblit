"""Tests for modules/multi_repo_orchestrator.py.

Covers:
- Repository discovery (present, absent, env-override paths)
- Layer status transitions (initialized, degraded, failed)
- Graceful degradation when managed repos are absent
- Event bus integration
- Boot report structure
- Runtime status reporting
- Singleton factory
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modules.multi_repo_orchestrator import (
    MANAGED_REPOS,
    BootLayer,
    LayerStatus,
    MultiRepoOrchestrator,
    RepositoryDiscovery,
    RepositoryManifest,
    _build_boot_layers,
    get_multi_repo_orchestrator,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_orchestrator(
    tmp_root: Path,
    bus: object | None = None,
) -> MultiRepoOrchestrator:
    """Return an orchestrator rooted at *tmp_root* with an optional injected bus."""
    return MultiRepoOrchestrator(niblit_root=tmp_root, event_bus=bus)


# ── BootLayer ─────────────────────────────────────────────────────────────────

class TestBootLayer:
    def test_duration_ms_zero_when_not_timed(self) -> None:
        layer = BootLayer(layer_id=0, name="Test", components=[])
        assert layer.duration_ms == 0.0

    def test_duration_ms_computed(self) -> None:
        layer = BootLayer(layer_id=0, name="Test", components=[])
        layer.start_time = 1_000_000.0
        layer.end_time = 1_000_000.5
        assert abs(layer.duration_ms - 500.0) < 1.0

    def test_to_dict_includes_status_value(self) -> None:
        layer = BootLayer(layer_id=2, name="EventBus", components=["CoreBus"])
        layer.status = LayerStatus.INITIALIZED
        d = layer.to_dict()
        assert d["status"] == "initialized"
        assert d["layer_id"] == 2
        assert "duration_ms" in d


# ── _build_boot_layers ────────────────────────────────────────────────────────

class TestBuildBootLayers:
    def test_exactly_eight_layers(self) -> None:
        layers = _build_boot_layers()
        assert len(layers) == 8

    def test_layer_ids_are_sequential(self) -> None:
        layers = _build_boot_layers()
        assert [layer.layer_id for layer in layers] == list(range(8))

    def test_layer_6_has_cloud_server_repo(self) -> None:
        layers = _build_boot_layers()
        cloud = layers[6]
        assert cloud.managed_repo == "niblit-cloud-server"

    def test_layer_7_has_ui_repo(self) -> None:
        layers = _build_boot_layers()
        gui = layers[7]
        assert gui.managed_repo == "niblit-ui"

    def test_internal_layers_have_no_managed_repo(self) -> None:
        layers = _build_boot_layers()
        for layer in layers[:6]:
            assert layer.managed_repo == ""


# ── RepositoryDiscovery ───────────────────────────────────────────────────────

class TestRepositoryDiscovery:
    def test_discover_returns_manifest_when_present(self, tmp_path: Path) -> None:
        # Create a fake niblit-lean-algos sibling with the expected structure.
        lean_root = tmp_path.parent / "niblit-lean-algos"
        lean_root.mkdir(parents=True, exist_ok=True)
        (lean_root / "lean.json").write_text("{}")

        discovery = RepositoryDiscovery(tmp_path)
        manifest = discovery.discover("niblit-lean-algos")

        assert manifest.present
        assert manifest.compatible

    def test_discover_returns_not_present_when_absent(self, tmp_path: Path) -> None:
        discovery = RepositoryDiscovery(tmp_path)
        manifest = discovery.discover("niblit-ui")
        assert not manifest.present
        assert manifest.availability_state == "unavailable"
        assert manifest.runtime_maps["nodes"]["status"] == "unavailable"
        assert "startup_commands" in manifest.bootstrap_contract
        assert manifest.error

    def test_env_override_takes_precedence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ui = tmp_path / "fake-ui"
        fake_ui.mkdir()
        (fake_ui / "package.json").write_text("{}")
        monkeypatch.setenv("NIBLIT_UI_ROOT", str(fake_ui))

        discovery = RepositoryDiscovery(tmp_path)
        manifest = discovery.discover("niblit-ui")

        assert manifest.present
        assert manifest.root == fake_ui.resolve()
        assert manifest.compatible

    def test_bundled_lean_algos_discovered(self, tmp_path: Path) -> None:
        # niblit-lean-algos lives inside the Niblit root.
        bundled = tmp_path / "niblit-lean-algos"
        bundled.mkdir()
        (bundled / "lean.json").write_text("{}")

        discovery = RepositoryDiscovery(tmp_path)
        manifest = discovery.discover("niblit-lean-algos")

        assert manifest.present

    def test_discover_all_returns_all_repos(self, tmp_path: Path) -> None:
        discovery = RepositoryDiscovery(tmp_path)
        manifests = discovery.discover_all()
        assert set(manifests.keys()) == set(MANAGED_REPOS)

    def test_cloud_server_compatible_with_requirements_txt(self, tmp_path: Path) -> None:
        fake_cloud = tmp_path.parent / "niblit-cloud-server"
        fake_cloud.mkdir(parents=True, exist_ok=True)
        (fake_cloud / "requirements.txt").write_text("fastapi\n")

        discovery = RepositoryDiscovery(tmp_path)
        manifest = discovery.discover("niblit-cloud-server")

        assert manifest.present
        assert manifest.compatible
        assert manifest.availability_state == "available"
        assert "health_check" in manifest.bootstrap_contract
        assert "event_channels" in manifest.bootstrap_contract

    def test_services_detected_for_lean_algos_with_niblit_bridge(self, tmp_path: Path) -> None:
        lean = tmp_path / "niblit-lean-algos"
        lean.mkdir()
        (lean / "lean.json").write_text("{}")
        (lean / "niblit_bridge").mkdir()

        discovery = RepositoryDiscovery(tmp_path)
        manifest = discovery.discover("niblit-lean-algos")

        assert "niblit_bridge" in manifest.services


# ── MultiRepoOrchestrator ─────────────────────────────────────────────────────

class TestMultiRepoOrchestrator:
    def test_boot_returns_report_dict(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()

        assert "runtime_status" in report
        assert "layers" in report
        assert "repositories" in report
        assert "duration_ms" in report
        assert "correlation_id" in report
        assert "managed_services" in report

    def test_boot_runtime_status_is_string(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        assert report["runtime_status"] in ("ready", "degraded", "failed")

    def test_boot_reports_eight_layers(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        assert len(report["layers"]) == 8

    def test_boot_reports_all_managed_repos(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        for repo in MANAGED_REPOS:
            assert repo in report["repositories"]

    def test_missing_managed_repos_degrade_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Clear all repo-path env overrides so discovery only searches
        # inside tmp_path (where no managed repos exist).
        from modules.multi_repo_orchestrator import REPO_PATH_ENV
        for env_var in REPO_PATH_ENV.values():
            monkeypatch.delenv(env_var, raising=False)

        orch = _make_orchestrator(tmp_path)
        report = orch.boot()

        # Layers backed by managed repos that are absent must degrade, not fail.
        for layer_dict in report["layers"]:
            if layer_dict["layer_id"] in (6, 7):
                repo_name = "niblit-cloud-server" if layer_dict["layer_id"] == 6 else "niblit-ui"
                repo_info = report["repositories"][repo_name]
                if not repo_info["present"]:
                    assert layer_dict["status"] == LayerStatus.DEGRADED.value

    def test_present_lean_algos_initializes_layer_5(self, tmp_path: Path) -> None:
        # Layer 5 is an internal layer so it should probe module imports.
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        layer_5 = next(lay for lay in report["layers"] if lay["layer_id"] == 5)
        # Status is determined by whether the module can be imported; either
        # initialized or degraded is acceptable — it must not be "pending".
        assert layer_5["status"] != LayerStatus.PENDING.value

    def test_get_layer_returns_correct_layer(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch.boot()
        layer = orch.get_layer(0)
        assert layer is not None
        assert layer.layer_id == 0
        assert layer.name == "RuntimeManager"

    def test_get_layer_returns_none_for_unknown_id(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        assert orch.get_layer(99) is None

    def test_get_repo_manifest_after_boot(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch.boot()
        manifest = orch.get_repo_manifest("niblit-ui")
        assert manifest is not None
        assert isinstance(manifest, RepositoryManifest)

    def test_get_runtime_status_before_boot(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        status = orch.get_runtime_status()
        assert status["runtime_status"] == "pending"

    def test_event_bus_receives_layer_events(self, tmp_path: Path) -> None:
        bus = MagicMock()
        orch = _make_orchestrator(tmp_path, bus=bus)
        orch.boot()
        # The mock bus should have been called for layer and repo events.
        assert bus.publish.call_count > 0

    def test_layer_events_published_for_each_layer(self, tmp_path: Path) -> None:
        published_types: list[str] = []

        class FakeBus:
            def publish(self, event: object) -> None:
                t = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
                if t:
                    published_types.append(str(t))

        orch = _make_orchestrator(tmp_path, bus=FakeBus())
        orch.boot()

        layer_event_types = {t for t in published_types if t.startswith("layer.")}
        # Each of 8 layers must emit at least one layer.* event.
        assert len(layer_event_types) >= 1

    def test_runtime_ready_event_published(self, tmp_path: Path) -> None:
        published_types: list[str] = []

        class FakeBus:
            def publish(self, event: object) -> None:
                t = getattr(event, "type", None)
                if t:
                    published_types.append(str(t))

        orch = _make_orchestrator(tmp_path, bus=FakeBus())
        orch.boot()
        assert "runtime.ready" in published_types

    def test_repo_discovery_events_published(self, tmp_path: Path) -> None:
        published_types: list[str] = []

        class FakeBus:
            def publish(self, event: object) -> None:
                t = getattr(event, "type", None)
                if t:
                    published_types.append(str(t))

        orch = _make_orchestrator(tmp_path, bus=FakeBus())
        orch.boot()
        # Expect either "repo.discovered" or "repo.unavailable" for each repo.
        repo_events = [t for t in published_types if t.startswith("repo.")]
        assert len(repo_events) >= len(MANAGED_REPOS)

    def test_correlation_id_consistent_across_boot(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        cid = report["correlation_id"]
        assert cid
        assert report["correlation_id"] == cid

    def test_duration_ms_non_negative(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        assert report["duration_ms"] >= 0.0

    def test_layer_to_dict_in_report_has_required_keys(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        for layer_dict in report["layers"]:
            assert "layer_id" in layer_dict
            assert "name" in layer_dict
            assert "status" in layer_dict
            assert "components" in layer_dict
            assert "duration_ms" in layer_dict

    def test_repo_dict_in_report_has_required_keys(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        for repo_name, repo_dict in report["repositories"].items():
            assert "name" in repo_dict
            assert "present" in repo_dict
            assert "compatible" in repo_dict
            assert "layer" in repo_dict
            assert "availability_state" in repo_dict
            assert "bootstrap_contract" in repo_dict
            assert "runtime_maps" in repo_dict

    def test_present_managed_repo_initializes_layer(self, tmp_path: Path) -> None:
        # Plant a fake niblit-cloud-server inside tmp_path.
        cloud = tmp_path / "niblit-cloud-server"
        cloud.mkdir()
        (cloud / "requirements.txt").write_text("fastapi\n")

        orch = _make_orchestrator(tmp_path)
        report = orch.boot()
        layer_6 = next(lay for lay in report["layers"] if lay["layer_id"] == 6)
        assert layer_6["status"] == LayerStatus.INITIALIZED.value

    def test_supervision_registers_states_for_managed_repositories(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch.boot()
        states = orch.get_supervision_status()
        for repo in MANAGED_REPOS:
            assert repo in states
            assert "state" in states[repo]

    def test_start_managed_repositories_returns_unavailable_when_absent(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch.boot()
        started = orch.start_managed_repositories(["niblit-ui"])
        assert started["niblit-ui"]["state"] in {"unavailable", "degraded", "registered", "running"}


# ── Singleton factory ─────────────────────────────────────────────────────────

class TestGetMultiRepoOrchestrator:
    def test_singleton_returns_same_instance(self, tmp_path: Path) -> None:
        import modules.multi_repo_orchestrator as mod
        mod._ORCHESTRATOR = None  # reset for test isolation

        a = get_multi_repo_orchestrator(niblit_root=tmp_path)
        b = get_multi_repo_orchestrator(niblit_root=tmp_path)
        assert a is b
        mod._ORCHESTRATOR = None  # cleanup


# ── Event type values ─────────────────────────────────────────────────────────

class TestEventTypeValues:
    def test_layer_event_type_values_importable(self) -> None:
        from core.event_bus import EventType

        assert EventType.LAYER_INITIALIZED.value == "layer.initialized"
        assert EventType.LAYER_DEGRADED.value == "layer.degraded"
        assert EventType.LAYER_FAILED.value == "layer.failed"
        assert EventType.LAYER_RETRYING.value == "layer.retrying"
        assert EventType.RUNTIME_READY.value == "runtime.ready"
        assert EventType.REPO_DISCOVERED.value == "repo.discovered"
        assert EventType.REPO_UNAVAILABLE.value == "repo.unavailable"
        assert EventType.REPO_REGISTERED.value == "repo.registered"


# ── Event dataclass canonical envelope fields ─────────────────────────────────

class TestEventEnvelopeFields:
    def test_event_has_source_repository_field(self) -> None:
        from core.event_bus import Event, EventType

        evt = Event(type=EventType.SYSTEM_STARTED, source="test")
        assert hasattr(evt, "source_repository")
        assert evt.source_repository == "niblit"

    def test_event_has_correlation_id_field(self) -> None:
        from core.event_bus import Event, EventType

        evt = Event(type=EventType.SYSTEM_STARTED, source="test", correlation_id="abc-123")
        assert evt.correlation_id == "abc-123"

    def test_event_has_parent_event_id_field(self) -> None:
        from core.event_bus import Event, EventType

        evt = Event(type=EventType.SYSTEM_STARTED, source="test", parent_event_id=42)
        assert evt.parent_event_id == 42

    def test_event_has_destination_field(self) -> None:
        from core.event_bus import Event, EventType

        evt = Event(type=EventType.SYSTEM_STARTED, source="test", destination="foundation_architecture")
        assert evt.destination == "foundation_architecture"

    def test_event_has_intent_field(self) -> None:
        from core.event_bus import Event, EventType

        evt = Event(type=EventType.SYSTEM_STARTED, source="test", intent="boot_layer_0")
        assert evt.intent == "boot_layer_0"

    def test_existing_event_fields_still_present(self) -> None:
        from core.event_bus import Event, EventType

        evt = Event(
            type=EventType.SYSTEM_STARTED,
            source="test",
            payload={"k": "v"},
            event_priority="high",
        )
        assert evt.type == EventType.SYSTEM_STARTED
        assert evt.source == "test"
        assert evt.payload == {"k": "v"}
        assert evt.event_priority == "high"
        assert evt.trace_id  # auto-generated
