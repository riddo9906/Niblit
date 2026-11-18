"""Source-level relocation acceptance; never starts Core, MT5 or inference."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def profile(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("relocation_paths", SOURCE / "niblit_core/config/paths.py")
    paths = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(paths)
    install = tmp_path / "installation"
    external = tmp_path / "external"
    install.mkdir()
    external.mkdir()
    (external / "config.env").write_text("NIBLIT_TRADING_MODE=observe\n")
    (external / "memory.json").write_text("{}")
    db = sqlite3.connect(external / "ledger.sqlite3")
    try:
        db.execute("create table evidence(id text)")
        db.commit()
    finally:
        db.close()
    binary = install / "niblit-ui.exe"
    binary.write_bytes(b"controlled fixture; never executed")
    data = {"schema_version": "niblit-environment/1", "installation_id": "test-only",
            "approved_roots": [str(tmp_path)], "resources": {
                "configuration": {"kind": "file", "path": str(external / "config.env")},
                "memory": {"kind": "file", "path": str(external / "memory.json")},
                "ledger": {"kind": "sqlite", "path": str(external / "ledger.sqlite3")},
                "ui": {"kind": "executable", "base": "installation", "path": "niblit-ui.exe",
                       "filename": "niblit-ui.exe", "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "required": True},
                "runtime_state": {"kind": "directory", "path": str(tmp_path / "state"), "disposable": True},
                "cloud": {"kind": "service", "path": "http://127.0.0.1:8000"}}}
    monkeypatch.setattr(paths, "PROJECT_ROOT", install)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    for key in (*paths._BINDINGS.values(), "NIBLIT_INSTALLATION_MANIFEST_SHA256"):
        monkeypatch.delenv(key, raising=False)
    manifest = tmp_path / "deployment.json"

    def publish():
        manifest.write_text(json.dumps(data))
        monkeypatch.setenv("NIBLIT_INSTALLATION_MANIFEST", str(manifest))
        monkeypatch.setenv("NIBLIT_INSTALLATION_MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest())
    publish()
    return paths, data, publish, install, external


def test_plan_is_read_only_and_services_are_not_health_claims(profile, tmp_path):
    paths, _, _, _, _ = profile
    result = paths.environment_plan()
    assert result["paths_ready"] and not result["execution_authorized"]
    assert result["resources"]["cloud"]["status"] == "readiness_unverified"
    assert not (tmp_path / "state").exists()


def test_cwd_independent_and_external_bindings_preserved(profile, monkeypatch, tmp_path):
    paths, _, _, install, external = profile
    monkeypatch.chdir(external)
    result = paths.apply_environment()
    assert result["installation"] == str(install)
    assert Path(os.environ["NIBLIT_MEMORY_PATH"]) == external / "memory.json"
    assert not (install / "memory.json").exists()
    assert (tmp_path / "state/environment-observation.json").exists()


def test_same_drive_relocation_detected_and_old_state_preserved(profile, tmp_path, monkeypatch):
    paths, _, _, install, external = profile
    paths.apply_environment()
    moved = tmp_path / "moved"
    install.rename(moved)
    monkeypatch.setattr(paths, "PROJECT_ROOT", moved)
    result = paths.apply_environment()
    assert result["relocated"]
    assert result["resources"]["memory"]["value"] == str(external / "memory.json")
    assert len(list((tmp_path / "state").glob("environment-observation.*.json"))) == 1


def test_frozen_install_and_bundle_are_independent(profile, monkeypatch, tmp_path):
    paths, _, _, install, _ = profile
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "niblit.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "extracted"), raising=False)
    assert paths.runtime_layout()["installation"] == install
    assert paths.runtime_layout()["bundle"] == tmp_path / "extracted"
    assert paths.runtime_layout()["workspace"] is None


@pytest.mark.parametrize("name", ["memory", "ledger", "configuration"])
def test_missing_persistence_blocks_without_replacement(profile, name, tmp_path):
    paths, data, _, _, _ = profile
    path = Path(data["resources"][name]["path"])
    path.unlink()
    with pytest.raises(paths.EnvironmentResolutionError):
        paths.apply_environment()
    assert not path.exists() and not (tmp_path / "state").exists()


def test_optional_dependency_generates_plan_not_installation(profile):
    paths, data, publish, _, external = profile
    data["resources"]["optional"] = {"kind": "file", "path": str(external / "missing")}
    publish()
    result = paths.environment_plan()
    assert result["paths_ready"]
    assert result["approval_required"][0]["resource"] == "optional"
    assert not (external / "missing").exists()


def test_manifest_pin_rejects_tampering(profile):
    paths, _, _, _, _ = profile
    Path(os.environ["NIBLIT_INSTALLATION_MANIFEST"]).write_text("{}")
    with pytest.raises(paths.EnvironmentResolutionError, match="pin mismatch"):
        paths.environment_plan()


def test_executable_substitution_rejected(profile):
    paths, _, _, install, _ = profile
    (install / "niblit-ui.exe").write_bytes(b"replacement")
    with pytest.raises(paths.EnvironmentResolutionError, match="identity mismatch"):
        paths.environment_plan()


@pytest.mark.parametrize("value", ["../evil.exe", "C:relative.exe", "http://host/evil.exe"])
def test_misleading_application_paths_rejected(profile, value):
    paths, data, publish, _, _ = profile
    data["resources"]["ui"]["path"] = value
    publish()
    with pytest.raises(paths.EnvironmentResolutionError):
        paths.environment_plan()


def test_root_escape_rejected(profile, tmp_path):
    paths, data, publish, _, _ = profile
    data["approved_roots"] = [str(tmp_path / "other")]
    publish()
    with pytest.raises(paths.EnvironmentResolutionError, match="escapes"):
        paths.environment_plan()


def test_conflicting_existing_memory_binding_rejected(profile, monkeypatch, tmp_path):
    paths, _, _, _, _ = profile
    monkeypatch.setenv("NIBLIT_MEMORY_PATH", str(tmp_path / "different.json"))
    with pytest.raises(paths.EnvironmentResolutionError, match="conflicts"):
        paths.environment_plan()


def test_persistent_guard_rejects_disappearance_and_rebinding(profile, tmp_path):
    paths, _, _, _, external = profile
    assert paths.guard_persistent_resource("memory", external / "memory.json")
    with pytest.raises(paths.EnvironmentResolutionError):
        paths.guard_persistent_resource("memory", tmp_path / "new.json")
    (external / "memory.json").unlink()
    with pytest.raises(paths.EnvironmentResolutionError):
        paths.guard_persistent_resource("memory", external / "memory.json")


def test_disposable_directory_cannot_enclose_memory(profile):
    paths, data, publish, _, external = profile
    data["resources"]["runtime_state"]["path"] = str(external)
    publish()
    with pytest.raises(paths.EnvironmentResolutionError, match="contains"):
        paths.environment_plan()


def test_symlink_escape(profile, tmp_path):
    paths, data, publish, install, _ = profile
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    link = install / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation privilege unavailable; junction test covers Windows")
    data["resources"]["optional"] = {"kind": "file", "base": "installation", "path": "linked/missing"}
    publish()
    with pytest.raises(paths.EnvironmentResolutionError):
        paths.environment_plan()


def test_legacy_resolution_remains_unchanged_without_manifest(profile, monkeypatch):
    paths, _, _, install, _ = profile
    monkeypatch.delenv("NIBLIT_INSTALLATION_MANIFEST")
    assert paths.resolve_path("data") == install / "data"
    assert not paths.guard_persistent_resource("memory", "not-used")


def test_metadata_rollback_does_not_change_persistent_bindings(profile, tmp_path, monkeypatch):
    paths, _, _, install, external = profile
    paths.apply_environment()
    moved = tmp_path / "relocated"
    install.rename(moved)
    monkeypatch.setattr(paths, "PROJECT_ROOT", moved)
    paths.apply_environment()
    backup = next((tmp_path / "state").glob("environment-observation.*.json"))
    original_memory = (external / "memory.json").read_bytes()
    paths.restore_environment_observation(backup)
    state = json.loads((tmp_path / "state/environment-observation.json").read_text())
    assert state["installation"] == str(install)
    assert paths.environment_plan()["installation"] == str(moved)
    assert (external / "memory.json").read_bytes() == original_memory


@pytest.mark.parametrize("url", ["http://example.com", "http://user:secret@localhost:8000", "file:///C:/models", "http://localhost:8000?token=private"])
def test_unapproved_or_secret_bearing_service_rejected(profile, url):
    paths, data, publish, _, _ = profile
    data["resources"]["cloud"]["path"] = url
    publish()
    with pytest.raises(paths.EnvironmentResolutionError):
        paths.environment_plan()


def test_junction_escape_windows(profile, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction test")
    import subprocess
    paths, data, publish, install, _ = profile
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    link = install / "linked"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    data["resources"]["optional"] = {"kind": "file", "base": "installation", "path": "linked/missing"}
    publish()
    try:
        with pytest.raises(paths.EnvironmentResolutionError):
            paths.environment_plan()
    finally:
        # Remove only this test-created empty junction, never its target.
        os.rmdir(link)


def test_bootstrap_calls_profile_before_changing_working_directory(profile, monkeypatch):
    from modules import runtime_bootstrap
    paths, _, _, install, external = profile
    import niblit_core.config.paths as runtime_paths
    calls = []
    monkeypatch.setattr(runtime_paths, "apply_environment", lambda: calls.append(os.getcwd()))
    monkeypatch.setattr(runtime_bootstrap, "_find_repo_root", lambda start: install)
    monkeypatch.chdir(external)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert runtime_bootstrap.bootstrap_runtime_environment(install) == install
    assert calls == [str(external)]
    assert Path.cwd() == install


def test_source_bootstrap_cross_drive_subprocess(profile, monkeypatch, tmp_path):
    import subprocess
    import tempfile
    paths, data, publish, install, external = profile
    c_root = os.environ.get("NIBLIT_TEST_C_ROOT")
    if os.name != "nt" or not c_root or Path(c_root).drive == install.drive:
        pytest.skip("Explicit second-drive test root not supplied")
    Path(c_root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-c-fixture-", dir=c_root) as temporary:
        other_drive = Path(temporary)
        for name in ("config.env", "memory.json", "ledger.sqlite3"):
            (other_drive / name).write_bytes((external / name).read_bytes())
        data["approved_roots"].append(str(other_drive))
        for resource, filename in (("configuration", "config.env"), ("memory", "memory.json"), ("ledger", "ledger.sqlite3")):
            data["resources"][resource]["path"] = str(other_drive / filename)
        publish()
        script = ("import sys,json,os; from pathlib import Path; "
                  "from modules.runtime_bootstrap import bootstrap_runtime_environment; "
                  f"sys.frozen=True; sys.executable={str(install / 'niblit.exe')!r}; "
                  "root=bootstrap_runtime_environment(); "
                  "print(json.dumps({'installation':str(root),'memory':os.environ['NIBLIT_MEMORY_PATH']}))")
        env = dict(os.environ, PYTHONPATH=str(SOURCE), PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=other_drive, env=env,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        observed = json.loads(result.stdout)
        assert observed["installation"] == str(install)
        assert Path(observed["memory"]).drive != install.drive
        assert not (install / "memory.json").exists()


def test_cloud_autostart_is_suppressed_in_manifest_profile(profile, monkeypatch):
    from modules import niblit_ui_launcher as launcher
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected service launch"))
    messages = []
    assert launcher._maybe_start_cloud_server("http://127.0.0.1:8000", messages.append) is None
    assert "ownership" in messages[0]


def test_real_memory_gateway_refuses_missing_bound_ledger(profile):
    from modules.memory_laboratory.gateway import MemoryGateway
    from modules.memory_laboratory.setup import Config
    from types import SimpleNamespace
    paths, _, _, _, external = profile
    paths.apply_environment()
    ledger = external / "ledger.sqlite3"
    backend = SimpleNamespace(embedder=object(), close=lambda: None)
    gateway = MemoryGateway(Config(url="http://127.0.0.1:6333"), ledger,
                            setup=backend, authorize=lambda *args: True)
    gateway.close()
    ledger.unlink()
    with pytest.raises(ValueError, match="unavailable"):
        with gateway.db():
            pytest.fail("missing ledger opened")
    assert not ledger.exists()
    with pytest.raises(ValueError, match="unavailable"):
        MemoryGateway(Config(url="http://127.0.0.1:6333"), ledger, setup=backend)
    assert not ledger.exists()
