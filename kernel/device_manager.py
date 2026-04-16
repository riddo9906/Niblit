"""
kernel/device_manager.py — Abstract device registry.

Maintains a registry of virtual devices (CPU, GPU, disk, network, …)
and their current state.  On platforms where :mod:`psutil` is available
the CPU and memory readings are real; on restricted environments they
degrade gracefully to static placeholders.

Device plug-in model
--------------------
Any code can call ``register(name, device_dict)`` to add a custom
device.  Devices are plain dicts with at minimum the key ``"type"``.
"""

from __future__ import annotations

import logging
import platform
import threading
from typing import Any

log = logging.getLogger("NiblitOSKernel.DeviceManager")

__all__ = ["DeviceManager"]

try:
    import psutil as _psutil  # type: ignore[import]
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False


def _cpu_info() -> dict:
    """Return a snapshot of CPU info."""
    info: dict = {
        "type": "cpu",
        "arch": platform.machine(),
        "cores_logical": 1,
        "cores_physical": 1,
        "percent": 0.0,
    }
    if _PSUTIL_AVAILABLE:
        try:
            info["cores_logical"] = _psutil.cpu_count(logical=True) or 1
            info["cores_physical"] = _psutil.cpu_count(logical=False) or 1
            info["percent"] = _psutil.cpu_percent(interval=None)
        except Exception:
            pass
    return info


def _memory_info() -> dict:
    info: dict = {"type": "memory", "total_bytes": 0, "available_bytes": 0, "percent": 0.0}
    if _PSUTIL_AVAILABLE:
        try:
            vm = _psutil.virtual_memory()
            info.update(
                total_bytes=vm.total,
                available_bytes=vm.available,
                percent=vm.percent,
            )
        except Exception:
            pass
    return info


def _disk_info() -> dict:
    info: dict = {"type": "disk", "partitions": []}
    if _PSUTIL_AVAILABLE:
        try:
            partitions = []
            for part in _psutil.disk_partitions(all=False):
                try:
                    usage = _psutil.disk_usage(part.mountpoint)
                    partitions.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_bytes": usage.total,
                        "free_bytes": usage.free,
                        "percent": usage.percent,
                    })
                except (OSError, PermissionError):
                    pass
            info["partitions"] = partitions
        except Exception:
            pass
    return info


def _network_info() -> dict:
    info: dict = {"type": "network", "interfaces": {}}
    if _PSUTIL_AVAILABLE:
        try:
            addrs = _psutil.net_if_addrs()
            stats = _psutil.net_if_stats()
            interfaces = {}
            for name, addr_list in addrs.items():
                iface_stat = stats.get(name)
                interfaces[name] = {
                    "up": iface_stat.isup if iface_stat else False,
                    "speed_mbps": iface_stat.speed if iface_stat else 0,
                    "addresses": [str(a.address) for a in addr_list],
                }
            info["interfaces"] = interfaces
        except Exception:
            pass
    return info


class DeviceManager:
    """
    Registry and live-query layer for system devices.

    Built-in devices (``cpu``, ``memory``, ``disk``, ``network``) are
    auto-populated at instantiation and refreshed on ``refresh()``.
    Additional devices can be registered with ``register()``.
    """

    def __init__(self) -> None:
        self._devices: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._refresh_devices()
        log.debug("[DM] DeviceManager ready with %d devices", len(self._devices))

    # ---------------------------------------------------------- refresh -------
    def _refresh_devices(self) -> None:
        with self._lock:
            self._devices["cpu"] = _cpu_info()
            self._devices["memory"] = _memory_info()
            self._devices["disk"] = _disk_info()
            self._devices["network"] = _network_info()

    def refresh(self) -> None:
        """Re-probe all built-in devices."""
        self._refresh_devices()
        log.debug("[DM] Devices refreshed.")

    # ---------------------------------------------------------- register ------
    def register(self, name: str, device: dict) -> None:
        """
        Register a custom device under *name*.

        *device* should be a dict with at minimum ``{"type": "<device_type>"}``.
        """
        with self._lock:
            self._devices[name] = device
        log.debug("[DM] Device registered: %s (%s)", name, device.get("type", "unknown"))

    def unregister(self, name: str) -> bool:
        """Remove a registered device by name.  Returns True if it existed."""
        with self._lock:
            existed = name in self._devices
            self._devices.pop(name, None)
        return existed

    # ---------------------------------------------------------- query ---------
    def get(self, name: str) -> dict | None:
        """Return the device dict for *name*, or None."""
        with self._lock:
            return dict(self._devices[name]) if name in self._devices else None

    def get_device(self, name: str) -> dict | None:
        """Alias for get()."""
        return self.get(name)

    def probe_all(self) -> None:
        """Alias for refresh()."""
        self.refresh()

    def list_devices(self) -> dict[str, dict]:
        """Return a shallow copy of the full device registry."""
        with self._lock:
            return {k: dict(v) for k, v in self._devices.items()}

    # ---------------------------------------------------------- status --------
    def status(self) -> dict:
        self._refresh_devices()
        return {
            "device_count": len(self._devices),
            "devices": self.list_devices(),
        }

    def shutdown(self) -> None:
        log.debug("[DM] DeviceManager shut down.")
