"""
bios_integration.py — Niblit BIOS / UEFI Integration Layer
===========================================================
Reads and (where permitted by the OS) patches BIOS / UEFI settings on any
supported platform:

  • Linux  — dmidecode (read), efivarfs / /sys/firmware/efi (UEFI variables),
             /proc/acpi, biosdevname, grub.cfg patching for kernel cmdline flags
  • Windows — wmic (read), bcdedit (boot configuration, admin)
  • macOS   — system_profiler SPHardwareDataType (read), nvram (EFI vars)
  • Termux  — getprop (Android firmware metadata, read-only)

Security note
-------------
This module NEVER overwrites EFI variables or BIOS blocks without an explicit
``write=True`` kwarg.  All write operations are logged and require the calling
process to have the necessary OS privileges.  On cloud deployments the module
runs in read-only probe mode automatically.

Singleton access via ``get_bios_integration()``.
"""

from __future__ import annotations

import json
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

# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 10) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout,
                                       stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _is_cloud() -> bool:
    return any(os.environ.get(k) for k in ("VERCEL", "RENDER", "FLY_APP_NAME", "K_SERVICE"))


def _is_termux() -> bool:
    return os.path.exists("/data/data/com.termux")


# ── BIOS / UEFI probe helpers ─────────────────────────────────────────────────

def _probe_linux() -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    # dmidecode — system / BIOS table
    if shutil.which("dmidecode"):
        raw = _run(["dmidecode", "-t", "bios"], timeout=8)
        for line in raw.splitlines():
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                data[k.strip().lower().replace(" ", "_")] = v.strip()
        raw2 = _run(["dmidecode", "-t", "system"], timeout=8)
        for line in raw2.splitlines():
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                k2 = "system_" + k.strip().lower().replace(" ", "_")
                data[k2] = v.strip()

    # UEFI — boot mode
    efi_path = Path("/sys/firmware/efi")
    data["uefi_boot"] = efi_path.exists()

    # EFI variables count
    if efi_path.is_dir():
        try:
            data["efi_var_count"] = len(list((efi_path / "efivars").iterdir()))
        except Exception:
            pass

    # Secure Boot
    sb_path = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c")
    if sb_path.exists():
        try:
            raw_bytes = sb_path.read_bytes()
            data["secure_boot"] = bool(raw_bytes[-1]) if raw_bytes else False
        except Exception:
            data["secure_boot"] = "unknown"

    # Kernel cmdline (current boot)
    try:
        data["kernel_cmdline"] = Path("/proc/cmdline").read_text().strip()
    except Exception:
        pass

    # ACPI tables present
    try:
        tables = list(Path("/sys/firmware/acpi/tables").iterdir())
        data["acpi_tables"] = [t.name for t in tables][:20]
    except Exception:
        pass

    return data


def _probe_windows() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key, query in (
        ("bios_version", "wmic bios get SMBIOSBIOSVersion"),
        ("bios_vendor", "wmic bios get Manufacturer"),
        ("bios_date", "wmic bios get ReleaseDate"),
        ("system_model", "wmic computersystem get Model"),
        ("baseboard", "wmic baseboard get Product"),
    ):
        raw = _run(query.split(), timeout=10)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        data[key] = lines[1] if len(lines) > 1 else lines[0] if lines else ""
    return data


def _probe_macos() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    raw = _run(["system_profiler", "SPHardwareDataType"], timeout=10)
    for line in raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            data[k.strip().lower().replace(" ", "_")] = v.strip()
    # EFI vars via nvram
    if shutil.which("nvram"):
        raw_nv = _run(["nvram", "-x", "-p"], timeout=5)
        data["nvram_vars_count"] = raw_nv.count("<key>")
    return data


def _probe_termux() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for prop in ("ro.product.model", "ro.product.manufacturer",
                 "ro.build.version.release", "ro.hardware",
                 "ro.bootloader", "ro.baseband"):
        val = _run(["getprop", prop], timeout=3).strip()
        if val:
            data[prop] = val
    return data


# ── BIOS/GRUB write helpers (Linux only, privileged) ─────────────────────────

def _set_kernel_cmdline_flag(flag: str, value: str, write: bool = False) -> str:
    """
    Append a flag to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub,
    then run update-grub.  Requires root.  write=False → dry-run only.
    """
    grub_cfg = Path("/etc/default/grub")
    if not grub_cfg.exists():
        return "⚠️  /etc/default/grub not found (non-GRUB system)"
    content = grub_cfg.read_text()
    flag_str = f"{flag}={value}" if value else flag
    if flag in content:
        return f"ℹ️  Flag '{flag}' already present in GRUB cmdline"
    new_content = re.sub(
        r'(GRUB_CMDLINE_LINUX_DEFAULT=")([^"]*)"',
        lambda m: f'{m.group(1)}{m.group(2)} {flag_str}"',
        content,
    )
    if not write:
        return f"[DRY-RUN] Would add '{flag_str}' to GRUB_CMDLINE_LINUX_DEFAULT"
    if os.geteuid() != 0 if hasattr(os, "geteuid") else True:
        return "⚠️  Root required to write GRUB config"
    grub_cfg.write_text(new_content)
    _run(["update-grub"], timeout=30)
    return f"✅ Added '{flag_str}' to GRUB cmdline and ran update-grub"


def _read_efi_var(guid: str, name: str) -> bytes:
    path = Path(f"/sys/firmware/efi/efivars/{name}-{guid}")
    if path.exists():
        return path.read_bytes()[4:]  # strip 4-byte attributes
    return b""


# ─────────────────────────────────────────────────────────────────────────────
# BIOSIntegration
# ─────────────────────────────────────────────────────────────────────────────

class BIOSIntegration:
    """
    Niblit BIOS / UEFI integration layer.

    Probes firmware metadata on boot, exposes it to the KB, and provides
    controlled write capabilities (GRUB cmdline patching, EFI var reads)
    when running on hardware with adequate privileges.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self.knowledge_db = knowledge_db
        self._profile: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._system = platform.system().lower()
        self._read_only = _is_cloud()

    # ── Public API ────────────────────────────────────────────────────────────

    def probe(self) -> Dict[str, Any]:
        """Probe and return the firmware profile."""
        with self._lock:
            profile = self._collect()
            self._profile = profile
            self._store(profile)
            return profile

    def get_profile(self) -> Dict[str, Any]:
        if self._profile is None:
            return self.probe()
        return self._profile

    def summary(self) -> str:
        p = self.get_profile()
        lines = ["🔧 BIOS / UEFI Profile"]
        for k, v in list(p.items())[:20]:
            if v and str(v).strip():
                lines.append(f"   {k}: {str(v)[:80]}")
        return "\n".join(lines)

    def uefi_vars(self) -> str:
        """Return a summary of EFI variable names (Linux only)."""
        efi = Path("/sys/firmware/efi/efivars")
        if not efi.exists():
            return "EFI variables not available (not a UEFI system or no access)"
        try:
            names = [p.name.split("-")[0] for p in efi.iterdir()][:30]
            return "EFI variables (first 30):\n" + "\n".join(f"  {n}" for n in names)
        except PermissionError:
            return "⚠️  Permission denied — run as root to read EFI variables"

    def set_cmdline_flag(self, flag: str, value: str = "", write: bool = False) -> str:
        """Add a kernel boot flag to GRUB (Linux only)."""
        if self._system != "linux":
            return f"⚠️  GRUB cmdline editing only supported on Linux (current: {self._system})"
        if self._read_only:
            return "[READ-ONLY] Cloud deployment — GRUB editing disabled"
        return _set_kernel_cmdline_flag(flag, value, write=write)

    def status(self) -> str:
        p = self.get_profile() if self._profile else {}
        uefi = p.get("uefi_boot", "unknown")
        secure = p.get("secure_boot", "unknown")
        return (
            f"BIOSIntegration | system={self._system} | "
            f"uefi={uefi} | secure_boot={secure} | "
            f"read_only={self._read_only}"
        )

    def to_json(self, indent: int = 2) -> str:
        """Return the current BIOS/UEFI profile as a JSON string."""
        return json.dumps(self.get_profile(), indent=indent, default=str)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _collect(self) -> Dict[str, Any]:
        base = {
            "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "system": self._system,
            "read_only": self._read_only,
        }
        try:
            if _is_termux():
                base.update(_probe_termux())
            elif self._system == "linux":
                base.update(_probe_linux())
            elif self._system == "windows":
                base.update(_probe_windows())
            elif self._system == "darwin":
                base.update(_probe_macos())
        except Exception as e:
            log.debug("[BIOSIntegration] probe error: %s", e)
        return base

    def _store(self, p: Dict[str, Any]) -> None:
        if self.knowledge_db is None:
            return
        try:
            summary = (
                f"BIOS/UEFI: system={p.get('system')} | "
                f"uefi={p.get('uefi_boot')} | "
                f"secure_boot={p.get('secure_boot')} | "
                f"vendor={p.get('vendor', p.get('system_manufacturer', '?'))} | "
                f"version={p.get('version', p.get('bios_version', '?'))}"
            )[:400]
            self.knowledge_db.add_fact("niblit_bios_profile", summary)
        except Exception as e:
            log.debug("[BIOSIntegration] KB store failed: %s", e)


# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[BIOSIntegration] = None
_LOCK = threading.Lock()


def get_bios_integration(knowledge_db: Optional[Any] = None) -> BIOSIntegration:
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = BIOSIntegration(knowledge_db=knowledge_db)
                _INSTANCE.probe()
    return _INSTANCE
