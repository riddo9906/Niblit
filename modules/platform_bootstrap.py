"""
platform_bootstrap.py — Niblit Platform Bootstrap
==================================================
Detects the runtime platform at startup, configures Niblit paths and
capabilities accordingly, and exposes a unified ``PlatformBootstrap`` object
so every other module can query platform capabilities without scattering
``platform.system()`` checks everywhere.

Supported platforms
-------------------
* PC Linux (x86_64 / ARM)
* PC Windows
* PC macOS
* Android / Termux
* Embedded / Raspberry Pi / Jetson
* Car / infotainment (detected via env flag NIBLIT_CAR_MODE=1)
* Console (detected via env flag NIBLIT_CONSOLE_MODE=1)
* Cloud (Vercel / Render / Fly.io — detected via env vars)

Singleton access via ``get_platform_bootstrap()``.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Platform capability constants
# ─────────────────────────────────────────────────────────────────────────────

class Capabilities:
    """Simple namespace of boolean capability flags."""

    def __init__(self, **kwargs: bool) -> None:
        # defaults — everything off
        self.persistent_storage: bool = False
        self.system_service: bool = False
        self.local_llm: bool = False
        self.gpu_inference: bool = False
        self.display: bool = False
        self.audio: bool = False
        self.camera: bool = False
        self.bluetooth: bool = False
        self.usb_control: bool = False
        self.network: bool = True   # almost always available
        self.touch: bool = False
        self.low_memory: bool = False
        for k, v in kwargs.items():
            setattr(self, k, v)

    def as_dict(self) -> Dict[str, bool]:
        return {k: v for k, v in self.__dict__.items()}

# ─────────────────────────────────────────────────────────────────────────────
# Platform detectors
# ─────────────────────────────────────────────────────────────────────────────

def _is_termux() -> bool:
    return (
        os.path.exists("/data/data/com.termux")
        or "termux" in os.environ.get("PREFIX", "").lower()
    )

def _is_cloud() -> bool:
    indicators = (
        "VERCEL", "RENDER", "FLY_APP_NAME",
        "RAILWAY_STATIC_URL", "HEROKU_APP_NAME",
        "K_SERVICE",  # Google Cloud Run
    )
    return any(os.environ.get(k) for k in indicators)

def _is_car() -> bool:
    return os.environ.get("NIBLIT_CAR_MODE", "").strip() in ("1", "true", "yes")

def _is_console() -> bool:
    return os.environ.get("NIBLIT_CONSOLE_MODE", "").strip() in ("1", "true", "yes")

def _is_embedded() -> bool:
    machine = platform.machine().lower()
    if "arm" in machine or "aarch64" in machine:
        try:
            model = Path("/proc/device-tree/model").read_text(errors="replace").lower()
            return any(k in model for k in ("raspberry", "jetson", "tegra", "rock", "orange"))
        except Exception:
            return True  # ARM Linux — assume embedded
    return False

def _total_ram_gb() -> float:
    try:
        import psutil  # type: ignore[import]
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        pass
    try:
        mem_kb = int(Path("/proc/meminfo").read_text().split()[1])
        return mem_kb / 1024 ** 2
    except Exception:
        return 4.0  # assume 4 GB if unknown

# ─────────────────────────────────────────────────────────────────────────────
# PlatformBootstrap
# ─────────────────────────────────────────────────────────────────────────────

class PlatformBootstrap:
    """
    Detects and exposes the current platform profile and capability set.

    Also applies platform-specific bootstrap actions (env var defaults,
    storage path overrides, low-memory tweaks) at construction time.
    """

    def __init__(self) -> None:
        self.platform_type: str = self._detect()
        self.capabilities: Capabilities = self._build_caps()
        self._apply_bootstrap()
        log.info("[PlatformBootstrap] platform=%s caps=%s",
                 self.platform_type,
                 {k: v for k, v in self.capabilities.as_dict().items() if v})

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_mobile(self) -> bool:
        return "android" in self.platform_type

    @property
    def is_cloud(self) -> bool:
        return "cloud" in self.platform_type

    @property
    def is_embedded(self) -> bool:
        return "embedded" in self.platform_type or "car" in self.platform_type

    @property
    def is_windows(self) -> bool:
        return "windows" in self.platform_type

    @property
    def is_macos(self) -> bool:
        return "macos" in self.platform_type

    @property
    def is_linux(self) -> bool:
        return "linux" in self.platform_type or "embedded" in self.platform_type

    def info(self) -> str:
        lines = [
            f"🚀 PlatformBootstrap",
            f"   Type      : {self.platform_type}",
            f"   System    : {platform.system()} {platform.release()}",
            f"   Machine   : {platform.machine()}",
            f"   Python    : {sys.version.split()[0]}",
            f"   Niblit root: {_niblit_root()}",
            "   Capabilities:",
        ]
        for k, v in sorted(self.capabilities.as_dict().items()):
            lines.append(f"     {'✅' if v else '  '} {k}")
        return "\n".join(lines)

    def data_root(self) -> Path:
        """Return the writable data directory for this platform."""
        custom = os.environ.get("NIBLIT_DATA_DIR")
        if custom:
            return Path(custom)
        if _is_cloud():
            return Path(os.environ.get("NIBLIT_DATA_DIR", "/data"))
        if _is_termux():
            prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
            return Path(prefix).parent / "home" / "niblit_data"
        if platform.system() == "Windows":
            return Path(os.environ.get("APPDATA", Path.home())) / "Niblit"
        if platform.system() == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Niblit"
        return Path.home() / ".niblit"

    def requirements_hint(self) -> str:
        """Return human-readable setup hints for the current platform."""
        lines = [f"📋 Platform setup hints for: {self.platform_type}"]
        if _is_termux():
            lines += [
                "  • pkg install python rust openssl git",
                "  • pip install -r requirements.txt",
                "  • run: bash boot/install.sh   (installs Termux:Boot autostart)",
                "  • Install Termux:Boot from F-Droid and grant autostart permission",
            ]
        elif _is_cloud():
            lines += [
                "  • Already running in cloud — no OS installation needed",
                "  • Ensure HF_TOKEN / API keys are set as environment secrets",
            ]
        elif _is_embedded():
            lines += [
                "  • sudo apt install python3 python3-pip git",
                "  • pip install -r requirements.txt",
                "  • bash boot/install.sh  (installs systemd service)",
                "  • Consider NIBLIT_LITE_MODE=1 if RAM < 1 GB",
            ]
        elif platform.system() == "Windows":
            lines += [
                "  • Install Python 3.10+ from python.org",
                "  • pip install -r requirements.txt",
                "  • Run: boot\\install_windows.bat  (as Administrator)",
                "  • Install NSSM from nssm.cc for best Windows Service support",
            ]
        elif platform.system() == "Darwin":
            lines += [
                "  • brew install python@3.12",
                "  • pip install -r requirements.txt",
                "  • bash boot/install.sh  (installs macOS LaunchAgent)",
            ]
        else:
            lines += [
                "  • sudo apt install python3 python3-pip git   (or equivalent)",
                "  • pip install -r requirements.txt",
                "  • bash boot/install.sh  (installs systemd service)",
            ]
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _detect(self) -> str:
        if _is_car():
            return "car_linux"
        if _is_console():
            return "console_linux"
        if _is_cloud():
            return "cloud"
        if _is_termux():
            return "android_termux"
        if _is_embedded():
            m = platform.machine().lower()
            try:
                model = Path("/proc/device-tree/model").read_text(errors="replace").lower()
                if "raspberry" in model:
                    return "embedded_raspberry_pi"
                if any(k in model for k in ("jetson", "tegra")):
                    return "embedded_nvidia_jetson"
            except Exception:
                pass
            return f"embedded_arm_{m}"
        s = platform.system().lower()
        m = platform.machine().lower()
        if s == "linux":
            return f"pc_linux_{m}"
        if s == "windows":
            return "pc_windows"
        if s == "darwin":
            return "pc_macos"
        return f"unknown_{s}"

    def _build_caps(self) -> Capabilities:
        ram = _total_ram_gb()
        low_mem = ram < 2.0
        ptype = self.platform_type
        is_cloud = "cloud" in ptype
        is_android = "android" in ptype
        is_embedded = "embedded" in ptype or "car" in ptype
        is_desktop = any(k in ptype for k in ("pc_linux", "pc_windows", "pc_macos"))

        return Capabilities(
            persistent_storage=not is_cloud,
            system_service=not is_cloud,
            local_llm=not low_mem and not is_cloud,
            gpu_inference=is_desktop and not low_mem,
            display=is_desktop,
            audio=is_desktop or is_android,
            camera=is_android,
            bluetooth=is_android or is_embedded,
            usb_control=is_desktop or is_embedded,
            network=True,
            touch=is_android or "car" in ptype,
            low_memory=low_mem,
        )

    def _apply_bootstrap(self) -> None:
        """Apply platform-specific env defaults and create data directory."""
        data = self.data_root()
        try:
            data.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Override NIBLIT_DATA_DIR so all other modules pick up the right path
        if not os.environ.get("NIBLIT_DATA_DIR"):
            os.environ["NIBLIT_DATA_DIR"] = str(data)

        if self.capabilities.low_memory:
            os.environ.setdefault("NIBLIT_LITE_MODE", "1")
            log.info("[PlatformBootstrap] Low memory detected — NIBLIT_LITE_MODE=1 applied")

        if _is_termux():
            # Termux-specific: make sure PREFIX/bin is on PATH
            prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
            bin_path = f"{prefix}/bin"
            if bin_path not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_path + ":" + os.environ.get("PATH", "")

def _niblit_root() -> Path:
    return Path(__file__).resolve().parent.parent

# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[PlatformBootstrap] = None
_LOCK = threading.Lock()

def get_platform_bootstrap() -> PlatformBootstrap:
    """Return the process-wide PlatformBootstrap singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = PlatformBootstrap()
    return _INSTANCE


if __name__ == "__main__":
    print('Running platform_bootstrap.py')
