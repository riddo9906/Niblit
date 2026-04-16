#!/usr/bin/env python3
"""
kernel/shell.py — NiblitOS Python kernel shell
─────────────────────────────────────────────────────────────────────────────
An interactive CLI shell that sits on top of the Python kernel/ abstraction
layer.  It provides a POSIX-like command interface for interacting with all
NiblitOS subsystems:

  • Process management   (ps / spawn / kill)
  • Virtual filesystem   (ls / cat / write / mkdir)
  • Devices              (dev / probe)
  • IPC                  (ipc publish / subscribe / pop)
  • Syscalls             (syscall <name> [json-args])
  • Niblit AI tool       (ask / tool)
  • HAL                  (hal info / hal run <cmd…>)

This shell is designed to replace the main.py interactive loop with a
kernel-aware frontend that understands OS-level concepts.

Usage:
  python3 -m kernel.shell          # interactive REPL
  python3 -m kernel.shell --cmd "ask hello"   # single command
"""

from __future__ import annotations

import argparse
import json
import logging
import readline  # noqa: F401  (enables arrow keys / history in input())
import textwrap
from typing import Any

log = logging.getLogger(__name__)

# ── Banner ────────────────────────────────────────────────────────────────────
_BANNER = textwrap.dedent("""
    ╔══════════════════════════════════════════════════════╗
    ║          NiblitOS  —  Kernel Shell  v2.0             ║
    ║  Type 'help' for commands, 'exit' to quit.           ║
    ╚══════════════════════════════════════════════════════╝
""")

_PROMPT = "\033[32mniblit-os\033[0m> "


# ── Shell class ───────────────────────────────────────────────────────────────
class KernelShell:
    """Interactive shell over the NiblitOS Python kernel abstraction."""

    def __init__(self) -> None:
        from kernel import get_os_kernel
        self._kernel = get_os_kernel()
        self._hal = None
        self._running = True

    def _get_hal(self) -> Any:
        if self._hal is None:
            try:
                from kernel.hal import get_hal
                self._hal = get_hal()
            except Exception as exc:  # noqa: BLE001
                print(f"[HAL] unavailable: {exc}")
        return self._hal

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def run_command(self, line: str) -> None:
        parts = line.split(None, 1)
        if not parts:
            return
        verb = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        dispatch = {
            "help":    self._cmd_help,
            "status":  self._cmd_status,
            "version": self._cmd_version,
            # process
            "ps":      self._cmd_ps,
            "spawn":   self._cmd_spawn,
            "kill":    self._cmd_kill,
            # filesystem
            "ls":      self._cmd_ls,
            "cat":     self._cmd_cat,
            "write":   self._cmd_write,
            "mkdir":   self._cmd_mkdir,
            # devices
            "dev":     self._cmd_dev,
            "probe":   self._cmd_probe,
            # ipc
            "ipc":     self._cmd_ipc,
            # syscall
            "syscall": self._cmd_syscall,
            # memory
            "mem":     self._cmd_mem,
            # AI
            "ask":     self._cmd_ask,
            "tool":    self._cmd_tool,
            # hal
            "hal":     self._cmd_hal,
            # misc
            "exit":    self._cmd_exit,
            "quit":    self._cmd_exit,
        }

        handler = dispatch.get(verb)
        if handler:
            try:
                handler(rest.strip())
            except Exception as exc:  # noqa: BLE001
                print(f"Error: {exc}")
        else:
            print(f"Unknown command '{verb}'. Type 'help' for a list.")

    # ── Command implementations ───────────────────────────────────────────────

    def _cmd_help(self, _: str) -> None:
        print(textwrap.dedent("""
        Process management:
          ps                        — list running processes
          spawn <name> <cmd>        — spawn a subprocess
          kill <name>               — stop a named process

        Filesystem (virtual):
          ls [path]                 — list directory (default: /)
          cat <path>                — read a file
          write <path> <content>    — write content to a file
          mkdir <path>              — create a directory

        Devices:
          dev                       — list registered devices
          probe                     — re-probe all devices

        IPC:
          ipc push <channel> <msg>  — push a message
          ipc pop  <channel>        — pop next message
          ipc pub  <channel> <msg>  — publish to subscribers
          ipc sub  <channel>        — subscribe (prints future msgs)

        Syscall dispatcher:
          syscall <name> [json]     — invoke a named syscall

        Memory:
          mem                       — memory budget report

        Niblit AI tool:
          ask <query>               — query Niblit AI
          tool <name> [json]        — call a Niblit tool

        HAL:
          hal info                  — HAL platform info
          hal run <cmd>             — run command via HAL

        Misc:
          status                    — full kernel status
          version                   — version info
          exit / quit               — exit the shell
        """))

    def _cmd_status(self, _: str) -> None:
        s = self._kernel.status()
        print(json.dumps(s, indent=2, default=str))

    def _cmd_version(self, _: str) -> None:
        print(f"NiblitOS Python Kernel Shell v{self._kernel.VERSION}")
        hal = self._get_hal()
        if hal:
            print(f"HAL: {hal.name}  root={hal.root_path()}")

    # ── Process ───────────────────────────────────────────────────────────────
    def _cmd_ps(self, _: str) -> None:
        procs = self._kernel.process_manager.list_processes()
        if not procs:
            print("No processes running.")
            return
        print(f"{'Name':<20} {'Type':<10} {'State':<12} {'PID/TID':<10}")
        print("-" * 55)
        for p in procs:
            print(f"{p['name']:<20} {p['type']:<10} {p['state']:<12} {str(p.get('pid', p.get('tid','-'))):<10}")

    def _cmd_spawn(self, rest: str) -> None:
        parts = rest.split(None, 1)
        if len(parts) < 2:
            print("Usage: spawn <name> <cmd...>")
            return
        name, cmd_str = parts
        cmd = cmd_str.split()
        self._kernel.process_manager.spawn(name, cmd)
        print(f"Spawned '{name}': {cmd}")

    def _cmd_kill(self, name: str) -> None:
        if not name:
            print("Usage: kill <name>")
            return
        self._kernel.process_manager.kill(name)
        print(f"Killed '{name}'.")

    # ── Filesystem ────────────────────────────────────────────────────────────
    def _cmd_ls(self, path: str) -> None:
        path = path or "/"
        entries = self._kernel.fs_manager.listdir(path)
        if entries is None:
            print(f"ls: {path}: not found or not a directory")
        else:
            for e in sorted(entries):
                print(e)

    def _cmd_cat(self, path: str) -> None:
        if not path:
            print("Usage: cat <path>")
            return
        content = self._kernel.fs_manager.read_file(path)
        if content is None:
            print(f"cat: {path}: not found")
        else:
            print(content)

    def _cmd_write(self, rest: str) -> None:
        parts = rest.split(None, 1)
        if len(parts) < 2:
            print("Usage: write <path> <content>")
            return
        path, content = parts
        self._kernel.fs_manager.write_file(path, content)
        print(f"Written to {path}.")

    def _cmd_mkdir(self, path: str) -> None:
        if not path:
            print("Usage: mkdir <path>")
            return
        self._kernel.fs_manager.mkdir(path)
        print(f"Created directory {path}.")

    # ── Devices ───────────────────────────────────────────────────────────────
    def _cmd_dev(self, _: str) -> None:
        devs = self._kernel.device_manager.list_devices()
        for d in devs:
            info = self._kernel.device_manager.get_device(d)
            state = info.get("state", "unknown")
            kind = info.get("type", "device")
            print(f"  {d:<20} {kind:<15} [{state}]")

    def _cmd_probe(self, _: str) -> None:
        self._kernel.device_manager.probe_all()
        print("Device probe complete.")

    # ── IPC ──────────────────────────────────────────────────────────────────
    def _cmd_ipc(self, rest: str) -> None:
        parts = rest.split(None, 2)
        if not parts:
            print("Usage: ipc <push|pop|pub|sub> <channel> [payload]")
            return
        subcmd = parts[0]
        channel = parts[1] if len(parts) > 1 else ""

        if subcmd == "push":
            payload = parts[2] if len(parts) > 2 else ""
            self._kernel.ipc.push(channel, payload, sender="shell")
            print(f"Pushed to '{channel}'.")
        elif subcmd == "pop":
            msg = self._kernel.ipc.pop(channel)
            if msg:
                print(f"[{msg.sender}] {msg.payload}")
            else:
                print(f"No messages in '{channel}'.")
        elif subcmd == "pub":
            payload = parts[2] if len(parts) > 2 else ""
            self._kernel.ipc.publish(channel, payload)
            print(f"Published to '{channel}'.")
        elif subcmd == "sub":
            received: list[Any] = []
            self._kernel.ipc.subscribe(channel, lambda m: received.append(m))
            print(f"Subscribed to '{channel}'. Messages will appear here.")
        else:
            print(f"Unknown ipc sub-command '{subcmd}'.")

    # ── Syscall ───────────────────────────────────────────────────────────────
    def _cmd_syscall(self, rest: str) -> None:
        parts = rest.split(None, 1)
        if not parts:
            # List available syscalls
            names = self._kernel.syscall_dispatcher.list_syscalls()
            print("Available syscalls:")
            for n in names:
                print(f"  {n}")
            return
        name = parts[0]
        kwargs: dict[str, Any] = {}
        if len(parts) > 1:
            try:
                kwargs = json.loads(parts[1])
            except json.JSONDecodeError:
                print("Warning: args not valid JSON, passing as empty dict.")
        result = self._kernel.syscall_dispatcher.call(name, kwargs)
        print(json.dumps(result, indent=2, default=str))

    # ── Memory ────────────────────────────────────────────────────────────────
    def _cmd_mem(self, _: str) -> None:
        report = self._kernel.memory_manager.report()
        print(json.dumps(report, indent=2, default=str))

    # ── AI ───────────────────────────────────────────────────────────────────
    def _cmd_ask(self, query: str) -> None:
        if not query:
            print("Usage: ask <query>")
            return
        # Route through the syscall dispatcher's niblit_query if available,
        # else try NiblitCore directly.
        try:
            result = self._kernel.syscall_dispatcher.call(
                "niblit_query", {"query": query}
            )
            print(json.dumps(result, indent=2, default=str))
        except Exception:  # noqa: BLE001
            try:
                from niblit_core import NiblitCore  # type: ignore[import]
                core = NiblitCore()
                print(core.process(query))
            except Exception as exc2:  # noqa: BLE001
                print(f"Niblit unavailable: {exc2}")

    def _cmd_tool(self, rest: str) -> None:
        parts = rest.split(None, 1)
        if not parts:
            print("Usage: tool <name> [json-args]")
            return
        name = parts[0]
        kwargs: dict[str, Any] = {}
        if len(parts) > 1:
            try:
                kwargs = json.loads(parts[1])
            except json.JSONDecodeError:
                kwargs = {"args": parts[1]}
        result = self._kernel.syscall_dispatcher.call(name, kwargs)
        print(json.dumps(result, indent=2, default=str))

    # ── HAL ───────────────────────────────────────────────────────────────────
    def _cmd_hal(self, rest: str) -> None:
        hal = self._get_hal()
        if not hal:
            print("HAL not available.")
            return
        if rest == "info" or not rest:
            print(json.dumps(hal.info(), indent=2))
        elif rest.startswith("run "):
            cmd = rest[4:].split()
            result = hal.run(cmd, capture=True, timeout=10)
            print(result.stdout or "(no output)")
            if result.stderr:
                print(f"STDERR: {result.stderr}")
        else:
            print(f"Unknown hal sub-command '{rest}'. Try: hal info | hal run <cmd>")

    def _cmd_exit(self, _: str) -> None:
        print("Goodbye.")
        self._running = False

    # ── REPL ─────────────────────────────────────────────────────────────────
    def run(self) -> None:
        print(_BANNER)
        while self._running:
            try:
                line = input(_PROMPT).strip()
                if line:
                    self.run_command(line)
            except KeyboardInterrupt:
                print("\n(Ctrl-C — type 'exit' to quit)")
            except EOFError:
                self._cmd_exit("")

    def run_once(self, cmd: str) -> None:
        self.run_command(cmd)


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kernel.shell",
        description="NiblitOS Python Kernel Shell",
    )
    parser.add_argument("--cmd", "-c", help="Run a single command and exit")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    shell = KernelShell()
    if args.cmd:
        shell.run_once(args.cmd)
    else:
        shell.run()


if __name__ == "__main__":
    main()
