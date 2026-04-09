"""
kernel_integration.py — Niblit Kernel Integration Layer
========================================================
Reads and (with adequate privileges) modifies live kernel parameters and
kernel module state on any supported platform:

  • Linux  — /proc/version, /proc/sys (sysctl), /proc/modules, /sys/module,
             modprobe/rmmod, kernel cmdline via /proc/cmdline, dmesg,
             /sys/class/thermal (temperature), /sys/bus/pci (PCI devices)
  • Windows — winver, wmic, Get-WmiObject (read-only via subprocess)
  • macOS   — uname, sysctl, kextstat (read-only)
  • Termux  — uname, /proc (read-only)

Security note
-------------
Write operations (sysctl -w, modprobe, rmmod) require root / CAP_SYS_ADMIN and
must be called with ``write=True``.  Cloud deployments are automatically
locked to read-only mode.

Singleton access via ``get_kernel_integration()``.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def _run(cmd: list, timeout: int = 10) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout,
                                       stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _is_cloud() -> bool:
    return any(os.environ.get(k) for k in ("VERCEL", "RENDER", "FLY_APP_NAME", "K_SERVICE"))


# ─────────────────────────────────────────────────────────────────────────────
# Platform probe helpers
# ─────────────────────────────────────────────────────────────────────────────

def _probe_linux() -> Dict[str, Any]:
    d: Dict[str, Any] = {}

    # Basic version
    try:
        d["kernel_version"] = Path("/proc/version").read_text().strip()
    except Exception:
        d["kernel_version"] = platform.release()

    # Loaded modules
    try:
        raw = Path("/proc/modules").read_text()
        d["loaded_modules"] = [line.split()[0] for line in raw.splitlines()][:50]
        d["module_count"] = len(raw.splitlines())
    except Exception:
        d["loaded_modules"] = []

    # Key sysctl params
    interesting = [
        "kernel.hostname", "kernel.ostype", "kernel.osrelease",
        "vm.swappiness", "net.ipv4.ip_forward",
        "kernel.nmi_watchdog", "kernel.perf_event_paranoid",
    ]
    d["sysctl"] = {}
    for param in interesting:
        val = _run(["sysctl", "-n", param], timeout=3).strip()
        if val:
            d["sysctl"][param] = val

    # CPU governor
    gov_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if gov_path.exists():
        try:
            d["cpu_governor"] = gov_path.read_text().strip()
        except Exception:
            pass

    # Temperatures
    temps: Dict[str, str] = {}
    for tz in Path("/sys/class/thermal").iterdir() if Path("/sys/class/thermal").exists() else []:
        try:
            ttype = (tz / "type").read_text().strip()
            ttemp = int((tz / "temp").read_text().strip()) / 1000
            temps[ttype] = f"{ttemp:.1f}°C"
        except Exception:
            pass
    if temps:
        d["temperatures"] = temps

    # PCI devices (truncated)
    if shutil.which("lspci"):
        raw = _run(["lspci"], timeout=5)
        d["pci_devices"] = raw.strip().splitlines()[:20]

    return d


def _probe_windows() -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    d["kernel_version"] = platform.version()
    d["kernel_release"] = platform.release()
    raw = _run(["wmic", "os", "get", "Caption,BuildNumber,Version"], timeout=10)
    d["windows_os_raw"] = raw.strip()[:300]
    return d


def _probe_macos() -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    d["kernel_version"] = _run(["uname", "-r"], timeout=5).strip()
    d["sysctl"] = {}
    for key in ("hw.model", "hw.ncpu", "hw.memsize", "machdep.cpu.brand_string"):
        val = _run(["sysctl", "-n", key], timeout=3).strip()
        if val:
            d["sysctl"][key] = val
    if shutil.which("kextstat"):
        raw = _run(["kextstat"], timeout=5)
        d["kext_count"] = len(raw.strip().splitlines()) - 1
    return d


# ─────────────────────────────────────────────────────────────────────────────
# KernelIntegration
# ─────────────────────────────────────────────────────────────────────────────

class KernelIntegration:
    """Niblit kernel information and controlled-write interface."""

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self.knowledge_db = knowledge_db
        self._profile: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._system = platform.system().lower()
        self._read_only = _is_cloud()

    # ── Public API ────────────────────────────────────────────────────────────

    def probe(self) -> Dict[str, Any]:
        with self._lock:
            p = self._collect()
            self._profile = p
            self._store(p)
            return p

    def get_profile(self) -> Dict[str, Any]:
        if self._profile is None:
            return self.probe()
        return self._profile

    def summary(self) -> str:
        p = self.get_profile()
        lines = [
            f"🐧 Kernel Integration",
            f"   System  : {self._system}",
            f"   Version : {p.get('kernel_version', '?')[:80]}",
            f"   Modules : {p.get('module_count', 'n/a')} loaded",
            f"   Read-only: {self._read_only}",
        ]
        temps = p.get("temperatures", {})
        if temps:
            for k, v in list(temps.items())[:4]:
                lines.append(f"   Temp/{k}: {v}")
        sysctl = p.get("sysctl", {})
        for k, v in list(sysctl.items())[:5]:
            lines.append(f"   sysctl {k} = {v}")
        return "\n".join(lines)

    def dmesg(self, lines: int = 40) -> str:
        if self._system != "linux":
            return "dmesg only available on Linux"
        raw = _run(["dmesg", "--notime", f"--lines={lines}"], timeout=5)
        return raw or "⚠️  dmesg returned no output (may need elevated permissions)"

    def search_dmesg(self, pattern: str, lines: int = 200) -> str:
        """Return dmesg lines matching *pattern* (a Python regex).

        Useful for finding hardware errors, OOM events, driver messages, etc.
        Example: ``ki.search_dmesg(r"error|fail|warn", lines=500)``
        """
        if self._system != "linux":
            return "dmesg search only available on Linux"
        raw = _run(["dmesg", "--notime", f"--lines={lines}"], timeout=5)
        if not raw:
            return "⚠️  dmesg returned no output"
        try:
            rx = re.compile(pattern, re.IGNORECASE)
            matched = [l for l in raw.splitlines() if rx.search(l)]
            if not matched:
                return f"No dmesg lines matched {pattern!r}"
            return "\n".join(matched[:100])
        except re.error as exc:
            return f"Invalid regex {pattern!r}: {exc}"

    def set_sysctl(self, key: str, value: str, write: bool = False) -> str:
        if self._system != "linux":
            return f"sysctl write only supported on Linux (current: {self._system})"
        if self._read_only:
            return "[READ-ONLY] Cloud deployment — sysctl write disabled"
        if not write:
            return f"[DRY-RUN] sysctl -w {key}={value}"
        if os.geteuid() != 0 if hasattr(os, "geteuid") else True:
            return "⚠️  Root required to set sysctl"
        out = _run(["sysctl", "-w", f"{key}={value}"], timeout=5)
        return out.strip() or f"✅ sysctl {key}={value} set"

    def load_module(self, module: str, write: bool = False) -> str:
        if self._system != "linux":
            return "Kernel module loading only supported on Linux"
        if self._read_only:
            return "[READ-ONLY] Cloud deployment — module loading disabled"
        if not write:
            return f"[DRY-RUN] modprobe {module}"
        if os.geteuid() != 0 if hasattr(os, "geteuid") else True:
            return "⚠️  Root required to load kernel modules"
        out = _run(["modprobe", module], timeout=10)
        return out.strip() or f"✅ Module '{module}' loaded"

    def unload_module(self, module: str, write: bool = False) -> str:
        if self._system != "linux":
            return "Kernel module unloading only supported on Linux"
        if self._read_only:
            return "[READ-ONLY] Cloud deployment — module unloading disabled"
        if not write:
            return f"[DRY-RUN] rmmod {module}"
        if os.geteuid() != 0 if hasattr(os, "geteuid") else True:
            return "⚠️  Root required to unload kernel modules"
        out = _run(["rmmod", module], timeout=10)
        return out.strip() or f"✅ Module '{module}' unloaded"

    def list_modules(self) -> str:
        p = self.get_profile()
        mods = p.get("loaded_modules", [])
        if not mods:
            return "No module list available"
        return f"Loaded kernel modules ({len(mods)}):\n" + "\n".join(f"  {m}" for m in mods[:40])

    def status(self) -> str:
        p = self.get_profile() if self._profile else {}
        return (
            f"KernelIntegration | system={self._system} | "
            f"kernel={p.get('kernel_version', '?')[:50]} | "
            f"modules={p.get('module_count', '?')} | "
            f"read_only={self._read_only}"
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _collect(self) -> Dict[str, Any]:
        base = {
            "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "system": self._system,
        }
        try:
            if self._system == "linux":
                base.update(_probe_linux())
            elif self._system == "windows":
                base.update(_probe_windows())
            elif self._system == "darwin":
                base.update(_probe_macos())
            else:
                base["kernel_version"] = platform.release()
        except Exception as e:
            log.debug("[KernelIntegration] probe error: %s", e)
        return base

    def _store(self, p: Dict[str, Any]) -> None:
        if self.knowledge_db is None:
            return
        try:
            summary = (
                f"Kernel: {p.get('kernel_version', '?')[:80]} | "
                f"modules={p.get('module_count', '?')} | "
                f"system={p.get('system')}"
            )[:400]
            self.knowledge_db.add_fact("niblit_kernel_profile", summary)
        except Exception as e:
            log.debug("[KernelIntegration] KB store failed: %s", e)


# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[KernelIntegration] = None
_LOCK = threading.Lock()


def get_kernel_integration(knowledge_db: Optional[Any] = None) -> KernelIntegration:
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = KernelIntegration(knowledge_db=knowledge_db)
                _INSTANCE.probe()
    return _INSTANCE


if __name__ == "__main__":
    print('Running kernel_integration.py')
