# kernel/hal/base.py — Base HAL interface
from __future__ import annotations

import abc
import subprocess
from typing import Any


class BaseHAL(abc.ABC):
    """Abstract hardware abstraction layer.

    Concrete subclasses implement platform-specific process execution,
    filesystem paths, and capability flags.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable platform name."""

    @property
    @abc.abstractmethod
    def capabilities(self) -> dict[str, bool]:
        """Dict of capability flags, e.g. {'gpu': False, 'camera': True}."""

    @abc.abstractmethod
    def run(
        self,
        cmd: list[str],
        *,
        capture: bool = False,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a command in the HAL's environment."""

    @abc.abstractmethod
    def root_path(self) -> str:
        """Root of the HAL's filesystem namespace (e.g. '/' or proot chroot)."""

    def info(self) -> dict[str, Any]:
        return {
            "hal": self.name,
            "root": self.root_path(),
            "capabilities": self.capabilities,
        }


if __name__ == "__main__":
    print('Running base.py')
