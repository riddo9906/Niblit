#!/usr/bin/env python3
"""Native desktop cognitive runtime shell for Niblit."""

from __future__ import annotations

import datetime
import logging
import os
import platform
import queue
import threading
from collections import deque
from typing import Any

log = logging.getLogger("Niblit.DesktopShell")


def _is_wsl() -> bool:
    """Return True when running inside Windows Subsystem for Linux."""
    try:
        with open("/proc/version", encoding="utf-8") as _fh:
            content = _fh.read().lower()
            return "microsoft" in content or "wsl" in content
    except Exception:
        return False


def desktop_ui_supported() -> bool:
    """Return True when launching a desktop UI is likely viable."""
    if os.getenv("NIBLIT_HEADLESS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.getenv("CI", "").strip().lower() in {"1", "true", "yes"}:
        return False
    system = platform.system().lower()
    if system in {"windows", "darwin"}:
        return True
    # WSL2 with WSLg (Windows 11 21H2+) provides a display server automatically.
    # Always attempt UI launch on WSL so WSLg users get the desktop shell.
    if _is_wsl():
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


class _UILogHandler(logging.Handler):
    def __init__(self, sink: queue.Queue[str]) -> None:
        super().__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._sink.put_nowait(f"[{ts}] {record.name}: {record.getMessage()}")
        except Exception:
            return


class DesktopRuntimeShell:
    """Tkinter-based native runtime dashboard using existing runtime abstractions."""

    def __init__(self, core: Any, io: Any | None = None) -> None:
        self.core = core
        self.io = io
        self._runtime = None
        self._runtime_event_cursor = 0
        self._runtime_events: deque[str] = deque(maxlen=250)
        self._event_bus_events: deque[str] = deque(maxlen=250)
        self._chat_log: deque[str] = deque(maxlen=300)
        self._log_lines: deque[str] = deque(maxlen=400)
        self._log_queue: queue.Queue[str] = queue.Queue(maxsize=1000)
        self._chat_reply_queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=100)
        self._mode = os.getenv("NIBLIT_RUNTIME_MODE", "api").strip().lower() or "api"
        self._stop = False
        self._event_bus_subscribed = False
        self._log_handler: _UILogHandler | None = None

    def run(self) -> bool:
        """Launch the desktop shell. Returns True when launched."""
        if not desktop_ui_supported():
            _hint = (
                " On WSL, set DISPLAY (e.g. DISPLAY=:0) or use WSL2 with WSLg."
                if _is_wsl()
                else " Set DISPLAY or WAYLAND_DISPLAY to point at a running display server."
            )
            log.warning(
                "Desktop UI unavailable: no display server detected.%s "
                "Use --headless or NIBLIT_HEADLESS=1 to suppress this and run CLI only.",
                _hint,
            )
            return False
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            log.warning("Tkinter unavailable (%s) — falling back to CLI shell.", exc)
            return False

        try:
            from modules.unified_runtime import get_unified_runtime

            self._runtime = get_unified_runtime()
            self._runtime.boot(core=self.core)
        except Exception:
            self._runtime = None

        self._subscribe_event_bus()
        self._install_log_handler()

        root = tk.Tk()
        root.title("Niblit AIOS Desktop Cognitive Runtime")
        root.geometry("1440x900")
        root.configure(bg="#0c0f17")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Niblit.TFrame", background="#0f1422")
        style.configure("Niblit.TLabel", background="#0f1422", foreground="#9fb4d4")
        style.configure("NiblitValue.TLabel", background="#0f1422", foreground="#53f3c4")
        style.configure("Niblit.TNotebook", background="#0f1422", borderwidth=0)
        style.configure("Niblit.TNotebook.Tab", background="#182235", foreground="#a2bddf")
        style.map("Niblit.TNotebook.Tab", background=[("selected", "#223553")])

        top = ttk.Frame(root, style="Niblit.TFrame")
        top.pack(fill="x", padx=12, pady=10)

        self._runtime_status_var = tk.StringVar(value="booting")
        self._provider_var = tk.StringVar(value="provider: n/a")
        self._ale_var = tk.StringVar(value="ALE: n/a")
        self._threads_var = tk.StringVar(value="threads: n/a")
        self._facts_var = tk.StringVar(value="facts: n/a")
        self._mode_var = tk.StringVar(value=self._mode)

        ttk.Label(top, text="Niblit AIOS", style="NiblitValue.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(top, textvariable=self._runtime_status_var, style="NiblitValue.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._provider_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._ale_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._threads_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._facts_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, text="mode", style="Niblit.TLabel").pack(side="left", padx=(12, 4))
        mode_box = ttk.Combobox(top, textvariable=self._mode_var, values=["api", "local", "normal"], width=9, state="readonly")
        mode_box.pack(side="left")
        mode_box.bind("<<ComboboxSelected>>", self._on_mode_change)

        main = ttk.Frame(root, style="Niblit.TFrame")
        main.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        notebook = ttk.Notebook(main, style="Niblit.TNotebook")
        notebook.pack(fill="both", expand=True)

        def tab(name: str):
            frm = ttk.Frame(notebook, style="Niblit.TFrame")
            notebook.add(frm, text=name)
            return frm

        self._chat_text = self._mk_text(tab("Chat"))
        self._mk_chat_input(root, tk, main)
        self._runtime_text = self._mk_text(tab("Live Runtime Panel"))
        self._ale_text = self._mk_text(tab("ALE Cycle Monitor"))
        self._provider_text = self._mk_text(tab("Provider/Runtime Monitor"))
        self._telemetry_text = self._mk_text(tab("Telemetry Graphs"))
        self._memory_text = self._mk_text(tab("Memory Activity Feed"))
        self._trading_text = self._mk_text(tab("Trading Intelligence Feed"))
        self._logs_text = self._mk_text(tab("Runtime Logs Console"))
        self._eventbus_text = self._mk_text(tab("EventBus Activity Stream"))
        self._governance_text = self._mk_text(tab("Dev-Agent Governance"))
        self._models_text = self._mk_text(tab("Qdrant/Llama Status"))
        self._tasks_text = self._mk_text(tab("Background Tasks"))
        self._orchestration_text = self._mk_text(tab("Orchestration Graph"))
        self._metrics_text = self._mk_text(tab("Cognitive Metrics"))

        self._append(self._chat_text, "Niblit Desktop Cognitive Runtime ready.")

        def _on_close() -> None:
            self._stop = True
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)
        self._refresh_loop(root)
        root.mainloop()

        self._cleanup()
        return True

    @staticmethod
    def _mk_text(parent: Any) -> Any:
        from tkinter import scrolledtext

        t = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            bg="#0b0f1a",
            fg="#a8c3e2",
            insertbackground="#4ef3c4",
            font=("Consolas", 10),
        )
        t.pack(fill="both", expand=True, padx=8, pady=8)
        t.configure(state="disabled")
        return t

    def _mk_chat_input(self, root: Any, tk: Any, main_frame: Any) -> None:
        row = tk.Frame(main_frame, bg="#0f1422")
        row.pack(fill="x", pady=(8, 0))
        self._chat_entry = tk.Text(
            row,
            height=3,
            bg="#121a2a",
            fg="#d8e7f9",
            insertbackground="#4ef3c4",
            font=("Segoe UI", 11),
        )
        self._chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        btn = tk.Button(
            row,
            text="Send",
            bg="#14304a",
            fg="#53f3c4",
            activebackground="#1b4468",
            relief="flat",
            command=self._submit_chat,
            padx=18,
            pady=8,
        )
        btn.pack(side="left")
        self._chat_entry.bind("<Control-Return>", lambda _e: self._submit_chat())
        root.bind("<Control-Return>", lambda _e: self._submit_chat())

    def _append(self, widget: Any, text: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", text.rstrip() + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _replace(self, widget: Any, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text.rstrip() + "\n")
        widget.configure(state="disabled")

    def _on_mode_change(self, _event: Any = None) -> None:
        mode = (self._mode_var.get() or "api").strip().lower()
        self._mode = mode
        os.environ["NIBLIT_RUNTIME_MODE"] = mode

    def _submit_chat(self) -> None:
        text = self._chat_entry.get("1.0", "end").strip()
        if not text:
            return
        self._chat_entry.delete("1.0", "end")
        self._chat_log.append(f"You: {text}")
        self._append(self._chat_text, f"You: {text}")
        threading.Thread(target=self._run_chat_command, args=(text,), daemon=True).start()

    def _run_chat_command(self, text: str) -> None:
        try:
            if self._runtime is not None:
                reply = self._runtime.dispatch_command(command=text, core=self.core)
            elif getattr(self.core, "router", None):
                reply = self.core.router.process(text)
            else:
                reply = self.core.handle(text)
        except Exception as exc:
            reply = f"[error] {exc}"
        try:
            self._chat_reply_queue.put_nowait((text, str(reply)))
        except Exception:
            return

    def _subscribe_event_bus(self) -> None:
        if self._event_bus_subscribed:
            return
        try:
            rm = getattr(self.core, "runtime_manager", None)
            bus = getattr(rm, "event_bus", None)
            if bus is None:
                return

            def _on_event(event: Any) -> None:
                etype = getattr(getattr(event, "type", None), "value", None) or str(getattr(event, "type", "event"))
                source = str(getattr(event, "source", "unknown"))
                payload = getattr(event, "payload", {}) or {}
                line = f"{etype} | {source} | {str(payload)[:240]}"
                self._event_bus_events.append(line)

            bus.subscribe_all(_on_event)
            self._event_bus_subscribed = True
        except Exception:
            return

    def _install_log_handler(self) -> None:
        if self._log_handler is not None:
            return
        try:
            handler = _UILogHandler(self._log_queue)
            logging.getLogger().addHandler(handler)
            self._log_handler = handler
        except Exception:
            self._log_handler = None

    def _cleanup(self) -> None:
        if self._log_handler is not None:
            try:
                logging.getLogger().removeHandler(self._log_handler)
            except Exception:
                pass
            self._log_handler = None

    def _refresh_loop(self, root: Any) -> None:
        if self._stop:
            return
        self._drain_queues()
        self._refresh_runtime()
        root.after(1400, lambda: self._refresh_loop(root))

    def _drain_queues(self) -> None:
        while True:
            try:
                _q, reply = self._chat_reply_queue.get_nowait()
                self._chat_log.append(f"Niblit: {reply}")
                self._append(self._chat_text, f"Niblit: {reply}")
            except queue.Empty:
                break

        while True:
            try:
                line = self._log_queue.get_nowait()
                self._log_lines.append(line)
            except queue.Empty:
                break

        try:
            from core.notification_queue import notif_queue

            for msg in notif_queue.pop_all():
                self._log_lines.append(f"[notif] {msg}")
        except Exception:
            pass

    def _refresh_runtime(self) -> None:
        runtime_state = {}
        providers = {}
        telemetry = {}
        events_stats = {}
        if self._runtime is not None:
            try:
                snap = self._runtime.state(core=self.core)
                runtime_state = snap.get("state", {})
                providers = snap.get("providers", {})
                telemetry = snap.get("telemetry", {})
                events_stats = snap.get("events", {})
                new_events = self._runtime.events(since=self._runtime_event_cursor, limit=200)
                for ev in new_events:
                    self._runtime_event_cursor = max(self._runtime_event_cursor, int(ev.get("id", 0)))
                    self._runtime_events.append(
                        f"{ev.get('type', 'event')} | {ev.get('source', 'runtime')} | {str(ev.get('payload', {}))[:240]}"
                    )
            except Exception as exc:
                self._runtime_events.append(f"runtime.error | desktop | {exc}")

        active_provider = runtime_state.get("active_provider", "unknown")
        mode = runtime_state.get("runtime_mode", self._mode)
        ale = telemetry.get("ale") or {}
        threads = telemetry.get("threads")
        facts = telemetry.get("facts_count")
        self._runtime_status_var.set(f"mode={mode}")
        self._provider_var.set(f"provider: {active_provider}")
        self._ale_var.set(f"ALE: {'running' if ale.get('running') else 'stopped'} #{ale.get('cycle', 0)}")
        self._threads_var.set(f"threads: {threads if threads is not None else 'n/a'}")
        self._facts_var.set(f"facts: {facts if facts is not None else 'n/a'}")

        self._replace(
            self._runtime_text,
            "\n".join(
                [
                    "Live Cognitive Runtime Panel",
                    f"- Runtime mode: {mode}",
                    f"- Active provider: {active_provider}",
                    f"- Deployment: {runtime_state.get('deployment', {})}",
                    f"- Loaded models: {runtime_state.get('loaded_models', [])}",
                    f"- Active agents: {runtime_state.get('active_agents', [])}",
                    f"- Command history: {len(runtime_state.get('command_history', []))}",
                    f"- Runtime events buffered: {len(self._runtime_events)}",
                ]
            ),
        )

        self._replace(
            self._ale_text,
            "\n".join(
                [
                    "ALE Cycle Monitor",
                    f"- Running: {ale.get('running', False)}",
                    f"- Cycle: {ale.get('cycle', 0)}",
                    f"- Topic: {ale.get('topic', 'n/a')}",
                ]
            ),
        )

        self._replace(
            self._provider_text,
            "\n".join(
                [
                    "Provider/Runtime Monitor",
                    f"- Active: {providers.get('active_provider', active_provider)}",
                    f"- Health: {providers.get('health', {})}",
                    f"- Manager status: {providers.get('manager_status', {})}",
                    f"- Event counts: {events_stats.get('event_counts', {})}",
                ]
            ),
        )

        self._replace(self._telemetry_text, self._telemetry_graph_text(telemetry, events_stats))
        self._replace(self._memory_text, self._memory_feed_text())
        self._replace(self._trading_text, self._trading_feed_text())
        self._replace(self._logs_text, "\n".join(self._log_lines) or "No runtime logs yet.")
        self._replace(self._eventbus_text, "\n".join(self._event_bus_events) or "No EventBus events yet.")
        self._replace(self._governance_text, self._governance_text_value())
        self._replace(self._models_text, self._model_status_text())
        self._replace(self._tasks_text, self._tasks_text_value())
        self._replace(self._orchestration_text, self._orchestration_graph_text())
        self._replace(self._metrics_text, self._metrics_text_value(telemetry, events_stats))

    @staticmethod
    def _bar(label: str, value: int, unit: int = 1, width: int = 20) -> str:
        if unit <= 0:
            unit = 1
        n = max(0, min(width, int(value / unit)))
        return f"{label:<14} [{'█' * n}{'·' * (width - n)}] {value}"

    def _telemetry_graph_text(self, telemetry: dict[str, Any], events_stats: dict[str, Any]) -> str:
        threads = int(telemetry.get("threads", 0) or 0)
        facts = int(telemetry.get("facts_count", 0) or 0)
        counts = events_stats.get("event_counts", {}) or {}
        event_total = int(sum(int(v) for v in counts.values())) if counts else 0
        return "\n".join(
            [
                "Telemetry Graphs",
                self._bar("threads", threads, unit=2),
                self._bar("facts", facts, unit=25),
                self._bar("events", event_total, unit=10),
                f"provider_health: {telemetry.get('provider_health', {})}",
            ]
        )

    def _memory_feed_text(self) -> str:
        lines = ["Memory Activity Feed"]
        try:
            facts = self.core.db.list_facts(limit=20)
            for f in facts[:20]:
                lines.append(f"- {f.get('key', 'fact')}: {str(f.get('value', ''))[:120]}")
        except Exception as exc:
            lines.append(f"[memory unavailable] {exc}")
        return "\n".join(lines)

    def _trading_feed_text(self) -> str:
        lines = ["Trading Intelligence Feed"]
        tb = getattr(self.core, "trading_brain", None)
        if tb is None:
            lines.append("trading_brain not initialised")
            return "\n".join(lines)
        try:
            if hasattr(tb, "status"):
                lines.append(str(tb.status()))
            else:
                lines.append(str(tb))
        except Exception as exc:
            lines.append(f"[trading status error] {exc}")
        return "\n".join(lines)

    def _governance_text_value(self) -> str:
        lines = ["Dev-Agent Governance Panel"]
        nda = getattr(self.core, "niblit_dev_agent", None)
        if nda is None:
            lines.append("niblit_dev_agent unavailable")
            return "\n".join(lines)
        try:
            lines.append(f"status: {nda.get_status()}")
            lines.append(f"runtime: {nda.get_runtime_snapshot()}")
            lines.append(f"providers: {nda.get_provider_snapshot()}")
        except Exception as exc:
            lines.append(f"[governance error] {exc}")
        return "\n".join(lines)

    def _model_status_text(self) -> str:
        lines = ["Qdrant/Memory + Llama3 Runtime Status"]
        lines.append(f"vector_store: {getattr(self.core, 'vector_store', None) is not None}")
        lines.append(f"hybrid_qdrant: {getattr(self.core, 'hybrid_qdrant', None) is not None}")
        lines.append(f"memory_store: {getattr(self.core, 'memory_store', None) is not None}")
        lb = getattr(self.core, "local_brain", None)
        if lb is not None and hasattr(lb, "status"):
            try:
                lines.append(f"local_brain: {lb.status()}")
            except Exception as exc:
                lines.append(f"local_brain error: {exc}")
        else:
            lines.append("local_brain not initialised")
        return "\n".join(lines)

    def _tasks_text_value(self) -> str:
        lines = ["Background Task Monitor"]
        rm = getattr(self.core, "runtime_manager", None)
        if rm is None:
            lines.append("runtime_manager unavailable")
            return "\n".join(lines)
        try:
            lines.append(f"runtime_manager_stats: {rm.get_stats()}")
        except Exception as exc:
            lines.append(f"runtime_manager stats error: {exc}")
        try:
            tq = getattr(rm, "task_queue", None)
            if tq is not None and hasattr(tq, "pending_count"):
                lines.append(f"pending_tasks: {tq.pending_count()}")
        except Exception:
            pass
        lines.append(f"active_threads: {len(threading.enumerate())}")
        return "\n".join(lines)

    def _orchestration_graph_text(self) -> str:
        rm = getattr(self.core, "runtime_manager", None)
        if rm is None:
            return "Runtime Orchestration Graph\nruntime_manager unavailable"
        orch = getattr(rm, "orchestrator", None)
        stats = {}
        if orch is not None and hasattr(orch, "get_stats"):
            try:
                stats = orch.get_stats()
            except Exception:
                stats = {}
        return "\n".join(
            [
                "Runtime Orchestration Graph",
                "RuntimeManager",
                "  ├─ EventBus",
                "  ├─ TaskQueue",
                "  └─ Orchestrator",
                f"orchestrator_stats: {stats}",
                f"phase2_agents: {list(getattr(self.core, 'phase2_agents', {}).keys())}",
            ]
        )

    @staticmethod
    def _metrics_text_value(telemetry: dict[str, Any], events_stats: dict[str, Any]) -> str:
        event_counts = events_stats.get("event_counts", {}) if isinstance(events_stats, dict) else {}
        return "\n".join(
            [
                "Cognitive Metrics Display",
                f"telemetry: {telemetry}",
                f"event_counts: {event_counts}",
                f"last_event_id: {events_stats.get('last_event_id') if isinstance(events_stats, dict) else 'n/a'}",
            ]
        )


def launch_desktop_shell(core: Any, io: Any | None = None) -> bool:
    """Launch the desktop shell and return whether launch succeeded."""
    shell = DesktopRuntimeShell(core=core, io=io)
    return shell.run()
