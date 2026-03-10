#!/usr/bin/env python3
"""
niblit_core.py — NiblitCore: Unified Autonomous AI Runtime

Integrates all Niblit modules into a single orchestrated core.
Compatible with main.py and server.py.
"""

# ============================================================
# STDLIB IMPORTS
# ============================================================
import os
import sys
import time
import threading
import logging
from datetime import datetime, timezone

# ============================================================
# PATH SETUP
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ============================================================
# LOGGING SETUP
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)
log = logging.getLogger("NiblitCore")

# ============================================================
# GLOBAL FLAGS & COMMAND LIST
# ============================================================
DEBUG_MODE = True
COMMANDS = [
    "help", "status", "memory", "search", "summary",
    "learn about", "self-heal", "self-teach", "self-research",
    "debug on", "debug off", "threads"
]

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def safe_call(fn, *a, **kw):
    """Call fn(*a, **kw) safely, logging and returning an error string on failure."""
    try:
        return fn(*a, **kw)
    except Exception:
        log.exception(f"safe_call failed for {fn}")
        name = getattr(fn, "__name__", "unknown")
        return f"[ERROR::{name}]"


def parse_intent(text: str):
    """Parse a user command string into (intent, meta) tuple."""
    t = text.strip().lower()
    if t in ("help", "?"):
        return "help", {}
    if t in ("time", "what time is it", "current time"):
        return "time", {}
    if t in ("status", "health"):
        return "status", {}
    if t.startswith("remember "):
        rest = text[9:].strip()
        if ":" in rest:
            k, v = rest.split(":", 1)
            return "remember", {"key": k.strip(), "value": v.strip()}
    if t.startswith("learn about ") or t.startswith("learn "):
        topic = text.split(" ", 2)[-1].strip()
        return "learn", {"topic": topic}
    if t.startswith("ideas about ") or t.startswith("ideas "):
        topic = text.split(" ", 1)[-1].strip()
        return "ideas", {"topic": topic}
    if t in ("toggle-llm on", "llm on"):
        return "toggle_llm", {"state": "on"}
    if t in ("toggle-llm off", "llm off"):
        return "toggle_llm", {"state": "off"}
    if t in ("shutdown", "exit", "quit"):
        return "shutdown", {}
    return "chat", {"text": text}

# ============================================================
# SAFE IMPORT SYSTEM (modules/ sub-package)
# ============================================================

class _FallbackDB:
    """Minimal no-op stub used when KnowledgeDB is unavailable."""
    def __getattr__(self, name):
        return lambda *a, **kw: None

# ============================
# CORE MODULE IMPORTS
# ============================
try:
    from modules.knowledge_db import KnowledgeDB
except Exception as _e:
    log.warning(f"KnowledgeDB failed to import: {_e}")
    KnowledgeDB = None

try:
    from modules.intent_parser import parse_intent
except Exception as _e:
    log.warning(f"parse_intent failed to import: {_e}")
    def parse_intent(text):
        return "unknown", {}

try:
    from niblit_brain import NiblitBrain
except Exception as _e:
    log.warning(f"NiblitBrain failed to import: {_e}")
    NiblitBrain = None

try:
    from collector_full import Collector
except Exception as _e:
    log.warning(f"Collector failed to import: {_e}")
    Collector = None

try:
    from trainer_full import Trainer
except Exception as _e:
    log.warning(f"Trainer failed to import: {_e}")
    Trainer = None

try:
    from modules.slsa_manager import slsa_manager
except Exception as _e:
    log.warning(f"slsa_manager failed to import: {_e}")
    slsa_manager = None

try:
    from modules.db import LocalDB
except Exception as _e:
    log.warning(f"LocalDB failed to import: {_e}")
    LocalDB = None

# ============================
# ORCHESTRATOR IMPORTS
# ============================
ORCHESTRATOR_AVAILABLE = False
RepoAuditor = None
self_heal_main = None
FixGuideGenerator = None

try:
    from tools.repo_audit import RepoAuditor
    from tools.self_heal_auto import main as self_heal_main
    from tools.FixGuideGenerator import FixGuideGenerator
    ORCHESTRATOR_AVAILABLE = True
    log.info("Orchestrator components loaded successfully")
except Exception as _e:
    log.warning(f"Orchestrator components not available: {_e}")

# hf_query — imported from niblit_brain; falls back to None if unavailable
try:
    from niblit_brain import hf_query
except ImportError as _e:
    log.warning(f"hf_query failed to import: {_e}")
    hf_query = None

# ============================
# ORPHANED MODULE IMPORTS
# ============================
try:
    from niblit_actions import NiblitActions
except Exception as _e:
    log.warning(f"NiblitActions failed to import: {_e}")
    NiblitActions = None

try:
    from niblit_env import NiblitEnv
except Exception as _e:
    log.warning(f"NiblitEnv failed to import: {_e}")
    NiblitEnv = None

try:
    from niblit_guard import NiblitGuard
except Exception as _e:
    log.warning(f"NiblitGuard failed to import: {_e}")
    NiblitGuard = None

try:
    from niblit_hf import NiblitHF
except Exception as _e:
    log.warning(f"NiblitHF failed to import: {_e}")
    NiblitHF = None

try:
    from niblit_identity import NiblitIdentity
except Exception as _e:
    log.warning(f"NiblitIdentity failed to import: {_e}")
    NiblitIdentity = None

try:
    from niblit_learning import NiblitLearning
except Exception as _e:
    log.warning(f"NiblitLearning failed to import: {_e}")
    NiblitLearning = None

try:
    from niblit_manager import NiblitManager
except Exception as _e:
    log.warning(f"NiblitManager failed to import: {_e}")
    NiblitManager = None

try:
    from niblit_net import fetch_data, learn_from_data
except Exception as _e:
    log.warning(f"niblit_net failed to import: {_e}")
    fetch_data = None
    learn_from_data = None

try:
    from niblit_network_full import NiblitNetwork
except Exception as _e:
    log.warning(f"NiblitNetwork failed to import: {_e}")
    NiblitNetwork = None

try:
    from lifecycle_engine import LifecycleEngine
except Exception as _e:
    log.warning(f"LifecycleEngine failed to import: {_e}")
    LifecycleEngine = None

try:
    from module_loader import load_modules
except Exception as _e:
    log.warning(f"module_loader failed to import: {_e}")
    load_modules = None

try:
    from generator_full import Generator
except Exception as _e:
    log.warning(f"Generator failed to import: {_e}")
    Generator = None

try:
    from healer_full import Healer
except Exception as _e:
    log.warning(f"Healer failed to import: {_e}")
    Healer = None

try:
    from membrane_full import Membrane
except Exception as _e:
    log.warning(f"Membrane failed to import: {_e}")
    Membrane = None

# ============================
# SAFE IMPORT SYSTEM
# ============================

def safe_import(name, default=None):
    try:
        mod = __import__(f"modules.{name}", fromlist=[name])
        cls = "".join(x.capitalize() for x in name.split("_"))
        return getattr(mod, cls, default)
    except Exception as e:
        log.warning(f"Module {name} failed to load: {e}")
        return default

class Stub:
    def __init__(self, *a, **k):
        pass

SelfResearcher    = safe_import("self_researcher", Stub)
LLMAdapter        = safe_import("llm_adapter", Stub)
SelfHealer        = safe_import("self_healer", Stub)
SelfTeacher       = safe_import("self_teacher", Stub)
Reflect           = safe_import("reflect", Stub)
SelfImplementer   = safe_import("self_implementer", Stub)
SelfIdeaGenerator = safe_import("self_idea_generator", Stub)

try:
    from modules import internet_manager
except Exception as _e:
    log.warning(f"internet_manager failed to import: {_e}")
    internet_manager = None

# ============================================================
# INTELLIGENCE LAYER IMPORTS
# ============================================================

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

if NiblitRouter is None:
    try:
        from niblit_router import safe_call, NiblitRouter
    except Exception as _e:
        log.warning(f"NiblitRouter failed to import: {_e}")
        NiblitRouter = None

if safe_call is None:
    def safe_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            log.exception(f"safe_call failed for {fn}")
            name = getattr(fn, "__name__", "unknown")
            return f"[ERROR::{name}]"

try:
    from collector_full import Collector
except Exception as _e:
    log.warning(f"Collector not available: {_e}")
    Collector = None

try:
    from trainer_full import Trainer
except Exception as _e:
    log.warning(f"Trainer not available: {_e}")
    Trainer = None

try:
    from niblit_tasks import NiblitTasks
except Exception as _e:
    log.warning(f"NiblitTasks not available: {_e}")
    NiblitTasks = None

# ============================================================
# SYSTEM SERVICE IMPORTS (all optional)
# ============================================================

try:
    from niblit_sensors_full import NiblitSensors
except Exception as _e:
    log.warning(f"NiblitSensors not available: {_e}")
    NiblitSensors = None

try:
    from niblit_voice_full import NiblitVoice
except Exception as _e:
    log.warning(f"NiblitVoice not available: {_e}")
    NiblitVoice = None

try:
    from niblit_network_full import NiblitNetwork
except Exception as _e:
    log.warning(f"NiblitNetwork not available: {_e}")
    NiblitNetwork = None

try:
    from niblit_env import NiblitEnv
except Exception as _e:
    log.warning(f"NiblitEnv not available: {_e}")
    NiblitEnv = None

try:
    from niblit_identity import NiblitIdentity
except Exception as _e:
    log.warning(f"NiblitIdentity not available: {_e}")
    NiblitIdentity = None

try:
    from niblit_guard import NiblitGuard
except Exception as _e:
    log.warning(f"NiblitGuard not available: {_e}")
    NiblitGuard = None

try:
    from niblit_actions import NiblitActions
except Exception as _e:
    log.warning(f"NiblitActions not available: {_e}")
    NiblitActions = None

try:
    from niblit_hf import NiblitHF
except Exception as _e:
    log.warning(f"NiblitHF not available: {_e}")
    NiblitHF = None

try:
    from niblit_manager import NiblitManager
except Exception as _e:
    log.warning(f"NiblitManager not available: {_e}")
    NiblitManager = None

try:
    from niblit_learning import NiblitLearning
except Exception as _e:
    log.warning(f"NiblitLearning not available: {_e}")
    NiblitLearning = None

try:
    from slsa_generator_full import SLSAGenerator
    from modules.slsa_manager import slsa_manager
except Exception as _e:
    log.warning(f"SLSA modules not available: {_e}")
    SLSAGenerator = None
    slsa_manager = None

try:
    from healer_full import Healer
except Exception as _e:
    log.warning(f"Healer not available: {_e}")
    Healer = None

try:
    from membrane_full import Membrane
except Exception as _e:
    log.warning(f"Membrane not available: {_e}")
    Membrane = None

try:
    from generator_full import Generator
except Exception as _e:
    log.warning(f"Generator not available: {_e}")
    Generator = None

try:
    from self_maintenance_full import SelfMaintenance
except Exception as _e:
    log.warning(f"SelfMaintenance not available: {_e}")
    SelfMaintenance = None

try:
    from lifecycle_engine import LifecycleEngine
except Exception as _e:
    log.warning(f"LifecycleEngine not available: {_e}")
    LifecycleEngine = None

# ============================================================
# ORCHESTRATOR AVAILABILITY CHECK
# ============================================================
ORCHESTRATOR_AVAILABLE = False
try:
    from niblit_orchestrator import (
        run_audit,
        run_self_heal,
        generate_fix_guide,
        execute_fix_guide,
        verify_imports,
        hf_task_example,
    )
    ORCHESTRATOR_AVAILABLE = True
    log.info("Orchestrator components loaded successfully")
except Exception as _e:
    log.warning(f"Orchestrator components not available: {_e}")

# ============================================================
# CORE
# ============================================================

class NiblitCore:

    def __init__(self, memory_path=None):

        log.info("Booting TRUE Autonomous Niblit...")
        self.start_ts = time.time()
        if KnowledgeDB:
            self.db = KnowledgeDB(memory_path) if memory_path else KnowledgeDB()
        else:
            log.warning("KnowledgeDB unavailable; using no-op fallback db")
            self.db = _FallbackDB()
        # Expose db as memory for compatibility with app.py and other modules
        self.memory = self.db
        self._routing = False
        self.orchestrator_available = ORCHESTRATOR_AVAILABLE
        self._orchestration_running = False

        # MODULE LOAD
        self.reflect = safe_call(Reflect, self.db)
        self.self_healer = safe_call(SelfHealer, self.db)
        self.llm = safe_call(LLMAdapter, self.db)
        self.trainer = Trainer(self.db) if Trainer else None
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

        self.collector = (
            Collector(
                db=self.db,
                trainer=self.trainer,
                self_teacher=self.self_teacher
            )
            if Collector else None
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
        if NiblitBrain:
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
        else:
            self.brain = None

        # ROUTER
        if NiblitRouter:
            self.router = NiblitRouter(self, self.db, self)
            self.router.start()
        else:
            self.router = None

        # SYSTEM SERVICES (all optional)
        self.sensors = NiblitSensors() if NiblitSensors else None
        self.voice = NiblitVoice() if NiblitVoice else None
        self.network = NiblitNetwork() if NiblitNetwork else None
        self.env = NiblitEnv() if NiblitEnv else None
        self.identity = NiblitIdentity() if NiblitIdentity else None
        self.guard = NiblitGuard() if NiblitGuard else None
        self.actions = NiblitActions() if NiblitActions else None
        self.healer = Healer() if Healer else None
        self.membrane = Membrane() if Membrane else None
        self.generator = Generator() if Generator else None
        self.self_maintenance = SelfMaintenance() if SelfMaintenance else None

        # NiblitHF — shares MemoryManager singleton
        try:
            self.niblit_hf = NiblitHF() if NiblitHF else None
        except Exception as _e:
            log.warning(f"NiblitHF init failed: {_e}")
            self.niblit_hf = None

        # NiblitLearning
        self.learning = NiblitLearning(self.db) if NiblitLearning else None

        # NiblitTasks
        self.tasks = (
            NiblitTasks(brain=self.brain, memory=self.db)
            if NiblitTasks else None
        )
        if self.tasks:
            self.tasks.start()

        # Lifecycle Engine (optional, heavy)
        self.lifecycle = None
        if LifecycleEngine:
            try:
                self.lifecycle = LifecycleEngine()
                self.lifecycle.start()
            except Exception as _e:
                log.warning(f"LifecycleEngine start failed: {_e}")
                self.lifecycle = None

        # SELF IDEA GENERATOR
        self.idea_generator = safe_call(SelfIdeaGenerator, db=self.db, collector=self.collector)
        if self.idea_generator:
            threading.Thread(target=self.idea_generator.autonomous_loop, daemon=True).start()

        # AUTONOMOUS THREADS
        threading.Thread(target=self._health_loop, daemon=True).start()
        threading.Thread(target=self._trainer_loop, daemon=True).start()
        threading.Thread(target=self._auto_research_loop, daemon=True).start()
        threading.Thread(target=self._self_heal_loop, daemon=True).start()

        if self.orchestrator_available:
            log.info("Orchestrator components available")
        else:
            log.warning("Orchestrator components not available")

        log.info("TRUE AUTONOMOUS NIBLIT READY")

    # ============================
    # ORCHESTRATOR METHODS
    # ============================

    def _run_audit(self):
        """Run repository audit via orchestrator"""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Running audit...")
            run_audit()
            log.info("[ORCHESTRATOR] Audit completed")
            return "[Audit completed]"
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Audit failed: {e}")
            return f"[Audit failed: {e}]"

    def _run_self_heal_orchestrated(self):
        """Run self-heal via orchestrator"""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Running self-heal...")
            run_self_heal()
            log.info("[ORCHESTRATOR] Self-heal completed")
            return "[Self-heal completed]"
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Self-heal failed: {e}")
            return f"[Self-heal failed: {e}]"

    def _generate_fix_guide(self):
        """Generate fix guide via orchestrator"""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Generating fix guide...")
            guide = generate_fix_guide()
            execute_fix_guide(guide)
            log.info("[ORCHESTRATOR] Fix guide generated")
            return "[Fix guide generated]"
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Fix guide generation failed: {e}")
            return f"[Fix guide failed: {e}]"

    def _verify_imports_orchestrated(self):
        """Verify module imports via orchestrator"""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Verifying imports...")
            modules_to_check = [
                "modules.analytics",
                "modules.bios",
                "modules.control_panel",
                "modules.counter_active_membrane",
                "modules.db",
                "modules.device_manager",
                "modules.evolve",
                "modules.firmware",
                "modules.hf_adapter",
                "modules.idea_generator",
                "modules.internet_manager",
                "modules.llm_adapter",
                "modules.llm_module",
                "modules.local_llm_adapter",
                "modules.market_researcher",
                "modules.orphan_imports",
                "modules.permission_manager",
                "modules.reflect",
                "modules.self_healer",
                "modules.self_idea_implementation",
                "modules.self_maintenance",
                "modules.self_researcher",
                "modules.self_teacher",
                "modules.slsa_generator",
                "modules.storage",
                "modules.terminal_tools"
            ]
            success = 0
            fail = 0
            failed_modules = []
            for mod in modules_to_check:
                try:
                    __import__(mod)
                    log.info(f"[IMPORT] SUCCESS: {mod}")
                    success += 1
                except Exception as e:
                    log.warning(f"[IMPORT] FAILED: {mod}: {e}")
                    failed_modules.append(f"{mod}: {e}")
                    fail += 1
            result = f"Verification completed: {success} success, {fail} failed."
            if failed_modules:
                result += f"\nFailed: {', '.join(failed_modules)}"
            log.info(f"[ORCHESTRATOR] {result}")
            return result
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Import verification failed: {e}")
            return f"[Import verification failed: {e}]"

    def _run_orchestration_pipeline(self):
        """Run full orchestration pipeline"""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator not available]"
            if self._orchestration_running:
                return "[Orchestration already running]"

            self._orchestration_running = True
            log.info("[ORCHESTRATOR] Pipeline started")

            results = []
            results.append("=== ORCHESTRATION PIPELINE ===")
            results.append(self._run_audit())
            results.append(self._run_self_heal_orchestrated())
            results.append(self._generate_fix_guide())
            results.append(self._verify_imports_orchestrated())

            log.info("[ORCHESTRATOR] Pipeline completed")
            self._orchestration_running = False

            return "\n".join(results)
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Pipeline failed: {e}")
            self._orchestration_running = False
            return f"[Pipeline failed: {e}]"

    def _hf_task(self, prompt):
        """Execute HF task via orchestrator"""
        try:
            if not ORCHESTRATOR_AVAILABLE:
                return "[Orchestrator/HF not available]"
            log.info(f"[HF TASK] Executing: {prompt}")
            response = hf_task_example(prompt)
            log.info(f"[HF TASK] Response received")
            return str(response) if response else "[No response]"
        except Exception as e:
            log.error(f"[HF TASK] Failed: {e}")
            return f"[HF task failed: {e}]"

    def _trigger_learning(self, user_input: str, response: str):
        """Invoke NiblitLearning on each conversation turn, queue follow-up tasks."""
        if self.learning:
            try:
                self.learning.process_interaction(user_input, response)
            except Exception as _e:
                log.warning(f"NiblitLearning.process_interaction failed: {_e}")
        if self.tasks:
            try:
                self.tasks.add_task("remember", {"input": user_input, "response": response})
            except Exception as _e:
                log.warning(f"NiblitTasks.add_task failed: {_e}")

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
                if self.collector:
                    self.collector.flush_if_needed()
                if self.trainer:
                    safe_call(self.trainer.train_cycle)
            except Exception:
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
            return slsa_manager.status() if slsa_manager else "[SLSA unavailable]"

        if ltext.startswith("self-research"):
            parts = text.split(" ", 1)
            topic = parts[1] if len(parts) > 1 else "general"
            if self.researcher and hasattr(self.researcher, "search"):
                if self.internet:
                    self.researcher.internet = self.internet
                return safe_call(self.researcher.search, topic) or "[Research failed]"

        # ============================
        # ORCHESTRATOR COMMANDS
        # ============================

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
                status_msg = f"Memory: {len(self.db.recent_interactions(500))}"
                if self.orchestrator_available:
                    status_msg += " | Orchestrator: Available"
                else:
                    status_msg += " | Orchestrator: Unavailable"
                return status_msg
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
            if not slsa_manager:
                return "[SLSA not available]"
            parts = text.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.start(topics) if slsa_manager else "[SLSA unavailable]"
        if ltext.startswith("stop_slsa"):
            return slsa_manager.stop() if slsa_manager else "[SLSA unavailable]"
        if ltext.startswith("restart_slsa"):
            if not slsa_manager:
                return "[SLSA not available]"
            parts = text.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.restart(topics) if slsa_manager else "[SLSA unavailable]"

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
                self._trigger_learning(text, r)
                return r

        response = None
        if self.llm_enabled and self.hf:
            response = safe_call(self.hf.ask_single, text)

        if not response and self.llm_enabled:
            response = safe_call(self.llm.query, text)

        if not response and self.brain:
            response = self.brain.think(text)

        if not response:
            response = f"I hear you: {text}"

        self._trigger_learning(text, response)
        return response

    # ============================
    # HELP & SHUTDOWN
    # ============================

    def help_text(self):
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

    def shutdown(self):
        log.info("Shutdown started")
        self.running = False
        if self.tasks:
            try:
                self.tasks.stop()
            except Exception:
                pass
        if self.lifecycle:
            try:
                self.lifecycle.stop()
            except Exception:
                pass
        if self.network:
            try:
                self.network.shutdown()
            except Exception:
                pass
        if hasattr(self, "db") and self.db:
            try:
                self.db.shutdown()
            except Exception:
                pass
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
