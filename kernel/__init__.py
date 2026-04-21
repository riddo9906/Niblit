"""
kernel/ — Niblit OS Abstraction Layer
======================================
Provides an OS-like platform on top of which NiblitCore runs.

The kernel abstracts:
  - Process management (threads / subprocesses)
  - Memory allocation budgeting
  - Virtual filesystem access
  - Device registry (CPU, GPU, disk, network)
  - Syscall dispatch (named function-call table tied to niblit_tools)
  - Inter-process communication (IPC bus)

Public API
----------
    from kernel import NiblitOSKernel, get_os_kernel

    kernel = get_os_kernel()
    kernel.boot()
    kernel.shutdown()
"""

from __future__ import annotations

import logging
import threading

from kernel.device_manager import DeviceManager
from kernel.fs_manager import FSManager
from kernel.ipc import IPCBus
from kernel.memory_manager import MemoryManager
from kernel.process_manager import ProcessManager
from kernel.syscall_dispatcher import SyscallDispatcher

log = logging.getLogger("NiblitOSKernel")

__all__ = ["NiblitOSKernel", "get_os_kernel"]


class NiblitOSKernel:
    """
    OS abstraction kernel for Niblit.

    Acts as the runtime platform beneath NiblitCore.  It manages processes,
    memory budgets, a virtual filesystem view, a device registry, a syscall
    dispatch table, and an IPC message bus.

    All subsystems are lazily initialised on ``boot()`` and cleanly torn down
    on ``shutdown()``.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._booted = False
        self._lock = threading.Lock()

        # Subsystems (set during boot)
        self.process_manager: ProcessManager | None = None
        self.memory_manager: MemoryManager | None = None
        self.fs_manager: FSManager | None = None
        self.device_manager: DeviceManager | None = None
        self.syscall_dispatcher: SyscallDispatcher | None = None
        self.ipc: IPCBus | None = None

    # ------------------------------------------------------------------ boot /
    def boot(self) -> None:
        """Initialise all kernel subsystems in dependency order."""
        with self._lock:
            if self._booted:
                return
            log.info("[Kernel] Booting NiblitOSKernel v%s …", self.VERSION)
            try:
                self.process_manager = ProcessManager()
                self.memory_manager = MemoryManager()
                self.fs_manager = FSManager()
                self.device_manager = DeviceManager()
                self.ipc = IPCBus()
                self.syscall_dispatcher = SyscallDispatcher(
                    process_manager=self.process_manager,
                    memory_manager=self.memory_manager,
                    fs_manager=self.fs_manager,
                    device_manager=self.device_manager,
                    ipc=self.ipc,
                )
                self._booted = True
                log.info("[Kernel] Boot complete — all subsystems online.")
            except Exception as exc:
                log.error("[Kernel] Boot failed: %s", exc, exc_info=True)
                raise

    # --------------------------------------------------------------- shutdown /
    def shutdown(self) -> None:
        """Gracefully stop all kernel subsystems."""
        with self._lock:
            if not self._booted:
                return
            log.info("[Kernel] Shutting down …")
            for subsystem_name in (
                "syscall_dispatcher",
                "ipc",
                "device_manager",
                "fs_manager",
                "memory_manager",
                "process_manager",
            ):
                obj = getattr(self, subsystem_name, None)
                if obj and hasattr(obj, "shutdown"):
                    try:
                        obj.shutdown()
                    except Exception as exc:
                        log.warning("[Kernel] %s.shutdown() error: %s", subsystem_name, exc)
            self._booted = False
            log.info("[Kernel] Shutdown complete.")

    # ----------------------------------------------------------------- status /
    def status(self) -> dict:
        """Return a summary dict describing kernel state."""
        return {
            "version": self.VERSION,
            "booted": self._booted,
            "process_manager": self.process_manager.status() if self.process_manager else None,
            "memory_manager": self.memory_manager.status() if self.memory_manager else None,
            "fs_manager": self.fs_manager.status() if self.fs_manager else None,
            "device_manager": self.device_manager.status() if self.device_manager else None,
            "syscalls": self.syscall_dispatcher.registered_syscalls() if self.syscall_dispatcher else [],
            "ipc": self.ipc.status() if self.ipc else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NiblitOSKernel v{self.VERSION} booted={self._booted}>"


# ─────────────────────────────────────────────────────────────────── singleton
_kernel_instance: NiblitOSKernel | None = None
_kernel_lock = threading.Lock()


def get_os_kernel() -> NiblitOSKernel:
    """Return the process-wide singleton NiblitOSKernel, booting it if needed."""
    global _kernel_instance
    if _kernel_instance is None:
        with _kernel_lock:
            if _kernel_instance is None:
                _kernel_instance = NiblitOSKernel()
                _kernel_instance.boot()
    return _kernel_instance
