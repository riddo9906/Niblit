#!/usr/bin/env python3
import modules.orphan_imports
import os, sys, time, threading, logging, random
from datetime import datetime
from collector_full import Collector
from trainer_full import Trainer
from modules.intent_parser import parse_intent
from modules.knowledge_db import KnowledgeDB
from modules.safe_loader import safe_call
from niblit_brain import NiblitBrain
from modules.slsa_manager import slsa_manager
from modules.evolve import engine as evolve_engine

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s')
log = logging.getLogger("NiblitCore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_PATH = os.path.join(BASE_DIR, "modules")
if MODULES_PATH not in sys.path:
    sys.path.insert(0, MODULES_PATH)

# ============================
# SAFE IMPORT SYSTEM
# ============================

def safe_import(name, default=None):
    try:
        mod = __import__(f"modules.{name}", fromlist=[name])
        cls = "".join(x.capitalize() for x in name.split("_"))
        return getattr(mod, cls, mod)
    except Exception as e:
        log.warning(f"Module {name} failed to load: {e}")
        return default

class Stub:
    def __init__(self, *a, **k): pass

SelfResearcher  = safe_import("self_researcher", Stub)
LLMAdapter      = safe_import("llm_adapter", Stub)
SelfHealer      = safe_import("self_healer", Stub)
SelfTeacher     = safe_import("self_teacher", Stub)
Reflect         = safe_import("reflect", Stub)
SelfImplementer = safe_import("self_implementer", Stub)
SelfIdeaGenerator = safe_import("self_idea_generator", Stub)

try:
    from modules import internet_manager
except:
    internet_manager = None

try:
    from niblit_router import NiblitRouter
except:
    NiblitRouter = None

# ============================
# CORE
# ============================

class NiblitCore:

    def __init__(self, memory_path=None):

        log.info("Booting TRUE Autonomous Niblit...")
        self.start_ts = time.time()
        self.db = KnowledgeDB(memory_path) if memory_path else KnowledgeDB()
        self._routing = False

        # MODULE LOAD
        self.reflect = safe_call(Reflect, self.db)
        self.self_healer = safe_call(SelfHealer, self.db)
        self.llm = safe_call(LLMAdapter, self.db)
        self.trainer = Trainer(self.db)
        self.self_teacher = safe_call(
            SelfTeacher,
            db=self.db,
            researcher=None,
            reflector=self.reflect
        )
        self.self_implementer = safe_call(
            SelfImplementer,
            db=self.db,
            core=self
        )

        self.collector = Collector(
            db=self.db,
            trainer=self.trainer,
            self_teacher=self.self_teacher
        )

        self.modules = {
            "llm": self.llm,
            "reflect": self.reflect,
            "implementer": self.self_implementer
        }

        # INTERNET
        try:
            self.internet = internet_manager.InternetManager(db=self.db) if internet_manager else None
            if self.internet:
                def quick_summary(query):
                    results = self.internet.search(query, max_results=1)
                    return results[0] if results else "[No info found]"
                self.internet.quick_summary = quick_summary
                log.info("InternetManager loaded successfully.")
        except:
            self.internet = None

        # SELF RESEARCHER
        self.researcher = safe_call(SelfResearcher, self.db, self.modules)
        if self.researcher and self.internet:
            self.researcher.internet = self.internet
            log.info("Injected InternetManager into SelfResearcher.")
        if self.self_teacher:
            self.self_teacher.researcher = self.researcher

        # HF BRAIN
        try:
            from modules.hf_brain import HFBrain
            self.hf = HFBrain(db=self.db)
        except:
            self.hf = None

        self.llm_enabled = True
        self.running = True

        # NIBLIT BRAIN
        try:
            self.brain = NiblitBrain(self.db, llm_enabled=True, internet=self.internet)
            if self.brain and hasattr(self.brain, "self_teacher"):
                self.self_teacher = self.brain.self_teacher
            if self.collector:
                self.collector.self_teacher = self.self_teacher
            if self.brain and hasattr(self.brain, "self_implementer"):
                self.brain.self_implementer = self.self_implementer
        except Exception as e:
            log.warning(f"NiblitBrain failed: {e}")
            self.brain = None

        # ROUTER
        if NiblitRouter:
            self.router = NiblitRouter(self, self.db, self)
            self.router.start()
        else:
            self.router = None

        # SELF IDEA GENERATOR
        self.idea_generator = safe_call(SelfIdeaGenerator, db=self.db, collector=self.collector)
        if self.idea_generator:
            threading.Thread(target=self.idea_generator.autonomous_loop, daemon=True).start()

        # AUTONOMOUS THREADS
        threading.Thread(target=self._health_loop, daemon=True).start()
        threading.Thread(target=self._trainer_loop, daemon=True).start()
        threading.Thread(target=self._auto_research_loop, daemon=True).start()
        threading.Thread(target=self._self_heal_loop, daemon=True).start()
        log.info("TRUE AUTONOMOUS NIBLIT READY")

    # ============================
    # LOOPS
    # ============================

    def _health_loop(self):
        last = -1
        while self.running:
            uptime = int(time.time() - self.start_ts)
            if uptime // 120 != last:
                last = uptime // 120
                try:
                    mem = len(self.db.recent_interactions(50))
                except:
                    mem = 0
                log.info(f"[HEALTH] uptime={uptime}s mem={mem}")
            time.sleep(5)

    def _trainer_loop(self):
        while self.running:
            try:
                self.collector.flush_if_needed()
                safe_call(self.trainer.train_cycle)
            except:
                pass
            time.sleep(90)

    def _auto_research_loop(self):
        while self.running:
            try:
                queued = self.db.get_learning_queue()
                if queued and self.researcher:
                    for item in queued:
                        topic = item.get("topic") if isinstance(item, dict) else item
                        if topic:
                            log.info(f"[AUTO RESEARCH] {topic}")
                            if self.internet:
                                self.researcher.internet = self.internet
                            if hasattr(self.researcher, "search"):
                                result = safe_call(self.researcher.search, topic)
                                if result:
                                    try:
                                        self.db.add_fact(
                                            f"auto_research:{topic}",
                                            str(result),
                                            tags=["research", "auto"]
                                        )
                                    except:
                                        pass
            except:
                pass
            time.sleep(150)

    def _self_heal_loop(self):
        while self.running:
            try:
                if hasattr(self.self_healer, "run_cycle"):
                    safe_call(self.self_healer.run_cycle)
                elif hasattr(self.self_healer, "repair"):
                    safe_call(self.self_healer.repair)
                elif hasattr(self.self_healer, "full_heal"):
                    safe_call(self.self_healer.full_heal, self)
            except:
                pass
            time.sleep(300)

    # ============================
    # HANDLE
    # ============================

    def handle(self, text: str) -> str:
        ltext = text.lower().strip()

        if self.brain:
            if (ltext.startswith("reflect") or
                ltext.startswith("auto-reflect") or
                ltext.startswith("self-idea") or
                ltext.startswith("self-implement")):
                if hasattr(self.brain, "handle"):
                    return self.brain.handle(text)
                return self.brain.think(text)

        if ltext.startswith("slsa-status"):
            return slsa_manager.status()

        if ltext.startswith("self-research"):
            parts = text.split(" ", 1)
            topic = parts[1] if len(parts) > 1 else "general"
            if self.researcher and hasattr(self.researcher, "search"):
                if self.internet:
                    self.researcher.internet = self.internet
                return safe_call(self.researcher.search, topic) or "[Research failed]"

        intent, meta = parse_intent(text)

        if intent == "help":
            return self.help_text()
        if intent == "time":
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        if intent == "status":
            try:
                return f"Memory: {len(self.db.recent_interactions(500))}"
            except:
                return "Memory: 0"
        if intent == "remember":
            self.db.add_fact(meta["key"], meta["value"])
            return "Saved."
        if intent == "learn":
            self.db.queue_learning(meta.get("topic"))
            return "Queued for autonomous research."
        if intent == "toggle_llm":
            self.llm_enabled = str(meta.get("state")).lower() == "on"
            return f"LLM {'enabled' if self.llm_enabled else 'disabled'}"
        if intent == "ideas":
            topic = meta.get("topic", "")
            return f"Ideas for {topic}: Prototype → Test → Evolve"

        if ltext.startswith("summary ") and self.internet:
            return self.internet.quick_summary(text[8:].strip())
        if ltext.startswith("search ") and self.internet:
            r = self.internet.search(text[7:])
            return "\n".join(r) if r else "[No results]"

        if ltext.startswith("start_slsa"):
            parts = text.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.start(topics)
        if ltext.startswith("stop_slsa"):
            return slsa_manager.stop()
        if ltext.startswith("restart_slsa"):
            parts = text.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.restart(topics)

        if intent == "shutdown":
            threading.Thread(target=self.shutdown, daemon=True).start()
            return "Shutdown scheduled."

        if self.router and not self._routing:
            try:
                self._routing = True
                r = self.router.process(text)
            finally:
                self._routing = False
            if r and r.strip() != text:
                return r

        if self.llm_enabled and self.hf:
            r = safe_call(self.hf.ask_single, text)
            if r:
                return r

        if self.llm_enabled:
            r = safe_call(self.llm.query, text)
            if r:
                return r

        if self.brain:
            return self.brain.think(text)

        return f"I hear you: {text}"

    # ============================
    # HELP & SHUTDOWN
    # ============================

    def help_text(self):
        return (
            "help\n"
            "time\n"
            "status\n"
            "remember key:value\n"
            "learn about <topic>\n"
            "ideas about <topic>\n"
            "search <query>\n"
            "summary <query>\n"
            "self-research <topic>\n"
            "reflect <topic>\n"
            "self-idea <topic>\n"
            "self-implement <topic>\n"
            "slsa-status\n"
            "start_slsa [topic1,topic2,...]\n"
            "stop_slsa\n"
            "restart_slsa [topic1,topic2,...]\n"
            "toggle-llm on/off\n"
            "shutdown"
        )

    def shutdown(self):
        log.info("Shutdown started")
        self.running = False
        time.sleep(1)
        log.info("Shutdown complete")

# ============================
if __name__ == "__main__":
    core = NiblitCore()
    print("TRUE Autonomous Niblit running.")
    try:
        while core.running:
            cmd = input("Niblit > ").strip()
            print(core.handle(cmd))
    except KeyboardInterrupt:
        core.shutdown()
