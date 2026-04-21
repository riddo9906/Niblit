# kernel/hal/linux.py — Linux host HAL
from __future__ import annotations

import subprocess

from kernel.hal.base import BaseHAL


class LinuxHAL(BaseHAL):
    """Native Linux platform — executes commands directly."""

    @property
    def name(self) -> str:
        return "linux"

    @property
    def capabilities(self) -> dict[str, bool]:
        import shutil
        return {
            "gpu":    shutil.which("nvidia-smi") is not None,
            "docker": shutil.which("docker") is not None,
            "camera": False,
            "proot":  shutil.which("proot") is not None,
        }

    def run(
        self,
        cmd: list[str],
        *,
        capture: bool = False,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )

    def root_path(self) -> str:
        return "/"
