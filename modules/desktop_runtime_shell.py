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


def desktop_ui_supported() -> bool:
    """Return True when launching a desktop UI is likely viable."""
    if os.getenv("NIBLIT_HEADLESS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.getenv("CI", "").strip().lower() in {"1", "true", "yes"}:
        return False
    system = platform.system().lower()
    if system in {"windows", "darwin"}:
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
        self._cognition_feed: deque[str] = deque(maxlen=120)
        self._retrieval_feed: deque[str] = deque(maxlen=120)
        self._memory_synthesis_feed: deque[str] = deque(maxlen=120)
        self._chat_log: deque[str] = deque(maxlen=300)
        self._log_lines: deque[str] = deque(maxlen=400)
        self._log_queue: queue.Queue[str] = queue.Queue(maxsize=1000)
        self._chat_reply_queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=100)
        self._command_history: list[str] = []
        self._history_index: int = 0
        self._mode = os.getenv("NIBLIT_RUNTIME_MODE", "api").strip().lower() or "api"
        self._stop = False
        self._event_bus_subscribed = False
        self._log_handler: _UILogHandler | None = None
        self._activity_frames = ("◐", "◓", "◑", "◒")
        self._activity_idx = 0

    def run(self) -> bool:
        """Launch the desktop shell. Returns True when launched."""
        if not desktop_ui_supported():
            log.warning(
                "Desktop UI not supported in this environment; falling back to CLI mode."
            )
            return False
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            log.warning("Tkinter unavailable: %s — falling back to CLI mode.", exc)
            return False

        try:
            from modules.unified_runtime import get_unified_runtime

            self._runtime = get_unified_runtime()
            self._runtime.boot(core=self.core)
        except Exception:
            self._runtime = None

        self._subscribe_event_bus()
        self._install_log_handler()
        self._emit_startup_telemetry()

        root = tk.Tk()
        root.title("Niblit AIOS Desktop Cognitive Runtime")
        root.geometry("1440x900")
        root.configure(bg="#080b14")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Niblit.TFrame", background="#0f1527")
        style.configure("Niblit.TLabel", background="#0f1527", foreground="#b2c7e6")
        style.configure("NiblitValue.TLabel", background="#0f1527", foreground="#6af7d1")
        style.configure("Niblit.TNotebook", background="#0f1527", borderwidth=0)
        style.configure("Niblit.TNotebook.Tab", background="#1b2740", foreground="#b7c9e8", padding=(10, 6))
        style.map("Niblit.TNotebook.Tab", background=[("selected", "#2a3f63")])

        top = ttk.Frame(root, style="Niblit.TFrame")
        top.pack(fill="x", padx=12, pady=10)

        self._runtime_status_var = tk.StringVar(value="booting")
        self._provider_var = tk.StringVar(value="provider: n/a")
        self._ale_var = tk.StringVar(value="ALE: n/a")
        self._threads_var = tk.StringVar(value="threads: n/a")
        self._facts_var = tk.StringVar(value="facts: n/a")
        self._llama_var = tk.StringVar(value="llama3: n/a")
        self._activity_var = tk.StringVar(value="◐")
        self._mode_var = tk.StringVar(value=self._mode)

        ttk.Label(top, text="Niblit AIOS", style="NiblitValue.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(top, textvariable=self._runtime_status_var, style="NiblitValue.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._provider_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._ale_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._threads_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._facts_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._llama_var, style="Niblit.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, textvariable=self._activity_var, style="NiblitValue.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, text="mode", style="Niblit.TLabel").pack(side="left", padx=(12, 4))
        mode_box = ttk.Combobox(top, textvariable=self._mode_var, values=["api", "local", "normal"], width=9, state="readonly")
        mode_box.pack(side="left")
        mode_box.bind("<<ComboboxSelected>>", self._on_mode_change)

        main = ttk.Frame(root, style="Niblit.TFrame")
        main.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        notebook = ttk.Notebook(main, style="Niblit.TNotebook")
        notebook.pack(fill="both", expand=True)
        self._notebook = notebook

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
        self._timeline_text = self._mk_text(tab("Cognitive Timeline"))
        self._reflection_viewer_text = self._mk_text(tab("Reflection Viewer"))
        self._dataset_text = self._mk_text(tab("Dataset Signals"))

        self._append(self._chat_text, "Niblit Desktop Cognitive Runtime ready.")

        def _on_close() -> None:
            self._stop = True
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)
        self._refresh_loop(root)
        root.mainloop()

        self._cleanup()
        return True

    def _mk_text(self, parent: Any) -> Any:
        from tkinter import scrolledtext

        t = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            bg="#0b1020",
            fg="#c4d8f0",
            insertbackground="#6af7d1",
            selectbackground="#2f4e74",
            selectforeground="#ecf5ff",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
        )
        t.pack(fill="both", expand=True, padx=8, pady=8)
        t._last_text = ""
        self._install_text_interactions(t)
        t.configure(state="disabled")
        return t

    def _mk_chat_input(self, root: Any, tk: Any, main_frame: Any) -> None:
        row = tk.Frame(main_frame, bg="#0f1527")
        row.pack(fill="x", pady=(8, 0))
        self._chat_entry = tk.Text(
            row,
            height=3,
            bg="#111a30",
            fg="#d8e7f9",
            insertbackground="#6af7d1",
            selectbackground="#2f4e74",
            selectforeground="#ecf5ff",
            relief="flat",
            borderwidth=0,
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
        self._chat_entry.bind("<Up>", self._chat_history_up)
        self._chat_entry.bind("<Down>", self._chat_history_down)
        root.bind("<Control-Return>", lambda _e: self._submit_chat())
        self._install_input_context_menu(self._chat_entry, tk)

    def _chat_history_up(self, _event: Any) -> str:
        if not self._command_history:
            return "break"
        self._history_index = max(0, self._history_index - 1)
        self._chat_entry.delete("1.0", "end")
        self._chat_entry.insert("1.0", self._command_history[self._history_index])
        return "break"

    def _chat_history_down(self, _event: Any) -> str:
        if not self._command_history:
            return "break"
        self._history_index = min(len(self._command_history), self._history_index + 1)
        self._chat_entry.delete("1.0", "end")
        if self._history_index < len(self._command_history):
            self._chat_entry.insert("1.0", self._command_history[self._history_index])
        return "break"

    @staticmethod
    def _install_input_context_menu(widget: Any, tk: Any) -> None:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Cut", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: widget.tag_add("sel", "1.0", "end"))

        def _show(event: Any) -> None:
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", _show)

    @staticmethod
    def _install_text_interactions(widget: Any) -> None:
        import tkinter as tk

        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Select All", command=lambda: widget.tag_add("sel", "1.0", "end"))

        def _show(event: Any) -> None:
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", _show)
        widget.bind("<Control-c>", lambda _e: widget.event_generate("<<Copy>>"))

    def _append(self, widget: Any, text: str) -> None:
        near_bottom = float(widget.yview()[1]) >= 0.98 if widget.yview() else True
        widget.configure(state="normal")
        widget.insert("end", text.rstrip() + "\n")
        if near_bottom:
            widget.see("end")
        widget.configure(state="disabled")

    def _replace(self, widget: Any, text: str) -> None:
        normalized = text.rstrip() + "\n"
        if getattr(widget, "_last_text", None) == normalized:
            return
        y_pos = widget.yview()[0] if widget.yview() else 0.0
        near_bottom = float(widget.yview()[1]) >= 0.98 if widget.yview() else True
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", normalized)
        widget._last_text = normalized
        if near_bottom:
            widget.see("end")
        else:
            widget.yview_moveto(y_pos)
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
        self._command_history.append(text)
        self._history_index = len(self._command_history)
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

    def _emit_startup_telemetry(self) -> None:
        """Emit a runtime event and increment telemetry when the desktop shell starts."""
        try:
            from modules.event_bus import NiblitEvent, get_event_bus
            bus = get_event_bus()
            bus.publish(NiblitEvent(
                type="runtime.desktop.launched",
                source="DesktopRuntimeShell",
                payload={"mode": self._mode, "platform": platform.system().lower()},
            ))
        except Exception as exc:
            log.debug("Desktop startup event_bus emission failed: %s", exc)
        try:
            telemetry = getattr(self.core, "telemetry", None)
            if telemetry is not None:
                telemetry.increment_counter("desktop_shell_launches_total")
        except Exception as exc:
            log.debug("Desktop startup telemetry failed: %s", exc)

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
        self._activity_idx = (self._activity_idx + 1) % len(self._activity_frames)
        self._activity_var.set(self._activity_frames[self._activity_idx])
        root.after(700, lambda: self._refresh_loop(root))

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
        cognition = {}
        if self._runtime is not None:
            try:
                snap = self._runtime.state(core=self.core)
                runtime_state = snap.get("state", {})
                providers = snap.get("providers", {})
                telemetry = snap.get("telemetry", {})
                events_stats = snap.get("events", {})
                cognition = snap.get("cognition", {})
                new_events = self._runtime.events(since=self._runtime_event_cursor, limit=200)
                for ev in new_events:
                    self._runtime_event_cursor = max(self._runtime_event_cursor, int(ev.get("id", 0)))
                    event_type = str(ev.get("type", "event"))
                    line = f"{event_type} | {ev.get('source', 'runtime')} | {str(ev.get('payload', {}))[:240]}"
                    self._runtime_events.append(line)
                    if any(token in event_type for token in ("cognition", "reflection", "response.complete")):
                        self._cognition_feed.append(line)
                    if any(token in event_type for token in ("live.ingestion", "research", "knowledge_gap", "knowledge")):
                        self._retrieval_feed.append(line)
                    if any(token in event_type for token in ("memory", "synthesis", "trade_reflection", "market_episode")):
                        self._memory_synthesis_feed.append(line)
            except Exception as exc:
                self._runtime_events.append(f"runtime.error | desktop | {exc}")

        active_provider = runtime_state.get("active_provider", "unknown")
        active_model = runtime_state.get("active_local_model", "unknown")
        mode = runtime_state.get("runtime_mode", self._mode)
        ale = telemetry.get("ale") or {}
        runtime_tasks = telemetry.get("runtime_tasks") or {}
        tokens = telemetry.get("token_usage") or telemetry.get("tokens") or {}
        threads = telemetry.get("threads")
        facts = telemetry.get("facts_count")
        self._runtime_status_var.set(f"mode={mode}")
        self._provider_var.set(f"provider: {active_provider}")
        self._ale_var.set(f"ALE: {'running' if ale.get('running') else 'stopped'} #{ale.get('cycle', 0)}")
        self._threads_var.set(f"threads: {threads if threads is not None else 'n/a'}")
        self._facts_var.set(f"facts: {facts if facts is not None else 'n/a'}")
        self._llama_var.set(f"llama3: {'active' if 'llama' in str(active_model).lower() or 'llama' in str(active_provider).lower() else 'standby'}")

        self._replace(
            self._runtime_text,
            "\n".join(
                [
                    "Live Cognitive Runtime Panel",
                    f"- Runtime mode: {mode}",
                    f"- Active provider: {active_provider}",
                    f"- Active local model: {active_model}",
                    f"- Deployment: {runtime_state.get('deployment', {})}",
                    f"- Loaded models: {runtime_state.get('loaded_models', [])}",
                    f"- Active agents: {runtime_state.get('active_agents', [])}",
                    f"- Command history: {len(runtime_state.get('command_history', []))}",
                    f"- Runtime events buffered: {len(self._runtime_events)}",
                    f"- EventBus stream size: {len(self._event_bus_events)}",
                    f"- Cognition feed size: {len(self._cognition_feed)}",
                    f"- Retrieval feed size: {len(self._retrieval_feed)}",
                    f"- Memory synthesis feed size: {len(self._memory_synthesis_feed)}",
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
                    f"- Local preset: {providers.get('active_local_model', active_model)}",
                    f"- Health: {providers.get('health', {})}",
                    f"- Manager status: {providers.get('manager_status', {})}",
                    f"- Token usage: {tokens}",
                    f"- Task stream: {runtime_tasks}",
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
        self._replace(self._metrics_text, self._metrics_text_value(telemetry, events_stats, cognition))
        self._replace(self._timeline_text, self._timeline_text_value(cognition))
        self._replace(self._reflection_viewer_text, self._reflection_text_value(cognition))
        self._replace(self._dataset_text, self._dataset_text_value(cognition))

    @staticmethod
    def _bar(label: str, value: int, unit: int = 1, width: int = 20) -> str:
        if unit <= 0:
            unit = 1
        n = max(0, min(width, int(value / unit)))
        return f"{label:<14} [{'█' * n}{'·' * (width - n)}] {value}"

    def _telemetry_graph_text(self, telemetry: dict[str, Any], events_stats: dict[str, Any]) -> str:
        threads = int(telemetry.get("threads", 0) or 0)
        facts = int(telemetry.get("facts_count", 0) or 0)
        token_usage = telemetry.get("token_usage") or telemetry.get("tokens") or {}
        token_total = int(token_usage.get("total", token_usage.get("used", 0)) or 0) if isinstance(token_usage, dict) else 0
        counts = events_stats.get("event_counts", {}) or {}
        event_total = int(sum(int(v) for v in counts.values())) if counts else 0
        observability = telemetry.get("event_observability", {}) or {}
        module_observability = telemetry.get("module_event_observability", {}) or {}
        return "\n".join(
            [
                "Telemetry Graphs",
                self._bar("threads", threads, unit=2),
                self._bar("facts", facts, unit=25),
                self._bar("events", event_total, unit=10),
                self._bar("tokens", token_total, unit=200),
                self._bar("dropped", int(observability.get("dropped_events", 0) or 0), unit=1),
                self._bar("unconsumed", int(observability.get("unconsumed_events", 0) or 0), unit=1),
                f"provider_health: {telemetry.get('provider_health', {})}",
                f"core_event_observability: {observability}",
                f"module_event_observability: {module_observability}",
            ]
        )

    def _memory_feed_text(self) -> str:
        lines = ["Memory Activity Feed", "Recent memory synthesis:"]
        if self._memory_synthesis_feed:
            lines.extend(f"- {line}" for line in list(self._memory_synthesis_feed)[-8:])
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
    def _metrics_text_value(telemetry: dict[str, Any], events_stats: dict[str, Any], cognition: dict[str, Any]) -> str:
        event_counts = events_stats.get("event_counts", {}) if isinstance(events_stats, dict) else {}
        significance = events_stats.get("significance", {}) if isinstance(events_stats, dict) else {}
        confidence = cognition.get("confidence_summary", {}) if isinstance(cognition, dict) else {}
        return "\n".join(
            [
                "Cognitive Metrics Display",
                f"telemetry: {telemetry}",
                f"event_counts: {event_counts}",
                f"significance: {significance}",
                f"confidence: {confidence}",
                f"last_event_id: {events_stats.get('last_event_id') if isinstance(events_stats, dict) else 'n/a'}",
                f"dropped_events: {events_stats.get('dropped_events') if isinstance(events_stats, dict) else 'n/a'}",
                f"unconsumed_events: {events_stats.get('unconsumed_events') if isinstance(events_stats, dict) else 'n/a'}",
                f"throughput_last_minute: {events_stats.get('throughput_last_minute') if isinstance(events_stats, dict) else 'n/a'}",
            ]
        )

    @staticmethod
    def _timeline_text_value(cognition: dict[str, Any]) -> str:
        lines = ["Unified Cognitive Timeline"]
        episodes = cognition.get("episodes", []) if isinstance(cognition, dict) else []
        if not episodes:
            lines.append("No cognitive episodes yet.")
            return "\n".join(lines)
        for item in episodes[-10:]:
            ts = item.get("timestamp_lineage", {}).get("closed_at") or item.get("timestamp_lineage", {}).get("last_event_at")
            lines.append(
                f"- {ts} | {item.get('topic', 'episode')} | "
                f"sig={item.get('significance', {}).get('classification', 'low')} | "
                f"conf={float(item.get('confidence_score', 0.0) or 0.0):.2f} | "
                f"eval={float(item.get('evaluation_score', 0.0) or 0.0):.2f}"
            )
        return "\n".join(lines)

    @staticmethod
    def _reflection_text_value(cognition: dict[str, Any]) -> str:
        lines = ["Long-Horizon Reflection Viewer"]
        reflections = cognition.get("reflections", []) if isinstance(cognition, dict) else []
        if not reflections:
            lines.append("No reflections available.")
            return "\n".join(lines)
        for item in reflections:
            lines.append(f"- {item.get('type')}: {item.get('summary')}")
        return "\n".join(lines)

    @staticmethod
    def _dataset_text_value(cognition: dict[str, Any]) -> str:
        lines = ["Dataset Generation Indicators"]
        dataset = cognition.get("datasets", {}) if isinstance(cognition, dict) else {}
        compression = cognition.get("compression", {}) if isinstance(cognition, dict) else {}
        pending = cognition.get("pending_dataset_candidates", []) if isinstance(cognition, dict) else []
        lines.append(f"dataset: {dataset}")
        lines.append(f"compression: {compression}")
        if pending:
            lines.append("pending_candidates:")
            for item in pending[:6]:
                prompt = str(item.get("prompt", ""))[:120]
                lines.append(f"- {prompt}")
        else:
            lines.append("pending_candidates: none")
        return "\n".join(lines)


def launch_desktop_shell(core: Any, io: Any | None = None) -> bool:
    """Launch the desktop shell and return whether launch succeeded."""
    shell = DesktopRuntimeShell(core=core, io=io)
    return shell.run()
