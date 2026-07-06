#!/usr/bin/env python3
"""Niblit Multi-Repository Runtime Orchestrator.

Implements the Unified Multi-Repository Runtime Architecture where Niblit is the
single authoritative startup entry point and orchestrates the full ecosystem.

Architecture
------------
The runtime is organised into eight layers (0–7).  Each layer reports its status
through the unified Event Bus so every status transition is observable.

    Layer 0 — RuntimeManager
    Layer 1 — FoundationArchitecture
    Layer 2 — Unified Event Bus
    Layer 3 — Memory · Knowledge · Understanding
    Layer 4 — LocalBrain · ALE · Reflection · Governance
    Layer 5 — Trading · Research · Internet · Automation
    Layer 6 — Cloud Services        (niblit-cloud-server)
    Layer 7 — GUI                   (niblit-ui)

Layers 0–5 are satisfied by modules already present in this repository.
Layers 6 and 7 are resolved by discovering the sibling repositories at startup.

Managed Repositories
--------------------
* niblit-ui           — Layer 7: Runtime Dashboard and all GUI surfaces.
* niblit-cloud-server — Layer 6: Distributed runtime, remote API, synchronisation.
* niblit-lean-algos   — Layer 5 (trading sub-layer): Quantitative execution, market data.

Layer Status Model
------------------
Each layer transitions through:
    ``initialized`` → the layer is online and fully ready.
    ``degraded``    → the layer started but with reduced capability.
    ``failed``      → the layer could not start; downstream layers may still boot.
    ``retrying``    → a transient failure was detected and the layer is being retried.

Missing managed repositories degrade their layer rather than halting the boot.

Usage
-----
    from modules.multi_repo_orchestrator import MultiRepoOrchestrator

    orchestrator = MultiRepoOrchestrator()
    report = orchestrator.boot()
    print(report["runtime_status"])   # "ready" | "degraded" | "failed"
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("Niblit.MultiRepoOrchestrator")

# ── Constants ──────────────────────────────────────────────────────────────────

SOURCE_REPOSITORY = "niblit"

# Names of the three managed sibling repositories.
MANAGED_REPOS: tuple[str, ...] = (
    "niblit-ui",
    "niblit-cloud-server",
    "niblit-lean-algos",
)

# Maps a managed repository to the boot layer it contributes to.
REPO_LAYER_MAP: dict[str, int] = {
    "niblit-ui": 7,
    "niblit-cloud-server": 6,
    "niblit-lean-algos": 5,
}

# Environment variable overrides for repository root paths.
REPO_PATH_ENV: dict[str, str] = {
    "niblit-ui": "NIBLIT_UI_ROOT",
    "niblit-cloud-server": "NIBLIT_CLOUD_SERVER_ROOT",
    "niblit-lean-algos": "NIBLIT_LEAN_ALGOS_ROOT",
}

# Maximum retries for a layer before it is marked failed.
MAX_LAYER_RETRIES = 2


# ── Enumerations ───────────────────────────────────────────────────────────────

class LayerStatus(str, Enum):
    """Observable status states reported through the Event Bus for every layer."""

    PENDING = "pending"
    INITIALIZED = "initialized"
    DEGRADED = "degraded"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class RepositoryManifest:
    """Describes a discovered managed repository."""

    name: str
    root: Path
    layer: int
    present: bool = False
    availability_state: str = "unavailable"
    compatible: bool = False
    services: list[str] = field(default_factory=list)
    extension_points: list[str] = field(default_factory=list)
    bootstrap_contract: dict[str, Any] = field(default_factory=dict)
    runtime_maps: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["root"] = str(self.root)
        return out


@dataclass
class BootLayer:
    """Represents one layer of the deterministic boot sequence."""

    layer_id: int
    name: str
    components: list[str]
    status: LayerStatus = LayerStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    retry_count: int = 0
    error: str = ""
    managed_repo: str = ""

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000.0
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["status"] = self.status.value
        out["duration_ms"] = self.duration_ms
        return out


@dataclass
class ManagedRepoProcessState:
    """Lifecycle status for a supervised managed repository process."""

    repo_name: str
    state: str = "unavailable"
    pid: int = 0
    restart_count: int = 0
    last_health_status: str = "unknown"
    diagnostics_source: str = "core.runtime_manager"
    message: str = ""
    started_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Repository discovery ───────────────────────────────────────────────────────

class RepositoryDiscovery:
    """Locates and validates managed sibling repositories.

    Search order for each repository (first match wins):
    1. Environment variable override (e.g. ``NIBLIT_UI_ROOT``).
    2. Sibling directory of the Niblit repository root.
    3. Parent's parent directory (workspace roots in common CI layouts).
    """

    def __init__(self, niblit_root: Path) -> None:
        self._root = niblit_root

    # ── public API ─────────────────────────────────────────────────────────────

    def discover_all(self) -> dict[str, RepositoryManifest]:
        """Return a manifest for every managed repository."""
        manifests: dict[str, RepositoryManifest] = {}
        for repo_name in MANAGED_REPOS:
            manifests[repo_name] = self.discover(repo_name)
        return manifests

    def discover(self, repo_name: str) -> RepositoryManifest:
        """Discover and validate a single managed repository."""
        layer = REPO_LAYER_MAP.get(repo_name, 5)
        manifest = RepositoryManifest(
            name=repo_name,
            root=Path("."),
            layer=layer,
        )

        candidate = self._locate(repo_name)
        if candidate is None:
            manifest.error = f"Repository not found: {repo_name}"
            manifest.availability_state = "unavailable"
            manifest.bootstrap_contract = self._build_bootstrap_contract(repo_name, None)
            manifest.runtime_maps = self._build_runtime_maps(repo_name, root=None, present=False)
            log.debug("[Discovery] %s — not found", repo_name)
            return manifest

        manifest.root = candidate
        manifest.present = True
        manifest.compatible = self._validate(candidate, repo_name)
        manifest.availability_state = "available" if manifest.compatible else "incompatible"
        manifest.services = self._detect_services(candidate, repo_name)
        manifest.extension_points = self._detect_extension_points(candidate, repo_name)
        manifest.bootstrap_contract = self._build_bootstrap_contract(repo_name, candidate)
        manifest.runtime_maps = self._build_runtime_maps(repo_name, root=candidate, present=True)

        if not manifest.compatible:
            manifest.error = f"Compatibility check failed for {repo_name}"

        log.info(
            "[Discovery] %s — present=%s compatible=%s services=%s",
            repo_name,
            manifest.present,
            manifest.compatible,
            manifest.services,
        )
        return manifest

    # ── private helpers ────────────────────────────────────────────────────────

    def _locate(self, repo_name: str) -> Path | None:
        # 1. Explicit env override.
        env_var = REPO_PATH_ENV.get(repo_name, "")
        if env_var:
            override = os.environ.get(env_var, "").strip()
            if override:
                p = Path(override)
                if p.is_dir():
                    return p.resolve()

        # 2. Bundled sub-directory (niblit-lean-algos lives inside this repo).
        bundled = self._root / repo_name
        if bundled.is_dir():
            return bundled.resolve()

        # 3. Sibling of Niblit root.
        sibling = self._root.parent / repo_name
        if sibling.is_dir():
            return sibling.resolve()

        # 4. Workspace-level sibling (one level higher).
        workspace_sibling = self._root.parent.parent / repo_name
        if workspace_sibling.is_dir():
            return workspace_sibling.resolve()

        return None

    def _validate(self, root: Path, repo_name: str) -> bool:
        """Return True if the repository looks structurally compatible."""
        if repo_name == "niblit-lean-algos":
            # Must have lean.json or algorithms directory.
            return (root / "lean.json").exists() or (root / "algorithms").is_dir()
        if repo_name == "niblit-cloud-server":
            # Must have package.json or requirements.txt or server entry point.
            return any(
                (root / f).exists()
                for f in ("package.json", "requirements.txt", "server.py", "app.py", "index.js")
            )
        if repo_name == "niblit-ui":
            # Must have package.json or index.html or src directory.
            return any(
                (root / f).exists()
                for f in ("package.json", "index.html", "src")
            )
        return True

    def _detect_services(self, root: Path, repo_name: str) -> list[str]:
        services: list[str] = []
        if repo_name == "niblit-lean-algos":
            if (root / "algorithms").is_dir():
                services.append("algorithm_execution")
            if (root / "niblit_bridge").is_dir():
                services.append("niblit_bridge")
            if (root / "scripts").is_dir():
                services.append("lean_scripts")
        elif repo_name == "niblit-cloud-server":
            services.append("remote_api")
            services.append("synchronisation")
            if (root / "workers").is_dir():
                services.append("distributed_workers")
        elif repo_name == "niblit-ui":
            services.append("runtime_dashboard")
            services.append("event_bus_inspector")
            if (root / "src").is_dir():
                services.append("component_library")
        return services

    def _detect_extension_points(self, root: Path, repo_name: str) -> list[str]:
        ext: list[str] = []
        if repo_name == "niblit-lean-algos":
            ext.append("trading.signal.consumer")
            ext.append("trading.result.producer")
        elif repo_name == "niblit-cloud-server":
            ext.append("runtime.remote_event_bus")
            ext.append("runtime.sync_bridge")
        elif repo_name == "niblit-ui":
            ext.append("ui.runtime_consumer")
            ext.append("ui.event_bus_subscriber")
        return ext

    def _build_bootstrap_contract(self, repo_name: str, root: Path | None) -> dict[str, Any]:
        startup_commands: list[str] = []
        health_check: dict[str, Any] = {"kind": "probe", "checks": []}
        required_env: list[str] = []
        diagnostics_source = "core.runtime_manager"

        if repo_name == "niblit-cloud-server":
            startup_commands = ["python app.py", "python server.py", "npm run start"]
            health_check["checks"] = ["http_endpoint", "process_alive"]
            required_env = ["NIBLIT_CLOUD_SERVER_ROOT"]
        elif repo_name == "niblit-ui":
            # Prefer Tauri when src-tauri/tauri.conf.json is present; fall back to
            # plain Vite dev-server so the contract works without Tauri installed.
            tauri_conf = (root / "src-tauri" / "tauri.conf.json") if root is not None else None
            if tauri_conf is not None and tauri_conf.is_file():
                startup_commands = ["npm run tauri:dev", "npm run dev", "npm start"]
            else:
                startup_commands = ["npm run tauri:dev", "npm run dev", "npm start"]
            health_check["checks"] = ["http_endpoint", "process_alive"]
            required_env = ["NIBLIT_UI_ROOT"]
        elif repo_name == "niblit-lean-algos":
            startup_commands = ["python -m niblit_bridge", "python scripts/run.py"]
            health_check["checks"] = ["bridge_ready", "process_alive"]
            required_env = ["NIBLIT_LEAN_ALGOS_ROOT"]

        checks = health_check.get("checks", [])
        if root is None:
            checks = [*checks, "repository_present"]
        return {
            "startup_commands": startup_commands,
            "health_check": {"kind": health_check.get("kind", "probe"), "checks": checks},
            "shutdown_contract": {"method": "graceful_signal", "grace_period_seconds": 15},
            "required_env": required_env,
            "required_config": ["repository_root"],
            "event_channels": {
                "publish": [f"repo.{repo_name}.status", f"repo.{repo_name}.diagnostics"],
                "subscribe": ["runtime.ready", "runtime.system.stopping"],
            },
            "ownership": {
                "lifecycle_owner": SOURCE_REPOSITORY,
                "startup_owner": "orchestrator",
                "shutdown_owner": "orchestrator",
                "restart_policy": {"mode": "on_failure", "max_restarts": 2},
                "diagnostics_source": diagnostics_source,
            },
            "native_startup_untouched": True,
        }

    def _build_runtime_maps(
        self,
        repo_name: str,
        *,
        root: Path | None,
        present: bool,
    ) -> dict[str, Any]:
        unknown = "unknown"
        unavailable = "unavailable"
        if not present or root is None:
            return {
                "directory_module_dependencies": unavailable,
                "startup_lifecycle": unavailable,
                "config_env": unavailable,
                "event_channels": unavailable,
                "threading_process_ownership": unavailable,
                "persistence_state_paths": unavailable,
                "shutdown_ordering": unavailable,
                "nodes": {"status": unavailable, "repo": repo_name},
            }

        files = {p.name for p in root.iterdir()} if root.exists() else set()
        deps: list[str] = []
        if "package.json" in files:
            deps.append("nodejs")
        if "requirements.txt" in files or "pyproject.toml" in files:
            deps.append("python")
        if not deps:
            deps.append(unknown)

        startup_commands = self._build_bootstrap_contract(repo_name, root).get("startup_commands", [])
        return {
            "directory_module_dependencies": {
                "root": str(root),
                "dependencies": deps,
                "detected_modules": sorted(list(files))[:30],
            },
            "startup_lifecycle": {
                "startup_commands": startup_commands,
                "lifecycle_owner": SOURCE_REPOSITORY,
                "runtime_state": "discovered",
            },
            "config_env": {
                "required_env": REPO_PATH_ENV.get(repo_name, ""),
                "detected_env_files": [name for name in (".env", ".env.example") if name in files] or [unknown],
            },
            "event_channels": {
                "publish": [f"repo.{repo_name}.status"],
                "subscribe": ["runtime.ready", "runtime.system.stopping"],
            },
            "threading_process_ownership": {
                "owner": SOURCE_REPOSITORY,
                "supervision": "managed",
            },
            "persistence_state_paths": {
                "paths": [str(root / "runtime"), str(root / "logs")],
                "status": "derived",
            },
            "shutdown_ordering": {
                "order_hint": "after_core_before_eventbus_stop",
                "grace_period_seconds": 15,
            },
            "nodes": {
                "status": "available",
                "repo": repo_name,
            },
        }


# ── Event bus helpers ──────────────────────────────────────────────────────────

def _get_event_bus() -> Any | None:
    """Return the process-level module event bus, or None if unavailable."""
    try:
        from modules.event_bus import get_event_bus  # type: ignore[import]
        return get_event_bus()
    except Exception:
        return None


def _publish_layer_event(
    bus: Any | None,
    event_type: str,
    layer: BootLayer,
    *,
    correlation_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Publish a layer status event through the module event bus."""
    if bus is None:
        return
    try:
        from modules.event_bus import NiblitEvent  # type: ignore[import]
        payload: dict[str, Any] = {
            "layer_id": layer.layer_id,
            "layer_name": layer.name,
            "status": layer.status.value,
            "components": layer.components,
            "duration_ms": layer.duration_ms,
            "retry_count": layer.retry_count,
            "managed_repo": layer.managed_repo,
            "error": layer.error,
            "correlation_id": correlation_id,
            "source_repository": SOURCE_REPOSITORY,
            "timestamp": time.time(),
        }
        if extra:
            payload.update(extra)
        event = NiblitEvent(
            type=event_type,
            source="multi_repo_orchestrator",
            payload=payload,
        )
        bus.publish(event)
    except Exception as exc:
        log.debug("[Orchestrator] event bus publish failed: %s", exc)


def _publish_repo_event(
    bus: Any | None,
    event_type: str,
    manifest: RepositoryManifest,
    *,
    correlation_id: str = "",
) -> None:
    """Publish a repository discovery event through the module event bus."""
    if bus is None:
        return
    try:
        from modules.event_bus import NiblitEvent  # type: ignore[import]
        payload: dict[str, Any] = {
            "repo_name": manifest.name,
            "repo_root": str(manifest.root),
            "layer": manifest.layer,
            "present": manifest.present,
            "availability_state": manifest.availability_state,
            "compatible": manifest.compatible,
            "services": manifest.services,
            "extension_points": manifest.extension_points,
            "bootstrap_contract": manifest.bootstrap_contract,
            "runtime_maps": manifest.runtime_maps,
            "error": manifest.error,
            "correlation_id": correlation_id,
            "source_repository": SOURCE_REPOSITORY,
            "timestamp": time.time(),
        }
        event = NiblitEvent(
            type=event_type,
            source="multi_repo_orchestrator",
            payload=payload,
        )
        bus.publish(event)
    except Exception as exc:
        log.debug("[Orchestrator] repo event publish failed: %s", exc)


# ── Managed repository supervision ─────────────────────────────────────────────

class RepositorySupervisor:
    """Best-effort process supervision for managed repositories."""

    def __init__(self, *, bus: Any | None, correlation_id: str) -> None:
        self._bus = bus
        self._correlation_id = correlation_id
        self._lock = threading.RLock()
        self._states: dict[str, ManagedRepoProcessState] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}

    def register(self, manifest: RepositoryManifest) -> ManagedRepoProcessState:
        with self._lock:
            state = self._states.get(manifest.name) or ManagedRepoProcessState(repo_name=manifest.name)
            if not manifest.present:
                state.state = "unavailable"
                state.message = manifest.error or "repository unavailable"
                state.last_health_status = "unavailable"
            elif not manifest.compatible:
                state.state = "degraded"
                state.message = manifest.error or "repository incompatible"
                state.last_health_status = "degraded"
            else:
                state.state = "registered"
                state.last_health_status = "unknown"
                state.message = "registered for supervision"
            ownership = dict(manifest.bootstrap_contract.get("ownership", {}) or {})
            state.diagnostics_source = str(ownership.get("diagnostics_source", "core.runtime_manager"))
            self._states[manifest.name] = state
        self._publish("repo.supervision.registered", manifest, state=state.state, message=state.message)
        return state

    def start(self, manifest: RepositoryManifest) -> ManagedRepoProcessState:
        # Guard: if a healthy process is already running for this repo, skip re-launch.
        with self._lock:
            existing = self._states.get(manifest.name)
            if existing is not None and existing.state == "running":
                proc = self._processes.get(manifest.name)
                if proc is not None and proc.poll() is None:
                    log.debug(
                        "[Supervisor] %s already running (pid=%s) — skipping duplicate start",
                        manifest.name,
                        existing.pid,
                    )
                    return existing
        state = self.register(manifest)
        if state.state in {"unavailable", "degraded"}:
            return state
        commands = list(manifest.bootstrap_contract.get("startup_commands", []) or [])
        if not commands:
            state.state = "degraded"
            state.message = "no startup commands declared"
            self._publish("repo.supervision.degraded", manifest, state=state.state, message=state.message)
            return state
        command = commands[0]
        try:
            process = subprocess.Popen(  # noqa: S603
                shlex.split(command),
                cwd=str(manifest.root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._processes[manifest.name] = process
                state.state = "running"
                state.pid = int(process.pid or 0)
                state.started_at = time.time()
                state.last_health_status = "healthy"
                state.message = f"started: {command}"
            self._publish("repo.supervision.started", manifest, state=state.state, pid=state.pid)
            return state
        except Exception as exc:
            state.state = "degraded"
            state.message = f"start failed: {exc}"
            state.last_health_status = "degraded"
            self._publish("repo.supervision.degraded", manifest, state=state.state, message=state.message)
            return state

    def check_health(self, manifest: RepositoryManifest) -> ManagedRepoProcessState:
        with self._lock:
            state = self._states.get(manifest.name) or ManagedRepoProcessState(repo_name=manifest.name)
            proc = self._processes.get(manifest.name)
        if proc is None:
            state.last_health_status = "unknown" if manifest.present else "unavailable"
            return state
        if proc.poll() is None:
            state.last_health_status = "healthy"
            return state
        state.last_health_status = "failed"
        ownership = dict(manifest.bootstrap_contract.get("ownership", {}) or {})
        restart_policy = dict(ownership.get("restart_policy", {}) or {})
        max_restarts = int(restart_policy.get("max_restarts", 0))
        if state.restart_count < max_restarts:
            state.restart_count += 1
            self._publish(
                "repo.supervision.restarting",
                manifest,
                state="restarting",
                restart_count=state.restart_count,
            )
            return self.start(manifest)
        state.state = "failed"
        state.message = "process exited and restart limit reached"
        self._publish("repo.supervision.failed", manifest, state=state.state, message=state.message)
        return state

    def stop(self, manifest: RepositoryManifest) -> ManagedRepoProcessState:
        with self._lock:
            state = self._states.get(manifest.name) or ManagedRepoProcessState(repo_name=manifest.name)
            proc = self._processes.pop(manifest.name, None)
        if proc is None:
            state.state = "stopped" if manifest.present else "unavailable"
            return state
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        state.state = "stopped"
        state.last_health_status = "stopped"
        state.message = "gracefully stopped"
        self._publish("repo.supervision.stopped", manifest, state=state.state)
        return state

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {name: state.to_dict() for name, state in self._states.items()}

    def _publish(self, event_type: str, manifest: RepositoryManifest, **extra: Any) -> None:
        if self._bus is None:
            return
        try:
            from modules.event_bus import NiblitEvent  # type: ignore[import]

            payload = {
                "repo_name": manifest.name,
                "repo_root": str(manifest.root),
                "correlation_id": self._correlation_id,
                "source_repository": SOURCE_REPOSITORY,
                "timestamp": time.time(),
            }
            payload.update(extra)
            self._bus.publish(NiblitEvent(type=event_type, source="multi_repo_orchestrator", payload=payload))
        except Exception:
            return


# ── Boot layers definition ─────────────────────────────────────────────────────

def _build_boot_layers() -> list[BootLayer]:
    """Return the canonical ordered list of boot layers."""
    return [
        BootLayer(
            layer_id=0,
            name="RuntimeManager",
            components=["RuntimeManager", "EventBus", "TaskQueue", "Orchestrator"],
        ),
        BootLayer(
            layer_id=1,
            name="FoundationArchitecture",
            components=["FoundationArchitecture", "CognitiveFeedbackLoop", "ProvenanceGraph"],
        ),
        BootLayer(
            layer_id=2,
            name="UnifiedEventBus",
            components=["CoreEventBus", "ModuleEventBus", "EventBridges", "CorrelationEngine"],
        ),
        BootLayer(
            layer_id=3,
            name="MemoryKnowledgeUnderstanding",
            components=["PersistenceManager", "KnowledgeDB", "MemorySystem", "UnderstandingLayer"],
        ),
        BootLayer(
            layer_id=4,
            name="CognitionCore",
            components=["LocalBrain", "ALE", "ReflectionEngine", "GovernanceEngine"],
        ),
        BootLayer(
            layer_id=5,
            name="DomainServices",
            components=[
                "TradingBrain", "SelfResearcher", "InternetManager",
                "AutoResearcher", "SelfIdeaImplementation",
            ],
        ),
        BootLayer(
            layer_id=6,
            name="CloudLayer",
            components=["RemoteAPI", "Synchronisation", "DistributedWorkers", "RemoteEventBus"],
            managed_repo="niblit-cloud-server",
        ),
        BootLayer(
            layer_id=7,
            name="GUILayer",
            components=[
                "RuntimeDashboard", "CognitiveVisualisation", "EventBusInspector",
                "MarketDashboard", "TradingDashboard",
            ],
            managed_repo="niblit-ui",
        ),
    ]


# ── Main orchestrator ──────────────────────────────────────────────────────────

class MultiRepoOrchestrator:
    """Single authoritative startup orchestrator for the Niblit ecosystem.

    Niblit must always start from this orchestrator.  It owns the deterministic
    7-layer boot sequence, repository discovery, Event Bus registration, and
    lifecycle management for all managed repositories.

    Parameters
    ----------
    niblit_root:
        Explicit path to the Niblit repository root.  Auto-detected when ``None``.
    event_bus:
        Inject a custom event bus (useful in tests).  The process-level
        module bus is used when ``None``.
    """

    def __init__(
        self,
        niblit_root: Path | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._root = niblit_root or self._detect_root()
        self._bus = event_bus  # may be None; resolved lazily if not injected
        self._discovery = RepositoryDiscovery(self._root)
        self._layers = _build_boot_layers()
        self._manifests: dict[str, RepositoryManifest] = {}
        self._correlation_id = f"boot-{uuid.uuid4().hex[:12]}"
        self._boot_start: float = 0.0
        self._boot_end: float = 0.0
        self._runtime_status: str = "pending"
        self._supervisor: RepositorySupervisor | None = None

    # ── public API ─────────────────────────────────────────────────────────────

    def boot(self) -> dict[str, Any]:
        """Execute the deterministic 8-layer boot sequence (Layers 0–7).

        Returns
        -------
        dict
            Structured boot report with keys:
            ``runtime_status``, ``layers``, ``repositories``, ``duration_ms``.
        """
        self._boot_start = time.time()
        log.info("[MultiRepoOrchestrator] boot sequence started (correlation=%s)", self._correlation_id)

        bus = self._bus or _get_event_bus()
        self._supervisor = RepositorySupervisor(bus=bus, correlation_id=self._correlation_id)

        # Repository discovery
        self._manifests = self._discovery.discover_all()
        for repo_name, manifest in self._manifests.items():
            event_type = "repo.discovered" if manifest.present else "repo.unavailable"
            _publish_repo_event(bus, event_type, manifest, correlation_id=self._correlation_id)
            if self._supervisor is not None:
                self._supervisor.register(manifest)
            level = log.info if manifest.present else log.warning
            level("[MultiRepoOrchestrator] repo=%s present=%s compatible=%s", repo_name, manifest.present, manifest.compatible)

        # Execute each layer in order
        all_initialized = True
        for layer in self._layers:
            self._boot_layer(layer, bus=bus)
            if layer.status == LayerStatus.FAILED:
                all_initialized = False
            elif layer.status == LayerStatus.DEGRADED:
                all_initialized = False

        self._boot_end = time.time()
        self._runtime_status = "ready" if all_initialized else "degraded"

        # Publish runtime.ready event
        _publish_runtime_ready(bus, self._runtime_status, self._correlation_id, self._layers)

        report = self.get_runtime_status()
        log.info(
            "[MultiRepoOrchestrator] boot complete status=%s duration_ms=%.1f",
            self._runtime_status,
            (self._boot_end - self._boot_start) * 1000.0,
        )
        return report

    def get_runtime_status(self) -> dict[str, Any]:
        """Return a structured snapshot of the current runtime state."""
        return {
            "runtime_status": self._runtime_status,
            "correlation_id": self._correlation_id,
            "niblit_root": str(self._root),
            "boot_start": self._boot_start,
            "boot_end": self._boot_end,
            "duration_ms": (self._boot_end - self._boot_start) * 1000.0 if self._boot_end else 0.0,
            "layers": [layer.to_dict() for layer in self._layers],
            "repositories": {name: m.to_dict() for name, m in self._manifests.items()},
            "managed_services": self.get_supervision_status(),
        }

    def get_layer(self, layer_id: int) -> BootLayer | None:
        """Return the BootLayer for a given layer ID, or None."""
        for layer in self._layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    def get_repo_manifest(self, repo_name: str) -> RepositoryManifest | None:
        """Return the discovered manifest for a managed repository, or None."""
        return self._manifests.get(repo_name)

    def start_managed_repositories(self, repo_names: list[str] | None = None) -> dict[str, Any]:
        """Start selected managed repositories under supervision."""
        if self._supervisor is None:
            return {}
        selected = repo_names or list(self._manifests.keys())
        result: dict[str, Any] = {}
        for repo_name in selected:
            manifest = self._manifests.get(repo_name)
            if manifest is None:
                continue
            result[repo_name] = self._supervisor.start(manifest).to_dict()
        return result

    def monitor_managed_repositories(self) -> dict[str, Any]:
        """Run one health-check pass over all supervised repositories."""
        if self._supervisor is None:
            return {}
        out: dict[str, Any] = {}
        for repo_name, manifest in self._manifests.items():
            out[repo_name] = self._supervisor.check_health(manifest).to_dict()
        return out

    def stop_managed_repositories(self) -> dict[str, Any]:
        """Gracefully stop all supervised managed repositories."""
        if self._supervisor is None:
            return {}
        out: dict[str, Any] = {}
        for repo_name, manifest in self._manifests.items():
            out[repo_name] = self._supervisor.stop(manifest).to_dict()
        return out

    def get_supervision_status(self) -> dict[str, Any]:
        if self._supervisor is None:
            return {}
        return self._supervisor.snapshot()

    # ── layer execution ────────────────────────────────────────────────────────

    def _boot_layer(self, layer: BootLayer, *, bus: Any | None) -> None:
        """Initialise one boot layer, reporting status through the Event Bus."""
        layer.start_time = time.time()

        if layer.managed_repo:
            self._boot_managed_repo_layer(layer, bus=bus)
        else:
            self._boot_internal_layer(layer, bus=bus)

        layer.end_time = time.time()
        _publish_layer_event(
            bus,
            f"layer.{layer.status.value}",
            layer,
            correlation_id=self._correlation_id,
        )

    def _boot_internal_layer(self, layer: BootLayer, *, bus: Any | None) -> None:
        """Boot an internal Niblit layer (Layers 0–5)."""
        try:
            ok, msg = self._probe_internal_layer(layer)
            if ok:
                layer.status = LayerStatus.INITIALIZED
                log.info("[Layer %d] %s — initialized", layer.layer_id, layer.name)
            else:
                layer.status = LayerStatus.DEGRADED
                layer.error = msg
                log.warning("[Layer %d] %s — degraded: %s", layer.layer_id, layer.name, msg)
        except Exception as exc:
            layer.status = LayerStatus.FAILED
            layer.error = str(exc)
            log.error("[Layer %d] %s — failed: %s", layer.layer_id, layer.name, exc)

    def _boot_managed_repo_layer(self, layer: BootLayer, *, bus: Any | None) -> None:
        """Boot a layer backed by a managed external repository (Layers 6–7)."""
        repo_name = layer.managed_repo
        manifest = self._manifests.get(repo_name)

        if manifest is None or not manifest.present:
            layer.status = LayerStatus.DEGRADED
            layer.error = f"{repo_name} not found — layer degraded gracefully"
            log.warning("[Layer %d] %s — %s", layer.layer_id, layer.name, layer.error)
            return

        if not manifest.compatible:
            layer.status = LayerStatus.DEGRADED
            layer.error = f"{repo_name} compatibility check failed"
            log.warning("[Layer %d] %s — %s", layer.layer_id, layer.name, layer.error)
            return

        # Register services and extension points from the managed repo.
        self._register_repo_services(manifest, bus=bus)
        if self._supervisor is not None:
            self._supervisor.register(manifest)

        layer.status = LayerStatus.INITIALIZED
        log.info(
            "[Layer %d] %s — initialized (repo=%s services=%s)",
            layer.layer_id,
            layer.name,
            repo_name,
            manifest.services,
        )

    def _probe_internal_layer(self, layer: BootLayer) -> tuple[bool, str]:
        """Probe whether an internal layer's key components are importable."""
        probe_map: dict[int, list[str]] = {
            0: ["core.runtime_manager"],
            1: ["modules.foundation_architecture"],
            2: ["core.event_bus", "modules.event_bus"],
            3: ["modules.knowledge_db"],
            4: ["modules.local_brain"],
            5: ["modules.trading_brain"],
        }
        modules_to_check = probe_map.get(layer.layer_id, [])
        failed: list[str] = []
        for mod in modules_to_check:
            if mod not in sys.modules:
                try:
                    import importlib
                    importlib.import_module(mod)
                except Exception as exc:
                    failed.append(f"{mod}: {exc}")
        if failed:
            return False, "; ".join(failed)
        return True, ""

    def _register_repo_services(
        self, manifest: RepositoryManifest, *, bus: Any | None
    ) -> None:
        """Register Event Bus endpoints and extension points for a managed repo."""
        if bus is None:
            return
        try:
            from modules.event_bus import NiblitEvent  # type: ignore[import]
            payload: dict[str, Any] = {
                "repo_name": manifest.name,
                "layer": manifest.layer,
                "services": manifest.services,
                "extension_points": manifest.extension_points,
                "repo_root": str(manifest.root),
                "bootstrap_contract": manifest.bootstrap_contract,
                "runtime_maps": manifest.runtime_maps,
                "correlation_id": self._correlation_id,
                "source_repository": SOURCE_REPOSITORY,
                "timestamp": time.time(),
            }
            bus.publish(NiblitEvent(
                type="repo.registered",
                source="multi_repo_orchestrator",
                payload=payload,
            ))
        except Exception as exc:
            log.debug("[Orchestrator] service registration event failed: %s", exc)

    # ── utility ────────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_root() -> Path:
        """Detect the Niblit repository root from the call stack."""
        # Prefer the location of this module file.
        this_file = Path(__file__).resolve()
        candidate = this_file.parent.parent  # modules/ → repo root
        if (candidate / "niblit_core.py").exists():
            return candidate
        return this_file.parent.parent


# ── runtime.ready publisher ────────────────────────────────────────────────────

def _publish_runtime_ready(
    bus: Any | None,
    runtime_status: str,
    correlation_id: str,
    layers: list[BootLayer],
) -> None:
    if bus is None:
        return
    try:
        from modules.event_bus import NiblitEvent  # type: ignore[import]
        payload: dict[str, Any] = {
            "runtime_status": runtime_status,
            "correlation_id": correlation_id,
            "layer_summary": {
                layer.name: layer.status.value for layer in layers
            },
            "lineage_channel": "orchestrator.runtime_ready",
            "source_repository": SOURCE_REPOSITORY,
            "timestamp": time.time(),
        }
        bus.publish(NiblitEvent(
            type="runtime.ready",
            source="multi_repo_orchestrator",
            payload=payload,
        ))
    except Exception as exc:
        log.debug("[Orchestrator] runtime.ready publish failed: %s", exc)


# ── module-level singleton ─────────────────────────────────────────────────────

_ORCHESTRATOR: MultiRepoOrchestrator | None = None


def get_multi_repo_orchestrator(
    niblit_root: Path | None = None,
    event_bus: Any | None = None,
) -> MultiRepoOrchestrator:
    """Return the process-level MultiRepoOrchestrator singleton.

    Creates and caches the instance on first call.  Pass *niblit_root* or
    *event_bus* only on the first call; subsequent calls ignore them.
    """
    global _ORCHESTRATOR  # noqa: PLW0603
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = MultiRepoOrchestrator(niblit_root=niblit_root, event_bus=event_bus)
    return _ORCHESTRATOR
