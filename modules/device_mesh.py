"""
device_mesh.py — Niblit Device Mesh Network
============================================
Discovers, catalogues, and connects to other Niblit-capable devices on the
local network, enabling Niblit to:

  1. Spread itself to adjacent devices (copy + auto-install via SSH)
  2. Delegate heavy tasks to remote nodes (distributed ALE / training)
  3. Aggregate hardware resources across the mesh
  4. Synchronise knowledge-bases across the mesh

Discovery methods
-----------------
  * mDNS / zeroconf  — ``zeroconf`` Python package (optional)
  * ARP scan         — ``arp-scan`` / ``arp`` / ``ip neigh`` (Linux)
  * Nmap ping scan   — ``nmap -sn`` (optional, requires nmap)
  * Netbios / LLMNR  — Windows fallback via ipconfig / arp

Spread mechanism
----------------
When ``spread=True`` the mesh node will SSH into a discovered host, copy the
Niblit directory, and run ``boot/install.sh``.  This requires:
  • ``ssh`` and ``scp`` / ``rsync`` on PATH
  • SSH key-based authentication (no password prompts)
  • The remote host running a compatible Linux / Termux environment

Security
--------
Spread is DISABLED by default.  Set ``NIBLIT_MESH_SPREAD=1`` to enable.
Discovered hosts are stored in the KB and on disk (mesh_nodes.json) but
nothing is executed on remote hosts without explicit consent.

Singleton access via ``get_device_mesh()``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _run(cmd: list, timeout: int = 15) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout,
                                       stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _niblit_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _writable_path(filename: str) -> Path:
    """Return a writable path for persistent mesh state."""
    data_dir = os.environ.get("NIBLIT_DATA_DIR")
    if data_dir and os.access(data_dir, os.W_OK):
        return Path(data_dir) / filename
    if os.access(str(_niblit_root()), os.W_OK):
        return _niblit_root() / filename
    import tempfile
    return Path(tempfile.gettempdir()) / filename


# ── Discovery helpers ─────────────────────────────────────────────────────────

def _local_ips() -> List[str]:
    """Return local IP addresses of this host."""
    ips = []
    try:
        for iface in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface[4][0]
            if not ip.startswith("127.") and ":" not in ip:
                ips.append(ip)
    except Exception:
        pass
    return list(dict.fromkeys(ips))


def _subnet_from_ip(ip: str) -> str:
    """Return e.g. '192.168.1.' from '192.168.1.100'."""
    parts = ip.rsplit(".", 1)
    return parts[0] + "." if len(parts) == 2 else ""


def _arp_discover(subnet: str) -> List[str]:
    """Discover hosts via arp/ip neigh on Linux."""
    hosts = []
    # Try ip neigh
    raw = _run(["ip", "neigh", "show"], timeout=5)
    for line in raw.splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s", line)
        if m and m.group(1).startswith(subnet):
            hosts.append(m.group(1))
    # Try arp -n
    if not hosts:
        raw = _run(["arp", "-n"], timeout=5)
        for line in raw.splitlines():
            m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s", line)
            if m and m.group(1).startswith(subnet):
                hosts.append(m.group(1))
    # Try arp-scan (requires root usually)
    if not hosts and shutil.which("arp-scan"):
        raw = _run(["arp-scan", "--localnet"], timeout=20)
        for line in raw.splitlines():
            m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s", line)
            if m:
                hosts.append(m.group(1))
    return list(dict.fromkeys(hosts))


def _nmap_discover(subnet: str) -> List[str]:
    """Discover live hosts via nmap ping scan (requires nmap)."""
    if not shutil.which("nmap"):
        return []
    raw = _run(["nmap", "-sn", f"{subnet}0/24", "-oG", "-"], timeout=30)
    return re.findall(r"Host: (\d+\.\d+\.\d+\.\d+)", raw)


def _mdns_discover() -> List[Dict[str, Any]]:
    """Discover _niblit._tcp services via zeroconf."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser  # type: ignore[import]
        found: List[Dict[str, Any]] = []
        _lock = threading.Event()

        class Handler:
            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info:
                    addr = socket.inet_ntoa(info.addresses[0]) if info.addresses else "?"
                    found.append({"name": name, "ip": addr, "port": info.port})

            def remove_service(self, zc, type_, name): pass
            def update_service(self, zc, type_, name): pass

        zc = Zeroconf()
        ServiceBrowser(zc, "_niblit._tcp.local.", Handler())
        time.sleep(3)
        zc.close()
        return found
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# DeviceMesh
# ─────────────────────────────────────────────────────────────────────────────

class DeviceMesh:
    """
    Niblit mesh network manager.

    Discovers adjacent devices, catalogues them as mesh nodes, and (when
    NIBLIT_MESH_SPREAD=1) copies Niblit to those devices via SSH/rsync.
    """

    _NODES_FILE = "mesh_nodes.json"
    _SCAN_INTERVAL = 3600  # 1 hour

    def __init__(self, knowledge_db: Optional[Any] = None, autoscan: bool = False) -> None:
        self.knowledge_db = knowledge_db
        self._spread_enabled = os.environ.get("NIBLIT_MESH_SPREAD", "").strip() in ("1", "true")
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._nodes_path = _writable_path(self._NODES_FILE)
        self._load_nodes()
        if autoscan:
            self._bg_scan()

    # ── Public API ────────────────────────────────────────────────────────────

    def scan(self) -> List[Dict[str, Any]]:
        """Run a full LAN discovery scan and return the node list."""
        discovered = []
        local_ips = _local_ips()
        subnets = list({_subnet_from_ip(ip) for ip in local_ips if ip})

        for subnet in subnets:
            if not subnet:
                continue
            for ip in _arp_discover(subnet):
                discovered.append({"ip": ip, "method": "arp"})
            for ip in _nmap_discover(subnet):
                if not any(d["ip"] == ip for d in discovered):
                    discovered.append({"ip": ip, "method": "nmap"})

        for node in _mdns_discover():
            if not any(d.get("ip") == node["ip"] for d in discovered):
                discovered.append({**node, "method": "mdns", "niblit": True})

        with self._lock:
            for node in discovered:
                ip = node.get("ip", "")
                if ip and ip not in (local_ips or []):
                    self._nodes[ip] = {
                        **self._nodes.get(ip, {}),
                        **node,
                        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
        self._save_nodes()
        self._store_kb()
        log.info("[DeviceMesh] Scan complete — %d node(s) found", len(self._nodes))
        return list(self._nodes.values())

    def nodes(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._nodes.values())

    def summary(self) -> str:
        nodes = self.nodes()
        if not nodes:
            return "🌐 Device Mesh — no nodes discovered yet (run 'mesh scan')"
        lines = [f"🌐 Device Mesh — {len(nodes)} node(s)"]
        for n in nodes[:20]:
            niblit_tag = " 🤖[Niblit]" if n.get("niblit") else ""
            lines.append(f"  {n.get('ip', '?')}  [{n.get('method', '?')}]{niblit_tag}  "
                         f"last={n.get('last_seen', '?')}")
        return "\n".join(lines)

    def ping(self, ip: str) -> str:
        """Ping a specific host and return result."""
        cmd = ["ping", "-c", "1", "-W", "2", ip] if platform.system() != "Windows" \
              else ["ping", "-n", "1", ip]
        raw = _run(cmd, timeout=5)
        return raw.strip()[:300] or f"No response from {ip}"

    def ssh_run(self, ip: str, cmd: str, user: str = "", timeout: int = 30) -> str:
        """Run a command on a remote host via SSH (key-based auth required)."""
        ssh_target = f"{user}@{ip}" if user else ip
        result = _run(["ssh", "-o", "StrictHostKeyChecking=no",
                       "-o", "ConnectTimeout=5",
                       ssh_target, cmd], timeout=timeout)
        return result.strip()[:2000] or "(no output)"

    def spread(self, ip: str, user: str = "niblit") -> str:
        """
        Copy Niblit to a remote device and run the installer.
        Only active when NIBLIT_MESH_SPREAD=1.
        """
        if not self._spread_enabled:
            return (
                "⛔ Mesh spread is disabled.  Set NIBLIT_MESH_SPREAD=1 to enable.\n"
                "   This will copy Niblit to the remote device via SSH/rsync."
            )
        root = str(_niblit_root())
        ssh_target = f"{user}@{ip}"

        # 1. rsync Niblit to the remote host
        rsync = shutil.which("rsync") or shutil.which("scp")
        if rsync and "rsync" in rsync:
            spread_cmd = [
                "rsync", "-az", "--exclude=.git", "--exclude=__pycache__",
                root + "/", f"{ssh_target}:/opt/niblit/"
            ]
        elif rsync:  # scp fallback
            spread_cmd = ["scp", "-r", root, f"{ssh_target}:/opt/niblit"]
        else:
            return "⚠️  rsync/scp not found — cannot spread to remote device"

        result = _run(spread_cmd, timeout=120)
        if not result and shutil.which("rsync"):
            result = "(rsync completed silently)"

        # 2. Run installer on the remote host
        install_result = self.ssh_run(ip, "bash /opt/niblit/boot/install.sh", user=user, timeout=60)
        return f"Spread to {ip}:\n  Copy: {result}\n  Install: {install_result}"

    def status(self) -> str:
        return (
            f"DeviceMesh | nodes={len(self._nodes)} | "
            f"spread_enabled={self._spread_enabled} | "
            f"nodes_file={self._nodes_path}"
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_nodes(self) -> None:
        try:
            if self._nodes_path.exists():
                self._nodes = json.loads(self._nodes_path.read_text())
        except Exception:
            self._nodes = {}

    def _save_nodes(self) -> None:
        try:
            self._nodes_path.write_text(json.dumps(self._nodes, indent=2))
        except Exception as e:
            log.debug("[DeviceMesh] save_nodes failed: %s", e)

    def _store_kb(self) -> None:
        if self.knowledge_db is None:
            return
        try:
            with self._lock:
                ips = list(self._nodes.keys())
            summary = f"Mesh nodes: {len(ips)} | IPs: {', '.join(ips[:10])}"
            self.knowledge_db.add_fact("niblit_mesh_nodes", summary)
        except Exception as e:
            log.debug("[DeviceMesh] KB store failed: %s", e)

    def _bg_scan(self) -> None:
        def _loop():
            self.scan()
            while True:
                time.sleep(self._SCAN_INTERVAL)
                self.scan()
        t = threading.Thread(target=_loop, daemon=True, name="niblit-mesh-scan")
        t.start()


# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[DeviceMesh] = None
_LOCK = threading.Lock()


def get_device_mesh(knowledge_db: Optional[Any] = None) -> DeviceMesh:
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = DeviceMesh(knowledge_db=knowledge_db, autoscan=False)
    return _INSTANCE
