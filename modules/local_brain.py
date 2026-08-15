"""modules/local_brain.py — LocalBrain Runtime Gateway.

This module implements the LocalBrain as a lightweight Runtime Gateway
responsible for validating, launching, monitoring, and recovering the
CloudRuntime. It does NOT perform inference, load models, or manage processes.

All inference responsibilities have moved to CloudRuntime.

Communication with CloudRuntime uses HTTP REST.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("Niblit.LocalBrain")


# ── Safe env helpers ──────────────────────────────────────────────────────────
def getenv_int(name: str, default: int) -> int:
    """Return an int from the environment, falling back to *default* on bad input."""
    try:
        raw = os.environ.get(name, "")
        if raw is None or raw.strip() == "":
            return default
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def getenv_float(name: str, default: float) -> float:
    """Return a float from the environment, falling back to *default* on bad input."""
    try:
        raw = os.environ.get(name, "")
        if raw is None or raw.strip() == "":
            return default
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def getenv_str(name: str, default: str) -> str:
    """Return a str from the environment, falling back to *default* on bad input."""
    raw = os.environ.get(name, None)
    if raw is None or raw.strip() == "":
        return default
    return str(raw.strip())


# ── Configuration ─────────────────────────────────────────────────────────────
# LocalBrain-specific configuration for runtime gateway operations.

_NIBLIT_CLOUD_RUNTIME_PATH: str = getenv_str(
    "NIBLIT_CLOUD_RUNTIME_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "Niblit-cloud-server"),
)
_NIBLIT_RUNTIME_PROFILE: str = getenv_str("NIBLIT_RUNTIME_PROFILE", "local").lower()
_NIBLIT_RUNTIME_HEALTH_TTL: float = getenv_float("NIBLIT_RUNTIME_HEALTH_TTL", 10.0)
_NIBLIT_RUNTIME_RESTART_MAX: int = getenv_int("NIBLIT_RUNTIME_RESTART_MAX", 5)
_NIBLIT_RUNTIME_BACKOFF_INIT: float = getenv_float("NIBLIT_RUNTIME_BACKOFF_INIT", 1.0)
_NIBLIT_RUNTIME_BACKOFF_MAX: float = getenv_float("NIBLIT_RUNTIME_BACKOFF_MAX", 60.0)
_NIBLIT_CLOUD_SERVER_PRIMARY_PORT: int = getenv_int("NIBLIT_CLOUD_SERVER_PRIMARY_PORT", 8000)

# Legacy env vars kept for backwards compatibility
_NIBLIT_LLAMA_SERVER_URL: str = getenv_str("NIBLIT_LLAMA_SERVER_URL", "http://127.0.0.1:8080")
_NIBLIT_GGUF_BACKEND: str = getenv_str("NIBLIT_GGUF_BACKEND", "auto").lower()

# ── Legacy compatibility ──────────────────────────────────────────────────────
# These module-level constants are kept for backwards compatibility with
# existing callers that import them directly. New code should use the
# LocalBrainGateway API instead.

_MAX_NEW_TOKENS: int = getenv_int("NIBLIT_LOCAL_MAX_NEW", 512)
_GGUF_N_CTX: int = getenv_int("NIBLIT_GGUF_N_CTX", 16384)
_GGUF_N_THREADS: int = getenv_int("NIBLIT_GGUF_N_THREADS", 4)
_GGUF_CHAT_TEMPLATE: str = getenv_str("NIBLIT_GGUF_CHAT_TEMPLATE", "qwen").lower()
_GGUF_STOP_TOKENS_STR: str = os.environ.get("NIBLIT_GGUF_STOP_TOKENS", "").strip()

# Model paths (legacy — now managed by CloudRuntime)
_WINDOWS_MODEL_ROOT = r"C:\Users\Riyaad\llama_migration\models"
_WINDOWS_LLAMA_CPP_ROOT = r"C:\Users\Riyaad\llama_migration\llama.cpp"
_QWEN_MODEL_FILENAME = "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
_LLAMA_MODEL_FILENAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
_DEFAULT_LOCAL_PRESET = "llama3"
_LOCAL_MODEL_PRESETS = ("llama3", "qwen")

# ── Structural context ────────────────────────────────────────────────────────
# Updated to reflect the new architecture where CloudRuntime owns inference.

_NIBLIT_STRUCTURAL_CONTEXT = """
=== NIBLIT ARCHITECTURE (your structural awareness) ===

ENTRY POINTS:
  main.py           — Interactive CLI
  app.py / server.py — FastAPI endpoints

CORE ORCHESTRATION:
  LocalBrain Gateway — Runtime gateway; validates, launches, monitors CloudRuntime
  NiblitCore         — Master controller
  NiblitRouter       — Text → handler routing
  niblit_brain.py    — NiblitBrain: cognition, training, cloud fallback
  niblit_memory/     — Memory layers

RUNTIME:
  CloudRuntime       — Server-grade runtime (inference, scheduler, API, trading)
  llama-server       — GGUF inference backend (managed by CloudRuntime)

BRAIN / LLM STACK:
  NiblitBrain        — Cognition, reasoning, learning
  BrainRouter        — Routes to CloudRuntime or memory brain
  CloudRuntime       — Model execution via HTTP REST
  LocalBrain Gateway — Runtime orchestration only

LEARNING & SELF-IMPROVEMENT:
  ALE (29 steps)     — Autonomous learning engine
  SelfResearcher     — Multi-backend research
  SelfTeacher        — Ingests research into KnowledgeDB
  BrainTrainer       — Fine-tunes on research data (moved from LocalBrain)
  ReflectModule      — Summarises KB reflections

TRADING & MARKET:
  CloudRuntime       — Complete trading pipeline
  niblit-lean-algos  — QuantConnect LEAN integration
  Freqtrade          — Order execution
=== END NIBLIT ARCHITECTURE ===
"""

_NIBLIT_FULL_STRUCTURAL_CONTEXT = """
=== NIBLIT FULL ARCHITECTURE ===

You are Niblit, an autonomous AI operating system.

RUNTIME GATEWAY:
  LocalBrain       — Runtime discovery, validation, coordination, monitoring, recovery

CORE ORCHESTRATION:
  NiblitCore        — Master controller
  NiblitRouter      — 100+ command families
  RuntimeManager    — Runtime lifecycle management
  RuntimeBootstrap  — Path and environment setup

INFERENCE (CloudRuntime):
  CloudRuntime      — 21-stage boot, inference, scheduler, APIs
  GGUFEngine        — GGUF model execution
  ModelManager      — Model loading and provider management
  llama-server      — HTTP inference backend

COGNITION:
  NiblitBrain       — think(), learn(), reasoning
  BrainRouter       — local|balanced|power|offline routing
  BrainTrainer      — Training data and knowledge synthesis

MEMORY:
  LocalDB           — JSON facts/interactions
  KnowledgeDB       — Rich JSON facts and queue
  FusedMemory       — SQLite + Qdrant vector search
  NiblitMemory      — Circuit-breaker, cache, rate-limit

TRADING:
  CloudRuntime      — Trading pipeline (market→lean→validate→risk→execute→feedback)
  niblit-lean-algos — LEAN backtesting and signals
  Freqtrade         — Order execution and portfolio management
=== END NIBLIT FULL ARCHITECTURE ===
"""

_DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT = (
    "You are Niblit, an autonomous AI operating system. "
    "You are powered by CloudRuntime for inference. "
    "You always respond as Niblit.\n"
) + _NIBLIT_STRUCTURAL_CONTEXT

_TOOL_CALL_SYSTEM_PROMPT = (
    "You are Niblit, an autonomous AI operating system with function-calling tools.\n"
    "Use the provided tools to inspect and control Niblit's subsystems.\n"
) + _NIBLIT_FULL_STRUCTURAL_CONTEXT

_SHORT_CHAT_SYSTEM_PROMPT = "You are Niblit, a helpful and friendly AI assistant. Reply concisely and naturally."

# ── Runtime lock ─────────────────────────────────────────────────────────────
_MODEL_SWITCH_LOCK = threading.Lock()


# ── LocalBrain Gateway ───────────────────────────────────────────────────────
class LocalBrainGateway:
    """Runtime Gateway for CloudRuntime.

    This class replaces the monolithic QwenLocalBrain. It owns exactly:
    - Runtime Discovery
    - Runtime Validation
    - Runtime Coordination
    - Runtime Monitoring
    - Runtime Status
    - Runtime Recovery
    - Configuration Discovery

    It does NOT own inference, model loading, or process management.
    Those responsibilities belong to CloudRuntime.
    """

    def __init__(
        self,
        cloud_runtime_path: str = _NIBLIT_CLOUD_RUNTIME_PATH,
        profile: str = _NIBLIT_RUNTIME_PROFILE,
        health_ttl: float = _NIBLIT_RUNTIME_HEALTH_TTL,
        restart_max: int = _NIBLIT_RUNTIME_RESTART_MAX,
        backoff_init: float = _NIBLIT_RUNTIME_BACKOFF_INIT,
        backoff_max: float = _NIBLIT_RUNTIME_BACKOFF_MAX,
    ) -> None:
        self.cloud_runtime_path = Path(cloud_runtime_path)
        self.profile = profile
        self.health_ttl = health_ttl
        self.restart_max = restart_max
        self.backoff_init = backoff_init
        self.backoff_max = backoff_max

        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._restart_count = 0
        self._last_health_ts = 0.0
        self._healthy = False
        self._running = False

    # ── Runtime Discovery ────────────────────────────────────────────────────

    def discover(self) -> Dict[str, Any]:
        """Locate all required runtime components.

        Returns a discovery report with paths and availability.
        """
        report = {
            "cloud_runtime": self._discover_cloud_runtime(),
            "llama_server": self._discover_llama_server(),
            "gguf_models": self._discover_gguf_models(),
            "profile": self.profile,
            "valid": False,
        }
        report["valid"] = all(
            v.get("exists", False) for k, v in report.items()
            if k in ("cloud_runtime", "llama_server") and isinstance(v, dict)
        )
        return report

    def _discover_cloud_runtime(self) -> Dict[str, Any]:
        """Discover CloudRuntime executable."""
        main_py = self.cloud_runtime_path / "main.py"
        return {
            "path": str(main_py),
            "exists": main_py.is_file(),
            "type": "python",
        }

    def _discover_llama_server(self) -> Dict[str, Any]:
        """Discover llama-server binary."""
        candidates = [
            Path(os.environ.get("NIBLIT_LLAMA_BINARY", "")),
            Path(_WINDOWS_LLAMA_CPP_ROOT) / "build" / "bin" / "llama-server.exe",
            Path(_WINDOWS_LLAMA_CPP_ROOT) / "build" / "bin" / "llama-server",
            Path("llama-server"),
            Path("build/bin/llama-server"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return {
                    "path": str(candidate),
                    "exists": True,
                    "type": "binary",
                }
        return {
            "path": "",
            "exists": False,
            "type": "unknown",
        }

    def _discover_gguf_models(self) -> Dict[str, Any]:
        """Discover available GGUF models."""
        models = {}
        model_root = Path(_WINDOWS_MODEL_ROOT)
        if model_root.is_dir():
            for gguf in model_root.glob("*.gguf"):
                models[gguf.stem] = str(gguf)
        return {
            "root": str(model_root),
            "models": models,
            "count": len(models),
        }

    # ── Runtime Validation ───────────────────────────────────────────────────

    def validate(self) -> Dict[str, Any]:
        """Validate all runtime prerequisites.

        Returns a validation report.
        """
        discovery = self.discover()
        errors = []
        warnings = []

        # CloudRuntime check
        if not discovery["cloud_runtime"]["exists"]:
            errors.append("CloudRuntime main.py not found")

        # llama-server check (warning only — CloudRuntime may manage this)
        if not discovery["llama_server"]["exists"]:
            warnings.append("llama-server binary not found (CloudRuntime may manage this)")

        # GGUF models check
        if discovery["gguf_models"]["count"] == 0:
            warnings.append("No GGUF models found")

        return {
            "valid": len(errors) == 0,
            "discovery": discovery,
            "errors": tuple(errors),
            "warnings": tuple(warnings),
        }

    # ── Runtime Coordination ─────────────────────────────────────────────────

    def launch(self, wait_for_ready: bool = True, timeout: float = 60.0) -> Dict[str, Any]:
        """Launch CloudRuntime and wait for READY state.

        Args:
            wait_for_ready: If True, block until CloudRuntime is READY
            timeout: Maximum seconds to wait for READY

        Returns:
            Launch report with status and details
        """
        with self._lock:
            if self._running and self._healthy and self._process and self._process.poll() is None:
                return {
                    "status": "already_running",
                    "pid": self._process.pid,
                    "healthy": self._healthy,
                }

            validation = self.validate()
            if not validation["valid"]:
                return {
                    "status": "validation_failed",
                    "errors": validation["errors"],
                }

            try:
                self._process = self._spawn_cloud_runtime()
                self._running = True
                self._restart_count = 0
            except Exception as exc:
                log.error("[LocalBrain] Failed to launch CloudRuntime: %s", exc)
                return {
                    "status": "launch_failed",
                    "error": str(exc),
                }

        if wait_for_ready and self._process:
            ready = self._wait_for_ready(timeout)
            if not ready:
                return {
                    "status": "timeout",
                    "pid": self._process.pid if self._process else None,
                }

        return {
            "status": "launched",
            "pid": self._process.pid if self._process else None,
            "healthy": self._healthy,
        }

    def _spawn_cloud_runtime(self) -> subprocess.Popen:
        """Spawn CloudRuntime as a subprocess."""
        main_py = self.cloud_runtime_path / "main.py"
        cmd = [
            sys.executable,
            str(main_py),
        ]
        log.info("[LocalBrain] Launching CloudRuntime: %s", cmd)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cloud_runtime_path),
        )
        return process

    def _wait_for_ready(self, timeout: float) -> bool:
        """Wait for CloudRuntime to reach READY state."""
        start = time.time()
        health_url = f"http://127.0.0.1:{_NIBLIT_CLOUD_SERVER_PRIMARY_PORT}/healthz"

        while time.time() - start < timeout:
            if self._process and self._process.poll() is not None:
                log.error("[LocalBrain] CloudRuntime process exited with code %d", self._process.returncode)
                return False

            if self._check_health(health_url):
                self._healthy = True
                self._last_health_ts = time.time()
                log.info("[LocalBrain] CloudRuntime is READY")
                return True

            time.sleep(0.5)

        log.warning("[LocalBrain] CloudRuntime did not reach READY within %.1f seconds", timeout)
        return False

    # ── Runtime Monitoring ───────────────────────────────────────────────────

    def monitor(self) -> Dict[str, Any]:
        """Monitor CloudRuntime health.

        Returns current health status.
        """
        health_url = f"http://127.0.0.1:{_NIBLIT_CLOUD_SERVER_PRIMARY_PORT}/healthz"
        status_url = f"http://127.0.0.1:{_NIBLIT_CLOUD_SERVER_PRIMARY_PORT}/v1/runtime/status"

        healthy = self._check_health(health_url)
        now = time.time()

        with self._lock:
            if healthy:
                self._healthy = True
                self._last_health_ts = now
            else:
                self._healthy = False

            # Check if process died
            process_alive = self._process is not None and self._process.poll() is None
            if self._running and not process_alive:
                self._running = False
                self._healthy = False

        result = {
            "healthy": self._healthy,
            "running": self._running,
            "last_check_ts": now,
            "last_healthy_ts": self._last_health_ts,
        }

        # Get detailed status if healthy
        if healthy:
            try:
                status = self._http_get_json(status_url)
                result["runtime_status"] = status
            except Exception as exc:
                result["status_error"] = str(exc)

        return result

    def _check_health(self, url: str) -> bool:
        """Check if a URL is reachable."""
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return False

    def _http_get_json(self, url: str) -> Dict[str, Any]:
        """Make HTTP GET request and parse JSON response."""
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    # ── Runtime Status ───────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Get unified runtime status.

        Returns status for UI, RuntimeManager, diagnostics, and scheduler.
        """
        monitor_result = self.monitor()
        discovery = self.discover()
        validation = self.validate()

        return {
            "local_brain": {
                "profile": self.profile,
                "running": self._running,
                "healthy": self._healthy,
                "restart_count": self._restart_count,
                "last_health_ts": self._last_health_ts,
            },
            "cloud_runtime": monitor_result,
            "discovery": discovery,
            "validation": validation,
        }

    # ── Runtime Recovery ─────────────────────────────────────────────────────

    def recover(self, max_attempts: Optional[int] = None) -> Dict[str, Any]:
        """Attempt to recover CloudRuntime if unhealthy.

        Uses exponential backoff for restart attempts.

        Args:
            max_attempts: Maximum restart attempts (defaults to configured limit)

        Returns:
            Recovery report
        """
        if max_attempts is None:
            max_attempts = self.restart_max

        if self._healthy and self._running and self._process and self._process.poll() is None:
            return {
                "status": "already_healthy",
                "restart_count": self._restart_count,
            }

        if self._restart_count >= max_attempts:
            return {
                "status": "max_restarts_exceeded",
                "restart_count": self._restart_count,
                "max": max_attempts,
            }

        # Exponential backoff
        backoff = min(
            self.backoff_init * (2 ** self._restart_count),
            self.backoff_max,
        )

        log.warning(
            "[LocalBrain] Recovering CloudRuntime (attempt %d/%d, backoff=%.1fs)",
            self._restart_count + 1, max_attempts, backoff,
        )

        time.sleep(backoff)

        # Stop existing process if alive
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

        with self._lock:
            self._process = None
            self._running = False
            self._healthy = False
            self._restart_count += 1

        # Relaunch
        result = self.launch(wait_for_ready=True, timeout=60.0)

        if result.get("status") == "launched" and self._healthy:
            log.info("[LocalBrain] CloudRuntime recovered successfully")
            return {
                "status": "recovered",
                "restart_count": self._restart_count,
                "pid": result.get("pid"),
            }
        else:
            log.error("[LocalBrain] CloudRuntime recovery failed: %s", result.get("status"))
            return {
                "status": "recovery_failed",
                "restart_count": self._restart_count,
                "detail": result,
            }

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def shutdown(self) -> Dict[str, Any]:
        """Gracefully shutdown CloudRuntime.

        Returns shutdown report.
        """
        with self._lock:
            if not self._process or self._process.poll() is not None:
                return {"status": "not_running"}

            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    self._process.kill()
                    self._process.wait(timeout=5)
                except Exception as exc:
                    log.error("[LocalBrain] Force kill failed: %s", exc)

            self._running = False
            self._healthy = False
            log.info("[LocalBrain] CloudRuntime shutdown complete")
            return {"status": "shutdown", "pid": self._process.pid}


# ── Singleton ────────────────────────────────────────────────────────────────
_gateway: Optional[LocalBrainGateway] = None
_gateway_lock = threading.Lock()


def get_local_brain() -> LocalBrainGateway:
    """Return the process-wide LocalBrainGateway singleton."""
    global _gateway
    with _gateway_lock:
        if _gateway is None:
            _gateway = LocalBrainGateway()
    return _gateway


def reset_local_brain() -> None:
    """Discard the current singleton so the next get_local_brain() creates fresh."""
    global _gateway
    with _gateway_lock:
        _gateway = None


# ── Backwards-compatible APIs ────────────────────────────────────────────────
# These maintain compatibility with existing code that imports from local_brain.
# They are deprecated and will be removed in a future version.

class QwenLocalBrain:
    """DEPRECATED: Legacy compatibility shim.

    This class now delegates to CloudRuntime via HTTP REST.
    Inference is performed by CloudRuntime, not LocalBrain.

    This shim exists only to maintain backwards compatibility during the
    transition to the new Runtime Gateway architecture.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        log.warning(
            "[LocalBrain] QwenLocalBrain is deprecated. Use CloudRuntime via HTTP REST. "
            "See docs/LOCALBRAIN_NEXT_GENERATION.md for the new architecture."
        )
        self.gateway = get_local_brain()
        self._model_name = "cloud-runtime"

    def generate(
        self,
        prompt: str,
        max_new_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """DEPRECATED: Delegate to CloudRuntime."""
        return self.chat(prompt, max_new_tokens=max_new_tokens, system_prompt=system_prompt)

    def chat(
        self,
        prompt: str,
        max_new_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """DEPRECATED: Delegate to CloudRuntime via HTTP."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self._call_cloud_runtime(messages, max_new_tokens or _MAX_NEW_TOKENS)

    def ask(self, prompt: str, context: str = "", system_prompt: Optional[str] = None) -> str:
        """DEPRECATED: Convenience wrapper."""
        full = f"{context.strip()}\n\n{prompt.strip()}" if context.strip() else prompt.strip()
        return self.chat(full, system_prompt=system_prompt)

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """DEPRECATED: Tool-calling wrapper."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self._call_cloud_runtime(messages, _MAX_NEW_TOKENS)

    def _call_cloud_runtime(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        """Call CloudRuntime HTTP API."""
        base_url = f"http://127.0.0.1:{_NIBLIT_CLOUD_SERVER_PRIMARY_PORT}"
        payload = json.dumps({
            "model": "local",
            "messages": messages,
            "max_tokens": max_tokens,
        }).encode("utf-8")

        for path in ("/v1/chat/completions", "/chat/completions", "/chat"):
            try:
                req = urllib.request.Request(
                    f"{base_url}{path}",
                    data=payload,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return content.strip() or "[LocalBrain: empty response]"
            except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError):
                continue

        return "[LocalBrain error: CloudRuntime unreachable]"


class BrainTrainer:
    """DEPRECATED: Legacy compatibility shim.

    BrainTrainer has moved to niblit_brain.py.
    This shim exists only for backwards compatibility.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        log.warning(
            "[LocalBrain] BrainTrainer is deprecated. "
            "Use NiblitBrain in niblit_brain.py instead. "
            "See docs/LOCALBRAIN_NEXT_GENERATION.md for the new architecture."
        )
        self.memory = kwargs.get("memory")
        self._pairs: list = []
        self._facts: list = []

    def record_exchange(self, user_prompt: str, assistant_response: str) -> None:
        """DEPRECATED: No-op."""
        pass

    def ingest_research(self, topic: str, text: str) -> None:
        """DEPRECATED: No-op."""
        pass

    def get_training_context(self, limit: int = 8) -> str:
        """DEPRECATED: Return empty context."""
        return ""


class NiblitCloudBrain:
    """DEPRECATED: Legacy compatibility shim.

    NiblitCloudBrain has moved to NiblitBrain in niblit_brain.py.
    This shim exists only for backwards compatibility.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        log.warning(
            "[LocalBrain] NiblitCloudBrain is deprecated. "
            "Use CloudRuntime HTTP endpoints directly. "
            "See docs/LOCALBRAIN_NEXT_GENERATION.md for the new architecture."
        )
        self.base_url = f"http://127.0.0.1:{_NIBLIT_CLOUD_SERVER_PRIMARY_PORT}"

    def chat(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 512) -> str:
        """DEPRECATED: Delegate to CloudRuntime."""
        brain = QwenLocalBrain()
        return brain.chat(prompt, max_new_tokens=max_tokens, system_prompt=system_prompt)

    def ask(self, prompt: str, context: str = "", system_prompt: Optional[str] = None) -> str:
        """DEPRECATED: Delegate to chat()."""
        return self.chat(prompt, system_prompt=system_prompt)


# ── Legacy helper functions ──────────────────────────────────────────────────

def swap_local_brain(preset: str) -> QwenLocalBrain:
    """DEPRECATED: Return a compatibility shim.

    Model switching is now handled by CloudRuntime via HTTP REST.
    See POST /v1/runtime/model/switch
    """
    log.warning(
        "[LocalBrain] swap_local_brain() is deprecated. "
        "Use CloudRuntime POST /v1/runtime/model/switch instead."
    )
    return QwenLocalBrain()


def set_backend_url(url: str, backend: str = "http") -> QwenLocalBrain:
    """DEPRECATED: No-op.

    Backend configuration is now handled by CloudRuntime.
    """
    log.warning(
        "[LocalBrain] set_backend_url() is deprecated. "
        "Configure CloudRuntime directly."
    )
    return QwenLocalBrain()


def get_backend_info() -> Dict[str, str]:
    """DEPRECATED: Return legacy backend info."""
    log.warning("[LocalBrain] get_backend_info() is deprecated.")
    return {
        "backend": _NIBLIT_GGUF_BACKEND,
        "llama_server_url": _NIBLIT_LLAMA_SERVER_URL,
        "cloud_server_url": f"http://127.0.0.1:{_NIBLIT_CLOUD_SERVER_PRIMARY_PORT}",
    }


def acquire_model_lock(timeout: float = 30.0) -> bool:
    """DEPRECATED: No-op lock for backwards compatibility."""
    log.debug("[LocalBrain] acquire_model_lock() is deprecated (no-op)")
    return _MODEL_SWITCH_LOCK.acquire(timeout=timeout)


def release_model_lock() -> None:
    """DEPRECATED: No-op lock release for backwards compatibility."""
    log.debug("[LocalBrain] release_model_lock() is deprecated (no-op)")
    try:
        _MODEL_SWITCH_LOCK.release()
    except RuntimeError:
        pass


# ── Legacy helpers and constants (for backwards compatibility) ────────────────
# These are kept solely to satisfy existing imports in tests and other modules.
# New code should NOT rely on them.

_GGUF_TEMPLATES: Dict[str, str] = {}


def _build_gguf_prompt(prompt: str, template: str = "qwen", system_prompt: str = "") -> str:
    """DEPRECATED: Legacy prompt builder. CloudRuntime handles templating."""
    log.debug("[LocalBrain] _build_gguf_prompt() is deprecated (no-op)")
    return prompt


def _clean_subprocess_output(output: str, full_prompt: str) -> str:
    """DEPRECATED: Legacy output cleaner."""
    log.debug("[LocalBrain] _clean_subprocess_output() is deprecated (no-op)")
    return output


def _resolve_portable_model_path(preset: str) -> str:
    """DEPRECATED: Return empty string."""
    log.debug("[LocalBrain] _resolve_portable_model_path() is deprecated (no-op)")
    return ""


class _LocalBrainConfig:
    """DEPRECATED: Legacy config singleton.

    CloudRuntime and CloudConfig now own configuration.
    This stub exists only for backwards compatibility.
    """

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)


def _cfg() -> _LocalBrainConfig:
    """DEPRECATED: Return legacy config singleton."""
    global _LocalBrainConfig
    if not hasattr(_cfg, "_instance"):
        _cfg._instance = _LocalBrainConfig()
    return _cfg._instance


# Legacy constants for imports
# Note: some callers import the underscored names, others import without underscore.
_NIBLIT_KB_TOOLS: list = []
_NIBLIT_ALL_TOOLS: list = []
_NIBLIT_SLIM_TOOLS: list = []
NIBLIT_KB_TOOLS = _NIBLIT_KB_TOOLS
NIBLIT_ALL_TOOLS = _NIBLIT_ALL_TOOLS
NIBLIT_SLIM_TOOLS = _NIBLIT_SLIM_TOOLS
_SLIM_SYSTEM_PROMPT = _SHORT_CHAT_SYSTEM_PROMPT
