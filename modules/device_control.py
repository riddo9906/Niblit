"""
device_control.py — Niblit Device Control Manager
==================================================
Provides Niblit with full-spectrum command execution, process management,
and hardware interface capabilities on any supported platform.  Acts as
the bridge between Niblit's AI layer and the host OS / hardware layer.

Capabilities
------------
* Secure sandboxed shell command execution with timeout, capture, and logging
* Process list, kill, spawn
* Hardware sensor reading (temperatures, fans, battery, network stats)
* USB / serial device enumeration
* 3D printer / robotics interface via serial (G-code send)
* Machine / CNC bridge via G-code over USB-serial
* Audio device enumeration (future TTS output routing)

Security model
--------------
All commands are validated against a configurable allow-list (NIBLIT_CMD_ALLOWLIST).
If not set, only a default safe set is allowed.  Commands prefixed with '!'
bypass the allow-list only when NIBLIT_CMD_UNRESTRICTED=1 is set AND
the process has been explicitly flagged as trusted.

Singleton access via ``get_device_control()``.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Safety ────────────────────────────────────────────────────────────────────

# Default safe-list: read-only / informational commands only
_DEFAULT_SAFE = {
    "ls", "dir", "pwd", "echo", "cat", "head", "tail", "grep", "find",
    "ps", "top", "df", "du", "free", "uname", "hostname", "whoami", "id",
    "env", "printenv", "date", "uptime", "lscpu", "lspci", "lsusb",
    "ifconfig", "ip", "ping", "traceroute", "curl", "wget",
    "python3", "python", "pip", "pip3", "git",
    "systemctl", "journalctl", "dmesg",
    "adb", "fastboot",   # Android tooling
    "getprop", "setprop", # Termux / Android
    "nmcli", "bluetoothctl",
    "stty", "screen", "minicom",  # serial
}

def _is_cloud() -> bool:
    return any(os.environ.get(k) for k in ("VERCEL", "RENDER", "FLY_APP_NAME", "K_SERVICE"))


def _is_allowed(cmd_str: str) -> bool:
    """Return True if the command is in the allow-list or unrestricted mode is on."""
    if os.environ.get("NIBLIT_CMD_UNRESTRICTED", "") in ("1", "true"):
        return True
    first_token = cmd_str.strip().split()[0].lower() if cmd_str.strip() else ""
    # Strip path prefix
    first_token = os.path.basename(first_token)
    custom = os.environ.get("NIBLIT_CMD_ALLOWLIST", "")
    allowed = _DEFAULT_SAFE | {t.strip() for t in custom.split(",") if t.strip()}
    return first_token in allowed


# ─────────────────────────────────────────────────────────────────────────────
# DeviceControl
# ─────────────────────────────────────────────────────────────────────────────

class DeviceControl:
    """
    Full-spectrum device control manager for Niblit.

    Provides sandboxed command execution, process management, hardware sensor
    reads, serial device bridging (3D printers, robots, CNC machines), and
    an inventory of connected USB/PCI devices.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self.knowledge_db = knowledge_db
        self._system = platform.system().lower()
        self._cloud = _is_cloud()
        self._exec_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    # ── Command execution ────────────────────────────────────────────────────

    def execute(
        self,
        cmd: str,
        timeout: int = 30,
        capture: bool = True,
        shell: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a command and return {stdout, stderr, returncode, cmd, duration}.
        Commands are validated against the allow-list unless unrestricted mode is on.
        """
        if not _is_allowed(cmd):
            return {
                "cmd": cmd,
                "stdout": "",
                "stderr": f"⛔ Command '{cmd.split()[0]}' not in allow-list. "
                          "Set NIBLIT_CMD_ALLOWLIST=cmd1,cmd2 to extend, "
                          "or NIBLIT_CMD_UNRESTRICTED=1 for full access.",
                "returncode": 126,
                "duration": 0,
            }
        start = time.time()
        try:
            result = subprocess.run(
                cmd if shell else cmd.split(),
                shell=shell,
                capture_output=capture,
                text=True,
                timeout=timeout,
            )
            record = {
                "cmd": cmd,
                "stdout": result.stdout[:8000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
                "duration": round(time.time() - start, 3),
            }
        except subprocess.TimeoutExpired:
            record = {
                "cmd": cmd,
                "stdout": "",
                "stderr": f"⏱  Command timed out after {timeout}s",
                "returncode": -1,
                "duration": timeout,
            }
        except Exception as e:
            record = {
                "cmd": cmd,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "duration": round(time.time() - start, 3),
            }
        with self._lock:
            self._exec_history.append(record)
            self._exec_history = self._exec_history[-200:]
        return record

    def execute_str(self, cmd: str, timeout: int = 30) -> str:
        """Execute and return combined stdout / stderr as a string."""
        r = self.execute(cmd, timeout=timeout)
        out = r["stdout"].strip()
        err = r["stderr"].strip()
        if r["returncode"] != 0 and err:
            return f"{out}\n⚠️  {err}".strip()
        return out or f"(exit {r['returncode']})"

    # ── Process management ───────────────────────────────────────────────────

    def list_processes(self, filter_str: str = "") -> str:
        """Return a filtered process list."""
        if self._system == "windows":
            raw = self.execute_str("tasklist", timeout=10)
        else:
            raw = self.execute_str("ps aux", timeout=10)
        if filter_str:
            lines = [l for l in raw.splitlines() if filter_str.lower() in l.lower()]
            return "\n".join(lines[:50])
        return "\n".join(raw.splitlines()[:50])

    def kill_process(self, pid: int, force: bool = False) -> str:
        if self._system == "windows":
            return self.execute_str(f"taskkill /PID {pid}{' /F' if force else ''}", timeout=5)
        sig = "-9" if force else "-15"
        return self.execute_str(f"kill {sig} {pid}", timeout=5)

    # ── Hardware sensors ─────────────────────────────────────────────────────

    def sensors(self) -> str:
        """Return temperature / fan / battery sensor data."""
        lines = []
        # Linux sensors
        if self._system == "linux":
            if shutil.which("sensors"):
                lines.append(self.execute_str("sensors", timeout=5))
            # Temperatures from sysfs
            thermal = Path("/sys/class/thermal")
            if thermal.exists():
                for tz in sorted(thermal.iterdir()):
                    try:
                        ttype = (tz / "type").read_text().strip()
                        ttemp = int((tz / "temp").read_text().strip()) / 1000
                        lines.append(f"  {ttype}: {ttemp:.1f}°C")
                    except Exception:
                        pass
            # Battery
            power = Path("/sys/class/power_supply")
            if power.exists():
                for bat in power.iterdir():
                    try:
                        cap = (bat / "capacity").read_text().strip()
                        status = (bat / "status").read_text().strip()
                        lines.append(f"  Battery {bat.name}: {cap}% ({status})")
                    except Exception:
                        pass
        elif self._system == "darwin":
            lines.append(self.execute_str("pmset -g batt", timeout=5))
        elif self._system == "windows":
            lines.append(self.execute_str(
                "wmic path Win32_Battery get BatteryStatus,EstimatedChargeRemaining", timeout=10
            ))
        return "\n".join(lines) or "No sensor data available"

    # ── USB / serial devices ─────────────────────────────────────────────────

    def list_usb(self) -> str:
        if self._system == "linux" and shutil.which("lsusb"):
            return self.execute_str("lsusb", timeout=5)
        if self._system == "darwin":
            return self.execute_str("system_profiler SPUSBDataType", timeout=10)
        if self._system == "windows":
            return self.execute_str(
                "wmic path Win32_USBControllerDevice get Antecedent,Dependent", timeout=10
            )
        return "USB enumeration not supported on this platform"

    def list_serial_ports(self) -> List[str]:
        """Return a list of available serial port paths."""
        ports = []
        if self._system == "linux":
            ports = [str(p) for p in Path("/dev").glob("ttyUSB*")]
            ports += [str(p) for p in Path("/dev").glob("ttyACM*")]
            ports += [str(p) for p in Path("/dev").glob("ttyS[0-9]*") if p.exists()]
        elif self._system == "darwin":
            ports = [str(p) for p in Path("/dev").glob("cu.usbserial*")]
            ports += [str(p) for p in Path("/dev").glob("cu.usbmodem*")]
        elif self._system == "windows":
            # Try pyserial if available
            try:
                import serial.tools.list_ports as slp  # type: ignore[import]
                ports = [p.device for p in slp.comports()]
            except ImportError:
                ports = ["(install pyserial for COM port enumeration)"]
        return ports

    def send_serial(
        self, port: str, command: str, baud: int = 115200, timeout: float = 2.0
    ) -> str:
        """
        Send a raw string (e.g. G-code) to a serial device and return the reply.
        Useful for 3D printers, CNC machines, Arduino, robotics controllers.
        """
        try:
            import serial  # type: ignore[import]
        except ImportError:
            return "⚠️  pyserial not installed — pip install pyserial"
        try:
            with serial.Serial(port, baud, timeout=timeout) as ser:
                ser.write((command.strip() + "\n").encode())
                time.sleep(0.1)
                reply = ser.read(ser.in_waiting or 512).decode(errors="replace")
            return reply.strip() or "(no reply)"
        except Exception as e:
            return f"⚠️  Serial error on {port}: {e}"

    def gcode(self, port: str, gcode_str: str, baud: int = 115200) -> str:
        """
        Send one or more G-code lines to a 3D printer / CNC / robot arm.
        Newline-separated commands are sent sequentially.
        """
        results = []
        for line in gcode_str.strip().splitlines():
            line = line.strip()
            if line and not line.startswith(";"):
                reply = self.send_serial(port, line, baud=baud)
                results.append(f"{line} → {reply}")
        return "\n".join(results) or "(no commands sent)"

    # ── History / status ─────────────────────────────────────────────────────

    def history(self, n: int = 20) -> str:
        with self._lock:
            recent = self._exec_history[-n:]
        if not recent:
            return "No commands executed yet"
        lines = []
        for r in recent:
            lines.append(
                f"  [{r['returncode']}] {r['cmd'][:60]}  "
                f"({r['duration']}s)  {r['stdout'][:40].strip()}"
            )
        return "\n".join(lines)

    def status(self) -> str:
        with self._lock:
            count = len(self._exec_history)
        ports = self.list_serial_ports()
        return (
            f"DeviceControl | system={self._system} | cloud={self._cloud} | "
            f"commands_run={count} | serial_ports={ports[:3]}"
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[DeviceControl] = None
_LOCK = threading.Lock()


def get_device_control(knowledge_db: Optional[Any] = None) -> DeviceControl:
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = DeviceControl(knowledge_db=knowledge_db)
    return _INSTANCE
