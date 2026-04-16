"""
kernel/syscall_dispatcher.py — Named syscall dispatch table.

Provides an OS-style syscall interface backed by Niblit's
:mod:`niblit_tools.tool_registry` (LangChain-style function-calling).

Any registered tool can be invoked as a "syscall" by name with a
structured argument dict, mirroring how a userland program would
issue a system call to the OS kernel.

Architecture
------------
    Caller  →  SyscallDispatcher.call(name, kwargs)
                        ↓
               niblit_tools ToolRegistry.run(name, kwargs)
                        ↓
               Registered tool function (Python callable)

Built-in kernel syscalls (``proc_list``, ``mem_info``, ``dev_list``,
``fs_listdir``, ``fs_read``, ``ipc_push``, ``ipc_pop``,
``kernel_status``) are pre-registered at init time and delegate to
the kernel subsystems passed in the constructor.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("NiblitOSKernel.SyscallDispatcher")

__all__ = ["SyscallDispatcher"]

# Optional: niblit_tools ToolRegistry integration
try:
    from niblit_tools.tool_registry import get_registry as _get_tool_registry
    _TOOL_REGISTRY_AVAILABLE = True
except Exception:
    _get_tool_registry = None  # type: ignore[assignment]
    _TOOL_REGISTRY_AVAILABLE = False


class SyscallDispatcher:
    """
    Dispatch table for named kernel syscalls + niblit_tools integration.

    Syscalls are plain Python callables registered by name.  When
    :mod:`niblit_tools` is available, every tool in the global
    ``ToolRegistry`` is also available as a syscall automatically.

    Parameters
    ----------
    process_manager, memory_manager, fs_manager, device_manager, ipc:
        Kernel subsystem references used to implement built-in syscalls.
    """

    def __init__(
        self,
        process_manager=None,
        memory_manager=None,
        fs_manager=None,
        device_manager=None,
        ipc=None,
    ) -> None:
        self._syscalls: Dict[str, Any] = {}
        self._pm = process_manager
        self._mm = memory_manager
        self._fs = fs_manager
        self._dm = device_manager
        self._ipc = ipc

        self._register_builtin_syscalls()

        if _TOOL_REGISTRY_AVAILABLE and _get_tool_registry:
            self._tool_registry = _get_tool_registry()
        else:
            self._tool_registry = None

        log.debug(
            "[Syscall] SyscallDispatcher ready — %d built-in syscalls, tool_registry=%s",
            len(self._syscalls),
            "yes" if self._tool_registry else "no",
        )

    # ─────────────────────────────────────────────── built-in syscall wiring ──

    def _register_builtin_syscalls(self) -> None:
        """Register kernel-internal syscalls backed by subsystems."""

        def proc_list(**_kw) -> dict:
            return self._pm.status() if self._pm else {"error": "process_manager unavailable"}

        def mem_info(**_kw) -> dict:
            return self._mm.status() if self._mm else {"error": "memory_manager unavailable"}

        def dev_list(device: str = "", **_kw) -> dict:
            if not self._dm:
                return {"error": "device_manager unavailable"}
            if device:
                return self._dm.get(device) or {"error": f"unknown device: {device}"}
            return self._dm.list_devices()

        def fs_listdir(path: str = "", **_kw) -> list:
            if not self._fs:
                return []
            return self._fs.listdir(path)

        def fs_read(path: str = "", **_kw) -> str:
            if not self._fs:
                return ""
            return self._fs.read_text(path) if path else ""

        def ipc_push(channel: str = "", payload: Any = None, sender: str = "syscall", **_kw) -> bool:
            if not self._ipc or not channel:
                return False
            self._ipc.push(channel, payload, sender=sender)
            return True

        def ipc_pop(channel: str = "", timeout: float = 0.0, **_kw):
            if not self._ipc or not channel:
                return None
            msg = self._ipc.pop(channel, timeout=timeout or None)
            if msg is None:
                return None
            return {"topic": msg.topic, "payload": msg.payload, "sender": msg.sender}

        def kernel_status(**_kw) -> dict:
            result: dict = {}
            if self._pm:
                result["processes"] = self._pm.status()
            if self._mm:
                result["memory"] = self._mm.status()
            if self._dm:
                result["devices"] = {"device_count": len(self._dm.list_devices())}
            if self._ipc:
                result["ipc"] = self._ipc.status()
            return result

        for name, fn in (
            ("proc_list", proc_list),
            ("mem_info", mem_info),
            ("dev_list", dev_list),
            ("fs_listdir", fs_listdir),
            ("fs_read", fs_read),
            ("ipc_push", ipc_push),
            ("ipc_pop", ipc_pop),
            ("kernel_status", kernel_status),
        ):
            self._syscalls[name] = fn

    # ─────────────────────────────────────────────────────────── public API ──

    def register(self, name: str, fn: Any) -> None:
        """Register a custom syscall under *name*."""
        self._syscalls[name] = fn
        log.debug("[Syscall] Registered custom syscall: %s", name)

    def call(self, name: str, kwargs: Optional[Dict[str, Any]] = None) -> Any:
        """
        Dispatch a syscall by *name* with optional keyword arguments.

        Resolution order:
        1. Built-in / custom syscalls registered on this dispatcher
        2. Niblit ToolRegistry (if available)

        Raises :class:`KeyError` if the syscall is not found.
        """
        kwargs = kwargs or {}

        # 1. Built-in / custom syscalls
        fn = self._syscalls.get(name)
        if fn is not None:
            log.debug("[Syscall] call %s (built-in)", name)
            return fn(**kwargs)

        # 2. niblit_tools ToolRegistry
        if self._tool_registry is not None:
            try:
                log.debug("[Syscall] call %s (tool_registry)", name)
                return self._tool_registry.run(name, kwargs)
            except KeyError:
                raise KeyError(f"Unknown syscall: {name!r}") from None
            except Exception as exc:
                raise KeyError(f"Syscall {name!r} failed in tool registry: {exc}") from exc

        raise KeyError(f"Unknown syscall: {name!r}")

    def registered_syscalls(self) -> List[str]:
        """Return names of all registered built-in/custom syscalls."""
        return sorted(self._syscalls.keys())

    def all_callable_names(self) -> List[str]:
        """Return names of all callable syscalls including tool registry tools."""
        names = set(self._syscalls.keys())
        if self._tool_registry is not None:
            try:
                tools = self._tool_registry.list_tools()
                names.update(t["name"] for t in tools)
            except Exception:
                pass
        return sorted(names)

    def shutdown(self) -> None:
        self._syscalls.clear()
        log.debug("[Syscall] SyscallDispatcher shut down.")
