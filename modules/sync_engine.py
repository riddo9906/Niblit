#!/usr/bin/env python3
"""
modules/sync_engine.py — Niblit Local ↔ Cloud Sync Protocol (LCSP v1)
======================================================================
*Offline-first, resumable, kernel-integrated sync.*

This module implements the full LCSP v1 spec described in the Niblit
architecture docs.  Highlights:

* **Artifact model** — everything that can be synced is a
  :class:`SyncArtifact` (memory, code, model, log, slsa, agent, event).
* **Offline queue** — changes are appended to a JSONL file and survive
  process restarts.  When connectivity is restored the queue drains
  automatically.
* **Hash-based diffing** — :class:`ChangeDetector` computes SHA-256 over
  the serialised artifact content so identical payloads are never
  re-sent.
* **Smart filtering** — :func:`should_sync` gates on priority threshold
  and artifact type so ephemeral / temp artifacts are never uploaded.
* **Conflict resolution** — three-layer strategy (timestamp priority →
  MWDS weight → synthesizer text merge).
* **Sync modes** — ``realtime``, ``batch``, ``lazy``, ``offline``
  (configurable via ``NIBLIT_SYNC_MODE`` env var).
* **Kernel feedback** — after every successful sync cycle the result is
  written back into :class:`~modules.niblit_core_kernel.KernelMemory`
  (or v2) so the rest of the cognitive pipeline is aware.
* **Device tagging** — every artifact is stamped with
  ``NIBLIT_DEVICE_ID`` (default: ``"local_device"``) so multi-device
  merges can be traced.

Transport
---------
The default :class:`RESTTransport` uses stdlib ``urllib`` and sends JSON
payloads to a configurable cloud endpoint (``NIBLIT_SYNC_ENDPOINT``).
No third-party HTTP library is required; the transport degrades to
*offline* mode when the endpoint is not set or is unreachable.

Integration points
------------------
* Called by ``niblit_core._init_optional_services()`` and started as a
  background thread in ``_start_sync_loops()``.
* ``SyncEngine.collect_artifacts()`` pulls eligible records from the
  MWDS :class:`~modules.memory_weighting.MemoryStore` (``sync_eligible``
  items) and from any registered :attr:`artifact_providers`.
* After each sync, ``SyncEngine.feedback_to_kernel()`` stores a compact
  event in the kernel memory.

Singleton
---------
``get_sync_engine()`` returns the process-wide :class:`SyncEngine`.

Configuration (environment variables)
--------------------------------------
``NIBLIT_SYNC_MODE``       — realtime | batch | lazy | offline (default: lazy)
``NIBLIT_SYNC_INTERVAL``   — seconds between batch/lazy cycles (default: 300)
``NIBLIT_SYNC_ENDPOINT``   — base URL of cloud REST API (default: "")
``NIBLIT_SYNC_API_TOKEN``  — bearer token for cloud auth (default: "")
``NIBLIT_SYNC_QUEUE_PATH`` — path to offline queue JSONL file
``NIBLIT_DEVICE_ID``       — identifier for this device (default: local_device)
``NIBLIT_SYNC_MIN_PRIORITY``— minimum artifact priority to sync (default: 0.3)
``NIBLIT_SYNC_MAX_BATCH``  — max artifacts per sync cycle (default: 50)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_SYNC_MODE = os.environ.get("NIBLIT_SYNC_MODE", "lazy").lower()
_SYNC_INTERVAL = float(os.environ.get("NIBLIT_SYNC_INTERVAL", "300"))
_SYNC_ENDPOINT = os.environ.get("NIBLIT_SYNC_ENDPOINT", "").rstrip("/")
_SYNC_API_TOKEN = os.environ.get("NIBLIT_SYNC_API_TOKEN", "")
_SYNC_QUEUE_PATH = os.environ.get(
    "NIBLIT_SYNC_QUEUE_PATH",
    str(Path.home() / ".niblit" / "sync_queue.jsonl"),
)
_DEVICE_ID = os.environ.get("NIBLIT_DEVICE_ID", "local_device")
_MIN_PRIORITY = float(os.environ.get("NIBLIT_SYNC_MIN_PRIORITY", "0.3"))
_MAX_BATCH = int(os.environ.get("NIBLIT_SYNC_MAX_BATCH", "50"))

# Artifact type constants
ARTIFACT_TYPES = frozenset({
    "memory", "code", "model", "log", "slsa", "agent", "event",
})

# Sync state constants
SYNC_STATE_PENDING = "pending"
SYNC_STATE_SYNCED = "synced"
SYNC_STATE_CONFLICT = "conflict"
SYNC_STATE_FAILED = "failed"

# Sync mode constants
SYNC_MODE_REALTIME = "realtime"
SYNC_MODE_BATCH = "batch"
SYNC_MODE_LAZY = "lazy"
SYNC_MODE_OFFLINE = "offline"


# ═════════════════════════════════════════════════════════════════════════════
# Sync Artifact
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SyncArtifact:
    """A unit of data that can be synced between local and cloud.

    Attributes
    ----------
    id:            Unique artifact identifier (UUID if not set).
    type:          Artifact category (``"memory"``, ``"code"``, ``"slsa"``, …).
    content:       Serialisable dict holding the payload.
    version:       Monotonically increasing integer (incremented on each edit).
    hash:          SHA-256 of the serialised *content* (computed by
                   :class:`ChangeDetector`).
    created_at:    UNIX timestamp of first creation.
    updated_at:    UNIX timestamp of last modification.
    source:        ``"local"`` or ``"cloud"`` — origin of this artifact.
    priority:      Float in ``[0, 1]``; higher = more important to sync.
    sync_state:    ``"pending"``, ``"synced"``, ``"conflict"``, or ``"failed"``.
    origin_device: Device ID that created this artifact.
    weight:        MWDS survival weight (if available); used for conflict resolution.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "memory"
    content: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    hash: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source: str = "local"
    priority: float = 0.5
    sync_state: str = SYNC_STATE_PENDING
    origin_device: str = field(default_factory=lambda: _DEVICE_ID)
    weight: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SyncArtifact":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def update_hash(self) -> None:
        """Recompute the SHA-256 content hash in-place."""
        raw = json.dumps(self.content, sort_keys=True, default=str)
        self.hash = hashlib.sha256(raw.encode()).hexdigest()

    def mark_synced(self) -> None:
        self.sync_state = SYNC_STATE_SYNCED
        self.updated_at = time.time()

    def mark_failed(self) -> None:
        self.sync_state = SYNC_STATE_FAILED
        self.updated_at = time.time()


# ═════════════════════════════════════════════════════════════════════════════
# Sync Queue (JSONL persistence)
# ═════════════════════════════════════════════════════════════════════════════

class SyncQueue:
    """Persistent offline queue backed by a JSONL file.

    Artifacts are appended to the JSONL file immediately on ``push()``.
    When connectivity is restored, ``drain()`` returns the pending items
    and ``commit_drained()`` removes them from disk atomically.

    Thread-safe.

    Args:
        queue_path: Path to the JSONL file (created on first use).
    """

    def __init__(self, queue_path: str = _SYNC_QUEUE_PATH) -> None:
        self._path = Path(queue_path)
        self._lock = threading.Lock()
        self._in_memory: List[SyncArtifact] = []
        self._load()

    def _load(self) -> None:
        """Load persisted artifacts from the JSONL file."""
        if not self._path.exists():
            return
        with self._lock:
            try:
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        self._in_memory.append(SyncArtifact.from_dict(d))
                    except Exception:
                        pass
                log.debug("[SyncQueue] Loaded %d pending artifacts", len(self._in_memory))
            except Exception as exc:
                log.debug("[SyncQueue] load failed: %s", exc)

    def push(self, artifact: SyncArtifact) -> None:
        """Append *artifact* to the queue and persist it."""
        with self._lock:
            self._in_memory.append(artifact)
            self._append_to_disk(artifact)

    def _append_to_disk(self, artifact: SyncArtifact) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(artifact.to_dict(), default=str) + "\n")
        except Exception as exc:
            log.debug("[SyncQueue] persist failed: %s", exc)

    def drain(self, max_items: int = _MAX_BATCH) -> List[SyncArtifact]:
        """Return up to *max_items* pending artifacts (does NOT remove them yet)."""
        with self._lock:
            return list(self._in_memory[:max_items])

    def commit_drained(self, count: int) -> None:
        """Remove the first *count* items from the queue and rewrite disk."""
        with self._lock:
            self._in_memory = self._in_memory[count:]
            self._rewrite_disk()

    def _rewrite_disk(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lines = [
                json.dumps(a.to_dict(), default=str)
                for a in self._in_memory
            ]
            self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        except Exception as exc:
            log.debug("[SyncQueue] rewrite failed: %s", exc)

    def size(self) -> int:
        with self._lock:
            return len(self._in_memory)

    def clear(self) -> None:
        with self._lock:
            self._in_memory.clear()
            try:
                self._path.unlink(missing_ok=True)
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════════════
# Change Detector
# ═════════════════════════════════════════════════════════════════════════════

class ChangeDetector:
    """Hash-based artifact change detection.

    Maintains an in-memory registry of ``artifact_id → content_hash`` so
    that unchanged artifacts are never re-queued.

    Args:
        hasher: Callable that accepts a dict and returns a hex-digest string.
                Defaults to SHA-256 of the JSON-serialised content.
    """

    def __init__(self, hasher: Optional[Callable[[Dict[str, Any]], str]] = None) -> None:
        self._hasher = hasher or self._default_hash
        self._registry: Dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _default_hash(content: Dict[str, Any]) -> str:
        raw = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def compute(self, content: Dict[str, Any]) -> str:
        """Compute and return a hash string for *content*."""
        return self._hasher(content)

    def has_changed(self, artifact_id: str, content: Dict[str, Any]) -> bool:
        """Return True if *content* differs from the last-seen hash.

        Also updates the registry with the new hash.

        Args:
            artifact_id: Unique identifier for the artifact.
            content:     Current artifact content dict.

        Returns:
            True if the content has changed since the last call.
        """
        new_hash = self._hasher(content)
        with self._lock:
            old_hash = self._registry.get(artifact_id)
            changed = (old_hash != new_hash)
            self._registry[artifact_id] = new_hash
        return changed

    def mark_seen(self, artifact_id: str, content_hash: str) -> None:
        """Manually register a hash without doing a comparison."""
        with self._lock:
            self._registry[artifact_id] = content_hash

    def forget(self, artifact_id: str) -> None:
        """Remove *artifact_id* from the registry (forces re-check next time)."""
        with self._lock:
            self._registry.pop(artifact_id, None)

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._registry)


# ═════════════════════════════════════════════════════════════════════════════
# Conflict Resolver
# ═════════════════════════════════════════════════════════════════════════════

class ConflictResolver:
    """Three-layer conflict resolution for concurrent local + cloud edits.

    Resolution hierarchy:

    1. **Timestamp** — most recently updated artifact wins.
    2. **MWDS weight** — higher adaptive survival weight wins.
    3. **Text merge** — PatternSynthesizer produces a merged summary.

    Args:
        weight_tolerance: Score difference below which timestamp is used
                          instead of weight comparison (default 0.05).
    """

    def __init__(self, weight_tolerance: float = 0.05) -> None:
        self._tol = weight_tolerance

    def resolve(
        self,
        local: SyncArtifact,
        remote: SyncArtifact,
    ) -> Tuple[SyncArtifact, str]:
        """Return ``(winner, reason)`` for a local vs. remote conflict.

        Args:
            local:  The local version of the artifact.
            remote: The remote (cloud) version.

        Returns:
            A tuple of ``(winning_artifact, reason_string)``.
        """
        # Layer 1 — Timestamp
        ts_diff = abs(local.updated_at - remote.updated_at)
        if ts_diff > 1.0:
            if local.updated_at > remote.updated_at:
                return local, "timestamp:local_newer"
            return remote, "timestamp:remote_newer"

        # Layer 2 — MWDS weight
        w_diff = local.weight - remote.weight
        if abs(w_diff) > self._tol:
            if w_diff > 0:
                return local, "weight:local_heavier"
            return remote, "weight:remote_heavier"

        # Layer 3 — Merge (synthesize a union of content)
        merged = self._merge(local, remote)
        return merged, "merge:synthesized"

    def _merge(
        self,
        local: SyncArtifact,
        remote: SyncArtifact,
    ) -> SyncArtifact:
        """Produce a merged artifact combining local and remote content.

        For dict payloads, remote keys overwrite local keys (remote is
        treated as more authoritative for shared keys).  Unique local keys
        are preserved.  A ``"_merged": true`` flag is injected.
        """
        merged_content: Dict[str, Any] = {**local.content}
        merged_content.update(remote.content)
        merged_content["_merged"] = True
        merged_content["_merge_sources"] = [local.origin_device, remote.origin_device]

        merged = SyncArtifact(
            id=local.id,
            type=local.type,
            content=merged_content,
            version=max(local.version, remote.version) + 1,
            source="local",
            priority=max(local.priority, remote.priority),
            sync_state=SYNC_STATE_PENDING,
            origin_device=_DEVICE_ID,
            weight=max(local.weight, remote.weight),
        )
        merged.update_hash()
        return merged


# ═════════════════════════════════════════════════════════════════════════════
# Transport Layer
# ═════════════════════════════════════════════════════════════════════════════

class RESTTransport:
    """Lightweight REST transport using stdlib urllib.

    Sends ``POST /sync/push`` and ``GET /sync/pull`` to a configurable
    endpoint.  Degrades gracefully to offline mode when the endpoint is
    empty or unreachable.

    Args:
        endpoint:    Base URL (e.g. ``"https://api.niblit.cloud"``).
        api_token:   Bearer token for ``Authorization`` header.
        timeout:     HTTP request timeout in seconds (default 15).
    """

    def __init__(
        self,
        endpoint: str = _SYNC_ENDPOINT,
        api_token: str = _SYNC_API_TOKEN,
        timeout: float = 15.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._token = api_token
        self._timeout = timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def push(self, artifacts: List[SyncArtifact]) -> bool:
        """Upload *artifacts* to the cloud endpoint.

        Args:
            artifacts: List of artifacts to push.

        Returns:
            True on success, False on failure or if endpoint not configured.
        """
        if not self._endpoint:
            return False
        url = f"{self._endpoint}/sync/push"
        payload = json.dumps(
            {"device_id": _DEVICE_ID, "artifacts": [a.to_dict() for a in artifacts]},
            default=str,
        ).encode()
        try:
            req = Request(url, data=payload, headers=self._headers(), method="POST")
            with urlopen(req, timeout=self._timeout) as resp:
                return resp.status == 200
        except URLError as exc:
            log.debug("[RESTTransport] push failed: %s", exc)
            return False
        except Exception as exc:
            log.debug("[RESTTransport] push error: %s", exc)
            return False

    def pull(self, since_ts: float = 0.0) -> List[SyncArtifact]:
        """Download artifacts from the cloud updated after *since_ts*.

        Args:
            since_ts: UNIX timestamp; only artifacts updated after this are returned.

        Returns:
            List of remote :class:`SyncArtifact` objects.
        """
        if not self._endpoint:
            return []
        url = f"{self._endpoint}/sync/pull?device_id={_DEVICE_ID}&since={since_ts}"
        try:
            req = Request(url, headers=self._headers(), method="GET")
            with urlopen(req, timeout=self._timeout) as resp:
                if resp.status != 200:
                    return []
                data = json.loads(resp.read().decode())
                raw_list = data.get("artifacts", [])
                return [SyncArtifact.from_dict(r) for r in raw_list if isinstance(r, dict)]
        except URLError as exc:
            log.debug("[RESTTransport] pull failed: %s", exc)
            return []
        except Exception as exc:
            log.debug("[RESTTransport] pull error: %s", exc)
            return []

    @property
    def configured(self) -> bool:
        """True if an endpoint URL has been set."""
        return bool(self._endpoint)


# ═════════════════════════════════════════════════════════════════════════════
# Filtering
# ═════════════════════════════════════════════════════════════════════════════

def should_sync(artifact: SyncArtifact, min_priority: float = _MIN_PRIORITY) -> bool:
    """Return True if *artifact* meets the criteria for synchronisation.

    Args:
        artifact:     The artifact to evaluate.
        min_priority: Minimum priority threshold (default ``_MIN_PRIORITY``).

    Returns:
        True when priority ≥ *min_priority* AND type is not ``"temp"``.
    """
    if artifact.type == "temp":
        return False
    return artifact.priority >= min_priority


# ═════════════════════════════════════════════════════════════════════════════
# Compression helper
# ═════════════════════════════════════════════════════════════════════════════

def compress_artifact(artifact: SyncArtifact) -> SyncArtifact:
    """Return a lightly compressed copy of *artifact*.

    For memory-type artifacts the content is summarised (text truncated;
    embeddings dropped).  For other types the content is returned as-is.
    Heavy compression (e.g. zlib) is not applied here so the result
    remains human-readable JSON.

    Args:
        artifact: Original artifact.

    Returns:
        A new :class:`SyncArtifact` with reduced-size content.
    """
    if artifact.type not in ("memory", "log"):
        return artifact

    content = dict(artifact.content)

    # Truncate long text fields
    for key in ("text", "summary", "content", "data", "value"):
        if key in content and isinstance(content[key], str) and len(content[key]) > 500:
            content[key] = content[key][:497] + "…"

    # Drop raw embedding vectors (they can be recomputed locally)
    content.pop("embedding", None)
    content.pop("embeddings", None)
    content["_compressed"] = True

    compressed = SyncArtifact(
        id=artifact.id,
        type=artifact.type,
        content=content,
        version=artifact.version,
        source=artifact.source,
        priority=artifact.priority,
        sync_state=artifact.sync_state,
        origin_device=artifact.origin_device,
        weight=artifact.weight,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )
    compressed.update_hash()
    return compressed


# ═════════════════════════════════════════════════════════════════════════════
# Sync Engine
# ═════════════════════════════════════════════════════════════════════════════

class SyncEngine:
    """Niblit Local ↔ Cloud Sync Engine (LCSP v1).

    Orchestrates the full sync pipeline:

    1. **Collect** eligible artifacts from MWDS and registered providers.
    2. **Detect** changes via SHA-256 diffing.
    3. **Compress** artifacts before transmission.
    4. **Queue** them in the persistent :class:`SyncQueue`.
    5. **Send** via :class:`RESTTransport` (or drop to offline).
    6. **Pull** remote updates and merge with :class:`ConflictResolver`.
    7. **Feedback** sync result into kernel memory.

    Sync modes (set via ``NIBLIT_SYNC_MODE``):

    * ``realtime``   — push immediately when an artifact is queued.
    * ``batch``      — run full cycle on a fixed interval.
    * ``lazy``       — run only when the background loop detects idle time.
    * ``offline``    — never push; accumulate queue for later.

    Args:
        mode:          Sync mode string (default: ``_SYNC_MODE``).
        interval:      Seconds between cycles in batch/lazy mode.
        transport:     Optional custom transport (defaults to :class:`RESTTransport`).
        queue:         Optional custom :class:`SyncQueue`.
        detector:      Optional :class:`ChangeDetector`.
        resolver:      Optional :class:`ConflictResolver`.
        kernel_memory: Optional :class:`~modules.niblit_core_kernel.KernelMemory`
                       for post-sync feedback.
        memory_store:  Optional MWDS :class:`~modules.memory_weighting.MemoryStore`
                       for pulling sync-eligible records.
    """

    def __init__(
        self,
        mode: str = _SYNC_MODE,
        interval: float = _SYNC_INTERVAL,
        transport: Optional[RESTTransport] = None,
        queue: Optional[SyncQueue] = None,
        detector: Optional[ChangeDetector] = None,
        resolver: Optional[ConflictResolver] = None,
        kernel_memory: Optional[Any] = None,
        memory_store: Optional[Any] = None,
    ) -> None:
        self.mode = mode.lower()
        self.interval = interval
        self.transport = transport or RESTTransport()
        self.queue = queue or SyncQueue()
        self.detector = detector or ChangeDetector()
        self.resolver = resolver or ConflictResolver()

        self._kernel_memory = kernel_memory
        self._memory_store = memory_store

        # Registered artifact providers (callables returning List[SyncArtifact])
        self._providers: List[Callable[[], List[SyncArtifact]]] = []

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._last_pull_ts: float = 0.0
        self._stats: Dict[str, int] = {
            "artifacts_queued": 0,
            "artifacts_pushed": 0,
            "artifacts_pulled": 0,
            "conflicts_resolved": 0,
            "cycles_completed": 0,
            "push_failures": 0,
        }

        log.info(
            "[SyncEngine] LCSP v1 initialised — mode=%s interval=%.0fs endpoint=%s",
            self.mode, self.interval, "configured" if self.transport.configured else "none",
        )

    # ── Provider registration ─────────────────────────────────────────────────

    def register_provider(self, provider: Callable[[], List[SyncArtifact]]) -> None:
        """Register a callable that returns artifacts to consider for sync.

        Args:
            provider: Zero-argument callable returning ``List[SyncArtifact]``.
        """
        with self._lock:
            self._providers.append(provider)

    # ── Artifact collection ───────────────────────────────────────────────────

    def collect_artifacts(self) -> List[SyncArtifact]:
        """Collect sync candidates from all registered providers and MWDS.

        Returns:
            Filtered list of :class:`SyncArtifact` ready for diffing.
        """
        candidates: List[SyncArtifact] = []

        # ── MWDS memory store ─────────────────────────────────────────────
        ms = self._memory_store
        if ms is None:
            try:
                from modules.memory_weighting import get_memory_store
                ms = get_memory_store()
                self._memory_store = ms
            except Exception:
                pass

        if ms is not None:
            try:
                eligible = ms.sync_eligible()
                for rec in eligible:
                    artifact = SyncArtifact(
                        id=getattr(rec, "record_id", str(uuid.uuid4())),
                        type="memory",
                        content={
                            "text": str(getattr(rec, "content", ""))[:500],
                            "importance": float(getattr(rec, "importance", 0.5)),
                            "source": str(getattr(rec, "source", "kernel")),
                        },
                        priority=float(getattr(rec, "importance", 0.5)),
                        weight=float(getattr(rec, "weight", 0.5)),
                        source="local",
                    )
                    artifact.update_hash()
                    candidates.append(artifact)
            except Exception as exc:
                log.debug("[SyncEngine] MWDS collect failed: %s", exc)

        # ── Registered providers ──────────────────────────────────────────
        with self._lock:
            providers = list(self._providers)
        for provider in providers:
            try:
                artifacts = provider()
                candidates.extend(artifacts)
            except Exception as exc:
                log.debug("[SyncEngine] provider collect failed: %s", exc)

        # ── Filter ────────────────────────────────────────────────────────
        filtered = [a for a in candidates if should_sync(a)]
        return filtered[:_MAX_BATCH]

    # ── Sync pipeline ─────────────────────────────────────────────────────────

    def queue_artifact(self, artifact: SyncArtifact) -> bool:
        """Enqueue a single artifact for sync.

        Runs the change-detect → compress → queue pipeline.  If mode is
        ``realtime`` and an endpoint is configured, also attempts an
        immediate push.

        Args:
            artifact: The artifact to queue.

        Returns:
            True if the artifact was newly queued (changed since last seen).
        """
        if not should_sync(artifact):
            return False
        if not self.detector.has_changed(artifact.id, artifact.content):
            return False

        compressed = compress_artifact(artifact)
        self.queue.push(compressed)
        with self._lock:
            self._stats["artifacts_queued"] += 1

        log.debug("[SyncEngine] Queued artifact %s (type=%s)", artifact.id[:8], artifact.type)

        if self.mode == SYNC_MODE_REALTIME:
            self._push_batch([compressed])

        return True

    def _push_batch(self, batch: List[SyncArtifact]) -> bool:
        """Push *batch* to the cloud transport.

        Args:
            batch: List of artifacts to push.

        Returns:
            True if push succeeded.
        """
        if not self.transport.configured:
            return False
        ok = self.transport.push(batch)
        with self._lock:
            if ok:
                self._stats["artifacts_pushed"] += len(batch)
                for a in batch:
                    a.mark_synced()
            else:
                self._stats["push_failures"] += 1
                for a in batch:
                    a.mark_failed()
        return ok

    def _pull_remote(self) -> List[SyncArtifact]:
        """Pull updates from cloud and merge conflicts.

        Returns:
            List of merged artifacts that should be written back locally.
        """
        remote_artifacts = self.transport.pull(since_ts=self._last_pull_ts)
        if not remote_artifacts:
            return []

        self._last_pull_ts = time.time()
        with self._lock:
            self._stats["artifacts_pulled"] += len(remote_artifacts)

        merged: List[SyncArtifact] = []
        for remote in remote_artifacts:
            # If we have a matching local entry, resolve conflict
            local_match = self._find_local(remote.id)
            if local_match is not None:
                winner, reason = self.resolver.resolve(local_match, remote)
                if reason.startswith("merge"):
                    with self._lock:
                        self._stats["conflicts_resolved"] += 1
                merged.append(winner)
                log.debug(
                    "[SyncEngine] Conflict %s resolved: %s", remote.id[:8], reason
                )
            else:
                merged.append(remote)

        return merged

    def _find_local(self, artifact_id: str) -> Optional[SyncArtifact]:
        """Find a local artifact by ID in the in-memory queue."""
        for a in self.queue.drain(max_items=200):
            if a.id == artifact_id:
                return a
        return None

    def run_cycle(self) -> Dict[str, Any]:
        """Run one full sync cycle.

        Pipeline: collect → diff → compress → queue → push → pull → merge

        Returns:
            Dict with cycle statistics.
        """
        t0 = time.time()
        log.debug("[SyncEngine] Starting sync cycle (mode=%s)", self.mode)

        # 1. Collect
        candidates = self.collect_artifacts()
        queued = 0
        for artifact in candidates:
            if self.queue_artifact(artifact):
                queued += 1

        # 2. Drain and push
        pushed = 0
        if self.mode != SYNC_MODE_OFFLINE:
            batch = self.queue.drain()
            if batch and self._push_batch(batch):
                self.queue.commit_drained(len(batch))
                pushed = len(batch)

        # 3. Pull remote updates
        merged = self._pull_remote()

        # 4. Feedback into kernel
        elapsed = time.time() - t0
        self.feedback_to_kernel(queued=queued, pushed=pushed, pulled=len(merged), latency_ms=elapsed * 1000)

        with self._lock:
            self._stats["cycles_completed"] += 1

        result = {
            "queued": queued,
            "pushed": pushed,
            "pulled": len(merged),
            "merged": [a.to_dict() for a in merged[:3]],
            "latency_ms": round(elapsed * 1000, 1),
        }
        log.info(
            "[SyncEngine] Cycle done — queued=%d pushed=%d pulled=%d latency=%.0fms",
            queued, pushed, len(merged), elapsed * 1000,
        )
        return result

    # ── Kernel feedback ───────────────────────────────────────────────────────

    def feedback_to_kernel(
        self,
        queued: int = 0,
        pushed: int = 0,
        pulled: int = 0,
        latency_ms: float = 0.0,
    ) -> None:
        """Write sync event into KernelMemory so cognition is aware.

        Tries the v2 kernel first, then falls back to v1.

        Args:
            queued:     Number of artifacts queued this cycle.
            pushed:     Number of artifacts pushed this cycle.
            pulled:     Number of artifacts pulled this cycle.
            latency_ms: Cycle wall-clock time.
        """
        event = {
            "event": "sync_completed",
            "artifacts_queued": queued,
            "artifacts_pushed": pushed,
            "artifacts_pulled": pulled,
            "latency_ms": round(latency_ms, 1),
            "ts": int(time.time()),
            "device_id": _DEVICE_ID,
        }
        km = self._kernel_memory
        if km is None:
            try:
                from modules.niblit_core_kernel import get_niblit_core_kernel
                km = get_niblit_core_kernel().memory
                self._kernel_memory = km
            except Exception:
                pass
        if km is not None:
            try:
                km.store(event, importance=0.4, source="sync_engine")
                return
            except Exception as exc:
                log.debug("[SyncEngine] kernel memory feedback failed: %s", exc)

        # V2 fallback
        try:
            from modules.niblit_core_kernel_v2 import get_niblit_core_kernel_v2
            get_niblit_core_kernel_v2().remember(event, importance=0.4)
        except Exception:
            pass

    # ── Background loop ───────────────────────────────────────────────────────

    def start_background_loop(self) -> threading.Thread:
        """Spawn a daemon thread running the sync loop.

        The thread checks :attr:`_stop_event` so ``stop()`` terminates it.
        Starting twice is a no-op while the loop thread is still alive.

        Returns:
            The started :class:`threading.Thread`.
        """
        existing = getattr(self, "_bg_thread", None)
        if existing is not None and existing.is_alive():
            log.debug("[SyncEngine] Background loop already running")
            return existing

        t = threading.Thread(
            target=self._background_loop,
            name="SyncEngineLoop",
            daemon=True,
        )
        t.start()
        self._bg_thread = t
        log.info("[SyncEngine] Background loop started (mode=%s)", self.mode)
        return t

    def _background_loop(self) -> None:
        """Main background sync loop."""
        while not self._stop_event.is_set():
            if self.mode == SYNC_MODE_OFFLINE:
                time.sleep(10)
                continue
            try:
                self.run_cycle()
            except Exception as exc:
                log.debug("[SyncEngine] cycle error: %s", exc)
            # Interruptible sleep
            elapsed = 0.0
            while elapsed < self.interval and not self._stop_event.is_set():
                time.sleep(min(5.0, self.interval - elapsed))
                elapsed += 5.0

    def stop(self) -> None:
        """Signal the background loop to stop."""
        self._stop_event.set()

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a snapshot of sync engine state."""
        with self._lock:
            stats = dict(self._stats)
        return {
            **stats,
            "mode": self.mode,
            "interval": self.interval,
            "queue_size": self.queue.size(),
            "endpoint_configured": self.transport.configured,
            "last_pull_ts": self._last_pull_ts,
            "device_id": _DEVICE_ID,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

_sync_engine: Optional[SyncEngine] = None
_sync_engine_lock = threading.Lock()


def get_sync_engine(**kwargs) -> SyncEngine:
    """Return the process-level :class:`SyncEngine` singleton.

    Thread-safe, lazily created on first call.  Any keyword arguments are
    forwarded to the constructor **only** on the first call.
    """
    global _sync_engine  # pylint: disable=global-statement
    with _sync_engine_lock:
        if _sync_engine is None:
            _sync_engine = SyncEngine(**kwargs)
        return _sync_engine


if __name__ == "__main__":
    print('Running sync_engine.py')
