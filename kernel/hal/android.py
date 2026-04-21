# kernel/hal/android.py — Android HAL stub
# ─────────────────────────────────────────────────────────────────────────────
# Wraps the existing proot-based Alpine Linux userland that Niblit's APK
# already uses (modules/proot_env.py + modules/apk_bootstrap.py).
#
# This HAL provides the kernel/ abstraction layer with a way to execute
# commands inside the Alpine chroot on Android devices, enabling Niblit
# to run full Linux tooling on Android without root.
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from kernel.hal.base import BaseHAL

log = logging.getLogger(__name__)

# Well-known path where proot Alpine is installed inside the Niblit APK.
_DEFAULT_ALPINE_ROOT = os.path.expanduser("~/.niblit/alpine")


class AndroidHAL(BaseHAL):
    """Android platform HAL — wraps proot + Alpine Linux userland.

    Command execution is routed through proot so that standard Linux
    binaries (Python, curl, git, etc.) work inside the Alpine chroot
    even without Android root access.

    Falls back gracefully to the ProotEnvironment singleton if available,
    otherwise constructs a minimal proot invocation directly.
    """

    def __init__(self, alpine_root: str = _DEFAULT_ALPINE_ROOT) -> None:
        self._alpine_root = alpine_root
        self._proot_env = None  # lazy-loaded

    @property
    def name(self) -> str:
        return "android"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "gpu":    False,
            "docker": False,
            "camera": True,   # Android cameras available via Java/JNI
            "proot":  True,
            "alpine": os.path.isdir(self._alpine_root),
        }

    def _get_proot_env(self) -> Any:
        """Lazily load the ProotEnvironment singleton from modules/."""
        if self._proot_env is None:
            try:
                from modules.proot_env import get_proot_env  # type: ignore[import]
                self._proot_env = get_proot_env()
            except Exception as exc:  # noqa: BLE001
                log.debug("ProotEnvironment unavailable: %s", exc)
                self._proot_env = None
        return self._proot_env

    def _build_proot_cmd(self, cmd: list[str]) -> list[str]:
        """Wrap *cmd* in a proot invocation against the Alpine chroot."""
        proot = "proot"
        return [
            proot,
            "--rootfs", self._alpine_root,
            "--bind=/dev",
            "--bind=/proc",
            "--bind=/sys",
            "--bind=/tmp",
            "--change-id=0:0",
            "--",
            *cmd,
        ]

    def run(
        self,
        cmd: list[str],
        *,
        capture: bool = False,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        # Try ProotEnvironment first (more complete setup)
        proot_env = self._get_proot_env()
        if proot_env is not None:
            try:
                result = proot_env.run(cmd, capture_output=capture, timeout=timeout)
                return result
            except Exception as exc:  # noqa: BLE001
                log.warning("ProotEnvironment.run failed (%s); falling back to direct proot", exc)

        # Direct proot fallback
        wrapped = self._build_proot_cmd(cmd)
        return subprocess.run(  # noqa: S603
            wrapped,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )

    def root_path(self) -> str:
        return self._alpine_root

    def bootstrap(self) -> bool:
        """Ensure the Alpine userland is installed (delegates to APKBootstrap)."""
        try:
            from modules.apk_bootstrap import get_apk_bootstrap  # type: ignore[import]
            bootstrap = get_apk_bootstrap()
            return bootstrap.ensure_installed()
        except Exception as exc:  # noqa: BLE001
            log.warning("APKBootstrap unavailable: %s", exc)
            return False
