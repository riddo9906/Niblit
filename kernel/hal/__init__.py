# kernel/hal/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# NiblitOS Hardware Abstraction Layer (HAL) package
#
# Provides hardware-specific backends that the Python kernel/ abstraction
# layer selects at runtime.  Currently implemented:
#   • AndroidHAL  — wraps the proot-based Alpine Linux userland (APK)
#   • LinuxHAL    — native Linux host (default, no special wrapping)
#
# Usage:
#   from kernel.hal import get_hal
#   hal = get_hal()
#   hal.run(["ls", "/"])

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.hal.base import BaseHAL


def get_hal() -> BaseHAL:
    """Return the appropriate HAL implementation for the current platform."""
    # Allow override via environment variable (useful for testing).
    override = os.environ.get("NIBLIT_HAL", "").lower()
    if override == "android":
        from kernel.hal.android import AndroidHAL
        return AndroidHAL()
    if override == "linux":
        from kernel.hal.linux import LinuxHAL
        return LinuxHAL()

    # Auto-detect
    try:
        with open("/proc/version") as f:
            version = f.read().lower()
        if "android" in version:
            from kernel.hal.android import AndroidHAL
            return AndroidHAL()
    except OSError:
        pass

    from kernel.hal.linux import LinuxHAL
    return LinuxHAL()


__all__ = ["get_hal"]
if __name__ == "__main__":
    print('Running __init__.py')
