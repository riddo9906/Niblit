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

from modules.boot_diagnostics import BootDiagnostics, ProcessDiagnostics, is_port_available

log = logging.getLogger("Niblit.UILauncher")

_DEFAULT_API_PORT = int(os.environ.get("NIBLIT_API_PORT", os.environ.get("PORT", "8080")))
_DEFAULT_UI_PORT = int(os.environ.get("NIBLIT_UI_PORT", "5173"))
_DEFAULT_API_HOST = os.environ.get("NIBLIT_API_HOST", "127.0.0.1")
# Bundled desktop builds do not expose an HTTP readiness endpoint, so readiness
# is defined as "the process stayed alive through its initial stabilization
# window without exiting immediately".
_BUNDLED_UI_STABLE_WINDOW_SECONDS = 2.0


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
    readiness: dict[str, str] = field(default_factory=dict)

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


def _diagnostic_emitter(diagnostics: BootDiagnostics) -> Callable[[str], None]:
    return diagnostics.emitter or log.info


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


def _readiness_timeout(env_name: str, default: float) -> float:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _terminate_process(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _spawn_logged_process(
    *,
    name: str,
    cmd: list[str],
    cwd: Optional[Path],
    env: Optional[dict[str, str]],
    diagnostics: BootDiagnostics,
) -> tuple[subprocess.Popen, ProcessDiagnostics]:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if proc.pid is None:
        raise RuntimeError(f"{name} failed to start: missing child PID")
    proc_diag = ProcessDiagnostics(
        name=name,
        command=cmd,
        cwd=cwd,
        pid=int(proc.pid),
        stdout=proc.stdout,
        stderr=proc.stderr,
        emitter=_diagnostic_emitter(diagnostics),
    )
    proc_diag.log_started()
    return proc, proc_diag


def _wait_for_process_ready(
    *,
    name: str,
    proc: subprocess.Popen,
    proc_diag: ProcessDiagnostics,
    timeout: float,
    readiness: Callable[[], bool],
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if readiness():
            return
        exit_code = proc.poll()
        if exit_code is not None:
            proc_diag.dump_failure(exit_code=exit_code)
            raise RuntimeError(f"{name} exited before becoming ready (exit code {exit_code})")
        time.sleep(0.25)
    _terminate_process(proc)
    proc_diag.dump_failure(exit_code=proc.poll())
    raise TimeoutError(f"{name} startup timed out after {timeout:.1f}s")


def _bundled_ui_is_stable(proc: subprocess.Popen, started_at: float, stable_window: float) -> bool:
    return proc.poll() is None and (time.monotonic() - started_at) >= stable_window


def validate_primary_ui_dependencies(
    *,
    diagnostics: BootDiagnostics,
    ui_root: Optional[Path],
    ui_exe: Optional[Path],
    cloud_url: str,
    api_host: str,
    api_port: int,
    ui_port: int,
    tauri_mode: Optional[bool] = None,
) -> dict[str, str]:
    stage = diagnostics.start("Dependency validation")
    readiness: dict[str, str] = {}
    try:
        if not sys.executable:
            raise RuntimeError("Python executable unavailable")
        readiness["python"] = sys.executable

        if _http_ready(f"http://{api_host}:{api_port}/health"):
            readiness["api_port"] = "in_use_by_existing_service"
        elif is_port_available(api_host, api_port):
            readiness["api_port"] = "available"
        else:
            raise RuntimeError(f"API port {api_port} is already in use by another process")

        if os.environ.get("NIBLIT_CLOUD_AUTOSTART", "").strip().lower() in ("1", "true", "yes"):
            if _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"):
                readiness["cloud"] = "already_ready"
            elif find_cloud_server_exe() or find_cloud_server_root():
                readiness["cloud"] = "launchable"
            else:
                raise FileNotFoundError("Cloud Server repository/executable not found")
        else:
            readiness["cloud"] = "disabled"

        if ui_exe is not None:
            readiness["ui"] = str(ui_exe)
        elif ui_root is not None:
            readiness["ui"] = str(ui_root)
            npm = _resolve_npm()
            if npm is None:
                raise FileNotFoundError("npm not found on PATH")
            readiness["npm"] = npm
            if tauri_mode is not True and not is_port_available("127.0.0.1", ui_port):
                raise RuntimeError(f"UI port {ui_port} is already in use by another process")
        else:
            raise FileNotFoundError("UI repository/executable not found")
        diagnostics.success(stage, "dependencies validated")
        return readiness
    except Exception as exc:
        diagnostics.failure(stage, exc)
        raise


def start_api_server_thread(
    core: Any,
    *,
    host: str = _DEFAULT_API_HOST,
    port: int | None = None,
    diagnostics: Optional[BootDiagnostics] = None,
) -> tuple[threading.Thread, str]:
    """Start ``server.py`` in a daemon thread bound to the live *core* instance."""
    port = port or _DEFAULT_API_PORT
    api_url = f"http://{host}:{port}"
    stage = diagnostics.start("API server startup") if diagnostics is not None else None

    if _http_ready(f"{api_url}/health"):
        log.info("[UILauncher] API already listening at %s", api_url)
        if diagnostics is not None and stage is not None:
            diagnostics.success(stage, f"API ready at {api_url}")
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

    deadline = time.monotonic() + _readiness_timeout("NIBLIT_API_START_TIMEOUT", 45.0)
    while time.monotonic() < deadline:
        if _http_ready(f"{api_url}/health"):
            log.info("[UILauncher] API ready at %s", api_url)
            if diagnostics is not None and stage is not None:
                diagnostics.success(stage, f"API ready at {api_url}")
            return thread, api_url
        time.sleep(0.25)

    exc = TimeoutError(f"API server did not become ready at {api_url}")
    if diagnostics is not None and stage is not None:
        diagnostics.failure(stage, exc)
    raise exc


def maybe_start_cloud_server(
    *,
    diagnostics: Optional[BootDiagnostics] = None,
) -> tuple[Optional[subprocess.Popen], str]:
    """Optionally start niblit-cloud-server (inference layer) as a subprocess.

    In packaged (PyInstaller) mode the bundled ``niblit-cloud.exe`` is used
    directly.  In development mode the source directory is located and
    ``python -m uvicorn app.main:app`` is used instead.
    """
    if os.environ.get("NIBLIT_CLOUD_AUTOSTART", "").strip().lower() not in ("1", "true", "yes"):
        return None, os.environ.get("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000")

    cloud_url = os.environ.get("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
    stage = diagnostics.start("Cloud server startup") if diagnostics is not None else None
    if _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"):
        log.info("[UILauncher] Cloud server already up at %s", cloud_url)
        if diagnostics is not None and stage is not None:
            diagnostics.success(stage, f"Cloud ready at {cloud_url}")
        return None, cloud_url

    port = urllib.parse.urlparse(cloud_url).port or 8000
    timeout = _readiness_timeout("NIBLIT_CLOUD_START_TIMEOUT", 120.0)

    # ── Packaged mode: use pre-bundled niblit-cloud executable ────────────────
    cloud_exe = find_cloud_server_exe()
    if cloud_exe is not None:
        cmd = [
            str(cloud_exe),
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        log.info("[UILauncher] Starting bundled cloud-server: %s", " ".join(cmd))
        proc, proc_diag = _spawn_logged_process(
            name="Cloud Server",
            cmd=cmd,
            cwd=None,
            env=os.environ.copy(),
            diagnostics=diagnostics or BootDiagnostics(),
        )
        _wait_for_process_ready(
            name="Cloud Server",
            proc=proc,
            proc_diag=proc_diag,
            timeout=timeout,
            readiness=lambda: _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"),
        )
        if diagnostics is not None and stage is not None:
            diagnostics.success(stage, f"Cloud ready at {cloud_url}")
        return proc, cloud_url

    # ── Development mode: start from source directory via uvicorn ────────────
    cloud_root = find_cloud_server_root()
    if cloud_root is None:
        exc = FileNotFoundError("NIBLIT_CLOUD_AUTOSTART set but cloud-server repo not found")
        if diagnostics is not None and stage is not None:
            diagnostics.failure(stage, exc)
        raise exc

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
    proc, proc_diag = _spawn_logged_process(
        name="Cloud Server",
        cmd=cmd_dev,
        cwd=cloud_root,
        env=os.environ.copy(),
        diagnostics=diagnostics or BootDiagnostics(),
    )
    _wait_for_process_ready(
        name="Cloud Server",
        proc=proc,
        proc_diag=proc_diag,
        timeout=timeout,
        readiness=lambda: _http_ready(f"{cloud_url}/health") or _http_ready(f"{cloud_url}/healthz"),
    )
    if diagnostics is not None and stage is not None:
        diagnostics.success(stage, f"Cloud ready at {cloud_url}")
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
    diagnostics: Optional[BootDiagnostics] = None,
) -> tuple[subprocess.Popen, Optional[ProcessDiagnostics], str]:
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
        proc, proc_diag = _spawn_logged_process(
            name="UI",
            cmd=[str(ui_exe)],
            cwd=ui_exe.parent,
            env=env,
            diagnostics=diagnostics or BootDiagnostics(),
        )
        return proc, proc_diag, "bundled"

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
        proc, proc_diag = _spawn_logged_process(
            name="UI",
            cmd=cmd,
            cwd=ui_root,
            env=env,
            diagnostics=diagnostics or BootDiagnostics(),
        )
        return proc, proc_diag, "tauri"

    if production or not node_modules.is_dir():
        ensure_ui_build(ui_root, npm)
        if not dist_index.is_file():
            raise FileNotFoundError(f"Missing {dist_index} after build")
        cmd = [npm, "run", "preview", "--", "--port", str(ui_port)]
        log.info("[UILauncher] Serving niblit-ui production build on port %s", ui_port)
        proc, proc_diag = _spawn_logged_process(
            name="UI",
            cmd=cmd,
            cwd=ui_root,
            env=env,
            diagnostics=diagnostics or BootDiagnostics(),
        )
        return proc, proc_diag, "preview"

    cmd = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(ui_port)]
    log.info("[UILauncher] Starting niblit-ui dev server: %s", " ".join(cmd))
    proc, proc_diag = _spawn_logged_process(
        name="UI",
        cmd=cmd,
        cwd=ui_root,
        env=env,
        diagnostics=diagnostics or BootDiagnostics(),
    )
    return proc, proc_diag, "dev"


def launch_primary_ui(
    core: Any,
    io: Any | None = None,
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> UiLaunchResult:
    """Start API + optional cloud + niblit-ui. Never raises — returns degraded result on failure."""
    diagnostics = BootDiagnostics(emitter=on_status or (io.out if io is not None and hasattr(io, "out") else None))

    def _say(msg: str) -> None:
        log.info(msg)
        if on_status:
            on_status(msg)
        elif io is not None and hasattr(io, "out"):
            io.out(msg)

    api_host = _DEFAULT_API_HOST
    api_port = _DEFAULT_API_PORT
    ui_port = _DEFAULT_UI_PORT
    cloud_url = os.environ.get("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000")
    ui_exe = find_niblit_ui_exe()
    ui_root = None if ui_exe is not None else find_niblit_ui_root()
    tauri_mode = bool(ui_root and (ui_root / "src-tauri" / "tauri.conf.json").is_file())

    try:
        readiness = validate_primary_ui_dependencies(
            diagnostics=diagnostics,
            ui_root=ui_root,
            ui_exe=ui_exe,
            cloud_url=cloud_url,
            api_host=api_host,
            api_port=api_port,
            ui_port=ui_port,
            tauri_mode=tauri_mode,
        )
        api_thread, api_url = start_api_server_thread(core, host=api_host, port=api_port, diagnostics=diagnostics)
    except Exception as exc:
        return UiLaunchResult(success=False, mode="disabled", message=str(exc))

    cloud_proc: Optional[subprocess.Popen] = None
    try:
        cloud_proc, cloud_url = maybe_start_cloud_server(diagnostics=diagnostics)
        readiness["cloud"] = "ready"
    except Exception as exc:
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            message=str(exc),
            _api_thread=api_thread,
            _cloud_process=cloud_proc,
            readiness=readiness,
        )

    if ui_exe is None and ui_root is None:
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            message="niblit-ui not found (set NIBLIT_UI_PATH or place niblit-ui as a sibling repo)",
            _api_thread=api_thread,
            _cloud_process=cloud_proc,
            readiness=readiness,
        )

    stage = diagnostics.start("UI startup")
    try:
        ui_proc, ui_proc_diag, launch_mode = launch_ui_process(
            ui_exe=ui_exe,
            ui_root=ui_root,
            api_url=api_url,
            cloud_url=cloud_url,
            ui_port=ui_port,
            diagnostics=diagnostics,
        )
        ui_timeout = _readiness_timeout("NIBLIT_UI_START_TIMEOUT", 45.0)
        if launch_mode in {"dev", "preview", "tauri"}:
            _wait_for_process_ready(
                name="UI",
                proc=ui_proc,
                proc_diag=ui_proc_diag,
                timeout=ui_timeout,
                readiness=lambda: _http_ready(f"http://127.0.0.1:{ui_port}"),
            )
            ui_url = f"http://127.0.0.1:{ui_port}"
        else:
            bundled_start_time = time.monotonic()
            bundled_stable_window = _BUNDLED_UI_STABLE_WINDOW_SECONDS
            # Bundled desktop UIs have no HTTP readiness endpoint; if a caller
            # configures a shorter timeout than the stabilization window, prefer
            # the stabilization window so we can still detect immediate crash loops.
            bundled_timeout = max(ui_timeout, bundled_stable_window)
            _wait_for_process_ready(
                name="UI",
                proc=ui_proc,
                proc_diag=ui_proc_diag,
                timeout=bundled_timeout,
                readiness=lambda: _bundled_ui_is_stable(
                    ui_proc,
                    bundled_start_time,
                    bundled_stable_window,
                ),
            )
            ui_url = str(ui_exe) if ui_exe is not None else ""
        readiness["ui"] = "ready"
        diagnostics.success(stage, f"UI ready ({launch_mode})")
    except Exception as exc:
        if stage is not None:
            diagnostics.failure(stage, exc)
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            message=str(exc),
            _api_thread=api_thread,
            _cloud_process=cloud_proc,
            readiness=readiness,
        )

    _say(f"🖥️  niblit-ui primary interface: {ui_url}  (API: {api_url})")
    diagnostics.summary()
    return UiLaunchResult(
        success=True,
        mode="active",
        api_url=api_url,
        ui_url=ui_url,
        message="niblit-ui launched",
        _ui_process=ui_proc,
        _api_thread=api_thread,
        _cloud_process=cloud_proc,
        readiness=readiness,
    )


def ui_launch_supported() -> bool:
    """Return True when primary UI launch should be attempted (not headless CI)."""
    if os.environ.get("NIBLIT_HEADLESS", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("CI", "").strip() == "1":
        return False
    return True
