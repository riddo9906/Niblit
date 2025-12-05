# niblit_core.py
import os
import sys
import json
import time
from datetime import datetime

# --- Ensure modules folder is on sys.path ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_PATH = os.path.join(BASE_DIR, "modules")
if MODULES_PATH not in sys.path:
    sys.path.insert(0, MODULES_PATH)

# --- Import modules ---
from modules.self_researcher import SelfResearcher
from modules.storage import KnowledgeDB
from modules.llm_adapter import LLMAdapter
from modules.analytics import AnalyticsModule
from modules.antifraud import AntiFraudModule
from modules.idea_generator import IdeaGenerator
from modules.reflect import ReflectModule
from niblit_net import fetch_data, learn_from_data
from modules.self_healer import SelfHealer
from modules.self_teacher import SelfTeacher
from modules.self_maintenance import SelfMaintenance
from modules.counter_active_membrane import CounterActiveMembrane
from modules.self_idea_implementation import SelfIdeaImplementation
from modules.slsa_generator import SLSAGenerator
from modules.control_panel import ControlPanel
from modules.device_manager import DeviceManager
from modules.bios import BIOS
from modules.firmware import Firmware
from modules.bootloader import Bootloader
from modules.filesystem_manager import FileSystemManager
from modules.terminal_tools import TerminalTools
from modules.permission_manager import PermissionManager

# --- Memory & Logs ---
MEMORY_FILE = os.path.join(BASE_DIR, "niblit_memory.json")
CHAT_LOG_DIR = os.path.join(BASE_DIR, "chat_logs")
os.makedirs(CHAT_LOG_DIR, exist_ok=True)

def now_ts():
    return int(time.time())

def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class NiblitCore:
    def __init__(self, memory_path=MEMORY_FILE):
        self.db = KnowledgeDB(memory_path)
        self.personality = self.db.get_personality()

        # --- External LLM toggle ---
        self.llm_enabled = True

        # --- Initialize modules ---
        self.llm = LLMAdapter(self.db)
        self.analytics = AnalyticsModule(self.db)
        self.antifraud = AntiFraudModule(self.db)
        self.idea_gen = IdeaGenerator(self.db)
        self.reflect = ReflectModule(self.db)

        self.self_healer = SelfHealer(self.db)
        self.self_teacher = SelfTeacher(self.db)
        self.self_maintenance = SelfMaintenance(self.db)
        self.cam = CounterActiveMembrane(self.db)
        self.self_idea_impl = SelfIdeaImplementation(self.db)
        self.slsa_gen = SLSAGenerator(self.db)
        self.control_panel = ControlPanel(self.db, {})
        self.device_manager = DeviceManager()
        self.bios = BIOS()
        self.firmware = Firmware()
        self.bootloader = Bootloader()
        self.fs_manager = FileSystemManager()
        self.terminal_tools = TerminalTools()
        self.perms = PermissionManager()

        # --- Modules registry ---
        self.modules = {
            'analytics': self.analytics,
            'antifraud': self.antifraud,
            'ideas': self.idea_gen,
            'reflect': self.reflect,
            'llm': self.llm,
            'self_healer': self.self_healer,
            'self_teacher': self.self_teacher,
            'self_maintenance': self.self_maintenance,
            'cam': self.cam,
            'self_idea_impl': self.self_idea_impl,
            'slsa': self.slsa_gen,
            'control_panel': self.control_panel,
            'device_manager': self.device_manager,
            'bios': self.bios,
            'firmware': self.firmware,
            'bootloader': self.bootloader,
            'fs_manager': self.fs_manager,
            'terminal_tools': self.terminal_tools,
            'perms': self.perms
        }

        # --- SelfResearcher gets full module registry ---
        self.self_researcher = SelfResearcher(self.db, self.modules)

        # Reload last chat context
        self.context = self.db.recent_interactions(50)

    # --- Chat Logging ---
    def log_chat(self, role, message):
        date_file = os.path.join(CHAT_LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
        with open(date_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp()}] {role.upper()}: {message}\n")
        self.db.add_interaction(role, message)

    # --- Handle input ---
    def handle(self, text: str):
        text = text.strip()
        self.log_chat("user", text)
        low = text.lower()
        response = None

        # --- Help ---
        if 'help' in low:
            response = self.help_text()

        # --- Toggle LLM command ---
        elif low.startswith("toggle-llm"):
            parts = low.split()
            if len(parts) == 2 and parts[1] in ("on", "off"):
                response = self.toggle_llm(parts[1] == "on")
            else:
                response = "[TOGGLE ERROR] Usage: toggle-llm on/off"

        # --- Self-Research Commands ---
        elif low.startswith("self-research"):
            parts = text.split(" ", 2)

            # Natural query (self-research <query>)
            if len(parts) == 2:
                query = parts[1]
                response = self.self_researcher.handle_command("web.run", query)

            # Explicit command + argument
            elif len(parts) >= 3:
                cmd = parts[1]
                arg = parts[2]
                response = self.self_researcher.handle_command(cmd, arg)

            else:
                response = "[RESEARCH ERROR] Usage: self-research <cmd> <arg> or self-research <natural query>"

        # --- LLM ---
        elif self.llm_enabled and self.llm.is_available():
            try:
                response = self.llm.query(text, context=self.db.recent_interactions(20))
            except Exception as e:
                response = f"I heard you say: \"{text}\" (LLM error: {e})"

        else:
            # fallback / raw data mode
            response = f"[RAW DATA MODE] You said: \"{text}\""

        self.log_chat("assistant", response)
        return response

    # --- Toggle LLM ---
    def toggle_llm(self, on: bool):
        self.llm_enabled = on
        return f"LLM {'enabled' if on else 'disabled'}"

    # --- Help text ---
    def help_text(self):
        return (
            "Commands:\n"
            "  learn about <topic>\n"
            "  !remember key: value\n"
            "  !forget key\n"
            "  !memory\n"
            "  analyze <query>\n"
            "  ideas about <topic>\n"
            "  reflect\n"
            "  evolve\n"
            "  status\n"
            "  self-heal\n"
            "  self-teach\n"
            "  self-maintenance\n"
            "  self-idea-impl\n"
            "  self-research <cmd> <arg>\n"
            "  self-research <natural query>\n"
            "  toggle-llm on/off\n"
            "  device-info\n"
            "  read-file <path>\n"
            "  write-file <path> <text>\n"
        )

    # --- Save memory ---
    def save_all(self):
        self.db._save()
