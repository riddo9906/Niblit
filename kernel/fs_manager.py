"""
kernel/fs_manager.py — Virtual filesystem abstraction.

Wraps the real filesystem (via :mod:`pathlib`) behind a controlled
interface so kernel subsystems can:

  - Mount / unmount logical volumes onto paths
  - Read / write files through a single audited gateway
  - List directory contents safely
  - Resolve virtual paths to real OS paths

No actual FUSE or kernel-mode FS is involved; this is a pure Python
abstraction layer that adds access control and auditing on top of
:func:`pathlib.Path` operations.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("NiblitOSKernel.FSManager")

__all__ = ["FSManager"]


class FSManager:
    """
    Virtual filesystem manager.

    Supports mounting real directories under logical mount points and
    provides read/write helpers that enforce path containment (no path
    traversal outside a mounted volume).

    Parameters
    ----------
    root:
        Base directory used when resolving relative paths.  Defaults to
        the current working directory.
    """

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root).resolve() if root else Path.cwd()
        self._mounts: dict[str, Path] = {}  # logical_name → real_path
        log.debug("[FS] FSManager initialised with root %s", self._root)

    # ------------------------------------------------------------ mount/umount
    def mount(self, name: str, real_path: str) -> None:
        """
        Mount a real directory under the logical name *name*.

        Raises :class:`FileNotFoundError` if *real_path* does not exist.
        """
        p = Path(real_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"[FS] Cannot mount {real_path!r}: path does not exist")
        self._mounts[name] = p
        log.debug("[FS] Mounted %r → %s", name, p)

    def umount(self, name: str) -> bool:
        """Remove a mount point by name.  Returns True if it existed."""
        removed = self._mounts.pop(name, None) is not None
        if removed:
            log.debug("[FS] Unmounted %r", name)
        return removed

    # ----------------------------------------------------------------- resolve
    def resolve(self, virtual_path: str) -> Path:
        """
        Resolve *virtual_path* to a real :class:`Path`.

        If *virtual_path* starts with ``<name>/`` or equals ``<name>``,
        the leading segment is replaced by the corresponding mount point.
        Otherwise the path is resolved relative to ``root``.
        """
        parts = virtual_path.lstrip("/").split("/", 1)
        mount_name = parts[0]
        remainder = parts[1] if len(parts) > 1 else ""

        if mount_name in self._mounts:
            base = self._mounts[mount_name]
            real = (base / remainder).resolve()
            # Safety: ensure result is inside the mount
            if not str(real).startswith(str(base)):
                raise PermissionError(
                    f"[FS] Path traversal blocked: {virtual_path!r} escapes mount {mount_name!r}"
                )
            return real

        # Fall back to root-relative resolution
        real = (self._root / virtual_path).resolve()
        if not str(real).startswith(str(self._root)):
            raise PermissionError(
                f"[FS] Path traversal blocked: {virtual_path!r} escapes root {self._root}"
            )
        return real

    # ----------------------------------------------------------------- read/write
    def read_text(self, virtual_path: str, encoding: str = "utf-8") -> str:
        """Read and return text content at *virtual_path*."""
        real = self.resolve(virtual_path)
        log.debug("[FS] read_text %s", real)
        return real.read_text(encoding=encoding)

    def write_text(self, virtual_path: str, content: str, encoding: str = "utf-8") -> None:
        """Write *content* to *virtual_path*, creating parent directories."""
        real = self.resolve(virtual_path)
        real.parent.mkdir(parents=True, exist_ok=True)
        log.debug("[FS] write_text %s (%d chars)", real, len(content))
        real.write_text(content, encoding=encoding)

    def read_bytes(self, virtual_path: str) -> bytes:
        """Read and return raw bytes from *virtual_path*."""
        real = self.resolve(virtual_path)
        log.debug("[FS] read_bytes %s", real)
        return real.read_bytes()

    def write_bytes(self, virtual_path: str, data: bytes) -> None:
        """Write raw *data* to *virtual_path*, creating parent directories."""
        real = self.resolve(virtual_path)
        real.parent.mkdir(parents=True, exist_ok=True)
        log.debug("[FS] write_bytes %s (%d bytes)", real, len(data))
        real.write_bytes(data)

    # ------------------------------------------------------------------- list
    def listdir(self, virtual_path: str = "") -> list[str]:
        """Return names of entries in *virtual_path* (or root if empty)."""
        real = self.resolve(virtual_path) if virtual_path else self._root
        if not real.is_dir():
            raise NotADirectoryError(f"[FS] Not a directory: {virtual_path!r}")
        return sorted(e.name for e in real.iterdir())

    def exists(self, virtual_path: str) -> bool:
        """Return True if *virtual_path* exists."""
        try:
            return self.resolve(virtual_path).exists()
        except (PermissionError, FileNotFoundError):
            return False

    # ----------------------------------------------------------------- status
    def status(self) -> dict:
        mounts_info = {}
        for name, path in self._mounts.items():
            try:
                stat = os.statvfs(path)
                free_bytes = stat.f_bavail * stat.f_frsize
                total_bytes = stat.f_blocks * stat.f_frsize
            except (AttributeError, OSError):
                free_bytes = total_bytes = -1
            mounts_info[name] = {
                "real_path": str(path),
                "exists": path.exists(),
                "free_bytes": free_bytes,
                "total_bytes": total_bytes,
            }
        return {
            "root": str(self._root),
            "mounts": mounts_info,
        }

    def shutdown(self) -> None:
        self._mounts.clear()
        log.debug("[FS] FSManager shut down.")
