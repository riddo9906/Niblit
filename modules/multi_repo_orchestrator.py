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
import sys
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
    compatible: bool = False
    services: list[str] = field(default_factory=list)
    extension_points: list[str] = field(default_factory=list)
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
            log.debug("[Discovery] %s — not found", repo_name)
            return manifest

        manifest.root = candidate
        manifest.present = True
        manifest.compatible = self._validate(candidate, repo_name)
        manifest.services = self._detect_services(candidate, repo_name)
        manifest.extension_points = self._detect_extension_points(candidate, repo_name)

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
            "compatible": manifest.compatible,
            "services": manifest.services,
            "extension_points": manifest.extension_points,
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

        # Repository discovery
        self._manifests = self._discovery.discover_all()
        for repo_name, manifest in self._manifests.items():
            event_type = "repo.discovered" if manifest.present else "repo.unavailable"
            _publish_repo_event(bus, event_type, manifest, correlation_id=self._correlation_id)
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
