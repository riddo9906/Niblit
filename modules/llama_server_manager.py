#!/usr/bin/env python3
"""
modules/llama_server_manager.py — Managed llama.cpp server for Niblit.

The LlamaServerManager owns the lifecycle of a single llama-server process.
It discovers GGUF model files in configured search directories, maintains a
model registry, and supports hot-switching the active model without restarting
the Niblit runtime.

Architecture position
---------------------
RuntimeManager
  └─ llama_server_manager  ← LlamaServerManager (this module)
       ├─ discovers models (scan configured directories for .gguf files)
       ├─ registers all discovered models in a local registry
       ├─ manages llama-server process lifecycle (start / stop / health)
       └─ notifies local_brain of URL/model changes after a switch

Boot behaviour
--------------
The manager does NOT start llama-server automatically on import or on service
registration.  The runtime calls ``start()`` explicitly when the user requests
local inference, or when ``NIBLIT_LLAMA_AUTOSTART=1`` is set in the
environment.

If an external llama-server is already listening at the configured URL the
manager adopts it (``adopt_external_server()``) and skips process management.

Dynamic model switching
-----------------------
llama-server loads exactly one model per process.  To switch models the
manager:

1. Acquires ``_MODEL_SWITCH_LOCK`` from :mod:`modules.local_brain` to prevent
   in-flight inference from being interrupted.
2. Terminates the running server process (or marks the adopted server as
   released).
3. Starts a fresh server process with the new model.
4. Notifies :mod:`modules.local_brain` of the new active URL so its HTTP
   backend resumes transparently.

Environment variables
---------------------
NIBLIT_LLAMA_SERVER_URL      Base URL of target llama-server
                             (default: ``http://127.0.0.1:8080``)
NIBLIT_LLAMA_BINARY_PATH     Path to the ``llama-server`` binary.
                             Auto-detected from common locations when unset.
NIBLIT_LLAMA_MODEL_DIRS      ``os.pathsep``-separated list of directories to
                             scan for ``.gguf`` files.
NIBLIT_LLAMA_DEFAULT_MODEL   File stem of the model to load on ``start()``.
NIBLIT_LLAMA_AUTOSTART       Set to ``"1"`` to start the server automatically
                             when the service is initialised by RuntimeManager.
NIBLIT_LLAMA_N_CTX           Context length passed to llama-server
                             (default: ``16384``).
NIBLIT_LLAMA_N_THREADS       CPU threads (default: ``0`` = auto-detect by
                             llama-server itself).
NIBLIT_LLAMA_HOST            Bind host for the managed server
                             (default: ``127.0.0.1``).
NIBLIT_LLAMA_PORT            Bind port for the managed server
                             (default: ``8080``).
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("LlamaServerManager")

# ── Module-level singleton ──────────────────────────────────────────────────
_manager: Optional["LlamaServerManager"] = None
_manager_lock = threading.Lock()

# ── Default model search directories ───────────────────────────────────────
_DEFAULT_MODEL_DIRS: list[str] = [
    os.path.expanduser("~/llama_migration/models"),
    os.path.expanduser("~/.cache/llama.cpp"),
    os.path.expanduser("~/.cache/huggingface/hub"),
    # Portable Windows path used by the primary developer
    r"C:\Users\Riyaad\llama_migration\models",
    # Repository-local models/ subfolder
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"),
]

# ── Quantization tags extracted from GGUF filenames ────────────────────────
_KNOWN_QUANT_TAGS: tuple[str, ...] = (
    "Q8_0", "Q6_K", "Q5_K_M", "Q5_K_S", "Q5_0",
    "Q4_K_M", "Q4_K_S", "Q4_0",
    "Q3_K_L", "Q3_K_M", "Q3_K_S", "Q2_K",
    "IQ4_XS", "IQ3_XS", "IQ2_XXS",
    "F16", "F32",
)

# ── Well-known llama-server binary search order ─────────────────────────────
_BINARY_SEARCH_PATHS: tuple[str, ...] = (
    os.path.expanduser("~/llama.cpp/build/bin/llama-server"),
    r"C:\Users\Riyaad\llama_migration\llama.cpp\build\bin\Release\llama-server.exe",
    r"C:\Users\Riyaad\llama_migration\llama.cpp\build\bin\llama-server.exe",
    "llama-server",        # rely on PATH lookup
    "llama-server.exe",
)

# Startup timeout when polling the server health endpoint
_SERVER_START_TIMEOUT_SECONDS = 120.0
_SERVER_HEALTH_POLL_INTERVAL = 2.0
_HTTP_PROBE_TIMEOUT = 3.0


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    """Descriptor for a discovered or registered GGUF model file."""

    name: str
    path: str
    size_mb: float
    quantization: str = ""
    is_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "size_mb": round(self.size_mb, 1),
            "quantization": self.quantization,
            "is_active": self.is_active,
        }


# ── Helper functions ────────────────────────────────────────────────────────

def _parse_quantization(filename: str) -> str:
    """Extract the quantization tag from a GGUF filename (e.g. ``Q4_K_M``)."""
    stem = pathlib.Path(filename).stem.upper()
    for tag in _KNOWN_QUANT_TAGS:
        if tag in stem:
            return tag
    return ""


def _deduplicate_ordered(items: list[str]) -> list[str]:
    """Return a deduplicated list preserving the original order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ── Core class ──────────────────────────────────────────────────────────────

class LlamaServerManager:
    """Manages one llama-server process and a registry of discovered GGUF models.

    Responsibilities
    ----------------
    1. **Model discovery** — scans configured directories for ``.gguf`` files
       and populates :attr:`registered_models`.
    2. **Server lifecycle** — starts, stops, and health-monitors the
       ``llama-server`` binary as a subprocess.
    3. **Model switching** — gracefully stops the current server and restarts
       it with the requested model; notifies :mod:`modules.local_brain`.

    The manager is safe to instantiate even when no binary is present or no
    models have been found; every public method returns a safe value in that
    situation rather than raising an exception.
    """

    def __init__(self) -> None:
        # Server addressing
        self._server_url: str = _resolve_server_url()
        self._bind_host: str = (
            os.environ.get("NIBLIT_LLAMA_HOST", "").strip()
            or os.environ.get("NIBLIT_LLAMA_SERVER_HOST", "127.0.0.1").strip()
            or "127.0.0.1"
        )
        _port_raw = (
            os.environ.get("NIBLIT_LLAMA_PORT", "")
            or os.environ.get("NIBLIT_LLAMA_SERVER_PORT", "8080")
        ).strip()
        self._bind_port: int = int(_port_raw) if _port_raw.isdigit() else 8080

        # Runtime configuration
        self._binary: Optional[str] = _resolve_binary()
        _ctx_raw = os.environ.get("NIBLIT_LLAMA_N_CTX", "16384").strip()
        self._n_ctx: int = int(_ctx_raw) if _ctx_raw.isdigit() else 16384
        _threads_raw = os.environ.get("NIBLIT_LLAMA_N_THREADS", "0").strip()
        self._n_threads: int = int(_threads_raw) if _threads_raw.isdigit() else 0
        self._default_model_name: str = os.environ.get("NIBLIT_LLAMA_DEFAULT_MODEL", "").strip()
        self._autostart: bool = os.environ.get("NIBLIT_LLAMA_AUTOSTART", "0").strip() in (
            "1", "true", "yes",
        )

        # Model registry
        self.registered_models: Dict[str, ModelInfo] = {}
        self._active_model_name: Optional[str] = None

        # Process state
        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._process_lock = threading.Lock()
        self._external_server: bool = False  # True when we adopted an already-running server
        self._server_ready: bool = False
        self._start_time: Optional[float] = None

        # Health monitor
        self._stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._last_health: Dict[str, Any] = {"status": "stopped", "checked_at": 0.0}
        self._health_lock = threading.Lock()

        log.debug(
            "[LlamaServerManager] initialized — binary=%s url=%s autostart=%s",
            self._binary, self._server_url, self._autostart,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def discover_models(self, extra_dirs: Optional[List[str]] = None) -> List[ModelInfo]:
        """Scan configured directories for ``.gguf`` model files.

        Newly found models are added to :attr:`registered_models`.
        Existing entries are not overwritten so that caller-applied overrides
        (e.g. ``is_active``) are preserved.

        Args:
            extra_dirs: Additional directories to scan ahead of the defaults.

        Returns:
            List of :class:`ModelInfo` objects found during this invocation.
        """
        dirs = self._collect_scan_dirs(extra_dirs)
        found: List[ModelInfo] = []
        for directory in dirs:
            p = pathlib.Path(directory)
            if not p.is_dir():
                continue
            for gguf in sorted(p.rglob("*.gguf")):
                info = _make_model_info(gguf)
                if info.name not in self.registered_models:
                    self.registered_models[info.name] = info
                    log.info(
                        "[LlamaServerManager] discovered model: %s (%.0f MB)",
                        info.name, info.size_mb,
                    )
                found.append(info)
        log.debug(
            "[LlamaServerManager] discover_models complete: %d found, %d registered",
            len(found), len(self.registered_models),
        )
        return found

    def register_model(self, path: str, name: Optional[str] = None) -> ModelInfo:
        """Explicitly register a GGUF model file.

        Use this to add models that lie outside the standard scan directories.

        Args:
            path:  Absolute (or resolvable) path to the ``.gguf`` file.
            name:  Display name key.  Defaults to the file stem.

        Returns:
            :class:`ModelInfo` for the registered model.
        """
        p = pathlib.Path(path)
        info = _make_model_info(p, override_name=name)
        self.registered_models[info.name] = info
        log.info(
            "[LlamaServerManager] registered model: %s → %s",
            info.name, info.path,
        )
        return info

    def get_registered_models(self) -> List[ModelInfo]:
        """Return all registered models sorted alphabetically by name."""
        return sorted(self.registered_models.values(), key=lambda m: m.name)

    def start(self, model_name: Optional[str] = None) -> bool:
        """Start the managed llama-server with the specified or default model.

        If a server process is already running this call returns ``True``
        immediately.  If an external server is detected at the configured URL
        it is adopted without spawning a subprocess.

        Args:
            model_name: Registered model name to load.  Falls back to
                :attr:`_default_model_name`, then to the first registered
                model, then to env-var configured paths.

        Returns:
            ``True`` on success, ``False`` if the server could not be started.
        """
        with self._process_lock:
            if self._is_server_alive():
                log.debug("[LlamaServerManager] server already running — skipping start")
                return True

            # Adopt an already-running external server when possible
            if self._probe_http():
                log.info(
                    "[LlamaServerManager] external server detected at %s — adopting",
                    self._server_url,
                )
                self._external_server = True
                self._server_ready = True
                return True

            model_path = self._resolve_model_path(model_name)
            if model_path is None:
                log.warning("[LlamaServerManager] no model available — cannot start server")
                return False
            if self._binary is None:
                log.warning("[LlamaServerManager] llama-server binary not found — cannot start server")
                return False

            return self._spawn_server(model_path)

    def stop(self) -> None:
        """Stop the managed llama-server process.

        If the server was adopted from an external process this call simply
        releases our handle without terminating the external process.
        """
        with self._process_lock:
            if self._external_server:
                log.info("[LlamaServerManager] releasing adopted external server — not terminating")
                self._server_ready = False
                self._external_server = False
                return
            self._terminate_process()
            self._server_ready = False
            self._active_model_name = None

    def switch_model(self, model_name: str) -> bool:
        """Switch the active model by stopping and restarting llama-server.

        Acquires the model-switch lock from :mod:`modules.local_brain` so
        that any in-flight inference call finishes cleanly before the server
        restarts.

        Args:
            model_name: Key in :attr:`registered_models` to activate.

        Returns:
            ``True`` when the switch succeeded, ``False`` otherwise.
        """
        if model_name == self._active_model_name:
            log.debug(
                "[LlamaServerManager] model %s already active — no switch needed",
                model_name,
            )
            return True

        model_info = self.registered_models.get(model_name)
        if model_info is None:
            log.warning("[LlamaServerManager] unknown model '%s' — switch aborted", model_name)
            return False

        log.info(
            "[LlamaServerManager] switching model: %s → %s",
            self._active_model_name or "<none>", model_name,
        )

        switch_lock = self._get_model_switch_lock()
        acquired = switch_lock.acquire(timeout=30.0) if switch_lock is not None else True
        try:
            self.stop()
            time.sleep(0.5)  # brief pause so the OS releases the port
            ok = self.start(model_name)
        finally:
            if switch_lock is not None and acquired:
                switch_lock.release()

        if ok:
            self._notify_local_brain(model_info)
        return ok

    def health_check(self) -> Dict[str, Any]:
        """Snapshot the current health of the managed llama-server.

        This method is safe to call from any thread.

        Returns:
            Dict with keys ``status``, ``server_url``, ``active_model``,
            ``server_pid``, ``external``, ``server_ready``,
            ``registered_models``, ``checked_at``.
        """
        proc_alive = self._is_server_alive()
        http_ok = self._probe_http() if (proc_alive or self._external_server) else False

        if (proc_alive or self._external_server) and http_ok:
            status = "healthy"
        elif proc_alive and not http_ok:
            status = "degraded"
        else:
            status = "stopped"

        snap: Dict[str, Any] = {
            "status": status,
            "server_url": self._server_url,
            "active_model": self._active_model_name,
            "server_pid": self._process.pid if self._process is not None else None,
            "external": self._external_server,
            "server_ready": self._server_ready,
            "registered_models": len(self.registered_models),
            "checked_at": time.time(),
        }
        with self._health_lock:
            self._last_health = snap
        return snap

    def status(self) -> Dict[str, Any]:
        """Return a full status report suitable for CLI display or diagnostics."""
        health = self.health_check()
        return {
            **health,
            "binary": self._binary,
            "autostart": self._autostart,
            "models": [m.to_dict() for m in self.get_registered_models()],
        }

    def adopt_external_server(self) -> bool:
        """Probe the configured server URL and adopt it when reachable.

        Returns:
            ``True`` when the adoption succeeded.
        """
        if self._probe_http():
            self._external_server = True
            self._server_ready = True
            log.info(
                "[LlamaServerManager] adopted external llama-server at %s",
                self._server_url,
            )
            return True
        log.debug(
            "[LlamaServerManager] adopt_external_server: no server at %s",
            self._server_url,
        )
        return False

    def start_health_monitor(self, interval_seconds: float = 30.0) -> None:
        """Start a background daemon thread that periodically calls :meth:`health_check`.

        If the monitor is already running this is a no-op.

        Args:
            interval_seconds: Polling interval in seconds (default: 30).
        """
        if self._health_thread is not None and self._health_thread.is_alive():
            return
        self._stop_event.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            args=(interval_seconds,),
            daemon=True,
            name="LlamaServerHealthMonitor",
        )
        self._health_thread.start()
        log.debug(
            "[LlamaServerManager] health monitor started (interval=%.0fs)",
            interval_seconds,
        )

    def stop_health_monitor(self) -> None:
        """Signal the background health monitor to stop and wait for it."""
        self._stop_event.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=5.0)
            self._health_thread = None

    def get_last_health(self) -> Dict[str, Any]:
        """Return the most recent health snapshot without re-probing."""
        with self._health_lock:
            return dict(self._last_health)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _spawn_server(self, model_path: str) -> bool:
        """Start a new llama-server subprocess.

        Must be called with ``_process_lock`` held.
        """
        cmd = self._build_command(model_path)
        log.info("[LlamaServerManager] launching: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._start_time = time.time()
        except OSError as exc:
            log.error("[LlamaServerManager] failed to spawn server: %s", exc)
            self._process = None
            return False

        # Poll the health endpoint until ready or timeout
        deadline = time.time() + _SERVER_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self._process.poll() is not None:
                # Process exited unexpectedly
                stderr_tail = ""
                try:
                    if self._process.stderr is not None:
                        stderr_tail = self._process.stderr.read(2048) or ""
                except Exception:
                    pass
                log.error(
                    "[LlamaServerManager] server exited before becoming ready. stderr: %s",
                    stderr_tail[:500],
                )
                self._process = None
                return False

            if self._probe_http():
                # Identify which registered model is now active
                stem = pathlib.Path(model_path).stem.lower()
                matched_name = stem  # fallback
                for reg_name, info in self.registered_models.items():
                    if pathlib.Path(info.path).stem.lower() == stem:
                        matched_name = reg_name
                        info.is_active = True
                        break

                # Clear is_active on previously active model
                if self._active_model_name and self._active_model_name in self.registered_models:
                    self.registered_models[self._active_model_name].is_active = False

                self._active_model_name = matched_name
                self._server_ready = True
                elapsed = time.time() - self._start_time
                log.info(
                    "[LlamaServerManager] server ready after %.1fs — active_model=%s",
                    elapsed, self._active_model_name,
                )
                return True

            time.sleep(_SERVER_HEALTH_POLL_INTERVAL)

        log.warning(
            "[LlamaServerManager] server did not become ready within %.0f seconds",
            _SERVER_START_TIMEOUT_SECONDS,
        )
        self._terminate_process()
        return False

    def _terminate_process(self) -> None:
        """Terminate the managed subprocess.

        Must be called with ``_process_lock`` held.
        """
        if self._process is None:
            return
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5.0)
        except Exception as exc:
            log.debug("[LlamaServerManager] error during process termination: %s", exc)
        finally:
            self._process = None
            log.info("[LlamaServerManager] server process stopped")

    def _is_server_alive(self) -> bool:
        """Return ``True`` when the managed subprocess is still running."""
        return self._process is not None and self._process.poll() is None

    def _probe_http(self) -> bool:
        """Return ``True`` when the llama-server ``/health`` endpoint responds 200."""
        try:
            import urllib.request

            url = f"{self._server_url}/health"
            with urllib.request.urlopen(url, timeout=_HTTP_PROBE_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _build_command(self, model_path: str) -> list[str]:
        """Build the llama-server launch command list."""
        cmd: list[str] = [
            self._binary,  # type: ignore[list-item]
            "--model", model_path,
            "--host", self._bind_host,
            "--port", str(self._bind_port),
            "--ctx-size", str(self._n_ctx),
        ]
        if self._n_threads > 0:
            cmd += ["--threads", str(self._n_threads)]
        return cmd

    def _collect_scan_dirs(self, extra_dirs: Optional[List[str]]) -> list[str]:
        """Assemble the ordered, deduplicated list of directories to scan."""
        dirs: list[str] = []
        env_dirs = os.environ.get("NIBLIT_LLAMA_MODEL_DIRS", "").strip()
        if env_dirs:
            dirs.extend(env_dirs.split(os.pathsep))
        if extra_dirs:
            dirs.extend(extra_dirs)
        dirs.extend(_DEFAULT_MODEL_DIRS)
        return _deduplicate_ordered(dirs)

    def _resolve_model_path(self, model_name: Optional[str]) -> Optional[str]:
        """Resolve *model_name* → absolute file path.

        Falls back through:
        1. Explicit *model_name* key in the registry
        2. :attr:`_default_model_name` key in the registry
        3. First model in the registry
        4. ``NIBLIT_GGUF_MODEL_PATH`` / ``NIBLIT_LOCAL_MODEL`` env vars
        """
        if model_name and model_name in self.registered_models:
            return self.registered_models[model_name].path
        if self._default_model_name and self._default_model_name in self.registered_models:
            return self.registered_models[self._default_model_name].path
        for info in self.registered_models.values():
            return info.path
        for env_var in ("NIBLIT_GGUF_MODEL_PATH", "NIBLIT_LOCAL_MODEL"):
            val = os.environ.get(env_var, "").strip()
            if val and pathlib.Path(val).exists():
                return val
        return None

    @staticmethod
    def _get_model_switch_lock() -> Optional[threading.Lock]:
        """Return the model-switch lock from :mod:`modules.local_brain`."""
        try:
            import modules.local_brain as _lb  # type: ignore[import]

            return getattr(_lb, "_MODEL_SWITCH_LOCK", None)
        except Exception:
            return None

    def _notify_local_brain(self, model_info: ModelInfo) -> None:
        """Update :mod:`modules.local_brain`'s config after a model switch.

        Sets the new ``llama_server_url`` on the mutable config object and
        clears the HTTP-availability cache so the next ``generate()`` call
        re-probes the endpoint.
        """
        try:
            import modules.local_brain as _lb  # type: ignore[import]

            cfg = getattr(_lb, "_local_brain_cfg", None)
            if cfg is not None:
                cfg.llama_server_url = self._server_url

            # Clear per-instance health cache so the next call re-validates
            cache: Optional[dict] = getattr(_lb, "_llama_server_available", None)
            if isinstance(cache, dict):
                cache.clear()

            log.info(
                "[LlamaServerManager] notified local_brain — active model: %s",
                model_info.name,
            )
        except Exception as exc:
            log.debug("[LlamaServerManager] could not notify local_brain: %s", exc)

    def _health_loop(self, interval: float) -> None:
        """Background health-monitor loop — runs as a daemon thread."""
        while not self._stop_event.wait(interval):
            try:
                snap = self.health_check()
                # Warn when a managed process disappears unexpectedly
                if (
                    self._server_ready
                    and not self._external_server
                    and not self._is_server_alive()
                ):
                    log.warning(
                        "[LlamaServerManager] managed server process died unexpectedly "
                        "(last health: %s)",
                        snap.get("status"),
                    )
                    self._server_ready = False
            except Exception as exc:  # pragma: no cover
                log.debug("[LlamaServerManager] health loop error: %s", exc)


# ── Module-level helpers (also used by RuntimeManager builder) ───────────────

def _resolve_server_url() -> str:
    """Resolve the llama-server base URL from environment variables."""
    explicit = os.environ.get("NIBLIT_LLAMA_SERVER_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = (
        os.environ.get("NIBLIT_LLAMA_HOST", "").strip()
        or os.environ.get("NIBLIT_LLAMA_SERVER_HOST", "127.0.0.1").strip()
        or "127.0.0.1"
    )
    port_raw = (
        os.environ.get("NIBLIT_LLAMA_PORT", "").strip()
        or os.environ.get("NIBLIT_LLAMA_SERVER_PORT", "8080").strip()
        or "8080"
    )
    port = int(port_raw) if port_raw.isdigit() else 8080
    return f"http://{host}:{port}"


def _resolve_binary() -> Optional[str]:
    """Locate the ``llama-server`` binary using env overrides and common paths."""
    env_path = os.environ.get("NIBLIT_LLAMA_BINARY_PATH", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    for candidate in _BINARY_SEARCH_PATHS:
        if shutil.which(candidate):
            return shutil.which(candidate)
        if os.path.isfile(candidate):
            return candidate
    return None


def _make_model_info(
    path: pathlib.Path, override_name: Optional[str] = None
) -> ModelInfo:
    """Build a :class:`ModelInfo` from a filesystem path."""
    size_bytes = 0
    try:
        size_bytes = path.stat().st_size
    except OSError:
        pass
    name = override_name if override_name else path.stem
    return ModelInfo(
        name=name,
        path=str(path.resolve()),
        size_mb=size_bytes / (1024 * 1024),
        quantization=_parse_quantization(path.name),
    )


# ── Singleton accessor ───────────────────────────────────────────────────────

def get_llama_server_manager() -> LlamaServerManager:
    """Return the process-level :class:`LlamaServerManager` singleton.

    Thread-safe.  Creates the instance on first call.
    """
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LlamaServerManager()
    return _manager
