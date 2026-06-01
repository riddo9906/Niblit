"""
niblit_dashboard.py — Niblit AIOS Dashboard (canonical Kivy APK entry point)
=============================================================================

This IS the Niblit APK UI — equivalent to kivy_app.py.
Both files run the same app; this file is the primary reference implementation.

Architecture
------------
┌─────────────────────────────────────────────────────────────────┐
│  NiblitKivyApp   (Kivy App)                                     │
│                                                                 │
│  ┌─────────────────┐   ┌──────────────────────────────────────┐ │
│  │  SideBarPanel   │   │  Main Area                           │ │
│  │  (command list) │   │  ┌──────────────────────────────┐    │ │
│  │  • Status       │   │  │ SearchPanel  (collapsible)   │    │ │
│  │  • Memory       │   │  └──────────────────────────────┘    │ │
│  │  • Learn Topic  │   │  ┌──────────────────────────────┐    │ │
│  │  • Search       │   │  │ ChatPanel  (local / API)     │    │ │
│  │  • Terminal     │   │  └──────────────────────────────┘    │ │
│  │  • Setup        │   │  ┌──────────────────────────────┐    │ │
│  │  • File Upload  │   │  │ TerminalPanel  (proot shell) │    │ │
│  │                 │   │  └──────────────────────────────┘    │ │
│  └─────────────────┘   │  ┌──────────────────────────────┐    │ │
│                        │  │ SetupPanel  (bootstrap)       │    │ │
│                        │  └──────────────────────────────┘    │ │
│                        └──────────────────────────────────────┘ │
│                                                                 │
│         ProotEnvironment ←── APKBootstrap (first run)          │
└─────────────────────────────────────────────────────────────────┘

Modes
-----
LOCAL  — Niblit runs inside the proot Linux userland (fully offline).
API    — Talks to an external Niblit REST server.

First launch
------------
APKBootstrap auto-starts, installs Alpine Linux + Python3 + Niblit deps
into app-private storage.  Progress shown in the Setup panel.

Usage
-----
    python niblit_dashboard.py         # desktop preview
    buildozer android debug            # build APK

Environment variables
---------------------
NIBLIT_API_URL   External API URL (API mode).  Default: http://10.0.2.2:5000
NIBLIT_API_KEY   Optional API key header.
NIBLIT_MODE      'local' | 'api'
"""

from __future__ import annotations

import os
import sys
import threading

# ── Kivy env flags must come before any kivy import ───────────────────────────
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

try:
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.core.window import Window
    from kivy.lang import Builder
    from kivy.metrics import dp
    from kivy.properties import ListProperty, StringProperty
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.filechooser import FileChooserListView
    from kivy.uix.label import Label
    from kivy.uix.modalview import ModalView
    from kivy.uix.progressbar import ProgressBar
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.spinner import Spinner
    from kivy.uix.textinput import TextInput
    _kivy_available = True
except ImportError:
    _kivy_available = False

if _kivy_available:
    _KIVY_WIDGET_REGISTRATIONS = (
        FileChooserListView,
        ProgressBar,
        ScrollView,
        Spinner,
        TextInput,
    )

try:
    from plyer import permissions as _plyer_permissions
    PLYER_OK = True
except ImportError:
    _plyer_permissions = None
    PLYER_OK = False

try:
    import requests as _requests
    _requests_available = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _requests_available = False

# ── Niblit proot modules (graceful fallback for desktop dev) ──────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from modules.proot_env import get_proot_env, STATUS_READY
    from modules.apk_bootstrap import get_apk_bootstrap
    _proot_available = True
except Exception:
    get_proot_env = None  # type: ignore[assignment]
    get_apk_bootstrap = None  # type: ignore[assignment]
    STATUS_READY = "ready"
    _proot_available = False

# ── Config ────────────────────────────────────────────────────────────────────
_API_URL  = os.getenv("NIBLIT_API_URL", "http://10.0.2.2:5000").rstrip("/")
_API_KEY  = os.getenv("NIBLIT_API_KEY", "")
_TIMEOUT  = 20

# ── Command definitions (sidebar) ─────────────────────────────────────────────
SEARCH_PROVIDERS = ["DDGS", "SerpAPI", "GitHub REST", "Qdrant", "MarketData"]

COMMANDS = [
    {"title": "📊 Status",       "key": "status",      "type": "status"},
    {"title": "🧠 Memory",       "key": "memory",       "type": "panel"},
    {"title": "📚 Learn Topic",  "key": "learn_about",  "type": "input",
     "input_label": "Topic:"},
    {"title": "🔍 Search",       "key": "search",       "type": "search"},
    {"title": "🖥  Terminal",    "key": "terminal",     "type": "terminal"},
    {"title": "⚙  Setup",       "key": "setup",        "type": "setup"},
    {"title": "📁 File Upload",  "key": "file_upload",  "type": "file"},
    {"title": "🔄 Reflect",      "key": "reflect",      "type": "action"},
    {"title": "💡 Self-Idea",    "key": "self-idea",    "type": "action"},
    {"title": "🔬 Self-Research","key": "self-research","type": "input",
     "input_label": "Topic:"},
]

# ──────────────────────────────────────────────────────────────────────────────
# KV layout
# ──────────────────────────────────────────────────────────────────────────────
KV = '''
#:import dp kivy.metrics.dp

<NiblitDashboardRoot>:
    orientation: "horizontal"
    SideBarPanel:
        id: sidebar
        size_hint_x: .32
        on_command_selected: root.on_command_selected(*args)
    BoxLayout:
        id: main_area
        orientation: "vertical"
        spacing: 4
        padding: [4, 4]
        SearchPanel:
            id: search_panel
            size_hint_y: None
            height: 0
            opacity: 0
        BoxLayout:
            id: dynamic_panel_area
            orientation: "vertical"
            size_hint_y: None
            height: self.minimum_height
        ChatPanel:
            id: chat_panel
            size_hint_y: 1
        TerminalPanel:
            id: terminal_panel
            size_hint_y: None
            height: 0
            opacity: 0
        SetupPanel:
            id: setup_panel
            size_hint_y: None
            height: 0
            opacity: 0

# ── Sidebar ───────────────────────────────────────────────────────────────────
<SideBarPanel>:
    ScrollView:
        id: scroll
        BoxLayout:
            id: panel_box
            orientation: "vertical"
            size_hint_y: None
            height: self.minimum_height
            padding: [4, 4]
            spacing: 4

# ── Chat panel ────────────────────────────────────────────────────────────────
<ChatPanel>:
    orientation: "vertical"
    padding: [6, 6]
    spacing: 4
    BoxLayout:
        size_hint_y: None
        height: dp(28)
        spacing: 4
        Label:
            text: "Mode:"
            size_hint_x: None
            width: dp(46)
            font_size: "12sp"
        Spinner:
            id: mode_spinner
            text: "local"
            values: ["local", "api"]
            size_hint_x: None
            width: dp(90)
            font_size: "12sp"
            on_text: app.on_mode_change(self.text)
        Label:
            id: conn_label
            text: "Initialising…"
            font_size: "11sp"
            color: 0.6, 0.6, 0.6, 1
            halign: "left"
            text_size: self.size
    ScrollView:
        id: chat_scroll
        size_hint_y: 1
        do_scroll_x: False
        BoxLayout:
            id: chat_box
            orientation: "vertical"
            size_hint_y: None
            height: self.minimum_height
            padding: [4, 4]
            spacing: 3
    BoxLayout:
        size_hint_y: None
        height: dp(50)
        spacing: 6
        TextInput:
            id: chat_input
            hint_text: root.input_hint
            multiline: False
            size_hint_x: 0.8
            on_text_validate: app.send_chat(self.text)
        Button:
            text: "Send"
            size_hint_x: 0.2
            background_color: 0.2, 0.5, 0.9, 1
            on_press: app.send_chat(chat_input.text)

# ── Terminal panel ────────────────────────────────────────────────────────────
<TerminalPanel>:
    orientation: "vertical"
    padding: [4, 4]
    spacing: 4
    BoxLayout:
        size_hint_y: None
        height: dp(24)
        Label:
            text: "🖥  proot terminal"
            font_size: "12sp"
            bold: True
            color: 0.3, 0.9, 0.5, 1
        Button:
            text: "✕"
            size_hint_x: None
            width: dp(28)
            font_size: "12sp"
            background_color: 0.4, 0.1, 0.1, 1
            on_press: app.hide_terminal()
    ScrollView:
        id: term_scroll
        size_hint_y: 1
        do_scroll_x: False
        TextInput:
            id: term_output
            readonly: True
            text: "$ "
            font_size: "12sp"
            size_hint_y: None
            height: max(self.minimum_height, dp(120))
            background_color: 0.04, 0.04, 0.04, 1
            foreground_color: 0.2, 0.95, 0.3, 1
    BoxLayout:
        size_hint_y: None
        height: dp(42)
        spacing: 4
        TextInput:
            id: term_input
            hint_text: "Enter command…"
            multiline: False
            size_hint_x: 0.75
            font_size: "12sp"
            background_color: 0.08, 0.08, 0.08, 1
            foreground_color: 0.9, 0.9, 0.9, 1
            on_text_validate: app.run_term_cmd(self.text, self)
        Button:
            text: "Run"
            size_hint_x: 0.15
            font_size: "12sp"
            background_color: 0.1, 0.55, 0.2, 1
            on_press: app.run_term_cmd(term_input.text, term_input)
        Button:
            text: "Clr"
            size_hint_x: 0.10
            font_size: "11sp"
            background_color: 0.3, 0.1, 0.1, 1
            on_press: app.clear_terminal()
    BoxLayout:
        size_hint_y: None
        height: dp(34)
        spacing: 4
        Button:
            text: "Open shell"
            size_hint_x: 0.5
            font_size: "11sp"
            background_color: 0.15, 0.3, 0.5, 1
            on_press: app.open_shell()
        Button:
            text: "niblit status"
            size_hint_x: 0.5
            font_size: "11sp"
            background_color: 0.2, 0.35, 0.2, 1
            on_press: app.run_niblit_status()

# ── Setup / Bootstrap panel ───────────────────────────────────────────────────
<SetupPanel>:
    orientation: "vertical"
    padding: [6, 6]
    spacing: 6
    BoxLayout:
        size_hint_y: None
        height: dp(24)
        Label:
            text: "⚙  Niblit APK Setup"
            font_size: "12sp"
            bold: True
            color: 0.3, 0.7, 1, 1
        Button:
            text: "✕"
            size_hint_x: None
            width: dp(28)
            font_size: "12sp"
            background_color: 0.4, 0.1, 0.1, 1
            on_press: app.hide_setup()
    BoxLayout:
        size_hint_y: None
        height: dp(26)
        spacing: 4
        Label:
            text: "Progress:"
            size_hint_x: None
            width: dp(72)
            font_size: "11sp"
        ProgressBar:
            id: setup_progress
            max: 100
            value: 0
    Label:
        id: setup_status_label
        text: "Tap '▶ Run Setup' to begin"
        font_size: "11sp"
        size_hint_y: None
        height: dp(22)
        color: 0.7, 0.7, 0.7, 1
        halign: "left"
        text_size: self.size
    ScrollView:
        size_hint_y: 1
        do_scroll_x: False
        TextInput:
            id: setup_log
            readonly: True
            text: ""
            font_size: "11sp"
            size_hint_y: None
            height: max(self.minimum_height, dp(80))
            background_color: 0.05, 0.05, 0.05, 1
            foreground_color: 0.78, 0.78, 0.78, 1
    BoxLayout:
        size_hint_y: None
        height: dp(36)
        spacing: 4
        Button:
            text: "▶ Run Setup"
            size_hint_x: 0.5
            font_size: "12sp"
            background_color: 0.1, 0.45, 0.75, 1
            on_press: app.start_bootstrap()
        Button:
            text: "📋 Info"
            size_hint_x: 0.5
            font_size: "12sp"
            background_color: 0.25, 0.25, 0.25, 1
            on_press: app.show_proot_info()

# ── Search panel ──────────────────────────────────────────────────────────────
<SearchPanel>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(56)
    spacing: dp(8)
    padding: [4, 4]
    Spinner:
        id: search_provider
        text: "DDGS"
        values: app.search_providers
        size_hint_x: None
        width: dp(110)
        font_size: "12sp"
    TextInput:
        id: search_input
        hint_text: "Search query…"
        multiline: False
        font_size: "12sp"
        on_text_validate: app.do_search(self.text, search_provider.text)
    Button:
        text: "Go"
        size_hint_x: None
        width: dp(44)
        background_color: 0.2, 0.5, 0.9, 1
        on_press: app.do_search(search_input.text, search_provider.text)
    Button:
        text: "✕"
        size_hint_x: None
        width: dp(28)
        background_color: 0.3, 0.1, 0.1, 1
        on_press: app.hide_search()

# ── File picker modal ─────────────────────────────────────────────────────────
<FilePickerModal>:
    size_hint: None, None
    size: dp(320), dp(400)
    auto_dismiss: False
    BoxLayout:
        orientation: "vertical"
        FileChooserListView:
            id: filechooser
            path: root.current_path
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(8)
            Button:
                text: "Select"
                on_press: root.do_select(filechooser.selection)
            Button:
                text: "Cancel"
                on_press: root.dismiss()

# ── Input bubble ──────────────────────────────────────────────────────────────
<InputBubble>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(44)
    spacing: 4
    Label:
        text: root.label_text
        size_hint_x: .38
        font_size: "12sp"
    TextInput:
        id: ti
        multiline: False
        size_hint_x: .50
        font_size: "12sp"
        on_text_validate: root.submit(ti.text)
    Button:
        text: "OK"
        size_hint_x: .12
        font_size: "12sp"
        on_press: root.submit(ti.text)

# ── Expanded sidebar panel ────────────────────────────────────────────────────
<ExpandedPanel>:
    orientation: "vertical"
    padding: [4, 4]
    spacing: 2
    Label:
        text: root.panel_text
        size_hint_y: None
        height: self.texture_size[1] + dp(8)
        font_size: "12sp"
        halign: "left"
        text_size: self.width, None
    Button:
        text: "Close"
        size_hint_y: None
        height: dp(28)
        font_size: "11sp"
        background_color: 0.3, 0.1, 0.1, 1
        on_press: root.parent.remove_widget(root)
'''


# ──────────────────────────────────────────────────────────────────────────────
# Widget classes
# ──────────────────────────────────────────────────────────────────────────────

if _kivy_available:

    class NiblitDashboardRoot(BoxLayout):
        """Root horizontal layout: sidebar + main area."""

        def on_command_selected(self, cmd_key: str, cmd_type: str) -> None:
            """Forward sidebar command selections into the running dashboard app."""
            app = App.get_running_app()
            app.handle_command(cmd_key, cmd_type)

    class SideBarPanel(BoxLayout):
        """Scrollable sidebar that lists all available commands."""

        def on_kv_post(self, _base_widget) -> None:
            """Build sidebar buttons after the KV tree has created widget ids."""
            Clock.schedule_once(self._build_buttons, 0.1)

        def _build_buttons(self, *_) -> None:
            """Populate the sidebar with the canonical command registry entries."""
            pb = self.ids.panel_box
            pb.clear_widgets()
            for cmd in COMMANDS:
                btn = Button(
                    text=cmd["title"],
                    size_hint_y=None,
                    height=dp(42),
                    font_size="12sp",
                    background_color=(0.18, 0.18, 0.22, 1),
                )
                btn.bind(
                    on_release=lambda b, c=cmd: self.dispatch(
                        "on_command_selected", c["key"], c["type"]
                    )
                )
                pb.add_widget(btn)

        def on_command_selected(self, _key: str, _cmd_type: str) -> None:
            """Dispatch the selected command key and type to the root widget."""
            return None

    class ChatPanel(BoxLayout):
        """Chat area with mode selector and message history."""
        input_hint = StringProperty("Ask Niblit…")

    class TerminalPanel(BoxLayout):
        """proot terminal emulator panel."""

    class SetupPanel(BoxLayout):
        """Bootstrap / setup progress panel."""

    class SearchPanel(BoxLayout):
        """Collapsible search bar."""

    class FilePickerModal(ModalView):
        """Modal file chooser used to route uploads into the dashboard workflow."""
        current_path = StringProperty(os.getcwd())

        def do_select(self, selection) -> None:
            """Send the chosen file path back to the app and close the picker."""
            if selection:
                App.get_running_app().handle_file_selected(selection[0])
                self.dismiss()

    class InputBubble(BoxLayout):
        """Inline prompt bubble for commands that require one extra text input."""
        label_text = StringProperty("Input:")
        cmd_key = StringProperty("")

        def submit(self, text: str) -> None:
            """Submit typed input back to the command dispatcher and remove the bubble."""
            App.get_running_app().handle_input_submit(self.cmd_key, text)
            # Remove bubble after submit
            if self.parent:
                self.parent.remove_widget(self)

    class ExpandedPanel(BoxLayout):
        """Sidebar expansion panel for status, memory, and inspection results."""
        panel_text = StringProperty("")


# ──────────────────────────────────────────────────────────────────────────────
# Chat message label helper + Main App (require Kivy)
# ──────────────────────────────────────────────────────────────────────────────

def _chat_label(text: str, align: str = "left", color=(1, 1, 1, 1)):
    if not _kivy_available:
        return None
    lbl = Label(
        text=text,
        markup=False,
        text_size=(Window.width * 0.65, None),
        halign=align,
        valign="top",
        color=color,
        size_hint_y=None,
        font_size="13sp",
    )
    lbl.bind(texture_size=lambda inst, sz: setattr(inst, "height", sz[1] + 10))
    return lbl


if _kivy_available:

    class NiblitKivyApp(App):
        """Niblit AIOS Dashboard application."""

        search_providers = ListProperty(SEARCH_PROVIDERS)

        def __init__(self, **kwargs):
            """Initialise persistent UI/runtime state before the KV tree is built."""
            super().__init__(**kwargs)
            self.title = "Niblit AIOS"
            self._mode: str = "api"
            self._proot = None
            self._bootstrap = None
            self._shell_proc = None
            self._shell_thread = None
            self._root = None

        def build(self):
            """Create the dashboard root layout and attach runtime-backed panels."""
            Builder.load_string(KV)
            Window.clearcolor = (0.08, 0.08, 0.10, 1)

            # Determine initial mode
            if _proot_available:
                _env = get_proot_env()
                _default_mode = "local" if _env.status == STATUS_READY else "api"
            else:
                _default_mode = "api"
            self._mode: str = os.getenv("NIBLIT_MODE", _default_mode)

            # proot / bootstrap singletons
            self._proot     = get_proot_env()     if _proot_available else None
            self._bootstrap = get_apk_bootstrap() if _proot_available else None

            # Interactive shell state
            self._shell_proc   = None
            self._shell_thread = None

            root = NiblitDashboardRoot()
            self._root = root

            # Set initial mode spinner
            root.ids.chat_panel.ids.mode_spinner.text = self._mode

            # Permissions + initial status check
            if PLYER_OK:
                Clock.schedule_once(self._request_permissions, 0.5)
            Clock.schedule_once(self._initial_status_check, 0.8)

            return root

        # ── Permission request ────────────────────────────────────────────────────

        def _request_permissions(self, *_) -> None:
            try:
                _plyer_permissions.request_permissions([
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.WRITE_EXTERNAL_STORAGE",
                    "android.permission.INTERNET",
                ])
            except Exception:
                pass

        # ── Initial status check ──────────────────────────────────────────────────

        def _initial_status_check(self, *_) -> None:
            if self._proot and self._proot.status == STATUS_READY:
                self._set_conn("🟢 Local proot mode — fully offline capable")
                self._bootstrap_log("✅ Environment already bootstrapped — ready!\n")
            elif self._proot:
                self._set_conn("⚠️  First run — see ⚙ Setup panel")
                self._bootstrap_log(
                    "First launch detected.\n"
                    "Tap '▶ Run Setup' in the ⚙ Setup panel to bootstrap\n"
                    "the offline Linux environment (Alpine Linux + Python3).\n"
                )
                # Auto-start bootstrap on first launch (shown in the Setup panel)
                Clock.schedule_once(lambda _: self.show_setup_panel(), 1)
                Clock.schedule_once(lambda _: self.start_bootstrap(), 1.2)
            else:
                self._set_conn(f"🌐 API mode — checking {_API_URL}…")
                threading.Thread(target=self._ping_api, daemon=True).start()

        # ── Command dispatch (from sidebar) ──────────────────────────────────────

        def handle_command(self, cmd_key: str, cmd_type: str) -> None:
            """Open the UI surface or action mapped to a sidebar command selection."""
            pb = self._root.ids.sidebar.ids.panel_box
            if cmd_type == "status":
                self._fetch_status()
            elif cmd_type == "panel":
                self._fetch_memory()
            elif cmd_type == "input":
                cfg = next((c for c in COMMANDS if c["key"] == cmd_key), {})
                bub = InputBubble(label_text=cfg.get("input_label", "Input:"))
                bub.cmd_key = cmd_key
                pb.add_widget(bub)
            elif cmd_type == "search":
                self.show_search()
            elif cmd_type == "terminal":
                self.show_terminal()
            elif cmd_type == "setup":
                self.show_setup_panel()
            elif cmd_type == "file":
                FilePickerModal().open()
            elif cmd_type == "action":
                self._run_action_cmd(cmd_key)

        def handle_input_submit(self, cmd_key: str, text: str) -> None:
            """Called when an InputBubble is submitted."""
            if not text.strip():
                return
            if cmd_key == "learn_about":
                self._chat_append(f"You: learn about {text}", align="right",
                                  color=(0.4, 0.8, 1, 1))
                self._set_conn("Learning…")
                threading.Thread(
                    target=self._dispatch_command, args=(f"learn about {text}",),
                    daemon=True
                ).start()
            elif cmd_key == "self-research":
                self._chat_append(f"You: self-research {text}", align="right",
                                  color=(0.4, 0.8, 1, 1))
                self._set_conn("Researching…")
                threading.Thread(
                    target=self._dispatch_command, args=(f"self-research {text}",),
                    daemon=True
                ).start()

        def handle_file_selected(self, path: str) -> None:
            """Echo the chosen file path into the chat transcript."""
            self._chat_append(f"[File selected] {path}", color=(0.7, 0.7, 0.7, 1))

        # ── Action commands (reflect, self-idea, etc.) ────────────────────────────

        def _run_action_cmd(self, cmd_key: str) -> None:
            """Dispatch immediate action commands without extra input collection."""
            self._chat_append(f"You: {cmd_key}", align="right", color=(0.4, 0.8, 1, 1))
            self._set_conn(f"Running {cmd_key}…")
            threading.Thread(
                target=self._dispatch_command, args=(cmd_key,), daemon=True
            ).start()

        # ── Mode change ───────────────────────────────────────────────────────────

        def on_mode_change(self, mode: str) -> None:
            """Switch the dashboard between local proot and remote API execution."""
            self._mode = mode
            if mode == "local":
                if self._proot and self._proot.status == STATUS_READY:
                    self._set_conn("🟢 Local proot mode")
                else:
                    self._set_conn("⚠️  proot not ready — run Setup first")
            else:
                self._set_conn(f"🌐 API mode — {_API_URL}")
                threading.Thread(target=self._ping_api, daemon=True).start()

        # ── Chat ──────────────────────────────────────────────────────────────────

        def send_chat(self, text: str) -> None:
            """Queue a chat message for local or remote command execution."""
            chat_input = self._root.ids.chat_panel.ids.chat_input
            text = text.strip()
            if not text:
                return
            chat_input.text = ""
            self._chat_append(f"You: {text}", align="right", color=(0.4, 0.8, 1, 1))
            self._set_conn("Thinking…")
            threading.Thread(
                target=self._dispatch_command, args=(text,), daemon=True
            ).start()

        def _dispatch_command(self, text: str) -> None:
            """Route a command to local proot or remote API depending on mode."""
            if self._mode == "local" and self._proot and self._proot.is_ready:
                reply = self._local_command(text)
            else:
                reply = self._api_command(text)
            Clock.schedule_once(lambda dt, r=reply: self._on_reply(r))

        def _local_command(self, text: str) -> str:
            """Run text as a Niblit command inside proot."""
            escaped = text.replace("'", "'\\''").replace('"', '\\"')
            cmd = (
                "cd /root/niblit && python3 -c \""
                "import sys; sys.path.insert(0,'.'); "
                "from niblit_core import NiblitCore; "
                f"c=NiblitCore(); print(c.handle('{escaped}'))\""
            )
            _, out, err = self._proot.run(cmd, timeout=120)
            return out.strip() or err.strip() or "[No response from local Niblit]"

        def _api_command(self, text: str) -> str:
            if not _requests_available:
                return "[requests not installed — API mode unavailable]"
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
                return resp.json().get("reply", "[no reply]")
            except Exception as exc:
                return f"[API error: {exc}]"

        def _on_reply(self, reply: str) -> None:
            self._chat_append(f"Niblit: {reply}", color=(1, 0.8, 0.3, 1))
            self._set_conn("Ready")

        # ── Status / Memory ───────────────────────────────────────────────────────

        def _fetch_status(self) -> None:
            self._set_conn("Fetching status…")
            threading.Thread(target=self._do_fetch_status, daemon=True).start()

        def _do_fetch_status(self) -> None:
            reply = self._dispatch_command_sync("status")
            Clock.schedule_once(lambda dt, r=reply: (
                self._expand_sidebar_panel(f"Status:\n{r}"),
                self._set_conn("Ready"),
            ))

        def _fetch_memory(self) -> None:
            self._set_conn("Loading memory…")
            threading.Thread(target=self._do_fetch_memory, daemon=True).start()

        def _do_fetch_memory(self) -> None:
            if self._mode == "local" and self._proot and self._proot.is_ready:
                _, out, _ = self._proot.run(
                    "cd /root/niblit && python3 -c \""
                    "import sys; sys.path.insert(0,'.'); "
                    "from niblit_memory import KnowledgeDB; "
                    "db=KnowledgeDB(); "
                    "facts=db.list_facts(10); "
                    "print(f'Facts: {len(facts)}'); "
                    "[print(' •', f.get(\\\"key\\\",\\\"\\\")[:60]) for f in facts[:6]]\"",
                    timeout=60,
                )
                text = out.strip() or "[Memory unavailable]"
            else:
                if not _requests_available:
                    text = "[requests not installed]"
                else:
                    try:
                        headers = {"X-API-Key": _API_KEY} if _API_KEY else {}
                        resp = _requests.get(f"{_API_URL}/memory", headers=headers,
                                             timeout=_TIMEOUT)
                        resp.raise_for_status()
                        facts = resp.json().get("facts", [])
                        text = f"Facts: {len(facts)}\n" + "\n".join(
                            f" • {f.get('key','')[:60]}" for f in facts[:6]
                        )
                    except Exception as exc:
                        text = f"[Memory error: {exc}]"
            Clock.schedule_once(lambda dt, t=text: (
                self._expand_sidebar_panel(f"Memory:\n{t}"),
                self._set_conn("Ready"),
            ))

        def _dispatch_command_sync(self, cmd: str) -> str:
            if self._mode == "local" and self._proot and self._proot.is_ready:
                return self._local_command(cmd)
            return self._api_command(cmd)

        # ── Search ────────────────────────────────────────────────────────────────

        def do_search(self, query: str, provider: str) -> None:
            """Submit a search request and preserve the selected provider in the UI."""
            if not query.strip():
                return
            self.hide_search()
            self._chat_append(f"🔍 Search [{provider}]: {query}", color=(0.6, 0.85, 1, 1))
            self._set_conn(f"Searching via {provider}…")
            threading.Thread(
                target=self._do_search_thread, args=(query,), daemon=True
            ).start()

        def _do_search_thread(self, query: str) -> None:
            """Execute a search request in the active runtime without blocking the UI."""
            if self._mode == "local" and self._proot and self._proot.is_ready:
                cmd = f"search {query}"
                reply = self._local_command(cmd)
            else:
                reply = self._api_command(f"search {query}")
            Clock.schedule_once(lambda dt, r=reply: self._on_reply(r))

        def show_search(self) -> None:
            """Expand the search controls above the chat panel."""
            sp = self._root.ids.search_panel
            sp.height = dp(56)
            sp.opacity = 1

        def hide_search(self) -> None:
            """Collapse the search controls to restore chat space."""
            sp = self._root.ids.search_panel
            sp.height = 0
            sp.opacity = 0

        # ── Terminal ──────────────────────────────────────────────────────────────

        def show_terminal(self) -> None:
            """Expose the embedded proot terminal panel."""
            tp = self._root.ids.terminal_panel
            tp.height = dp(260)
            tp.opacity = 1

        def hide_terminal(self) -> None:
            """Hide the embedded terminal while keeping its session state intact."""
            tp = self._root.ids.terminal_panel
            tp.height = 0
            tp.opacity = 0

        def run_term_cmd(self, cmd: str, input_widget=None) -> None:
            """Run a one-shot shell command inside proot and stream output to the panel."""
            if not cmd.strip():
                return
            if input_widget:
                input_widget.text = ""
            self._term_write(f"$ {cmd}\n")
            if self._proot and self._proot.is_ready:
                threading.Thread(
                    target=self._exec_term_cmd, args=(cmd,), daemon=True
                ).start()
            else:
                self._term_write("[proot not ready — run ⚙ Setup first]\n")

        def _exec_term_cmd(self, cmd: str) -> None:
            rc, out, err = self._proot.run(cmd, timeout=60)
            output = (out or "") + (err or "") or f"[exit {rc}]\n"
            Clock.schedule_once(lambda dt, o=output: self._term_write(o))

        def clear_terminal(self) -> None:
            """Reset the terminal transcript to a clean prompt."""
            self._root.ids.terminal_panel.ids.term_output.text = "$ "

        def open_shell(self) -> None:
            """Open or reuse an interactive proot shell session for the dashboard."""
            if not (self._proot and self._proot.is_ready):
                self._term_write("[proot not ready]\n")
                return
            if self._shell_proc and self._shell_proc.poll() is None:
                self._term_write("[shell already open]\n")
                return
            self._term_write("Opening interactive shell…\n")
            self._shell_proc = self._proot.popen("/bin/sh")
            if not self._shell_proc:
                self._term_write("[Failed to open shell]\n")
                return
            try:
                self._shell_proc.stdin.write(". /root/.profile 2>/dev/null; ")
                self._shell_proc.stdin.flush()
            except Exception:
                pass
            self._shell_thread = threading.Thread(
                target=self._shell_reader, daemon=True
            )
            self._shell_thread.start()

        def _shell_reader(self) -> None:
            try:
                for line in iter(self._shell_proc.stdout.readline, ""):
                    Clock.schedule_once(lambda dt, l=line: self._term_write(l))
            except Exception:
                pass
            Clock.schedule_once(lambda dt: self._term_write("\n[shell exited]\n"))

        def run_niblit_status(self) -> None:
            """Populate the terminal input with a local status command and execute it."""
            tp = self._root.ids.terminal_panel.ids.term_input
            tp.text = (
                "cd /root/niblit && python3 -c \""
                "import sys; sys.path.insert(0,'.'); "
                "from niblit_core import NiblitCore; c=NiblitCore(); print(c._cmd_status(''))\""
            )
            self.run_term_cmd(tp.text, tp)

        # ── Bootstrap / Setup panel ───────────────────────────────────────────────

        def show_setup_panel(self) -> None:
            """Expand the setup panel that drives first-run bootstrap tasks."""
            sp = self._root.ids.setup_panel
            sp.height = dp(280)
            sp.opacity = 1

        def hide_setup(self) -> None:
            """Collapse the setup panel without stopping bootstrap work."""
            sp = self._root.ids.setup_panel
            sp.height = 0
            sp.opacity = 0

        def start_bootstrap(self) -> None:
            """Start the APK bootstrap flow that prepares the local proot runtime."""
            if not _proot_available or self._bootstrap is None:
                self._set_setup_label("proot not available on this platform", 0)
                return
            self._set_setup_label("Starting setup…", 0)
            self._bootstrap_log("=" * 36 + "\nStarting Niblit APK bootstrap…\n")
            self._bootstrap.run(progress_callback=self._bootstrap_cb)

        def _bootstrap_cb(self, msg: str, pct: int) -> None:
            Clock.schedule_once(lambda dt, m=msg, p=pct: self._update_setup_ui(m, p))

        def _update_setup_ui(self, msg: str, pct: int) -> None:
            self._set_setup_label(msg, max(0, pct))
            self._bootstrap_log(f"  {msg}\n")
            if pct == 100:
                self._set_conn("🟢 Local proot mode — fully offline capable")
                self._root.ids.chat_panel.ids.mode_spinner.text = "local"
                self._mode = "local"

        def show_proot_info(self) -> None:
            """Append current proot and bootstrap state details to the setup log."""
            lines: list = []
            if self._proot:
                info = self._proot.info()
                lines += [
                    "── proot ──",
                    f"  status  : {info['status']}",
                    f"  storage : {info['storage_dir']}",
                    f"  rootfs  : {info['rootfs_exists']}",
                    f"  binary  : {bool(info['proot_bin'])}",
                    f"  sentinel: {info['setup_sentinel']}",
                ]
            if self._bootstrap:
                bs = self._bootstrap.get_status()
                lines += [
                    "── bootstrap ──",
                    f"  complete: {bs['bootstrap_complete']}",
                ]
                if "bootstrap_info" in bs:
                    bi = bs["bootstrap_info"]
                    lines.append(f"  done at : {bi.get('completed_at','?')}")
            if not lines:
                lines = ["proot not available"]
            self._bootstrap_log("\n".join(lines) + "\n")

        # ── API helpers ───────────────────────────────────────────────────────────

        def _ping_api(self) -> None:
            if not _requests_available:
                Clock.schedule_once(
                    lambda dt: self._set_conn("API — requests not installed")
                )
                return
            try:
                resp = _requests.get(f"{_API_URL}/health", timeout=5)
                label = (f"🟢 API online — {_API_URL}" if resp.status_code == 200
                         else f"🔴 API error {resp.status_code}")
            except Exception:
                label = f"🔴 API offline — {_API_URL}"
            Clock.schedule_once(lambda dt, l=label: self._set_conn(l))

        # ── UI helpers ────────────────────────────────────────────────────────────

        def _chat_append(self, text: str, align: str = "left",
                         color=(1, 1, 1, 1)) -> None:
            cb = self._root.ids.chat_panel.ids.chat_box
            cb.add_widget(_chat_label(text, align=align, color=color))
            scroll = self._root.ids.chat_panel.ids.chat_scroll
            Clock.schedule_once(lambda dt: setattr(scroll, "scroll_y", 0))

        def _set_conn(self, text: str) -> None:
            self._root.ids.chat_panel.ids.conn_label.text = text

        def _term_write(self, text: str) -> None:
            tp = self._root.ids.terminal_panel
            tp.ids.term_output.text += text
            Clock.schedule_once(
                lambda dt: setattr(tp.ids.term_scroll, "scroll_y", 0)
            )

        def _set_setup_label(self, text: str, pct: int) -> None:
            sp = self._root.ids.setup_panel
            sp.ids.setup_status_label.text = text
            sp.ids.setup_progress.value = pct

        def _bootstrap_log(self, text: str) -> None:
            sp = self._root.ids.setup_panel
            sp.ids.setup_log.text += text
            if len(sp.ids.setup_log.text) > 8000:
                sp.ids.setup_log.text = sp.ids.setup_log.text[-6000:]

        def _expand_sidebar_panel(self, text: str) -> None:
            pb = self._root.ids.sidebar.ids.panel_box
            panel = ExpandedPanel(panel_text=text)
            pb.add_widget(panel)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _kivy_available:
        raise SystemExit(
            "Kivy is required:\n"
            "  pip install kivy\n"
            "Then run:  python niblit_dashboard.py"
        )
    app_cls = globals().get("NiblitKivyApp")
    if app_cls is None:
        raise SystemExit("Kivy app failed to initialise")
    app_cls().run()
