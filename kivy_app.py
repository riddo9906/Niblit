"""
kivy_app.py — Niblit mobile client built with Kivy.

Communicates with the Niblit REST API (server.py / app.py).
Can be packaged as an Android APK using Buildozer::

    buildozer android debug

Local development (desktop preview)::

    python kivy_app.py

Environment variables
---------------------
NIBLIT_API_URL   Base URL of the Niblit API server.
                 Default: http://10.0.2.2:5000  (Android emulator loopback)
NIBLIT_API_KEY   Optional API key sent in the X-API-Key header.
"""

import os
import json
import threading

# Kivy must be imported before anything else sets up the display
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

try:
    from kivy.app import App
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput
    from kivy.uix.button import Button
    from kivy.uix.spinner import Spinner
    from kivy.core.window import Window
    from kivy.clock import Clock
    from kivy.lang import Builder
    _kivy_available = True
except ImportError:
    _kivy_available = False
    print("Kivy is not installed. Run: pip install kivy")

try:
    import requests as _requests
    _requests_available = True
except ImportError:
    _requests = None
    _requests_available = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_API_URL = os.getenv("NIBLIT_API_URL", "http://10.0.2.2:5000").rstrip("/")
_API_KEY = os.getenv("NIBLIT_API_KEY", "")
_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# Kivy KV layout (inline, no separate .kv file required)
# ---------------------------------------------------------------------------
KV = """
<ChatMessage>:
    orientation: 'horizontal'
    size_hint_y: None
    height: self.minimum_height
    padding: [4, 2]

<NiblitRoot>:
    orientation: 'vertical'
    padding: 10
    spacing: 8

    Label:
        text: 'Niblit AI'
        font_size: '22sp'
        bold: True
        size_hint_y: None
        height: '40dp'
        color: 0.3, 0.7, 1, 1

    Label:
        id: status_label
        text: 'Connecting...'
        font_size: '13sp'
        size_hint_y: None
        height: '24dp'
        color: 0.6, 0.6, 0.6, 1

    ScrollView:
        id: scroll_view
        size_hint_y: 1
        do_scroll_x: False

        BoxLayout:
            id: chat_box
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: [4, 4]
            spacing: 4

    BoxLayout:
        orientation: 'horizontal'
        size_hint_y: None
        height: '56dp'
        spacing: 6

        TextInput:
            id: user_input
            hint_text: 'Ask Niblit...'
            multiline: False
            size_hint_x: 0.8
            on_text_validate: app.send_message()

        Button:
            text: 'Send'
            size_hint_x: 0.2
            background_color: 0.2, 0.5, 0.9, 1
            on_press: app.send_message()

    BoxLayout:
        orientation: 'horizontal'
        size_hint_y: None
        height: '36dp'
        spacing: 6

        Button:
            text: 'View Memory'
            size_hint_x: 0.5
            font_size: '12sp'
            background_color: 0.3, 0.3, 0.3, 1
            on_press: app.fetch_memory()

        Button:
            text: 'Clear Chat'
            size_hint_x: 0.5
            font_size: '12sp'
            background_color: 0.4, 0.2, 0.2, 1
            on_press: app.clear_chat()
"""


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _make_message_label(text: str, align: str = "left", color=(1, 1, 1, 1)) -> Label:
    """Create a wrapped, selectable message label."""
    lbl = Label(
        text=text,
        markup=False,
        text_size=(Window.width - 24, None),
        halign=align,
        valign="top",
        color=color,
        size_hint_y=None,
        font_size="14sp",
    )
    lbl.bind(texture_size=lambda inst, sz: setattr(inst, "height", sz[1] + 8))
    return lbl


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class NiblitRoot(BoxLayout):
    """Root layout widget (defined in KV above)."""


class NiblitApp(App):
    """Kivy application class for Niblit mobile client."""

    def build(self):
        Builder.load_string(KV)
        self.title = "Niblit AI"
        Window.clearcolor = (0.1, 0.1, 0.12, 1)
        self.root_widget = NiblitRoot()
        # Schedule a health-check ping shortly after start
        Clock.schedule_once(self._check_connection, 1)
        return self.root_widget

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------

    def send_message(self):
        """Read user input, display it, and fire an async API call."""
        user_input = self.root_widget.ids.user_input
        text = user_input.text.strip()
        if not text:
            return
        user_input.text = ""
        self._append_message(f"You: {text}", align="right", color=(0.4, 0.8, 1, 1))
        self._set_status("Thinking…")
        threading.Thread(
            target=self._call_chat,
            args=(text,),
            daemon=True,
        ).start()

    def fetch_memory(self):
        """Fetch memory facts from /memory and display a summary."""
        self._set_status("Loading memory…")
        threading.Thread(target=self._call_memory, daemon=True).start()

    def clear_chat(self):
        """Clear all messages from the chat box."""
        chat_box = self.root_widget.ids.chat_box
        chat_box.clear_widgets()
        self._set_status("Chat cleared")

    # ------------------------------------------------------------------
    # Network calls (run on background threads)
    # ------------------------------------------------------------------

    def _call_chat(self, text: str) -> None:
        try:
            headers = {"Content-Type": "application/json"}
            if _API_KEY:
                headers["X-API-Key"] = _API_KEY
            resp = _requests.post(
                f"{_API_URL}/chat",
                json={"text": text},
                headers=headers,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data.get("reply", "[no reply]")
            Clock.schedule_once(lambda dt: self._on_chat_reply(reply))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            err = f"[Error: {exc}]"
            Clock.schedule_once(lambda dt, e=err: self._on_chat_reply(e))

    def _call_memory(self) -> None:
        try:
            headers = {}
            if _API_KEY:
                headers["X-API-Key"] = _API_KEY
            resp = _requests.get(
                f"{_API_URL}/memory",
                headers=headers,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            facts = resp.json().get("facts", [])
            summary = f"Memory: {len(facts)} facts stored."
            if facts:
                preview = "; ".join(
                    str(f.get("key", "")) for f in facts[:5]
                )
                summary += f"\nLatest keys: {preview}"
            Clock.schedule_once(lambda dt, s=summary: self._on_memory_result(s))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            err = f"[Memory error: {exc}]"
            Clock.schedule_once(lambda dt, e=err: self._on_memory_result(e))

    def _check_connection(self, _dt=None) -> None:
        threading.Thread(target=self._ping, daemon=True).start()

    def _ping(self) -> None:
        try:
            resp = _requests.get(f"{_API_URL}/health", timeout=5)
            if resp.status_code == 200:
                Clock.schedule_once(
                    lambda dt: self._set_status(f"Connected — {_API_URL}")
                )
            else:
                Clock.schedule_once(
                    lambda dt: self._set_status(f"Server error {resp.status_code}")
                )
        except Exception:  # pylint: disable=broad-exception-caught
            Clock.schedule_once(
                lambda dt: self._set_status(f"Offline — using {_API_URL}")
            )

    # ------------------------------------------------------------------
    # UI update helpers (must run on main thread via Clock.schedule_once)
    # ------------------------------------------------------------------

    def _on_chat_reply(self, reply: str) -> None:
        self._append_message(f"Niblit: {reply}", color=(1, 0.8, 0.3, 1))
        self._set_status("Ready")

    def _on_memory_result(self, summary: str) -> None:
        self._append_message(f"[Memory] {summary}", color=(0.7, 0.7, 0.7, 1))
        self._set_status("Ready")

    def _append_message(self, text: str, align: str = "left", color=(1, 1, 1, 1)) -> None:
        chat_box = self.root_widget.ids.chat_box
        lbl = _make_message_label(text, align=align, color=color)
        chat_box.add_widget(lbl)
        scroll = self.root_widget.ids.scroll_view
        Clock.schedule_once(lambda dt: setattr(scroll, "scroll_y", 0))

    def _set_status(self, text: str) -> None:
        self.root_widget.ids.status_label.text = text


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _kivy_available:
        raise SystemExit("Kivy is required. Install it with: pip install kivy")
    if not _requests_available:
        raise SystemExit("requests is required. Install it with: pip install requests")
    NiblitApp().run()
