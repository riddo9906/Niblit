from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import modules.niblit_ui_launcher as launcher
from modules.boot_diagnostics import BootDiagnostics


class _AliveThread:
    def is_alive(self) -> bool:
        return True


class _FakeLeanManager:
    def __init__(self) -> None:
        self.algos_dir: Path | None = None
        self._signal_thread = None
        self._monitor_thread = None
        self.start_calls = 0

    def start(self) -> str:
        self.start_calls += 1
        self._signal_thread = _AliveThread()
        self._monitor_thread = _AliveThread()
        return "started"


def test_cloud_autostart_defaults_on_for_packaged_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NIBLIT_CLOUD_AUTOSTART", raising=False)
    monkeypatch.setattr(launcher, "_bundle_base", lambda: tmp_path)
    assert launcher._cloud_autostart_enabled() is True


def test_validate_primary_ui_dependencies_requires_lean_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ui_root = tmp_path / "niblit-ui"
    ui_root.mkdir()
    (ui_root / "package.json").write_text("{}")

    monkeypatch.setattr(launcher, "find_lean_algos_root", lambda: None)
    monkeypatch.setattr(launcher, "_cloud_autostart_enabled", lambda: False)
    monkeypatch.setattr(launcher, "_http_ready", lambda *args, **kwargs: False)
    monkeypatch.setattr(launcher, "is_port_available", lambda *args, **kwargs: True)
    monkeypatch.setattr(launcher, "_resolve_npm", lambda: "npm")

    with pytest.raises(FileNotFoundError, match="Lean execution layer"):
        launcher.validate_primary_ui_dependencies(
            diagnostics=BootDiagnostics(),
            ui_root=ui_root,
            ui_exe=None,
            cloud_url="http://127.0.0.1:8000",
            api_host="127.0.0.1",
            api_port=8080,
            ui_port=5173,
            tauri_mode=False,
        )


def test_ensure_lean_runtime_ready_starts_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lean_root = tmp_path / "niblit-lean-algos"
    (lean_root / "niblit_bridge").mkdir(parents=True)
    (lean_root / "algorithms").mkdir()

    manager = _FakeLeanManager()
    core = SimpleNamespace(lean_algo_manager=manager)

    monkeypatch.setattr(launcher, "find_lean_algos_root", lambda: lean_root)
    monkeypatch.delenv("NIBLIT_LEAN_ALGOS_ROOT", raising=False)
    monkeypatch.delenv("NIBLIT_LEAN_ALGOS", raising=False)

    old_root = os.environ.get("NIBLIT_LEAN_ALGOS_ROOT")
    old_algos = os.environ.get("NIBLIT_LEAN_ALGOS")
    try:
        result = launcher.ensure_lean_runtime_ready(core, diagnostics=BootDiagnostics())

        assert result == lean_root
        assert manager.algos_dir == lean_root
        assert manager.start_calls == 1
        assert os.environ["NIBLIT_LEAN_ALGOS_ROOT"] == str(lean_root)
        assert os.environ["NIBLIT_LEAN_ALGOS"] == str(lean_root)
    finally:
        if old_root is None:
            os.environ.pop("NIBLIT_LEAN_ALGOS_ROOT", None)
        else:
            os.environ["NIBLIT_LEAN_ALGOS_ROOT"] = old_root
        if old_algos is None:
            os.environ.pop("NIBLIT_LEAN_ALGOS", None)
        else:
            os.environ["NIBLIT_LEAN_ALGOS"] = old_algos


def test_verify_runtime_bootstrap_requires_skills_layer() -> None:
    core = SimpleNamespace(
        runtime_manager=object(),
        startup_report=SimpleNamespace(results={"db": {"status": "ready"}}),
        db=object(),
        router=None,
        brain_router=None,
        local_brain=object(),
        brain=None,
    )

    with pytest.raises(RuntimeError, match="Skills layer"):
        launcher.verify_runtime_bootstrap(core, diagnostics=BootDiagnostics())
