#!/usr/bin/env python3
"""
aios_hal.py — Niblit AIOS Hardware Abstraction Layer (HAL)
==========================================================
Consolidates the four hardware-facing modules into a single, unified
Hardware Abstraction Layer so the rest of AIOS never has to import from
``bios``, ``bios_integration``, ``hardware_scanner``, or
``platform_bootstrap`` directly.

Public API
----------
* ``HAL.probe()``        — run a full hardware + platform probe and return a
                           combined ``HALProfile`` dict.
* ``HAL.capabilities``   — ``Capabilities`` object from ``platform_bootstrap``.
* ``HAL.platform_type``  — e.g. ``"pc_linux"``, ``"android_termux"``, …
* ``HAL.bios_info``      — BIOS / UEFI metadata dict (read-only).
* ``HAL.hw_profile``     — hardware profile dict from ``hardware_scanner``.
* ``get_aios_hal()``     — singleton accessor.

The HAL is intentionally read-only at the AIOS level — write operations
(e.g. UEFI patching) remain gated behind explicit ``write=True`` kwargs in
the underlying ``BIOSIntegration`` module.

Singleton access via ``get_aios_hal()``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# ── Sub-layer imports (graceful fallback so HAL survives minimal deployments) ─

try:
    from modules.bios import BIOS as _BIOS
    _BIOS_AVAILABLE = True
except Exception as _e:
    log.debug("HAL: modules.bios unavailable — %s", _e)
    _BIOS_AVAILABLE = False
    _BIOS = None  # type: ignore[assignment]

try:
    from modules.bios_integration import get_bios_integration as _get_bios_integration
    _BIOS_INT_AVAILABLE = True
except Exception as _e:
    log.debug("HAL: modules.bios_integration unavailable — %s", _e)
    _BIOS_INT_AVAILABLE = False
    _get_bios_integration = None  # type: ignore[assignment]

try:
    from modules.hardware_scanner import get_hardware_scanner as _get_hardware_scanner
    _HW_SCANNER_AVAILABLE = True
except Exception as _e:
    log.debug("HAL: modules.hardware_scanner unavailable — %s", _e)
    _HW_SCANNER_AVAILABLE = False
    _get_hardware_scanner = None  # type: ignore[assignment]

try:
    from modules.platform_bootstrap import get_platform_bootstrap as _get_platform_bootstrap
    _PLATFORM_AVAILABLE = True
except Exception as _e:
    log.debug("HAL: modules.platform_bootstrap unavailable — %s", _e)
    _PLATFORM_AVAILABLE = False
    _get_platform_bootstrap = None  # type: ignore[assignment]


# ── HALProfile type alias ─────────────────────────────────────────────────────

HALProfile = Dict[str, Any]


# ── HAL ───────────────────────────────────────────────────────────────────────

class HAL:
    """
    Hardware Abstraction Layer for NIBLIT-AIOS.

    Aggregates BIOS / UEFI metadata, hardware profile, and platform
    capabilities into a single ``HALProfile`` dict that higher AIOS layers
    can query without knowing the underlying probe implementation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profile: Optional[HALProfile] = None
        self._probed_at: float = 0.0

        # Sub-layer singletons (lazily resolved)
        self._bios_integration = None
        self._hw_scanner = None
        self._platform_bootstrap = None

    # ── Public read properties ────────────────────────────────────────────────

    @property
    def capabilities(self) -> Any:
        """Return the ``Capabilities`` object from platform_bootstrap."""
        self._ensure_probed()
        if self._platform_bootstrap is not None:
            return getattr(self._platform_bootstrap, "capabilities", None)
        return None

    @property
    def platform_type(self) -> str:
        """Return the detected platform type string."""
        self._ensure_probed()
        if self._platform_bootstrap is not None:
            return getattr(self._platform_bootstrap, "platform_type", "unknown")
        return "unknown"

    @property
    def bios_info(self) -> Dict[str, Any]:
        """Return the BIOS / UEFI metadata dict (read-only snapshot)."""
        self._ensure_probed()
        if self._profile:
            return dict(self._profile.get("bios", {}))
        return {}

    @property
    def hw_profile(self) -> Dict[str, Any]:
        """Return the hardware profile dict from hardware_scanner."""
        self._ensure_probed()
        if self._profile:
            return dict(self._profile.get("hardware", {}))
        return {}

    # ── probe() ───────────────────────────────────────────────────────────────

    def probe(self, force: bool = False) -> HALProfile:
        """
        Run a full hardware + platform probe and return a combined
        ``HALProfile`` dict.

        The result is cached after the first call.  Pass ``force=True`` to
        re-probe (useful after a hardware change or on demand from diagnostics).

        Keys in the returned dict
        -------------------------
        ``bios_basic``   — basic BIOS check result string (from ``modules.bios``)
        ``bios``         — detailed BIOS / UEFI metadata dict
        ``hardware``     — hardware profile dict (CPU, RAM, GPU, …)
        ``platform``     — platform capabilities and type
        ``probed_at``    — Unix timestamp of this probe run
        """
        with self._lock:
            if self._profile is not None and not force:
                return dict(self._profile)
            profile = self._run_probe()
            self._profile = profile
            self._probed_at = time.time()
            return dict(profile)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_probed(self) -> None:
        if self._profile is None:
            self.probe()

    def _run_probe(self) -> HALProfile:
        profile: HALProfile = {
            "bios_basic": None,
            "bios": {},
            "hardware": {},
            "platform": {},
            "probed_at": time.time(),
        }

        # Layer 1 — basic BIOS check
        if _BIOS_AVAILABLE and _BIOS is not None:
            try:
                bios_obj = _BIOS()
                profile["bios_basic"] = bios_obj.boot_sequence()
            except Exception as exc:
                log.debug("HAL: BIOS.boot_sequence() failed — %s", exc)

        # Layer 2 — detailed BIOS / UEFI integration
        if _BIOS_INT_AVAILABLE and _get_bios_integration is not None:
            try:
                self._bios_integration = _get_bios_integration()
                bios_data = self._bios_integration.probe()
                profile["bios"] = bios_data if isinstance(bios_data, dict) else {}
            except Exception as exc:
                log.debug("HAL: bios_integration.probe() failed — %s", exc)

        # Layer 3 — hardware scanner
        if _HW_SCANNER_AVAILABLE and _get_hardware_scanner is not None:
            try:
                self._hw_scanner = _get_hardware_scanner()
                hw_data = self._hw_scanner.scan()
                profile["hardware"] = hw_data if isinstance(hw_data, dict) else {}
            except Exception as exc:
                log.debug("HAL: hardware_scanner.scan() failed — %s", exc)

        # Layer 4 — platform bootstrap
        if _PLATFORM_AVAILABLE and _get_platform_bootstrap is not None:
            try:
                self._platform_bootstrap = _get_platform_bootstrap()
                caps = getattr(self._platform_bootstrap, "capabilities", None)
                ptype = getattr(self._platform_bootstrap, "platform_type", "unknown")
                profile["platform"] = {
                    "type": ptype,
                    "capabilities": caps.as_dict() if caps and hasattr(caps, "as_dict") else {},
                }
            except Exception as exc:
                log.debug("HAL: platform_bootstrap probe failed — %s", exc)

        log.debug("HAL: probe complete — platform=%s", profile["platform"].get("type", "?"))
        return profile

    def status(self) -> Dict[str, Any]:
        """Return a summary of the current HAL probe status."""
        return {
            "probed": self._profile is not None,
            "probed_at": self._probed_at,
            "platform_type": self.platform_type,
            "bios_available": _BIOS_INT_AVAILABLE,
            "hardware_scanner_available": _HW_SCANNER_AVAILABLE,
            "platform_bootstrap_available": _PLATFORM_AVAILABLE,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_hal: Optional[HAL] = None
_hal_lock = threading.Lock()


def get_aios_hal() -> HAL:
    """Return the process-level AIOS HAL singleton."""
    global _hal
    if _hal is None:
        with _hal_lock:
            if _hal is None:
                _hal = HAL()
    return _hal


if __name__ == "__main__":
    print('Running aios_hal.py')
