"""Centralized project path resolution utilities."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_project_root() -> Path:
    """Return the repository root directory."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PROJECT_ROOT


def get_data_dir() -> Path:
    """Return the canonical data directory."""
    return resolve_path("data")


def get_memory_dir() -> Path:
    """Return the canonical memory directory."""
    return resolve_path("niblit_memory")


def resolve_path(*segments: str) -> Path:
    """Resolve one or more path segments under the project root."""
    return get_project_root().joinpath(*segments)


class EnvironmentResolutionError(ValueError):
    """A deployment binding is missing, changed, or outside its approved roots."""


def runtime_layout():
    """Independent resource roots; never derive an installation from the CWD."""
    frozen = bool(getattr(sys, "frozen", False))
    installation = get_project_root()
    return {"installation": installation,
            "bundle": Path(getattr(sys, "_MEIPASS", installation)).resolve(),
            "workspace": None if frozen else PROJECT_ROOT,
            "executable": Path(sys.executable).resolve()}


def _absolute(value):
    path = Path(value)
    if not path.is_absolute() or path == Path(path.anchor):
        raise EnvironmentResolutionError("Expected an absolute, non-root resource path")
    if os.name == "nt" and any(os.path.isreserved(part) for part in path.parts[1:]):
        raise EnvironmentResolutionError("Reserved Windows resource path")
    return path.resolve()


def _bounded(path, roots):
    # resolve() follows existing symlinks/junctions, including ancestor links of
    # a missing leaf. Lexical prefix matching would permit workspace escapes.
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in roots):
        raise EnvironmentResolutionError("Resource escapes approved roots")
    return path


def _approved_roots(data):
    roots = []
    for value in data["approved_roots"]:
        root = _absolute(value)
        if Path(value) != root:
            raise EnvironmentResolutionError("Approved root must not be redirected by a link or junction")
        roots.append(root)
    return roots


def _manifest():
    name = os.environ.get("NIBLIT_INSTALLATION_MANIFEST", "")
    pin = os.environ.get("NIBLIT_INSTALLATION_MANIFEST_SHA256", "").lower()
    if not name or len(pin) != 64:
        raise EnvironmentResolutionError("An explicit manifest and SHA256 trust pin are required")
    path = _absolute(name)
    if path.stat().st_size > 131072:
        raise EnvironmentResolutionError("Manifest exceeds size limit")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise EnvironmentResolutionError("Manifest trust pin mismatch")
    data = json.loads(raw)
    if data.get("schema_version") != "niblit-environment/1" or not data.get("installation_id"):
        raise EnvironmentResolutionError("Unsupported environment manifest")
    if not 1 <= len(data.get("approved_roots", [])) <= 16:
        raise EnvironmentResolutionError("Bounded approved roots required")
    if not 1 <= len(data.get("resources", {})) <= 32:
        raise EnvironmentResolutionError("Bounded resource inventory required")
    return data, pin


def _resource(spec, layout, roots):
    kind = spec.get("kind")
    value = spec.get("path", "")
    if kind == "service":
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or url.hostname not in
                {"127.0.0.1", "127.0.0.2", "localhost", "::1"} or
                url.username or url.password or url.query or url.fragment):
            raise EnvironmentResolutionError("Only credential-free configured loopback services are supported")
        return {"value": value, "status": "readiness_unverified", "kind": kind}
    if kind not in {"file", "directory", "executable", "sqlite", "model"}:
        raise EnvironmentResolutionError("Unsupported resource kind")
    base = spec.get("base", "absolute")
    if base == "absolute":
        path = _absolute(value)
    elif base in {"installation", "bundle"}:
        rel = Path(value)
        if not value or rel.is_absolute() or rel.drive or ".." in rel.parts or ":" in value:
            raise EnvironmentResolutionError("Invalid application-relative resource")
        if os.name == "nt" and any(os.path.isreserved(part) for part in rel.parts):
            raise EnvironmentResolutionError("Reserved Windows relative resource")
        path = _bounded(layout[base] / rel, [layout[base]])
    else:
        raise EnvironmentResolutionError("Unsupported resource base")
    path = _bounded(path, roots)
    if not path.exists():
        return {"value": str(path), "kind": kind, "status": "missing"}
    if (kind == "directory") != path.is_dir():
        raise EnvironmentResolutionError("Resource type mismatch")
    if kind == "executable":
        pin = spec.get("sha256", "").lower()
        if len(pin) != 64 or path.name.lower() != spec.get("filename", "").lower():
            raise EnvironmentResolutionError("Executable identity requires filename and SHA256")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != pin:
            raise EnvironmentResolutionError("Executable identity mismatch")
    if kind in {"sqlite", "model"}:
        expected = b"SQLite format 3\x00" if kind == "sqlite" else b"GGUF"
        with path.open("rb") as stream:
            if stream.read(len(expected)) != expected:
                raise EnvironmentResolutionError("Resource format mismatch")
    return {"value": str(path), "kind": kind, "status": "available"}


_BINDINGS = {"configuration": "NIBLIT_ENV_FILE", "memory": "NIBLIT_MEMORY_PATH",
             "ledger": "NIBLIT_MEMORY_LAB_LEDGER"}


def environment_plan():
    """Read-only reconstruction plan; no process launch, probe, install or store creation."""
    data, pin = _manifest()
    layout = runtime_layout()
    roots = _approved_roots(data)
    resources = {name: _resource(spec, layout, roots)
                 for name, spec in data["resources"].items()}
    blocked, repairs, approval = [], [], []
    for name, item in resources.items():
        spec = data["resources"][name]
        if name == "runtime_state" and not spec.get("disposable"):
            raise EnvironmentResolutionError("Runtime observations require an application-owned disposable directory")
        if spec.get("disposable"):
            if (name not in {"cache", "logs", "runtime_state"} or item["kind"] != "directory"
                    or spec.get("base", "absolute") != "absolute"):
                raise EnvironmentResolutionError("Only explicit disposable runtime directories may be created")
            path = Path(item["value"])
            if path.is_relative_to(layout["installation"]):
                raise EnvironmentResolutionError("Runtime repair must not modify the installation")
            for other_name, other in resources.items():
                if other_name != name and other["kind"] != "service":
                    other_path = Path(other["value"])
                    if path == other_path or other_path.is_relative_to(path) or path.is_relative_to(other_path):
                        raise EnvironmentResolutionError("Disposable directory contains another bound resource")
        if item["status"] == "missing":
            if spec.get("disposable"):
                repairs.append(name)
            else:
                approval.append({"resource": name, "action": "restore or reconfigure explicitly; no automatic installation"})
                if spec.get("required", False):
                    blocked.append(name)
    for name, expected_kind in {"configuration": "file", "memory": "file", "ledger": "sqlite"}.items():
        item = resources.get(name)
        if not item or item["kind"] != expected_kind or item["status"] != "available":
            blocked.append(name)
        elif os.environ.get(_BINDINGS[name]) and _absolute(os.environ[_BINDINGS[name]]) != Path(item["value"]):
            raise EnvironmentResolutionError("Existing persistent configuration conflicts with manifest")
    return {"schema_version": "niblit-environment-plan/1", "installation_id": data["installation_id"],
            "manifest_sha256": pin, "installation": str(layout["installation"]),
            "bundle": str(layout["bundle"]), "workspace": str(layout["workspace"]) if layout["workspace"] else None,
            "resources": resources, "blocked": sorted(set(blocked)), "safe_repairs": repairs,
            "approval_required": approval, "paths_ready": not blocked,
            "service_readiness": "not_probed", "execution_authorized": False}


def apply_environment():
    """Apply only validated process bindings and disposable-directory repair.

    The pinned operator manifest is immutable. No automatic credential edits,
    persistent-store creation, service startup or remembered-path substitution.
    """
    plan = environment_plan()
    if not plan["paths_ready"]:
        raise EnvironmentResolutionError("Required resources unavailable: " + ", ".join(plan["blocked"]))
    for name in plan["safe_repairs"]:
        Path(plan["resources"][name]["value"]).mkdir(parents=True, exist_ok=True)
    # Revalidate after directory creation, before publishing process bindings.
    plan = environment_plan()
    state_dir = plan["resources"].get("runtime_state", {})
    if state_dir.get("kind") == "directory" and state_dir.get("status") == "available":
        state = Path(state_dir["value"]) / "environment-observation.json"
        previous = None
        if state.exists():
            if state.is_symlink() or state.resolve().parent != state.parent.resolve() or state.stat().st_size > 131072:
                raise EnvironmentResolutionError("Unsafe environment observation file")
            raw = state.read_bytes()
            previous = json.loads(raw)
            if previous.get("installation_id") != plan["installation_id"]:
                raise EnvironmentResolutionError("Environment observation belongs to another installation")
            backup = state.with_name("environment-observation." + hashlib.sha256(raw).hexdigest() + ".json")
            if not backup.exists():
                if len(list(state.parent.glob("environment-observation.*.json"))) >= 32:
                    raise EnvironmentResolutionError("Observation backup limit reached; operator review required")
                with backup.open("xb") as stream:
                    stream.write(raw)
        plan["relocated"] = bool(previous and previous.get("installation") != plan["installation"])
        # Observations never supply resource bindings. A moved application must
        # still pass the immutable pinned manifest on every startup.
        payload = {key: plan[key] for key in ("schema_version", "installation_id", "installation", "manifest_sha256")}
        fd, temporary = tempfile.mkstemp(prefix="environment-", suffix=".tmp", dir=state.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, state)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    for name, variable in _BINDINGS.items():
        os.environ[variable] = plan["resources"][name]["value"]
    return plan


def guard_persistent_resource(name, path):
    """Reject rebinding or disappearance of a store in manifest-enabled runtimes."""
    if not os.environ.get("NIBLIT_INSTALLATION_MANIFEST"):
        return False
    data, _ = _manifest()
    spec = data["resources"].get(name)
    if not spec or spec.get("kind") != {"memory": "file", "configuration": "file", "ledger": "sqlite"}.get(name):
        raise EnvironmentResolutionError("Persistent resource not bound")
    item = _resource(spec, runtime_layout(), _approved_roots(data))
    if item["status"] != "available" or _absolute(path) != Path(item["value"]):
        raise EnvironmentResolutionError("Persistent resource unavailable or rebound")
    return True


def restore_environment_observation(backup):
    """Explicit metadata-only rollback. Never restores databases or configuration."""
    plan = environment_plan()
    if not plan["paths_ready"]:
        raise EnvironmentResolutionError("Cannot roll back metadata with unavailable required resources")
    state_dir = plan["resources"].get("runtime_state", {})
    if state_dir.get("status") != "available":
        raise EnvironmentResolutionError("Runtime observation directory unavailable")
    directory = Path(state_dir["value"])
    source = _absolute(backup)
    if source.parent != directory or source.stat().st_size > 131072:
        raise EnvironmentResolutionError("Invalid metadata rollback source")
    raw = source.read_bytes()
    expected = "environment-observation." + hashlib.sha256(raw).hexdigest() + ".json"
    payload = json.loads(raw)
    if source.name != expected or payload.get("installation_id") != plan["installation_id"] or payload.get("manifest_sha256") != plan["manifest_sha256"]:
        raise EnvironmentResolutionError("Metadata rollback identity mismatch")
    target = directory / "environment-observation.json"
    fd, temporary = tempfile.mkstemp(prefix="rollback-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

