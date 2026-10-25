"""Offline coverage for frozen service ownership and final readiness checks."""
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.trading_runtime_client import TradingRuntimeClient
from modules.multi_repo_orchestrator import RepositorySupervisor


def test_deferred_wait_does_not_spin_after_essential_readiness():
    import main
    core = SimpleNamespace(_deferred_init_event=threading.Event(), _deferred_init_phase="running")
    assert main.NiblitCore.wait_for_initialization(core, timeout=0.01) is False
    core._deferred_init_phase = "complete"
    core._deferred_init_event.set()
    assert main.NiblitCore.wait_for_initialization(core, timeout=0.01) is True


def test_explicit_environment_file_loads_without_source_checkout(monkeypatch, tmp_path):
    from modules.resilient_boot import BootStatus, load_environment
    env_file = tmp_path / "testing.env"
    env_file.write_text("NIBLIT_TEST_ENV_MARKER=standalone\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    monkeypatch.delenv("NIBLIT_TEST_ENV_MARKER", raising=False)
    monkeypatch.setenv("NIBLIT_ENV_FILE", str(env_file))
    status = BootStatus()
    assert load_environment(str(tmp_path), status)
    import os
    assert os.environ["NIBLIT_TEST_ENV_MARKER"] == "standalone"
    monkeypatch.delenv("NIBLIT_TEST_ENV_MARKER")
    assert str(env_file) in status.env_sources


def test_frozen_bootstrap_cannot_walk_into_source_checkout(monkeypatch, tmp_path):
    import sys
    from modules.runtime_bootstrap import _find_repo_root
    (tmp_path / "niblit_core.py").touch()
    (tmp_path / "niblit_io.py").touch()
    bundle = tmp_path / "dist" / "niblit"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "niblit.exe"))
    assert _find_repo_root(bundle / "main.py") == bundle


def test_trading_client_attaches_without_claiming_service_ownership(monkeypatch):
    client = TradingRuntimeClient()
    monkeypatch.setattr(client, "_refresh", lambda *args: True)
    asyncio.run(client.start())
    assert client._owns_service is False
    asyncio.run(client.stop())


def test_trading_client_starts_and_stops_only_its_supervised_lean(monkeypatch):
    from modules import multi_repo_orchestrator as module
    client = TradingRuntimeClient()
    orchestrator = Mock()
    orchestrator.get_repo_manifest.return_value = None
    orchestrator.start_managed_repositories.return_value = {"niblit-lean-algos": {"pid": 123, "state": "running"}}
    attempts = iter([False, True])
    monkeypatch.setattr(client, "_refresh", lambda *args: next(attempts))
    monkeypatch.setattr(module, "get_multi_repo_orchestrator", lambda: orchestrator)
    asyncio.run(client.start())
    asyncio.run(client.stop())
    orchestrator.boot.assert_called_once()
    orchestrator.stop_managed_repositories.assert_called_once_with(["niblit-lean-algos"])


def test_trading_client_reports_actual_service_identity(monkeypatch):
    from modules import trading_runtime_client as module
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps({
        "healthy": True, "state": "ready", "backend": "paper", "mode": "observe", "execution_enabled": False,
    }).encode()
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: response)
    client = TradingRuntimeClient()
    assert client._refresh(True)
    assert client.backend == "paper"
    assert client.state == "ready"
    assert client.execution_mode == "observe"
    assert not client.execution_enabled


def test_supervisor_attaches_to_healthy_service_without_spawning(monkeypatch):
    from modules import multi_repo_orchestrator as module
    supervisor = RepositorySupervisor(bus=None, correlation_id="test")
    manifest = SimpleNamespace(name="niblit-cloud-server", present=True, compatible=True, bootstrap_contract={}, error=None)
    monkeypatch.setattr(supervisor, "_existing_service_ready", lambda _: True)
    spawn = Mock(side_effect=AssertionError("must not spawn an attached service"))
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    state = supervisor.start(manifest)
    assert state.state == "running"
    assert state.pid is None
    assert supervisor.check_health(manifest).last_health_status == "healthy"
    supervisor.stop(manifest)
    spawn.assert_not_called()


@pytest.mark.parametrize("health,expected", [("healthy", "success"), ("degraded", "degraded")])
def test_final_bootstrap_does_not_treat_degraded_health_as_ready(monkeypatch, health, expected):
    import main
    from modules import multi_repo_orchestrator as module
    manager = Mock()
    manager.get_runtime_services.return_value = {"service_count": 1}
    manager.get_runtime_health.return_value = {"status": health}
    core = SimpleNamespace(runtime_manager=manager, brain=object())
    orchestrator = Mock()
    orchestrator.start_managed_repositories.return_value = {"niblit-cloud-server": {"state": "running"}}
    monkeypatch.setattr(module, "get_multi_repo_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(main, "_BOOT_STATUS", main.BootStatus())
    emitter = Mock()
    monkeypatch.setattr(main, "_emit_lifecycle_event", emitter)
    report = main._run_staged_runtime_bootstrap(core, Mock())
    assert report["health_verification"]["status"] == expected
    assert emitter.call_args.args[:2] == ("runtime_ready", expected)
    orchestrator.boot.assert_not_called()
