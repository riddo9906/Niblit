# niblit_core.py
from dotenv import load_dotenv
load_dotenv()

import sys, os, time, logging
from datetime import datetime

log = logging.getLogger("NiblitCore")
logging.basicConfig(level=logging.INFO)

# Safe import helper
def safe_import(name):
    try:
        return __import__(name)
    except Exception as e:
        log.error(f"[Import] Failed to load {name}: {e}")
        return None

# Ensure modules/ folder in path
modules_path = os.path.join(os.path.dirname(__file__), "modules")
if modules_path not in sys.path:
    sys.path.insert(0, modules_path)

# Load runtime pieces
memory_mod = safe_import("niblit_memory") or safe_import("modules.storage")
MemoryManager = getattr(memory_mod, "MemoryManager", None) or getattr(memory_mod, "KnowledgeDB", None)
llm_adapter_module = safe_import("modules.llm_adapter") or safe_import("llm_adapter")
hf_adapter_module  = safe_import("modules.hf_adapter") or safe_import("hf_adapter")
self_researcher_module = safe_import("modules.self_researcher") or safe_import("self_researcher")
market_researcher_module = safe_import("modules.market_researcher") or safe_import("market_researcher")

def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class NiblitCore:
    def __init__(self):
        log.info("[Init] NiblitCore starting...")
        # Memory manager (wraps DB)
        if MemoryManager:
            try:
                # prefer parameterless constructor if available
                self.memory = MemoryManager()
            except Exception:
                # fallback: try KnowledgeDB from modules.storage
                try:
                    from modules.storage import KnowledgeDB
                    self.memory = KnowledgeDB()
                except Exception:
                    self.memory = None
        else:
            self.memory = None

        self.start_ts = time.time()
        self.running  = True

        # Adapters - pass DB where required
        try:
            self.llm_adapter = llm_adapter_module.LLMAdapter(self.memory) if llm_adapter_module else None
        except Exception as e:
            log.error(f"[Init] LLMAdapter init failed: {e}")
            self.llm_adapter = None

        try:
            self.hf_adapter  = hf_adapter_module.HFAdapter(self.memory)  if hf_adapter_module else None
        except Exception as e:
            log.error(f"[Init] HFAdapter init failed: {e}")
            self.hf_adapter = None

        # research modules
        try:
            self.researcher = self_researcher_module.SelfResearcher(self.memory, getattr(self.memory, "runtime_registry", {}) ) if self_researcher_module else None
        except Exception as e:
            log.error(f"[Init] Researcher init failed: {e}")
            self.researcher = None

        try:
            self.market = market_researcher_module.MarketResearcher(self.memory) if market_researcher_module else None
        except Exception as e:
            log.error(f"[Init] Market init failed: {e}")
            self.market = None

        # LLM toggle
        self.llm_enabled = True

    # try adapters in order: local LLM adapter -> HF adapter
    def attempt_adapters(self, user_text, tone=None):
        context = None
        if self.memory and hasattr(self.memory, "show_all"):
            try:
                context = self.memory.show_all()
            except Exception:
                context = None

        # 1) Local LLM adapter (wraps provider; respects provider.is_online)
        if self.llm_adapter and getattr(self.llm_adapter, "is_available", lambda: False)():
            try:
                resp = self.llm_adapter.query(user_text, context=context)
                if resp:
                    if self.memory and hasattr(self.memory, "add_entry"):
                        try:
                            self.memory.add_entry(user_text, resp)
                        except Exception:
                            pass
                    return resp
            except Exception as e:
                log.error(f"[Adapter] LLMAdapter failed: {e}")

        # 2) HF adapter (router) as fallback
        if self.hf_adapter and getattr(self.hf_adapter, "is_online", lambda: False)():
            try:
                resp = self.hf_adapter.query(user_text, context=context)
                if resp:
                    if self.memory and hasattr(self.memory, "add_entry"):
                        try:
                            self.memory.add_entry(user_text, resp)
                        except Exception:
                            pass
                    return resp
            except Exception as e:
                log.error(f"[Adapter] HFAdapter failed: {e}")

        return None

    # Main handle entry (text command or chat)
    def handle(self, text: str):
        text = (text or "").strip()
        if not text:
            return "..."

        # quick local logging
        try:
            if self.memory and hasattr(self.memory, "add_entry"):
                # We store user utterance as a lightweight entry; implementations may vary.
                self.memory.add_entry("USER", text)
        except Exception:
            pass

        low = text.lower()
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""

        # Quick help
        if text.strip() == "?" or text.strip().lower() == "help":
            return self.help_text()

        # Toggle LLM (on/off)
        if low.startswith("toggle-llm"):
            p = low.split()
            if len(p) == 2 and p[1] in ("on", "off"):
                self.llm_enabled = (p[1] == "on")
                return f"LLM {'enabled' if self.llm_enabled else 'disabled'}"
            else:
                return "[TOGGLE ERROR] Usage: toggle-llm on/off"

        # show memory
        if text.lower() == "show memory":
            if not self.memory or not hasattr(self.memory, "show_all"):
                return "[Memory Missing]"
            try:
                entries = self.memory.show_all()
                if not entries:
                    return "[Memory Empty]"
                return "\n".join([f"{i+1}. {e.get('user','?')} -> {e.get('reply','?')}" for i,e in enumerate(entries)])
            except Exception:
                return "[Memory Error]"

        # self-research commands
        if cmd in ("self-research", "research", "study", "web", "search"):
            if self.researcher:
                # researcher.handle_command expects (cmd, arg) or natural query
                # Use "web.run" mapping inside researcher for natural queries
                try:
                    if cmd in ("self-research", "research") and arg:
                        # pass natural query
                        return self.researcher.handle_command("web.run", arg)
                    else:
                        return self.researcher.handle_command(cmd, arg)
                except Exception as e:
                    log.error(f"[Research] error: {e}")
                    return f"[Research Error] {e}"
            else:
                return "[Researcher Missing]"

        # market commands
        if cmd in ("market", "finance", "economy", "trends"):
            if self.market:
                try:
                    if arg:
                        return self.market.summary(arg)
                    else:
                        return self.market.summary("stocks")
                except Exception as e:
                    log.error(f"[Market] error: {e}")
                    return f"[Market Error] {e}"
            else:
                return "[Market Researcher Missing]"

        # device info / utilities routing (if memory runtime registry present)
        if cmd in ("device-info", "device", "status"):
            try:
                registry = getattr(self.memory, "runtime_registry", {}) if self.memory else {}
                device = registry.get("device_manager")
                control = registry.get("control_panel")
                if device and hasattr(device, "info"):
                    return str(device.info())
                if control and hasattr(control, "status"):
                    return str(control.status())
            except Exception:
                pass

        # If LLMs disabled or adapters failed => raw fallback
        if not self.llm_enabled:
            return f"[RAW DATA MODE] You said: \"{text}\""

        # Try adapters (local -> HF)
        adapter_resp = self.attempt_adapters(text)
        if adapter_resp:
            return adapter_resp

        # final fallback
        fallback = f"[FALLBACK] I heard: {text}"
        try:
            if self.memory and hasattr(self.memory, "add_entry"):
                self.memory.add_entry("FALLBACK", fallback)
        except Exception:
            pass
        return fallback

    def help_text(self):
        return (
            "Commands:\n"
            "  ? or help - quick help\n"
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
            "  market <topic>\n"
            "  toggle-llm on/off\n"
            "  device-info\n"
            "  read-file <path>\n"
            "  write-file <path> <text>\n"
        )

    def save_all(self):
        try:
            if self.memory and hasattr(self.memory, "autosave"):
                self.memory.autosave()
            elif self.memory and hasattr(self.memory, "_save"):
                self.memory._save()
        except Exception:
            pass

    def shutdown(self):
        log.info("[Shutdown] Saving memory...")
        self.save_all()
        self.running = False
        log.info("[Shutdown] Done.")

if __name__ == "__main__":
    core = NiblitCore()
    print("[Selftest] NiblitCore interactive mode. Type '?' for help.")
    try:
        while core.running:
            cmd = input("You: ").strip()
            if cmd.lower() in ("exit","quit","shutdown"):
                core.shutdown()
                break
            print("Niblit:", core.handle(cmd))
    except KeyboardInterrupt:
        core.shutdown()
