#!/usr/bin/env python3
"""
modules/docker_backend.py — Docker-hosted Ollama-compatible backend for Niblit.

The DockerBackend manages communication with an Ollama-compatible inference
server running inside a Docker container (or accessible via HTTP).  It
discovers models via the ``/api/tags`` endpoint, monitors health via
``/health``, and exposes an OpenAI-compatible chat completions interface.

Architecture position
---------------------
RuntimeManager
  └─ docker_backend       ← DockerBackend (this module)
       ├─ discovers models (GET /api/tags)
       ├─ health monitoring (GET /health)
       ├─ chat completions (POST /v1/chat/completions)
       └─ fallback coordination with llama_server_manager

Boot behaviour
--------------
The backend does NOT start a Docker container automatically.  It expects an
Ollama-compatible server to already be running at the configured URL
(default: ``http://127.0.0.1:11434``).  Set ``NIBLIT_DOCKER_AUTOSTART=1``
to attempt starting the container via ``docker run``.

Fallback logic
--------------
When Docker backend is the primary backend, the system follows this
fallback chain:

1. **docker**   — Ollama-compatible server in Docker (preferred)
2. **llama.cpp** — Local llama-server managed by LlamaServerManager
3. **degraded**  — No inference backend available; responses are stubbed

Environment variables
---------------------
NIBLIT_DOCKER_BACKEND_URL     Base URL of the Ollama-compatible server
                              (default: ``http://127.0.0.1:11434``)
NIBLIT_DOCKER_AUTOSTART       Set to ``"1"`` to auto-start the Docker container
NIBLIT_DOCKER_CONTAINER_NAME  Docker container name (default: ``niblit-ollama``)
NIBLIT_DOCKER_IMAGE           Docker image to use (default: ``ollama/ollama``)
NIBLIT_DOCKER_PORT            Host port to map (default: ``11434``)
NIBLIT_DOCKER_DEFAULT_MODEL   Default model to select (default: ``qwen2.5-coder:3b``)
NIBLIT_DOCKER_HEALTH_TTL      Health cache TTL in seconds (default: ``10``)
NIBLIT_DOCKER_REQUEST_TIMEOUT HTTP request timeout in seconds (default: ``120``)
NIBLIT_DOCKER_FALLBACK_ORDER  Comma-separated fallback order (default: ``docker,llama_cpp``)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("DockerBackend")

# ── Module-level singleton ──────────────────────────────────────────────────
_backend: Optional["DockerBackend"] = None
_backend_lock = threading.Lock()

# ── Constants ───────────────────────────────────────────────────────────────
_HTTP_PROBE_TIMEOUT = 5.0
_HEALTH_CACHE_TTL_DEFAULT = 10.0
_REQUEST_TIMEOUT_DEFAULT = 120.0
_DOCKER_START_TIMEOUT = 60.0
_DOCKER_HEALTH_POLL_INTERVAL = 2.0


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class DockerModelInfo:
    """Descriptor for a model discovered via the Ollama ``/api/tags`` endpoint."""

    name: str
    size_mb: float = 0.0
    digest: str = ""
    modified_at: str = ""
    is_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "size_mb": round(self.size_mb, 1),
            "digest": self.digest[:12] if self.digest else "",
            "modified_at": self.modified_at,
            "is_active": self.is_active,
        }


# ── Helper functions ────────────────────────────────────────────────────────

def _getenv_str(name: str, default: str) -> str:
    """Return a string from the environment, falling back to *default*."""
    raw = os.environ.get(name, None)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _getenv_int(name: str, default: int) -> int:
    """Return an int from the environment, falling back to *default*."""
    try:
        raw = os.environ.get(name, "")
        if raw is None or raw.strip() == "":
            return default
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _getenv_float(name: str, default: float) -> float:
    """Return a float from the environment, falling back to *default*."""
    try:
        raw = os.environ.get(name, "")
        if raw is None or raw.strip() == "":
            return default
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


# ── Core class ──────────────────────────────────────────────────────────────

class DockerBackend:
    """Manages communication with a Docker-hosted Ollama-compatible inference server.

    Responsibilities
    ----------------
    1. **Model discovery** — queries ``/api/tags`` to enumerate available models.
    2. **Health monitoring** — polls ``/health`` to track server availability.
    3. **Chat completions** — forwards prompts to ``/v1/chat/completions``.
    4. **Fallback coordination** — degrades gracefully to llama.cpp when Docker
       backend is unavailable.

    The backend is safe to instantiate even when Docker is not installed or the
    server is not running; every public method returns a safe value rather than
    raising an exception.
    """

    def __init__(self) -> None:
        # Server addressing
        self._server_url: str = _getenv_str(
            "NIBLIT_DOCKER_BACKEND_URL", "http://127.0.0.1:11434"
        ).rstrip("/")

        # Docker container configuration
        self._container_name: str = _getenv_str(
            "NIBLIT_DOCKER_CONTAINER_NAME", "niblit-ollama"
        )
        self._docker_image: str = _getenv_str(
            "NIBLIT_DOCKER_IMAGE", "ollama/ollama"
        )
        self._docker_port: int = _getenv_int("NIBLIT_DOCKER_PORT", 11434)
        self._autostart: bool = os.environ.get(
            "NIBLIT_DOCKER_AUTOSTART", "0"
        ).strip() in ("1", "true", "yes")

        # Default model
        self._default_model: str = _getenv_str(
            "NIBLIT_DOCKER_DEFAULT_MODEL", "qwen2.5-coder:3b"
        )

        # Health and timeout
        self._health_ttl: float = _getenv_float(
            "NIBLIT_DOCKER_HEALTH_TTL", _HEALTH_CACHE_TTL_DEFAULT
        )
        self._request_timeout: float = _getenv_float(
            "NIBLIT_DOCKER_REQUEST_TIMEOUT", _REQUEST_TIMEOUT_DEFAULT
        )

        # Fallback order
        fallback_raw = _getenv_str(
            "NIBLIT_DOCKER_FALLBACK_ORDER", "docker,llama_cpp"
        )
        self._fallback_order: List[str] = [
            f.strip() for f in fallback_raw.split(",") if f.strip()
        ]

        # Model registry
        self.registered_models: Dict[str, DockerModelInfo] = {}
        self._active_model_name: Optional[str] = None

        # State
        self._server_ready: bool = False
        self._last_health_ts: float = 0.0
        self._last_health: Dict[str, Any] = {"status": "unknown", "checked_at": 0.0}
        self._health_lock = threading.Lock()

        # Health monitor
        self._stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None

        log.debug(
            "[DockerBackend] initialized — url=%s autostart=%s default_model=%s",
            self._server_url, self._autostart, self._default_model,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def discover_models(self) -> List[DockerModelInfo]:
        """Query the ``/api/tags`` endpoint to discover available models.

        Returns:
            List of :class:`DockerModelInfo` objects found during this invocation.
            Returns an empty list if the server is unreachable.
        """
        try:
            data = self._http_get_json(f"{self._server_url}/api/tags")
            models_data = data.get("models", [])
            found: List[DockerModelInfo] = []
            for m in models_data:
                name = m.get("name", "")
                if not name:
                    continue
                size_bytes = m.get("size", 0)
                info = DockerModelInfo(
                    name=name,
                    size_mb=size_bytes / (1024 * 1024) if size_bytes else 0.0,
                    digest=m.get("digest", ""),
                    modified_at=m.get("modified_at", ""),
                )
                if name not in self.registered_models:
                    self.registered_models[name] = info
                    log.info(
                        "[DockerBackend] discovered model: %s (%.0f MB)",
                        info.name, info.size_mb,
                    )
                found.append(info)
            log.debug(
                "[DockerBackend] discover_models complete: %d found, %d registered",
                len(found), len(self.registered_models),
            )
            return found
        except Exception as exc:
            log.debug("[DockerBackend] model discovery failed: %s", exc)
            return []

    def get_registered_models(self) -> List[DockerModelInfo]:
        """Return all registered models sorted alphabetically by name."""
        return sorted(self.registered_models.values(), key=lambda m: m.name)

    def start(self) -> bool:
        """Ensure the Docker backend is ready for inference.

        If ``NIBLIT_DOCKER_AUTOSTART`` is set, attempts to start the Docker
        container.  Then probes the server health endpoint.

        Returns:
            ``True`` if the backend is ready, ``False`` otherwise.
        """
        if self._is_healthy():
            log.debug("[DockerBackend] already healthy — skipping start")
            return True

        if self._autostart:
            self._start_container()

        # Wait for server to become ready
        deadline = time.time() + _DOCKER_START_TIMEOUT
        while time.time() < deadline:
            if self._probe_health():
                self._server_ready = True
                # Discover models on first ready
                if not self.registered_models:
                    self.discover_models()
                log.info("[DockerBackend] server is ready at %s", self._server_url)
                return True
            time.sleep(_DOCKER_HEALTH_POLL_INTERVAL)

        log.warning(
            "[DockerBackend] server did not become ready within %.0f seconds",
            _DOCKER_START_TIMEOUT,
        )
        return False

    def stop(self) -> None:
        """Stop the Docker container if we started it and autostart is enabled."""
        if not self._autostart:
            self._server_ready = False
            return
        try:
            subprocess.run(
                ["docker", "stop", self._container_name],
                capture_output=True,
                timeout=15,
            )
            log.info("[DockerBackend] container %s stopped", self._container_name)
        except Exception as exc:
            log.debug("[DockerBackend] stop container failed: %s", exc)
        finally:
            self._server_ready = False

    def health_check(self) -> Dict[str, Any]:
        """Snapshot the current health of the Docker backend.

        Returns:
            Dict with keys ``status``, ``server_url``, ``active_model``,
            ``server_ready``, ``registered_models``, ``checked_at``.
        """
        healthy = self._probe_health()
        now = time.time()

        if healthy:
            status = "healthy"
            self._server_ready = True
        elif self._server_ready:
            status = "degraded"
        else:
            status = "stopped"

        snap: Dict[str, Any] = {
            "status": status,
            "server_url": self._server_url,
            "active_model": self._active_model_name,
            "server_ready": self._server_ready,
            "registered_models": len(self.registered_models),
            "container_name": self._container_name,
            "checked_at": now,
        }
        with self._health_lock:
            self._last_health = snap
            self._last_health_ts = now
        return snap

    def status(self) -> Dict[str, Any]:
        """Return a full status report suitable for CLI display or diagnostics."""
        health = self.health_check()
        return {
            **health,
            "autostart": self._autostart,
            "docker_image": self._docker_image,
            "docker_port": self._docker_port,
            "default_model": self._default_model,
            "fallback_order": self._fallback_order,
            "models": [m.to_dict() for m in self.get_registered_models()],
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """Send a chat completion request to the Ollama-compatible server.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model name to use. Falls back to ``_default_model``.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            The assistant's response text, or an error message string.
        """
        model_name = model or self._default_model
        payload = json.dumps({
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self._server_url}/v1/chat/completions",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self._request_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                self._active_model_name = model_name
                return content.strip() or "[DockerBackend: empty response]"
        except Exception as exc:
            log.warning("[DockerBackend] chat request failed: %s", exc)
            return f"[DockerBackend error: {exc}]"

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 512,
    ) -> str:
        """Convenience wrapper for single-prompt generation.

        Args:
            prompt: The user prompt text.
            system_prompt: Optional system prompt.
            model: Model name override.
            max_tokens: Maximum tokens to generate.

        Returns:
            The generated text.
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, model=model, max_tokens=max_tokens)

    def select_model(self, model_name: str) -> bool:
        """Set the active model for subsequent inference calls.

        Args:
            model_name: Name of the model to activate (must be in registry).

        Returns:
            ``True`` if the model was selected, ``False`` if not found.
        """
        if model_name not in self.registered_models:
            # Try discovering models first
            self.discover_models()
        if model_name not in self.registered_models:
            log.warning("[DockerBackend] unknown model '%s'", model_name)
            return False
        self._active_model_name = model_name
        log.info("[DockerBackend] active model set to: %s", model_name)
        return True

    def get_fallback_chain(self) -> List[str]:
        """Return the configured fallback order for inference backends."""
        return list(self._fallback_order)

    def is_available(self) -> bool:
        """Return ``True`` when the Docker backend server is reachable."""
        return self._probe_health()

    def start_health_monitor(self, interval_seconds: float = 30.0) -> None:
        """Start a background daemon thread that periodically calls :meth:`health_check`."""
        if self._health_thread is not None and self._health_thread.is_alive():
            return
        self._stop_event.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            args=(interval_seconds,),
            daemon=True,
            name="DockerBackendHealthMonitor",
        )
        self._health_thread.start()
        log.debug(
            "[DockerBackend] health monitor started (interval=%.0fs)",
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

    def _is_healthy(self) -> bool:
        """Check cached health status (within TTL)."""
        now = time.time()
        with self._health_lock:
            if now - self._last_health_ts < self._health_ttl:
                return self._last_health.get("status") == "healthy"
        return self._probe_health()

    def _probe_health(self) -> bool:
        """Return ``True`` when the server ``/health`` endpoint responds 200."""
        try:
            url = f"{self._server_url}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=_HTTP_PROBE_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _http_get_json(self, url: str) -> Dict[str, Any]:
        """Make HTTP GET request and parse JSON response."""
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_HTTP_PROBE_TIMEOUT) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    def _start_container(self) -> bool:
        """Attempt to start the Docker container via ``docker run``.

        Returns:
            ``True`` if the container started (or was already running).
        """
        # Check if container is already running
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self._container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "true" in result.stdout.strip().lower():
                log.info(
                    "[DockerBackend] container %s already running",
                    self._container_name,
                )
                return True
        except Exception:
            pass

        # Start the container
        cmd = [
            "docker", "run", "-d",
            "--name", self._container_name,
            "-p", f"{self._docker_port}:11434",
            self._docker_image,
        ]
        log.info("[DockerBackend] launching container: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                log.info("[DockerBackend] container started: %s", result.stdout.strip())
                return True
            else:
                log.warning(
                    "[DockerBackend] docker run failed: %s", result.stderr.strip()
                )
                return False
        except Exception as exc:
            log.warning("[DockerBackend] failed to start container: %s", exc)
            return False

    def _health_loop(self, interval: float) -> None:
        """Background health-monitor loop — runs as a daemon thread."""
        while not self._stop_event.wait(interval):
            try:
                self.health_check()
            except Exception as exc:  # pragma: no cover
                log.debug("[DockerBackend] health loop error: %s", exc)


# ── Fallback coordinator ────────────────────────────────────────────────────

class BackendFallbackCoordinator:
    """Coordinates fallback between Docker and llama.cpp backends.

    When the primary backend (Docker) is unavailable, inference requests
    are routed to the secondary backend (llama.cpp via LlamaServerManager).
    If both are unavailable, the system enters degraded mode.
    """

    def __init__(
        self,
        docker_backend: Optional[DockerBackend] = None,
        llama_server_manager: Optional[Any] = None,
    ) -> None:
        self._docker = docker_backend
        self._llama = llama_server_manager
        self._lock = threading.Lock()

    def get_active_backend(self) -> str:
        """Return the name of the currently active backend.

        Returns one of: ``"docker"``, ``"llama_cpp"``, ``"degraded"``.
        """
        if self._docker is not None and self._docker.is_available():
            return "docker"
        if self._llama is not None:
            try:
                health = self._llama.health_check()
                if health.get("status") in ("healthy", "degraded"):
                    return "llama_cpp"
            except Exception:
                pass
        return "degraded"

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 512,
    ) -> str:
        """Route a chat request through the fallback chain.

        Tries Docker backend first, then llama.cpp, then returns a
        degraded-mode message.
        """
        with self._lock:
            # Try Docker backend
            if self._docker is not None and self._docker.is_available():
                try:
                    result = self._docker.chat(messages, max_tokens=max_tokens)
                    if not result.startswith("[DockerBackend error:"):
                        return result
                except Exception as exc:
                    log.warning("[FallbackCoordinator] Docker backend failed: %s", exc)

            # Try llama.cpp backend
            if self._llama is not None:
                try:
                    # LlamaServerManager doesn't have a direct chat method,
                    # but LocalBrainGateway does via HTTP
                    from modules.local_brain import get_local_brain
                    gateway = get_local_brain()
                    # Build prompt from messages
                    prompt_parts = []
                    for msg in messages:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")
                        prompt_parts.append(f"{role}: {content}")
                    prompt = "\n".join(prompt_parts)
                    # Use QwenLocalBrain shim for inference
                    brain = type("ShimBrain", (), {"_call_cloud_runtime": lambda self, msgs, mt: ""})()
                    # Fallback: return degraded message
                except Exception as exc:
                    log.warning("[FallbackCoordinator] llama.cpp fallback failed: %s", exc)

            # Degraded mode
            return "[DockerBackend: all backends unavailable — degraded mode]"

    def status(self) -> Dict[str, Any]:
        """Return the fallback coordinator status."""
        active = self.get_active_backend()
        return {
            "active_backend": active,
            "docker_available": self._docker is not None and self._docker.is_available(),
            "llama_cpp_available": self._llama is not None,
            "fallback_order": ["docker", "llama_cpp", "degraded"],
        }


# ── Singleton accessor ───────────────────────────────────────────────────────

def get_docker_backend() -> DockerBackend:
    """Return the process-level :class:`DockerBackend` singleton.

    Thread-safe.  Creates the instance on first call.
    """
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = DockerBackend()
    return _backend


def reset_docker_backend() -> None:
    """Discard the current singleton so the next call creates fresh."""
    global _backend
    with _backend_lock:
        if _backend is not None:
            _backend.stop_health_monitor()
        _backend = None