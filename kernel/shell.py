#!/usr/bin/env python3
"""
kernel/shell.py — NiblitOS Python kernel shell
─────────────────────────────────────────────────────────────────────────────
An interactive CLI shell that sits on top of the Python kernel/ abstraction
layer.  It provides a POSIX-like command interface for interacting with all
NiblitOS subsystems:

  • Process management   (ps / spawn / kill)
  • Virtual filesystem   (ls / cat / write / mkdir / touch / rm)
  • Devices              (dev / probe)
  • IPC                  (ipc push / pop / pub / sub / drain / size)
  • Syscalls             (syscall <name> [json-args])
  • Niblit AI tool       (ask / tool / niblit-status)
  • HAL                  (hal info / hal run <cmd…>)
  • OS-level info        (env / uptime / history)

Usage:
  python3 -m kernel.shell          # interactive REPL
  python3 -m kernel.shell --cmd "ask hello"   # single command
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import readline  # noqa: F401  (enables arrow keys / history in input())
import textwrap
import time
from typing import Any

log = logging.getLogger(__name__)

# ── Banner ────────────────────────────────────────────────────────────────────
_BANNER = textwrap.dedent("""
    ╔══════════════════════════════════════════════════════╗
    ║          NiblitOS  —  Kernel Shell  v2.1             ║
    ║  Type 'help' for commands, 'exit' to quit.           ║
    ╚══════════════════════════════════════════════════════╝
""")

_PROMPT = "\033[32mniblit-os\033[0m> "

_START_TIME = time.monotonic()


# ── Shell class ───────────────────────────────────────────────────────────────
class KernelShell:
    """Interactive shell over the NiblitOS Python kernel abstraction."""

    def __init__(self) -> None:
        from kernel import get_os_kernel
        self._kernel = get_os_kernel()
        self._hal: Any = None
        self._running = True
        self._history: list[str] = []

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
            "help":          self._cmd_help,
            "status":        self._cmd_status,
            "version":       self._cmd_version,
            "uptime":        self._cmd_uptime,
            "env":           self._cmd_env,
            "history":       self._cmd_history,
            # process
            "ps":            self._cmd_ps,
            "spawn":         self._cmd_spawn,
            "kill":          self._cmd_kill,
            # filesystem
            "ls":            self._cmd_ls,
            "cat":           self._cmd_cat,
            "write":         self._cmd_write,
            "mkdir":         self._cmd_mkdir,
            "touch":         self._cmd_touch,
            "rm":            self._cmd_rm,
            # devices
            "dev":           self._cmd_dev,
            "probe":         self._cmd_probe,
            # ipc
            "ipc":           self._cmd_ipc,
            # syscall
            "syscall":       self._cmd_syscall,
            # memory
            "mem":           self._cmd_mem,
            # Niblit AI
            "ask":           self._cmd_ask,
            "tool":          self._cmd_tool,
            "niblit-status": self._cmd_niblit_status,
            # hal
            "hal":           self._cmd_hal,
            # misc
            "exit":          self._cmd_exit,
            "quit":          self._cmd_exit,
        }

        handler = dispatch.get(verb)
        if handler:
            try:
                handler(rest.strip())
            except Exception as exc:  # noqa: BLE001
                print(f"Error: {exc}")
        else:
            # Try to dispatch as a syscall before giving up
            try:
                result = self._kernel.syscall_dispatcher.call(verb, {})
                print(json.dumps(result, indent=2, default=str))
            except (KeyError, AttributeError):
                print(f"Unknown command '{verb}'. Type 'help' for a list.")

    # ── Command implementations ───────────────────────────────────────────────

    def _cmd_help(self, _: str) -> None:
        print(textwrap.dedent("""
        Process management:
          ps                        — list running processes
          spawn <name> <cmd>        — spawn a subprocess
          kill  <name>              — stop a named process

        Filesystem (virtual):
          ls    [path]              — list directory (default: cwd)
          cat   <path>              — read a file
          write <path> <content>    — write content to a file
          touch <path>              — create an empty file
          rm    <path>              — remove a file
          mkdir <path>              — create a directory

        Devices:
          dev                       — list registered devices (rich summary)
          probe                     — re-probe all devices

        IPC bus:
          ipc push  <ch> <msg>      — push a message to channel
          ipc pop   <ch>            — pop next message
          ipc drain <ch>            — drain all messages
          ipc pub   <ch> <msg>      — publish (also delivers to subscribers)
          ipc sub   <ch>            — subscribe (future msgs printed)
          ipc size  <ch>            — pending message count
          ipc status                — full IPC status

        Syscall dispatcher:
          syscall [<name> [json]]   — list or invoke a named syscall

        Memory:
          mem                       — memory budget + physical report

        Niblit AI tool:
          ask          <query>      — query Niblit AI
          tool <name>  [json]       — call a Niblit tool
          niblit-status             — show Niblit AI subsystem status

        HAL (Hardware Abstraction Layer):
          hal info                  — HAL platform info
          hal run <cmd>             — run command via HAL
          hal capabilities          — list HAL capabilities

        Misc:
          env    [filter]           — show environment variables
          uptime                    — time since shell start
          history                   — show command history
          status                    — full kernel status (JSON)
          version                   — version info
          exit / quit               — exit the shell

        Any unrecognised command is attempted as a syscall.
        """))

    def _cmd_status(self, _: str) -> None:
        s = self._kernel.status()
        print(json.dumps(s, indent=2, default=str))

    def _cmd_version(self, _: str) -> None:
        print(f"NiblitOS Python Kernel Shell v{self._kernel.VERSION}")
        hal = self._get_hal()
        if hal:
            print(f"HAL: {hal.name}  root={hal.root_path()}")

    def _cmd_uptime(self, _: str) -> None:
        elapsed = time.monotonic() - _START_TIME
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        print(f"Uptime: {h:02d}:{m:02d}:{s:02d}  ({elapsed:.1f}s)")

    def _cmd_env(self, filt: str) -> None:
        for k, v in sorted(os.environ.items()):
            if not filt or filt.lower() in k.lower():
                print(f"  {k}={v}")

    def _cmd_history(self, _: str) -> None:
        for i, cmd in enumerate(self._history[-50:], 1):
            print(f"  {i:3d}  {cmd}")

    # ── Process ───────────────────────────────────────────────────────────────
    def _cmd_ps(self, _: str) -> None:
        procs = self._kernel.process_manager.list_processes()
        if not procs:
            print("No processes running.")
            return
        print(f"{'Name':<20} {'Type':<12} {'State':<12} {'Alive':<6}")
        print("-" * 53)
        for p in procs:
            alive_s = "yes" if p.get("alive") else "no"
            print(f"{p.get('pid','?'):<20} {p.get('type', p.get('kind','?')):<12} {p.get('status','?'):<12} {alive_s:<6}")

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
        ok = self._kernel.process_manager.kill(name)
        print(f"{'Stopped' if ok else 'Not found'}: '{name}'.")

    # ── Filesystem ────────────────────────────────────────────────────────────
    def _cmd_ls(self, path: str) -> None:
        path = path or ""
        try:
            entries = self._kernel.fs_manager.listdir(path)
            for e in entries:
                print(e)
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            print(f"ls: {exc}")

    def _cmd_cat(self, path: str) -> None:
        if not path:
            print("Usage: cat <path>")
            return
        try:
            content = self._kernel.fs_manager.read_file(path)
            print(content, end="" if content.endswith("\n") else "\n")
        except (FileNotFoundError, PermissionError) as exc:
            print(f"cat: {exc}")

    def _cmd_write(self, rest: str) -> None:
        parts = rest.split(None, 1)
        if len(parts) < 2:
            print("Usage: write <path> <content>")
            return
        path, content = parts
        try:
            self._kernel.fs_manager.write_file(path, content + "\n")
            print(f"Written to {path}.")
        except (PermissionError, OSError) as exc:
            print(f"write: {exc}")

    def _cmd_touch(self, path: str) -> None:
        if not path:
            print("Usage: touch <path>")
            return
        try:
            real = self._kernel.fs_manager.resolve(path)
            real.parent.mkdir(parents=True, exist_ok=True)
            real.touch(exist_ok=True)
            print(f"Touched {path}.")
        except (PermissionError, OSError) as exc:
            print(f"touch: {exc}")

    def _cmd_rm(self, path: str) -> None:
        if not path:
            print("Usage: rm <path>")
            return
        try:
            self._kernel.fs_manager.remove(path)
            print(f"Removed {path}.")
        except (FileNotFoundError, PermissionError, IsADirectoryError) as exc:
            print(f"rm: {exc}")

    def _cmd_mkdir(self, path: str) -> None:
        if not path:
            print("Usage: mkdir <path>")
            return
        try:
            self._kernel.fs_manager.mkdir(path)
            print(f"Created directory {path}.")
        except (PermissionError, OSError) as exc:
            print(f"mkdir: {exc}")

    # ── Devices ───────────────────────────────────────────────────────────────
    def _cmd_dev(self, _: str) -> None:
        devs = self._kernel.device_manager.list_devices()
        if not devs:
            print("No devices registered.")
            return
        print(f"  {'Name':<20} {'Type':<15} Details")
        print("  " + "-" * 60)
        for name, info in devs.items():
            kind = info.get("type", "device")
            if kind == "cpu":
                detail = f"arch={info.get('arch','?')} cores={info.get('cores_logical',1)} cpu%={info.get('percent',0):.1f}"
            elif kind == "memory":
                total_mb = info.get("total_bytes", 0) // (1024 * 1024)
                avail_mb = info.get("available_bytes", 0) // (1024 * 1024)
                detail = f"total={total_mb}MB avail={avail_mb}MB used%={info.get('percent',0):.1f}"
            elif kind == "disk":
                parts = info.get("partitions", [])
                detail = f"{len(parts)} partition(s)"
            elif kind == "network":
                ifaces = info.get("interfaces", {})
                up = sum(1 for i in ifaces.values() if i.get("up"))
                detail = f"{len(ifaces)} interface(s) {up} up"
            else:
                detail = str(info)[:50]
            print(f"  {name:<20} {kind:<15} {detail}")

    def _cmd_probe(self, _: str) -> None:
        self._kernel.device_manager.probe_all()
        print("Device probe complete.")

    # ── IPC ──────────────────────────────────────────────────────────────────
    def _cmd_ipc(self, rest: str) -> None:
        parts = rest.split(None, 2)
        if not parts:
            print(json.dumps(self._kernel.ipc.status(), indent=2))
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
                print(f"[{msg.sender}@{msg.topic}] {msg.payload}")
            else:
                print(f"No messages in '{channel}'.")
        elif subcmd == "drain":
            msgs = self._kernel.ipc.drain(channel)
            if msgs:
                for m in msgs:
                    print(f"  [{m.sender}] {m.payload}")
            else:
                print(f"No messages in '{channel}'.")
        elif subcmd == "pub":
            payload = parts[2] if len(parts) > 2 else ""
            count = self._kernel.ipc.publish(channel, payload, sender="shell")
            print(f"Published to '{channel}' ({count} subscriber(s) notified).")
        elif subcmd == "sub":
            def _on_msg(m: Any) -> None:
                print(f"\n[IPC/{channel}] {m.payload}")
            self._kernel.ipc.subscribe(channel, _on_msg)
            print(f"Subscribed to '{channel}'. Future messages will appear here.")
        elif subcmd == "size":
            n = self._kernel.ipc.channel_size(channel)
            print(f"Channel '{channel}' has {n} pending message(s).")
        elif subcmd == "status":
            print(json.dumps(self._kernel.ipc.status(), indent=2))
        else:
            print(f"Unknown ipc sub-command '{subcmd}'.")
            print("Usage: ipc <push|pop|drain|pub|sub|size|status> <channel> [payload]")

    # ── Syscall ───────────────────────────────────────────────────────────────
    def _cmd_syscall(self, rest: str) -> None:
        parts = rest.split(None, 1)
        if not parts:
            names = self._kernel.syscall_dispatcher.all_callable_names()
            print(f"Available syscalls ({len(names)}):")
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
        try:
            result = self._kernel.syscall_dispatcher.call(name, kwargs)
            print(json.dumps(result, indent=2, default=str))
        except KeyError as exc:
            print(f"syscall: {exc}")

    # ── Memory ────────────────────────────────────────────────────────────────
    def _cmd_mem(self, _: str) -> None:
        report = self._kernel.memory_manager.status()
        print(json.dumps(report, indent=2, default=str))

    # ── AI ───────────────────────────────────────────────────────────────────
    def _cmd_ask(self, query: str) -> None:
        if not query:
            print("Usage: ask <query>")
            return
        # Route through NiblitCore directly (the syscall_dispatcher niblit_query
        # only posts to the C++ ring buffer; the Python shell wants an actual reply).
        try:
            from niblit_core import NiblitCore  # type: ignore[import]
            core = NiblitCore()
            answer = core.process(query)
            print(answer if answer else "(no response)")
        except Exception as exc:  # noqa: BLE001
            # Fall back to the syscall dispatcher route
            try:
                result = self._kernel.syscall_dispatcher.call(
                    "niblit_query", {"query": query}
                )
                if isinstance(result, str):
                    print(result)
                else:
                    print(json.dumps(result, indent=2, default=str))
            except Exception:  # noqa: BLE001
                print(f"Niblit unavailable: {exc}")

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
        try:
            result = self._kernel.syscall_dispatcher.call(name, kwargs)
            print(json.dumps(result, indent=2, default=str))
        except KeyError as exc:
            print(f"tool: {exc}")

    def _cmd_niblit_status(self, _: str) -> None:
        """Show the status of the Niblit AI subsystem."""
        try:
            from niblit_core import NiblitCore  # type: ignore[import]
            core = NiblitCore()
            s = core.status() if hasattr(core, "status") else {"available": True}
            print(json.dumps(s, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print(f"Niblit AI: not available ({exc})")

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
            try:
                result = hal.run(cmd, capture=True, timeout=15)
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(f"STDERR: {result.stderr}", end="")
                if result.returncode != 0:
                    print(f"(exit code {result.returncode})")
            except Exception as exc:  # noqa: BLE001
                print(f"hal run error: {exc}")
        elif rest == "capabilities":
            print(json.dumps(hal.capabilities, indent=2))
        else:
            print(f"Unknown hal sub-command '{rest}'. Try: hal info | hal run <cmd> | hal capabilities")

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
                    self._history.append(line)
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
