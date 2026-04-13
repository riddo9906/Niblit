"""
niblit_dashboard_app.py — Advanced Niblit Kivy App with Modular Command Panels and Dynamic UI

Features:
- Expandable sidebar for status/command modules
- Dynamic input bubbles for commands with parameters
- Integrated chat panel
- File chooser modal for file-accepting commands
- Permission system prompt (demo example: storage permissions)
- Integrated search panel with provider selection and browser bubble
- Outputs routed to correct panels; easy to wire to backend

IMPORTANT: This is a scaffold for Kivy (>=2.3.0) + KivyMD. 
Install with: pip install kivy kivymd
"""

import os
from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.properties import StringProperty, ObjectProperty, ListProperty
from kivy.metrics import dp

try:
    from plyer import permissions
    PLYER_OK = True
except ImportError:
    PLYER_OK = False

# Demo: Fake search providers and command definitions
SEARCH_PROVIDERS = ["DDGS", "SerpAPI", "GitHub REST", "Serpex", "Qdrant", "MarketData"]
COMMANDS = [
    {"title": "Status", "key": "status", "type": "status"},
    {"title": "Memory", "key": "memory", "type": "panel"},
    {"title": "Learn Topic", "key": "learn_about", "type": "input", "input_label": "Topic:"},
    {"title": "Search", "key": "search", "type": "search"},
    {"title": "File Command", "key": "file_upload", "type": "file"},
    # Add more command definitions as needed...
]

KV = '''
<NiblitDashboardRoot>:
    orientation: "horizontal"
    # Sidebar
    SideBarPanel:
        id: sidebar
        size_hint_x: .33
        on_command_selected: root.on_command_selected(*args)
    # Main area
    BoxLayout:
        id: main_area
        orientation: "vertical"
        spacing: 6
        # Search/top bubble area
        SearchPanel:
            id: search_panel
            size_hint_y: None
            height: 0
        # Chat area
        FloatLayout:
            ChatPanel:
                id: chat_panel
                size_hint: 1, 1

<FilePickerModal@ModalView>:
    size_hint: None, None
    size: dp(320), dp(400)
    auto_dismiss: False
    BoxLayout:
        orientation: 'vertical'
        FileChooserListView:
            id: filechooser
            path: root.current_path
        BoxLayout:
            size_hint_y: None
            height: dp(50)
            spacing: dp(8)
            Button:
                text: "Select"
                on_press: root.on_select(filechooser.selection)
            Button:
                text: "Cancel"
                on_press: root.dismiss()

<SearchPanel@BoxLayout>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(64)
    opacity: 1
    spacing: dp(10)
    Spinner:
        id: search_provider
        text: "DDGS"
        values: app.search_providers
        size_hint_x: None
        width: dp(120)
    TextInput:
        id: search_input
        hint_text: "Enter search query"
        multiline: False
        on_text_validate: root.do_search(search_input.text)
    Button:
        text: "Search"
        on_press: root.do_search(search_input.text)
    Button:
        text: "Hide"
        size_hint_x: None
        width: dp(50)
        on_press: root.have_search.hide_search()

<ChatPanel@BoxLayout>:
    orientation: "vertical"
    padding: [8, 8]
    Label:
        id: chat_log
        size_hint_y: 1
        text: root.chat_history_str
        text_size: self.width, None
        halign: 'left'
        valign: 'top'
    BoxLayout:
        size_hint_y: None
        height: dp(56)
        spacing: dp(6)
        TextInput:
            id: chat_input
            hint_text: root.input_hint
            multiline: False
            on_text_validate: root.send_chat(chat_input.text)
        Button:
            text: "Send"
            on_press: root.send_chat(chat_input.text)
        Button:
            text: "Commands"
            on_press: root.show_commands()

<SideBarPanel@ScrollView>:
    size_hint_x: .33
    BoxLayout:
        id: panel_box
        orientation: "vertical"
        size_hint_y: None
        height: self.minimum_height

<ExpandedPanel@BoxLayout>:
    orientation: "vertical"
    padding: [6, 6]
    Label:
        id: panel_label
        text: root.panel_text
        size_hint_y: None
        height: self.texture_size[1] + dp(10)
    Button:
        text: "Close"
        size_hint_y: None
        height: dp(30)
        on_press: root.parent.remove_widget(root)

<InputBubble@BoxLayout>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(44)
    Label:
        id: lb
        text: root.label_text
        size_hint_x: .4
    TextInput:
        id: ti
        multiline: False
        size_hint_x: .5
    Button:
        text: "OK"
        size_hint_x: .1
        on_press: root.on_submit(ti.text)
'''

class NiblitDashboardRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_command_selected(self, cmd_key, cmd_type):
        if cmd_type == "status":
            self.ids.chat_panel.add_system_message(f"Status: All systems operational (demo)")
        elif cmd_type == "panel":
            # Expand a panel in sidebar
            panel = ExpandedPanel(panel_text="Memory: 48 facts stored\n(Details...)")
            self.ids.sidebar.ids.panel_box.add_widget(panel)
        elif cmd_type == "input":
            # Show parameter bubble under sidebar
            input_bub = InputBubble(label_text="Topic:", on_submit=self._handle_learn_topic)
            self.ids.sidebar.ids.panel_box.add_widget(input_bub)
        elif cmd_type == "file":
            self.show_file_picker()
        elif cmd_type == "search":
            self.ids.search_panel.height = dp(64)
            self.ids.search_panel.opacity = 1
        # Add more types as you wish...

    def _handle_learn_topic(self, topic):
        self.ids.chat_panel.add_user_message(f"Learn about: {topic}")
        self.ids.sidebar.ids.panel_box.clear_widgets()

    def show_file_picker(self):
        modal = FilePickerModal(on_submit=self._handle_file_selected)
        modal.open()

    def _handle_file_selected(self, path):
        self.ids.chat_panel.add_system_message(f"File selected: {path}")

class FilePickerModal(ModalView):
    current_path = StringProperty(os.getcwd())
    on_submit = ObjectProperty(lambda *a: None)

    def on_select(self, selection):
        if selection:
            self.on_submit(selection[0])
            self.dismiss()

class InputBubble(BoxLayout):
    label_text = StringProperty("Input:")
    on_submit = ObjectProperty(lambda *a: None)
    def __init__(self, label_text="Input:", on_submit=None, **kwargs):
        super().__init__(**kwargs)
        self.label_text = label_text
        if on_submit is not None:
            self.on_submit = on_submit

class ExpandedPanel(BoxLayout):
    panel_text = StringProperty("")
    def __init__(self, panel_text="", **kwargs):
        super().__init__(**kwargs)
        self.panel_text = panel_text

class ChatPanel(BoxLayout):
    chat_history = ListProperty([])
    input_hint = StringProperty("Ask Niblit...")

    @property
    def chat_history_str(self):
        return "\n".join(self.chat_history)

    def send_chat(self, text):
        if not text.strip():
            return
        self.add_user_message(text)
        # Demo routing: echo back result
        self.add_system_message(f"Niblit: (demo reply to '{text}')")
        self.ids.chat_input.text = ""

    def show_commands(self):
        # Example: open sidebar or show hint
        pass
    def add_user_message(self, text):
        self.chat_history.append(f"You: {text}")

    def add_system_message(self, text):
        self.chat_history.append(text)

class SideBarPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(self._build, 0.1)

    def _build(self, *a):
        pb = self.ids.panel_box
        pb.clear_widgets()
        for cmd in COMMANDS:
            btn = Button(
                text=cmd["title"],
                size_hint_y=None,
                height=dp(44),
                on_release=lambda b, c=cmd: self.dispatch('on_command_selected', c["key"], c["type"])
            )
            pb.add_widget(btn)

    def on_command_selected(self, key, cmd_type):
        pass  # Dispatched for root to handle

class SearchPanel(BoxLayout):
    have_search = ObjectProperty(None)
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.have_search = self

    def do_search(self, query):
        provider = self.ids.search_provider.text
        # Route to correct backend; for demo just print
        App.get_running_app().root.ids.chat_panel.add_system_message(
            f"Search '{query}' via {provider} (demo)")
        self.hide_search()

    def hide_search(self):
        self.height = 0
        self.opacity = 0

class NiblitKivyApp(App):
    search_providers = ListProperty(SEARCH_PROVIDERS)
    def build(self):
        Builder.load_string(KV)
        # Permissions demo: on start, request storage permission
        if PLYER_OK:
            Clock.schedule_once(self.request_permissions, 0.5)
        return NiblitDashboardRoot()

    def request_permissions(self, *a):
        if PLYER_OK:
            permissions.request_permissions(['android.permission.READ_EXTERNAL_STORAGE'])

if __name__ == "__main__":
    NiblitKivyApp().run()
