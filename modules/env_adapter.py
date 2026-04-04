"""
env_adapter.py — Pluggable Environment Adapter Framework for Niblit
====================================================================
Niblit discovers and adapts to every runtime environment it operates in.
Each environment gets an *adapter* that reports its capabilities, resource
limits, and available tool-sets to the ``EnvAdapterRegistry``.  The registry
merges all adapters' capability reports into the cross-environment state via
``EnvStateManager``.

Architecture
------------
* ``BaseEnvAdapter``   — abstract base; every concrete adapter extends this.
* Built-in adapters:
    - ``PythonEnvAdapter``   — Python interpreter + installed packages
    - ``TermuxEnvAdapter``   — Android/Termux-specific tools
    - ``CloudEnvAdapter``    — Vercel / Render / Fly.io / GCP / Azure
    - ``NodeEnvAdapter``     — Node.js runtime (detected via PATH)
    - ``RustEnvAdapter``     — Cargo/rustc (detected via PATH)
    - ``BrowserEnvAdapter``  — Pyodide / WebAssembly context (future)
* ``EnvAdapterRegistry`` — auto-detects and registers applicable adapters,
  exposes ``capabilities()`` as a merged dict and ``learn()`` to refresh.
* Singleton via ``get_env_adapter_registry()``.

Learning model
--------------
Every call to ``registry.learn()`` probes each adapter, merges the results
into ``EnvStateManager``, and stores a knowledge fact via the knowledge_db if
one is provided.  This is how Niblit "comes back better" — the state envelope
accumulates environment knowledge that persists across sessions.
"""

from __future__ import annotations

import importlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Base adapter ──────────────────────────────────────────────────────────────

class BaseEnvAdapter(ABC):
    """Abstract base for all environment adapters."""

    name: str = "base"

    @abstractmethod
    def is_applicable(self) -> bool:
        """Return True if this adapter applies to the current environment."""

    @abstractmethod
    def probe(self) -> Dict[str, Any]:
        """
        Probe the environment and return a dict of discovered capabilities.
        Must be safe and fast (≤2 s).  Never raises — returns empty dict on error.
        """

    def learn(self) -> Dict[str, Any]:
        """
        Extended probe called periodically.  May be slower than ``probe()``.
        Default implementation delegates to ``probe()``.
        """
        return self.probe()


# ── Built-in adapters ─────────────────────────────────────────────────────────

class PythonEnvAdapter(BaseEnvAdapter):
    """Probes the Python interpreter and key installed packages."""

    name = "python"

    def is_applicable(self) -> bool:
        return True  # always applicable — we're running in Python

    def probe(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": f"{platform.system()}/{platform.machine()}",
            "arch": platform.machine(),
        }
        packages_of_interest = [
            "fastapi", "uvicorn", "pydantic", "requests", "httpx",
            "numpy", "torch", "transformers", "openai", "anthropic",
            "qdrant_client", "langchain", "PIL", "cv2",
        ]
        available: List[str] = []
        for pkg in packages_of_interest:
            try:
                importlib.import_module(pkg)
                available.append(pkg)
            except ImportError:
                pass
        caps["python_packages"] = available
        caps["python_path_dirs"] = sys.path[:5]
        return caps


class TermuxEnvAdapter(BaseEnvAdapter):
    """Detects Android/Termux environment and its CLI tools."""

    name = "termux"

    def is_applicable(self) -> bool:
        return (
            os.path.isdir("/data/data/com.termux")
            or "com.termux" in os.environ.get("PREFIX", "")
            or shutil.which("termux-info") is not None
        )

    def probe(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {"termux": True}
        termux_tools = [
            "termux-battery-status", "termux-camera-info",
            "termux-clipboard-get", "termux-info",
            "termux-notification", "termux-tts-speak",
            "termux-wifi-connectioninfo",
        ]
        available = [t for t in termux_tools if shutil.which(t)]
        caps["termux_tools"] = available
        caps["pkg_manager"] = "pkg" if shutil.which("pkg") else None
        caps["ndk_available"] = shutil.which("clang") is not None
        return caps

    def learn(self) -> Dict[str, Any]:
        caps = self.probe()
        # Try to get battery info
        if shutil.which("termux-battery-status"):
            try:
                out = subprocess.check_output(  # noqa: S603
                    ["termux-battery-status"],
                    shell=False, timeout=3, text=True,
                )
                import json as _json
                caps["battery"] = _json.loads(out)
            except Exception:
                pass
        return caps


class CloudEnvAdapter(BaseEnvAdapter):
    """Detects cloud / serverless environments."""

    name = "cloud"

    _CLOUD_MARKERS = {
        "vercel": ("VERCEL", "VERCEL_URL"),
        "render": ("RENDER",),
        "fly": ("FLY_APP_NAME",),
        "gcp_run": ("K_SERVICE", "GOOGLE_CLOUD_PROJECT"),
        "azure": ("WEBSITE_SITE_NAME",),
        "heroku": ("DYNO",),
        "railway": ("RAILWAY_ENVIRONMENT",),
    }

    def is_applicable(self) -> bool:
        return any(
            os.environ.get(v) for vars in self._CLOUD_MARKERS.values() for v in vars
        )

    def probe(self) -> Dict[str, Any]:
        detected: List[str] = []
        for platform_name, env_vars in self._CLOUD_MARKERS.items():
            if any(os.environ.get(v) for v in env_vars):
                detected.append(platform_name)
        caps: Dict[str, Any] = {
            "cloud_platforms": detected,
            "read_only_fs": self._is_read_only(),
            "has_network": True,  # cloud environments always have network
        }
        return caps

    @staticmethod
    def _is_read_only() -> bool:
        return bool(os.environ.get("VERCEL") or os.environ.get("K_SERVICE"))


class NodeEnvAdapter(BaseEnvAdapter):
    """Detects a Node.js runtime on the PATH."""

    name = "node"

    def is_applicable(self) -> bool:
        return shutil.which("node") is not None

    def probe(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {"node_available": True}
        try:
            version = subprocess.check_output(  # noqa: S603
                ["node", "--version"], shell=False, timeout=5, text=True
            ).strip()
            caps["node_version"] = version
        except Exception:
            caps["node_version"] = "unknown"
        caps["npm_available"] = shutil.which("npm") is not None
        caps["npx_available"] = shutil.which("npx") is not None
        caps["yarn_available"] = shutil.which("yarn") is not None
        caps["bun_available"] = shutil.which("bun") is not None
        return caps

    def learn(self) -> Dict[str, Any]:
        caps = self.probe()
        # Check if the Niblit Node node is installed
        niblit_node = shutil.which("niblit-node")
        caps["niblit_node_installed"] = niblit_node is not None
        return caps


class RustEnvAdapter(BaseEnvAdapter):
    """Detects a Rust toolchain on the PATH."""

    name = "rust"

    def is_applicable(self) -> bool:
        return shutil.which("rustc") is not None or shutil.which("cargo") is not None

    def probe(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {"rust_available": True}
        for tool in ("rustc", "cargo", "rustup"):
            if shutil.which(tool):
                try:
                    ver = subprocess.check_output(  # noqa: S603
                        [tool, "--version"], shell=False, timeout=5, text=True
                    ).strip()
                    caps[f"{tool}_version"] = ver
                except Exception:
                    caps[f"{tool}_version"] = "available"
        return caps

    def learn(self) -> Dict[str, Any]:
        caps = self.probe()
        # Check if the Niblit Rust node binary exists
        niblit_bin = shutil.which("niblit-rust") or shutil.which("niblit_rust")
        caps["niblit_rust_installed"] = niblit_bin is not None
        return caps


class LinuxSysAdapter(BaseEnvAdapter):
    """Probes Linux system capabilities (kernel, CPU, memory)."""

    name = "linux_sys"

    def is_applicable(self) -> bool:
        return platform.system().lower() == "linux"

    def probe(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {
            "linux_kernel": platform.release(),
            "cpu_count": os.cpu_count(),
        }
        # Read /proc/meminfo for total memory
        try:
            mem_kb = 0
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_kb = int(line.split()[1])
                        break
            caps["memory_mb"] = mem_kb // 1024
        except Exception:
            pass
        caps["has_docker"] = shutil.which("docker") is not None
        caps["has_systemd"] = shutil.which("systemctl") is not None
        return caps


# ── Registry ──────────────────────────────────────────────────────────────────

class EnvAdapterRegistry:
    """
    Auto-detects applicable environment adapters and merges their capability
    reports into a unified dict.  Feeds discoveries into the cross-environment
    state via ``EnvStateManager``.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self._knowledge_db = knowledge_db
        self._adapters: List[BaseEnvAdapter] = []
        self._capabilities: Dict[str, Any] = {}
        self._last_learn_ts: float = 0.0
        self._detect_adapters()
        log.info(
            "EnvAdapterRegistry ready — adapters: %s",
            [a.name for a in self._adapters],
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def capabilities(self) -> Dict[str, Any]:
        """Return the merged capabilities dict (probed once on startup)."""
        if not self._capabilities:
            self._run_probes()
        return dict(self._capabilities)

    def learn(self, force: bool = False) -> Dict[str, Any]:
        """
        Run extended learning across all adapters.  Rate-limited to once per
        5 minutes unless ``force=True``.

        Updates ``EnvStateManager`` with the result and stores a knowledge fact.
        """
        now = time.time()
        if not force and now - self._last_learn_ts < 300:
            return dict(self._capabilities)

        results: Dict[str, Any] = {}
        for adapter in self._adapters:
            try:
                data = adapter.learn()
                results[adapter.name] = data
                self._capabilities.update({f"{adapter.name}.{k}": v for k, v in data.items()})
            except Exception as exc:
                log.debug("EnvAdapterRegistry: adapter %s learn() failed — %s", adapter.name, exc)

        self._last_learn_ts = now

        # Push into cross-environment state
        try:
            from modules.env_state import get_env_state_manager
            mgr = get_env_state_manager(knowledge_db=self._knowledge_db)
            mgr.update({
                "env_capabilities": self._capabilities,
                "origin_platform": f"{platform.system().lower()}/{platform.machine()}",
            })
            mgr.save()
        except Exception as exc:
            log.debug("EnvAdapterRegistry: could not update env_state — %s", exc)

        # Store knowledge fact
        if self._knowledge_db:
            try:
                adapters_seen = [a.name for a in self._adapters]
                self._knowledge_db.add_fact(
                    "env:adapters:detected",
                    f"Environment adapters active: {', '.join(adapters_seen)} "
                    f"at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                )
            except Exception:
                pass

        log.info("EnvAdapterRegistry.learn() complete — %d capability keys", len(self._capabilities))
        return results

    def register(self, adapter: BaseEnvAdapter) -> None:
        """Register a custom adapter at runtime."""
        if adapter not in self._adapters:
            self._adapters.append(adapter)
            log.debug("EnvAdapterRegistry: registered custom adapter '%s'", adapter.name)

    def adapter_names(self) -> List[str]:
        """Return list of registered adapter names."""
        return [a.name for a in self._adapters]

    def status(self) -> Dict[str, Any]:
        """Return a status summary."""
        return {
            "adapters": self.adapter_names(),
            "capability_keys": len(self._capabilities),
            "last_learn": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._last_learn_ts))
                if self._last_learn_ts else "never"
            ),
        }

    # ── Internal ────────────────────────────────────────────────────────────

    def _detect_adapters(self) -> None:
        """Instantiate and register all applicable built-in adapters."""
        candidates: List[BaseEnvAdapter] = [
            PythonEnvAdapter(),
            TermuxEnvAdapter(),
            CloudEnvAdapter(),
            NodeEnvAdapter(),
            RustEnvAdapter(),
            LinuxSysAdapter(),
        ]
        for adapter in candidates:
            try:
                if adapter.is_applicable():
                    self._adapters.append(adapter)
            except Exception as exc:
                log.debug("EnvAdapterRegistry: is_applicable() failed for %s — %s", adapter.name, exc)

    def _run_probes(self) -> None:
        """Run fast probes on all adapters to populate initial capabilities."""
        for adapter in self._adapters:
            try:
                data = adapter.probe()
                self._capabilities.update({f"{adapter.name}.{k}": v for k, v in data.items()})
            except Exception as exc:
                log.debug("EnvAdapterRegistry: probe() failed for %s — %s", adapter.name, exc)


# ── Singleton ──────────────────────────────────────────────────────────────
import threading

_registry: Optional[EnvAdapterRegistry] = None
_registry_lock = threading.Lock()


def get_env_adapter_registry(
    knowledge_db: Optional[Any] = None,
) -> EnvAdapterRegistry:
    """Return the process-level EnvAdapterRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = EnvAdapterRegistry(knowledge_db=knowledge_db)
                _registry.learn(force=True)
    return _registry
