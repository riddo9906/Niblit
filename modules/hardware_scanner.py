"""
hardware_scanner.py — Niblit Hardware Scanner
==============================================
Cross-platform hardware profiling module.  Detects CPU architecture, RAM,
storage, GPU, network interfaces, sensors, and host-platform type (PC,
Android/Termux, console, car/embedded, server) and stores the profile in the
Niblit knowledge-base.

Singleton access via ``get_hardware_scanner()``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Optional heavy dependencies (graceful fallback) ───────────────────────────
try:
    import psutil
    _PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL = False

# ─────────────────────────────────────────────────────────────────────────────
# Platform-type detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_platform_type() -> str:
    """Return a human label for the host platform type."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    # Android / Termux
    if "android" in system or os.path.exists("/data/data/com.termux"):
        return "android"
    # Windows
    if system == "windows":
        return "pc_windows"
    # macOS
    if system == "darwin":
        return "pc_macos"
    # Linux — try to distinguish server / desktop / embedded / car
    if system == "linux":
        # Termux on Android
        if os.path.exists("/data/data/com.termux") or "termux" in os.environ.get("PREFIX", "").lower():
            return "android_termux"
        # Raspberry Pi / embedded ARM
        if "arm" in machine or "aarch64" in machine:
            try:
                model = Path("/proc/device-tree/model").read_text(errors="replace").lower()
                if "raspberry" in model:
                    return "embedded_raspberry_pi"
                if any(k in model for k in ("jetson", "tegra")):
                    return "embedded_nvidia_jetson"
                return "embedded_arm"
            except Exception:
                return "embedded_arm"
        # Generic Linux x86_64
        return "pc_linux"
    # FreeBSD / OpenBSD etc.
    if "bsd" in system:
        return "pc_bsd"
    return f"unknown_{system}"


def _cpu_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python_bits": platform.architecture()[0],
        "cores_physical": None,
        "cores_logical": None,
        "max_freq_mhz": None,
        "current_freq_mhz": None,
    }
    if _PSUTIL:
        try:
            info["cores_physical"] = psutil.cpu_count(logical=False)
            info["cores_logical"] = psutil.cpu_count(logical=True)
            freq = psutil.cpu_freq()
            if freq:
                info["max_freq_mhz"] = round(freq.max, 1)
                info["current_freq_mhz"] = round(freq.current, 1)
        except Exception:
            pass
    # Try lscpu as fallback on Linux
    if info["processor"] in ("", "unknown") and shutil.which("lscpu"):
        try:
            out = subprocess.check_output(["lscpu"], text=True, timeout=5)
            for line in out.splitlines():
                if "Model name" in line:
                    info["processor"] = line.split(":", 1)[-1].strip()
                    break
        except Exception:
            pass
    return info


def _ram_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {"total_gb": None, "available_gb": None, "used_percent": None}
    if _PSUTIL:
        try:
            vm = psutil.virtual_memory()
            info["total_gb"] = round(vm.total / 1024 ** 3, 2)
            info["available_gb"] = round(vm.available / 1024 ** 3, 2)
            info["used_percent"] = vm.percent
        except Exception:
            pass
    return info


def _storage_info() -> List[Dict[str, Any]]:
    drives: List[Dict[str, Any]] = []
    if _PSUTIL:
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    drives.append({
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / 1024 ** 3, 2),
                        "free_gb": round(usage.free / 1024 ** 3, 2),
                        "used_percent": usage.percent,
                    })
                except Exception:
                    drives.append({"mountpoint": part.mountpoint, "fstype": part.fstype})
        except Exception:
            pass
    return drives


def _gpu_info() -> List[Dict[str, Any]]:
    gpus: List[Dict[str, Any]] = []
    # Try nvidia-smi
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                text=True, timeout=10,
            )
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                gpus.append({
                    "name": parts[0] if parts else "unknown",
                    "vram_mb": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                    "driver": parts[2] if len(parts) > 2 else None,
                    "type": "nvidia",
                })
        except Exception:
            pass
    # Try rocm-smi for AMD
    if not gpus and shutil.which("rocm-smi"):
        try:
            out = subprocess.check_output(["rocm-smi", "--showproductname"], text=True, timeout=10)
            for line in out.strip().splitlines():
                if "GPU" in line:
                    gpus.append({"name": line.strip(), "type": "amd"})
        except Exception:
            pass
    # Linux /proc/driver/nvidia fallback
    if not gpus:
        try:
            nv = Path("/proc/driver/nvidia/gpus")
            if nv.exists():
                for gpu_dir in nv.iterdir():
                    info_file = gpu_dir / "information"
                    if info_file.exists():
                        text = info_file.read_text(errors="replace")
                        name = "unknown"
                        for ln in text.splitlines():
                            if "Model" in ln:
                                name = ln.split(":", 1)[-1].strip()
                                break
                        gpus.append({"name": name, "type": "nvidia_proc"})
        except Exception:
            pass
    return gpus


def _network_info() -> List[Dict[str, Any]]:
    ifaces: List[Dict[str, Any]] = []
    if _PSUTIL:
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for name, addr_list in addrs.items():
                st = stats.get(name)
                ipv4 = next((a.address for a in addr_list if a.family.name == "AF_INET"), None)
                ifaces.append({
                    "name": name,
                    "ipv4": ipv4,
                    "is_up": st.isup if st else None,
                    "speed_mbps": st.speed if st else None,
                })
        except Exception:
            pass
    return ifaces


def _os_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "node": platform.node(),
    }
    # Android extra info
    if os.path.exists("/data/data/com.termux"):
        try:
            prop = subprocess.check_output(
                ["getprop", "ro.build.version.release"], text=True, timeout=5
            ).strip()
            info["android_version"] = prop
        except Exception:
            pass
    return info


# ─────────────────────────────────────────────────────────────────────────────
# HardwareScanner
# ─────────────────────────────────────────────────────────────────────────────

class HardwareScanner:
    """Scans host hardware, caches the profile, and stores it in Niblit's KB."""

    _CACHE_KEY = "niblit_hardware_profile"

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        autoscan: bool = True,
        scan_interval_hours: float = 6.0,
    ) -> None:
        self.knowledge_db = knowledge_db
        self.scan_interval_hours = scan_interval_hours
        self._profile: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._last_scan: float = 0.0

        if autoscan:
            self._run_scan_background()

    # ── Public API ────────────────────────────────────────────────────────────

    def scan(self) -> Dict[str, Any]:
        """Run a full hardware scan and return the profile dict."""
        with self._lock:
            profile = self._collect()
            self._profile = profile
            self._last_scan = time.time()
            self._store(profile)
            return profile

    def get_profile(self) -> Dict[str, Any]:
        """Return the cached profile (scanning if no cache exists)."""
        if self._profile is None:
            return self.scan()
        return self._profile

    def summary(self) -> str:
        """Return a human-readable hardware summary."""
        p = self.get_profile()
        cpu = p.get("cpu", {})
        ram = p.get("ram", {})
        gpus = p.get("gpus", [])
        storage = p.get("storage", [])
        ptype = p.get("platform_type", "unknown")

        lines = [
            f"🖥  Platform : {ptype}",
            f"🔧 OS       : {p.get('os', {}).get('system', '?')} {p.get('os', {}).get('release', '')}",
            f"⚙️  CPU      : {cpu.get('processor', '?')}  "
            f"[{cpu.get('architecture', '?')}] "
            f"{cpu.get('cores_logical', '?')} threads",
        ]
        if ram.get("total_gb") is not None:
            lines.append(
                f"🧠 RAM      : {ram['total_gb']} GB total  "
                f"({ram.get('available_gb', '?')} GB free)"
            )
        if gpus:
            gpu_str = ", ".join(g.get("name", "?") for g in gpus)
            lines.append(f"🎮 GPU      : {gpu_str}")
        for drv in storage[:3]:
            lines.append(
                f"💾 Storage  : {drv.get('mountpoint', '?')}  "
                f"{drv.get('total_gb', '?')} GB  "
                f"({drv.get('free_gb', '?')} GB free)"
            )
        return "\n".join(lines)

    def requirements_report(self) -> str:
        """Produce a Niblit deployment recommendation for this hardware."""
        p = self.get_profile()
        ptype = p.get("platform_type", "")
        ram = p.get("ram", {})
        total_gb = ram.get("total_gb") or 0
        cpu = p.get("cpu", {})
        arch = cpu.get("architecture", "").lower()
        lines = ["📋 Niblit Deployment Recommendation"]
        lines.append(f"   Platform : {ptype}")

        if "android" in ptype:
            lines.append("   Mode     : Termux / Android daemon (niblit_boot.sh)")
            lines.append("   Startup  : boot/install.sh (Termux boot hook)")
            lines.append("   Storage  : /data/data/com.termux/files/home/niblit_data/")
        elif "windows" in ptype:
            lines.append("   Mode     : Windows Service (boot/install_windows.bat)")
            lines.append("   Startup  : NSSM or Windows Task Scheduler")
        elif "darwin" in ptype:
            lines.append("   Mode     : macOS LaunchAgent (boot/niblit.plist)")
            lines.append("   Startup  : launchctl load ~/Library/LaunchAgents/niblit.plist")
        elif "embedded" in ptype:
            lines.append("   Mode     : Embedded / SBC (systemd service, low-mem config)")
            lines.append("   Startup  : boot/install.sh")
            if total_gb < 1:
                lines.append("   ⚠️  Low RAM — enable NIBLIT_LITE_MODE=1")
        else:
            lines.append("   Mode     : Linux systemd service (boot/install.sh)")
            lines.append("   Startup  : systemctl enable niblit && systemctl start niblit")

        if "arm" in arch or "aarch64" in arch:
            lines.append("   Arch     : ARM — ensure Python 3.10+ and psutil are installed")
        if total_gb >= 8:
            lines.append("   Memory   : Sufficient for full Niblit stack + LLM inference")
        elif total_gb >= 2:
            lines.append("   Memory   : Moderate — recommend HF_TOKEN for remote LLM only")
        else:
            lines.append("   Memory   : Low — use NIBLIT_LITE_MODE=1, disable local LLM")

        return "\n".join(lines)

    def status(self) -> str:
        age = time.time() - self._last_scan
        age_str = f"{age / 60:.1f} min ago" if self._last_scan > 0 else "never"
        p = self.get_profile()
        return (
            f"HardwareScanner | last scan: {age_str} | "
            f"platform: {p.get('platform_type', '?')} | "
            f"CPU: {p.get('cpu', {}).get('architecture', '?')}"
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _collect(self) -> Dict[str, Any]:
        return {
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform_type": _detect_platform_type(),
            "os": _os_info(),
            "cpu": _cpu_info(),
            "ram": _ram_info(),
            "storage": _storage_info(),
            "gpus": _gpu_info(),
            "network": _network_info(),
            "python_version": sys.version,
        }

    def _store(self, profile: Dict[str, Any]) -> None:
        if self.knowledge_db is None:
            return
        try:
            summary = (
                f"Hardware: {profile.get('platform_type')} | "
                f"CPU: {profile['cpu'].get('processor', '?')} "
                f"[{profile['cpu'].get('architecture', '?')}] | "
                f"RAM: {profile['ram'].get('total_gb', '?')} GB | "
                f"OS: {profile['os'].get('system', '?')} {profile['os'].get('release', '')}"
            )[:400]
            self.knowledge_db.add_fact(self._CACHE_KEY, summary)
            log.debug("[HardwareScanner] profile stored in KB")
        except Exception as e:
            log.debug("[HardwareScanner] KB store failed: %s", e)

    def _run_scan_background(self) -> None:
        def _loop() -> None:
            self.scan()
            while True:
                time.sleep(self.scan_interval_hours * 3600)
                self.scan()
        t = threading.Thread(target=_loop, daemon=True, name="niblit-hw-scanner")
        t.start()


# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[HardwareScanner] = None
_LOCK = threading.Lock()


def get_hardware_scanner(
    knowledge_db: Optional[Any] = None,
    autoscan: bool = True,
) -> HardwareScanner:
    """Return the process-wide HardwareScanner singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = HardwareScanner(knowledge_db=knowledge_db, autoscan=autoscan)
    return _INSTANCE
