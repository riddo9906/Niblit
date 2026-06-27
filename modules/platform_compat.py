#!/usr/bin/env python3
"""Platform compatibility helpers for cross-platform socket and runtime behavior."""

from __future__ import annotations

import logging
import os
import socket
import sys
from typing import Optional, Tuple

log = logging.getLogger("PlatformCompat")

_DEFAULT_TCP_PORT = int(
    os.environ.get(
        "NIBLIT_CTL_TCP_PORT",
        os.environ.get("NIBLIT_CTL_PORT", "7681"),
    )
    or "7681"
)


def unix_socket_available() -> bool:
    """Return True when AF_UNIX domain sockets are available on this platform."""
    return hasattr(socket, "AF_UNIX")


def platform_mode() -> str:
    """Return a coarse platform label for boot reporting."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return "fallback"


def default_sidecar_tcp_host() -> str:
    return os.environ.get("NIBLIT_CTL_TCP_HOST", "127.0.0.1").strip() or "127.0.0.1"


def default_sidecar_tcp_port() -> int:
    try:
        return int(os.environ.get("NIBLIT_CTL_TCP_PORT", str(_DEFAULT_TCP_PORT)))
    except (TypeError, ValueError):
        return _DEFAULT_TCP_PORT


def create_stream_server(
    *,
    unix_path: Optional[str] = None,
    tcp_host: Optional[str] = None,
    tcp_port: Optional[int] = None,
    backlog: int = 4,
) -> Tuple[Optional[socket.socket], str, str]:
    """Create a listening stream socket with UNIX-first, TCP-fallback semantics.

    Returns ``(socket, transport, endpoint)`` where *transport* is ``unix`` or
    ``tcp``, and *endpoint* is a path or ``host:port`` string.  On failure
    returns ``(None, "disabled", "")``.
    """
    host = tcp_host or default_sidecar_tcp_host()
    port = tcp_port if tcp_port is not None else default_sidecar_tcp_port()

    if unix_socket_available() and unix_path:
        try:
            try:
                os.unlink(unix_path)
            except FileNotFoundError:
                pass
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(unix_path)
            try:
                os.chmod(unix_path, 0o600)
            except OSError:
                pass
            srv.listen(backlog)
            return srv, "unix", unix_path
        except (AttributeError, OSError) as exc:
            log.warning(
                "Unix socket bind failed for %s (%s) — trying TCP fallback",
                unix_path,
                exc,
            )

    if not unix_socket_available():
        log.warning(
            "Unix socket not supported on this platform — switching to TCP fallback"
        )

    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(backlog)
        endpoint = f"{host}:{port}"
        return srv, "tcp", endpoint
    except OSError as exc:
        log.error("TCP sidecar bind failed on %s:%s — %s", host, port, exc)
        return None, "disabled", ""


def connect_stream_client(
    *,
    unix_path: Optional[str] = None,
    tcp_host: Optional[str] = None,
    tcp_port: Optional[int] = None,
    timeout: float = 30.0,
) -> socket.socket:
    """Connect to a sidecar endpoint using UNIX or TCP as available."""
    host = tcp_host or default_sidecar_tcp_host()
    port = tcp_port if tcp_port is not None else default_sidecar_tcp_port()

    if unix_socket_available() and unix_path:
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(timeout)
            conn.connect(unix_path)
            return conn
        except (AttributeError, FileNotFoundError, OSError):
            pass

    conn = socket.create_connection((host, port), timeout=timeout)
    conn.settimeout(timeout)
    return conn
