#!/usr/bin/env python3
"""Launch niblit-ui as the primary graphical interface (API-attached, non-blocking).

Boot order enforced by :func:`launch_primary_ui`:
  1. Niblit core runtime is already running (caller owns ``core``).
  2. HTTP API layer starts in a daemon thread (``server.py`` bound to *core*).
  3. Optional niblit-cloud-server subprocess (when configured).
  4. niblit-ui dev server, static build, or bundled Tauri exe opens as a separate process.
  5. UI connects via HTTP/WebSocket only — no Python imports in the frontend.

The Niblit core runtime never depends on the UI process lifecycle.

Packaged (PyInstaller) mode
---------------------------
When the process is frozen (``getattr(sys, "frozen", False)`` is True) the launcher
looks for pre-bundled executables relative to the directory that contains
``niblit.exe``.  All existing env-var overrides remain effective and take priority.

  Bundled layout expected by niblit.spec::

    <bundle_base>/
    ├── niblit.exe               ← entry point (this process)
    ├── niblit-ui.exe            ← Tauri UI executable
    └── cloud/
        └── niblit-cloud.exe     ← Cloud-server executable
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("Niblit.UILauncher")

_DEFAULT_API_PORT = int(os.environ.get("NIBLIT_API_PORT", os.environ.get("PORT", "8080")))
_DEFAULT_UI_PORT = int(os.environ.get("NIBLIT_UI_PORT", "5173"))


# ── PyInstaller bundle helpers ────────────────────────────────────────────────

def _bundle_base() -> Optional[Path]:
    """Return the one-folder PyInstaller bundle directory, or *None* when not packaged.

    In one-folder mode ``sys.executable`` is the niblit.exe inside the bundle
    directory.  All sibling resources (niblit-ui.exe, cloud/) are relative to
    that same directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return None


def find_niblit_ui_exe() -> Optional[Path]:
    """Return the path to the bundled Tauri UI executable, or *None*.

    Used in packaged mode only.  Returns None in development mode so that the
    existing :func:`find_niblit_ui_root` / npm-based launch path is used instead.

    Search order:
    1. ``NIBLIT_UI_PATH`` env var pointing to a .exe file.
    2. ``<bundle_base>/niblit-ui.exe`` (staged by niblit-build.js).
    """
    env_path = (
        os.environ.get("NIBLIT_UI_PATH", "").strip()
        or os.environ.get("NIBLIT_UI_ROOT", "").strip()
    )
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        # Accept a direct path to an executable (e.g. niblit-ui.exe on Windows
        # or a bare binary on Linux/macOS).
        if candidate.is_file() and not (candidate / "package.json").exists():
            return candidate

    base = _bundle_base()
    if base is not None:
        candidate = base / "niblit-ui.exe"
        if candidate.is_file():
            return candidate

    return None


@dataclass
class UiLaunchResult:
    """Outcome of a primary UI launch attempt."""

    success: bool
    mode: str = "disabled"  # active | degraded | disabled
    api_url: str = ""
    ui_url: str = ""
    message: str = ""
    _ui_process: Optional[subprocess.Popen] = field(default=None, repr=False)
    _api_thread: Optional[threading.Thread] = field(default=None, repr=False)
    _cloud_process: Optional[subprocess.Popen] = field(default=None, repr=False)

    def wait(self) -> int:
        """Block until the UI process exits (or return 0 when UI was not started)."""
        if self._ui_process is None:
            return 0
        try:
            return self._ui_process.wait()
        except KeyboardInterrupt:
            self.terminate()
            return 130

    def terminate(self) -> None:
        """Stop UI and optional cloud subprocesses (API thread is daemon)."""
        for proc in (self._ui_process, self._cloud_process):
            if proc is None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def find_niblit_ui_root() -> Optional[Path]:
    """Resolve niblit-ui directory.

    Search order (first match wins):
    1. ``NIBLIT_UI_PATH`` or ``NIBLIT_UI_ROOT`` environment variable override.
    2. Sibling of the Niblit repository root (canonical local development layout).
    3. Bundled sub-directory inside the Niblit repository.
    """
    # Accept either env var (NIBLIT_UI_PATH for launcher, NIBLIT_UI_ROOT for orchestrator).
    env_path = (
        os.environ.get("NIBLIT_UI_PATH", "").strip()
        or os.environ.get("NIBLIT_UI_ROOT", "").strip()
    )
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if (candidate / "package.json").is_file():
            return candidate

    here = Path(__file__).resolve().parents[1]
    for sibling in (
        here.parent / "niblit-ui",
        here.parent / "Niblit-ui",
        here / "niblit-ui",
    ):
        if (sibling / "package.json").is_file():
            return sibling.resolve()
    return None


def find_cloud_server_root() -> Optional[Path]:
    """Resolve niblit-cloud-server directory for optional autostart.

    In packaged (PyInstaller) mode the bundled exe is preferred over the source
    directory.  Use :func:`find_cloud_server_exe` when you need the exe path.
    """
    env_path = os.environ.get("NIBLIT_CLOUD_SERVER_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if (candidate / "app" / "main.py").is_file():
            return candidate

    here = Path(__file__).resolve().parents[1]
    for sibling in (
        here.parent / "niblit-cloud-server",
        here.parent / "Niblit-cloud-server",
    ):
        if (sibling / "app" / "main.py").is_file():
            return sibling.resolve()
    return None


def find_cloud_server_exe() -> Optional[Path]:
    """Return the path to the bundled cloud-server executable, or *None*.

    This is the fast-path used in packaged mode.  Returns None when not
    frozen or when the env-var override points at a source directory instead
    of an exe.

    Search order:
    1. ``NIBLIT_CLOUD_SERVER_PATH`` env var pointing directly to a .exe file.
    2. ``<bundle_base>/cloud/niblit-cloud.exe`` (staged by niblit-build.js).
    """
    env_path = os.environ.get("NIBLIT_CLOUD_SERVER_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        # Accept a direct path to an executable (cross-platform: .exe on Windows,
        # bare binary on Linux/macOS).
        if candidate.is_file() and not (candidate / "app" / "main.py").exists():
            return candidate

    base = _bundle_base()
    if base is not None:
        for candidate in (
            base / "cloud" / "niblit-cloud.exe",
            base / "cloud" / "niblit-cloud",
        ):
            if candidate.is_file():
                return candidate

    return None


def _http_ready(url: str, timeout: float = 1.5) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_api_server_thread(core: Any, *, host: str = "127.0.0.1", port: int | None = None) -> tuple[threading.Thread, str]:
    """Start ``server.py`` in a daemon thread bound to the live *core* instance."""
    port = port or _DEFAULT_API_PORT
    api_url = f"http://{host}:{port}"

    if _http_ready(f"{api_url}/health"):
        log.info("[UILauncher] API already listening at %s", api_url)
        return threading.current_thread(), api_url

    import server as _server_module

    _server_module.bind_core(core)

    def _run() -> None:
        import uvicorn

        uvicorn.run(
            _server_module.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )

    thread = threading.Thread(target=_run, name="NiblitAPIServer", daemon=True)
    thread.start()

    deadline = time.monotonic() + float(os.environ.get("NIBLIT_API_START_TIMEOUT", "45"))
    while time.monotonic() < deadline:
        if _http_ready(f"{api_url}/health"):
            log.info("[UILauncher] API ready at %s", api_url)
            return thread, api_url
        time.sleep(0.25)

    raise RuntimeError(f"API server did not become ready at {api_url}")


def maybe_start_cloud_server() -> tuple[Optional[subprocess.Popen], str]:
    """Optionally start niblit-cloud-server (inference layer) as a subprocess.

    In packaged (PyInstaller) mode the bundled ``niblit-cloud.exe`` is used
    directly.  In development mode the source directory is located and
    ``python -m uvicorn app.main:app`` is used instead.
    """
    if os.environ.get("NIBLIT_CLOUD_AUTOSTART", "").strip().lower() not in ("1", "true", "yes"):
        return None, os.environ.get("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000")

    cloud_url = os.environ.get("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
    if _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"):
        log.info("[UILauncher] Cloud server already up at %s", cloud_url)
        return None, cloud_url

    port = urllib.parse.urlparse(cloud_url).port or 8000

    # ── Packaged mode: use pre-bundled niblit-cloud executable ────────────────
    cloud_exe = find_cloud_server_exe()
    if cloud_exe is not None:
        cmd = [
            str(cloud_exe),
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        log.info("[UILauncher] Starting bundled cloud-server: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"):
                return proc, cloud_url
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        log.warning("[UILauncher] Bundled cloud server autostart timed out — inference API may be unavailable")
        return proc, cloud_url

    # ── Development mode: start from source directory via uvicorn ────────────
    cloud_root = find_cloud_server_root()
    if cloud_root is None:
        log.warning("[UILauncher] NIBLIT_CLOUD_AUTOSTART set but cloud-server repo not found")
        return None, cloud_url

    cmd_dev = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    log.info("[UILauncher] Starting cloud-server: %s", " ".join(cmd_dev))
    proc = subprocess.Popen(
        cmd_dev,
        cwd=str(cloud_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"):
            return proc, cloud_url
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    log.warning("[UILauncher] Cloud server autostart timed out — inference API may be unavailable")
    return proc, cloud_url


def _resolve_npm() -> Optional[str]:
    return shutil.which("npm") or shutil.which("npm.cmd")


def _is_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def ensure_ui_build(ui_root: Path, npm: str) -> None:
    """Run ``npm run build`` when production mode needs a static ``dist/`` bundle."""
    dist_index = ui_root / "dist" / "index.html"
    if dist_index.is_file() and not _is_truthy("NIBLIT_UI_FORCE_REBUILD"):
        return
    log.info("[UILauncher] Building niblit-ui (npm run build)…")
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=str(ui_root),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"npm run build failed: {tail or 'unknown error'}")


def launch_ui_process(
    *,
    ui_root: Optional[Path] = None,
    ui_exe: Optional[Path] = None,
    api_url: str,
    cloud_url: str,
    ui_port: int | None = None,
) -> subprocess.Popen:
    """Start niblit-ui as a separate process.

    Accepts either a source *ui_root* (development mode — uses npm) or a
    pre-built *ui_exe* (packaged mode — runs the Tauri executable directly).
    Exactly one of *ui_root* or *ui_exe* must be provided.
    """
    if ui_exe is not None:
        # ── Packaged mode: launch the bundled Tauri exe directly ──────────────
        env = os.environ.copy()
        env["VITE_NIBLIT_API_URL"] = api_url
        env["VITE_NIBLIT_CLOUD_URL"] = cloud_url
        log.info("[UILauncher] Launching bundled niblit-ui: %s", ui_exe)
        return subprocess.Popen([str(ui_exe)], env=env)

    if ui_root is None:
        raise ValueError("launch_ui_process: provide either ui_root or ui_exe")

    # ── Development mode: launch via npm ─────────────────────────────────────
    ui_port = ui_port or _DEFAULT_UI_PORT
    env = os.environ.copy()
    env["VITE_NIBLIT_API_URL"] = api_url
    env["VITE_NIBLIT_CLOUD_URL"] = cloud_url
    env.setdefault("BROWSER", "none")

    npm = _resolve_npm()
    if npm is None:
        raise FileNotFoundError("npm not found on PATH — install Node.js to launch niblit-ui")

    dist_index = ui_root / "dist" / "index.html"
    node_modules = ui_root / "node_modules"
    production = _is_truthy("NIBLIT_UI_PRODUCTION")
    tauri_src = ui_root / "src-tauri" / "tauri.conf.json"
    # Auto-detect Tauri: use it when src-tauri/tauri.conf.json exists unless explicitly
    # disabled via NIBLIT_UI_TAURI=0.  The env var can still force Tauri on (=1) or off (=0).
    tauri_env = os.environ.get("NIBLIT_UI_TAURI", "").strip().lower()
    if tauri_env in ("0", "false", "no"):
        tauri_mode = False
    elif tauri_env in ("1", "true", "yes"):
        tauri_mode = True
    else:
        tauri_mode = tauri_src.is_file()

    if tauri_mode and tauri_src.is_file():
        cmd = [npm, "run", "tauri:dev" if not production else "tauri:build"]
        log.info("[UILauncher] Starting niblit-ui Tauri: %s", " ".join(cmd))
        return subprocess.Popen(cmd, cwd=str(ui_root), env=env)

    if production or not node_modules.is_dir():
        ensure_ui_build(ui_root, npm)
        if not dist_index.is_file():
            raise FileNotFoundError(f"Missing {dist_index} after build")
        cmd = [npm, "run", "preview", "--", "--port", str(ui_port)]
        log.info("[UILauncher] Serving niblit-ui production build on port %s", ui_port)
        return subprocess.Popen(cmd, cwd=str(ui_root), env=env)

    cmd = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(ui_port)]
    log.info("[UILauncher] Starting niblit-ui dev server: %s", " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(ui_root), env=env)


def launch_primary_ui(
    core: Any,
    io: Any | None = None,
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> UiLaunchResult:
    """Start API + optional cloud + niblit-ui. Never raises — returns degraded result on failure."""

    def _say(msg: str) -> None:
        log.info(msg)
        if on_status:
            on_status(msg)
        elif io is not None and hasattr(io, "out"):
            io.out(msg)

    try:
        api_thread, api_url = start_api_server_thread(core)
    except Exception as exc:
        log.warning("[UILauncher] API server failed: %s", exc)
        return UiLaunchResult(success=False, mode="disabled", message=str(exc))

    cloud_proc: Optional[subprocess.Popen] = None
    cloud_url = os.environ.get("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000")
    try:
        cloud_proc, cloud_url = maybe_start_cloud_server()
    except Exception as exc:
        log.warning("[UILauncher] Cloud autostart skipped: %s", exc)

    # ── Resolve the UI: bundled exe (packaged) or source root (dev) ──────────
    ui_exe = find_niblit_ui_exe()
    ui_root = None if ui_exe is not None else find_niblit_ui_root()

    if ui_exe is None and ui_root is None:
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            message="niblit-ui not found (set NIBLIT_UI_PATH or place niblit-ui as a sibling repo)",
            _api_thread=api_thread,
            _cloud_process=cloud_proc,
        )

    ui_port = _DEFAULT_UI_PORT
    try:
        ui_proc = launch_ui_process(
            ui_exe=ui_exe,
            ui_root=ui_root,
            api_url=api_url,
            cloud_url=cloud_url,
            ui_port=ui_port,
        )
    except Exception as exc:
        log.warning("[UILauncher] niblit-ui launch failed: %s", exc)
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            message=str(exc),
            _api_thread=api_thread,
            _cloud_process=cloud_proc,
        )

    ui_url = f"http://127.0.0.1:{ui_port}"
    _say(f"🖥️  niblit-ui primary interface: {ui_url}  (API: {api_url})")
    return UiLaunchResult(
        success=True,
        mode="active",
        api_url=api_url,
        ui_url=ui_url,
        message="niblit-ui launched",
        _ui_process=ui_proc,
        _api_thread=api_thread,
        _cloud_process=cloud_proc,
    )


def ui_launch_supported() -> bool:
    """Return True when primary UI launch should be attempted (not headless CI)."""
    if os.environ.get("NIBLIT_HEADLESS", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("CI", "").strip() == "1":
        return False
    return True
