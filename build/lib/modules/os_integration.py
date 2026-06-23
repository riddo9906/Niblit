"""
os_integration.py — Niblit OS Integration & Service Ownership Layer
====================================================================
Makes Niblit a persistent system-level service on any supported platform:
  • Linux / Raspberry Pi / embedded ARM  — systemd unit
  • Android / Termux                      — Termux:Boot hook
  • macOS                                  — LaunchAgent plist
  • Windows                                — NSSM-based Windows Service
  • Generic (fallback)                     — shell auto-start via ~/.profile

After installation Niblit starts automatically on every boot and runs as a
background daemon that the current OS "wears" — hardware resources are
exposed to Niblit through the host OS, enabling the ALE to propose OS-level
and hardware-level optimisations over time.

Singleton access via ``get_os_integration()``.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_termux() -> bool:
    return (
        os.path.exists("/data/data/com.termux")
        or "termux" in os.environ.get("PREFIX", "").lower()
    )

def _niblit_root() -> Path:
    """Return the absolute path of the Niblit project directory."""
    return Path(__file__).resolve().parent.parent

def _python_exe() -> str:
    return sys.executable

def _run(cmd: list, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        timeout=300,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Platform-specific installers
# ─────────────────────────────────────────────────────────────────────────────

class _LinuxInstaller:
    """Installs Niblit as a systemd user (or system) service on Linux."""

    _UNIT_NAME = "niblit.service"

    @property
    def _user_systemd_dir(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user"

    @property
    def _system_systemd_dir(self) -> Path:
        return Path("/etc/systemd/system")

    def _unit_content(self, root: Path, python: str) -> str:
        return textwrap.dedent(f"""\
            [Unit]
            Description=Niblit AI System — autonomous learning & OS integration layer
            After=network.target

            [Service]
            Type=simple
            WorkingDirectory={root}
            ExecStart={python} {root / "app.py"}
            Restart=always
            RestartSec=10
            StandardOutput=journal
            StandardError=journal
            Environment="PYTHONUNBUFFERED=1"
            Environment="NIBLIT_BOOT_MODE=service"

            [Install]
            WantedBy=default.target
        """)

    def install(self, system_wide: bool = False) -> str:
        root = _niblit_root()
        python = _python_exe()
        unit = self._unit_content(root, python)

        if system_wide and os.geteuid() == 0:
            dest = self._system_systemd_dir / self._UNIT_NAME
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(unit)
            _run(["systemctl", "daemon-reload"], check=False)
            _run(["systemctl", "enable", self._UNIT_NAME], check=False)
            _run(["systemctl", "start", self._UNIT_NAME], check=False)
            return f"✅ Niblit installed as system-wide systemd service → {dest}"
        else:
            dest = self._user_systemd_dir / self._UNIT_NAME
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(unit)
            _run(["systemctl", "--user", "daemon-reload"], check=False)
            _run(["systemctl", "--user", "enable", self._UNIT_NAME], check=False)
            _run(["systemctl", "--user", "start", self._UNIT_NAME], check=False)
            return f"✅ Niblit installed as user systemd service → {dest}"

    def status(self) -> str:
        for scope in (["--user"], []):
            try:
                r = _run(["systemctl"] + scope + ["status", self._UNIT_NAME], check=False)
                if r.returncode == 0:
                    return r.stdout.strip()[:600]
            except Exception:
                pass
        return "niblit.service — not found (run 'os install' to set up)"

    def uninstall(self) -> str:
        for scope in (["--user"], []):
            try:
                _run(["systemctl"] + scope + ["stop", self._UNIT_NAME], check=False)
                _run(["systemctl"] + scope + ["disable", self._UNIT_NAME], check=False)
            except Exception:
                pass
        for candidate in (
            self._user_systemd_dir / self._UNIT_NAME,
            self._system_systemd_dir / self._UNIT_NAME,
        ):
            try:
                candidate.unlink()
            except Exception:
                pass
        return "✅ Niblit systemd service removed"

class _TermuxInstaller:
    """Installs Niblit via Termux:Boot for autostart on Android reboot."""

    @property
    def _boot_dir(self) -> Path:
        return Path.home() / ".termux" / "boot"

    @property
    def _script(self) -> Path:
        return self._boot_dir / "niblit_start.sh"

    def install(self, **_: Any) -> str:
        root = _niblit_root()
        python = _python_exe()
        self._boot_dir.mkdir(parents=True, exist_ok=True)
        script = textwrap.dedent(f"""\
            #!/data/data/com.termux/files/usr/bin/bash
            # Niblit Termux:Boot autostart script
            termux-wake-lock
            cd {root}
            export NIBLIT_BOOT_MODE=service
            nohup {python} app.py >> ~/niblit.log 2>&1 &
        """)
        self._script.write_text(script)
        self._script.chmod(0o755)
        return (
            f"✅ Niblit Termux:Boot hook installed → {self._script}\n"
            "   Install Termux:Boot from F-Droid and grant it permission to start on boot."
        )

    def status(self) -> str:
        if self._script.exists():
            return f"Termux boot hook: {self._script} (exists)"
        return "Termux boot hook: not installed (run 'os install')"

    def uninstall(self) -> str:
        try:
            self._script.unlink()
        except Exception:
            pass
        return "✅ Niblit Termux boot hook removed"

class _MacOSInstaller:
    """Installs Niblit as a macOS LaunchAgent (user-level auto-start)."""

    _LABEL = "io.niblit.daemon"

    @property
    def _plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self._LABEL}.plist"

    def install(self, **_: Any) -> str:
        root = _niblit_root()
        python = _python_exe()
        plist = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>             <string>{self._LABEL}</string>
                <key>ProgramArguments</key>
                <array>
                    <string>{python}</string>
                    <string>{root / "app.py"}</string>
                </array>
                <key>WorkingDirectory</key>  <string>{root}</string>
                <key>RunAtLoad</key>         <true/>
                <key>KeepAlive</key>         <true/>
                <key>EnvironmentVariables</key>
                <dict>
                    <key>NIBLIT_BOOT_MODE</key><string>service</string>
                </dict>
                <key>StandardOutPath</key>   <string>{Path.home()}/Library/Logs/niblit.log</string>
                <key>StandardErrorPath</key> <string>{Path.home()}/Library/Logs/niblit.err</string>
            </dict>
            </plist>
        """)
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._plist_path.write_text(plist)
        _run(["launchctl", "load", str(self._plist_path)], check=False)
        return f"✅ Niblit LaunchAgent installed → {self._plist_path}"

    def status(self) -> str:
        if not self._plist_path.exists():
            return "LaunchAgent plist: not found (run 'os install')"
        try:
            r = _run(["launchctl", "list", self._LABEL], check=False)
            return r.stdout.strip()[:400] or "LaunchAgent plist exists but launchctl gave no output"
        except Exception as e:
            return f"LaunchAgent plist exists but status check failed: {e}"

    def uninstall(self) -> str:
        _run(["launchctl", "unload", str(self._plist_path)], check=False)
        try:
            self._plist_path.unlink()
        except Exception:
            pass
        return "✅ Niblit LaunchAgent removed"

class _WindowsInstaller:
    """Installs Niblit via NSSM (Windows Service wrapper) or Task Scheduler."""

    _SVC_NAME = "NiblitAI"

    def install(self, **_: Any) -> str:
        root = _niblit_root()
        python = _python_exe()
        if shutil.which("nssm"):
            try:
                _run(["nssm", "install", self._SVC_NAME, python, str(root / "app.py")], check=False)
                _run(["nssm", "set", self._SVC_NAME, "AppDirectory", str(root)], check=False)
                _run(["nssm", "set", self._SVC_NAME, "AppEnvironmentExtra",
                      "NIBLIT_BOOT_MODE=service"], check=False)
                _run(["nssm", "start", self._SVC_NAME], check=False)
                return f"✅ Niblit Windows Service installed via NSSM (name={self._SVC_NAME})"
            except Exception as e:
                return f"⚠️ NSSM install failed: {e}"
        # Fallback: Task Scheduler
        bat = root / "boot" / "niblit_start.bat"
        bat.parent.mkdir(exist_ok=True)
        bat.write_text(
            f'@echo off\ncd /d "{root}"\n'
            f'set NIBLIT_BOOT_MODE=service\n'
            f'"{python}" app.py\n'
        )
        try:
            _run([
                "schtasks", "/Create", "/TN", self._SVC_NAME,
                "/TR", str(bat), "/SC", "ONLOGON",
                "/RL", "HIGHEST", "/F",
            ], check=False)
            return (
                f"✅ Niblit scheduled via Task Scheduler (ONLOGON)\n"
                f"   Script: {bat}\n"
                f"   Install NSSM (nssm.cc) for a proper Windows Service."
            )
        except Exception as e:
            return f"⚠️ Task Scheduler setup failed: {e}\n   Manually run: {bat}"

    def status(self) -> str:
        try:
            r = _run(["sc", "query", self._SVC_NAME], check=False)
            return r.stdout.strip()[:400]
        except Exception:
            return "Windows Service: not found (run 'os install')"

    def uninstall(self) -> str:
        if shutil.which("nssm"):
            _run(["nssm", "stop", self._SVC_NAME], check=False)
            _run(["nssm", "remove", self._SVC_NAME, "confirm"], check=False)
        else:
            _run(["schtasks", "/Delete", "/TN", self._SVC_NAME, "/F"], check=False)
        return "✅ Niblit Windows service/task removed"

class _GenericInstaller:
    """Fallback: appends a Niblit autostart line to ~/.profile / ~/.bashrc."""

    def install(self, **_: Any) -> str:
        root = _niblit_root()
        python = _python_exe()
        line = (
            f'\n# Niblit autostart\n'
            f'( cd "{root}" && NIBLIT_BOOT_MODE=service nohup {python} app.py '
            f'>> ~/.niblit.log 2>&1 & )\n'
        )
        for rc in (Path.home() / ".profile", Path.home() / ".bashrc"):
            try:
                content = rc.read_text() if rc.exists() else ""
                if "NIBLIT_BOOT_MODE" not in content:
                    with rc.open("a") as f:
                        f.write(line)
            except Exception:
                pass
        return (
            "✅ Niblit autostart added to ~/.profile and ~/.bashrc\n"
            "   Will start on next login shell. Open a new terminal or run: source ~/.profile"
        )

    def status(self) -> str:
        for rc in (Path.home() / ".profile", Path.home() / ".bashrc"):
            if rc.exists() and "NIBLIT_BOOT_MODE" in rc.read_text():
                return f"Generic autostart: found in {rc}"
        return "Generic autostart: not configured (run 'os install')"

    def uninstall(self) -> str:
        removed = []
        for rc in (Path.home() / ".profile", Path.home() / ".bashrc"):
            if not rc.exists():
                continue
            lines = rc.read_text().splitlines(keepends=True)
            new_lines = []
            skip = False
            for ln in lines:
                if "# Niblit autostart" in ln:
                    skip = True
                if skip and ln.strip() == "":
                    skip = False
                    continue
                if not skip:
                    new_lines.append(ln)
            rc.write_text("".join(new_lines))
            removed.append(str(rc))
        return f"✅ Niblit autostart removed from {', '.join(removed) or 'N/A'}"

# ─────────────────────────────────────────────────────────────────────────────
# OSIntegration — unified facade
# ─────────────────────────────────────────────────────────────────────────────

class OSIntegration:
    """
    Unified OS integration façade.

    Detects the current platform and delegates to the correct installer.
    After calling ``install()`` Niblit will start automatically on every
    hardware boot/login, behaving like an OS-level background service.
    """

    def __init__(self, hardware_scanner: Optional[Any] = None) -> None:
        self.hardware_scanner = hardware_scanner
        self._installer = self._pick_installer()
        self._platform = platform.system()

    # ── Public API ────────────────────────────────────────────────────────────

    def install(self, system_wide: bool = False) -> str:
        """Install Niblit as an auto-starting service on the current platform."""
        try:
            return self._installer.install(system_wide=system_wide)
        except Exception as e:
            log.warning("[OSIntegration] install error: %s", e)
            return f"⚠️ OS install failed: {e}"

    def uninstall(self) -> str:
        """Remove the Niblit auto-start entry."""
        try:
            return self._installer.uninstall()
        except Exception as e:
            return f"⚠️ OS uninstall failed: {e}"

    def status(self) -> str:
        """Return the current service/boot-hook status."""
        try:
            return self._installer.status()
        except Exception as e:
            return f"⚠️ OS status check failed: {e}"

    def info(self) -> str:
        """Return human-readable integration layer info."""
        lines = [
            f"🔌 OSIntegration — Niblit as OS-level daemon",
            f"   Platform    : {self._platform}",
            f"   Installer   : {type(self._installer).__name__}",
            f"   Niblit root : {_niblit_root()}",
            f"   Python      : {_python_exe()}",
        ]
        hw = self.hardware_scanner
        if hw is not None:
            try:
                p = hw.get_profile()
                lines.append(f"   HW type     : {p.get('platform_type', 'unknown')}")
            except Exception:
                pass
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _pick_installer(self):
        if _is_termux():
            return _TermuxInstaller()
        s = platform.system().lower()
        if s == "linux":
            return _LinuxInstaller()
        if s == "darwin":
            return _MacOSInstaller()
        if s == "windows":
            return _WindowsInstaller()
        return _GenericInstaller()

# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[OSIntegration] = None
_LOCK = threading.Lock()

def get_os_integration(hardware_scanner: Optional[Any] = None) -> OSIntegration:
    """Return the process-wide OSIntegration singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = OSIntegration(hardware_scanner=hardware_scanner)
    return _INSTANCE


if __name__ == "__main__":
    print('Running os_integration.py')
