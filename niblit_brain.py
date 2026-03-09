#!/usr/bin/env python3
"""
NIBLIT BRAIN MODULE
Handles thinking, learning, HFBrain integration, self modules, and router compatibility
"""

import sys
import os
import datetime
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

log = logging.getLogger("NiblitBrain")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)

# ───────── Local Modules ─────────
try:
    from modules.db import LocalDB
except Exception as _e:
    log.warning(f"LocalDB unavailable: {_e}")
    LocalDB = None

try:
    from modules.hf_brain import HFBrain
except Exception as _e:
    log.warning(f"HFBrain unavailable: {_e}")
    HFBrain = None

try:
    from modules.self_researcher import SelfResearcher
except Exception as _e:
    log.warning(f"SelfResearcher unavailable: {_e}")
    SelfResearcher = None

try:
    from modules.self_healer import SelfHealer
except Exception as _e:
    log.warning(f"SelfHealer unavailable: {_e}")
    SelfHealer = None

try:
    from modules.self_idea_implementation import SelfIdeaImplementation
except Exception as _e:
    log.warning(f"SelfIdeaImplementation unavailable: {_e}")
    SelfIdeaImplementation = None

try:
    from modules.reflect import ReflectModule
except Exception as _e:
    log.warning(f"ReflectModule unavailable: {_e}")
    ReflectModule = None

try:
    from modules.self_teacher import SelfTeacher
except Exception as _e:
    log.warning(f"SelfTeacher unavailable: {_e}")
    SelfTeacher = None

try:
    from modules.internet_manager import InternetManager
except Exception as _e:
    log.warning(f"InternetManager unavailable: {_e}")
    InternetManager = None

# ───────── Memory Adapter ─────────
class _DBMemoryAdapter:
    def __init__(self, memory, db_path="niblit.db"):
        self._memory = memory
        self._db = LocalDB(db_path) if LocalDB else None

    def __getattr__(self, name):
        return getattr(self._memory, name)

    def store_learning(self, entry):
        if hasattr(self._memory, "store_learning"):
            return self._memory.store_learning(entry)
        if self._db:
            self._db.add_entry("learning", entry)

    def recall(self, query, limit=5):
        if hasattr(self._memory, "recall"):
            return self._memory.recall(query, limit)
        if not self._db:
            return []
        results = []
        for item in reversed(self._db.get_log()):
            val = str(item.get("value", ""))
            if query.lower() in val.lower():
                results.append(item)
            if len(results) >= limit:
                break
        return results

    def get_preferences(self):
        if hasattr(self._memory, "get_preferences"):
            return self._memory.get_preferences()
        return {}

    def store_preferences(self, prefs):
        if hasattr(self._memory, "store_preferences"):
            return self._memory.store_preferences(prefs)

# ───────── NiblitBrain ─────────
class NiblitBrain:
    def __init__(self, memory, llm_enabled=True, internet=None):
        self.memory = memory
        self.llm_enabled = llm_enabled

        # Wrap memory if LocalDB exists
        if LocalDB and memory is not None:
            try:
                self.memory = _DBMemoryAdapter(memory)
            except Exception as e:
                log.warning(f"DB adapter attach failed: {e}")

        # Preferences
        try:
            prefs = self.memory.get_preferences()
            if not prefs:
                prefs = {"tone": "neutral", "interaction_style": "casual"}
                self.memory.store_preferences(prefs)
        except AttributeError:
            prefs = {"tone": "neutral", "interaction_style": "casual"}
        self.preferences = prefs

        # HFBrain
        try:
            if HFBrain:
                self.hf_brain = HFBrain(self.memory)
                log.info("HFBrain loaded successfully")
            else:
                self.hf_brain = None
        except RuntimeError as e:
            log.warning(f"HFBrain failed to initialize: {e}")
            self.hf_brain = None

        # InternetManager injection
        self.internet = internet or (InternetManager(db=self.memory) if InternetManager else None)

        # Self Modules
        self.self_researcher = SelfResearcher(self.memory) if SelfResearcher else None
        if self.self_researcher:
            self.self_researcher.internet = self.internet  # use updated InternetManager

        self.self_healer = SelfHealer(self.memory) if SelfHealer else None

        try:
            if SelfIdeaImplementation and self.memory:
                self.self_idea = SelfIdeaImplementation(self.memory)
                log.info("SelfIdeaImplementation loaded successfully")
            else:
                self.self_idea = None
        except Exception as e:
            log.warning(f"Failed to init SelfIdeaImplementation: {e}")
            self.self_idea = None

        self.reflect = ReflectModule(self.memory) if ReflectModule else None
        if self.reflect:
            log.info("ReflectModule loaded successfully")

        # SelfTeacher Wiring
        self.self_teacher = None
        if SelfTeacher:
            self.self_teacher = SelfTeacher(
                db=self.memory,
                researcher=self.self_researcher,
                reflector=self.reflect,
                learner=self.self_idea
            )
            log.info("SelfTeacher loaded successfully")

        # Inject teacher + learner into ReflectModule
        if self.reflect:
            if self.self_teacher:
                self.reflect.self_teacher = self.self_teacher
            if self.self_idea:
                self.reflect.learner = self.self_idea

    # ───────── Learning ─────────
    def learn(self, user_input):
        try:
            if hasattr(self.memory, "store_learning"):
                # If InternetManager structured search results exist, store them
                if isinstance(user_input, dict) and "structured_search" in user_input:
                    for res in user_input["structured_search"]:
                        self.memory.store_learning({
                            "time": datetime.datetime.utcnow().isoformat(),
                            "input": res.get("text"),
                            "source": res.get("source"),
                            "url": res.get("url")
                        })
                else:
                    self.memory.store_learning({
                        "time": datetime.datetime.utcnow().isoformat(),
                        "input": user_input
                    })
        except Exception as e:
            log.debug(f"Learning failed: {e}")

    # ───────── Thinking ─────────
    def think(self, user_input):
        self.learn(user_input)
        context = ""
        try:
            if hasattr(self.memory, "recall"):
                recalled = self.memory.recall(user_input)
                if recalled:
                    context = "Based on previous knowledge:\n"
                    for r in recalled:
                        if isinstance(r, dict):
                            context += f"- {r.get('input')}\n"
                        else:
                            context += f"- {r}\n"
                    context += "\n"
        except Exception:
            context = ""

        prompt = context + user_input
        if not self.llm_enabled:
            log.info("LLM disabled, returning neutral response")
            return f"[LLM disabled] '{user_input}'"

        if self.hf_brain:
            try:
                response = self.hf_brain.ask_single(prompt)
                if response:
                    return response.strip()
            except Exception as e:
                log.warning(f"HFBrain ask failed: {e}")
        return f"[neutral] I hear you: '{user_input}'"

    # ───────── Command Handling ─────────
    def handle_command(self, command: str):
        cmd = command.strip()
        lcmd = cmd.lower()

        if lcmd.startswith("self-research"):
            topic = cmd[len("self-research"):].strip() or "general"
            if self.self_researcher:
                # Use InternetManager structured search
                structured_results = self.self_researcher.search(topic)
                self.learn({"structured_search": structured_results})
                return structured_results
            return "SelfResearcher module not available."

        elif lcmd.startswith("self-heal"):
            if self.self_healer:
                return self.self_healer.repair()
            return "SelfHealer module not available."

        elif lcmd.startswith("self-idea"):
            if self.self_idea:
                prompt = cmd[len("self-idea"):].strip()
                return self.self_idea.implement_idea(prompt)
            return "SelfIdeaImplementation not available."

        elif lcmd.startswith("self-implement"):
            if self.self_idea:
                return self.self_idea.implement_ideas()
            return "SelfIdeaImplementation not available."

        elif lcmd.startswith("reflect"):
            if self.reflect:
                text = cmd[len("reflect"):].strip()
                return self.reflect.collect_and_summarize(text)
            return "Reflect module not available."

        elif lcmd.startswith("auto-reflect"):
            if self.reflect and hasattr(self.memory, "recall"):
                recent = [str(x) for x in self.memory.recall("", 5)]
                return self.reflect.auto_reflect(recent)
            return "Auto reflection unavailable."

        else:
            return self.think(command)

    # ───────── Router-Compatible Handle ─────────
    def handle(self, text: str) -> str:
        if not getattr(self, "llm_enabled", True):
            return f"[LLM disabled] '{text}'"
        ltext = text.lower().strip()
        if (
            ltext.startswith("self-research")
            or ltext.startswith("self-heal")
            or ltext.startswith("self-idea")
            or ltext.startswith("self-implement")
            or ltext.startswith("reflect")
            or ltext.startswith("auto-reflect")
        ):
            return self.handle_command(text)
        return self.think(text)


<<<<<<< HEAD
# ───────── Module-level HF query (used by niblit_orchestrator) ─────────
def hf_query(prompt: str) -> str:
    """Execute a HuggingFace model query. Exposed at module level for orchestrator."""
    try:
        hf = HFBrain(None)
        return hf.ask_single(prompt) or "[No response]"
    except Exception as e:
        log.debug(f"hf_query failed: {e}")
        return f"[HF query failed: {e}]"
=======
# ─────────── HF Shortcut ───────────
def hf_query(prompt: str, memory=None, llm_enabled=True):
    if memory is None:
        try:
            from niblit_memory import MemoryManager
            memory = MemoryManager()
        except Exception as _e:
            log.warning(f"niblit_memory unavailable in hf_query, proceeding without memory: {_e}")
            memory = None
    brain = NiblitBrain(memory, llm_enabled=llm_enabled)
    return brain.think(prompt)
>>>>>>> 29b8b59 (Fix import errors: add hf_query to niblit_brain, wrap imports in lifecycle_engine)
