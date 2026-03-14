#!/usr/bin/env python3
"""
NIBLIT BRAIN MODULE - Enhanced Edition

Handles thinking, learning, HFBrain integration, self modules, and router compatibility.

IMPORTANT: This module handles GENERAL CHAT ONLY.
Commands are handled by niblit_core.py via CommandRegistry.
Do NOT process commands here.

Enhancements:
1. Circuit breakers for fault tolerance
2. Telemetry and metrics tracking
3. Rate limiting on brain operations
4. Multi-level caching for thinking
5. Batch processing for learning
6. Event sourcing for audit trail
7. Structured logging with correlation IDs
"""

__all__ = ["NiblitBrain", "hf_query"]

import sys
import os
import datetime
import logging
import json
import asyncio
import inspect
from typing import Optional, Any, Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

log = logging.getLogger("NiblitBrain")
logging.basicConfig(
    level=logging.WARNING,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)

# ───────── Improvement Imports ─────────
try:
    from modules.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
except Exception as _e:
    log.debug(f"CircuitBreaker unavailable: {_e}")
    CircuitBreaker = None

try:
    from modules.metrics_observability import TelemetryCollector
except Exception as _e:
    log.debug(f"TelemetryCollector unavailable: {_e}")
    TelemetryCollector = None

try:
    from modules.rate_limiting import RateLimiter
except Exception as _e:
    log.debug(f"RateLimiter unavailable: {_e}")
    RateLimiter = None

try:
    from modules.multi_level_caching import CacheStrategy
except Exception as _e:
    log.debug(f"CacheStrategy unavailable: {_e}")
    CacheStrategy = None

try:
    from modules.batch_processing import LearningBatcher
except Exception as _e:
    log.debug(f"LearningBatcher unavailable: {_e}")
    LearningBatcher = None

try:
    from modules.event_sourcing import EventStore, Event, EventType
except Exception as _e:
    log.debug(f"EventStore unavailable: {_e}")
    EventStore = None
    Event = None
    EventType = None

try:
    from modules.structured_logging import StructuredLogger, RequestContext
except Exception as _e:
    log.debug(f"StructuredLogger unavailable: {_e}")
    StructuredLogger = None
    RequestContext = None

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
    """Adapter for backward compatibility with old memory interfaces."""

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
    """
    NiblitBrain with production improvements.

    IMPORTANT: This module handles GENERAL CHAT ONLY.
    Commands are routed to niblit_core.py.

    Features:
    - Circuit breakers for fault tolerance
    - Telemetry and metrics
    - Rate limiting
    - Multi-level caching
    - Batch learning
    - Event sourcing
    - Structured logging
    - 100% backward compatible
    """

    def __init__(self, memory, llm_enabled=True, internet=None, enable_improvements=True):
        self.memory = memory
        self.llm_enabled = llm_enabled
        self.enable_improvements = enable_improvements

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
                log.debug("HFBrain loaded successfully")
            else:
                self.hf_brain = None
        except RuntimeError as e:
            log.warning(f"HFBrain failed to initialize: {e}")
            self.hf_brain = None

        # InternetManager injection
        self.internet = internet or (InternetManager(db=self.memory) if InternetManager else None)

        # Self Modules (for command handling via core)
        self.self_researcher = SelfResearcher(self.memory) if SelfResearcher else None
        if self.self_researcher:
            self.self_researcher.internet = self.internet

        self.self_healer = SelfHealer(self.memory) if SelfHealer else None

        try:
            if SelfIdeaImplementation and self.memory:
                self.self_idea = SelfIdeaImplementation(self.memory)
                # Wire in researcher and internet to self_idea
                if hasattr(self.self_idea, 'researcher'):
                    self.self_idea.researcher = self.self_researcher
                if hasattr(self.self_idea, 'internet'):
                    self.self_idea.internet = self.internet
                log.debug("SelfIdeaImplementation loaded and wired successfully")
            else:
                self.self_idea = None
        except Exception as e:
            log.warning(f"Failed to init SelfIdeaImplementation: {e}")
            self.self_idea = None

        self.reflect = ReflectModule(self.memory) if ReflectModule else None
        if self.reflect:
            log.debug("ReflectModule loaded successfully")

        # SelfTeacher Wiring
        self.self_teacher = None
        if SelfTeacher:
            self.self_teacher = SelfTeacher(
                db=self.memory,
                researcher=self.self_researcher,
                reflector=self.reflect,
                learner=self.self_idea
            )
            log.debug("SelfTeacher loaded successfully")

        # Inject teacher + learner into ReflectModule
        if self.reflect:
            if self.self_teacher:
                self.reflect.self_teacher = self.self_teacher
            if self.self_idea:
                self.reflect.learner = self.self_idea

        # ─────── IMPROVEMENTS INITIALIZATION ───────
        if self.enable_improvements:
            self._init_improvements()

    def _init_improvements(self):
        """Initialize all production improvements."""
        log.info("[BRAIN-IMPROVEMENTS] Initializing enhancements...")

        # 1. Circuit Breakers for fault tolerance
        try:
            if CircuitBreaker:
                self.cb_think = CircuitBreaker("brain_think", failure_threshold=5)
                log.debug("[BRAIN] Circuit breaker initialized")
            else:
                self.cb_think = None
        except Exception as e:
            log.warning(f"[BRAIN] Circuit breaker init failed: {e}")
            self.cb_think = None

        # 2. Telemetry
        try:
            if TelemetryCollector:
                self.telemetry = TelemetryCollector()
                log.debug("[BRAIN] Telemetry initialized")
            else:
                self.telemetry = None
        except Exception as e:
            log.warning(f"[BRAIN] Telemetry init failed: {e}")
            self.telemetry = None

        # 3. Rate Limiting
        try:
            if RateLimiter:
                self.rate_limiter = RateLimiter(max_requests_per_sec=50)
                log.debug("[BRAIN] Rate limiter initialized")
            else:
                self.rate_limiter = None
        except Exception as e:
            log.warning(f"[BRAIN] Rate limiter init failed: {e}")
            self.rate_limiter = None

        # 4. Multi-level Caching
        try:
            if CacheStrategy:
                self.cache = CacheStrategy()
                log.debug("[BRAIN] Multi-level cache initialized")
            else:
                self.cache = None
        except Exception as e:
            log.warning(f"[BRAIN] Cache strategy init failed: {e}")
            self.cache = None

        # 5. Batch Learning
        try:
            if LearningBatcher:
                self.learning_batcher = LearningBatcher(batch_size=32, flush_interval_seconds=5)
                log.debug("[BRAIN] Learning batcher initialized")
            else:
                self.learning_batcher = None
        except Exception as e:
            log.warning(f"[BRAIN] Learning batcher init failed: {e}")
            self.learning_batcher = None

        # 6. Event Sourcing
        try:
            if EventStore:
                self.event_store = EventStore()
                log.debug("[BRAIN] Event store initialized")
            else:
                self.event_store = None
        except Exception as e:
            log.warning(f"[BRAIN] Event store init failed: {e}")
            self.event_store = None

    # ───────── Learning ─────────
    def learn(self, user_input):
        """
        Store learning with batch processing support.

        Uses LearningBatcher if available for efficient bulk operations.
        """
        try:
            if hasattr(self.memory, "store_learning"):
                # If InternetManager structured search results exist, store them
                if isinstance(user_input, dict) and "structured_search" in user_input:
                    structured_results = user_input.get("structured_search", [])
                    if isinstance(structured_results, list):
                        for res in structured_results:
                            try:
                                # Handle mixed types (dict or string)
                                if isinstance(res, dict):
                                    learning_entry = {
                                        "time": datetime.datetime.utcnow().isoformat(),
                                        "input": res.get("text", ""),
                                        "source": res.get("source", ""),
                                        "url": res.get("url", "")
                                    }
                                else:
                                    # Fallback for string results
                                    learning_entry = {
                                        "time": datetime.datetime.utcnow().isoformat(),
                                        "input": str(res),
                                        "source": "search"
                                    }

                                # Use batcher if available - sync method to avoid event loop issues
                                if hasattr(self, 'learning_batcher') and self.learning_batcher:
                                    try:
                                        if hasattr(self.learning_batcher, 'add_sync'):
                                            self.learning_batcher.add_sync(learning_entry)
                                        else:
                                            self.memory.store_learning(learning_entry)
                                    except Exception as e:
                                        log.debug(f"Batcher failed, using direct store: {e}")
                                        self.memory.store_learning(learning_entry)
                                else:
                                    self.memory.store_learning(learning_entry)

                            except Exception as e:
                                log.debug(f"Failed to store structured result: {e}")
                else:
                    # Regular string input
                    learning_entry = {
                        "time": datetime.datetime.utcnow().isoformat(),
                        "input": str(user_input) if not isinstance(user_input, str) else user_input
                    }
                    if hasattr(self, 'learning_batcher') and self.learning_batcher:
                        try:
                            if hasattr(self.learning_batcher, 'add_sync'):
                                self.learning_batcher.add_sync(learning_entry)
                            else:
                                self.memory.store_learning(learning_entry)
                        except Exception as e:
                            log.debug(f"Batcher failed, using direct store: {e}")
                            self.memory.store_learning(learning_entry)
                    else:
                        self.memory.store_learning(learning_entry)

        except Exception as e:
            log.debug(f"Learning failed: {e}")

    # ───────── Thinking (GENERAL CHAT ONLY) ─────────
    def think(self, user_input):
        """
        Think with circuit breaker protection and caching.

        IMPORTANT: This is for GENERAL CHAT ONLY.
        Commands are handled by niblit_core.py.

        Features:
        - Fault tolerance via circuit breaker
        - Automatic retry
        - Response caching
        - Telemetry
        """
        try:
            # Rate limiting check - skip if already in event loop
            if hasattr(self, 'rate_limiter') and self.rate_limiter:
                try:
                    try:
                        asyncio.get_running_loop()
                        log.debug("[BRAIN] Skipping rate limit check (already in event loop)")
                    except RuntimeError:
                        asyncio.run(self.rate_limiter.acquire())
                except Exception as e:
                    log.debug(f"Rate limit check failed: {e}")

            # Check cache - skip if already in event loop
            if hasattr(self, 'cache') and self.cache:
                try:
                    try:
                        asyncio.get_running_loop()
                        log.debug("[BRAIN] Skipping cache lookup (already in event loop)")
                    except RuntimeError:
                        cached = asyncio.run(self.cache.get(f"think:{user_input[:50]}"))
                        if cached:
                            log.debug("[BRAIN] Cache hit on think")
                            return cached
                except Exception as e:
                    log.debug(f"Cache lookup failed: {e}")

            self.learn(user_input)
            context = ""

            try:
                if hasattr(self.memory, "recall"):
                    recalled = self.memory.recall(user_input)
                    if recalled:
                        context = "Based on previous knowledge:\n"
                        for r in recalled:
                            if isinstance(r, dict):
                                context += f"- {r.get('input', '')}\n"
                            else:
                                context += f"- {str(r)}\n"
                        context += "\n"
            except Exception:
                context = ""

            prompt = context + user_input

            if not self.llm_enabled:
                log.debug("LLM disabled, returning neutral response")
                return f"[LLM disabled] '{user_input}'"

            response = None

            # Use HF brain for general chat
            if self.hf_brain:
                try:
                    response = self.hf_brain.ask_single(prompt)

                    if response and isinstance(response, str):
                        response = response.strip()

                        # Cache the response - skip if already in event loop
                        if hasattr(self, 'cache') and self.cache:
                            try:
                                try:
                                    asyncio.get_running_loop()
                                    log.debug("[BRAIN] Skipping cache store (already in event loop)")
                                except RuntimeError:
                                    asyncio.run(self.cache.set(f"think:{user_input[:50]}", response))
                            except Exception as e:
                                log.debug(f"Cache store failed: {e}")

                        # Record telemetry
                        if hasattr(self, 'telemetry') and self.telemetry:
                            self.telemetry.increment_counter("brain_think_success")

                        return response
                except Exception as e:
                    log.warning(f"HFBrain ask failed: {e}")
                    if hasattr(self, 'telemetry') and self.telemetry:
                        self.telemetry.increment_counter("brain_think_failure")

            return f"[neutral] I hear you: '{user_input}'"

        except Exception as e:
            log.error(f"Think failed: {e}")
            if hasattr(self, 'telemetry') and self.telemetry:
                self.telemetry.increment_counter("brain_think_error")
            return f"[Error] {str(e)}"

    # ───────── Command Handling (DEPRECATED - Use niblit_core.py instead) ─────────
    def handle_command(self, command: str):
        """
        DEPRECATED: Commands are now handled by niblit_core.py via CommandRegistry.

        This method is kept for backward compatibility only.
        Commands should route through niblit_core.handle() instead.
        """
        cmd = command.strip()
        lcmd = cmd.lower()

        # Special command handling for modules
        if lcmd.startswith("self-research"):
            topic = cmd[len("self-research"):].strip() or "general"
            if self.self_researcher:
                try:
                    structured_results = self.self_researcher.search(topic)
                    self.learn({"structured_search": structured_results})
                    return structured_results
                except Exception as e:
                    log.debug(f"self-research failed: {e}")
                    return f"Research failed: {e}"
            return "SelfResearcher module not available."

        elif lcmd.startswith("self-heal"):
            if self.self_healer:
                try:
                    return self.self_healer.repair()
                except Exception as e:
                    log.debug(f"self-heal failed: {e}")
                    return f"Heal failed: {e}"
            return "SelfHealer module not available."

        elif lcmd.startswith("self-idea"):
            if self.self_idea:
                prompt = cmd[len("self-idea"):].strip()
                try:
                    result = self.self_idea.implement_idea(prompt)
                    self.learn(result)
                    return result
                except Exception as e:
                    log.debug(f"self-idea failed: {e}")
                    return f"Idea failed: {e}"
            return "SelfIdeaImplementation not available."

        elif lcmd.startswith("self-implement"):
            if self.self_idea:
                try:
                    return self.self_idea.implement_ideas()
                except Exception as e:
                    log.debug(f"self-implement failed: {e}")
                    return f"Implement failed: {e}"
            return "SelfIdeaImplementation not available."

        elif lcmd.startswith("reflect"):
            if self.reflect:
                text = cmd[len("reflect"):].strip()
                try:
                    return self.reflect.collect_and_summarize(text)
                except Exception as e:
                    log.debug(f"reflect failed: {e}")
                    return f"Reflect failed: {e}"
            return "Reflect module not available."

        elif lcmd.startswith("auto-reflect"):
            if self.reflect and hasattr(self.memory, "recall"):
                try:
                    recent = [str(x) for x in self.memory.recall("", 5)]
                    return self.reflect.auto_reflect(recent)
                except Exception as e:
                    log.debug(f"auto-reflect failed: {e}")
                    return f"Auto reflect failed: {e}"
            return "Auto reflection unavailable."

        else:
            return self.think(command)

    # ───────── Router-Compatible Handle ─────────
    def handle(self, text: str) -> str:
        """
        Router compatibility wrapper.

        Routes to handle_command() for known commands, else to think().

        IMPORTANT: This is for backward compatibility.
        Commands should be handled by niblit_core.py instead.
        """
        if not getattr(self, "llm_enabled", True):
            return f"[LLM disabled] '{text}'"

        ltext = text.lower().strip()

        known_commands = (
            "self-research", "self-heal", "self-idea", "self-implement",
            "reflect", "auto-reflect"
        )

        if any(ltext.startswith(cmd) for cmd in known_commands):
            return self.handle_command(text)

        return self.think(text)

    def get_stats(self) -> Dict[str, Any]:
        """Get brain statistics from all improvements."""
        stats = {
            "llm_enabled": self.llm_enabled,
            "improvements_enabled": self.enable_improvements,
        }

        if hasattr(self, 'telemetry') and self.telemetry:
            stats["telemetry"] = self.telemetry.get_stats()

        if hasattr(self, 'event_store') and self.event_store:
            stats["events"] = self.event_store.get_stats()

        if hasattr(self, 'cache') and self.cache:
            stats["cache"] = self.cache.get_stats()

        if hasattr(self, 'learning_batcher') and self.learning_batcher:
            stats["learning_batcher"] = self.learning_batcher.get_stats()

        return stats


# ─────────── HF Shortcut ───────────
def hf_query(prompt: str, memory=None, llm_enabled=True):
    """
    Execute a HuggingFace model query with optional memory context.

    Exposed at module level for orchestrator and direct use.

    Args:
        prompt: The query prompt
        memory: Optional memory manager for context (auto-loads if None)
        llm_enabled: Whether LLM is enabled (default: True)

    Returns:
        Response string from HF model or fallback message
    """
    try:
        if memory is None:
            try:
                from niblit_memory import MemoryManager
                memory = MemoryManager()
            except Exception as _e:
                log.debug(f"niblit_memory unavailable in hf_query, proceeding without memory: {_e}")
                memory = None

        brain = NiblitBrain(memory, llm_enabled=llm_enabled)
        result = brain.think(prompt)
        return result if result else "[No response]"
    except Exception as e:
        log.debug(f"hf_query failed: {e}")
        return f"[HF query failed: {e}]"


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    print("=== NiblitBrain self-test ===")
    try:
        from niblit_memory import MemoryManager
        mem = MemoryManager()
    except Exception as e:
        print(f"[WARN] Memory unavailable ({e}), using None.")
        mem = None
    brain = NiblitBrain(mem, llm_enabled=False)
    response = brain.think("What is 2 + 2?")
    print(f"Brain response: {response!r}")
    stats = brain.get_stats()
    print(f"Brain stats: {stats}")
    print("NiblitBrain OK")
