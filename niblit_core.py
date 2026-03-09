# niblit_core.py — Unified NiblitCore
# Single class, all 40+ components wired with graceful degradation.
# Compatible with main.py, server.py, and app.py entry points.

# ============================
# STDLIB IMPORTS
# ============================
import os
import sys
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

# ============================
# DIRECTORY SETUP
# ============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

# ============================
# LOGGING
# ============================
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("NiblitCore")

# ============================
# UTILITIES
# ============================

def safe_call(fn, *a, **kw):
    """Call fn(*a, **kw) and return None on any exception."""
    try:
        return fn(*a, **kw)
    except Exception as e:
        log.debug(f"safe_call failed for {fn}: {e}")
        return None


def parse_intent(text: str) -> Tuple[str, Dict[str, str]]:
    """Simple keyword-based intent parser. Returns (intent, meta)."""
    t = text.strip().lower()
    if t.startswith("remember "):
        payload = t[len("remember "):].strip()
        if ":" in payload:
            k, v = payload.split(":", 1)
            return "remember", {"key": k.strip(), "value": v.strip()}
        return "bad_remember", {}
    if t in ("time", "what time is it", "current time"):
        return "time", {}
    if "weather" in t:
        return "weather", {}
    if t in ("help", "commands"):
        return "help", {}
    if t in ("status", "health"):
        return "status", {}
    if t in ("shutdown", "exit", "quit"):
        return "shutdown", {}
    if t.startswith("learn about "):
        return "learn", {"topic": t[len("learn about "):].strip()}
    if t.startswith("learn "):
        return "learn", {"topic": t[len("learn "):].strip()}
    if t.startswith("ideas about "):
        return "ideas", {"topic": t[len("ideas about "):].strip()}
    if t.startswith("toggle-llm "):
        state = t[len("toggle-llm "):].strip()
        return "toggle_llm", {"state": state}
    return "chat", {}


# ============================
# SAFE IMPORT HELPER (modules/)
# ============================

class Stub:
    """Placeholder for optional modules that are unavailable."""
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


def safe_import(name, default=None):
    """Import a class from the modules/ package, returning default on failure."""
    try:
        mod = __import__(f"modules.{name}", fromlist=[name])
        cls = "".join(x.capitalize() for x in name.split("_"))
        return getattr(mod, cls, mod)
    except Exception as e:
        log.debug(f"Module {name} not available: {e}")
        return default


# ============================
# CORE DATABASE
# ============================
try:
    from modules.knowledge_db import KnowledgeDB
except Exception as _e:
    log.warning(f"KnowledgeDB not available: {_e}")
    KnowledgeDB = None

try:
    from modules.db import LocalDB
except Exception as _e:
    log.debug(f"LocalDB not available: {_e}")
    LocalDB = None

# ============================
# MEMORY
# ============================
try:
    from niblit_memory import MemoryManager
except Exception as _e:
    log.warning(f"MemoryManager not available: {_e}")
    MemoryManager = None

# ============================
# INTELLIGENCE LAYER
# ============================
try:
    from niblit_brain import NiblitBrain
except Exception as _e:
    log.warning(f"NiblitBrain not available: {_e}")
    NiblitBrain = None

try:
    from niblit_router import NiblitRouter
except Exception as _e:
    log.warning(f"NiblitRouter not available: {_e}")
    NiblitRouter = None

try:
    from trainer_full import Trainer
except Exception as _e:
    log.warning(f"Trainer not available: {_e}")
    Trainer = Stub

try:
    from collector_full import Collector
except Exception as _e:
    log.warning(f"Collector not available: {_e}")
    Collector = Stub

# ============================
# TASK & LIFECYCLE MANAGEMENT
# ============================
try:
    from niblit_tasks import NiblitTasks
except Exception as _e:
    log.debug(f"NiblitTasks not available: {_e}")
    NiblitTasks = None

try:
    from lifecycle_engine import LifecycleEngine
except Exception as _e:
    log.debug(f"LifecycleEngine not available: {_e}")
    LifecycleEngine = None

try:
    from slsa_generator_full import SLSAGenerator
except Exception as _e:
    log.debug(f"SLSAGenerator not available: {_e}")
    SLSAGenerator = None

# ============================
# SYSTEM SERVICES
# ============================
try:
    from niblit_sensors_full import NiblitSensors
except Exception as _e:
    log.debug(f"NiblitSensors not available: {_e}")
    NiblitSensors = None

try:
    from niblit_voice_full import NiblitVoice
except Exception as _e:
    log.debug(f"NiblitVoice not available: {_e}")
    NiblitVoice = None

try:
    from niblit_network_full import NiblitNetwork
except Exception as _e:
    log.debug(f"NiblitNetwork not available: {_e}")
    NiblitNetwork = None

try:
    from niblit_hf import NiblitHF
except Exception as _e:
    log.debug(f"NiblitHF not available: {_e}")
    NiblitHF = None

try:
    from niblit_env import NiblitEnv
except Exception as _e:
    log.debug(f"NiblitEnv not available: {_e}")
    NiblitEnv = None

try:
    from niblit_manager import NiblitManager
except Exception as _e:
    log.debug(f"NiblitManager not available: {_e}")
    NiblitManager = None

try:
    from niblit_actions import NiblitActions
except Exception as _e:
    log.debug(f"NiblitActions not available: {_e}")
    NiblitActions = None

try:
    from niblit_guard import NiblitGuard
except Exception as _e:
    log.debug(f"NiblitGuard not available: {_e}")
    NiblitGuard = None

try:
    from niblit_identity import NiblitIdentity
except Exception as _e:
    log.debug(f"NiblitIdentity not available: {_e}")
    NiblitIdentity = None

try:
    from niblit_learning import NiblitLearning
except Exception as _e:
    log.debug(f"NiblitLearning not available: {_e}")
    NiblitLearning = None

try:
    from niblit_io import NiblitIO
except Exception as _e:
    log.debug(f"NiblitIO not available: {_e}")
    NiblitIO = None

# ============================
# OPTIONAL COMPONENTS
# ============================
try:
    from membrane_full import Membrane
except Exception as _e:
    log.debug(f"Membrane not available: {_e}")
    Membrane = None

try:
    from healer_full import Healer
except Exception as _e:
    log.debug(f"Healer not available: {_e}")
    Healer = None

try:
    from generator_full import Generator
except Exception as _e:
    log.debug(f"Generator not available: {_e}")
    Generator = None

try:
    from self_maintenance_full import SelfMaintenance
except Exception as _e:
    log.debug(f"SelfMaintenance not available: {_e}")
    SelfMaintenance = None

try:
    from module_loader import load_modules
except Exception as _e:
    log.debug(f"module_loader not available: {_e}")
    load_modules = None

try:
    from niblit_net import fetch_data, learn_from_data
except Exception as _e:
    log.debug(f"niblit_net not available: {_e}")
    fetch_data = None
    learn_from_data = None

# ============================
# INTERNET & SLSA
# ============================
try:
    from modules.internet_manager import InternetManager
except Exception as _e:
    log.debug(f"InternetManager not available: {_e}")
    InternetManager = None

try:
    from modules.slsa_manager import slsa_manager
except Exception as _e:
    log.warning(f"slsa_manager not available: {_e}")
    slsa_manager = None

# ============================
# SELF MODULES (via safe_import from modules/)
# ============================
SelfResearcher    = safe_import("self_researcher", Stub)
LLMAdapter        = safe_import("llm_adapter", Stub)
SelfHealer_mod    = safe_import("self_healer", Stub)
SelfTeacher_mod   = safe_import("self_teacher", Stub)
Reflect_mod       = safe_import("reflect", Stub)
SelfImplementer   = safe_import("self_implementer", Stub)
SelfIdeaGenerator = safe_import("self_idea_generator", Stub)

# ============================
# TOOLS / ORCHESTRATION
# ============================
ORCHESTRATOR_AVAILABLE = False
RepoAuditor       = None
self_heal_main    = None
FixGuideGenerator = None

try:
    from tools.repo_audit import RepoAuditor
    from tools.self_heal_auto import main as self_heal_main
    from tools.FixGuideGenerator import FixGuideGenerator
    ORCHESTRATOR_AVAILABLE = True
    log.info("Orchestrator tools loaded successfully")
except Exception as _e:
    log.debug(f"Orchestrator tools not available: {_e}")


def hf_query(prompt: str) -> str:
    """Execute a HuggingFace model query via HFBrain if available."""
    try:
        from modules.hf_brain import HFBrain
        hf = HFBrain()
        return hf.ask_single(prompt) or "[No response]"
    except Exception as e:
        log.debug(f"hf_query failed: {e}")
        return f"[HF query failed: {e}]"


# ============================
# CORE
# ============================

class NiblitCore:

    def __init__(self, memory_path=None):

        log.info("Booting TRUE Autonomous Niblit...")
        self.start_ts = time.time()
        self._lock = threading.Lock()

        # ── Database (KnowledgeDB preferred, LocalDB fallback) ──
        if KnowledgeDB:
            self.db = KnowledgeDB(memory_path) if memory_path else KnowledgeDB()
        elif LocalDB:
            self.db = LocalDB(memory_path) if memory_path else LocalDB()
        else:
            self.db = None
            log.warning("No database available — running without persistence")

        self._routing = False
        self.orchestrator_available = ORCHESTRATOR_AVAILABLE
        self._orchestration_running = False
        self.llm_enabled = True
        self.running = True

        # ── Environment & Identity ──
        self.env = safe_call(NiblitEnv) if NiblitEnv else None
        self.identity = safe_call(NiblitIdentity) if NiblitIdentity else None
        if self.identity:
            safe_call(self.identity.verify)

        # ── System Services ──
        self.guard = safe_call(NiblitGuard) if NiblitGuard else None
        self.network = safe_call(NiblitNetwork) if NiblitNetwork else None
        self.sensors = safe_call(NiblitSensors) if NiblitSensors else None
        self.voice = safe_call(NiblitVoice) if NiblitVoice else None
        self.membrane = safe_call(Membrane) if Membrane else None
        self.healer_obj = safe_call(Healer) if Healer else None
        self.generator = safe_call(Generator) if Generator else None
        self.self_maintenance = safe_call(SelfMaintenance) if SelfMaintenance else None
        self.manager = safe_call(NiblitManager) if NiblitManager else None
        self.actions = safe_call(NiblitActions) if NiblitActions else None

        # ── Internet ──
        try:
            self.internet = InternetManager(db=self.db) if InternetManager else None
            if self.internet:
                def quick_summary(query):
                    results = self.internet.search(query, max_results=1)
                    if results and isinstance(results, list):
                        r = results[0]
                        return r.get("text", str(r)) if isinstance(r, dict) else str(r)
                    return "[No info found]"
                self.internet.quick_summary = quick_summary
                log.info("InternetManager loaded successfully.")
        except Exception as e:
            log.warning(f"InternetManager failed: {e}")
            self.internet = None

        # ── Self Modules ──
        self.reflect = safe_call(Reflect_mod, self.db)
        self.self_healer = safe_call(SelfHealer_mod, self.db)
        self.llm = safe_call(LLMAdapter, self.db)
        self.trainer = safe_call(Trainer, self.db)
        self.self_teacher = safe_call(
            SelfTeacher_mod,
            db=self.db,
            researcher=None,
            reflector=self.reflect
        )
        self.self_implementer = safe_call(SelfImplementer, db=self.db, core=self)

        # ── Collector ──
        self.collector = safe_call(
            Collector,
            db=self.db,
            trainer=self.trainer,
            self_teacher=self.self_teacher
        )

        self.modules = {
            "llm": self.llm,
            "reflect": self.reflect,
            "implementer": self.self_implementer
        }

        # ── SelfResearcher ──
        self.researcher = safe_call(SelfResearcher, self.db, self.modules)
        if self.researcher and self.internet:
            self.researcher.internet = self.internet
        if self.self_teacher:
            self.self_teacher.researcher = self.researcher

        # ── HFBrain (from modules) ──
        try:
            from modules.hf_brain import HFBrain
            self.hf = HFBrain(db=self.db)
        except Exception:
            self.hf = None

        # ── NiblitBrain ──
        try:
            self.brain = NiblitBrain(self.db, llm_enabled=True, internet=self.internet) if NiblitBrain else None
            if self.brain:
                if hasattr(self.brain, "self_teacher"):
                    self.self_teacher = self.brain.self_teacher
                if self.collector:
                    self.collector.self_teacher = self.self_teacher
                if hasattr(self.brain, "self_implementer"):
                    self.brain.self_implementer = self.self_implementer
        except Exception as e:
            log.warning(f"NiblitBrain failed: {e}")
            self.brain = None

        # ── NiblitHF (standalone HF module) ──
        self.niblit_hf = safe_call(NiblitHF) if NiblitHF else None

        # ── NiblitLearning ──
        self.learning = safe_call(NiblitLearning, self.db) if NiblitLearning else None

        # ── Router ──
        if NiblitRouter:
            try:
                self.router = NiblitRouter(self, self.db, self)
                self.router.start()
            except Exception as e:
                log.warning(f"NiblitRouter failed: {e}")
                self.router = None
        else:
            self.router = None

        # ── NiblitTasks ──
        if NiblitTasks and self.brain and self.db:
            try:
                self.tasks = NiblitTasks(self.brain, self.db)
                self.tasks.start()
            except Exception as e:
                log.warning(f"NiblitTasks failed: {e}")
                self.tasks = None
        else:
            self.tasks = None

        # ── SLSA Manager ──
        self.slsa_manager = slsa_manager

        # ── SelfIdeaGenerator ──
        self.idea_generator = safe_call(SelfIdeaGenerator, db=self.db, collector=self.collector)
        if self.idea_generator and hasattr(self.idea_generator, "autonomous_loop"):
            threading.Thread(target=self.idea_generator.autonomous_loop, daemon=True).start()

        # ── Lifecycle Engine ──
        self.lifecycle = None
        if LifecycleEngine:
            try:
                self.lifecycle = LifecycleEngine()
            except Exception as e:
                log.debug(f"LifecycleEngine failed to start: {e}")

        # ── Dynamic Module Loader ──
        if load_modules:
            try:
                load_modules()
            except Exception as e:
                log.debug(f"load_modules failed: {e}")

        # ── AUTONOMOUS BACKGROUND THREADS ──
        threading.Thread(target=self._health_loop, daemon=True).start()
        threading.Thread(target=self._trainer_loop, daemon=True).start()
        threading.Thread(target=self._auto_research_loop, daemon=True).start()
        threading.Thread(target=self._self_heal_loop, daemon=True).start()

        if self.orchestrator_available:
            log.info("Orchestrator components available")
        else:
            log.debug("Orchestrator components not available")

        log.info("TRUE AUTONOMOUS NIBLIT READY")

    # ============================
    # ORCHESTRATOR METHODS
    # ============================

    def _run_audit(self) -> str:
        """Run repository audit via orchestrator tools."""
        try:
            if not ORCHESTRATOR_AVAILABLE or not RepoAuditor:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Running audit...")
            auditor = RepoAuditor(BASE_DIR)
            report = auditor.run_audit()
            log.info("[ORCHESTRATOR] Audit completed")
            return str(report) if report else "[Audit completed]"
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Audit failed: {e}")
            return f"[Audit failed: {e}]"

    def _run_self_heal_orchestrated(self) -> str:
        """Run self-heal via orchestrator tools."""
        try:
            if not ORCHESTRATOR_AVAILABLE or not self_heal_main:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Running self-heal...")
            self_heal_main()
            log.info("[ORCHESTRATOR] Self-heal completed")
            return "[Self-heal completed]"
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Self-heal failed: {e}")
            return f"[Self-heal failed: {e}]"

    def _generate_fix_guide(self) -> str:
        """Generate fix guide via orchestrator tools."""
        try:
            if not ORCHESTRATOR_AVAILABLE or not FixGuideGenerator:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Generating fix guide...")
            db = (LocalDB() if LocalDB else None) or self.db
            fg = FixGuideGenerator(db)
            fix_guide_path = os.path.join(BASE_DIR, "Fix_Guide.txt")
            msg = fg.generate_fix_guide(fix_guide_path)
            log.info(f"[ORCHESTRATOR] Fix guide generated: {fix_guide_path}")
            return msg
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Fix guide generation failed: {e}")
            return f"[Fix guide failed: {e}]"

    def _verify_imports_orchestrated(self) -> str:
        """Verify module imports via orchestrator."""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Verifying imports...")
            modules_to_check = [
                "modules.analytics", "modules.bios", "modules.control_panel",
                "modules.counter_active_membrane", "modules.db",
                "modules.device_manager", "modules.evolve", "modules.firmware",
                "modules.hf_adapter", "modules.idea_generator",
                "modules.internet_manager", "modules.llm_adapter",
                "modules.llm_module", "modules.local_llm_adapter",
                "modules.market_researcher", "modules.orphan_imports",
                "modules.permission_manager", "modules.reflect",
                "modules.self_healer", "modules.self_idea_implementation",
                "modules.self_maintenance", "modules.self_researcher",
                "modules.self_teacher", "modules.slsa_generator",
                "modules.storage", "modules.terminal_tools",
            ]
            success = 0
            fail = 0
            failed_modules = []
            for mod in modules_to_check:
                try:
                    __import__(mod)
                    success += 1
                except Exception as e:
                    failed_modules.append(f"{mod}: {e}")
                    fail += 1
            result = f"Verification completed: {success} success, {fail} failed."
            if failed_modules:
                result += f"\nFailed: {', '.join(failed_modules[:5])}"
            log.info(f"[ORCHESTRATOR] {result}")
            return result
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Import verification failed: {e}")
            return f"[Import verification failed: {e}]"

    def _run_orchestration_pipeline(self) -> str:
        """Run full orchestration pipeline (audit -> self-heal -> fix-guide -> verify)."""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            if self._orchestration_running:
                return "[Orchestration already running]"
            self._orchestration_running = True
            log.info("[ORCHESTRATOR] Pipeline started")
            results = [
                "=== ORCHESTRATION PIPELINE ===",
                self._run_audit(),
                self._run_self_heal_orchestrated(),
                self._generate_fix_guide(),
                self._verify_imports_orchestrated(),
            ]
            log.info("[ORCHESTRATOR] Pipeline completed")
            self._orchestration_running = False
            return "\n".join(results)
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Pipeline failed: {e}")
            self._orchestration_running = False
            return f"[Pipeline failed: {e}]"

    def _hf_task(self, prompt: str) -> str:
        """Execute a HuggingFace task."""
        try:
            log.info(f"[HF TASK] Executing: {prompt}")
            response = hf_query(prompt)
            log.info("[HF TASK] Response received")
            return str(response) if response else "[No response]"
        except Exception as e:
            log.error(f"[HF TASK] Failed: {e}")
            return f"[HF task failed: {e}]"

    # ============================
    # BACKGROUND LOOPS
    # ============================

    def _health_loop(self):
        last = -1
        while self.running:
            uptime = int(time.time() - self.start_ts)
            if uptime // 120 != last:
                last = uptime // 120
                try:
                    if self.db:
                        if hasattr(self.db, "get_learning_log"):
                            mem = len(self.db.get_learning_log())
                        elif hasattr(self.db, "recent_interactions"):
                            mem = len(self.db.recent_interactions(50))
                        else:
                            mem = 0
                    else:
                        mem = 0
                except Exception:
                    mem = 0
                log.info(f"[HEALTH] uptime={uptime}s mem={mem}")
            time.sleep(5)

    def _trainer_loop(self):
        while self.running:
            try:
                if self.collector and hasattr(self.collector, "flush_if_needed"):
                    safe_call(self.collector.flush_if_needed)
                if self.trainer:
                    if hasattr(self.trainer, "train_cycle"):
                        safe_call(self.trainer.train_cycle)
                    elif hasattr(self.trainer, "step_if_needed"):
                        buf = getattr(self.collector, "buffer", []) if self.collector else []
                        safe_call(self.trainer.step_if_needed, buf)
            except Exception:
                pass
            time.sleep(90)

    def _auto_research_loop(self):
        while self.running:
            try:
                if self.db and hasattr(self.db, "get_learning_log") and self.researcher:
                    queued = self.db.get_learning_log()
                    for item in queued[-5:]:
                        topic = item.get("topic") if isinstance(item, dict) else None
                        if topic:
                            log.info(f"[AUTO RESEARCH] {topic}")
                            if self.internet:
                                self.researcher.internet = self.internet
                            if hasattr(self.researcher, "search"):
                                result = safe_call(self.researcher.search, topic)
                                if result and self.db and hasattr(self.db, "add_fact"):
                                    try:
                                        self.db.add_fact(
                                            f"auto_research:{topic}",
                                            str(result),
                                            tags=["research", "auto"]
                                        )
                                    except Exception:
                                        pass
            except Exception:
                pass
            time.sleep(150)

    def _self_heal_loop(self):
        while self.running:
            try:
                if self.self_healer:
                    if hasattr(self.self_healer, "run_cycle"):
                        safe_call(self.self_healer.run_cycle)
                    elif hasattr(self.self_healer, "repair"):
                        safe_call(self.self_healer.repair)
                    elif hasattr(self.self_healer, "full_heal"):
                        safe_call(self.self_healer.full_heal, self)
            except Exception:
                pass
            time.sleep(300)

    # ============================
    # MAIN COMMAND HANDLER
    # ============================

    def handle(self, text: str) -> str:
        ltext = text.lower().strip()

        # Brain handles self-* and reflect commands
        if self.brain:
            if (ltext.startswith("reflect") or
                    ltext.startswith("auto-reflect") or
                    ltext.startswith("self-idea") or
                    ltext.startswith("self-implement")):
                if hasattr(self.brain, "handle"):
                    return self.brain.handle(text)
                return self.brain.think(text)

        # SLSA manager commands
        if ltext.startswith("slsa-status"):
            return self.slsa_manager.status() if self.slsa_manager else "[SLSA not available]"

        if ltext.startswith("self-research"):
            parts = text.split(" ", 1)
            topic = parts[1] if len(parts) > 1 else "general"
            if self.researcher and hasattr(self.researcher, "search"):
                if self.internet:
                    self.researcher.internet = self.internet
                return safe_call(self.researcher.search, topic) or "[Research failed]"

        # ── Orchestrator Commands ──
        if ltext.startswith("orchestrate audit"):
            return self._run_audit()
        if ltext.startswith("orchestrate self-heal"):
            return self._run_self_heal_orchestrated()
        if ltext.startswith("orchestrate fix-guide"):
            return self._generate_fix_guide()
        if ltext.startswith("orchestrate verify"):
            return self._verify_imports_orchestrated()
        if ltext.startswith("orchestrate pipeline"):
            return self._run_orchestration_pipeline()
        if ltext.startswith("hf-task "):
            task_prompt = text[8:].strip()
            return self._hf_task(task_prompt)

        intent, meta = parse_intent(text)

        if intent == "help":
            return self.help_text()
        if intent == "time":
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        if intent == "status":
            try:
                mem_count = 0
                if self.db:
                    if hasattr(self.db, "recent_interactions"):
                        mem_count = len(self.db.recent_interactions(500))
                    elif hasattr(self.db, "get_learning_log"):
                        mem_count = len(self.db.get_learning_log())
                status_msg = f"Memory: {mem_count}"
                status_msg += " | Orchestrator: " + ("Available" if self.orchestrator_available else "Unavailable")
                return status_msg
            except Exception:
                return "Memory: 0"
        if intent == "remember":
            if self.db and hasattr(self.db, "add_fact"):
                safe_call(self.db.add_fact, meta["key"], meta["value"])
            return "Saved."
        if intent == "learn":
            if self.db and hasattr(self.db, "queue_learning"):
                safe_call(self.db.queue_learning, meta.get("topic"))
            return "Queued for autonomous research."
        if intent == "toggle_llm":
            self.llm_enabled = str(meta.get("state")).lower() in ("on", "true", "1")
            return f"LLM {'enabled' if self.llm_enabled else 'disabled'}"
        if intent == "ideas":
            topic = meta.get("topic", "")
            return f"Ideas for {topic}: Prototype -> Test -> Evolve"

        if ltext.startswith("summary ") and self.internet:
            return self.internet.quick_summary(text[8:].strip())
        if ltext.startswith("search ") and self.internet:
            r = self.internet.search(text[7:])
            if isinstance(r, list):
                return "\n".join(str(x) for x in r) if r else "[No results]"
            return str(r) if r else "[No results]"

        if ltext.startswith("start_slsa") and self.slsa_manager:
            parts = text.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return self.slsa_manager.start(topics)
        if ltext.startswith("stop_slsa") and self.slsa_manager:
            return self.slsa_manager.stop()
        if ltext.startswith("restart_slsa") and self.slsa_manager:
            parts = text.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return self.slsa_manager.restart(topics)

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

        if self.llm_enabled and self.llm:
            r = safe_call(self.llm.query, text)
            if r:
                return r

        if self.brain:
            return self.brain.think(text)

        return f"I hear you: {text}"

    # ============================
    # HELP & STATUS
    # ============================

    def help_text(self) -> str:
        base_help = (
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
        if self.orchestrator_available:
            orchestrator_help = (
                "\n\n--- ORCHESTRATOR COMMANDS ---\n"
                "orchestrate audit\n"
                "orchestrate self-heal\n"
                "orchestrate fix-guide\n"
                "orchestrate verify\n"
                "orchestrate pipeline\n"
                "hf-task <prompt>"
            )
            return base_help + orchestrator_help
        return base_help

    # ============================
    # SHUTDOWN
    # ============================

    def shutdown(self):
        log.info("Shutdown started")
        self.running = False
        if self.tasks:
            try:
                self.tasks.stop()
            except Exception:
                pass
        if self.db and hasattr(self.db, "shutdown"):
            try:
                self.db.shutdown()
            except Exception:
                pass
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
