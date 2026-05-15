#!/usr/bin/env python3
"""
niblit_core.py — NiblitCore: Production-Grade Autonomous AI Runtime with Full Self-Improvement

Enhanced with 17 production improvements + 10 self-improvement modules + Autonomous Learning:
1. CommandRegistry - Clean command dispatcher
2. LayeredArchitecture - Separation of concerns
3. DependencyInjection - Testable design
4. StructuredLogging - Correlation ID tracing
5. AsyncFirst - Full async/await support
6. EventSourcing - Immutable audit trail
7. RateLimiting - Token bucket algorithm
8. Metrics - Observability & telemetry
9. CircuitBreaker - Fault tolerance
10. ConnectionPooling - Resource efficiency
11. MultiLevelCaching - Performance optimization
12. BatchProcessing - Bulk operation efficiency
13. PluginArchitecture - Hot-reload support
14. MonitoringAlerting - Prometheus integration
15. CommandLLMDecoupling - Commands ≠ LLM
16. FullBackwardCompatibility - All logic preserved
17. ProductionReady - Enterprise-grade reliability

+ 10 SELF-IMPROVEMENT MODULES + AUTONOMOUS LEARNING ENGINE

Architecture:
User Input → CommandRegistry (commands only, zero LLM)
          → RouterLayer (complex routing)
          → ImprovementsLayer (autonomous self-improvement)
          → AutonomousLayer (background learning when idle)
          → LLMLayer (general chat only)

Compatible with main.py, server.py, and app.py.
"""
# pylint: disable=too-many-lines

# ============================================================
# STDLIB IMPORTS
# ============================================================
import os
import sys
import re
import tempfile
import time
import asyncio
import threading
import logging
import inspect
import importlib.util
import hashlib
import json
import uuid  # pylint: disable=unused-import
import traceback as _traceback
import contextvars
from datetime import datetime, timezone, timedelta  # pylint: disable=unused-import
from typing import Any, Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
import collections
from collections import defaultdict
import queue as _queue_mod
from contextlib import contextmanager
from pathlib import Path
from functools import lru_cache  # pylint: disable=unused-import
from enum import Enum  # pylint: disable=unused-import
from abc import ABC, abstractmethod  # pylint: disable=unused-import

# Load .env file when running locally (e.g. Termux).  On Vercel / Render the
# platform injects env vars directly, so this is a no-op in those environments.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on os.environ

# Side-effect import kept at module level so orphan symbol stubs are available
# (moved here from line 1 so it runs after stdlib/dotenv setup).
try:
    import modules.orphan_imports  # auto-added by self_heal_auto  # pylint: disable=unused-import
except Exception:
    pass

# ============================================================
# PATH SETUP
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

# ============================================================
# LOGGING SETUP
# ============================================================
log = logging.getLogger("NiblitCore")
chat_log = logging.getLogger("NiblitChat")

# Context variable for correlation ID
correlation_id_var = contextvars.ContextVar('correlation_id', default=None)

# ============================================================
# _try_import HELPER
# Centralises the repeated try/except import pattern used throughout this
# module.  Returns (object_or_None, available_bool).
# Usage:
#   MyClass, _MY_AVAILABLE = _try_import("modules.my_module", "MyClass")
# ============================================================

def _try_import(dotted_path: str, attr: Optional[str] = None):
    """Attempt to import *attr* from *dotted_path*.

    Returns ``(value, True)`` on success and ``(None, False)`` on any error,
    logging the failure at DEBUG level.  This replaces the repetitive
    try/except import blocks that appear throughout niblit_core.py.
    """
    try:
        import importlib as _il
        m = _il.import_module(dotted_path)
        result = getattr(m, attr) if attr else m
        return result, True
    except Exception as _e:
        log.debug("Optional import %s%s failed: %s", dotted_path,
                  f".{attr}" if attr else "", _e)
        return None, False

# ============================================================
# IMPROVEMENT IMPORTS (from modules/)
# ============================================================
try:
    from modules.command_registry import CommandRegistry
except Exception as e:
    log.debug(f"CommandRegistry import failed: {e}")
    CommandRegistry = None

try:
    from modules.structured_logging import StructuredLogger, RequestContext  # pylint: disable=unused-import
except Exception as e:
    log.debug(f"StructuredLogger import failed: {e}")
    StructuredLogger = None

try:
    from modules.async_first import AsyncTaskCoordinator, AsyncTask  # pylint: disable=unused-import
except Exception as e:
    log.debug(f"AsyncTaskCoordinator import failed: {e}")
    AsyncTaskCoordinator = None

try:
    from modules.event_sourcing import EventStore, Event, EventType  # pylint: disable=unused-import
except Exception as e:
    log.debug(f"EventStore import failed: {e}")
    EventStore = None

try:
    from modules.rate_limiting import RateLimiter
except Exception as e:
    log.debug(f"RateLimiter import failed: {e}")
    RateLimiter = None

try:
    from modules.metrics_observability import TelemetryCollector
except Exception as e:
    log.debug(f"TelemetryCollector import failed: {e}")
    TelemetryCollector = None

try:
    from modules.circuit_breaker import CircuitBreaker
except Exception as e:
    log.debug(f"CircuitBreaker import failed: {e}")
    CircuitBreaker = None

try:
    from modules.connection_pooling import ConnectionPool
except Exception as e:
    log.debug(f"ConnectionPool import failed: {e}")
    ConnectionPool = None

try:
    from modules.multi_level_caching import CacheStrategy
except Exception as e:
    log.debug(f"CacheStrategy import failed: {e}")
    CacheStrategy = None

try:
    from modules.batch_processing import LearningBatcher
except Exception as e:
    log.debug(f"LearningBatcher import failed: {e}")
    LearningBatcher = None

try:
    from modules.plugin_architecture import PluginManager, PluginInterface  # pylint: disable=unused-import
except Exception as e:
    log.debug(f"PluginManager import failed: {e}")
    PluginManager = None

try:
    from modules.monitoring_alerting import AlertManager, Alert, AlertSeverity  # pylint: disable=unused-import
except Exception as e:
    log.debug(f"AlertManager import failed: {e}")
    AlertManager = None

# ============================================================
# 10 SELF-IMPROVEMENT MODULES IMPORTS
# ============================================================
try:
    from modules.parallel_learner import ParallelLearner
except Exception as e:
    log.debug(f"ParallelLearner import failed: {e}")
    ParallelLearner = None

try:
    from modules.reasoning_engine import ReasoningEngine
except Exception as e:
    log.debug(f"ReasoningEngine import failed: {e}")
    ReasoningEngine = None

try:
    from modules.gap_analyzer import GapAnalyzer
except Exception as e:
    log.debug(f"GapAnalyzer import failed: {e}")
    GapAnalyzer = None

try:
    from modules.knowledge_synthesizer import KnowledgeSynthesizer
except Exception as e:
    log.debug(f"KnowledgeSynthesizer import failed: {e}")
    KnowledgeSynthesizer = None

try:
    from modules.prediction_engine import PredictionEngine
except Exception as e:
    log.debug(f"PredictionEngine import failed: {e}")
    PredictionEngine = None

try:
    from modules.memory_optimizer import MemoryOptimizer
except Exception as e:
    log.debug(f"MemoryOptimizer import failed: {e}")
    MemoryOptimizer = None

try:
    from modules.adaptive_learning import AdaptiveLearning
except Exception as e:
    log.debug(f"AdaptiveLearning import failed: {e}")
    AdaptiveLearning = None

try:
    from modules.metacognition import Metacognition
except Exception as e:
    log.debug(f"Metacognition import failed: {e}")
    Metacognition = None

try:
    from modules.collaborative_learner import CollaborativeLearner
except Exception as e:
    log.debug(f"CollaborativeLearner import failed: {e}")
    CollaborativeLearner = None

try:
    from modules.improvement_integrator import ImprovementIntegrator
except Exception as e:
    log.debug(f"ImprovementIntegrator import failed: {e}")
    ImprovementIntegrator = None

try:
    from modules.agentic_workflows import AgenticWorkflow
except Exception as e:
    log.debug(f"AgenticWorkflow import failed: {e}")
    AgenticWorkflow = None

try:
    from modules.enterprise_utility import EnterpriseUtility
except Exception as e:
    log.debug(f"EnterpriseUtility import failed: {e}")
    EnterpriseUtility = None

try:
    from modules.multimodal_intelligence import MultimodalIntelligence
except Exception as e:
    log.debug(f"MultimodalIntelligence import failed: {e}")
    MultimodalIntelligence = None

# ============================================================
# AUTONOMOUS LEARNING ENGINE IMPORT
# ============================================================
try:
    from modules.autonomous_learning_engine import AutonomousLearningEngine
except Exception as e:
    log.debug(f"AutonomousLearningEngine import failed: {e}")
    AutonomousLearningEngine = None

# ============================================================
# BUILDS INTEGRATOR IMPORT
# ============================================================
try:
    from modules.builds_integrator import BuildsIntegrator
except Exception as _e:
    log.debug(f"BuildsIntegrator import failed: {_e}")
    BuildsIntegrator = None  # type: ignore[assignment,misc]

# ============================================================
try:
    from modules.trading_brain import TradingBrain
except Exception as e:
    log.debug(f"TradingBrain import failed: {e}")
    TradingBrain = None  # type: ignore[assignment,misc]

# ── FilteredSwingTraderV3 (additive: continuous trend re-entry model) ────────
try:
    from modules.trading_swing_v3 import FilteredSwingTraderV3
except Exception as _e:
    log.debug(f"FilteredSwingTraderV3 import failed: {_e}")
    FilteredSwingTraderV3 = None  # type: ignore[assignment,misc]

# ── ALE Checkpoint Manager (additive: persistent state across restarts) ──────
try:
    from modules.ale_checkpoint import ALECheckpointManager
except Exception as _e:
    log.debug(f"ALECheckpointManager import failed: {_e}")
    ALECheckpointManager = None  # type: ignore[assignment,misc]

# ============================================================
# LIVE UPDATER + STRUCTURAL AWARENESS IMPORTS
# ============================================================
try:
    from modules.live_updater import LiveUpdater
except Exception as e:
    log.debug(f"LiveUpdater import failed: {e}")
    LiveUpdater = None

try:
    from modules.structural_awareness import StructuralAwareness
except Exception as e:
    log.debug(f"StructuralAwareness import failed: {e}")
    StructuralAwareness = None

try:
    from modules.code_generator import CodeGenerator
except Exception as e:
    log.debug(f"CodeGenerator import failed: {e}")
    CodeGenerator = None

try:
    from modules.code_compiler import CodeCompiler
except Exception as e:
    log.debug(f"CodeCompiler import failed: {e}")
    CodeCompiler = None

try:
    from modules.code_error_fixer import CodeErrorFixer
except Exception as e:
    log.debug(f"CodeErrorFixer import failed: {e}")
    CodeErrorFixer = None

try:
    from modules.filesystem_manager import FilesystemManager as FileManager
except Exception as e:
    log.debug(f"FilesystemManager import failed: {e}")
    FileManager = None

try:
    from modules.software_studier import SoftwareStudier
except Exception as e:
    log.debug(f"SoftwareStudier import failed: {e}")
    SoftwareStudier = None

try:
    from modules.evolve import EvolveEngine
except Exception as e:
    log.debug(f"EvolveEngine import failed: {e}")
    EvolveEngine = None

try:
    from civilization.civilization_core.civilization_controller import CivilizationController as _CivilizationController
except Exception as _civ_err:
    log.debug(f"CivilizationController import failed: {_civ_err}")
    _CivilizationController = None  # type: ignore[assignment,misc]

try:
    from modules.termux_wakelock import TermuxWakeLock
except Exception as e:
    log.debug(f"TermuxWakeLock import failed: {e}")
    TermuxWakeLock = None

# ── GameEngine (additive) ─────────────────────────────────────────────────────
try:
    from modules.game_engine import GameEngine as _GameEngine, get_game_engine as _get_game_engine
    _GAME_ENGINE_AVAILABLE = True
except Exception as _e:
    log.debug(f"GameEngine import failed: {_e}")
    _GameEngine = None  # type: ignore[assignment,misc]
    _get_game_engine = None  # type: ignore[assignment]
    _GAME_ENGINE_AVAILABLE = False

# ── UniversalFileManager (additive) ──────────────────────────────────────────
try:
    from modules.universal_file_manager import (
        UniversalFileManager as _UniversalFileManager,
        get_file_manager as _get_file_manager,
    )
    _UNIVERSAL_FILE_MANAGER_AVAILABLE = True
except Exception as _e:
    log.debug(f"UniversalFileManager import failed: {_e}")
    _UniversalFileManager = None  # type: ignore[assignment,misc]
    _get_file_manager = None  # type: ignore[assignment]
    _UNIVERSAL_FILE_MANAGER_AVAILABLE = False

# ============================================================
# DEPLOYMENT BRIDGE, AUTONOMOUS NETWORK, MODULE AUTONOMY
# ============================================================
try:
    from modules.deployment_bridge import DeploymentBridge, get_deployment_bridge  # pylint: disable=unused-import
    _DEPLOYMENT_BRIDGE_AVAILABLE = True
except Exception as _e:
    log.debug(f"DeploymentBridge import failed: {_e}")
    DeploymentBridge = None  # type: ignore[assignment,misc]
    get_deployment_bridge = None  # type: ignore[assignment]
    _DEPLOYMENT_BRIDGE_AVAILABLE = False

try:
    from modules.autonomous_network import AutonomousNetworkBuilder, get_autonomous_network  # pylint: disable=unused-import
    _AUTONOMOUS_NETWORK_AVAILABLE = True
except Exception as _e:
    log.debug(f"AutonomousNetworkBuilder import failed: {_e}")
    AutonomousNetworkBuilder = None  # type: ignore[assignment,misc]
    get_autonomous_network = None  # type: ignore[assignment]
    _AUTONOMOUS_NETWORK_AVAILABLE = False

try:
    from modules.module_autonomy import ModuleAutonomy, get_module_autonomy  # pylint: disable=unused-import
    _MODULE_AUTONOMY_AVAILABLE = True
except Exception as _e:
    log.debug(f"ModuleAutonomy import failed: {_e}")
    ModuleAutonomy = None  # type: ignore[assignment,misc]
    get_module_autonomy = None  # type: ignore[assignment]
    _MODULE_AUTONOMY_AVAILABLE = False

# ============================================================
# GLOBAL FLAGS & COMMAND LIST
# ============================================================
# Derive from environment so NIBLIT_DEBUG=false works at runtime.
DEBUG_MODE = os.getenv("NIBLIT_DEBUG", "true").lower() in ("true", "1")
COMMANDS = [
    "help", "status", "memory", "search", "summary",
    "learn about", "self-heal", "self-teach", "self-research",
    "self-idea", "self-implement", "reflect", "idea-implement",
    "debug on", "debug off", "threads",
    "show improvements", "run improvement-cycle", "improvement-status",
    "autonomous-learn start", "autonomous-learn stop", "autonomous-learn status",
    "autonomous-learn add-topic", "autonomous-learn code-status",
    "evolve", "evolve start", "evolve stop", "evolve status", "evolve history",
    "research code",
    "recall", "acquired data", "knowledge stats", "ale processes",
]

# ============================================================
# CONFIGURATION & DATACLASSES
# ============================================================

@dataclass
class NiblitConfig:
    """Configuration for NiblitCore with environment variable support."""
    # pylint: disable=too-many-instance-attributes
    base_dir: Path = Path(__file__).parent
    tools_dir: Optional[Path] = None
    memory_path: Optional[Path] = None
    debug_mode: bool = True
    log_level: str = "INFO"
    max_memory_entries: int = 500
    research_queue_limit: int = 5
    enable_orchestrator: bool = True
    enable_background_loops: bool = True
    enable_async_loops: bool = False
    shutdown_timeout_seconds: float = 30
    health_check_interval: int = 120
    dump_loop_log_interval: int = 300
    enable_improvements: bool = True
    enable_self_improvements: bool = True
    enable_autonomous_engine: bool = True

    def __post_init__(self):
        if self.tools_dir is None:
            self.tools_dir = self.base_dir / "tools"

    @classmethod
    def from_env(cls) -> "NiblitConfig":
        """Load configuration from environment variables."""
        _mp = os.getenv("NIBLIT_MEMORY_PATH", "").strip()
        return cls(
            memory_path=Path(_mp) if _mp else None,
            debug_mode=os.getenv("NIBLIT_DEBUG", "true").lower() in ("true", "1"),
            log_level=os.getenv("NIBLIT_LOG_LEVEL", "INFO"),
            enable_orchestrator=os.getenv("NIBLIT_ORCHESTRATOR", "true").lower() in ("true", "1"),
            enable_background_loops=os.getenv("NIBLIT_LOOPS", "true").lower() in ("true", "1"),
            enable_async_loops=os.getenv("NIBLIT_ASYNC", "false").lower() in ("true", "1"),
            enable_improvements=os.getenv("NIBLIT_IMPROVEMENTS", "true").lower() in ("true", "1"),
            enable_self_improvements=os.getenv("NIBLIT_SELF_IMPROVEMENTS", "true").lower() in ("true", "1"),
            enable_autonomous_engine=os.getenv("NIBLIT_AUTONOMOUS_ENGINE", "true").lower() in ("true", "1"),
        )


@dataclass
class StartupReport:
    """Track initialization status of each component."""
    results: Dict[str, Dict[str, Optional[str]]] = field(default_factory=dict)

    def add(self, name: str, status: str, error: Optional[str] = None):
        """Record component initialization result."""
        self.results[name] = {"status": status, "error": error}

    def is_healthy(self) -> bool:
        """Return True if all critical components initialized."""
        critical = ["db", "identity", "guard"]
        return all(
            self.results.get(c, {}).get("status") == "ready"
            for c in critical
        )

    def summary(self) -> str:
        """Generate startup summary."""
        ready = sum(1 for r in self.results.values() if r.get("status") == "ready")
        total = len(self.results)
        return f"Startup: {ready}/{total} components ready"


@dataclass
class HealthCheckResult:
    """Result of comprehensive health check."""
    status: str
    components: Dict[str, str]
    uptime_seconds: int
    memory_entries: int
    errors: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PerformanceMetrics:
    """Track performance metrics for all operations."""
    operation_times: Dict[str, Any] = field(default_factory=lambda: defaultdict(lambda: collections.deque(maxlen=1000)))
    operation_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_operation(self, name: str, duration_ms: float, success: bool = True):
        """Record operation execution."""
        self.operation_times[name].append(duration_ms)
        self.operation_counts[name] += 1
        if not success:
            self.error_counts[name] += 1

    def get_stats(self, name: str) -> Dict[str, float]:
        """Get statistics for an operation."""
        times = list(self.operation_times.get(name, []))
        if not times:
            return {}
        return {
            "count": self.operation_counts[name],
            "errors": self.error_counts[name],
            "avg_ms": sum(times) / len(times),
            "max_ms": max(times),
            "min_ms": min(times),
        }


class NiblitLogger:
    """Structured logging with context tracking."""

    def __init__(self, name: str):
        self.log = logging.getLogger(name)
        self.context_stack: List[Dict[str, Any]] = []

    @contextmanager
    def context(self, operation: str, **details):
        """Log operation entry/exit with context."""
        ctx = {"operation": operation, **details}
        self.context_stack.append(ctx)
        self.log.info(f"[ENTER] {operation}", extra=ctx)
        try:
            yield
        except Exception as e:
            self.log.error(f"[ERROR] {operation}: {e}", extra=ctx, exc_info=True)
            raise
        finally:
            self.context_stack.pop()
            self.log.info(f"[EXIT] {operation}", extra=ctx)

    def get_context_depth(self) -> int:
        """Get current context stack depth."""
        return len(self.context_stack)


class CachedOperation:
    """Simple cache with TTL for expensive operations."""

    def __init__(self, ttl_seconds: int = 3600):
        self.cache: Dict[str, Any] = {}
        self.ttl = ttl_seconds
        self.timestamps: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        with self._lock:
            if key not in self.cache:
                return None
            if time.time() - self.timestamps[key] > self.ttl:
                del self.cache[key]
                del self.timestamps[key]
                return None
            return self.cache[key]

    def set(self, key: str, value: Any):
        """Set cached value with timestamp."""
        with self._lock:
            self.cache[key] = value
            self.timestamps[key] = time.time()

    @staticmethod
    def cache_key(*args, **kwargs) -> str:
        """Generate cache key from arguments."""
        data = str(args) + str(sorted(kwargs.items()))
        return hashlib.md5(data.encode()).hexdigest()

    def clear_expired(self):
        """Remove all expired entries."""
        current_time = time.time()
        with self._lock:
            expired_keys = [
                k for k, ts in self.timestamps.items()
                if current_time - ts > self.ttl
            ]
            for k in expired_keys:
                del self.cache[k]
                del self.timestamps[k]


class ModuleRegistry:
    """Registry for dynamically loaded modules with plugin support."""

    def __init__(self):
        self._modules: Dict[str, type] = {}

    def register(self, name: str, module_class: type):
        """Register a module class."""
        self._modules[name] = module_class
        log.info(f"[REGISTRY] Registered module: {name}")

    def load_from_directory(self, plugin_dir: Path):
        """Auto-discover and load modules from directory."""
        if not plugin_dir.exists():
            log.debug(f"Plugin directory not found: {plugin_dir}")
            return

        for plugin_file in plugin_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    plugin_file.stem, plugin_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if name.startswith("Niblit"):
                            self.register(name, obj)
            except Exception as e:
                log.debug(f"Failed to load plugin {plugin_file}: {e}")

    def get(self, name: str, *args, **kwargs) -> Optional[Any]:
        """Instantiate a registered module."""
        if name not in self._modules:
            return None
        try:
            return self._modules[name](*args, **kwargs)
        except Exception as e:
            log.debug(f"Failed to instantiate {name}: {e}")
            return None


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

try:
    from modules.utils import safe_call  # noqa: F401
except Exception:
    def safe_call(fn: Callable, *a, **kw) -> Optional[Any]:  # type: ignore[misc]
        """Call fn(*a, **kw) safely, logging and returning None on failure."""
        try:
            return fn(*a, **kw)
        except Exception as e:
            log.debug(f"safe_call failed for {fn}: {e}")
            return None


class _NoopLock:
    """Trivial no-op context manager used as a fallback when an object has no lock."""
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


def sorted_walk(base):
    """os.walk wrapper that yields directories in sorted order."""
    for root, dirs, files in os.walk(base):
        dirs.sort()
        yield root, dirs, files


def parse_intent(text: str) -> Tuple[str, Dict[str, str]]:
    """Parse a user command string into (intent, meta) tuple."""
    t = text.strip().lower()

    exact_commands: Dict[str, Tuple[str, Dict[str, str]]] = {
        "help": ("help", {}), "?": ("help", {}),
        "time": ("time", {}), "what time is it": ("time", {}), "current time": ("time", {}),
        "status": ("status", {}), "health": ("status", {}),
        "toggle-llm on": ("toggle_llm", {"state": "on"}), "llm on": ("toggle_llm", {"state": "on"}),
        "toggle-llm off": ("toggle_llm", {"state": "off"}), "llm off": ("toggle_llm", {"state": "off"}),
        "shutdown": ("shutdown", {}), "exit": ("shutdown", {}), "quit": ("shutdown", {}),
    }
    if t in exact_commands:
        return exact_commands[t]

    if t.startswith("remember "):
        rest = text[9:].strip()
        if ":" in rest:
            k, v = rest.split(":", 1)
            return "remember", {"key": k.strip(), "value": v.strip()}
        return "bad_remember", {}

    for prefix, intent in (("learn about ", "learn"), ("learn ", "learn"),
                            ("ideas about ", "ideas"), ("ideas ", "ideas")):
        if t.startswith(prefix):
            return intent, {"topic": text[len(prefix):].strip()}

    return "chat", {}


class Stub:
    """Placeholder for optional modules that are unavailable."""
    # pylint: disable=too-many-instance-attributes
    def __init__(self, *a, **k):
        pass
    def __getattr__(self, name):
        return lambda *a, **k: None


class _FallbackDB:
    """Minimal no-op stub used when KnowledgeDB is unavailable."""
    def __getattr__(self, name):
        return lambda *a, **kw: None


def safe_import(name: str, default=None, attr: Optional[str] = None):
    """Import a class from the modules/ package, returning default on failure.

    Parameters
    ----------
    name:
        Module sub-name within ``modules/`` (e.g. ``"self_researcher"``).
    default:
        Value returned when the import fails (defaults to :class:`Stub`).
    attr:
        Explicit attribute name to retrieve from the module.  When omitted
        the class name is guessed by title-casing each word in *name*
        (e.g. ``"self_researcher"`` → ``"SelfResearcher"``).  Provide
        *attr* explicitly for names where the guess would be wrong, such as
        ``"llm_adapter"`` → ``attr="LLMAdapter"``.
    """
    try:
        mod = __import__(f"modules.{name}", fromlist=[name])
        cls_name = attr if attr else "".join(x.capitalize() for x in name.split("_"))
        return getattr(mod, cls_name, default)
    except Exception as e:
        log.debug(f"Module {name} not available: {e}")
        return default or Stub


# ============================================================
# SAFE IMPORTS
# ============================================================

try:
    from niblit_memory import KnowledgeDB
except Exception as _e:
    log.debug(f"KnowledgeDB failed to import: {_e}")
    KnowledgeDB = None

try:
    from niblit_memory import LocalDB
except Exception as _e:
    log.debug(f"LocalDB failed to import: {_e}")
    LocalDB = None

try:
    from niblit_brain import NiblitBrain
except Exception as _e:
    log.debug(f"NiblitBrain failed to import: {_e}")
    NiblitBrain = None

try:
    from niblit_router import NiblitRouter
except Exception as _e:
    log.debug(f"NiblitRouter failed to import: {_e}")
    NiblitRouter = None

try:
    from modules import internet_manager  # pylint: disable=unused-import
except Exception as _e:
    log.debug(f"internet_manager failed to import: {_e}")
    internet_manager = None

try:
    from collector_full import Collector
except Exception as _e:
    log.debug(f"Collector failed to import: {_e}")
    Collector = None

try:
    from trainer_full import Trainer, BackgroundTrainer
except Exception as _e:
    log.debug(f"Trainer failed to import: {_e}")
    Trainer = None

try:
    from generator_full import Generator
except Exception as _e:
    log.debug(f"Generator failed to import: {_e}")
    Generator = None

try:
    from healer_full import Healer
except Exception as _e:
    log.debug(f"Healer failed to import: {_e}")
    Healer = None

try:
    from membrane_full import Membrane
except Exception as _e:
    log.debug(f"Membrane failed to import: {_e}")
    Membrane = None

SelfResearcher = safe_import("self_researcher", Stub)
SelfHealer_mod = safe_import("self_healer", Stub)
SelfTeacher_mod = safe_import("self_teacher", Stub)
SelfImplementer = safe_import("self_implementer", Stub)
SelfIdeaGenerator = safe_import("self_idea_generator", Stub)
NiblitPersonality = safe_import("niblit_personality", None)

try:
    from modules.self_idea_implementation import SelfIdeaImplementation
except Exception as _e:
    log.debug(f"SelfIdeaImplementation not available: {_e}")
    SelfIdeaImplementation = None

try:
    from modules.reflect import ReflectModule as Reflect_mod
except Exception as _e:
    log.debug(f"ReflectModule not available: {_e}")
    Reflect_mod = None

try:
    from modules.llm_adapter import LLMAdapter
except Exception as _e:
    log.debug(f"LLMAdapter not available: {_e}")
    LLMAdapter = None

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
    from niblit_env import NiblitEnv
except Exception as _e:
    log.debug(f"NiblitEnv not available: {_e}")
    NiblitEnv = None

try:
    from niblit_identity import NiblitIdentity
except Exception as _e:
    log.debug(f"NiblitIdentity not available: {_e}")
    NiblitIdentity = None

try:
    from niblit_guard import NiblitGuard
except Exception as _e:
    log.debug(f"NiblitGuard not available: {_e}")
    NiblitGuard = None

try:
    from niblit_actions import NiblitActions
except Exception as _e:
    log.debug(f"NiblitActions not available: {_e}")
    NiblitActions = None

try:
    from niblit_hf import NiblitHF
except Exception as _e:
    log.debug(f"NiblitHF not available: {_e}")
    NiblitHF = None

try:
    from niblit_manager import NiblitManager
except Exception as _e:
    log.debug(f"NiblitManager not available: {_e}")
    NiblitManager = None

try:
    from niblit_learning import NiblitLearning
except Exception as _e:
    log.debug(f"NiblitLearning not available: {_e}")
    NiblitLearning = None

try:
    from niblit_io import NiblitIO  # pylint: disable=unused-import
except Exception as _e:
    log.debug(f"NiblitIO not available: {_e}")
    NiblitIO = None

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
    log.debug(f"SLSAGenerator (full) not available: {_e}; trying modules.slsa_generator")
    try:
        from modules.slsa_generator import SLSAGenerator
    except Exception as _e2:
        log.debug(f"SLSAGenerator not available: {_e2}")
        SLSAGenerator = None

try:
    # Prefer the full modular implementation (modules/self_maintenance.py)
    # which has run(), run_with_learning(), and get_history().
    # Fall back to the standalone stub only if the module is absent.
    from modules.self_maintenance import SelfMaintenance
except Exception as _e:
    log.debug(f"modules.self_maintenance not available ({_e}), trying self_maintenance_full")
    try:
        from self_maintenance_full import SelfMaintenance
    except Exception as _e2:
        log.debug(f"SelfMaintenance not available: {_e2}")
        SelfMaintenance = None

try:
    from module_loader import load_modules
except Exception as _e:
    log.debug(f"module_loader not available: {_e}")
    load_modules = None

try:
    from niblit_net import fetch_data, learn_from_data  # pylint: disable=unused-import
except Exception as _e:
    log.debug(f"niblit_net not available: {_e}")
    fetch_data = None
    learn_from_data = None

try:
    from modules.internet_manager import InternetManager
except Exception as _e:
    log.debug(f"InternetManager not available: {_e}")
    InternetManager = None

try:
    from modules.github_code_search import GitHubCodeSearch
except Exception as _e:
    log.debug(f"GitHubCodeSearch not available: {_e}")
    GitHubCodeSearch = None

try:
    from modules.stackoverflow_search import StackOverflowSearch
except Exception as _e:
    log.debug(f"StackOverflowSearch not available: {_e}")
    StackOverflowSearch = None

try:
    from modules.pypi_search import PyPISearch
except Exception as _e:
    log.debug(f"PyPISearch not available: {_e}")
    PyPISearch = None

try:
    from modules.searchcode_search import SearchcodeSearch
except Exception as _e:
    log.debug(f"SearchcodeSearch not available: {_e}")
    SearchcodeSearch = None

try:
    from modules.sqlite_researcher import SQLiteResearcher
except Exception as _e:
    log.debug(f"SQLiteResearcher not available: {_e}")
    SQLiteResearcher = None

try:
    from modules.market_researcher import MarketResearcher
except Exception as _e:
    log.debug(f"MarketResearcher not available: {_e}")
    MarketResearcher = None

try:
    from modules.github_sync import GitHubSync
except Exception as _e:
    log.debug(f"GitHubSync not available: {_e}")
    GitHubSync = None

try:
    from modules.build_scanner import BuildScanner
except Exception as _e:
    log.debug(f"BuildScanner not available: {_e}")
    BuildScanner = None

try:
    from modules.binary_tools import BinaryStudier
except Exception as _e:
    log.debug(f"BinaryStudier not available: {_e}")
    BinaryStudier = None

try:
    from modules.evolve import TERMUX_DEPLOY_PATH as _NIBLIT_BUILD_PATH
except Exception:
    _NIBLIT_BUILD_PATH = Path(
        "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
    )

slsa_manager = None
try:
    from modules.slsa_manager import slsa_manager as sm
    slsa_manager = sm
    log.debug("slsa_manager imported from modules.slsa_manager")
except Exception as _e:
    log.debug(f"slsa_manager not available: {_e}")

# ── Qdrant / VectorStore (shared singleton) ──────────────────────────────────
try:
    from modules.vector_store import VectorStore as _VectorStore
except Exception as _e:
    log.debug(f"VectorStore not available: {_e}")
    _VectorStore = None

# ── Dynamic Topic Enrichment & Qdrant Batch Population ───────────────────────
try:
    from modules.dynamic_topic_manager import DynamicTopicManager as _DynamicTopicManager
except Exception as _e:
    log.debug(f"DynamicTopicManager not available: {_e}")
    _DynamicTopicManager = None  # type: ignore[assignment,misc]

try:
    from modules.qdrant_tools import batch_populate_qdrant as _batch_populate_qdrant
except Exception as _e:
    log.debug(f"qdrant_tools not available: {_e}")
    _batch_populate_qdrant = None  # type: ignore[assignment]

try:
    from modules.background_topic_refresh import start_background_refresh as _start_background_refresh
except Exception as _e:
    log.debug(f"background_topic_refresh not available: {_e}")
    _start_background_refresh = None  # type: ignore[assignment]

# ── BackgroundJobManager (additive) ──────────────────────────────────────────
# Provides daemon-thread management for all periodic background jobs.
# Imported here so niblit_core can wire jobs and expose bg_jobs to the router.
try:
    from modules.background_jobs import bg_jobs as _bg_jobs
    _BG_JOBS_AVAILABLE = True
except Exception as _e:
    log.debug(f"background_jobs not available: {_e}")
    _bg_jobs = None  # type: ignore[assignment]
    _BG_JOBS_AVAILABLE = False

# ── ParameterManager (additive) ───────────────────────────────────────────────
# Hybrid env/DB/remote parameter store with background sync daemon thread.
try:
    from modules.parameter_manager import parameter_manager as _parameter_manager
    _PARAMETER_MANAGER_AVAILABLE = True
except Exception as _e:
    log.debug(f"parameter_manager not available: {_e}")
    _parameter_manager = None  # type: ignore[assignment]
    _PARAMETER_MANAGER_AVAILABLE = False

# ── LeanEngine (additive) ─────────────────────────────────────────────────────
# QuantConnect/LEAN CLI wrapper for non-blocking backtesting and live trading.
try:
    from modules.lean_engine import get_lean_engine as _get_lean_engine
    _LEAN_ENGINE_AVAILABLE = True
except Exception as _e:
    log.debug(f"lean_engine not available: {_e}")
    _get_lean_engine = None  # type: ignore[assignment]
    _LEAN_ENGINE_AVAILABLE = False

# ── LeanDeployEngine (additive) ───────────────────────────────────────────────
# QuantConnect REST API client for cloud project management and live trading.
try:
    from modules.lean_deploy_engine import get_lean_deploy_engine as _get_lean_deploy_engine
    _LEAN_DEPLOY_AVAILABLE = True
except Exception as _lde:
    log.debug(f"lean_deploy_engine not available: {_lde}")
    _get_lean_deploy_engine = None  # type: ignore[assignment]
    _LEAN_DEPLOY_AVAILABLE = False

# Niblit LEAN Algorithms manager — bridges TradingBrain with niblit-lean-algos.
try:
    from modules.lean_algo_manager import get_lean_algo_manager as _get_lean_algo_manager
    _LEAN_ALGO_MANAGER_AVAILABLE = True
except Exception as _lam:
    log.debug(f"lean_algo_manager not available: {_lam}")
    _get_lean_algo_manager = None  # type: ignore[assignment]
    _LEAN_ALGO_MANAGER_AVAILABLE = False

# Cross-repo distributed runtime coordinator (Niblit ↔ cloud ↔ lean).
try:
    from modules.distributed_runtime_coordinator import (
        get_distributed_runtime_coordinator as _get_distributed_runtime_coordinator,
    )
    _DISTRIBUTED_RUNTIME_COORDINATOR_AVAILABLE = True
except Exception as _drc:
    log.debug(f"distributed_runtime_coordinator not available: {_drc}")
    _get_distributed_runtime_coordinator = None  # type: ignore[assignment]
    _DISTRIBUTED_RUNTIME_COORDINATOR_AVAILABLE = False

# ── MarketDataProviders (additive) ────────────────────────────────────────────
# Unified gateway for free market data: yfinance, CCXT, TwelveData, OANDA, Alpaca.
try:
    from modules.market_data_providers import get_market_data_providers as _get_market_data_providers
    _MARKET_DATA_AVAILABLE = True
except Exception as _mde:
    log.debug(f"market_data_providers not available: {_mde}")
    _get_market_data_providers = None  # type: ignore[assignment]
    _MARKET_DATA_AVAILABLE = False

# ── TradingStudy (additive) ───────────────────────────────────────────────────
# Trading study, reflection, and metacognition engine.
try:
    from modules.trading_study import get_trading_study as _get_trading_study
    _TRADING_STUDY_AVAILABLE = True
except Exception as _tse:
    log.debug(f"trading_study not available: {_tse}")
    _get_trading_study = None  # type: ignore[assignment]
    _TRADING_STUDY_AVAILABLE = False

# ── KnowledgeFilter (additive) ────────────────────────────────────────────────
# Filter + summarizer: only genuine research/learning enters the KB.
try:
    from modules.knowledge_filter import get_knowledge_filter as _get_knowledge_filter
    _KNOWLEDGE_FILTER_AVAILABLE = True
except Exception as _kfe:
    log.debug(f"knowledge_filter not available: {_kfe}")
    _get_knowledge_filter = None  # type: ignore[assignment]
    _KNOWLEDGE_FILTER_AVAILABLE = False

# ── HardwareScanner (additive) ────────────────────────────────────────────────
# Cross-platform hardware profiler: CPU arch, RAM, GPU, storage, sensors.
try:
    from modules.hardware_scanner import get_hardware_scanner as _get_hardware_scanner
    _HARDWARE_SCANNER_AVAILABLE = True
except Exception as _hse:
    log.debug(f"hardware_scanner not available: {_hse}")
    _get_hardware_scanner = None  # type: ignore[assignment]
    _HARDWARE_SCANNER_AVAILABLE = False

# ── OSIntegration (additive) ───────────────────────────────────────────────────
# Installs Niblit as a persistent OS service (systemd / Termux:Boot / LaunchAgent / Windows SCM).
try:
    from modules.os_integration import get_os_integration as _get_os_integration
    _OS_INTEGRATION_AVAILABLE = True
except Exception as _oie:
    log.debug(f"os_integration not available: {_oie}")
    _get_os_integration = None  # type: ignore[assignment]
    _OS_INTEGRATION_AVAILABLE = False

# ── PlatformBootstrap (additive) ──────────────────────────────────────────────
# Detects platform type, sets capability flags, configures writable data root.
try:
    from modules.platform_bootstrap import get_platform_bootstrap as _get_platform_bootstrap
    _PLATFORM_BOOTSTRAP_AVAILABLE = True
except Exception as _pbe:
    log.debug(f"platform_bootstrap not available: {_pbe}")
    _get_platform_bootstrap = None  # type: ignore[assignment]
    _PLATFORM_BOOTSTRAP_AVAILABLE = False

# ── Phase-2 Agent architecture (additive) ─────────────────────────────────────
# RuntimeManager + all agents (PlannerAgent, ResearchAgent, CodingAgent,
# TestingAgent, ReflectionAgent, ArchitectureAgent) — wired into core so that
# ── BIOSIntegration (additive) ────────────────────────────────────────────────
# BIOS/UEFI probe + controlled write (GRUB cmdline, EFI vars) on any platform.
try:
    from modules.bios_integration import get_bios_integration as _get_bios_integration
    _BIOS_INTEGRATION_AVAILABLE = True
except Exception as _biose:
    log.debug(f"bios_integration not available: {_biose}")
    _get_bios_integration = None  # type: ignore[assignment]
    _BIOS_INTEGRATION_AVAILABLE = False

# ── KernelIntegration (additive) ──────────────────────────────────────────────
# Kernel version, sysctl, modules, dmesg, temperature sensors.
try:
    from modules.kernel_integration import get_kernel_integration as _get_kernel_integration
    _KERNEL_INTEGRATION_AVAILABLE = True
except Exception as _kie:
    log.debug(f"kernel_integration not available: {_kie}")
    _get_kernel_integration = None  # type: ignore[assignment]
    _KERNEL_INTEGRATION_AVAILABLE = False

# ── DeviceControl (additive) ──────────────────────────────────────────────────
# Sandboxed command exec, process manager, serial/G-code bridge for robots/3D printers.
try:
    from modules.device_control import get_device_control as _get_device_control
    _DEVICE_CONTROL_AVAILABLE = True
except Exception as _dce:
    log.debug(f"device_control not available: {_dce}")
    _get_device_control = None  # type: ignore[assignment]
    _DEVICE_CONTROL_AVAILABLE = False

# ── DeviceMesh (additive) ─────────────────────────────────────────────────────
# LAN discovery, mDNS, SSH spread — Niblit mesh network.
try:
    from modules.device_mesh import get_device_mesh as _get_device_mesh
    _DEVICE_MESH_AVAILABLE = True
except Exception as _dme:
    log.debug(f"device_mesh not available: {_dme}")
    _get_device_mesh = None  # type: ignore[assignment]
    _DEVICE_MESH_AVAILABLE = False

# ── GitHubDeepResearch (additive) ─────────────────────────────────────────────
# Trending repos, tracked-repo PRs/issues, self-improvement proposals from GitHub.
try:
    from modules.github_deep_research import get_github_deep_research as _get_github_deep_research
    _GITHUB_DEEP_AVAILABLE = True
except Exception as _ghde:
    log.debug(f"github_deep_research not available: {_ghde}")
    _get_github_deep_research = None  # type: ignore[assignment]
    _GITHUB_DEEP_AVAILABLE = False

# ── SecurityMembrane (additive) ──────────────────────────────────────────────
try:
    from modules.security_membrane import get_security_membrane as _get_security_membrane
    _SECURITY_MEMBRANE_AVAILABLE = True
except Exception as _sme:
    log.debug(f"security_membrane not available: {_sme}")
    _get_security_membrane = None  # type: ignore[assignment]
    _SECURITY_MEMBRANE_AVAILABLE = False

# ── CyberMembrane (advanced adaptive security layer) ─────────────────────────
try:
    from modules.niblit_cyber_membrane import get_cyber_membrane as _get_cyber_membrane
    _CYBER_MEMBRANE_AVAILABLE = True
except Exception as _cme:
    log.debug(f"niblit_cyber_membrane not available: {_cme}")
    _get_cyber_membrane = None  # type: ignore[assignment]
    _CYBER_MEMBRANE_AVAILABLE = False

# ── DefensiveEvolutionLoop (self-evolving immunity layer) ─────────────────────
try:
    from modules.niblit_defensive_evolution_loop import get_evolution_loop as _get_evolution_loop
    _EVOLUTION_LOOP_AVAILABLE = True
except Exception as _elo:
    log.debug(f"niblit_defensive_evolution_loop not available: {_elo}")
    _get_evolution_loop = None  # type: ignore[assignment]
    _EVOLUTION_LOOP_AVAILABLE = False

# ── EnvStateManager (additive) ───────────────────────────────────────────────
try:
    from modules.env_state import get_env_state_manager as _get_env_state_manager
    _ENV_STATE_AVAILABLE = True
except Exception as _ese:
    log.debug(f"env_state not available: {_ese}")
    _get_env_state_manager = None  # type: ignore[assignment]
    _ENV_STATE_AVAILABLE = False

# ── EnvAdapterRegistry (additive) ────────────────────────────────────────────
try:
    from modules.env_adapter import get_env_adapter_registry as _get_env_adapter_registry
    _ENV_ADAPTER_AVAILABLE = True
except Exception as _eae:
    log.debug(f"env_adapter not available: {_eae}")
    _get_env_adapter_registry = None  # type: ignore[assignment]
    _ENV_ADAPTER_AVAILABLE = False

# ── NiblitRuntime (additive) ─────────────────────────────────────────────────
try:
    from modules.niblit_runtime import get_niblit_runtime as _get_niblit_runtime
    _NIBLIT_RUNTIME_AVAILABLE = True
except Exception as _nre:
    log.debug(f"niblit_runtime not available: {_nre}")
    _get_niblit_runtime = None  # type: ignore[assignment]
    _NIBLIT_RUNTIME_AVAILABLE = False

# Niblit can create, dispatch, and reflect on agent tasks autonomously.
try:
    from core.runtime_manager import RuntimeManager as _RuntimeManager
    _RUNTIME_MANAGER_AVAILABLE = True
except Exception as _e:
    log.debug(f"RuntimeManager not available: {_e}")
    _RuntimeManager = None  # type: ignore[assignment,misc]
    _RUNTIME_MANAGER_AVAILABLE = False

try:
    from agents.planner_agent import PlannerAgent as _PlannerAgent
    from agents.research_agent import ResearchAgent as _ResearchAgent
    from agents.coding_agent import CodingAgent as _CodingAgent
    from agents.testing_agent import TestingAgent as _TestingAgent
    from agents.reflection_agent import ReflectionAgent as _ReflectionAgent
    from agents.architecture_agent import ArchitectureAgent as _ArchitectureAgent
    _PHASE2_AGENTS_AVAILABLE = True
except Exception as _e:
    log.debug(f"Phase-2 agents not available: {_e}")
    _PlannerAgent = _ResearchAgent = _CodingAgent = None  # type: ignore[assignment,misc]
    _TestingAgent = _ReflectionAgent = _ArchitectureAgent = None  # type: ignore[assignment,misc]
    _PHASE2_AGENTS_AVAILABLE = False

# ── NotificationQueue (additive) ─────────────────────────────────────────────
# Global thread-safe notification queue — all background threads push here.
try:
    from core.notification_queue import notif_queue as _global_notif_queue
    _GLOBAL_NOTIF_AVAILABLE = True
except Exception as _e:
    log.debug(f"core.notification_queue not available: {_e}")
    _global_notif_queue = None  # type: ignore[assignment]
    _GLOBAL_NOTIF_AVAILABLE = False

# ── MCP server ────────────────────────────────────────────────────────────────
try:
    from modules.mcp_server import (
        register_flask_routes as _mcp_register_flask_routes,
        attach_core as _mcp_attach_core,
        MCP_ENABLED as _MCP_ENABLED,
    )
    _MCP_AVAILABLE = True
except Exception as _e:
    log.debug(f"MCP server module unavailable: {_e}")
    _MCP_AVAILABLE = False
    _mcp_register_flask_routes = None
    _mcp_attach_core = None
    _MCP_ENABLED = False

ORCHESTRATOR_AVAILABLE = False
RepoAuditor = None
self_heal_main = None
FixGuideGenerator = None

try:
    from tools.repo_audit import RepoAuditor
    from tools.self_heal_auto import main as self_heal_main
    from tools.FixGuideGenerator import FixGuideGenerator
    ORCHESTRATOR_AVAILABLE = True
    log.info("Orchestrator tools loaded successfully")
except Exception as _e:
    log.debug(f"Orchestrator tools not available: {_e}")

# ── HybridQdrantManager (additive) ───────────────────────────────────────────
try:
    from modules.hybrid_qdrant_manager import get_hybrid_manager as _get_hybrid_manager
    _HYBRID_QDRANT_AVAILABLE = True
except Exception as _e:
    log.debug(f"HybridQdrantManager not available: {_e}")
    _get_hybrid_manager = None  # type: ignore[assignment]
    _HYBRID_QDRANT_AVAILABLE = False

# ── SelfMonitor (additive) ────────────────────────────────────────────────────
try:
    from modules.self_monitor import get_self_monitor as _get_self_monitor
    _SELF_MONITOR_AVAILABLE = True
except Exception as _e:
    log.debug(f"SelfMonitor not available: {_e}")
    _get_self_monitor = None  # type: ignore[assignment]
    _SELF_MONITOR_AVAILABLE = False

# ── NiblitKernel (additive) ───────────────────────────────────────────────────
try:
    from modules.niblit_kernel import get_kernel as _get_kernel
    _NIBLIT_KERNEL_AVAILABLE = True
except Exception as _e:
    log.debug(f"NiblitKernel not available: {_e}")
    _get_kernel = None  # type: ignore[assignment]
    _NIBLIT_KERNEL_AVAILABLE = False

# ── NiblitOSKernel (OS abstraction layer) ────────────────────────────────────
try:
    from kernel import get_os_kernel as _get_os_kernel
    _NIBLIT_OS_KERNEL_AVAILABLE = True
except Exception as _e:
    log.debug(f"NiblitOSKernel not available: {_e}")
    _get_os_kernel = None  # type: ignore[assignment]
    _NIBLIT_OS_KERNEL_AVAILABLE = False

# ── ResilienceWrapper (additive) ──────────────────────────────────────────────
try:
    from modules.resilience_wrapper import safe_init as _safe_init, safe_call as _safe_call, wrap_module as _wrap_module
    _RESILIENCE_AVAILABLE = True
except Exception as _e:
    log.debug(f"ResilienceWrapper not available: {_e}")
    _safe_init = None  # type: ignore[assignment]
    _safe_call = None  # type: ignore[assignment]
    _wrap_module = None  # type: ignore[assignment]
    _RESILIENCE_AVAILABLE = False

# ── AIDevLab (additive) ───────────────────────────────────────────────────────
# Self-Evolving AI Development Lab: hypothesis → research → arch → code → bench.
try:
    from modules.ai_dev_lab.lab_controller import AIDevLab as _AIDevLab
    _AI_DEV_LAB_AVAILABLE = True
except Exception as _e:
    log.debug(f"AIDevLab not available: {_e}")
    _AIDevLab = None  # type: ignore[assignment,misc]
    _AI_DEV_LAB_AVAILABLE = False

# ── Observability: AnomalyDetector, MetricsCollector, LogAggregator ──────────
try:
    from distributed_niblit.observability.anomaly_detector import AnomalyDetector as _AnomalyDetector
    _ANOMALY_DETECTOR_AVAILABLE = True
except Exception as _e:
    log.debug(f"AnomalyDetector not available: {_e}")
    _AnomalyDetector = None  # type: ignore[assignment,misc]
    _ANOMALY_DETECTOR_AVAILABLE = False

try:
    from distributed_niblit.observability.metrics_collector import MetricsCollector as _MetricsCollector
    _METRICS_COLLECTOR_AVAILABLE = True
except Exception as _e:
    log.debug(f"MetricsCollector not available: {_e}")
    _MetricsCollector = None  # type: ignore[assignment,misc]
    _METRICS_COLLECTOR_AVAILABLE = False

try:
    from distributed_niblit.observability.log_aggregator import LogAggregator as _LogAggregator
    _LOG_AGGREGATOR_AVAILABLE = True
except Exception as _e:
    log.debug(f"LogAggregator not available: {_e}")
    _LogAggregator = None  # type: ignore[assignment,misc]
    _LOG_AGGREGATOR_AVAILABLE = False

# ── AIOSScheduler (additive) ──────────────────────────────────────────────────
# Priority-queue wrapper around LifecycleEngine; user tasks preempt background ALE.
try:
    from aios_scheduler import AIOSScheduler as _AIOSScheduler, get_aios_scheduler as _get_aios_scheduler
    _AIOS_SCHEDULER_AVAILABLE = True
except Exception as _e:
    log.debug(f"AIOSScheduler not available: {_e}")
    _AIOSScheduler = None  # type: ignore[assignment,misc]
    _get_aios_scheduler = None  # type: ignore[assignment]
    _AIOS_SCHEDULER_AVAILABLE = False

# ── AIOS HAL (additive) ───────────────────────────────────────────────────────
# Unified hardware abstraction layer (bios + hardware_scanner + platform_bootstrap).
try:
    from aios_hal import get_aios_hal as _get_aios_hal
    _AIOS_HAL_AVAILABLE = True
except Exception as _e:
    log.debug(f"aios_hal not available: {_e}")
    _get_aios_hal = None  # type: ignore[assignment]
    _AIOS_HAL_AVAILABLE = False

# ── Global Code Intelligence (additive) ──────────────────────────────────────
try:
    from modules.global_code_intelligence.pattern_graph_builder import PatternGraphBuilder as _PatternGraphBuilder
    _PATTERN_GRAPH_AVAILABLE = True
except Exception as _e:
    log.debug(f"PatternGraphBuilder not available: {_e}")
    _PatternGraphBuilder = None  # type: ignore[assignment,misc]
    _PATTERN_GRAPH_AVAILABLE = False

try:
    from modules.global_code_intelligence.knowledge_reasoner import KnowledgeReasoner as _KnowledgeReasoner
    _KNOWLEDGE_REASONER_AVAILABLE = True
except Exception as _e:
    log.debug(f"KnowledgeReasoner not available: {_e}")
    _KnowledgeReasoner = None  # type: ignore[assignment,misc]
    _KNOWLEDGE_REASONER_AVAILABLE = False

try:
    from modules.global_code_intelligence.architecture_detector import ArchitectureDetector as _ArchitectureDetector
    _ARCH_DETECTOR_AVAILABLE = True
except Exception as _e:
    log.debug(f"ArchitectureDetector not available: {_e}")
    _ArchitectureDetector = None  # type: ignore[assignment,misc]
    _ARCH_DETECTOR_AVAILABLE = False

# ── Knowledge Engine (additive) ───────────────────────────────────────────────
try:
    from modules.knowledge_engine.knowledge_graph_builder import KnowledgeGraphBuilder as _KnowledgeGraphBuilder
    _KNOWLEDGE_GRAPH_AVAILABLE = True
except Exception as _e:
    log.debug(f"KnowledgeGraphBuilder not available: {_e}")
    _KnowledgeGraphBuilder = None  # type: ignore[assignment,misc]
    _KNOWLEDGE_GRAPH_AVAILABLE = False

try:
    from modules.knowledge_engine.repo_scanner import RepoScanner as _RepoScanner
    _REPO_SCANNER_AVAILABLE = True
except Exception as _e:
    log.debug(f"RepoScanner not available: {_e}")
    _RepoScanner = None  # type: ignore[assignment,misc]
    _REPO_SCANNER_AVAILABLE = False

try:
    from modules.knowledge_engine.embedding_pipeline import EmbeddingPipeline as _EmbeddingPipeline
    _EMBEDDING_PIPELINE_AVAILABLE = True
except Exception as _e:
    log.debug(f"EmbeddingPipeline not available: {_e}")
    _EmbeddingPipeline = None  # type: ignore[assignment,misc]
    _EMBEDDING_PIPELINE_AVAILABLE = False

# ── SDAL: NiblitState, EventBus, DecisionEngine ───────────────────────────────
try:
    from modules.niblit_state import NiblitState as _NiblitState, get_niblit_state as _get_niblit_state
    _NIBLIT_STATE_AVAILABLE = True
except Exception as _e:
    log.debug(f"NiblitState not available: {_e}")
    _NiblitState = None  # type: ignore[assignment,misc]
    _get_niblit_state = None  # type: ignore[assignment]
    _NIBLIT_STATE_AVAILABLE = False

try:
    from modules.event_bus import EventBus as _EventBus, get_event_bus as _get_sdal_event_bus
    _SDAL_EVENT_BUS_AVAILABLE = True
except Exception as _e:
    log.debug(f"SDAL EventBus not available: {_e}")
    _EventBus = None  # type: ignore[assignment,misc]
    _get_sdal_event_bus = None  # type: ignore[assignment]
    _SDAL_EVENT_BUS_AVAILABLE = False

try:
    from modules.decision_engine import (
        DecisionEngine as _DecisionEngine,
        get_decision_engine as _get_decision_engine,
    )
    _DECISION_ENGINE_AVAILABLE = True
except Exception as _e:
    log.debug(f"DecisionEngine not available: {_e}")
    _DecisionEngine = None  # type: ignore[assignment,misc]
    _get_decision_engine = None  # type: ignore[assignment]
    _DECISION_ENGINE_AVAILABLE = False

try:
    from modules.evaluation_engine import (
        EvaluationEngine as _EvaluationEngine,
        get_evaluation_engine as _get_evaluation_engine,
    )
    _EVALUATION_ENGINE_AVAILABLE = True
except Exception as _e:
    log.debug(f"EvaluationEngine not available: {_e}")
    _EvaluationEngine = None  # type: ignore[assignment,misc]
    _get_evaluation_engine = None  # type: ignore[assignment]
    _EVALUATION_ENGINE_AVAILABLE = False

try:
    from modules.cognitive_identity import (
        CognitiveIdentity as _CognitiveIdentity,
        get_cognitive_identity as _get_cognitive_identity,
    )
    _COGNITIVE_IDENTITY_AVAILABLE = True
except Exception as _e:
    log.debug(f"CognitiveIdentity not available: {_e}")
    _CognitiveIdentity = None  # type: ignore[assignment,misc]
    _get_cognitive_identity = None  # type: ignore[assignment]
    _COGNITIVE_IDENTITY_AVAILABLE = False

try:
    from modules.meta_engine import (
        MetaEngine as _MetaEngine,
        get_meta_engine as _get_meta_engine,
    )
    _META_ENGINE_AVAILABLE = True
except Exception as _e:
    log.debug(f"MetaEngine not available: {_e}")
    _MetaEngine = None  # type: ignore[assignment,misc]
    _get_meta_engine = None  # type: ignore[assignment]
    _META_ENGINE_AVAILABLE = False

try:
    from modules.policy_optimizer import (
        PolicyOptimizer as _PolicyOptimizer,
        get_policy_optimizer as _get_policy_optimizer,
    )
    _POLICY_OPTIMIZER_AVAILABLE = True
except Exception as _e:
    log.debug(f"PolicyOptimizer not available: {_e}")
    _PolicyOptimizer = None  # type: ignore[assignment,misc]
    _get_policy_optimizer = None  # type: ignore[assignment]
    _POLICY_OPTIMIZER_AVAILABLE = False


def hf_query(prompt: str) -> str:
    """Execute a HuggingFace model query via HFBrain if available."""
    try:
        from modules.hf_brain import HFBrain
        hf = HFBrain(None)
        return hf.ask_single(prompt) or "[No response]"
    except Exception as e:
        log.debug(f"hf_query failed: {e}")
        return f"[HF query failed: {e}]"


# ============================================================
# LOOP TRACER
# ============================================================

class LoopTracer:
    """
    Thread-safe registry that captures structured error records from every
    background loop in Niblit.

    Each record has the shape::

        {
            "loop":      str,           # loop/thread name  (e.g. "HealthLoop")
            "source":    str,           # file that owns the loop
            "ts":        str,           # ISO-8601 timestamp of the error
            "error":     str,           # str(exception)
            "error_type":str,           # type(exception).__name__
            "tb":        str,           # raw traceback string
            "frames": [                 # parsed frame list
                {
                    "file":     str,    # absolute path
                    "lineno":   int,
                    "function": str,
                    "code":     str,    # source line (stripped)
                }
            ],
        }

    Usage inside a loop body::

        try:
            ...loop work...
        except Exception as exc:
            loop_tracer.record("HealthLoop", exc)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._errors: collections.deque = collections.deque(maxlen=500)

    # ----------------------------------------------------------
    # Pre-compiled pattern used in _parse_frames — avoids re-importing
    # `re` and re-compiling the pattern on every call.
    _FRAME_RE = re.compile(r'File "([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)')

    @staticmethod
    def _parse_frames(tb_str: str) -> List[Dict]:
        frames = []
        lines = tb_str.splitlines()
        for i, line in enumerate(lines):
            m = LoopTracer._FRAME_RE.search(line)
            if m:
                code = lines[i + 1].strip() if i + 1 < len(lines) else ""
                frames.append({
                    "file": m.group(1),
                    "lineno": int(m.group(2)),
                    "function": m.group(3),
                    "code": code,
                })
        return frames

    # ----------------------------------------------------------
    def record(self, loop_name: str, exc: Exception) -> None:
        """Record a loop error.  Safe to call from any thread."""
        tb_str = _traceback.format_exc()
        frames = self._parse_frames(tb_str)
        # Use the first (outermost) frame — that is the loop-owner file,
        # e.g. niblit_core.py, niblit_memory.py, lifecycle_engine.py.
        source = frames[0]["file"] if frames else "<unknown>"
        record = {
            "loop": loop_name,
            "source": source,
            "ts": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
            "error_type": type(exc).__name__,
            "tb": tb_str,
            "frames": frames,
        }
        with self._lock:
            self._errors.append(record)
        log.debug(f"[LoopTracer] {loop_name} error recorded: {exc}")

    # ----------------------------------------------------------
    def get_errors(self) -> List[Dict]:
        """Return a snapshot of all recorded errors (thread-safe copy)."""
        with self._lock:
            return list(self._errors)

    # ----------------------------------------------------------
    def clear(self) -> None:
        """Clear all recorded errors."""
        with self._lock:
            self._errors.clear()

    # ----------------------------------------------------------
    def summary(self) -> str:
        """Return a compact human-readable summary."""
        errors = self.get_errors()
        if not errors:
            return "[LoopTracer] No loop errors recorded."
        lines = [f"[LoopTracer] {len(errors)} loop error(s):"]
        for e in errors:
            lines.append(
                f"  loop={e['loop']}  type={e['error_type']}  "
                f"source={e['source']}  ts={e['ts']}"
            )
            lines.append(f"    {e['error']}")
        return "\n".join(lines)


# Singleton instance shared across niblit_core and importers
loop_tracer = LoopTracer()


# ============================================================
# CORE
# ============================================================

class NiblitCore:
    """
    Production-Grade NiblitCore: Unified Autonomous AI Runtime with Full Self-Improvement

    Integrates 40+ components with:
    - 17 enterprise production improvements
    - 10 self-improvement modules
    - Autonomous Learning Engine (background learning when idle)

    Architecture:
    User Input → CommandRegistry → Router → Improvements → Autonomous Learning → LLM

    Compatible with main.py, server.py, and app.py.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, config: Optional[NiblitConfig] = None, memory_path: Optional[str] = None):
        """Initialize NiblitCore with optional config."""
        # pylint: disable=too-many-statements
        # Configuration
        self.config = config or NiblitConfig.from_env()
        if memory_path:
            self.config.memory_path = Path(memory_path)

        # Logging & Metrics
        self.logger = NiblitLogger("NiblitCore")
        self.metrics = PerformanceMetrics()
        self.startup_report = StartupReport()

        # Module registry for plugins
        self.module_registry = ModuleRegistry()

        # Caching
        self.research_cache = CachedOperation(ttl_seconds=3600)
        self.internet_cache = CachedOperation(ttl_seconds=1800)

        # Threading
        self._lock = threading.RLock()
        self._shutdown_event = threading.Event()
        self._background_threads: List[threading.Thread] = []
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_tasks: set = set()

        # State
        self.start_ts = time.time()
        self._routing = False
        self._orchestration_running = False
        self.llm_enabled = True
        self.running = True
        self.orchestrator_available = ORCHESTRATOR_AVAILABLE

        # Last dump check time
        self._last_dump_check = time.time()
        self._dump_loop_count = 0

        # Loop visibility and notification state
        self._loops_verbose: bool = True
        self._notifications: collections.deque = collections.deque(maxlen=50)
        self._show_routing: bool = False

        # SLSA state
        self.slsa_engine = None
        self.slsa_thread = None

        # Phased-initialization state
        # "pending"  — deferred thread not yet started
        # "running"  — Phase-1 (heavy modules) loading in background
        # "complete" — Phase-1 finished successfully
        # "failed"   — Phase-1 raised an unhandled exception
        self._deferred_init_phase: str = "pending"
        self._deferred_init_event: threading.Event = threading.Event()

        # Live init-progress queue — main.py drains this while blocking on
        # wait_for_ready() so the user sees real-time sub-phase progress
        # messages instead of a silent wait.
        self._init_progress_queue: _queue_mod.Queue = _queue_mod.Queue()
        self._current_init_phase: str = ""

        # Wake-lock: keeps CPU alive when screen is off / Termux is in background
        self.wakelock: Optional["TermuxWakeLock"] = (
            TermuxWakeLock() if TermuxWakeLock is not None else None
        )

        # NEW: Production improvements
        self.command_registry: Optional[CommandRegistry] = None
        self.task_coordinator: Optional[AsyncTaskCoordinator] = None
        self.event_store: Optional[EventStore] = None
        self.rate_limiter: Optional[RateLimiter] = None
        self.telemetry: Optional[TelemetryCollector] = None
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.connection_pool: Optional[ConnectionPool] = None
        self.cache_strategy: Optional[CacheStrategy] = None
        self.learning_batcher: Optional[LearningBatcher] = None
        self.plugin_manager: Optional[PluginManager] = None
        self.alert_manager: Optional[AlertManager] = None

        # NEW: 10 Self-Improvement Modules
        self.improvements: Optional[ImprovementIntegrator] = None
        self.parallel_learner: Optional[ParallelLearner] = None
        self.reasoning_engine: Optional[ReasoningEngine] = None
        self.gap_analyzer: Optional[GapAnalyzer] = None
        self.synthesizer: Optional[KnowledgeSynthesizer] = None
        self.predictor: Optional[PredictionEngine] = None
        self.memory_optimizer: Optional[MemoryOptimizer] = None
        self.adaptive_learning: Optional[AdaptiveLearning] = None
        self.metacognition: Optional[Metacognition] = None
        self.collaborative_learner: Optional[CollaborativeLearner] = None
        self.agentic_workflows: Optional[AgenticWorkflow] = None
        self.enterprise_utility: Optional[EnterpriseUtility] = None
        self.multimodal_intelligence: Optional[MultimodalIntelligence] = None

        # NEW: Autonomous Learning Engine
        self.autonomous_engine: Optional[AutonomousLearningEngine] = None
        # NEW: Trading Brain
        self.trading_brain: Optional["TradingBrain"] = None
        # NEW: FilteredSwingTraderV3 — continuous trend re-entry model (additive)
        self.swing_trader_v3: Optional[Any] = None
        # NEW: BackgroundTrainer — non-blocking daemon training loop (additive)
        self.background_trainer: Optional[Any] = None
        # NEW: ALECheckpointManager — persistent ALE state across restarts (additive)
        self.ale_checkpoint: Optional[Any] = None
        # NEW: GradedCurriculum — education-system learning progression (additive)
        self.graded_curriculum: Optional[Any] = None
        # NEW: LanguageModule — vocabulary, grammar, subject seeds, response formatter
        self.language_module: Optional[Any] = None
        # NEW: AcademicStudyModule — subject-structured study sessions
        self.academic_study: Optional[Any] = None
        # NEW: PhasedResearchEngine — 3-phase sequential research
        self.phased_research_engine: Optional[Any] = None

        # NEW: Live Updater + Structural Awareness
        self.live_updater: Optional[LiveUpdater] = None
        self.structural_awareness: Optional[StructuralAwareness] = None

        # NEW: Code capabilities + enhanced filesystem + software studier
        self.code_generator: Optional[CodeGenerator] = None
        self.code_compiler: Optional[CodeCompiler] = None
        self.code_error_fixer = None
        self.file_manager: Optional[FileManager] = None
        self.software_studier: Optional[SoftwareStudier] = None
        self.evolve_engine: Optional[EvolveEngine] = None

        # NEW: GitHub sync and build scanner (self-knowledge + self-update to GitHub)
        self.github_sync = None
        self.build_scanner = None
        self.binary_studier = None
        self.builds_integrator: Optional[Any] = None

        # NEW: SelfIdeaImplementation (research + implement + SLSA + memory)
        self.idea_implementation = None

        # NEW: Deployment bridge, autonomous network, module autonomy
        self.deployment_bridge: Optional[Any] = None
        self.autonomous_network: Optional[Any] = None
        self.module_autonomy: Optional[Any] = None

        # Personality layer (conversational AI)
        self.personality = None

        # Phase-initialised attributes declared here to satisfy W0201
        self.db = None
        self.memory = None
        self.env = None
        self.identity = None
        self.guard = None
        self.internet = None
        self.github_code_search = None
        self.stackoverflow_search = None
        self.pypi_search = None
        self.searchcode_search = None
        self.sqlite_researcher = None
        self.market_researcher = None
        self.fused_memory = None
        self.vector_store = None
        self.semantic_agent = None
        self.claude_engine = None
        self.reflect = None
        self.self_healer = None
        self.llm = None
        # Dynamic topic enrichment / Qdrant batch population
        self.dynamic_topic_manager: Optional[Any] = None
        self._topic_refresh_thread: Optional[Any] = None
        self._topic_refresh_stop_event: Optional[Any] = None
        self.trainer = None
        self.self_teacher = None
        self.self_implementer = None
        self.collector = None
        self.modules = None
        # ── Additive: background job manager and parameter manager ─────────
        # Expose the module-level singletons on the core so the router and
        # other modules can reach them via core.bg_jobs / core.parameter_manager
        self.bg_jobs: Optional[Any] = _bg_jobs if _BG_JOBS_AVAILABLE else None
        self.parameter_manager: Optional[Any] = _parameter_manager if _PARAMETER_MANAGER_AVAILABLE else None
        # ── Additive: LEAN engine ─────────────────────────────────────────
        self.lean_engine: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: HybridQdrantManager ────────────────────────────────
        self.hybrid_qdrant: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: SelfMonitor ────────────────────────────────────────
        self.self_monitor: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: NiblitKernel ───────────────────────────────────────
        self.kernel: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: NiblitOSKernel (OS abstraction layer) ─────────────
        self.os_kernel: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: KnowledgeDigest ────────────────────────────────────
        self.knowledge_digest: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: KnowledgeFilter ────────────────────────────────────
        self.knowledge_filter: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: LeanDeployEngine (QuantConnect REST API) ────────────
        self.lean_deploy_engine: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: LeanAlgoManager (niblit-lean-algos bridge) ───────────
        self.lean_algo_manager: Optional[Any] = None   # initialised in _init_optional_services
        # ── Additive: distributed runtime coordinator (Niblit/cloud/lean) ──
        self.runtime_coordinator: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: MarketDataProviders (multi-provider free data) ──────
        self.market_data_providers: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: TradingStudy (study/reflect/metacognition) ──────────
        self.trading_study: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: HardwareScanner (cross-platform hardware profiler) ──
        self.hardware_scanner: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: OSIntegration (install Niblit as OS service) ────────
        self.os_integration: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: PlatformBootstrap (platform type + capabilities) ────
        self.platform_bootstrap: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: BIOS/UEFI integration ──────────────────────────────────
        self.bios_integration: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Kernel integration ─────────────────────────────────────
        self.kernel_integration: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Device control (cmd exec, serial, G-code) ──────────────
        self.device_control: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Device mesh (LAN discovery + spread) ───────────────────
        self.device_mesh: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: GitHub deep research (trending + tracked repos) ─────────
        self.github_deep_research: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Security membrane ──────────────────────────────────────
        self.security_membrane: Optional[Any] = None  # initialised in _init_optional_services
        self.cyber_membrane: Optional[Any] = None    # advanced adaptive cyber membrane
        self.evolution_loop: Optional[Any] = None    # defensive evolution / self-attack loop
        # ── Phase 20: Temporal Coherence Layer ───────────────────────────────
        # Governs per-tier adaptation cadence and cross-timescale staleness.
        try:
            from modules.temporal_coherence import get_temporal_coherence_layer
            self._tcl = get_temporal_coherence_layer()
        except Exception:
            self._tcl = None
        self._last_feedback_arbitration: Optional[Dict[str, Any]] = None
        # ── Additive: Cross-environment state manager ─────────────────────────
        self.env_state_manager: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Environment adapter registry ────────────────────────────
        self.env_adapter_registry: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Niblit self-improving runtime environment ───────────────
        self.niblit_runtime: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Phase-2 agent architecture (RuntimeManager + agents) ─
        self.runtime_manager: Optional[Any] = None  # initialised in _init_optional_services
        self.phase2_agents: dict = {}  # {task_type: agent_instance}
        # ── Additive: Game engine ─────────────────────────────────────────
        self.game_engine: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Universal file manager ─────────────────────────────
        self.universal_file_manager: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: CivilizationController (STACA) ─────────────────────
        self.civilization: Optional[Any] = None  # initialised in _init_optional_services
        self.self_improvement_orchestrator: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Cognitive Kernel v2 (local reasoning, no LLM) ──────
        self.kernel_v2: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: MWDS MemoryStore (adaptive memory weighting) ───────
        self.memory_store: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: SyncEngine (LCSP v1 local↔cloud sync) ──────────────
        self.sync_engine: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: Cognitive Kernel v3 (fused v1+v2+KCB+agents+reward) ─
        self.kernel_v3: Optional[Any] = None  # initialised in _init_optional_services
        self.cognitive_graph_kernel: Optional[Any] = None  # initialised in _init_optional_services
        self.msg_layer: Optional[Any] = None  # initialised in _init_optional_services
        # ── Additive: SDAL — NiblitState, EventBus, DecisionEngine ───────────
        self.niblit_state: Optional[Any] = None    # initialised in _init_optional_services
        self.sdal_event_bus: Optional[Any] = None  # initialised in _init_optional_services
        self.decision_engine: Optional[Any] = None # initialised in _init_optional_services
        self.evaluation_engine: Optional[Any] = None  # initialised in _init_optional_services
        self.cognitive_identity: Optional[Any] = None  # initialised in _init_optional_services
        self.meta_engine: Optional[Any] = None  # initialised in _init_optional_services
        self.policy_optimizer: Optional[Any] = None  # initialised in _init_optional_services
        self.hf = None
        self.hf_brain = None  # alias to brain.hf_brain; tracked by component_report
        self.researcher = None
        self.self_researcher = None
        self.brain = None
        self.router = None
        self.niblit_hf = None
        self.learning = None
        self.tasks = None
        self.idea_generator = None
        self.network = None
        self.sensors = None
        self.voice = None
        self.actions = None
        self.manager = None
        self.membrane = None
        self.healer_obj = None
        self.generator = None
        self.self_maintenance = None
        self.slsa_manager = None
        self.lifecycle = None
        self.serpex_research_agent = None
        self.scrapy_research_agent = None

        log.info("✨ Booting Niblit (Phase 0 — fast start)...")

        try:
            if self.config.enable_improvements:
                self._init_improvements()

            # Phase 0: critical-path synchronous init (< 1 second)
            # DB, identity, internet — no model loads.
            self._initialize_core()

            # Minimal router: NiblitRouter accepts core itself as brain.
            # All router code-paths guard with ``if self.brain:`` so it
            # degrades gracefully until Phase 1 finishes.
            if NiblitRouter and self.db is not None:
                try:
                    self.router = NiblitRouter(self, self.db, self)
                    self.router.start()
                    log.info("✅ NiblitRouter (Phase 0) ready")
                except Exception as _re:
                    log.debug("Minimal router init failed: %s", _re)

            # Background health/trainer/research loops start now; they
            # guard all component access with getattr(..., None) so
            # they tolerate None components during Phase 1.
            self._start_background_services()

            if self.startup_report.is_healthy():
                log.info("✅ NIBLIT PHASE 0 READY — heavy modules loading in background")
            else:
                log.warning(f"⚠️ Degraded Phase-0 startup: {self.startup_report.summary()}")

            # Phase 1: all heavy modules load in a daemon thread.
            self._deferred_thread: Optional[threading.Thread] = threading.Thread(
                target=self._deferred_init,
                name="DeferredInitThread",
                daemon=True,
            )
            self._deferred_thread.start()

        except Exception as e:
            log.error(f"Fatal initialization error: {e}", exc_info=True)
            raise

    # ============================
    # IMPROVEMENT INITIALIZATION
    # ============================

    def _init_improvements(self):
        """Initialize all production improvements."""
        # pylint: disable=too-many-branches,too-many-statements
        log.info("[IMPROVEMENTS] Initializing 17 production enhancements...")

        try:
            # 1. CommandRegistry
            if CommandRegistry:
                self.command_registry = CommandRegistry()
                self._register_commands()
                log.info("[IMPROVEMENTS] ✅ CommandRegistry initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] CommandRegistry failed: {e}")

        try:
            # 2. AsyncTaskCoordinator
            if AsyncTaskCoordinator:
                self.task_coordinator = AsyncTaskCoordinator()
                log.info("[IMPROVEMENTS] ✅ AsyncTaskCoordinator initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] AsyncTaskCoordinator failed: {e}")

        try:
            # 3. EventStore
            if EventStore:
                self.event_store = EventStore(Path("./events.jsonl"))
                log.info("[IMPROVEMENTS] ✅ EventStore initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] EventStore failed: {e}")

        try:
            # 4. RateLimiter
            if RateLimiter:
                self.rate_limiter = RateLimiter(max_requests_per_sec=100)
                log.info("[IMPROVEMENTS] ✅ RateLimiter initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] RateLimiter failed: {e}")

        try:
            # 5. TelemetryCollector
            if TelemetryCollector:
                self.telemetry = TelemetryCollector()
                log.info("[IMPROVEMENTS] ✅ TelemetryCollector initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] TelemetryCollector failed: {e}")

        try:
            # 6. CircuitBreakers
            self.circuit_breakers["brain"] = CircuitBreaker(failure_threshold=5)
            self.circuit_breakers["router"] = CircuitBreaker(failure_threshold=5)
            self.circuit_breakers["internet"] = CircuitBreaker(failure_threshold=5)
            log.info("[IMPROVEMENTS] ✅ CircuitBreakers initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] CircuitBreakers failed: {e}")

        try:
            # 7. ConnectionPool
            if ConnectionPool:
                self.connection_pool = ConnectionPool()
                log.info("[IMPROVEMENTS] ✅ ConnectionPool initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] ConnectionPool failed: {e}")

        try:
            # 8. CacheStrategy
            if CacheStrategy:
                self.cache_strategy = CacheStrategy()
                log.info("[IMPROVEMENTS] ✅ CacheStrategy initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] CacheStrategy failed: {e}")

        try:
            # 9. LearningBatcher
            if LearningBatcher:
                self.learning_batcher = LearningBatcher(batch_size=32, flush_interval_seconds=5)
                log.info("[IMPROVEMENTS] ✅ LearningBatcher initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] LearningBatcher failed: {e}")

        try:
            # 10. PluginManager
            if PluginManager:
                self.plugin_manager = PluginManager()
                log.info("[IMPROVEMENTS] ✅ PluginManager initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] PluginManager failed: {e}")

        try:
            # 11. AlertManager
            if AlertManager:
                self.alert_manager = AlertManager()
                log.info("[IMPROVEMENTS] ✅ AlertManager initialized")
        except Exception as e:
            log.warning(f"[IMPROVEMENTS] AlertManager failed: {e}")

        log.info("[IMPROVEMENTS] ✅ 17 production enhancements initialized")

    # ============================
    # PHASED INIT: DEFERRED THREAD
    # ============================

    # Default per-layer timeout (seconds). Override via NIBLIT_LAYER_INIT_TIMEOUT.
    # If a layer hangs past this deadline the layer is marked degraded and the
    # next layer starts immediately — the stalled layer thread continues as daemon.
    _INIT_LAYER_TIMEOUT_DEFAULT: float = 90.0
    # Layer 5 (optional/extended services) can legitimately run longer, but 10
    # minutes feels "stuck" in interactive startup. Keep a tighter default and
    # allow explicit override via NIBLIT_LAYER5_INIT_TIMEOUT.
    _INIT_LAYER5_TIMEOUT_DEFAULT: float = 120.0

    def _init_with_timeout(self, layer_fn, layer_name: str, timeout: float = 0) -> bool:
        """Run *layer_fn* in a daemon thread; continue if it exceeds *timeout* seconds.

        This prevents a single stalled initialisation step (e.g. a Qdrant
        connection attempt, a model download, or a sluggish SQLite WAL open)
        from blocking all subsequent layers.

        The stalled thread keeps running as a daemon and may eventually complete,
        setting the expected ``self.*`` attributes.  All later layers already use
        ``getattr(self, 'attr', None)`` patterns, so a temporarily-absent
        attribute degrades gracefully.

        Returns ``True`` if the layer completed within timeout, ``False`` if it
        timed out or raised an unhandled exception.
        """
        _timeout = timeout or self._INIT_LAYER_TIMEOUT_DEFAULT
        try:
            _timeout = float(os.environ.get("NIBLIT_LAYER_INIT_TIMEOUT", _timeout))
        except (ValueError, TypeError):
            pass

        result: list = [None]
        exc_holder: list = [None]

        def _target() -> None:
            try:
                layer_fn()
                result[0] = True
            except Exception as _exc:  # noqa: BLE001
                exc_holder[0] = _exc

        t = threading.Thread(target=_target, daemon=True, name=f"niblit-layer-{layer_name}")
        t.start()
        t.join(timeout=_timeout)

        if t.is_alive():
            msg = (
                f"⚠️ [Layer {layer_name}] init timed out after {int(_timeout)}s — "
                "continuing without it (still loading in background)"
            )
            log.warning("[DEFERRED-INIT] %s", msg)
            self._push_init_progress(msg)
            return False

        if exc_holder[0] is not None:
            log.error("[DEFERRED-INIT] Layer '%s' raised: %s", layer_name, exc_holder[0])
            return False

        return bool(result[0])

    def _deferred_init(self) -> None:
        """Phase-1 background initialization.

        Runs :meth:`_initialize_modules` (VectorStore / HFBrain / ALE /
        CivilizationController / trading systems / 60+ optional services)
        inside a daemon thread so the CLI is available immediately after
        Phase 0 completes.

        Status is tracked via ``self._deferred_init_phase``:
        ``"pending"`` → ``"running"`` → ``"complete"`` / ``"failed"``
        """
        self._deferred_init_phase = "running"
        log.info("[DEFERRED-INIT] Phase 1 starting — heavy modules loading in background...")
        try:
            self._initialize_modules()

            self._deferred_init_phase = "complete"
            self._deferred_init_event.set()

            ready_count = sum(
                1 for r in self.startup_report.results.values()
                if r.get("status") == "ready"
            )
            total_count = len(self.startup_report.results)
            msg = (
                f"✅ Background init complete — {ready_count}/{total_count} components ready"
            )
            log.info("[DEFERRED-INIT] %s", msg)

            # Register core with NiblitKernel now that kernel is available.
            if getattr(self, "kernel", None):
                try:
                    self.kernel.register_module("NiblitCore", self)
                    self.kernel.update_self_identity("core_initialized", True)
                    self.kernel.log_improvement(
                        "NiblitCore fully initialized with kernel, hybrid-qdrant, and self-monitor",
                        category="init",
                    )
                except Exception:
                    pass

            # Push completion notification — user sees it after pressing Enter.
            try:
                from core.notification_queue import notif_queue as _nq
                _nq.push(msg)
            except Exception:
                pass
            try:
                if self._notifications is not None:
                    self._notifications.append(msg)
            except Exception:
                pass

        except Exception as exc:
            self._deferred_init_phase = "failed"
            self._deferred_init_event.set()
            log.error("[DEFERRED-INIT] Phase 1 failed: %s", exc, exc_info=True)
            _fail_msg = f"⚠️ Background init failed: {exc}"
            try:
                from core.notification_queue import notif_queue as _nq
                _nq.push(_fail_msg)
            except Exception:
                pass
            try:
                if self._notifications is not None:
                    self._notifications.append(_fail_msg)
            except Exception:
                pass

    def wait_for_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until Phase-1 deferred init completes (or *timeout* seconds).

        Returns ``True`` if Phase-1 finished successfully, ``False`` on
        timeout or failure.  Callers that need LLM / ALE / vector-store
        before acting (e.g. one-shot scripts, integration tests) should
        call this first.

        Args:
            timeout: Maximum seconds to wait.  ``None`` waits indefinitely.

        Returns:
            ``True`` if Phase-1 init completed successfully, ``False`` otherwise.
        """
        if self._deferred_init_phase in ("complete", "failed"):
            return self._deferred_init_phase == "complete"
        self._deferred_init_event.wait(timeout=timeout)
        return self._deferred_init_phase == "complete"

    def _push_init_progress(self, msg: str) -> None:
        """Push a sub-phase progress message to the live init-progress queue.

        Called by :meth:`_initialize_modules` at the start and end of each
        sub-phase so that the caller of :meth:`wait_for_ready` (e.g. main.py)
        can drain the queue and display real-time loading messages instead of
        silently blocking.

        The message is also written at INFO level and forwarded to the
        notification queue so it can appear in the CLI after the user presses
        Enter once the interactive shell opens.
        """
        self._current_init_phase = msg
        try:
            self._init_progress_queue.put_nowait(msg)
        except Exception:
            pass
        # Also forward to the background notification queue so it appears
        # when the CLI is already open (e.g. NIBLIT_SKIP_INIT_WAIT=1).
        try:
            from core.notification_queue import notif_queue as _nq
            _nq.push(msg)
        except Exception:
            pass
        log.info("[INIT-PROGRESS] %s", msg)

    def _register_commands(self):
        """Register commands with CommandRegistry."""
        # pylint: disable=too-many-statements
        if not self.command_registry:
            return

        # Core commands (no LLM)
        self.command_registry.register(
            "help", self._cmd_help, "Show the complete Niblit command reference", "core", priority=100
        )
        self.command_registry.register(
            "status", self._cmd_status, "Show overall system status (modules, threads, memory)", "core", priority=100
        )
        self.command_registry.register(
            "health", self._cmd_health, "Run a comprehensive health check across all subsystems", "core", priority=100
        )
        # Phase 21: Temporal Coherence Layer inspection command
        self.command_registry.register(
            "coherence", self._cmd_coherence,
            "Show Temporal Coherence Layer epoch, tier clocks, and barrier states (Phase 21)",
            "core", priority=99
        )
        self.command_registry.register(
            "metrics", self._cmd_metrics, "Show real-time performance metrics (CPU, RAM, latency)", "core", priority=100
        )
        self.command_registry.register(
            "time", self._cmd_time, "Display current date and time", "core", priority=100
        )

        # Autonomous Learning Commands
        self.command_registry.register(
            "autonomous-learn start", self._cmd_autonomous_start,
            "Resume the 28-step Autonomous Learning Engine (ALE) background loop", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn stop", self._cmd_autonomous_stop,
            "Pause ALE (all stored knowledge is retained)", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn status", self._cmd_autonomous_status,
            "View ALE cycle count, current topic, step timings, and KB facts", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn add-topic", self._cmd_autonomous_add_topic,
            "Inject a new research topic into the ALE rotation queue", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn code-status", self._cmd_autonomous_code_status,
            "Show ALE code-generation literacy loop status (langs, last file)", "autonomous", priority=98
        )

        # Knowledge recall & acquired data commands
        self.command_registry.register(
            "recall", self._cmd_recall,
            "Full-text search across KnowledgeDB facts for any stored topic", "knowledge", priority=95
        )
        self.command_registry.register(
            "acquired data", self._cmd_acquired_data,
            "Browse all facts acquired by the Autonomous Learning Engine", "knowledge", priority=95
        )
        self.command_registry.register(
            "knowledge stats", self._cmd_knowledge_stats,
            "KnowledgeDB statistics: fact counts, top tags, ALE step breakdown", "knowledge", priority=95
        )
        self.command_registry.register(
            "ale processes", self._cmd_ale_process_awareness,
            "Describe all 28 ALE pipeline steps with data-flow and status", "knowledge", priority=95
        )

        # SLSA commands
        self.command_registry.register(
            "slsa-status", self._cmd_slsa_status,
            "Show SLSA engine running state and last artifact built", "slsa", priority=90
        )
        self.command_registry.register(
            "start_slsa", self._cmd_slsa_start,
            "Start SLSA knowledge-artifact generation (optional topic list)", "slsa", priority=90
        )
        self.command_registry.register(
            "stop_slsa", self._cmd_slsa_stop,
            "Stop the SLSA background loop", "slsa", priority=90
        )
        self.command_registry.register(
            "restart_slsa", self._cmd_slsa_restart,
            "Restart SLSA with an updated topic list", "slsa", priority=90
        )

        # Brain commands (use internet, NOT LLM)
        self.command_registry.register(
            "self-research", self._cmd_self_research,
            "SelfResearcher: Serpex (1) → Searchcode (2) → Engine (3) → Internet (4)", "brain", priority=85
        )
        self.command_registry.register(
            "self-idea", self._cmd_self_idea,
            "Generate an idea via SelfIdeaGenerator and auto-implement it", "brain", priority=85
        )
        self.command_registry.register(
            "reflect", self._cmd_reflect,
            "Run ReflectModule on text and store reflection in KnowledgeDB", "brain", priority=85
        )
        self.command_registry.register(
            "self-implement", self._cmd_self_implement,
            "Enqueue an implementation plan directly to SelfImplementer", "brain", priority=85
        )
        self.command_registry.register(
            "self-teach", self._cmd_self_teach,
            "SelfTeacher: research → store in niblit_memory → feed learner → reflect", "brain", priority=85
        )
        self.command_registry.register(
            "idea-implement", self._cmd_idea_implement,
            "Full pipeline: generate idea → implement → compile → store in niblit_memory", "brain", priority=85
        )

        # Internet commands
        self.command_registry.register(
            "search", self._cmd_search,
            "Live internet search via SerpEx → DuckDuckGo fallback", "internet", priority=80
        )
        self.command_registry.register(
            "summary", self._cmd_summary,
            "Fetch a concise web summary and store it in KnowledgeDB", "internet", priority=80
        )

        # Orchestrator commands
        if ORCHESTRATOR_AVAILABLE:
            self.command_registry.register(
                "orchestrate audit", self._run_audit,
                "Run a full repository audit (imports, wiring, missing symbols)", "orchestrator", priority=70
            )
            self.command_registry.register(
                "orchestrate pipeline", self._run_orchestration_pipeline,
                "Run the complete full-upgrade pipeline end-to-end", "orchestrator", priority=70
            )

        # Diagnostic / tester commands
        self.command_registry.register(
            "run-diagnostics", self._cmd_run_diagnostics,
            "Execute the full Niblit diagnostic suite across all subsystems", "diagnostics", priority=65
        )
        self.command_registry.register(
            "run-live-test", self._cmd_run_live_test,
            "Run the interactive live command tester (smoke-tests all routes)", "diagnostics", priority=65
        )

        # Structural awareness commands — short-form aliases
        self.command_registry.register(
            "sa-structure", self._cmd_sa_structure,
            "Full structural inventory: modules, adapters, engines, memory", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-threads", self._cmd_sa_threads,
            "List every active thread with name, state, and daemon flag", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-loops", self._cmd_sa_loops,
            "Show all background loops with interval and running state", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-modules", self._cmd_sa_modules,
            "List all loaded Python modules and their wiring status", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-commands", self._cmd_sa_commands,
            "Enumerate every registered command with handler and priority", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-dashboard", self._cmd_sa_dashboard,
            "Full runtime dashboard: threads, loops, memory, ALE, modules", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-flow", self._cmd_sa_flow,
            "Explain how CLI routing, background loops, and memory all connect", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-resources", self._cmd_sa_resources,
            "Show RAM usage, CPU percent, and process uptime", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-awareness", self._cmd_sa_awareness,
            "All structural awareness in one view", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-scripts", self._cmd_sa_scripts,
            "List every repo script with its function", "structural_awareness", priority=74
        )
        self.command_registry.register(
            "deploy-bridge", lambda t="": self._cmd_deploy_bridge(t),
            "Cross-deployment state bridge: save/load/status", "deployment", priority=60
        )
        self.command_registry.register(
            "autonomous-network", lambda t="": self._cmd_autonomous_network(t),
            "Autonomous network builder: status/start/stop/reflect", "network", priority=60
        )
        self.command_registry.register(
            "module-autonomy", lambda t="": self._cmd_module_autonomy(t),
            "Module autonomy framework: status/start/stop/module", "autonomy", priority=60
        )

        # Extended autonomous learning commands
        self.command_registry.register(
            "autonomous-learn self-learn", self._cmd_autonomous_self_learn,
            "Run structural self-learn sequence", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn evolve-sequence", self._cmd_autonomous_evolve_sequence,
            "Run structured evolve sequence", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn command-awareness", self._cmd_autonomous_command_awareness,
            "Catalogue all commands (ALE Step 13)", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn command-exec", self._cmd_autonomous_command_exec,
            "Execute safe diagnostic commands (ALE Step 14)", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn topic-seed", self._cmd_autonomous_topic_seed,
            "Derive & seed new topics to ALE + SLSA + KB queue (ALE Step 15)", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn serpex-research", self._cmd_autonomous_serpex_research,
            "Run ALE Step 27: Serpex validated web research with relevance filter", "autonomous", priority=97
        )
        self.command_registry.register(
            "autonomous-learn serpex-search", self._cmd_autonomous_serpex_search,
            "Live Serpex web search with relevance filter (pass query after command)", "autonomous", priority=97
        )

        # GitHub sync commands
        self.command_registry.register(
            "github status", self._cmd_github_status,
            "Git status of Niblit build directory", "github", priority=85
        )
        self.command_registry.register(
            "github pull", self._cmd_github_pull,
            "Pull latest changes from GitHub", "github", priority=85
        )
        self.command_registry.register(
            "github push", self._cmd_github_push,
            "Push self-updates to GitHub", "github", priority=85
        )
        self.command_registry.register(
            "github log", self._cmd_github_log,
            "Show recent git commits", "github", priority=85
        )

        # Build scanner commands
        self.command_registry.register(
            "scan build", self._cmd_scan_build,
            "Scan Niblit build directory", "build", priority=85
        )
        self.command_registry.register(
            "read build file", self._cmd_read_build_file,
            "Read a file from the Niblit build directory", "build", priority=85
        )
        self.command_registry.register(
            "build summary", self._cmd_build_summary,
            "Summary of the Niblit build directory", "build", priority=85
        )
        self.command_registry.register(
            "build path", self._cmd_build_path,
            "Show Niblit build path and sync status", "build", priority=85
        )

        # Tree / filesystem commands
        self.command_registry.register(
            "tree scan", self._cmd_tree_scan,
            "Scan and list a directory tree", "build", priority=85
        )
        self.command_registry.register(
            "tree read", self._cmd_tree_read,
            "Read a file from the filesystem tree", "build", priority=85
        )
        self.command_registry.register(
            "tree write", self._cmd_tree_write,
            "Write content to a file in the tree", "build", priority=85
        )
        self.command_registry.register(
            "tree edit", self._cmd_tree_edit,
            "Find-and-replace text in a file", "build", priority=85
        )

        # Import / deploy improvements command
        self.command_registry.register(
            "import improvements", self._cmd_import_improvements,
            "Read evolved/ improvements and hot-reload them", "build", priority=85
        )
        self.command_registry.register(
            "deploy improvements", self._cmd_import_improvements,
            "Alias for import improvements", "build", priority=85
        )
        self.command_registry.register(
            "hot reload improvements", self._cmd_import_improvements,
            "Hot-reload evolution improvements into the running process", "build", priority=85
        )


    def _cmd_autonomous_start(self, _text: str) -> str:
        """Start autonomous learning engine."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"

        result = self.autonomous_engine.start()
        return "🚀 [AUTONOMOUS] Learning started ✅" if result else "ℹ️ [AUTONOMOUS] Already running"

    def _cmd_autonomous_stop(self, _text: str) -> str:
        """Stop autonomous learning engine."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"

        result = self.autonomous_engine.stop()
        return "⏹️ [AUTONOMOUS] Learning stopped ✅" if result else "ℹ️ [AUTONOMOUS] Not running"

    def _cmd_autonomous_status(self, _text: str) -> str:
        """Show autonomous learning status."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"

        stats = self.autonomous_engine.get_learning_stats()
        s = stats["stats"]
        mods = stats.get("modules_available", {})
        slsa_topics = stats.get("slsa_topics", [])
        result = f"""
🧠 **AUTONOMOUS LEARNING STATUS:**

Running: {'✅' if stats['running'] else '❌'}
System Idle: {'Yes' if stats['is_idle'] else 'No'}
Uptime: {stats['uptime_seconds']}s

📊 Learning Statistics:
  Research Cycles: {s.get('research_completed', 0)}
  Ideas Generated: {s.get('ideas_generated', 0)}
  Ideas Implemented: {s.get('ideas_implemented', 0)}
  Reflections: {s.get('reflections_conducted', 0)}
  SLSA Runs: {s.get('slsa_runs', 0)}
  Evolve Steps: {s.get('evolve_steps', 0)}
  Learning Rate: {s.get('learning_rate', 0.0):.6f} cycles/s

💻 Programming Literacy:
  Code Researched: {s.get('code_researched', 0)}
  Code Generated: {s.get('code_generated', 0)}
  Code Compiled: {s.get('code_compiled', 0)}
  Code Reflected: {s.get('code_reflected', 0)}
  Software Studied: {s.get('software_studied', 0)}
  Last Language: {s.get('last_language_studied', 'none')}
  Last Category: {s.get('last_software_category', 'none')}

📋 Command Awareness:
  Command Awareness Cycles: {s.get('command_awareness_cycles', 0)}
  Command Executions: {s.get('command_executions', 0)}
  Last Commands Studied: {s.get('last_commands_studied', 'none')}
  Self-Learn Sequences: {s.get('self_learn_sequences', 0)}
  Evolve Sequences: {s.get('evolve_sequences', 0)}

🌱 Topic Seeding:
  Topic Seedings: {s.get('topic_seedings', 0)}
  Last Seeded: {', '.join(s.get('last_seeded_topics') or []) or 'none'}
  ALE Topics: {stats.get('research_topics', 0)}
  SLSA Topics: {len(slsa_topics)} ({', '.join(slsa_topics[:3])}{'...' if len(slsa_topics) > 3 else ''})

🧩 Intelligent Reasoning:
  Reasoning Cycles: {s.get('reasoning_cycles', 0)}
  Last Inferences: {s.get('last_reasoning_inferences', 0)}
  Metacognition Cycles: {s.get('metacognition_cycles', 0)}
  Last Confidence: {s.get('last_metacognition_confidence', 'none')}

📚 Topics: {stats.get('research_topics', 0)} | Code Topics: {stats.get('code_research_topics', 0)} | \
SW Categories: {stats.get('software_study_categories', 0)}
💡 Pending Ideas: {stats.get('pending_ideas', 0)}

🔌 Modules Wired:
  internet             : {mods.get('internet', False)}
  code_generator       : {mods.get('code_generator', False)}
  code_compiler        : {mods.get('code_compiler', False)}
  software_studier     : {mods.get('software_studier', False)}
  structural_awareness : {mods.get('structural_awareness', False)}
  slsa_manager         : {mods.get('slsa_manager', False)}
  reasoning_engine     : {mods.get('reasoning_engine', False)}
  metacognition        : {mods.get('metacognition', False)}
"""
        return result.strip()

    def _cmd_autonomous_code_status(self, _text: str) -> str:
        """Show programming literacy / code loop status in detail."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        stats = self.autonomous_engine.get_learning_stats()
        s = stats["stats"]
        mods = stats.get("modules_available", {})
        lines = [
            "💻 **CODE LITERACY STATUS:**\n",
            f"  Code Researched  : {s.get('code_researched', 0)} cycles",
            f"  Code Generated   : {s.get('code_generated', 0)} snippets",
            f"  Code Compiled    : {s.get('code_compiled', 0)} runs",
            f"  Code Reflected   : {s.get('code_reflected', 0)} reflections",
            f"  Software Studied : {s.get('software_studied', 0)} categories",
            f"  Last Language    : {s.get('last_language_studied', 'none')}",
            f"  Last SW Category : {s.get('last_software_category', 'none')}",
            "\n🔌 Module Availability:",
            f"  internet         : {'✅' if mods.get('internet') else '❌'}",
            f"  code_generator   : {'✅' if mods.get('code_generator') else '❌'}",
            f"  code_compiler    : {'✅' if mods.get('code_compiler') else '❌'}",
            f"  software_studier : {'✅' if mods.get('software_studier') else '❌'}",
            f"  researcher       : {'✅' if mods.get('researcher') else '❌'}",
            "\n📋 Pending:",
            f"  Compilations     : {stats.get('pending_compilations', 0)}",
            f"  Reflections      : {stats.get('pending_reflections', 0)}",
            "\n⚙️ Loop runs during idle time. Use 'autonomous-learn start' to enable.",
        ]
        return "\n".join(lines)

    def _cmd_autonomous_add_topic(self, text: str) -> str:
        """Add research topic to autonomous engine."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"

        topic = (
            text[len("autonomous-learn add-topic"):].strip()
            if text.lower().startswith("autonomous-learn add-topic")
            else text.strip()
        )
        if not topic:
            return "Usage: autonomous-learn add-topic <topic>"

        result = self.autonomous_engine.add_research_topic(topic)
        return f"✅ Topic added: {topic}" if result else "ℹ️ Topic already exists"

    # ============================
    # KNOWLEDGE RECALL & ACQUIRED DATA COMMANDS
    # ============================

    def _cmd_recall(self, text: str) -> str:
        """Recall acquired data from KnowledgeDB matching a query."""
        query = text.strip()
        # Strip the 'recall' command prefix (with or without trailing space)
        if query.lower().startswith("recall "):
            query = query[len("recall "):].strip()
        elif query.lower() == "recall":
            query = ""

        if not self.db:
            return "[❌ KnowledgeDB not available]"

        try:
            results = self.db.recall(query, limit=8)
        except Exception as exc:
            return f"[Recall error: {exc}]"

        if not results:
            return f"ℹ️ Nothing found for '{query}'. Try 'acquired data' or 'knowledge stats'."

        lines = [f"🔍 **Recall results for '{query}'** ({len(results)} entries):\n"]
        for i, r in enumerate(results, 1):
            if isinstance(r, dict):
                key = r.get("key", r.get("topic", r.get("time", "")))
                value = r.get("value", r.get("input", r.get("text", str(r))))
                tags = r.get("tags", [])
                snippet = str(value)[:120].replace("\n", " ")
                tag_str = f"  [{', '.join(str(t) for t in tags[:3])}]" if tags else ""
                lines.append(f"  {i}. [{key}]{tag_str}\n     {snippet}")
            else:
                lines.append(f"  {i}. {str(r)[:120]}")
        return "\n".join(lines)

    def _cmd_acquired_data(self, text: str) -> str:
        """Show acquired data stored in KnowledgeDB, optionally filtered by category."""
        # pylint: disable=too-many-locals
        rest = text.strip()
        for prefix in ("acquired data ", "acquired data", "acquired-data ", "acquired-data"):
            if rest.lower().startswith(prefix):
                rest = rest[len(prefix):].strip()
                break
        else:
            rest = ""

        category = rest or None

        if not self.db or not hasattr(self.db, "get_acquired_data"):
            return "[❌ KnowledgeDB does not support get_acquired_data]"

        try:
            data = self.db.get_acquired_data(category=category, limit=20)
        except Exception as exc:
            return f"[Acquired data error: {exc}]"

        if not data:
            cat_msg = f" in category '{category}'" if category else ""
            return f"ℹ️ No acquired data{cat_msg} yet. Start 'autonomous-learn start' to begin collecting."

        cat_label = f" [{category}]" if category else ""
        lines = [f"📦 **Acquired Data{cat_label}** ({len(data)} entries, newest first):\n"]
        for i, fact in enumerate(data[:15], 1):
            key = str(fact.get("key", ""))[:50]
            value = fact.get("value", "")
            tags = fact.get("tags", [])
            snippet = str(value)[:100].replace("\n", " ")
            tag_str = ", ".join(str(t) for t in tags[:3])
            lines.append(f"  {i}. {key}\n     {snippet}\n     tags: {tag_str}")
        if len(data) > 15:
            lines.append(f"\n  ... and {len(data) - 15} more. Use 'acquired data <category>' to filter.")

        categories = ["research", "ideas", "implementation", "reflection", "code",
                      "compiled", "software_study", "all"]
        lines.append(f"\n📂 Available categories: {', '.join(categories)}")
        return "\n".join(lines)

    def _cmd_knowledge_stats(self, _text: str) -> str:
        """Show a summary of all stored knowledge and ALE process awareness."""
        if not self.db:
            return "[❌ KnowledgeDB not available]"

        if hasattr(self.db, "get_knowledge_summary"):
            try:
                return self.db.get_knowledge_summary()
            except Exception as exc:
                return f"[Knowledge summary error: {exc}]"

        # Fallback: basic stats
        try:
            all_data = self.db.get_all() if hasattr(self.db, "get_all") else {}
            lines = ["📚 **Knowledge Base Stats:**\n"]
            for section, items in all_data.items():
                count = len(items) if isinstance(items, (list, dict)) else "—"
                lines.append(f"  {section:<20}: {count}")
            return "\n".join(lines)
        except Exception as exc:
            return f"[Knowledge stats error: {exc}]"

    def _cmd_ale_process_awareness(self, _text: str) -> str:
        """Explain all Niblit ALE processes and how data flows through them."""
        ale_stats = {}
        if self.autonomous_engine:
            try:
                ale_stats = self.autonomous_engine.get_learning_stats()
            except Exception:
                pass

        s = ale_stats.get("stats", {})
        mods = ale_stats.get("modules_available", {})

        lines = [
            "🧠 **NIBLIT AUTONOMOUS LEARNING ENGINE — PROCESS AWARENESS**\n",
            "Niblit runs 15 self-improvement steps every idle cycle.",
            "All output is stored as structured facts in KnowledgeDB.",
            "Internet is the primary data source for collection steps.\n",
            "━━━ CORE LEARNING LOOP ━━━",
            f"  Step 1 — Research       : researcher+internet → KB  [{s.get('research_completed', 0)} runs]",
            f"  Step 2 — Idea Generation: SelfIdeaImpl/Generator    [{s.get('ideas_generated', 0)} ideas]",
            f"  Step 3 — Implementation : SelfImplementer executes  [{s.get('ideas_implemented', 0)} implemented]",
            f"  Step 4 — Reflection     : ReflectModule summarizes  [{s.get('reflections_conducted', 0)} reflections]",
            f"  Step 5 — SLSA           : generates knowledge artif [{s.get('slsa_runs', 0)} runs]",
            "  Step 6 — Learning       : SelfTeacher internalizes  [see KB: learning]",
            f"  Step 7 — Evolution      : EvolveEngine self-evolves [{s.get('evolve_steps', 0)} steps]",
            "",
            "━━━ PROGRAMMING LITERACY LOOP ━━━",
            f"  Step 8  — Code Research : internet+researcher→KB    [{s.get('code_researched', 0)} cycles]",
            f"  Step 9  — Code Generate : idea+implementer→code     [{s.get('code_generated', 0)} snippets]",
            f"  Step 10 — Code Compile  : CodeCompiler runs it      [{s.get('code_compiled', 0)} compiled]",
            f"  Step 11 — Code Reflect  : ReflectModule studies it  [{s.get('code_reflected', 0)} reflected]",
            f"  Step 12 — SW Study      : SoftwareStudier+internet  [{s.get('software_studied', 0)} categories]",
            "",
            "━━━ STRUCTURAL AWARENESS LOOP ━━━",
            f"  Step 13 — Cmd Awareness : catalogue all commands→KB [{s.get('command_awareness_cycles', 0)} cycles]",
            f"  Step 14 — Cmd Execution : run safe commands→log     [{s.get('command_executions', 0)} runs]",
            f"  On-Demand: Self-Learn Sequences  [{s.get('self_learn_sequences', 0)} runs]",
            f"  On-Demand: Evolve Sequences      [{s.get('evolve_sequences', 0)} runs]",
            "",
            "━━━ TOPIC SEEDING LOOP ━━━",
            f"  Step 15 — Topic Seeding : derive topics→ALE+SLSA+KB [{s.get('topic_seedings', 0)} cycles]",
            f"  Last Seeded Topics: {', '.join(s.get('last_seeded_topics') or []) or 'none'}",
            f"  Current SLSA Topics: {', '.join(ale_stats.get('slsa_topics', [])) or 'none'}",
            "",
            "━━━ DATA STORAGE ━━━",
            "  Every step stores a structured fact in KnowledgeDB with:",
            "    • Unique key (ale_<step>:<topic>:<timestamp>)",
            "    • Value dict with topic, result, and step name",
            "    • Tags: [ale_stepN, <category>, autonomous]",
            "  Data persists to niblit_memory.json automatically.",
            "  Recall with: 'recall <topic>'",
            "  Browse with: 'acquired data [category]'",
            "  Summary  : 'knowledge stats'",
            "",
            "━━━ MODULE STATUS ━━━",
        ]
        for mod, available in mods.items():
            lines.append(f"  {mod:<20}: {'✅' if available else '❌'}")

        lines += [
            "",
            "━━━ HOW TO QUERY ━━━",
            "  recall <topic>           — search all KB for topic",
            "  acquired data            — browse all acquired facts",
            "  acquired data research   — facts from Step 1",
            "  acquired data code       — facts from Steps 8-11",
            "  acquired data compiled   — compiled code output",
            "  knowledge stats          — full KB summary",
        ]
        return "\n".join(lines)

    # ============================
    # SELF-IMPROVEMENT COMMANDS
    # ============================

    def _cmd_show_improvements(self, _text: str) -> str:
        """Show all 10 self-improvement modules."""
        if not self.improvements:
            return "[❌ Self-improvements not available]"

        status = self.improvements.get_improvement_status()
        result = "🚀 **10 SELF-IMPROVEMENT MODULES:**\n\n"

        for i, (_name, desc) in enumerate(status.items(), 1):
            result += f"{i}. {desc}\n"

        return result

    def _cmd_run_improvement_cycle(self, _text: str) -> str:
        """Run complete improvement cycle."""
        if not self.improvements:
            return "[❌ Self-improvements not available]"

        try:
            log.info("🔄 [NIBLIT] Starting full improvement cycle...")
            results = self.improvements.run_full_improvement_cycle()

            output = "🔄 **IMPROVEMENT CYCLE RESULTS:**\n\n"
            for module, result in results.items():
                if isinstance(result, dict):
                    output += f"✅ {module.upper()}: {result}\n"
                else:
                    output += f"❌ {module.upper()}: {result}\n"

            return output
        except Exception as e:
            log.error(f"[IMPROVEMENTS] Improvement cycle failed: {e}", exc_info=True)
            return f"[❌ Improvement cycle failed: {e}]"

    def _cmd_improvement_status(self, _text: str) -> str:
        """Show improvement system status."""
        if not self.improvements:
            return "[❌ Self-improvements not available]"

        status = self.improvements.get_improvement_status()
        result = "📊 **IMPROVEMENT SYSTEM STATUS:**\n\n"

        active = sum(1 for s in status.values() if "✅" in str(s))
        total = len(status)

        result += f"Active Improvements: {active}/{total}\n\n"
        result += "Details:\n"
        for _name, state in status.items():
            result += f"  {state}\n"

        return result

    def _cmd_show_new_commands(self, _text: str = "") -> str:
        """Show all commands added in recent updates."""
        return (
            "🆕 **NEW COMMANDS (Recent Updates)**\n\n"
            "--- AUTONOMOUS LEARNING (Continuous — auto-starts with Niblit) ---\n"
            "autonomous-learn start             — Resume continuous learning after a stop\n"
            "autonomous-learn stop              — Pause continuous learning\n"
            "autonomous-learn status            — View stats including improvement_cycles count\n"
            "autonomous-learn add-topic <topic> — Seed a new research topic into ALE\n"
            "autonomous-learn code-status       — Programming literacy stats\n"
            "\n--- KNOWLEDGE RECALL (ALE Output) ---\n"
            "recall <topic>                     — Search all KB facts for topic (ale_learned tags included)\n"
            "acquired data                      — Browse all facts produced by ALE\n"
            "acquired data <category>           — Filter: research, ideas, code, compiled, reflection,\n"
            "                                     software_study, implementation, all\n"
            "knowledge stats                    — KB summary: counts, tags, ALE breakdown\n"
            "ale processes                      — Explain all 18 ALE steps + module status\n"
            "\n--- 10 SELF-IMPROVEMENTS (Now Continuous) ---\n"
            "run improvement-cycle              — Manually trigger full 10-module improvement cycle\n"
            "show improvements                  — List all 10 improvement modules\n"
            "improvement-status                 — Status of each improvement module\n"
            "\n--- STRUCTURAL SELF-AWARENESS ---\n"
            "my structure                       — Full component inventory\n"
            "my threads                         — All active threads\n"
            "my loops                           — Background loop status\n"
            "my modules                         — Loaded modules\n"
            "my commands                        — All registered commands\n"
            "new commands                       — This listing of recently added commands\n"
            "dashboard                          — Full runtime dashboard\n"
            "resource usage                     — RAM, CPU, uptime\n"
            "\n--- CODE & LEARNING ---\n"
            "generate code <lang> [template]    — Generate code\n"
            "run code <lang> <code>             — Execute code inline\n"
            "study language <lang>              — Study language best practices\n"
            "study software <category>          — Study a software category\n"
            "research code <lang> [topic]       — Research lang from internet → CodeGenerator\n"
            "\n--- REASONING ENGINE (LLM-level) ---\n"
            "reasoning build                    — Build knowledge graph from KB facts\n"
            "reasoning status                   — Show reasoning engine status\n"
            "reasoning chain <concept>          — Multi-hop chain from concept (legacy)\n"
            "reasoning paths <concept>          — BFS multi-hop paths with scores\n"
            "reasoning infer                    — Graph-based inference (legacy)\n"
            "reasoning cot <question>           — Chain-of-thought reasoning (LLM + graph)\n"
            "reasoning contradict               — Detect contradictions in KB facts\n"
            "\n--- REASONING & METACOGNITION ---\n"
            "self-research <topic>              — Autonomous research + KB storage\n"
            "reflect [text]                     — Reflect on topic (results stored in ale_learned)\n"
            "auto-reflect                       — Auto reflection on recent events\n"
            "\n--- EVOLUTION ---\n"
            "evolve                             — One self-evolution step\n"
            "evolve start                       — Continuous background evolution\n"
            "evolve stop                        — Stop background evolution\n"
            "evolve status                      — Evolution status\n"
            "\n--- GITHUB SYNC (self-updates) ---\n"
            "github status                      — Git status of Niblit build directory\n"
            "github pull                        — Pull latest changes from GitHub\n"
            "github push [message]              — Push self-updates to GitHub\n"
            "github log [n]                     — Show last n git commits (default 5)\n"
            "\n--- BUILD SCANNER (self-knowledge) ---\n"
            "scan build [subdir]                — List all files in the Niblit build directory\n"
            "read build file <name>             — Read a file from the build directory\n"
            "build summary                      — Summary of the build directory\n"
            "build path                         — Show Niblit build path and sync status\n"
            "\n--- AGENTIC & ORCHESTRATION ---\n"
            "agentic run <workflow>             — Run a named agentic workflow\n"
            "agentic list                       — List available agentic workflows\n"
            "orchestrate audit                  — Run repository audit\n"
            "orchestrate self-heal              — Run self-healing\n"
            "orchestrate pipeline               — Full orchestration pipeline\n"
            "\nTip: 'help' shows the full command reference.\n"
            "     All research, ideas, code, and improvement results are stored in\n"
            "     KnowledgeDB — use 'recall <topic>' or 'acquired data' to browse them."
        )

    # ============================
    # COMMAND HANDLERS (NO LLM)
    # ============================

    # ──────────────────────────────────────
    # LIVE UPDATER COMMANDS
    # ──────────────────────────────────────

    # ──────────────────────────────────────
    # AGENTIC WORKFLOW COMMANDS
    # ──────────────────────────────────────

    def _cmd_agentic_run(self, spec: str) -> str:
        """Run a named agentic workflow, optionally with context key=value pairs."""
        if not self.agentic_workflows:
            return "[❌ AgenticWorkflow not available]"
        parts = spec.strip().split(None, 1)
        workflow_name = parts[0] if parts else ""
        context: dict = {}
        if len(parts) > 1:
            # Parse trailing key=value pairs or treat remainder as 'topic' / 'goal'
            remainder = parts[1]
            if "=" in remainder:
                for kv in remainder.split():
                    if "=" in kv:
                        k, _, v = kv.partition("=")
                        context[k] = v
            else:
                context["topic"] = remainder
                context["goal"] = remainder
        if not workflow_name:
            available = ", ".join(self.agentic_workflows.list_workflows())
            return f"Usage: agentic run <workflow> [key=val ...]\nAvailable: {available}"
        record = self.agentic_workflows.run_workflow(workflow_name, context)
        return self.agentic_workflows.format_result(record)

    def _cmd_agentic_list(self, _text: str = "") -> str:
        """List all registered agentic workflows."""
        if not self.agentic_workflows:
            return "[❌ AgenticWorkflow not available]"
        workflows = self.agentic_workflows.list_workflows()
        lines = ["🤖 **REGISTERED AGENTIC WORKFLOWS:**", ""]
        for i, name in enumerate(workflows, 1):
            lines.append(f"  {i}. {name}")
        lines.append("")
        lines.append("Usage: agentic run <name> [topic=<topic>]")
        return "\n".join(lines)

    def _cmd_agentic_status(self, _text: str = "") -> str:
        """Show agentic workflow module status."""
        if not self.agentic_workflows:
            return "[❌ AgenticWorkflow not available]"
        status = self.agentic_workflows.workflow_status()
        lines = [
            "🤖 **AGENTIC WORKFLOW STATUS:**",
            f"Registered workflows: {status['registered_workflows']}",
            f"Executions this session: {status['executions_this_session']}",
            f"Last run: {status['last_run'] or 'none'}",
            f"Capability: {status['capability']}",
            f"Status: {status['status']}",
        ]
        return "\n".join(lines)

    # ──────────────────────────────────────
    # ENTERPRISE UTILITY COMMANDS
    # ──────────────────────────────────────

    def _cmd_enterprise_summary(self, _text: str = "") -> str:
        """Show enterprise operational summary."""
        if not self.enterprise_utility:
            return "[❌ EnterpriseUtility not available]"
        return self.enterprise_utility.format_summary()

    def _cmd_enterprise_audit(self, spec: str) -> str:
        """Show recent audit log entries."""
        if not self.enterprise_utility:
            return "[❌ EnterpriseUtility not available]"
        try:
            limit = int(spec.strip()) if spec.strip().isdigit() else 10
        except ValueError:
            limit = 10
        entries = self.enterprise_utility.get_audit_log(limit=limit)
        if not entries:
            return "📋 Audit log is empty."
        lines = [f"📋 **AUDIT LOG (last {len(entries)}):**", ""]
        for e in entries:
            lines.append(f"  [{e['ts']}] {e['event_type']} | {e['actor']} | {e['outcome']}"
                         + (f" — {e['details']}" if e.get('details') else ""))
        return "\n".join(lines)

    def _cmd_enterprise_health(self, _text: str = "") -> str:
        """Show component health report."""
        if not self.enterprise_utility:
            return "[❌ EnterpriseUtility not available]"
        report = self.enterprise_utility.get_health_report()
        lines = [
            f"🏥 **HEALTH REPORT — Overall: {report['overall'].upper()}**",
            f"Components: {report['healthy']}/{report['total_components']} healthy",
        ]
        for comp, info in report["components"].items():
            icon = "✅" if info["status"] == "healthy" else ("⚠️" if info["status"] == "degraded" else "❌")
            lines.append(f"  {icon} {comp}: {info['status']}")
        return "\n".join(lines)

    def _cmd_enterprise_sla(self, _text: str = "") -> str:
        """Show SLA metrics."""
        if not self.enterprise_utility:
            return "[❌ EnterpriseUtility not available]"
        sla = self.enterprise_utility.get_sla_report()
        if not sla:
            return "📈 No SLA metrics recorded yet."
        lines = ["📈 **SLA METRICS:**", ""]
        for op, m in sla.items():
            lines.append(f"  • {op}: {m['total']} ops | err={m['error_rate_pct']}% | "
                         f"avg={m['avg_latency_ms']}ms | max={m['max_latency_ms']}ms")
        return "\n".join(lines)

    # ──────────────────────────────────────
    # MULTIMODAL INTELLIGENCE COMMANDS
    # ──────────────────────────────────────

    def _cmd_multimodal_process(self, spec: str) -> str:
        """Process content with multimodal intelligence."""
        if not self.multimodal_intelligence:
            return "[❌ MultimodalIntelligence not available]"
        parts = spec.strip().split(None, 1)
        if not parts:
            return "Usage: multimodal process <content> OR multimodal process <modality> <content>"
        if parts[0] in ("text", "code", "json", "numeric", "mixed") and len(parts) > 1:
            modality, content = parts[0], parts[1]
        else:
            modality, content = "mixed", spec.strip()
        result = self.multimodal_intelligence.process(content, modality=modality)
        return f"🧠 **MULTIMODAL [{result.modality.upper()}]:**\n{result.content}"

    def _cmd_multimodal_status(self, _text: str = "") -> str:
        """Show multimodal intelligence module status."""
        if not self.multimodal_intelligence:
            return "[❌ MultimodalIntelligence not available]"
        status = self.multimodal_intelligence.get_status()
        lines = [
            "🧠 **MULTIMODAL INTELLIGENCE STATUS:**",
            f"Supported modalities: {', '.join(status['supported_modalities'])}",
            f"Inputs processed: {status['inputs_processed']}",
            f"Capability: {status['capability']}",
            f"Status: {status['status']}",
        ]
        if status["modality_breakdown"]:
            lines.append("Breakdown:")
            for mod, count in status["modality_breakdown"].items():
                lines.append(f"  • {mod}: {count}")
        return "\n".join(lines)

    # ──────────────────────────────────────
    # REASONING ENGINE COMMANDS
    # ──────────────────────────────────────

    def _cmd_reasoning_build(self, _text: str = "") -> str:
        """Build knowledge graph from current KnowledgeDB facts."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        try:
            facts = []
            if self.db and hasattr(self.db, "list_facts"):
                # list_facts() returns [{"key": ..., "value": ..., "tags": [...], "ts": ...}, ...]
                raw = self.db.list_facts(200)
                facts = [
                    {"key": str(f.get("key", "")), "value": str(f.get("value", ""))}
                    for f in (raw or [])
                    if isinstance(f, dict)
                ]
            graph = self.reasoning_engine.build_knowledge_graph(facts)
            return (f"🧠 **KNOWLEDGE GRAPH BUILT:**\n"
                    f"Concepts: {len(graph)}\n"
                    f"Sample nodes: {', '.join(list(graph.keys())[:10])}")
        except Exception as e:
            return f"[❌ Reasoning build failed: {e}]"

    def _cmd_reasoning_status(self, _text: str = "") -> str:
        """Show reasoning engine status."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        graph_size = len(self.reasoning_engine.graph)
        chain_count = len(self.reasoning_engine.reasoning_chains)
        return (f"🧠 **REASONING ENGINE STATUS:**\n"
                f"Knowledge graph concepts: {graph_size}\n"
                f"Reasoning chains stored: {chain_count}\n"
                f"Status: {'Ready — run `reasoning build` to populate graph' if graph_size == 0 else 'Active'}")

    def _cmd_reasoning_chain(self, concept: str) -> str:
        """Create a reasoning chain from the given concept."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        if not concept.strip():
            return "Usage: reasoning chain <concept>"
        chain = self.reasoning_engine.create_reasoning_chain(concept.strip())
        return f"🔗 **REASONING CHAIN from '{concept}':**\n{' → '.join(chain)}"

    def _cmd_reasoning_infer(self, _text: str = "") -> str:
        """Infer new knowledge from the current knowledge graph."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        inferences = self.reasoning_engine.infer_new_knowledge()
        if not inferences:
            return "🔮 No inferences yet — run 'reasoning build' first."
        lines = ["🔮 **INFERRED KNOWLEDGE:**", ""]
        for inf in inferences[:15]:
            lines.append(f"  • {inf}")
        if len(inferences) > 15:
            lines.append(f"  … and {len(inferences) - 15} more")
        return "\n".join(lines)

    def _cmd_reasoning_cot(self, question: str) -> str:
        """Run chain-of-thought reasoning for the given question."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        if not question.strip():
            return "Usage: reasoning cot <question>"
        facts = []
        if self.db and hasattr(self.db, "list_facts"):
            try:
                raw = self.db.list_facts(40) or []
                facts = [
                    {"key": str(f.get("key", "")), "value": str(f.get("value", ""))}
                    for f in raw if isinstance(f, dict)
                ]
            except Exception:
                pass
        cot = self.reasoning_engine.chain_of_thought(question.strip(), facts, max_steps=4)
        lines = [f"🧠 **CHAIN-OF-THOUGHT: {question}**", f"Source: {cot.source} | Confidence: {cot.confidence:.2f}", ""]
        for step in cot.steps:
            lines.append(f"  Step {step.index}: {step.question}")
            lines.append(f"    → {step.answer}")
        lines += ["", f"**Conclusion:** {cot.conclusion}"]
        return "\n".join(lines)

    def _cmd_reasoning_paths(self, concept: str) -> str:
        """Show multi-hop reasoning paths from the given concept."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        if not concept.strip():
            return "Usage: reasoning paths <concept>"
        paths = self.reasoning_engine.reason_paths(concept.strip(), goal=None, max_hops=4, top_k=3)
        if not paths:
            return f"🔗 No paths found from '{concept}' — run 'reasoning build' first."
        lines = [f"🔗 **REASONING PATHS from '{concept}':**", ""]
        for i, p in enumerate(paths, 1):
            lines.append(f"  {i}. {' → '.join(p.hops)}  (score: {p.score:.3f})")
        return "\n".join(lines)

    def _cmd_reasoning_contradict(self, _text: str = "") -> str:
        """Detect potential contradictions in KB facts."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        facts = []
        if self.db and hasattr(self.db, "list_facts"):
            try:
                raw = self.db.list_facts(60) or []
                facts = [
                    {"key": str(f.get("key", "")), "value": str(f.get("value", ""))}
                    for f in raw if isinstance(f, dict)
                ]
            except Exception:
                pass
        contradictions = self.reasoning_engine.detect_contradictions(facts)
        if not contradictions:
            return "✅ No contradictions detected in current KB facts."
        lines = [f"⚠️ **{len(contradictions)} POTENTIAL CONTRADICTIONS DETECTED:**", ""]
        for c in contradictions[:10]:
            lines.append(f"  • [{c.shared_concept}] '{c.fact_a_key}' vs '{c.fact_b_key}' (score:{c.score:.2f})")
        return "\n".join(lines)

    # ──────────────────────────────────────
    # COLLABORATIVE SYSTEMS COMMANDS
    # ──────────────────────────────────────


    def _cmd_collab_status(self, _text: str = "") -> str:
        """Show collaborative learner status."""
        if not self.collaborative_learner:
            return "[❌ CollaborativeLearner not available]"
        status = self.collaborative_learner.get_collaboration_status()
        lines = [
            "🤝 **COLLABORATIVE SYSTEMS STATUS:**",
            f"Peers connected: {status['peers_connected']}",
            f"Knowledge shared: {status['total_knowledge_shared']}",
            f"Peers: {', '.join(status['peers']) if status['peers'] else 'none'}",
            f"Capability: {status['capability']}",
            f"Status: {status['status']}",
        ]
        return "\n".join(lines)

    def _cmd_collab_register(self, spec: str) -> str:
        """Register a peer system: collab register <name> [cap1,cap2,...]"""
        if not self.collaborative_learner:
            return "[❌ CollaborativeLearner not available]"
        parts = spec.strip().split(None, 1)
        if not parts:
            return "Usage: collab register <name> [capabilities]"
        name = parts[0]
        caps = [c.strip() for c in parts[1].split(",")] if len(parts) > 1 else []
        self.collaborative_learner.register_peer(name, caps)
        return f"✅ Peer '{name}' registered with {len(caps)} capabilities"

    def _cmd_collab_request(self, spec: str) -> str:
        """Request knowledge from a peer: collab request <peer> <topic>"""
        if not self.collaborative_learner:
            return "[❌ CollaborativeLearner not available]"
        parts = spec.strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: collab request <peer_name> <topic>"
        peer, topic = parts[0], parts[1]
        result = self.collaborative_learner.request_knowledge(peer, topic)
        if "error" in result:
            return f"❌ {result['error']}"
        return (f"📥 **KNOWLEDGE FROM '{peer}':**\n"
                f"Topic: {result['topic']}\n"
                f"Data: {result['data']}")

    def _cmd_reload_module(self, module_name: str) -> str:
        """Hot-reload a module at runtime."""
        if self.live_updater:
            result = self.live_updater.reload_module(module_name)
            return result["message"]
        # Fallback: importlib.reload
        try:
            import importlib as _importlib
            mod = sys.modules.get(module_name)
            if mod is None:
                mod = _importlib.import_module(module_name)
            _importlib.reload(mod)
            return f"✅ Module '{module_name}' reloaded (direct fallback)."
        except Exception as e:
            return f"❌ Reload failed for '{module_name}': {e}"

    def _cmd_upgrade(self, _text: str = "") -> str:
        """Reload all modules whose files changed on disk."""
        if self.live_updater:
            changed = self.live_updater.reload_all_changed()
            if not changed:
                return "✅ All modules are up-to-date — no changes detected on disk."
            msgs = [r["message"] for r in changed]
            return "🔄 **Self-Upgrade Complete:**\n" + "\n".join(f"  • {m}" for m in msgs)
        return "[LiveUpdater not available — restart to pick up file changes]"

    def _cmd_update_history(self, _text: str = "") -> str:
        """Show recent hot-reload history."""
        if self.live_updater:
            return self.live_updater.summarize_history()
        return "[LiveUpdater not available]"

    # ──────────────────────────────────────
    # GITHUB SYNC COMMANDS
    # ──────────────────────────────────────

    def _cmd_github_status(self, _text: str = "") -> str:
        """Show git status of the Niblit build directory."""
        if not self.github_sync:
            return "[❌ GitHubSync not available]"
        return f"🐙 **GitHub Status:**\n{self.github_sync.status()}"

    def _cmd_github_pull(self, _text: str = "") -> str:
        """Pull the latest changes from GitHub into the build directory."""
        if not self.github_sync:
            return "[❌ GitHubSync not available]"
        result = self.github_sync.pull()
        return f"⬇️ **GitHub Pull:**\n{result}"

    def _cmd_github_push(self, text: str = "") -> str:
        """Push self-updates to GitHub. Optionally: 'github push <commit message>'"""
        if not self.github_sync:
            return "[❌ GitHubSync not available]"
        msg = text.strip() or None
        result = self.github_sync.push(msg)
        return f"⬆️ **GitHub Push:**\n{result}"

    def _cmd_github_log(self, text: str = "") -> str:
        """Show the last git commits from the build directory."""
        if not self.github_sync:
            return "[❌ GitHubSync not available]"
        try:
            n = int(text.strip()) if text.strip().isdigit() else 5
        except ValueError:
            n = 5
        return f"📜 **GitHub Log (last {n}):**\n{self.github_sync.log(n)}"

    # ──────────────────────────────────────
    # BUILD SCANNER COMMANDS
    # ──────────────────────────────────────

    def _cmd_scan_build(self, text: str = "") -> str:
        """Scan the Niblit build directory: list all files and subdirs."""
        if not self.build_scanner:
            return "[❌ BuildScanner not available]"
        subdir = text.strip()
        scan = self.build_scanner.scan(subdir)
        if scan.get("error"):
            return f"❌ {scan['error']}"
        lines = [f"🏗️ **Build scan:** `{scan['path']}`  ({scan['total']} entries)"]
        if scan["dirs"]:
            lines.append(f"  📁 Dirs ({len(scan['dirs'])}): {', '.join(scan['dirs'][:15])}")
        files = scan["files"]
        if files:
            lines.append(f"  📄 Files ({len(files)}):")
            for f in files[:30]:
                size_str = f" ({f['size']} B)" if f["size"] < 100_000 else f" ({f['size']//1024} KB)"
                lines.append(f"    {f['name']}{size_str}")
            if len(files) > 30:
                lines.append(f"    … and {len(files) - 30} more")
        return "\n".join(lines)

    def _cmd_read_build_file(self, filepath: str = "") -> str:
        """Read a file from the Niblit build directory."""
        if not self.build_scanner:
            return "[❌ BuildScanner not available]"
        if not filepath.strip():
            return "Usage: read build file <filename>"
        result = self.build_scanner.read_file(filepath.strip())
        if not result["success"]:
            return f"❌ {result['error']}"
        content = result["content"]
        preview = content[:1500]
        suffix = "\n…[truncated]" if len(content) > 1500 else ""
        return f"📄 **{filepath}** ({result['size']} bytes):\n```\n{preview}{suffix}\n```"

    def _cmd_build_summary(self, _text: str = "") -> str:
        """Show a summary of the Niblit build directory."""
        if not self.build_scanner:
            return "[❌ BuildScanner not available]"
        return self.build_scanner.summarize()

    def _cmd_build_path(self, _text: str = "") -> str:
        """Show the Niblit build path used by evolve and code generator."""
        lines = [
            "🏗️ **Niblit Build Path:**",
            f"  Path        : {_NIBLIT_BUILD_PATH}",
            f"  Exists      : {'✅ Yes' if _NIBLIT_BUILD_PATH.exists() else '❌ No (not on Termux)'}",
            f"  GitHub Sync : {'✅ Ready' if self.github_sync else '❌ Not available'}",
            f"  Build Scanner: {'✅ Ready' if self.build_scanner else '❌ Not available'}",
        ]
        if self.code_generator and hasattr(self.code_generator, "get_deploy_path"):
            dp = self.code_generator.get_deploy_path()
            lines.append(f"  Code Generator deploy path: {dp or '(not set)'}")
        return "\n".join(lines)

    # ──────────────────────────────────────
    # TREE / FILESYSTEM COMMANDS
    # ──────────────────────────────────────

    def _cmd_tree_scan(self, path: str = "") -> str:
        """Recursively list all files under *path* (or the repo root)."""
        target = Path(path.strip()) if path.strip() else Path(".")
        if not target.exists():
            return f"❌ Path not found: {target}"
        if self.file_manager and hasattr(self.file_manager, "list_dir"):
            result = self.file_manager.list_dir(str(target))
            if result.get("error"):
                return f"❌ {result['error']}"
            entries = result.get("entries", [])
            lines = [f"🌲 **Tree: `{target}`** ({len(entries)} entries)"]
            for e in entries[:60]:
                icon = "📁" if e.get("type") == "dir" else "📄"
                size = f" ({e['size']} B)" if e.get("size") is not None and e.get("type") != "dir" else ""
                lines.append(f"  {icon} {e['name']}{size}")
            if len(entries) > 60:
                lines.append(f"  … and {len(entries) - 60} more")
            return "\n".join(lines)
        # Fallback: stdlib walk
        lines = [f"🌲 **Tree: `{target}`**"]
        try:
            for root, _dirs, files in sorted_walk(target):
                depth = len(Path(root).relative_to(target).parts)
                indent = "  " * depth
                lines.append(f"{indent}📁 {Path(root).name}/")
                for f in sorted(files)[:20]:
                    lines.append(f"{indent}  📄 {f}")
        except Exception as e:
            return f"❌ {e}"
        return "\n".join(lines[:100])

    def _cmd_tree_read(self, path: str = "") -> str:
        """Read and display the contents of a file at *path*."""
        if not path.strip():
            return "Usage: tree read <path/to/file>"
        if self.file_manager and hasattr(self.file_manager, "read"):
            result = self.file_manager.read(path.strip())
            if result.get("error"):
                return f"❌ {result['error']}"
            content = result.get("content", "")
            preview = content[:2000]
            suffix = "\n…[truncated]" if len(content) > 2000 else ""
            return f"📄 **{path}** ({result.get('size', '?')} bytes):\n```\n{preview}{suffix}\n```"
        # Fallback
        try:
            content = Path(path.strip()).read_text(encoding="utf-8", errors="replace")
            preview = content[:2000]
            suffix = "\n…[truncated]" if len(content) > 2000 else ""
            return f"📄 **{path}**:\n```\n{preview}{suffix}\n```"
        except Exception as e:
            return f"❌ {e}"

    def _cmd_tree_write(self, spec: str = "") -> str:
        """Write content to a file. Usage: tree write <path> <content>"""
        parts = spec.strip().split(" ", 1)
        if len(parts) < 2:
            return "Usage: tree write <path> <content>"
        filepath, content = parts[0], parts[1]
        if self.file_manager and hasattr(self.file_manager, "write"):
            result = self.file_manager.write(filepath, content)
            if result.get("error"):
                return f"❌ {result['error']}"
            return f"✅ Written to `{filepath}` ({len(content)} chars)"
        # Fallback
        try:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"✅ Written to `{filepath}` ({len(content)} chars)"
        except Exception as e:
            return f"❌ {e}"

    def _cmd_tree_edit(self, spec: str = "") -> str:
        """Replace text in a file. Usage: tree edit <path> <old_text>||<new_text>"""
        parts = spec.strip().split(" ", 1)
        if len(parts) < 2 or "||" not in parts[1]:
            return "Usage: tree edit <path> <old_text>||<new_text>"
        filepath = parts[0]
        old_text, new_text = parts[1].split("||", 1)
        if self.file_manager and hasattr(self.file_manager, "replace_in_file"):
            result = self.file_manager.replace_in_file(filepath, old_text, new_text)
            if result.get("error"):
                return f"❌ {result['error']}"
            reps = result.get("replacements", 1)
            return f"✅ Replaced {reps} occurrence(s) in `{filepath}`"
        # Fallback
        try:
            p = Path(filepath)
            original = p.read_text(encoding="utf-8")
            updated = original.replace(old_text, new_text)
            count = original.count(old_text)
            p.write_text(updated, encoding="utf-8")
            return f"✅ Replaced {count} occurrence(s) in `{filepath}`"
        except Exception as e:
            return f"❌ {e}"

    # ──────────────────────────────────────
    # IMPORT / DEPLOY IMPROVEMENTS COMMAND
    # ──────────────────────────────────────

    def _cmd_import_improvements(self, _text: str = "") -> str:
        """Scan the evolved/ directory, read improvement files, and hot-reload them.

        This command:
        1. Finds all ``improvement_*.py`` files under every step sub-directory
           in the ``evolved/`` folder.
        2. Reads and stores their content as self-knowledge in the KB.
        3. Attempts to hot-reload each improvement via LiveUpdater.apply_patch()
           so the improvement takes effect without restarting Niblit.
        """
        # pylint: disable=too-many-branches
        # Locate evolved/ — prefer the evolve engine deploy path, then repo root
        evolved_dir: Optional[Path] = None
        if self.evolve_engine:
            dp = getattr(self.evolve_engine, "deploy_path", None)
            if dp and (Path(dp) / "evolved").exists():
                evolved_dir = Path(dp) / "evolved"
        if evolved_dir is None:
            repo_root = Path(__file__).resolve().parent
            candidate = repo_root / "evolved"
            if candidate.exists():
                evolved_dir = candidate

        if evolved_dir is None:
            return "❌ No `evolved/` directory found. Run an evolution cycle first."

        deployed: list = []
        understood: list = []
        errors: list = []

        for step_dir in sorted(evolved_dir.iterdir()):
            if not step_dir.is_dir():
                continue
            for fpath in sorted(step_dir.glob("improvement_*.py")):
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    errors.append(f"{fpath.name}: read error ({exc})")
                    continue

                understood.append(fpath.name)

                # Store in KB for self-understanding
                if self.db and hasattr(self.db, "add_fact"):
                    try:
                        self.db.add_fact(
                            f"import_improvement:{step_dir.name}:{fpath.stem}",
                            content[:400],
                            tags=["improvement", "deploy", "hot_reload"],
                        )
                    except Exception:
                        pass

                # Hot-reload via LiveUpdater
                if self.live_updater and hasattr(self.live_updater, "apply_patch"):
                    module_key = f"evolved.{step_dir.name}.{fpath.stem}"
                    try:
                        result = self.live_updater.apply_patch(module_key, content)
                        if result.get("success"):
                            deployed.append(fpath.name)
                        else:
                            errors.append(f"{fpath.name}: {result.get('error', 'patch failed')}")
                    except Exception as exc:
                        errors.append(f"{fpath.name}: {exc}")

        lines = [
            f"📦 **Import Improvements** — `{evolved_dir}`",
            f"  📖 Read     : {len(understood)} file(s)",
            f"  🔄 Deployed : {len(deployed)} file(s)",
        ]
        if deployed:
            lines.append("  ✅ " + ", ".join(deployed[:5]))
        if errors:
            lines.append(f"  ⚠️ Errors ({len(errors)}): " + "; ".join(errors[:3]))
        if not understood and not errors:
            lines.append("  ℹ️ No improvement files found yet.")
        return "\n".join(lines)

    # ──────────────────────────────────────
    # STRUCTURAL AWARENESS COMMANDS
    # ──────────────────────────────────────

    def _cmd_sa_structure(self, _text: str = "") -> str:
        """Show full component inventory."""
        if self.structural_awareness:
            return self.structural_awareness.component_report(self)
        return "[StructuralAwareness not available]"

    def _cmd_sa_threads(self, _text: str = "") -> str:
        """Show all active threads."""
        if self.structural_awareness:
            return self.structural_awareness.thread_report()
        lines = [f"🧵 Active threads ({threading.active_count()}):"]
        for t in threading.enumerate():
            lines.append(f"  • {t.name} ({'alive' if t.is_alive() else 'dead'})")
        return "\n".join(lines)

    def _cmd_sa_loops(self, _text: str = "") -> str:
        """Show background loop status."""
        if self.structural_awareness:
            return self.structural_awareness.loop_report(self)
        return "[StructuralAwareness not available]"

    def _cmd_sa_modules(self, _text: str = "") -> str:
        """Show loaded Niblit modules."""
        if self.structural_awareness:
            return self.structural_awareness.module_report()
        return "[StructuralAwareness not available]"

    def _cmd_sa_commands(self, _text: str = "") -> str:
        """Show all registered commands."""
        if self.structural_awareness:
            return self.structural_awareness.command_report(router=self.router)
        if self.router and hasattr(self.router, "help_text"):
            return self.router.help_text()
        return self.help_text()

    def _cmd_sa_dashboard(self, _text: str = "") -> str:
        """Show full runtime dashboard."""
        if self.structural_awareness:
            return self.structural_awareness.runtime_dashboard(
                core=self, router=self.router
            )
        return self._cmd_status("")

    def _cmd_sa_flow(self, _text: str = "") -> str:
        """Show operational flow description."""
        if self.structural_awareness:
            return self.structural_awareness.operational_flow()
        return "[StructuralAwareness not available]"

    def _cmd_sa_resources(self, _text: str = "") -> str:
        """Show resource usage."""
        if self.structural_awareness:
            return self.structural_awareness.resource_report()
        return "[StructuralAwareness not available]"

    def _cmd_sa_awareness(self, _text: str = "") -> str:
        """Show all structural awareness in one combined view."""
        if self.structural_awareness:
            sa = self.structural_awareness
            sections = [
                sa.component_report(self),
                "",
                sa.loop_report(self),
                "",
                sa.command_report(router=self.router),
                "",
                sa.resource_report(),
            ]
            return "\n".join(sections)
        return "[StructuralAwareness not available]"

    def _cmd_sa_scripts(self, _text: str = "") -> str:
        """List every repo script and its function."""
        if self.structural_awareness and hasattr(self.structural_awareness, "all_scripts_report"):
            return self.structural_awareness.all_scripts_report()
        return "[StructuralAwareness not available]"

    def _cmd_deploy_bridge(self, text: str = "") -> str:
        """Cross-deployment state bridge commands."""
        bridge = getattr(self, "deployment_bridge", None)
        if bridge is None:
            return "[DeploymentBridge not available]"
        sub = (text or "").strip().lower()
        if not sub or sub == "status":
            return bridge.status()
        if sub == "save":
            return bridge.save(self)
        if sub == "load":
            return bridge.load(self)
        return f"Usage: deploy-bridge [status|save|load]\n{bridge.status()}"

    def _cmd_autonomous_network(self, text: str = "") -> str:
        """Autonomous network builder commands."""
        net = getattr(self, "autonomous_network", None)
        if net is None:
            return "[AutonomousNetworkBuilder not available]"
        sub = (text or "").strip().lower()
        if not sub or sub == "status":
            return net.status()
        if sub == "start":
            net.start()
            return "✅ Autonomous network loops started"
        if sub == "stop":
            net.stop()
            return "⏹ Autonomous network loops stopped"
        if sub == "reflect":
            return net.reflect()
        return f"Usage: autonomous-network [status|start|stop|reflect]\n{net.status()}"

    def _cmd_module_autonomy(self, text: str = "") -> str:
        """Module autonomy framework commands."""
        ma = getattr(self, "module_autonomy", None)
        if ma is None:
            return "[ModuleAutonomy not available]"
        sub = (text or "").strip().lower()
        if not sub or sub == "status":
            return ma.report()
        if sub == "start":
            ma.start()
            return "✅ Module autonomy loops started"
        if sub == "stop":
            ma.stop()
            return "⏹ Module autonomy loops stopped"
        if sub.startswith("module "):
            return ma.module_status(sub[len("module "):].strip())
        return f"Usage: module-autonomy [status|start|stop|module <name>]\n{ma.report()}"

    # ──────────────────────────────────────
    # EXTENDED AUTONOMOUS LEARNING COMMANDS
    # ──────────────────────────────────────

    def _cmd_autonomous_self_learn(self, _text: str) -> str:
        """Run the structural self-learn sequence immediately."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "run_self_learn_sequence"):
            return "[❌ Self-learn sequence not available in this engine version]"
        result = self.autonomous_engine.run_self_learn_sequence()
        return result or "✅ Self-learn sequence completed"

    def _cmd_autonomous_evolve_sequence(self, _text: str) -> str:
        """Run the structured evolve sequence immediately."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "run_evolve_sequence"):
            return "[❌ Evolve sequence not available in this engine version]"
        result = self.autonomous_engine.run_evolve_sequence()
        return result or "✅ Evolve sequence completed"

    def _cmd_autonomous_command_awareness(self, _text: str) -> str:
        """Trigger ALE Step 13: catalogue all registered commands into KnowledgeDB."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_command_awareness"):
            return "[❌ Command awareness step not available]"
        result = self.autonomous_engine._autonomous_command_awareness()  # pylint: disable=protected-access
        return result or "✅ Command awareness complete"

    def _cmd_autonomous_command_exec(self, _text: str) -> str:
        """Trigger ALE Step 14: execute safe diagnostic commands autonomously."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_command_execution"):
            return "[❌ Command execution step not available]"
        result = self.autonomous_engine._autonomous_command_execution()  # pylint: disable=protected-access
        return result or "✅ Command execution complete"

    def _cmd_autonomous_topic_seed(self, _text: str) -> str:
        """Trigger ALE Step 15: derive new topics from KB and seed to ALE + SLSA + KB queue."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_topic_seeding"):
            return "[❌ Topic seeding step not available]"
        result = self.autonomous_engine._autonomous_topic_seeding()  # pylint: disable=protected-access
        return result or "✅ Topic seeding complete"

    def _cmd_autonomous_serpex_research(self, _text: str) -> str:
        """Trigger ALE Step 27: Serpex-backed validated web research with relevance filter."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_serpex_research"):
            return "[❌ Serpex research step not available]"
        return self.autonomous_engine._autonomous_serpex_research()  # pylint: disable=protected-access

    def _cmd_autonomous_serpex_search(self, text: str) -> str:
        """Live Serpex search with relevance filter.  Pass the query after 'serpex-search'."""
        query = text.strip()
        # Allow "autonomous-learn serpex-search <query>" — strip prefix if present
        for prefix in ("autonomous-learn serpex-search", "serpex-search"):
            if query.lower().startswith(prefix):
                query = query[len(prefix):].strip()
                break
        if not query:
            return "Usage: autonomous-learn serpex-search <query>"
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        agent = (
            self.autonomous_engine._get_serpex_agent()  # pylint: disable=protected-access
            if hasattr(self.autonomous_engine, "_get_serpex_agent")
            else None
        )
        if not agent:
            return "[Serpex agent unavailable — set SERPEX_API_KEY]"
        try:
            results = agent.search_web(query)
            valid = [r for r in (results or []) if isinstance(r, dict) and "error" not in r]
            if not valid:
                return f"No relevant Serpex results for: {query!r}"
            lines = [
                f"  [{i+1}] {r.get('title','(no title)')} — {r.get('snippet','')[:120]}"
                for i, r in enumerate(valid[:5])
            ]
            return f"🌐 Serpex results for {query!r}:\n" + "\n".join(lines)
        except Exception as exc:
            return f"[Serpex search error: {exc}]"

    def _cmd_generate_code(self, spec: str) -> str:
        """Generate code: 'python module name=my_mod docstring=Does X'"""
        if not self.code_generator:
            return "[CodeGenerator not available]"
        # Parse spec: first word is language, second is template (optional), rest are key=value
        parts = spec.split()
        if not parts:
            return "Usage: generate code <language> [template] [key=value ...]"
        language = parts[0]
        template = "module"
        kwargs = {}
        for part in parts[1:]:
            if "=" in part:
                k, _, v = part.partition("=")
                kwargs[k.strip()] = v.strip()
            elif not kwargs:  # Second positional arg = template
                template = part
        result = self.code_generator.generate(language, template, **kwargs)
        if not result["success"]:
            return f"❌ {result.get('error', 'Generation failed')}"
        name = kwargs.get("name", "unnamed")
        code = result["code"]
        ext = self.code_generator.get_extension(language)
        # Optionally save to generated/
        if self.file_manager:
            fpath = f"generated/{name}{ext}"
            self.file_manager.write(fpath, code)
            return f"✅ Generated {language}/{template} → saved to {fpath}\n\n```\n{code[:600]}\n```"
        return f"✅ Generated {language}/{template}:\n\n```\n{code[:600]}\n```"

    def _cmd_run_code(self, spec: str) -> str:
        """Run code: 'python print(\"hello\")' — auto-fixes syntax errors if needed."""
        if not self.code_compiler:
            return "[CodeCompiler not available]"
        parts = spec.split(None, 1)
        if len(parts) < 2:
            return "Usage: run code <language> <code>"
        language, code = parts[0], parts[1]
        # Use compile_with_autofix so syntax errors are corrected before execution
        result = self.code_compiler.compile_with_autofix(language, code)
        return result.format_output()

    def _cmd_fix_code(self, spec: str) -> str:
        """Fix and run code: 'fix code python <code>' — diagnoses and auto-repairs errors."""
        if not self.code_compiler:
            return "[CodeCompiler not available]"
        parts = spec.split(None, 1)
        if len(parts) < 2:
            return "Usage: fix code <language> <code>"
        language, code = parts[0], parts[1]
        if self.code_error_fixer:
            report = self.code_error_fixer.auto_fix_and_run(language, code, self.code_compiler)
            lines = []
            icon = "✅" if report["success"] else "❌"
            lines.append(f"{icon} Fix & Run ({language}) — {report['elapsed_ms']:.0f}ms")
            if report["fix_applied"]:
                lines.append(f"🔧 Fix applied: {report['explanation']}")
                lines.append(f"📋 Fixed code:\n```\n{report['final_code'][:400]}\n```")
            if report["output"]:
                lines.append(f"📤 Output:\n{report['output'].strip()}")
            if report["error"] and not report["success"]:
                lines.append(f"❗ Error: {report['error']}")
            return "\n".join(lines)
        # Fallback to plain compile_with_autofix
        result = self.code_compiler.compile_with_autofix(language, code)
        return result.format_output()

    def _cmd_validate_code(self, spec: str) -> str:
        """Validate syntax: 'validate python def foo(): pass'"""
        if not self.code_compiler:
            return "[CodeCompiler not available]"
        parts = spec.split(None, 1)
        if len(parts) < 2:
            return "Usage: validate <language> <code>"
        language, code = parts[0], parts[1]
        result = self.code_compiler.validate_syntax(language, code)
        if result["valid"] is True:
            return f"✅ Syntax valid ({language})"
        if result["valid"] is False:
            return f"❌ Syntax error ({language}): {result['error']}"
        return f"ℹ️ {result['error']}"

    def _cmd_study_language(self, language: str) -> str:
        """Study a programming language."""
        if not self.code_generator:
            return "[CodeGenerator not available]"
        return self.code_generator.study_language(language)

    def _cmd_list_templates(self, language: str = "") -> str:
        """List available code templates."""
        if not self.code_generator:
            return "[CodeGenerator not available]"
        return self.code_generator.list_templates(language or None)

    def _cmd_available_languages(self, _text: str = "") -> str:
        """Show available languages for code compiler."""
        lines = []
        if self.code_generator:
            from modules.code_generator import SUPPORTED_LANGUAGES  # pylint: disable=import-outside-toplevel
            lines.append(f"📝 **Generate**: {', '.join(SUPPORTED_LANGUAGES)}")
        if self.code_compiler:
            avail = self.code_compiler.available_languages()
            avail_str = ", ".join(k for k, v in avail.items() if v)
            unavail_str = ", ".join(k for k, v in avail.items() if not v)
            lines.append(f"▶️  **Run** (available): {avail_str}")
            if unavail_str:
                lines.append(f"   (unavailable): {unavail_str}")
        return "\n".join(lines) if lines else "[Code modules not available]"

    # ──────────────────────────────────────
    # FILE MANAGER COMMANDS
    # ──────────────────────────────────────

    def _cmd_read_file(self, filepath: str) -> str:
        """Read and display a file."""
        if not self.file_manager:
            return "[FilesystemManager not available]"
        result = self.file_manager.read(filepath)
        if not result["success"]:
            return f"❌ {result['error']}"
        content = result["content"]
        if isinstance(content, bytes):
            return f"📄 {filepath} ({result['size']} bytes, binary)"
        content_str: str = content  # narrowed to str by isinstance check above
        preview = content_str[:1000] if len(content_str) > 1000 else content_str
        suffix = "...[truncated]" if len(content_str) > 1000 else ""
        return f"📄 **{filepath}** ({result['size']} chars):\n```\n{preview}{suffix}\n```"

    def _cmd_write_file(self, spec: str) -> str:
        """Write a file: '<filepath> <content>'"""
        if not self.file_manager:
            return "[FilesystemManager not available]"
        parts = spec.split(None, 1)
        if len(parts) < 2:
            return "Usage: write file <filepath> <content>"
        filepath, content = parts[0], parts[1]
        result = self.file_manager.write(filepath, content)
        if result["success"]:
            return f"✅ Written {result['bytes']} bytes → {result['path']}"
        return f"❌ Write failed: {result['error']}"

    def _cmd_list_files(self, dirpath: str = ".") -> str:
        """List files in a directory."""
        if not self.file_manager:
            return "[FilesystemManager not available]"
        result = self.file_manager.list_dir(dirpath)
        if not result["success"]:
            return f"❌ {result['error']}"
        entries = result["entries"]
        if not entries:
            return f"📁 {result['path']} — empty"
        lines = [f"📁 **{result['path']}** ({len(entries)} entries):"]
        for e in entries[:40]:  # Cap at 40 entries
            icon = "📁" if e["type"] == "dir" else "📄"
            size = f" ({e['size']} B)" if e["type"] == "file" else ""
            lines.append(f"  {icon} {e['name']}{size}")
        if len(entries) > 40:
            lines.append(f"  ... and {len(entries) - 40} more")
        return "\n".join(lines)

    def _cmd_execute_file(self, filepath: str) -> str:
        """Execute a file."""
        if not self.file_manager:
            return "[FilesystemManager not available]"
        result = self.file_manager.execute(filepath)
        icon = "✅" if result["success"] else "❌"
        lines = [f"{icon} **Execute**: {filepath}"]
        if result["stdout"]:
            lines.append(f"\n📤 Output:\n{result['stdout'].strip()}")
        if result["stderr"]:
            lines.append(f"\n⚠️ Stderr:\n{result['stderr'].strip()}")
        if result.get("error"):
            lines.append(f"\n❗ {result['error']}")
        return "\n".join(lines)

    def _cmd_file_environment(self, _text: str = "") -> str:
        """Show filesystem environment info."""
        if not self.file_manager:
            return "[FilesystemManager not available]"
        return self.file_manager.environment_info()

    # ──────────────────────────────────────
    # SOFTWARE STUDIER COMMANDS
    # ──────────────────────────────────────

    def _cmd_study_software(self, category: str) -> str:
        """Study a software category."""
        if not self.software_studier:
            return "[SoftwareStudier not available]"
        return self.software_studier.study_category(category)

    def _cmd_software_categories(self, _text: str = "") -> str:
        """List software study categories."""
        if not self.software_studier:
            return "[SoftwareStudier not available]"
        return self.software_studier.list_categories()

    def _cmd_analyze_architecture(self, architecture: str) -> str:
        """Analyze a software architecture."""
        if not self.software_studier:
            return "[SoftwareStudier not available]"
        return self.software_studier.analyze_architecture(architecture)

    def _cmd_design_software(self, description: str) -> str:
        """Generate a software design outline."""
        if not self.software_studier:
            return "[SoftwareStudier not available]"
        return self.software_studier.design_software(description)

    def _cmd_software_studied(self, _text: str = "") -> str:
        """Show what software has been studied."""
        if not self.software_studier:
            return "[SoftwareStudier not available]"
        return self.software_studier.what_ive_studied()

    # ──────────────────────────────────────
    # EVOLVE ENGINE COMMANDS
    # ──────────────────────────────────────

    def _cmd_evolve_step(self, _text: str = "") -> str:
        """Run one evolution step."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        try:
            # Refresh references before stepping
            self.evolve_engine.refresh_from_core()
            result = self.evolve_engine.step()
            return (
                f"🧬 **Evolution step {result['iteration']}**\n"
                f"  Direction: {result['direction']}\n"
                f"  Actions ({len(result['actions'])}):\n"
                + "\n".join(f"    • {a}" for a in result["actions"])
            )
        except Exception as exc:
            log.error("Evolve step failed: %s", exc)
            return f"[Evolve error: {exc}]"

    def _cmd_evolve_start(self, _text: str = "") -> str:
        """Start background evolution."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        self.evolve_engine.refresh_from_core()
        ok = self.evolve_engine.start_background_evolution()
        return "✅ Background evolution started." if ok else "⚠️ Evolution already running."

    def _cmd_evolve_stop(self, _text: str = "") -> str:
        """Stop background evolution."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        self.evolve_engine.stop_background_evolution()
        return "✅ Background evolution stopped."

    def _cmd_evolve_status(self, _text: str = "") -> str:
        """Show evolution status."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        self.evolve_engine.refresh_from_core()
        status = self.evolve_engine.get_status()
        lines = [
            "🧬 **EvolveEngine Status:**",
            f"  Running    : {'✅ Yes' if status['running'] else '❌ No'}",
            f"  Iterations : {status['iteration']}",
            f"  Stats      : {status['stats']}",
            f"  Last Dir   : {status.get('last_direction', 'none')}",
            "  Modules    :",
        ]
        for mod, avail in status.get("available_modules", {}).items():
            lines.append(f"    {'✅' if avail else '❌'} {mod}")
        return "\n".join(lines)

    def _cmd_evolve_history(self, _text: str = "") -> str:
        """Show evolution history."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        return self.evolve_engine.summarize_history()

    def _cmd_research_code(self, spec: str) -> str:
        """Research a programming language from the internet."""
        if not self.researcher:
            return "[Researcher not available]"
        parts = spec.split(None, 1)
        language = parts[0] if parts else "python"
        topic = parts[1] if len(parts) > 1 else "best practices"
        if hasattr(self.researcher, "research_code_and_feed_generator"):
            return self.researcher.research_code_and_feed_generator(
                language, topic, code_generator=self.code_generator
            )
        return "[research_code not available — upgrade self_researcher.py]"

    def _cmd_help(self, _text: str) -> str:
        """Help command."""
        return self.help_text()

    def _cmd_loops_show(self) -> str:
        self._loops_verbose = True
        logging.disable(logging.NOTSET)
        try:
            from niblit_io import NiblitIO as _NiblitIO
            _NiblitIO._quiet = False  # pylint: disable=protected-access
        except Exception:
            pass
        return "✅ Loop output visible"

    def _cmd_loops_hide(self) -> str:
        self._loops_verbose = False
        logging.disable(logging.CRITICAL)
        try:
            from niblit_io import NiblitIO as _NiblitIO
            _NiblitIO._quiet = True  # pylint: disable=protected-access
        except Exception:
            pass
        return "⏹️ Loop output hidden (loops still running)"

    def _cmd_loops_status(self) -> str:
        vis = "visible" if getattr(self, '_loops_verbose', True) else "hidden"
        # Build a live list of which loops are actually running
        loop_status = []
        # Health monitor loop
        loop_status.append("health")
        # Brain trainer background loop
        if getattr(self, "brain", None) and getattr(
            getattr(self, "brain", None), "brain_trainer", None
        ):
            loop_status.append("trainer")
        # Autonomous learning engine
        ale = getattr(self, "autonomous_engine", None)
        if ale and ale.running:
            loop_status.append("ale (running)")
        else:
            loop_status.append("ale (stopped)")
        # Auto-research in SelfResearcher
        researcher = getattr(self, "researcher", None)
        if researcher and getattr(researcher, "_auto_research_enabled", False):
            loop_status.append("auto_research (enabled)")
        else:
            loop_status.append("auto_research (disabled)")
        # Memory dump monitoring
        loop_status.append("dump_monitoring")
        # Self-heal loop
        loop_status.append("self_heal")
        # Trading brain
        brain = getattr(self, "trading_brain", None)
        if brain and getattr(brain, "running", False):
            loop_status.append("trading_brain (running)")
        # Realtime stream
        stream = getattr(self, "_realtime_stream", None)
        if stream and getattr(stream, "running", False):
            loop_status.append("realtime_stream (running)")
        return (
            f"Loop output: {vis}\n"
            f"Active loops:\n"
            + "\n".join(f"  • {l}" for l in loop_status)
        )

    def _loop_notify(self, msg: str) -> None:
        """Push a notification to the deque if loops_verbose is enabled."""
        if getattr(self, '_loops_verbose', True):
            notif_deque = getattr(self, '_notifications', None)
            if notif_deque is not None:
                notif_deque.append(msg)

    def _cmd_routing_show(self) -> str:
        self._show_routing = True
        return "✅ Routing detail visible"

    def _cmd_routing_hide(self) -> str:
        self._show_routing = False
        return "⏹️ Routing detail hidden"

    def _cmd_routing_status(self) -> str:
        state = "visible" if getattr(self, '_show_routing', False) else "hidden"
        return f"Routing detail: {state}"

    def _cmd_chat_status(self) -> str:
        """Return recent chat exchange info."""
        hist = getattr(self, 'history', [])
        return f"Chat exchanges in history: {len(hist)}"

    def _cmd_notifications(self) -> str:
        """Return queued notifications."""
        notifs = getattr(self, '_notifications', None)
        if not notifs:
            return "No pending notifications"
        lines = list(notifs)
        notifs.clear()
        return "\n".join(lines) if lines else "No pending notifications"

    def _cmd_confidence(self, mode: str = "snapshot") -> str:
        """
        Return Niblit's live meta-confidence report (additive).

        Parameters
        ----------
        mode:
            'snapshot'   — overall confidence summary (default)
            'tree'       — full confidence parse tree by category
            'rich'       — extended evaluation including provenance sources
        """
        meta = getattr(self, "metacognition", None)
        if meta is None:
            return (
                "⚠️  Metacognition module not initialised.\n"
                "   Try: 'autonomous-learn start' to populate knowledge first."
            )
        try:
            if mode == "tree":
                tree = meta.get_confidence_parse_tree()
                return json.dumps(tree, indent=2, default=str)
            if mode == "rich":
                rich = meta.evaluate_understanding_rich()
                return json.dumps(rich, indent=2, default=str)
            return meta.confidence_cli_report()
        except Exception as exc:
            return f"[confidence] Error: {exc}"

    def _cmd_swing_status(self) -> str:
        """Return status of the FilteredSwingTraderV3 (additive)."""
        trader = getattr(self, "swing_trader_v3", None)
        if trader is None:
            return "⚠️  FilteredSwingTraderV3 not initialised."
        return trader.status()

    def _cmd_swing_legs(self, last_n: int = 10) -> str:
        """Return last *last_n* trade legs as JSON (additive)."""
        trader = getattr(self, "swing_trader_v3", None)
        if trader is None:
            return "⚠️  FilteredSwingTraderV3 not initialised."
        return json.dumps(trader.get_legs(last_n), indent=2, default=str)

    def _cmd_swing_explain(self) -> str:
        """Explain the last swing entry signal (additive)."""
        trader = getattr(self, "swing_trader_v3", None)
        if trader is None:
            return "⚠️  FilteredSwingTraderV3 not initialised."
        return trader.explain_last_entry()

    def _cmd_trainer_status(self) -> str:
        """Return BackgroundTrainer status (additive)."""
        bg = getattr(self, "background_trainer", None)
        if bg is None:
            return "⚠️  BackgroundTrainer not initialised."
        return bg.status()

    # ── ALE Checkpoint CLI commands (additive) ────────────────────────────

    def _cmd_ale(self, sub: str) -> str:
        """
        ALE persistent-state commands (additive).

        Sub-commands
        ------------
        status               — show checkpoint manager status
        checkpoint / save    — force-save current state now
        resume               — try to restore from saved checkpoint
        anchor <tag>         — create a named snapshot
        restore <tag>        — restore to a named anchor
        anchors              — list saved anchors
        backtrack [N]        — step back N steps in history
        pause                — pause cycle before next step
        resume-cycle         — resume a paused cycle
        history [N]          — last N step results (default 20)
        incomplete           — list incomplete steps from last run
        """
        # pylint: disable=too-many-branches,too-many-return-statements
        ckpt = getattr(self, "ale_checkpoint", None)
        if ckpt is None:
            return (
                "⚠️  ALECheckpointManager not initialised.\n"
                "   Start the autonomous engine first: 'autonomous-learn start'"
            )

        sub = sub.strip().lower() if sub else "status"

        if sub in ("status", ""):
            return ckpt.status()

        if sub in ("checkpoint", "save"):
            ok = ckpt.save()
            return "✅ Checkpoint saved." if ok else "❌ Checkpoint save failed — check logs."

        if sub == "resume":
            ok = ckpt.try_resume()
            return "✅ Resumed from checkpoint." if ok else "ℹ️  No checkpoint found — starting fresh."

        if sub.startswith("anchor ") or sub.startswith("anchor\t"):
            tag = sub.split(None, 1)[1].strip() if len(sub.split(None, 1)) > 1 else ""
            if not tag:
                return "Usage: ale anchor <tag>"
            return ckpt.create_anchor(tag)

        if sub.startswith("restore ") or sub.startswith("restore\t"):
            tag = sub.split(None, 1)[1].strip() if len(sub.split(None, 1)) > 1 else ""
            if not tag:
                return "Usage: ale restore <tag>"
            return ckpt.restore_anchor(tag)

        if sub == "anchors":
            return ckpt.list_anchors()

        if sub.startswith("backtrack"):
            parts = sub.split()
            try:
                n = int(parts[1]) if len(parts) > 1 else 1
            except (ValueError, IndexError):
                n = 1
            return ckpt.backtrack(n)

        if sub == "pause":
            return ckpt.pause_cycle()

        if sub in ("resume-cycle", "resume cycle"):
            return ckpt.resume_cycle()

        if sub.startswith("history"):
            parts = sub.split()
            try:
                n = int(parts[1]) if len(parts) > 1 else 20
            except (ValueError, IndexError):
                n = 20
            return ckpt.get_step_history(n)

        if sub == "incomplete":
            return ckpt.get_incomplete_steps()

        return (
            f"[ale] Unknown sub-command: '{sub}'\n"
            "  ale status / ale checkpoint / ale resume / ale anchor <tag>\n"
            "  ale restore <tag> / ale anchors / ale backtrack [N]\n"
            "  ale pause / ale resume-cycle / ale history [N] / ale incomplete"
        )

    def _cmd_memory_reset(self, confirm: str = "") -> str:
        """Flush ALL of Niblit's memory, caches, and state files for a clean start.

        Sub-commands
        ------------
        memory-reset confirm   — Perform the full wipe (requires 'confirm' keyword).
        memory-reset status    — Show what would be cleared without touching anything.
        memory-reset           — Print usage / warn before clearing.

        What is cleared
        ---------------
        • KnowledgeDB / NiblitMemory in-memory state (facts, events, interactions,
          learning_log, learning_queue) and their backing JSON files.
        • LocalDB JSON file (niblit.db).
        • FusedMemory SQLite tables (events, knowledge, graph_nodes, graph_edges).
        • ALE checkpoint file (ale_state.json) so learning restarts from cycle 0.
        • Deployment bridge snapshot (niblit_deployment_bridge.json).
        • In-memory research cache (CachedOperation TTL store).
        • ALE learning_history counters and research_topics queue.
        • SelfTeacher review queue in KB.
        • SelfResearcher history list.

        After reset, Niblit starts fresh — no contaminated facts, no blob topics.
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements,protected-access
        confirm = (confirm or "").strip().lower()

        # ── STATUS (dry-run) ─────────────────────────────────────────────────
        if confirm == "status":
            lines = ["=== memory-reset status (dry-run) ==="]
            # JSON memory files
            for attr, label in (
                ("db", "KnowledgeDB / NiblitMemory"),
                ("memory", "NiblitMemory standalone"),
            ):
                obj = getattr(self, attr, None)
                path = getattr(obj, "path", None) or getattr(obj, "filename", None)
                if path:
                    size = os.path.getsize(path) if os.path.exists(path) else 0
                    data = getattr(obj, "data", None) or getattr(obj, "state", None) or {}
                    fact_count = len(data.get("facts", [])) if isinstance(data, dict) else 0
                    lines.append(f"  • {label}: {path} ({size} bytes, {fact_count} facts)")
            # FusedMemory SQLite
            fused = getattr(self, "fused_memory", None)
            if fused:
                sp = getattr(fused, "_sqlite_path", None)
                if sp and os.path.exists(sp):
                    lines.append(f"  • FusedMemory SQLite: {sp} ({os.path.getsize(sp)} bytes)")
            # ALE checkpoint
            ckpt = getattr(self, "ale_checkpoint", None)
            if ckpt:
                cp = getattr(ckpt, "checkpoint_path", None)
                if cp and os.path.exists(cp):
                    lines.append(f"  • ALE checkpoint: {cp} ({os.path.getsize(cp)} bytes)")
            # Research cache
            rc = getattr(self, "research_cache", None)
            if rc:
                lines.append(f"  • Research cache: {len(getattr(rc, '_cache', {}))} entries (in-memory)")
            lines.append("")
            lines.append("Run 'memory-reset confirm' to wipe all of the above.")
            return "\n".join(lines)

        # ── SAFETY GUARD ─────────────────────────────────────────────────────
        if confirm != "confirm":
            return (
                "⚠️  memory-reset: This will wipe ALL stored memory, knowledge, ALE state,\n"
                "   research cache, and learning history so Niblit starts completely fresh.\n\n"
                "   Run 'memory-reset status' to see what will be cleared.\n"
                "   Run 'memory-reset confirm' to proceed."
            )

        # ── PERFORM FULL WIPE ────────────────────────────────────────────────
        log.info("[MEMORY-RESET] Full memory wipe initiated by user.")
        cleared: list = []
        errors: list = []

        _BLANK_STATE = {
            "facts": [], "interactions": [], "learning_log": [],
            "learning_queue": [], "preferences": {}, "events": [], "meta": {},
        }

        # 1. KnowledgeDB / NiblitMemory in-memory + file
        for attr in ("db", "memory"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                with getattr(obj, "lock", _NoopLock()):
                    for _field in ("facts", "interactions", "learning_log",
                                  "learning_queue", "events"):
                        if hasattr(obj, "data") and isinstance(obj.data, dict):
                            obj.data[_field] = []
                        if hasattr(obj, "state") and isinstance(obj.state, dict):
                            obj.state[_field] = []
                path = getattr(obj, "path", None) or getattr(obj, "filename", None)
                if path and os.path.exists(path):
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(_BLANK_STATE, f, indent=2)
                    cleared.append(f"KnowledgeDB/NiblitMemory file: {path}")
                cleared.append(f"{attr} in-memory state cleared")
            except Exception as exc:
                errors.append(f"{attr}: {exc}")

        # 2. LocalDB file (niblit.db)
        local_db = getattr(self, "local_db", None)
        if local_db is None:
            # Try to find through common attributes
            for attr_name in ("brain_db", "local_db", "localdb"):
                local_db = getattr(self, attr_name, None)
                if local_db is not None:
                    break
        if local_db and hasattr(local_db, "path"):
            try:
                local_db.data = {
                    "interactions": [], "facts": [],
                    "learning_log": [], "preferences": {},
                }
                local_db._save()  # type: ignore[attr-defined]
                cleared.append(f"LocalDB: {local_db.path}")
            except Exception as exc:
                errors.append(f"LocalDB: {exc}")

        # 3. FusedMemory SQLite tables
        fused = getattr(self, "fused_memory", None)
        if fused and hasattr(fused, "_conn"):
            try:
                with fused._lock:
                    fused._conn.executescript(
                        "DELETE FROM events; DELETE FROM knowledge; "
                        "DELETE FROM graph_nodes; DELETE FROM graph_edges;"
                    )
                    fused._conn.commit()
                cleared.append(f"FusedMemory SQLite tables cleared ({fused._sqlite_path})")
            except Exception as exc:
                errors.append(f"FusedMemory: {exc}")
        # Also try via db.fused_memory
        db_fused = getattr(getattr(self, "db", None), "fused_memory", None)
        if db_fused and db_fused is not fused and hasattr(db_fused, "_conn"):
            try:
                with db_fused._lock:
                    db_fused._conn.executescript(
                        "DELETE FROM events; DELETE FROM knowledge; "
                        "DELETE FROM graph_nodes; DELETE FROM graph_edges;"
                    )
                    db_fused._conn.commit()
                cleared.append("NiblitMemory FusedMemory SQLite tables cleared")
            except Exception as exc:
                errors.append(f"NiblitMemory FusedMemory: {exc}")

        # 4. ALE checkpoint file
        ckpt = getattr(self, "ale_checkpoint", None)
        if ckpt:
            cp = getattr(ckpt, "checkpoint_path", None)
            if cp and os.path.exists(cp):
                try:
                    os.remove(cp)
                    cleared.append(f"ALE checkpoint: {cp}")
                except Exception as exc:
                    errors.append(f"ALE checkpoint: {exc}")
            # Reset in-memory ALE state
            try:
                ckpt._state = {
                    "cycle_count": 0,
                    "learning_history": {},
                    "research_topics": [],
                    "step_results_history": [],
                }
                cleared.append("ALE checkpoint in-memory state cleared")
            except Exception as exc:
                errors.append(f"ALE checkpoint state: {exc}")

        # 5. Deployment bridge snapshot
        from modules.deployment_bridge import _BRIDGE_FILE as _bridge_file  # type: ignore[import]
        try:
            if os.path.exists(_bridge_file):
                os.remove(_bridge_file)
                cleared.append(f"Deployment bridge: {_bridge_file}")
        except Exception as exc:
            errors.append(f"Deployment bridge: {exc}")

        # 6. In-memory research cache
        rc = getattr(self, "research_cache", None)
        if rc and hasattr(rc, "_cache"):
            try:
                rc._cache.clear()
                cleared.append("Research cache (in-memory) cleared")
            except Exception as exc:
                errors.append(f"Research cache: {exc}")

        # 7. ALE engine learning_history + research_topics
        ale = getattr(self, "autonomous_engine", None)
        if ale:
            try:
                lh = getattr(ale, "learning_history", {})
                for key in list(lh):
                    if isinstance(lh[key], int):
                        lh[key] = 0
                    elif isinstance(lh[key], str):
                        lh[key] = ""
                cleared.append("ALE learning_history counters reset")
            except Exception as exc:
                errors.append(f"ALE learning_history: {exc}")
            try:
                ale.research_topics.clear()
                cleared.append("ALE research_topics queue cleared")
            except Exception as exc:
                errors.append(f"ALE research_topics: {exc}")
            try:
                ale._last_research_results = []
                ale._cycle_count = 0
                cleared.append("ALE cycle counter + last results cleared")
            except Exception:
                pass

        # 8. SelfTeacher review queue in KB
        st = getattr(self, "self_teacher", None)
        if st:
            try:
                st._review_queue = []
                st.review_queue = []
                st.last_reviewed = {}
                cleared.append("SelfTeacher review queue cleared")
            except Exception as exc:
                errors.append(f"SelfTeacher: {exc}")

        # 9. SelfResearcher history
        researcher = getattr(self, "researcher", None)
        if researcher:
            try:
                researcher.history = []
                researcher.responses = {}
                cleared.append("SelfResearcher history cleared")
            except Exception as exc:
                errors.append(f"SelfResearcher: {exc}")

        log.info("[MEMORY-RESET] Cleared %d item(s). Errors: %d", len(cleared), len(errors))

        lines = ["✅ Memory reset complete. Niblit starts fresh.\n", "Cleared:"]
        for item in cleared:
            lines.append(f"  ✓ {item}")
        if errors:
            lines.append("\nWarnings (non-fatal):")
            for err in errors:
                lines.append(f"  ⚠ {err}")
        lines.append(
            "\n💡 Tip: Restart the autonomous engine with 'autonomous-learn start' "
            "so ALE begins from a clean state."
        )
        return "\n".join(lines)

    def _cmd_reload_params(self) -> str:
        """On-demand ParameterManager reload (additive).

        Reloads parameters from the local JSON file and optional remote URL.
        Pushes a summary notification and returns it as a string.
        """
        pm = getattr(self, "parameter_manager", None) or _parameter_manager
        if pm is None:
            return "[reload_params] ParameterManager not available"
        try:
            summary = pm.reload()
            # Also push into core._notifications so it surfaces via 'notifications' cmd
            self._loop_notify(summary)
            return summary
        except Exception as exc:
            return f"[reload_params] Error: {exc}"

    def _cmd_run_selfheal(self) -> str:
        """Explicit self-heal trigger with notification output (additive).

        Runs the SelfHealer cycle (or equivalent) and returns/pushes the
        findings.  The work runs synchronously because the user explicitly
        requested it; however heavy sub-tasks inside SelfHealer may spawn
        their own daemon threads.

        Also calls SelfMaintenance.run() to prune old interactions and
        condense memory — the pattern prescribed by Fix_Guide.txt.
        """
        parts = []

        # ── SelfHealer: repair broken/empty KB facts ──────────────────────
        healer = getattr(self, "self_healer", None)
        if healer is None:
            parts.append("[run_selfheal] SelfHealer not available — ensure modules/self_healer.py is present")
        else:
            result = None
            for method_name in ("run_cycle", "repair", "full_heal", "run"):
                fn = getattr(healer, method_name, None)
                if fn is not None:
                    try:
                        result = fn(self) if method_name == "full_heal" else fn()
                    except Exception as exc:
                        result = f"[SelfHealer.{method_name} error] {exc}"
                    break
            parts.append(result or "✅ SelfHealer cycle completed")

        # ── SelfMaintenance: prune old interactions + condense memory ─────
        maintenance = getattr(self, "self_maintenance", None)
        if maintenance is not None:
            for method_name in ("run_with_learning", "run", "diagnose"):
                fn = getattr(maintenance, method_name, None)
                if fn is not None:
                    try:
                        mresult = fn()
                        parts.append(str(mresult) if mresult else "✅ SelfMaintenance run completed")
                    except Exception as mexc:
                        parts.append(f"[SelfMaintenance.{method_name} error] {mexc}")
                    break

        summary = "\n".join(parts) or "✅ Self-heal cycle completed (no output returned)"
        self._loop_notify(str(summary))
        return str(summary)

    # ── LEAN CLI commands (additive) ──────────────────────────────────────────

    def _cmd_lean(self, cmd: str) -> str:
        """Route a 'lean ...' command to the LeanEngine.

        Sub-commands
        ------------
        lean status                              — Show LEAN engine status
        lean login                               — Authenticate with QuantConnect cloud
        lean create <name> [sym=SPY] [cash=N]    — Create a new LEAN project
        lean list                                — List LEAN projects
        lean delete <name>                       — Delete a LEAN project
        lean backtest <name> [cloud]             — Run a back-test (background)
        lean live <name> [broker=paper]          — Start live trading (background)
        lean sweep <name> key=v1,v2 key2=v1,v2  — Parameter grid sweep (background)
        lean params <name>                       — Show optimal params for a project
        lean jobs                                — Show active LEAN background jobs
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-return-statements
        engine = getattr(self, "lean_engine", None)
        if engine is None:
            return "[lean] LeanEngine not initialised — check startup logs"

        parts = cmd.strip().split()
        if not parts:
            return engine.status()
        sub = parts[0].lower()
        rest = parts[1:]

        if sub == "status":
            return engine.status()
        if sub == "login":
            uid = os.environ.get("LEAN_API_USER_ID", "")
            tok = os.environ.get("LEAN_API_TOKEN", "")
            return engine.login(uid, tok)
        if sub in ("create", "new"):
            if not rest:
                return "Usage: lean create <name> [sym=SPY] [cash=100000] [start=YYYY-MM-DD] [end=YYYY-MM-DD]"
            name = rest[0]
            kwargs: dict = {}
            for kv in rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    kwargs[k] = int(v) if v.isdigit() else v
            return engine.create_project(name, **kwargs)
        if sub == "list":
            projects = engine.list_projects()
            if not projects:
                return "No LEAN projects found in workspace."
            return "LEAN projects:\n" + "\n".join(
                f"  • {p['name']} (config={'✅' if p['has_config'] else '❌'})"
                for p in projects
            )
        if sub == "delete":
            if not rest:
                return "Usage: lean delete <project-name>"
            return engine.delete_project(rest[0])
        if sub == "backtest":
            if not rest:
                return "Usage: lean backtest <project-name> [cloud]"
            cloud = len(rest) > 1 and "cloud" in rest[1].lower()
            return engine.run_backtest(rest[0], cloud=cloud)
        if sub == "live":
            if not rest:
                return "Usage: lean live <project-name> [broker=paper]"
            broker = "paper"
            for r in rest[1:]:
                if r.startswith("broker="):
                    broker = r.split("=", 1)[1]
            return engine.run_live(rest[0], broker=broker)
        if sub == "sweep":
            if not rest:
                return (
                    "Usage: lean sweep <project-name> param=v1,v2 param2=v1,v2\n"
                    "Example: lean sweep MyStrat fast=5,10,20 slow=30,50,100"
                )
            proj = rest[0]
            grid: dict = {}
            for kv in rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    vals = v.split(",")
                    # Try to cast to int/float
                    parsed = []
                    for val in vals:
                        try:
                            parsed.append(int(val))
                        except ValueError:
                            try:
                                parsed.append(float(val))
                            except ValueError:
                                parsed.append(val)
                    grid[k] = parsed
            if not grid:
                return "No parameters provided. Example: lean sweep MyStrat fast=5,10,20"
            return engine.parameter_sweep(proj, grid)
        if sub in ("params", "optimal-params", "best-params"):
            if not rest:
                data = engine._load_optimal_params()  # pylint: disable=protected-access
                if not data:
                    return "No optimal parameters stored yet."
                lines = [f"  {proj}: score={v.get('score')} metric={v.get('metric')}"
                         for proj, v in list(data.items())[:10]]
                return "Stored optimal LEAN parameters:\n" + "\n".join(lines)
            return str(engine.get_optimal_params(rest[0]) or "No params stored for that project")
        if sub == "jobs":
            return engine.active_jobs_summary()
        return (
            "LEAN commands:\n"
            "  lean status | login | create <n> | list | delete <n>\n"
            "  lean backtest <n> [cloud] | lean live <n> [broker]\n"
            "  lean sweep <n> p=v1,v2 | lean params [n] | lean jobs\n"
            "  lean deploy <sub>   — QuantConnect REST API (see 'lean deploy status')"
        )

    # ── LeanDeployEngine commands (additive) ─────────────────────────────────

    def _cmd_lean_deploy(self, cmd: str) -> str:
        """Route 'lean deploy ...' to LeanDeployEngine (QuantConnect REST API).

        Sub-commands
        ------------
        lean deploy status
        lean deploy projects
        lean deploy create <name>
        lean deploy backtest <projectId>
        lean deploy live-list
        lean deploy live-read <projectId> <deployId>
        lean deploy live-stop <projectId>
        lean deploy liquidate <projectId>
        lean deploy templates
        lean deploy generate <template> <name> [symbol=X] [fast=N] [slow=N]
        lean deploy quick <template> <name> [brokerage=PaperBrokerage] [symbol=X]
        lean deploy monitor <projectId> <deployId>
        lean deploy orders <projectId>
        lean deploy compile <projectId>
        """
        # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
        engine = getattr(self, "lean_deploy_engine", None)
        if engine is None:
            return "[lean deploy] LeanDeployEngine not initialised — check startup logs"

        parts = cmd.strip().split()
        if not parts:
            return engine.status()
        sub = parts[0].lower()
        rest = parts[1:]

        if sub == "status":
            return engine.status()
        if sub in ("projects", "list"):
            return engine.list_projects()
        if sub == "create":
            if not rest:
                return "Usage: lean deploy create <name>"
            return engine.create_project(rest[0])
        if sub in ("backtest", "bt"):
            if not rest:
                return "Usage: lean deploy backtest <projectId>"
            return engine.create_backtest(int(rest[0]))
        if sub in ("backtests", "list-backtests"):
            if not rest:
                return "Usage: lean deploy backtests <projectId>"
            return engine.list_backtests(int(rest[0]))
        if sub == "read-backtest":
            if len(rest) < 2:
                return "Usage: lean deploy read-backtest <projectId> <backtestId>"
            return engine.read_backtest(int(rest[0]), rest[1])
        if sub in ("live-list", "live", "running"):
            return engine.list_live_algorithms()
        if sub in ("live-read", "live-status"):
            if len(rest) < 2:
                return "Usage: lean deploy live-read <projectId> <deployId>"
            return engine.read_live_algorithm(int(rest[0]), rest[1])
        if sub in ("live-stop", "stop"):
            if not rest:
                return "Usage: lean deploy live-stop <projectId>"
            return engine.stop_live_algorithm(int(rest[0]))
        if sub == "liquidate":
            if not rest:
                return "Usage: lean deploy liquidate <projectId>"
            return engine.liquidate_live_algorithm(int(rest[0]))
        if sub == "compile":
            if not rest:
                return "Usage: lean deploy compile <projectId>"
            return engine.compile_project(int(rest[0]))
        if sub in ("templates", "list-templates"):
            return engine.list_templates()
        if sub == "generate":
            if len(rest) < 2:
                return "Usage: lean deploy generate <template> <name> [key=val ...]"
            tmpl, name = rest[0], rest[1]
            kwargs: dict = {}
            for kv in rest[2:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        kwargs[k] = int(v)
                    except ValueError:
                        try:
                            kwargs[k] = float(v)
                        except ValueError:
                            kwargs[k] = v
            return engine.generate_algorithm(template=tmpl, name=name, **kwargs)
        if sub == "quick":
            if len(rest) < 2:
                return "Usage: lean deploy quick <template> <name> [brokerage=PaperBrokerage] [symbol=X]"
            tmpl, name = rest[0], rest[1]
            broker = "PaperBrokerage"
            kwargs2: dict = {}
            for kv in rest[2:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k == "brokerage":
                        broker = v
                    else:
                        try:
                            kwargs2[k] = int(v)
                        except ValueError:
                            kwargs2[k] = v
            return engine.quick_deploy(template=tmpl, name=name, brokerage=broker, **kwargs2)
        if sub == "monitor":
            if len(rest) < 2:
                return "Usage: lean deploy monitor <projectId> <deployId>"
            return engine.start_monitor(int(rest[0]), rest[1])
        if sub == "stop-monitor":
            if not rest:
                return "Usage: lean deploy stop-monitor <deployId>"
            return engine.stop_monitor(rest[0])
        if sub == "orders":
            if not rest:
                return "Usage: lean deploy orders <projectId>"
            return engine.read_live_orders(int(rest[0]))
        return engine.status()

    # ── MarketDataProviders commands (additive) ───────────────────────────────

    def _cmd_market_data(self, cmd: str) -> str:
        """Route 'market ...' commands to MarketDataProviders.

        Sub-commands
        ------------
        market status
        market overview [sym1 sym2 ...]
        market fetch <symbol> [provider=yfinance] [interval=1d] [bars=50]
        market multi <sym1,sym2,...> [provider] [interval] [bars]
        market info <symbol>               — Yahoo Finance fundamental info
        market oanda-candles <instrument> [interval=H1] [bars=100]
        market oanda-account
        market oanda-order <instrument> <units>
        market oanda-instruments
        market ccxt-exchanges
        market ccxt-tickers [exchange=binance]
        market alpaca-account
        market alpaca-order <symbol> <qty> [side=buy]
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-return-statements
        mdp = getattr(self, "market_data_providers", None)
        if mdp is None:
            return "[market] MarketDataProviders not initialised — check startup logs"

        parts = cmd.strip().split()
        if not parts:
            return mdp.status()
        sub = parts[0].lower()
        rest = parts[1:]

        if sub == "status":
            return mdp.status()
        if sub == "overview":
            syms = rest if rest else None
            return mdp.market_overview(syms)
        if sub == "fetch":
            if not rest:
                return "Usage: market fetch <symbol> [provider=yfinance] [interval=1d] [bars=50]"
            sym = rest[0]
            provider = "auto"
            interval = "1d"
            bars = 50
            for kv in rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k == "provider":
                        provider = v
                    elif k == "interval":
                        interval = v
                    elif k == "bars":
                        bars = int(v)
            result = mdp.fetch(sym, provider=provider, interval=interval, bars=bars)
            if hasattr(result, "to_string"):
                return f"Fetched {sym} ({provider}/{interval}):\n{result.tail(5).to_string()}"
            return str(result)[:800]
        if sub == "multi":
            if not rest:
                return "Usage: market multi <sym1,sym2,...> [provider] [interval] [bars]"
            syms = rest[0].split(",")
            provider = rest[1] if len(rest) > 1 else "yfinance"
            interval = rest[2] if len(rest) > 2 else "1d"
            bars = int(rest[3]) if len(rest) > 3 else 20
            results = mdp.fetch_multi(syms, provider=provider, interval=interval, bars=bars)
            lines = [f"Multi-fetch ({provider}/{interval}):"]
            for s, r in results.items():
                if hasattr(r, "tail"):
                    close = r["Close"].iloc[-1] if "Close" in r.columns else "?"
                    lines.append(f"  {s}: latest_close={close}")
                else:
                    lines.append(f"  {s}: {str(r)[:80]}")
            return "\n".join(lines)
        if sub == "info":
            if not rest:
                return "Usage: market info <symbol>"
            info = mdp.yfinance_info(rest[0])
            if isinstance(info, dict):
                keys = ["longName", "sector", "marketCap", "trailingPE",
                        "dividendYield", "52WeekHigh", "52WeekLow"]
                lines = [f"Yahoo Finance info — {rest[0]}:"]
                for k in keys:
                    if k in info:
                        lines.append(f"  {k}: {info[k]}")
                return "\n".join(lines) if len(lines) > 1 else str(info)[:400]
            return str(info)[:400]
        if sub in ("oanda-candles", "oanda"):
            instr = rest[0] if rest else "EUR_USD"
            interval = rest[1] if len(rest) > 1 else "H1"
            bars = int(rest[2]) if len(rest) > 2 else 50
            result = mdp.oanda_candles(instr, interval=interval, bars=bars)
            return f"OANDA {instr} {interval}: {str(result)[:600]}"
        if sub == "oanda-account":
            return str(mdp.oanda_account_summary())[:600]
        if sub == "oanda-order":
            if len(rest) < 2:
                return "Usage: market oanda-order <instrument> <units>"
            return str(mdp.oanda_place_order(rest[0], int(rest[1])))[:400]
        if sub == "oanda-instruments":
            return "OANDA instruments:\n" + "\n".join(
                f"  {i}" for i in mdp.available_instruments_oanda()
            )
        if sub == "ccxt-exchanges":
            exchanges = mdp.ccxt_exchanges()
            return f"CCXT exchanges ({len(exchanges)}):\n" + " ".join(exchanges[:30])
        if sub == "ccxt-tickers":
            exchange = rest[0] if rest else "binance"
            tickers = mdp.ccxt_tickers(exchange)
            if isinstance(tickers, dict):
                return f"CCXT {exchange} tickers ({len(tickers)} pairs)"
            return str(tickers)[:300]
        if sub == "alpaca-account":
            return str(mdp.alpaca_account())[:400]
        if sub == "alpaca-order":
            if len(rest) < 2:
                return "Usage: market alpaca-order <symbol> <qty> [side=buy]"
            sym = rest[0]
            qty = float(rest[1])
            side = rest[2] if len(rest) > 2 else "buy"
            return str(mdp.alpaca_place_order(sym, qty, side=side))[:400]
        return mdp.status()

    # ── TradingStudy commands (additive) ─────────────────────────────────────

    def _cmd_trading_study(self, cmd: str) -> str:
        """Route 'trading study ...' commands to TradingStudy.

        Sub-commands
        ------------
        trading study status
        trading study brain           — Study last TradingBrain cycle
        trading study market [syms]   — Market snapshot study
        trading study lean <name>     — Study LEAN backtest results
        trading study live <deployId> — Study live algorithm status
        trading study deep            — Full deep study session
        trading study journal [n=50]  — Analyse trade journal
        trading study meta            — Metacognition check
        trading study auto-start [interval=300]
        trading study auto-stop
        trading study log <symbol> <side> <price> <qty> [pnl=N]
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-return-statements
        ts = getattr(self, "trading_study", None)
        if ts is None:
            return "[trading study] TradingStudy not initialised — check startup logs"

        parts = cmd.strip().split()
        if not parts:
            return ts.status()
        sub = parts[0].lower()
        rest = parts[1:]

        if sub == "status":
            return ts.status()
        if sub == "brain":
            return ts.study_last_trade_brain_cycle()
        if sub == "market":
            syms = rest if rest else None
            return ts.study_market_snapshot(syms)
        if sub == "lean":
            name = rest[0] if rest else ""
            if not name:
                return "Usage: trading study lean <project-name>"
            return ts.study_lean_backtest(name)
        if sub == "live":
            if not rest:
                return "Usage: trading study live <deployId>"
            deploy_id = rest[0]
            status_text = " ".join(rest[1:]) or "manual study trigger"
            return ts.study_live_algorithm(deploy_id, status_text)
        if sub == "deep":
            return ts.deep_study_session()
        if sub == "journal":
            n = int(rest[0]) if rest and rest[0].isdigit() else 50
            return ts.analyse_journal(n)
        if sub == "meta":
            return ts.metacognition_check()
        if sub in ("auto-start", "auto"):
            secs = int(rest[0]) if rest and rest[0].isdigit() else 300
            return ts.start_auto_study(interval_secs=secs)
        if sub == "auto-stop":
            return ts.stop_auto_study()
        if sub == "log":
            if len(rest) < 4:
                return "Usage: trading study log <symbol> <side> <price> <qty> [pnl=N]"
            sym, side, price, qty = rest[0], rest[1], float(rest[2]), float(rest[3])
            pnl = None
            for kv in rest[4:]:
                if kv.startswith("pnl="):
                    try:
                        pnl = float(kv.split("=", 1)[1])
                    except ValueError:
                        pass
            return ts.log_trade(sym, side, price, qty, pnl=pnl)
        return ts.status()

    # ── Game engine commands (additive) ───────────────────────────────────────

    def _cmd_game(self, cmd: str) -> str:
        """Route a 'game ...' command to the GameEngine.

        Sub-commands
        ------------
        game status              — Engine status
        game list                — List active entities
        game add <name> [x=N] [y=N] [vx=N] [vy=N] [tag=v]
                                 — Add an entity
        game remove <name>       — Remove an entity
        game step [N]            — Advance N ticks
        game reset               — Reset the world
        game save [path]         — Serialise world to JSON
        game load <path>         — Restore world from JSON
        game log [N]             — Show last N event log entries
        game score [+N]          — Show score or add N points
        game play <template>     — Load a built-in template (pong/gravity/adventure)
        game action <entity> k=v — Apply action dict to an entity
        """
        # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
        engine = getattr(self, "game_engine", None)
        if engine is None:
            return "[game] GameEngine not initialised — check startup logs"

        parts = cmd.strip().split()
        if not parts:
            return engine.status()
        sub = parts[0].lower()
        rest = parts[1:]

        if sub in ("status", ""):
            return engine.status()
        if sub in ("list", "ls", "entities"):
            return engine.list_entities()
        if sub == "add":
            if not rest:
                return "Usage: game add <name> [x=N] [y=N] [vx=N] [vy=N] [tag=v]"
            name = rest[0]
            kwargs: Dict[str, Any] = {}
            for kv in rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        kwargs[k] = float(v)
                    except ValueError:
                        kwargs[k] = v
            return engine.add_entity(name, **kwargs)
        if sub == "remove":
            if not rest:
                return "Usage: game remove <name>"
            return engine.remove_entity(rest[0])
        if sub == "step":
            n = 1
            if rest:
                try:
                    n = int(rest[0])
                except ValueError:
                    pass
            return engine.step(n)
        if sub == "reset":
            return engine.reset()
        if sub == "save":
            return engine.save_state(rest[0] if rest else None)
        if sub == "load":
            if not rest:
                return "Usage: game load <path>"
            return engine.load_state(rest[0])
        if sub in ("log", "events"):
            n = 20
            if rest:
                try:
                    n = int(rest[0])
                except ValueError:
                    pass
            return engine.event_log(n)
        if sub == "score":
            if rest and rest[0].lstrip("+-").isdigit():
                return engine.add_score(float(rest[0]))
            return f"🏆 Current score: {engine.score}"
        if sub == "play":
            if not rest:
                return "Usage: game play <template>  (pong / gravity / adventure)"
            return engine.play(rest[0])
        if sub == "action":
            if len(rest) < 2:
                return "Usage: game action <entity_name> key=value [key=value ...]"
            ename = rest[0]
            action: Dict[str, Any] = {}
            for kv in rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        action[k] = float(v)
                    except ValueError:
                        action[k] = v
            return engine.apply_action(ename, action)
        return (
            "Game commands:\n"
            "  game status | list | add <n> [x= y= vx= vy=] | remove <n>\n"
            "  game step [N] | reset | save [path] | load <path>\n"
            "  game log [N] | score [+N] | play <template> | action <n> k=v"
        )

    # ── Universal file manager commands (additive) ────────────────────────────

    def _cmd_file(self, cmd: str) -> str:
        """Route a 'file ...' command to the UniversalFileManager.

        Sub-commands
        ------------
        file status              — Handler registry summary
        file formats             — List all registered format handlers
        file detect <path>       — Detect file type and handler
        file read <path>         — Read and display a file
        file write <path> <txt>  — Write text content to a file
        file edit <path> OLD==>NEW
                                 — Replace first occurrence of OLD with NEW
        file execute <path> [args]
                                 — Execute a script file
        """
        # pylint: disable=too-many-branches,too-many-return-statements
        fm = getattr(self, "universal_file_manager", None)
        if fm is None:
            return "[file] UniversalFileManager not initialised — check startup logs"

        parts = cmd.strip().split(None, 2)
        if not parts:
            return fm.status()
        sub = parts[0].lower()
        rest_str = parts[1] if len(parts) > 1 else ""
        tail_str = parts[2] if len(parts) > 2 else ""

        if sub in ("status", ""):
            return fm.status()
        if sub == "formats":
            return fm.list_formats()
        if sub == "detect":
            if not rest_str:
                return "Usage: file detect <path>"
            return fm.detect(rest_str)
        if sub == "read":
            if not rest_str:
                return "Usage: file read <path>"
            return fm.read_file(rest_str)
        if sub == "write":
            if not rest_str or not tail_str:
                return "Usage: file write <path> <content>"
            return fm.write_file(rest_str, tail_str)
        if sub == "edit":
            if not rest_str or "==>" not in tail_str:
                return "Usage: file edit <path> OLD_TEXT==>NEW_TEXT"
            old_part, new_part = tail_str.split("==>", 1)
            return fm.edit_file(rest_str, old_part, new_part)
        if sub in ("execute", "exec", "run"):
            if not rest_str:
                return "Usage: file execute <path> [args...]"
            extra_args = tail_str.split() if tail_str else []
            return fm.execute_file(rest_str, extra_args)
        return (
            "File commands:\n"
            "  file status | formats | detect <path>\n"
            "  file read <path> | file write <path> <content>\n"
            "  file edit <path> OLD==>NEW | file execute <path> [args]"
        )

    # ── Phase-2 agent commands (additive) ─────────────────────────────────────

    # ── HardwareScanner commands (additive) ───────────────────────────────────
    def _cmd_hardware(self, cmd: str) -> str:
        """Route 'hardware ...' commands to HardwareScanner.

        Sub-commands
        ------------
        hardware scan             — Run a full hardware scan now
        hardware status           — Scanner status and last scan time
        hardware profile          — Full profile as JSON
        hardware summary          — Human-readable hardware summary
        hardware requirements     — Deployment recommendation for this hardware
        """
        # pylint: disable=too-many-return-statements
        lower = cmd.strip().lower()
        sub = lower.removeprefix("hardware").strip()
        hw = getattr(self, "hardware_scanner", None)
        if hw is None:
            return "[hardware] HardwareScanner not initialised — check startup logs"
        if sub in ("scan", "rescan"):
            profile = hw.scan()
            return hw.summary() + f"\n✅ Scan complete ({profile.get('scanned_at', '')})"
        if sub in ("status", ""):
            return hw.status()
        if sub in ("profile", "json"):
            return json.dumps(hw.get_profile(), indent=2, default=str)
        if sub in ("summary", "info"):
            return hw.summary()
        if sub in ("requirements", "recommend", "req"):
            return hw.requirements_report()
        return (
            "Hardware Scanner sub-commands:\n"
            "  hardware scan          — Run a full hardware scan\n"
            "  hardware status        — Scanner status\n"
            "  hardware summary       — Human-readable summary\n"
            "  hardware profile       — Full JSON profile\n"
            "  hardware requirements  — Deployment recommendation\n"
        )

    # ── OSIntegration commands (additive) ────────────────────────────────────
    def _cmd_os(self, cmd: str) -> str:
        """Route 'os ...' commands to OSIntegration.

        Sub-commands
        ------------
        os info                   — Show integration layer info
        os install                — Install Niblit as an auto-starting OS service
        os install --system       — Install system-wide (requires root/admin)
        os uninstall              — Remove the auto-start entry
        os status                 — Check service / boot-hook status
        platform info             — Platform type and capability flags
        platform requirements     — Setup hints for the current platform
        """
        # pylint: disable=too-many-branches,too-many-return-statements
        lower = cmd.strip().lower()
        sub = lower
        for prefix in ("os ", "platform "):
            if lower.startswith(prefix):
                sub = lower[len(prefix):].strip()
                break
        if lower in ("os", "platform"):
            sub = "info"

        osi = getattr(self, "os_integration", None)
        pb = getattr(self, "platform_bootstrap", None)

        if sub in ("info", ""):
            parts = []
            if pb:
                parts.append(pb.info())
            if osi:
                parts.append(osi.info())
            return "\n\n".join(parts) if parts else "[os] Neither OSIntegration nor PlatformBootstrap initialised"

        if osi is None:
            return "[os] OSIntegration not initialised — check startup logs"

        if sub in ("install", "install --user"):
            return osi.install(system_wide=False)
        if sub in ("install --system", "install system", "install system-wide"):
            return osi.install(system_wide=True)
        if sub in ("uninstall", "remove"):
            return osi.uninstall()
        if sub in ("status",):
            return osi.status()
        if sub in ("requirements", "req", "setup"):
            if pb:
                return pb.requirements_hint()
            return "[os] PlatformBootstrap not initialised"

        return (
            "OS integration sub-commands:\n"
            "  os info                — Integration layer info\n"
            "  os install             — Install Niblit as auto-starting service\n"
            "  os install --system    — System-wide install (root/admin required)\n"
            "  os uninstall           — Remove auto-start entry\n"
            "  os status              — Service / boot-hook status\n"
            "  os requirements        — Setup hints for this platform\n"
            "  platform info          — Platform type and capability flags\n"
        )

    # ── BIOSIntegration commands (additive) ───────────────────────────────────
    def _cmd_bios(self, cmd: str) -> str:
        """Route 'bios ...' commands to BIOSIntegration."""
        # pylint: disable=too-many-return-statements
        lower = cmd.strip().lower()
        sub = lower.removeprefix("bios").strip()
        bi = getattr(self, "bios_integration", None)
        if bi is None:
            return "[bios] BIOSIntegration not initialised — check startup logs"
        if sub in ("probe", "scan", "rescan"):
            bi.probe()
            return bi.summary()
        if sub in ("status", ""):
            return bi.status()
        if sub in ("summary", "info"):
            return bi.summary()
        if sub in ("uefi", "efi", "uefi vars", "efi vars"):
            return bi.uefi_vars()
        if sub.startswith("cmdline "):
            # bios cmdline <flag> [value] [--write]
            parts = sub.removeprefix("cmdline ").split()
            flag = parts[0] if parts else ""
            value = parts[1] if len(parts) > 1 and not parts[1].startswith("--") else ""
            write = "--write" in parts
            return bi.set_cmdline_flag(flag, value, write=write)
        return (
            "BIOS/UEFI sub-commands:\n"
            "  bios summary          — BIOS/UEFI profile summary\n"
            "  bios probe            — Re-probe firmware\n"
            "  bios status           — Integration status\n"
            "  bios uefi vars        — List EFI variable names (Linux)\n"
            "  bios cmdline <flag> [value] [--write]  — Add kernel boot flag\n"
        )

    # ── KernelIntegration commands (additive) ────────────────────────────────
    def _cmd_krnl(self, cmd: str) -> str:
        """Route 'krnl ...' commands to KernelIntegration."""
        # pylint: disable=too-many-return-statements
        lower = cmd.strip().lower()
        sub = lower
        for prefix in ("krnl ", "kernel "):
            if lower.startswith(prefix):
                sub = lower[len(prefix):].strip()
                break
        if lower in ("krnl", "kernel"):
            sub = "status"

        ki = getattr(self, "kernel_integration", None)
        if ki is None:
            return "[krnl] KernelIntegration not initialised — check startup logs"
        if sub in ("status", ""):
            return ki.status()
        if sub in ("summary", "info"):
            return ki.summary()
        if sub in ("dmesg",) or sub.startswith("dmesg"):
            n = 40
            parts = sub.split()
            if len(parts) > 1 and parts[1].isdigit():
                n = int(parts[1])
            return ki.dmesg(lines=n)
        if sub in ("modules", "lsmod"):
            return ki.list_modules()
        if sub.startswith("sysctl "):
            # krnl sysctl key=value [--write]
            parts = sub.removeprefix("sysctl ").split()
            kv = parts[0] if parts else ""
            k, _, v = kv.partition("=")
            write = "--write" in parts
            return ki.set_sysctl(k, v, write=write)
        if sub.startswith("modprobe ") or sub.startswith("load "):
            mod = sub.split()[-1]
            write = "--write" in sub
            return ki.load_module(mod, write=write)
        if sub.startswith("rmmod ") or sub.startswith("unload "):
            mod = sub.split()[-1]
            write = "--write" in sub
            return ki.unload_module(mod, write=write)
        return (
            "Kernel sub-commands:\n"
            "  krnl summary          — Kernel profile summary\n"
            "  krnl status           — Integration status\n"
            "  krnl dmesg [N]        — Last N dmesg lines\n"
            "  krnl modules          — List loaded kernel modules\n"
            "  krnl sysctl key=val [--write]  — Read/set sysctl param\n"
            "  krnl load <module> [--write]   — Load kernel module\n"
            "  krnl unload <module> [--write] — Unload kernel module\n"
        )

    # ── DeviceControl commands (additive) ────────────────────────────────────
    def _cmd_device_ctrl(self, cmd: str) -> str:
        """Route 'cmd exec / device ctrl' commands to DeviceControl."""
        # pylint: disable=too-many-branches,too-many-return-statements
        lower = cmd.strip()
        sub = lower
        for prefix in ("cmd exec ", "device ctrl ", "ctrl "):
            if lower.lower().startswith(prefix):
                sub = lower[len(prefix):]
                break

        dc = getattr(self, "device_control", None)
        if dc is None:
            return "[device ctrl] DeviceControl not initialised — check startup logs"

        lower_sub = sub.strip().lower()
        if lower_sub in ("status", ""):
            return dc.status()
        if lower_sub in ("history", "log"):
            return dc.history()
        if lower_sub in ("sensors", "sensor"):
            return dc.sensors()
        if lower_sub in ("usb", "lsusb"):
            return dc.list_usb()
        if lower_sub in ("serial", "ports"):
            return ", ".join(dc.list_serial_ports()) or "No serial ports found"
        if lower_sub.startswith("ps") or lower_sub in ("processes", "procs"):
            flt = lower_sub.removeprefix("ps").strip()
            return dc.list_processes(flt)
        if lower_sub.startswith("kill "):
            parts = sub.strip().split()
            try:
                pid = int(parts[1])
            except Exception:
                return "Usage: cmd exec kill <pid>"
            force = "-9" in sub or "--force" in sub
            return dc.kill_process(pid, force=force)
        if lower_sub.startswith("gcode "):
            parts = sub.strip().split(maxsplit=2)
            port = parts[1] if len(parts) > 1 else ""
            gcode = parts[2] if len(parts) > 2 else ""
            return dc.gcode(port, gcode)
        # Default: execute the command
        if sub.strip():
            return dc.execute_str(sub.strip())
        return (
            "Device Control sub-commands:\n"
            "  cmd exec <shell cmd>  — Execute a sandboxed shell command\n"
            "  cmd exec status       — DeviceControl status\n"
            "  cmd exec history      — Recent command history\n"
            "  cmd exec sensors      — Hardware temperatures / battery\n"
            "  cmd exec usb          — List USB devices\n"
            "  cmd exec serial       — List serial/COM ports\n"
            "  cmd exec ps [filter]  — Process list\n"
            "  cmd exec kill <pid>   — Kill a process\n"
            "  cmd exec gcode <port> <cmds>  — Send G-code to 3D printer/robot\n"
        )

    # ── DeviceMesh commands (additive) ───────────────────────────────────────
    def _cmd_mesh(self, cmd: str) -> str:
        """Route 'mesh ...' commands to DeviceMesh."""
        # pylint: disable=too-many-return-statements
        lower = cmd.strip().lower()
        sub = lower.removeprefix("mesh").strip()
        dm = getattr(self, "device_mesh", None)
        if dm is None:
            return "[mesh] DeviceMesh not initialised — check startup logs"
        if sub in ("scan", "discover"):
            dm.scan()
            return dm.summary()
        if sub in ("status", ""):
            return dm.status()
        if sub in ("nodes", "list"):
            return dm.summary()
        if sub.startswith("ping "):
            ip = sub.removeprefix("ping ").strip()
            return dm.ping(ip)
        if sub.startswith("ssh "):
            parts = sub.split(maxsplit=2)
            ip = parts[1] if len(parts) > 1 else ""
            remote_cmd = parts[2] if len(parts) > 2 else "echo hello"
            return dm.ssh_run(ip, remote_cmd)
        if sub.startswith("spread "):
            parts = sub.split()
            ip = parts[1] if len(parts) > 1 else ""
            user = parts[2] if len(parts) > 2 else "niblit"
            return dm.spread(ip, user)
        return (
            "Device Mesh sub-commands:\n"
            "  mesh scan             — Discover devices on LAN\n"
            "  mesh nodes            — List discovered nodes\n"
            "  mesh status           — Mesh status\n"
            "  mesh ping <ip>        — Ping a host\n"
            "  mesh ssh <ip> <cmd>   — Run SSH command on a node\n"
            "  mesh spread <ip> [user] — Copy Niblit to remote device\n"
            "                          (requires NIBLIT_MESH_SPREAD=1)\n"
        )

    # ── GitHubDeepResearch commands (additive) ───────────────────────────────
    def _cmd_github_deep(self, cmd: str) -> str:
        """Route 'github-deep ...' commands to GitHubDeepResearch."""
        # pylint: disable=too-many-return-statements
        lower = cmd.strip().lower()
        sub = lower
        for prefix in ("github-deep ", "github deep "):
            if lower.startswith(prefix):
                sub = lower[len(prefix):]
                break
        if lower in ("github-deep", "github deep"):
            sub = "status"

        gh = getattr(self, "github_deep_research", None)
        if gh is None:
            return "[github-deep] GitHubDeepResearch not initialised — check startup logs"

        if sub in ("status", ""):
            return gh.status()
        if sub in ("scan", "scan all"):
            result = gh.scan_all_tracked()
            return f"Scanned {len(result)} tracked repos. Run 'github-deep proposals' to see findings."
        if sub.startswith("trending"):
            topic = sub.removeprefix("trending").strip() or "machine-learning"
            return gh.trending_summary(topic)
        if sub.startswith("repo ") or sub.startswith("updates "):
            repo = sub.split(maxsplit=1)[-1].strip()
            return gh.repo_report(repo)
        if sub.startswith("track "):
            repo = sub.removeprefix("track ").strip()
            return gh.add_tracked_repo(repo)
        if sub in ("proposals", "ideas"):
            return gh.proposals()
        return (
            "GitHub Deep Research sub-commands:\n"
            "  github-deep status              — Status & token info\n"
            "  github-deep scan                — Scan all tracked repos\n"
            "  github-deep trending [topic]    — Top trending repos\n"
            "  github-deep repo <owner/repo>   — Repo PR/issue report\n"
            "  github-deep track <owner/repo>  — Add a repo to tracking\n"
            "  github-deep proposals           — Show improvement proposals\n"
        )

    def _cmd_agents(self, cmd: str = "") -> str:
        """Inspect and interact with the Phase-2 agent architecture.

        Sub-commands
        ------------
        agents                   — Status of all registered agents
        agents list              — Same as above
        agents submit <type> [k=v ...] — Enqueue a task for a named agent
        agents pending           — Show pending tasks in the task queue
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-return-statements
        rm = getattr(self, "runtime_manager", None)
        if rm is None:
            return (
                "[agents] RuntimeManager not initialised.\n"
                "Phase-2 agent architecture requires core.runtime_manager."
            )

        lower = cmd.strip().lower()
        parts = lower.split()
        sub = parts[0] if parts else "list"

        if sub in ("", "list", "status"):
            registered = rm.orchestrator.registered_task_types
            ph2 = getattr(self, "phase2_agents", {})
            lines = ["Phase-2 Agent Architecture\n" + "─" * 40]
            if registered:
                for ttype in registered:
                    agent_obj = ph2.get(ttype)
                    state = getattr(agent_obj, "state", "?") if agent_obj else "handler"
                    metrics = getattr(agent_obj, "metrics", None)
                    m_str = ""
                    if metrics:
                        m_str = (f" | handled={metrics.tasks_handled}"
                                 f" failed={metrics.tasks_failed}"
                                 f" avg={metrics.avg_time_ms:.0f}ms")
                    lines.append(f"  {ttype:<30} state={state}{m_str}")
            else:
                lines.append("  (no agents registered)")
            lines.append("")
            q = rm.task_queue
            if q:
                lines.append(f"Task queue: {q.pending_count()} pending, "
                              f"{q.completed_count()} completed")
            return "\n".join(lines)

        if sub == "submit":
            raw = cmd.strip().split()
            if len(raw) < 2:
                return "Usage: agents submit <task_type> [key=value ...]"
            task_type = raw[1]
            payload: dict = {}
            for kv in raw[2:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    payload[k] = v
            try:
                task = rm.submit_task(task_type, payload=payload, priority="normal")
                rm.dispatch_pending()
                return f"✅ Task '{task_type}' submitted (id={task.task_id[:8]})"
            except Exception as exc:
                return f"[agents submit] Error: {exc}"

        if sub in ("pending", "queue"):
            q = getattr(rm, "task_queue", None)
            if q is None:
                return "[agents] No task queue available"
            n = q.pending_count()
            if n == 0:
                return "No pending agent tasks."
            return f"{n} pending agent task(s). Use 'agents list' to see registered agents."

        return (
            "Agent commands:\n"
            "  agents [list]          — Show all registered agents + metrics\n"
            "  agents submit <type>   — Enqueue a task for an agent\n"
            "  agents pending         — Show pending tasks"
        )

    # ── Self-enhancement command (additive) ───────────────────────────────────

    def _cmd_self_enhance(self, cmd: str = "") -> str:
        """Trigger an explicit self-enhancement cycle.

        This submits a 'plan_improvement' task to the PlannerAgent (if wired),
        which decomposes it into research, coding, and reflection subtasks.
        Results are non-blocking — pushed to the notification queue.
        """
        rm = getattr(self, "runtime_manager", None)
        if rm is None:
            return "[self-enhance] RuntimeManager not initialised"
        try:
            goal = cmd.strip() or "Identify and implement the most impactful self-improvement"
            _task = rm.submit_task(
                "plan_improvement",
                payload={"goal": goal, "context": "Niblit self-enhancement cycle"},
                priority="high",
            )
            rm.dispatch_pending()
            msg = f"✅ Self-enhancement task submitted (goal: {goal[:60]})"
            self._loop_notify(msg)
            return msg
        except Exception as exc:
            return f"[self-enhance] Error: {exc}"

    def _cmd_status(self, _text: str) -> str:
        """Status command."""
        try:
            mem_count = self._get_memory_count()
            improvements = "✅ Active" if self.improvements else "❌ Inactive"
            autonomous = "✅ Running" if (self.autonomous_engine and self.autonomous_engine.running) else "❌ Stopped"
            self._refresh_unified_feedback_status()
            loop_quality = getattr(self, "_unified_loop_status", {}).get("recent_loop_quality")
            loop_label = (
                f"{loop_quality:.2f}" if isinstance(loop_quality, (int, float)) else "n/a"
            )
            _phase_icons = {
                "pending": "⏳ pending",
                "running": "⏳ loading modules...",
                "complete": "✅ ready",
                "failed": "❌ failed",
            }
            phase = getattr(self, "_deferred_init_phase", "pending")
            init_label = _phase_icons.get(phase, phase)
            # Phase 21: show current TCL epoch in status
            _epoch_label = "n/a"
            _runtime_mode = "normal"
            if getattr(self, "_tcl", None) is not None:
                try:
                    _epoch_label = str(self._tcl.epoch.current)
                except Exception:
                    pass
            if getattr(self, "runtime_coordinator", None) is not None:
                try:
                    _runtime_mode = str(
                        self.runtime_coordinator.status().get("runtime_mode", "normal")
                    )
                except Exception:
                    pass
            return (
                f"Status: OK | Memory: {mem_count} | "
                f"Improvements: {improvements} | Autonomous: {autonomous} | "
                f"Init: {init_label} | LoopQuality: {loop_label} | Epoch: {_epoch_label} "
                f"| RuntimeMode: {_runtime_mode}"
            )
        except Exception as e:
            log.error(f"Status command failed: {e}")
            return f"Status: Error - {e}"

    def _cmd_coherence(self, _text: str) -> str:
        """Phase 21: Temporal Coherence Layer inspection command.

        Shows the runtime epoch, per-tier adaptation clocks, and cross-tier
        synchronization barrier states so operators can verify that fast and
        slow subsystems are running in coherent lock-step.
        """
        if getattr(self, "_tcl", None) is None:
            return "⚠️ Temporal Coherence Layer not initialised (Phase 20 module unavailable)."
        try:
            tcl_status = self._tcl.status()
            epoch_info = tcl_status.get("epoch", {})
            clocks = tcl_status.get("clocks", {})
            barriers = tcl_status.get("barriers", {})

            lines = ["🕰️ **Temporal Coherence Layer** (Phase 20/21)"]
            lines.append(
                f"  Epoch : {epoch_info.get('current_epoch', '?')}  "
                f"| Uptime: {epoch_info.get('uptime_s', '?')}s"
            )
            lines.append("")
            lines.append("**Adaptation Clocks** (tier | next_in_s | count):")
            for tier, info in clocks.items():
                next_s = info.get("time_until_next_s", 0)
                count = info.get("adapt_count", 0)
                interval = info.get("min_interval_s", 0)
                gate = "🟢 open" if next_s == 0 else f"🔒 {next_s}s"
                lines.append(
                    f"  {tier:<12} {gate:<14} | interval={interval}s | adapted×{count}"
                )
            lines.append("")
            lines.append("**Synchronization Barriers** (fast→slow | staleness | coherent):")
            for key, info in barriers.items():
                coherent = info.get("coherent", True)
                icon = "✅" if coherent else "⚠️ STALE"
                staleness = info.get("staleness_s", 0)
                threshold = info.get("threshold_s", 0)
                lines.append(
                    f"  {key:<22} {icon}  | staleness={staleness}s / threshold={threshold}s"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"⚠️ Coherence status error: {exc}"

    def _cmd_health(self, _text: str) -> str:
        """Health check command."""
        hc = self.health_check()
        result = f"System Health: {hc.status}\n"
        result += f"Uptime: {hc.uptime_seconds}s\n"
        result += f"Memory: {hc.memory_entries} entries\n"
        result += "Components:\n"
        for name, state in hc.components.items():
            result += f"  {name}: {state}\n"
        if hc.errors:
            result += "Errors:\n"
            for error in hc.errors:
                result += f"  {error}\n"
        return result

    def _cmd_metrics(self, _text: str) -> str:
        """Metrics command."""
        result = "Performance Metrics:\n"
        for op_name in sorted(self.metrics.operation_counts.keys()):
            stats = self.metrics.get_stats(op_name)
            if stats:
                result += f"  {op_name}: {stats['count']} calls, "
                result += f"{stats['errors']} errors, "
                result += f"avg {stats['avg_ms']:.2f}ms\n"
        return result

    def _cmd_time(self, _text: str) -> str:
        """Time command."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _cmd_slsa_status(self, _text: str) -> str:
        """SLSA status command."""
        return self._get_slsa_status()

    def _cmd_slsa_start(self, text: str) -> str:
        """SLSA start command."""
        rest = text[len("start_slsa"):].strip() if text.lower().startswith("start_slsa") else text.strip()
        topics = rest.split() if rest else None
        return self._start_slsa_engine(topics)

    def _cmd_slsa_stop(self, _text: str) -> str:
        """SLSA stop command."""
        return self._stop_slsa_engine()

    def _cmd_slsa_restart(self, text: str) -> str:
        """SLSA restart command."""
        rest = text[len("restart_slsa"):].strip() if text.lower().startswith("restart_slsa") else text.strip()
        topics = rest.split() if rest else None
        return self._restart_slsa_engine(topics)

    def _cmd_self_research(self, text: str) -> str:
        """Self-research command — uses self_researcher + internet directly, NOT LLM."""
        topic = (
            text[len("self-research"):].strip()
            if text.lower().startswith("self-research")
            else text.strip()
        ) or "general"
        # Direct module path: use researcher directly
        if self.researcher and hasattr(self.researcher, "search"):
            try:
                results = self.researcher.search(topic, max_results=5, use_llm=False,
                                                  enable_autonomous_learning=True)
                if results:
                    return "\n".join(str(r) for r in results[:3]) or "[No results]"
            except Exception as e:
                log.debug(f"Researcher search failed: {e}")
        # Fallback: internet
        if self.internet:
            try:
                results = self.internet.search(topic, max_results=3)
                if results:
                    return "\n".join(
                        r.get("text", str(r)) if isinstance(r, dict) else str(r)
                        for r in results[:3]
                    ) or "[No results]"
            except Exception as e:
                log.debug(f"Internet search failed: {e}")
        # Last fallback: brain
        if self.brain:
            try:
                return self.brain.handle_command(f"self-research {topic}") or "[Research failed]"
            except Exception as e:
                log.debug(f"Brain fallback failed: {e}")
        return "[Research failed — no modules available]"

    def _cmd_self_idea(self, text: str) -> str:
        """Self-idea command — uses SelfIdeaImplementation directly, NOT LLM."""
        prompt = (
            text[len("self-idea"):].strip()
            if text.lower().startswith("self-idea")
            else text.strip()
        ) or "system improvement"
        # Direct module path: use idea_implementation
        if self.idea_implementation and hasattr(self.idea_implementation, "implement_idea"):
            try:
                result = self.idea_implementation.implement_idea(prompt)
                return str(result) if result else "[Idea generation failed]"
            except Exception as e:
                log.debug(f"idea_implementation failed: {e}")
        # Fallback: idea_generator
        if self.idea_generator and hasattr(self.idea_generator, "generate_plan"):
            try:
                result = self.idea_generator.generate_plan(prompt)
                return str(result) if result else "[Idea generation failed]"
            except Exception as e:
                log.debug(f"idea_generator failed: {e}")
        # Last fallback: brain
        if self.brain:
            try:
                return self.brain.handle_command(f"self-idea {prompt}") or "[Idea generation failed]"
            except Exception as e:
                log.debug(f"Brain fallback failed: {e}")
        return "[Idea generation failed — no modules available]"

    def _cmd_reflect(self, _text: str) -> str:
        """Reflect command — uses ReflectModule directly, NOT LLM."""
        topic = (_text[len("reflect"):].strip() if _text.lower().startswith("reflect") else _text.strip()) or ""
        # Direct module path: use reflect directly
        if self.reflect and hasattr(self.reflect, "reflect_on_research"):
            # When a short topic is given, research first so the stored reflection
            # contains real knowledge content, not just a shallow "Themes:" entry.
            # Same threshold as NiblitRouter._MAX_SHORT_TOPIC_WORDS
            is_short_topic = (
                topic and "\n" not in topic and len(topic.split()) <= 6
            )
            if is_short_topic:
                research_text = ""
                try:
                    researcher = getattr(self, "researcher", None)
                    internet = getattr(self, "internet", None)
                    if researcher and hasattr(researcher, "search"):
                        res = researcher.search(topic)
                        if isinstance(res, list):
                            research_text = " ".join(str(r) for r in res[:3])
                        elif res:
                            research_text = str(res)
                    if not research_text and internet and hasattr(internet, "quick_summary"):
                        research_text = internet.quick_summary(topic) or ""
                except Exception as e:
                    log.debug(f"Reflect pre-research failed: {e}")
                if research_text:
                    try:
                        result = self.reflect.reflect_on_research(topic, research_text)
                        return str(result) if result else "[Reflection completed]"
                    except Exception as e:
                        log.debug(f"reflect_on_research failed: {e}")
        if self.reflect and hasattr(self.reflect, "collect_and_summarize"):
            try:
                result = self.reflect.collect_and_summarize(topic or None)
                return str(result) if result else "[Reflection completed]"
            except Exception as e:
                log.debug(f"Reflect module failed: {e}")
        # Fallback: brain
        if self.brain:
            try:
                return self.brain.handle_command(f"reflect {topic}") or "[Reflection failed]"
            except Exception as e:
                log.debug(f"Brain fallback failed: {e}")
        return "[Reflect module not available]"

    def _cmd_self_implement(self, text: str) -> str:
        """Self-implement command — uses SelfImplementer directly."""
        plan = (
            text[len("self-implement"):].strip()
            if text.lower().startswith("self-implement")
            else text.strip()
        ) or ""
        # Direct module path: enqueue to self_implementer
        if self.self_implementer and hasattr(self.self_implementer, "enqueue_plan"):
            try:
                if plan:
                    self.self_implementer.enqueue_plan(plan)
                    return f"✅ Plan enqueued for implementation: {plan[:100]}"
                # No plan given — show queue status
                queue_len = len(getattr(self.self_implementer, "queue", []))
                return f"SelfImplementer running. Queue depth: {queue_len}"
            except Exception as e:
                log.debug(f"self_implementer failed: {e}")
        # Fallback: brain
        if self.brain:
            try:
                cmd = f"self-implement {plan}" if plan else "self-implement"
                return self.brain.handle_command(cmd) or "[Self-implement failed]"
            except Exception as e:
                log.debug(f"Brain fallback failed: {e}")
        return "[SelfImplementer not available]"

    def _cmd_self_teach(self, text: str) -> str:
        """Self-teach command — teaches a topic using SelfTeacher + internet research."""
        topic = text[len("self-teach"):].strip() if text.lower().startswith("self-teach") else text.strip()
        if not topic:
            return "Usage: self-teach <topic>"
        if self.self_teacher and hasattr(self.self_teacher, "teach"):
            try:
                result = self.self_teacher.teach(topic)
                return str(result) if result else f"✅ Teaching completed for: {topic}"
            except Exception as e:
                log.debug(f"self_teacher.teach failed: {e}")
        return f"[SelfTeacher not available for topic: {topic}]"

    def _cmd_idea_implement(self, text: str) -> str:
        """Generate and implement an idea using SelfIdeaImplementation."""
        prompt = text[len("idea-implement"):].strip() if text.lower().startswith("idea-implement") else text.strip()
        if not prompt:
            # Run batch implementation of stored ideas
            if self.idea_implementation and hasattr(self.idea_implementation, "implement_ideas"):
                try:
                    result = self.idea_implementation.implement_ideas(limit=5)
                    return str(result) if result else "✅ Idea implementation batch completed"
                except Exception as e:
                    log.debug(f"implement_ideas failed: {e}")
            return "Usage: idea-implement <idea prompt>"
        if self.idea_implementation and hasattr(self.idea_implementation, "implement_idea"):
            try:
                result = self.idea_implementation.implement_idea(prompt)
                return str(result) if result else f"✅ Idea implemented: {prompt[:80]}"
            except Exception as e:
                log.debug(f"idea_implementation failed: {e}")
        return f"[SelfIdeaImplementation not available for: {prompt}]"

    def _cmd_search(self, text: str) -> str:
        """Search command (uses internet directly, NOT LLM)."""
        if not self.internet:
            return "[Internet not available]"
        try:
            query = text[7:].strip()
            r = self.internet.search(query)
            if isinstance(r, list):
                return "\n".join(str(x) for x in r) if r else "[No results]"
            return str(r) if r else "[No results]"
        except Exception as e:
            log.error(f"Search failed: {e}")
            return f"[Search failed: {e}]"

    def _cmd_summary(self, text: str) -> str:
        """Summary command (uses internet directly, NOT LLM)."""
        if not self.internet:
            return "[Internet not available]"
        try:
            query = text[8:].strip()
            return self.internet.quick_summary(query)
        except Exception as e:
            log.error(f"Summary failed: {e}")
            return f"[Summary failed: {e}]"

    def _cmd_run_diagnostics(self, _text: str) -> str:
        """
        Run the full niblit diagnostic suite (run_diagnostics.py) and return
        its output as a string so it can be displayed inline during a session.
        """
        import subprocess
        script = os.path.join(BASE_DIR, "run_diagnostics.py")
        try:
            log.info("[DIAGNOSTICS] Running run_diagnostics.py ...")
            result = subprocess.run(
                [sys.executable, script],
                capture_output=True, text=True, timeout=300,
                cwd=BASE_DIR,
            )
            output = result.stdout or ""
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr
            log.info(f"[DIAGNOSTICS] Exited with code {result.returncode}")
            return output.strip() or "[Diagnostics produced no output]"
        except subprocess.TimeoutExpired:
            return "[DIAGNOSTICS] Timed out after 300 s"
        except Exception as e:
            log.error(f"[DIAGNOSTICS] Failed: {e}")
            return f"[DIAGNOSTICS] Failed: {e}"

    def _cmd_run_live_test(self, _text: str) -> str:
        """
        Run the live command tester (live_command_tester.py) and return its
        output inline so results can be inspected without leaving the REPL.
        """
        import subprocess
        script = os.path.join(BASE_DIR, "live_command_tester.py")
        try:
            log.info("[LIVE-TEST] Running live_command_tester.py ...")
            result = subprocess.run(
                [sys.executable, script],
                capture_output=True, text=True, timeout=300,
                cwd=BASE_DIR,
            )
            output = result.stdout or ""
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr
            log.info(f"[LIVE-TEST] Exited with code {result.returncode}")
            return output.strip() or "[Live-test produced no output]"
        except subprocess.TimeoutExpired:
            return "[LIVE-TEST] Timed out after 180 s"
        except Exception as e:
            log.error(f"[LIVE-TEST] Failed: {e}")
            return f"[LIVE-TEST] Failed: {e}"

    # ============================
    # CORE INITIALIZATION (unchanged)
    # ============================

    def _initialize_core(self):
        """Initialize core components with explicit ordering."""
        with self.logger.context("initialize_core"):
            self._init_database()
            self._init_identity_and_security()
            self._init_internet()

    def _init_database(self):
        """Initialize database with fallback chain."""
        try:
            if KnowledgeDB:
                self.db = KnowledgeDB(self.config.memory_path) if self.config.memory_path else KnowledgeDB()
            elif LocalDB:
                self.db = LocalDB(self.config.memory_path) if self.config.memory_path else LocalDB()
            else:
                log.warning("No persistent DB available; using fallback")
                self.db = _FallbackDB()

            self.memory = self.db
            self.startup_report.add("db", "ready")
            log.info("✅ Database initialized successfully")
        except Exception as e:
            log.error(f"Database initialization failed: {e}")
            self.db = _FallbackDB()
            self.memory = self.db
            self.startup_report.add("db", "degraded", str(e))

    def _init_identity_and_security(self):
        """Initialize identity and security modules."""
        try:
            self.env = safe_call(NiblitEnv) if NiblitEnv else None
            self.identity = safe_call(NiblitIdentity) if NiblitIdentity else None

            if self.identity:
                safe_call(self.identity.verify)

            self.guard = safe_call(NiblitGuard) if NiblitGuard else None

            self.startup_report.add("identity", "ready")
            self.startup_report.add("guard", "ready")
            log.info("✅ Identity and security initialized")
        except Exception as e:
            log.error(f"Identity/security init failed: {e}")
            self.startup_report.add("identity", "degraded", str(e))
            self.startup_report.add("guard", "degraded", str(e))

    def _init_internet(self):
        """Initialize internet manager and GitHub Code Search client."""
        # pylint: disable=too-many-statements
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
                log.info("✅ InternetManager loaded successfully")
            self.startup_report.add("internet", "ready")
        except Exception as e:
            log.debug(f"InternetManager failed: {e}")
            self.internet = None
            self.startup_report.add("internet", "unavailable", str(e))

        # GitHub Code Search — instantiated unconditionally; is_available() gates
        # actual API calls so it degrades gracefully without a token.
        try:
            self.github_code_search = GitHubCodeSearch() if GitHubCodeSearch else None
            if self.github_code_search and self.github_code_search.is_available():
                log.info("✅ GitHubCodeSearch loaded (token present)")
            else:
                log.debug("GitHubCodeSearch loaded (no token — rate-limited mode)")
            self.startup_report.add("github_code_search", "ready")
        except Exception as e:
            log.debug(f"GitHubCodeSearch failed: {e}")
            self.github_code_search = None
            self.startup_report.add("github_code_search", "unavailable", str(e))

        # Stack Overflow Search — always available (unauthenticated tier)
        try:
            self.stackoverflow_search = StackOverflowSearch() if StackOverflowSearch else None
            if self.stackoverflow_search:
                log.info("✅ StackOverflowSearch loaded")
            self.startup_report.add("stackoverflow_search", "ready")
        except Exception as e:
            log.debug(f"StackOverflowSearch failed: {e}")
            self.stackoverflow_search = None
            self.startup_report.add("stackoverflow_search", "unavailable", str(e))

        # PyPI Search — always available (public API)
        try:
            self.pypi_search = PyPISearch() if PyPISearch else None
            if self.pypi_search:
                log.info("✅ PyPISearch loaded")
            self.startup_report.add("pypi_search", "ready")
        except Exception as e:
            log.debug(f"PyPISearch failed: {e}")
            self.pypi_search = None
            self.startup_report.add("pypi_search", "unavailable", str(e))

        # Searchcode Search — public code search API + MCP endpoint; no key required
        try:
            self.searchcode_search = SearchcodeSearch() if SearchcodeSearch else None
            if self.searchcode_search:
                log.info("✅ SearchcodeSearch loaded (MCP: %s)", self.searchcode_search.mcp_is_available())
            self.startup_report.add("searchcode_search", "ready")
        except Exception as e:
            log.debug(f"SearchcodeSearch failed: {e}")
            self.searchcode_search = None
            self.startup_report.add("searchcode_search", "unavailable", str(e))

        # SQLiteResearcher — local-first, zero-latency KB lookup (no network required)
        try:
            self.sqlite_researcher = (
                SQLiteResearcher(knowledge_db=getattr(self, "db", None))
                if SQLiteResearcher else None
            )
            if self.sqlite_researcher:
                log.info("✅ SQLiteResearcher loaded (local KB backend)")
            self.startup_report.add("sqlite_researcher", "ready")
        except Exception as e:
            log.debug(f"SQLiteResearcher failed: {e}")
            self.sqlite_researcher = None
            self.startup_report.add("sqlite_researcher", "unavailable", str(e))

        # MarketResearcher — market/trading trend analysis.
        # Note: MarketResearcher exposes analyze_market()/summary() rather than a
        # search_web() interface, so it is not plugged into the SelfResearcher search
        # pipeline.  It is instead accessed directly via core.market_researcher or
        # routed through trading-related CLI commands.
        try:
            self.market_researcher = MarketResearcher(db=getattr(self, "db", None)) if MarketResearcher else None
            if self.market_researcher:
                log.info("✅ MarketResearcher loaded")
            self.startup_report.add("market_researcher", "ready")
        except Exception as e:
            log.debug(f"MarketResearcher failed: {e}")
            self.market_researcher = None
            self.startup_report.add("market_researcher", "unavailable", str(e))

    def _initialize_modules(self):
        """Initialize all modules with dependency management.

        Niblit boots in five named architectural layers.  Each layer is logged
        individually so the user can see exactly which part of the system is
        coming online.  After all layers finish a :meth:`_verify_unified_loop`
        check confirms that the core cognitive feedback-loop is intact.

        Each layer is wrapped with :meth:`_init_with_timeout` so that a stalled
        module (e.g. Qdrant connection, model download, SQLite WAL open) does not
        freeze the entire boot — subsequent layers continue and the stalled one
        finishes in the background.
        """
        with self.logger.context("initialize_modules"):
            # ── Layer 1 / 5 : Memory & Storage ────────────────────────────────
            self._push_init_progress(
                "🧱 [Layer 1/5] Memory & Storage — VectorStore, FusedMemory, SemanticAgent…"
            )
            self._init_with_timeout(self._init_vector_store, "1-Memory")
            self._push_init_progress("✅ [Layer 1/5] Memory & Storage ready")

            # ── Layer 2 / 5 : AI Adapters ─────────────────────────────────────
            self._push_init_progress(
                "🤖 [Layer 2/5] AI Adapters — LLM, HFBrain, SelfTeacher, SelfImplementer…"
            )
            self._init_with_timeout(self._init_ai_adapters, "2-AI-Adapters")
            self._push_init_progress("✅ [Layer 2/5] AI Adapters ready")

            # ── Layer 3 / 5 : Cognitive Core ──────────────────────────────────
            self._push_init_progress(
                "🧠 [Layer 3/5] Cognitive Core — NiblitBrain, NiblitRouter, ALE learning…"
            )
            self._init_with_timeout(self._init_brain_and_router, "3a-Brain-Router")
            self._init_with_timeout(self._init_learning_systems, "3b-Learning")
            self._push_init_progress("✅ [Layer 3/5] Cognitive Core ready")

            # ── Layer 4 / 5 : System Services ─────────────────────────────────
            self._push_init_progress(
                "⚙️  [Layer 4/5] System Services — Network, Sensors, Voice, Actions…"
            )
            self._init_with_timeout(self._init_system_services, "4-System-Services")
            self._push_init_progress("✅ [Layer 4/5] System Services ready")

            # ── Layer 5 / 5 : Optional & Extended Services ────────────────────
            self._push_init_progress(
                "🔌 [Layer 5/5] Extended Services — ALE, TradingBrain, CivilizationController, 60+ modules…"
            )
            _layer5_timeout = self._INIT_LAYER5_TIMEOUT_DEFAULT
            try:
                _layer5_timeout = float(
                    os.environ.get("NIBLIT_LAYER5_INIT_TIMEOUT", _layer5_timeout)
                )
            except (ValueError, TypeError):
                _layer5_timeout = self._INIT_LAYER5_TIMEOUT_DEFAULT
            self._init_with_timeout(
                self._init_optional_services,
                "5-Optional",
                timeout=_layer5_timeout,
            )
            self._push_init_progress("✅ [Layer 5/5] Extended Services ready")

            # ── Unification check ─────────────────────────────────────────────
            # Confirm that all five layers are wired into a single coherent
            # feedback loop before declaring Niblit fully operational.
            self._verify_unified_loop()

    def _verify_unified_loop(self) -> None:
        """Verify that all layers are connected into one unified feedback loop.

        Checks that the critical cognitive pipeline is intact:
          Input → Router → Brain → Memory → Quality/Evaluation → Learning/ALE

        Pushes a success or warning summary to the init-progress queue so the
        user sees the result immediately after boot.
        """
        checks: list = []

        def _ok(name: str) -> None:
            checks.append(("✅ ", name))

        def _warn(name: str, detail: str = "") -> None:
            checks.append(("⚠️ ", f"{name}" + (f" ({detail})" if detail else "")))

        # 1. Input layer — CommandRegistry
        if getattr(self, "command_registry", None):
            _ok("CommandRegistry (input dispatch)")
        else:
            _warn("CommandRegistry", "not available — commands use fallback dispatcher")

        # 2. Routing layer — NiblitRouter
        if getattr(self, "router", None):
            _ok("NiblitRouter (routing layer)")
        else:
            _warn("NiblitRouter", "not initialised — falling back to core.handle()")

        # 3. Cognitive layer — NiblitBrain
        if getattr(self, "brain", None):
            _ok("NiblitBrain (cognitive layer)")
        else:
            _warn("NiblitBrain", "not initialised — LLM responses unavailable")

        # 4. Memory layer — KnowledgeDB
        if getattr(self, "db", None):
            _ok("KnowledgeDB (memory layer)")
        else:
            _warn("KnowledgeDB", "not initialised — knowledge will not persist")

        # 5. Learning layer — NiblitLearning
        if getattr(self, "learning", None):
            _ok("NiblitLearning (interaction-feedback layer)")
        else:
            _warn("NiblitLearning", "not initialised — interaction learning degraded")

        # 6. Evaluation layer — EvaluationEngine
        if getattr(self, "evaluation_engine", None):
            _ok("EvaluationEngine (response-quality loop)")
        else:
            _warn("EvaluationEngine", "not initialised — advisor reinforcement disabled")

        # 7. Quality layer — QualityFeedback
        try:
            from modules.quality_feedback import get_quality_feedback  # noqa: PLC0415
            if get_quality_feedback():
                _ok("QualityFeedback (KB / policy feedback layer)")
        except Exception as _qf_err:  # noqa: BLE001
            _warn("QualityFeedback", f"unavailable — {type(_qf_err).__name__}")

        # 8. Policy layer — PolicyOptimizer
        if getattr(self, "policy_optimizer", None):
            _ok("PolicyOptimizer (cross-loop policy learning)")
        else:
            _warn("PolicyOptimizer", "not initialised — routing will not adapt globally")

        # 9. Learning layer — ALE
        if getattr(self, "autonomous_engine", None):
            _ok("AutonomousLearningEngine (learning loop)")
        else:
            _warn("AutonomousLearningEngine", "not initialised — background learning disabled")

        # 10. Optional advanced layers
        if getattr(self, "kernel_v3", None):
            _ok("CognitiveKernelV3 (advanced reasoning)")
        if getattr(self, "msg_layer", None):
            _ok("MSGLayer (meta-cognition)")
        if getattr(self, "cognitive_graph_kernel", None):
            _ok("CognitiveGraphKernel (graph reasoning)")

        warnings = [c for c in checks if c[0].startswith("⚠️")]
        ready = [c for c in checks if c[0].startswith("✅")]

        lines = ["🔗 Unified feedback-loop verification:"]
        for icon, name in checks:
            lines.append(f"   {icon}{name}")

        if warnings:
            lines.append(
                f"⚡ Loop status: {len(ready)}/{len(checks)} subsystems unified "
                f"— {len(warnings)} layer(s) degraded (Niblit will still operate)"
            )
            summary = "\n".join(lines)
            log.warning("[UNIFIED-LOOP] %s", summary)
        else:
            lines.append(
                f"✅ Unified loop CONFIRMED — all {len(ready)} subsystems active "
                "and wired into one coherent feedback loop"
            )
            summary = "\n".join(lines)
            log.info("[UNIFIED-LOOP] %s", summary)

        self._push_init_progress(summary)
        # Store the unification status for later inspection
        self._unified_loop_status: dict = {
            "ready": len(ready),
            "total": len(checks),
            "warnings": [n for _, n in warnings],
            "verified": len(warnings) == 0,
        }
        self._refresh_unified_feedback_status()

    def _refresh_unified_feedback_status(self) -> Dict[str, Any]:
        """Refresh runtime status of the whole-system feedback loop."""
        status: Dict[str, Any] = dict(getattr(self, "_unified_loop_status", {}))
        eval_quality = None
        qf_quality = None

        try:
            if getattr(self, "evaluation_engine", None) is not None:
                eval_quality = self.evaluation_engine.last_quality_score()
        except Exception:
            eval_quality = None

        try:
            from modules.quality_feedback import get_quality_feedback  # noqa: PLC0415
            qf_status = get_quality_feedback().status()
            qf_quality = qf_status.get("recent_avg_score")
            status["quality_feedback"] = qf_status
        except Exception:
            pass

        if getattr(self, "evaluation_engine", None) is not None:
            try:
                status["evaluation_engine"] = self.evaluation_engine.status()
            except Exception:
                pass

        if getattr(self, "learning", None) is not None and getattr(self, "db", None) is not None:
            try:
                status["learning_preferences"] = self.db.get_preferences()
            except Exception:
                pass

        if getattr(self, "adaptive_learning", None) is not None:
            try:
                status["adaptive_learning"] = {
                    "strategy": getattr(self.adaptive_learning, "learning_strategy", "balanced"),
                    "feedback_count": len(getattr(self.adaptive_learning, "feedback_history", []) or []),
                    "recommended_topics": self.adaptive_learning.get_recommended_topics(count=3),
                }
            except Exception:
                pass

        if isinstance(getattr(self, "_last_feedback_arbitration", None), dict):
            status["feedback_arbitration"] = dict(self._last_feedback_arbitration)

        # ── Phase 20: Temporal Coherence Layer status ─────────────────────────
        if getattr(self, "_tcl", None) is not None:
            try:
                status["temporal_coherence"] = self._tcl.status()
            except Exception:
                pass

        # ── Cross-repo runtime coordination status ────────────────────────────
        if getattr(self, "runtime_coordinator", None) is not None:
            try:
                self.runtime_coordinator.refresh()
                status["distributed_runtime"] = self.runtime_coordinator.status()
            except Exception:
                pass

        available_scores = [
            float(s) for s in (eval_quality, qf_quality) if s is not None
        ]
        status["recent_loop_quality"] = round(
            sum(available_scores) / len(available_scores), 3
        ) if available_scores else None
        status["loop_active"] = bool(
            getattr(self, "brain", None)
            and getattr(self, "db", None)
            and getattr(self, "learning", None)
        )

        self._unified_loop_status = status
        return status

    def _arbitrate_turn_quality(
        self,
        evaluation_quality: Optional[float],
        feedback_quality: Optional[float],
    ) -> Dict[str, Any]:
        """Resolve per-turn quality into one domain-scoped runtime authority.

        Phase 20 upgrade — Multi-Axis Quality Arbitration:
        In addition to the backward-compatible ``resolved_quality`` scalar, the
        result now carries a ``quality_axes`` dict with partially-independent
        quality dimensions.  Different subsystems should consume the axis most
        relevant to their function rather than always using the single scalar.

        Arbitration strategy (unchanged for the scalar):
        - if only one source exists, use it directly
        - if both exist and strongly disagree (diff ≥ 0.25), use the lower
          score as a conservative guardrail (conflict_min_guard)
        - otherwise blend with a configurable weighted average
        """
        _eval = None
        _qf = None
        try:
            if evaluation_quality is not None:
                _eval = max(0.0, min(1.0, float(evaluation_quality)))
        except Exception:
            _eval = None
        try:
            if feedback_quality is not None:
                _qf = max(0.0, min(1.0, float(feedback_quality)))
        except Exception:
            _qf = None

        result: Dict[str, Any] = {
            "evaluation_quality": _eval,
            "feedback_quality": _qf,
            "resolved_quality": None,
            "strategy": "none",
            "disagreement": None,
        }

        if _eval is None and _qf is None:
            return result

        if _eval is None:
            result["resolved_quality"] = round(_qf, 4)
            result["strategy"] = "single_source_feedback"
        elif _qf is None:
            result["resolved_quality"] = round(_eval, 4)
            result["strategy"] = "single_source_evaluation"
        else:
            _diff = abs(_eval - _qf)
            result["disagreement"] = round(_diff, 4)
            if _diff >= 0.25:
                result["resolved_quality"] = round(min(_eval, _qf), 4)
                result["strategy"] = "conflict_min_guard"
            else:
                _eval_w = float(os.environ.get("NIBLIT_FEEDBACK_EVAL_WEIGHT", "0.55"))
                _qf_w = float(os.environ.get("NIBLIT_FEEDBACK_QF_WEIGHT", "0.45"))
                _total_w = _eval_w + _qf_w
                if _total_w <= 0:
                    _eval_w, _qf_w, _total_w = 0.55, 0.45, 1.0
                _blended = ((_eval * _eval_w) + (_qf * _qf_w)) / _total_w
                result["resolved_quality"] = round(_blended, 4)
                result["strategy"] = "weighted_blend"
                result["weights"] = {
                    "evaluation": round(_eval_w / _total_w, 4),
                    "feedback": round(_qf_w / _total_w, 4),
                }

        # ── Multi-Axis Quality Arbitration (Phase 20) ─────────────────────────
        # Derive partially-independent quality dimensions from available signals.
        # Each axis captures a different aspect of interaction quality so that
        # subsystems (adaptive_learning, causality_tracker, nibblebots) can
        # consume the dimension most aligned with their function.
        _base = result["resolved_quality"]
        if _base is not None:
            _b = float(_base)
            # reasoning  — evaluation_engine signal is the best proxy
            _reasoning = float(_eval) if _eval is not None else _b
            # engagement — quality_feedback score correlates with user engagement
            _engagement = float(_qf) if _qf is not None else _b
            # factuality — conservative: min of available signals (avoids overconfidence)
            _factuality = min(float(_eval or _b), float(_qf or _b))
            # strategic_alignment — blended scalar (system-level coherence)
            _strategic = _b
            # stability — penalised if signals strongly disagree
            _disag = result.get("disagreement") or 0.0
            _stability = max(0.0, _b - float(_disag) * 0.5)
            result["quality_axes"] = {
                "reasoning":           round(_reasoning, 4),
                "engagement":          round(_engagement, 4),
                "factuality":          round(_factuality, 4),
                "strategic_alignment": round(_strategic, 4),
                "stability":           round(_stability, 4),
            }
        return result

    def _init_vector_store(self) -> None:
        """
        Create a shared :class:`~modules.vector_store.VectorStore` singleton
        that is passed to the LLM adapter, the ResearcherEngine, and any other
        module that wants semantic search over Niblit's knowledge base.

        The store selects its backend automatically:
        * **Qdrant** — when ``QDRANT_URL`` env var is set
        * **FAISS**  — when ``faiss-cpu`` and ``sentence-transformers`` are installed
        * **in-memory linear scan** — always available, no dependencies
        """
        self.vector_store = None
        if _VectorStore is None:
            log.debug("[INIT] VectorStore module not available")
            return
        try:
            self.vector_store = _VectorStore(
                collection=getattr(self.config, "QDRANT_COLLECTION", "niblit_knowledge"),
                qdrant_url=getattr(self.config, "QDRANT_URL", ""),
                qdrant_api_key=getattr(self.config, "QDRANT_API_KEY", ""),
            )
            log.info(
                "✅ VectorStore initialised (backend: %s)",
                self.vector_store.backend,
            )
            self.startup_report.add("vector_store", "ready")
        except Exception as exc:
            log.warning("VectorStore init failed: %s", exc)
            self.vector_store = None
            self.startup_report.add("vector_store", "degraded", str(exc))

        # ── FusedMemory singleton (Qdrant + SQLite hybrid backend) ────────────
        self.fused_memory = None
        try:
            from niblit_memory import FusedMemory as _FusedMemory
            self.fused_memory = _FusedMemory(
                vector_store=self.vector_store,
            )
            log.info(
                "✅ FusedMemory initialised (vector_backend=%s)",
                self.fused_memory.vector_backend,
            )
            self.startup_report.add("fused_memory", "ready")
        except Exception as exc:
            log.debug("FusedMemory init failed: %s", exc)
            self.startup_report.add("fused_memory", "degraded", str(exc))

        # ── SemanticAgent singleton (shared across all components) ────────────
        self.semantic_agent = None
        try:
            from niblit_agents.semantic_agent import SemanticAgent as _SemanticAgent
            self.semantic_agent = _SemanticAgent(
                vector_store=self.vector_store,
            )
            log.info(
                "✅ SemanticAgent initialised (available=%s)",
                self.semantic_agent.is_available(),
            )
            self.startup_report.add("semantic_agent", "ready")
        except Exception as exc:
            log.debug("SemanticAgent init failed: %s", exc)
            self.startup_report.add("semantic_agent", "degraded", str(exc))

        # ── ClaudeEngine singleton ────────────────────────────────────────────
        self.claude_engine = None
        try:
            from niblit_models.claude_engine import ClaudeEngine as _ClaudeEngine
            self.claude_engine = _ClaudeEngine()
            log.info(
                "✅ ClaudeEngine initialised (available=%s)",
                self.claude_engine.is_available(),
            )
            self.startup_report.add("claude_engine", "ready")
        except Exception as exc:
            log.debug("ClaudeEngine init failed: %s", exc)
            self.startup_report.add("claude_engine", "degraded", str(exc))

    def _init_ai_adapters(self):
        """Initialize AI adapter modules."""
        # pylint: disable=too-many-branches
        try:
            self.reflect = safe_call(Reflect_mod, self.db) if Reflect_mod else None
            self.self_healer = safe_call(SelfHealer_mod, self.db) if SelfHealer_mod else None

            # Pass shared VectorStore so the LLM adapter enriches code-generation
            # context with semantically-relevant KB facts (Qdrant / FAISS / memory).
            if LLMAdapter:
                _vs = getattr(self, "vector_store", None)
                try:
                    _params = inspect.signature(LLMAdapter.__init__).parameters
                    if "vector_store" in _params:
                        self.llm = LLMAdapter(vector_store=_vs)
                    else:
                        self.llm = safe_call(LLMAdapter)
                        if _vs and self.llm and not getattr(self.llm, "vector_store", None):
                            try:
                                self.llm.vector_store = _vs
                            except Exception:
                                pass
                except Exception:
                    self.llm = safe_call(LLMAdapter)
            else:
                self.llm = None

            self.trainer = safe_call(Trainer, self.db) if Trainer else None

            self.self_teacher = safe_call(
                SelfTeacher_mod,
                db=self.db,
                researcher=None,
                reflector=self.reflect
            ) if SelfTeacher_mod else None

            # Wire reflect with self_teacher now that both are initialized
            if self.reflect and self.self_teacher:
                try:
                    self.reflect.self_teacher = self.self_teacher
                except Exception as _e:
                    log.debug(f"[INIT] reflect.self_teacher wire failed (non-critical): {_e}")

            # ── Late-wire new ReflectModule v2 dependencies ──────────────────
            # brain_trainer, trading_brain, and llm are not yet built at this
            # point; they are wired in _init_optional_services() below.
            if self.reflect:
                try:
                    self.reflect.knowledge_db = self.db
                    log.debug("[INIT] reflect.knowledge_db wired")
                except Exception as _e:
                    log.debug("[INIT] reflect.knowledge_db wire failed: %s", _e)

            self.self_implementer = safe_call(
                SelfImplementer,
                db=self.db,
                core=self
            ) if SelfImplementer else None

            self.collector = safe_call(
                Collector,
                db=self.db,
                trainer=self.trainer,
                self_teacher=self.self_teacher
            ) if Collector else None

            self.modules = {
                "llm": self.llm,
                "reflect": self.reflect,
                "implementer": self.self_implementer
            }

            try:
                from modules.hf_brain import HFBrain
                self.hf = HFBrain(db=self.db)
            except Exception:
                self.hf = None

            self.startup_report.add("ai_adapters", "ready")
            log.info("✅ AI adapters initialized")
        except Exception as e:
            log.error(f"AI adapters init failed: {e}")
            self.startup_report.add("ai_adapters", "degraded", str(e))

    def _init_brain_and_router(self):
        """Initialize brain and router."""
        # pylint: disable=too-many-branches,too-many-statements
        try:
            self.researcher = safe_call(SelfResearcher, self.db, self.modules) if SelfResearcher else None
            # Alias used by structural_awareness.component_report() and live_updater
            self.self_researcher = self.researcher
            # ── Inject cognitive components into SelfResearcher (additive) ───
            if hasattr(self, 'researcher') and self.researcher is not None:
                if hasattr(self.researcher, 'hybrid_manager') and hasattr(self, 'hybrid_qdrant'):
                    self.researcher.hybrid_manager = self.hybrid_qdrant  # pylint: disable=attribute-defined-outside-init
                if hasattr(self.researcher, 'kernel') and hasattr(self, 'kernel'):
                    self.researcher.kernel = self.kernel  # pylint: disable=attribute-defined-outside-init
                if hasattr(self, 'kernel') and self.kernel:
                    self.kernel.register_module("SelfResearcher", self.researcher)

            if self.researcher and self.internet:
                self.researcher.internet = self.internet  # pylint: disable=attribute-defined-outside-init

            # Inject Searchcode into SelfResearcher now (available at this phase).
            # Serpex is injected later in _init_optional_services after the
            # niblit_agents.ResearchAgent has been constructed.
            if self.researcher:
                if getattr(self, "searchcode_search", None):
                    try:
                        self.researcher.searchcode_search = self.searchcode_search  # pylint: disable=attribute-defined-outside-init
                    except Exception as _e:
                        log.debug("[INIT] researcher.searchcode_search injection failed: %s", _e)
                if getattr(self, "stackoverflow_search", None):
                    try:
                        self.researcher.stackoverflow_search = self.stackoverflow_search  # pylint: disable=attribute-defined-outside-init
                    except Exception as _e:
                        log.debug("[INIT] researcher.stackoverflow_search injection failed: %s", _e)
                if getattr(self, "pypi_search", None):
                    try:
                        self.researcher.pypi_search = self.pypi_search  # pylint: disable=attribute-defined-outside-init
                    except Exception as _e:
                        log.debug("[INIT] researcher.pypi_search injection failed: %s", _e)
                if getattr(self, "sqlite_researcher", None):
                    try:
                        self.researcher.sqlite_researcher = self.sqlite_researcher  # pylint: disable=attribute-defined-outside-init
                    except Exception as _e:
                        log.debug("[INIT] researcher.sqlite_researcher injection failed: %s", _e)

            # Inject shared VectorStore into the researcher so semantic caching
            # and Qdrant-backed retrieval are available during autonomous research.
            if self.researcher and getattr(self, "vector_store", None):
                if not getattr(self.researcher, "vector_store", None):
                    try:
                        self.researcher.vector_store = self.vector_store  # pylint: disable=attribute-defined-outside-init
                    except Exception as _e:
                        log.debug("[INIT] researcher.vector_store injection failed: %s", _e)

            # Inject shared SemanticAgent into the researcher for enriched storage.
            if self.researcher and getattr(self, "semantic_agent", None):
                try:
                    self.researcher.semantic_agent = self.semantic_agent  # pylint: disable=attribute-defined-outside-init
                except Exception as _e:
                    log.debug("[INIT] researcher.semantic_agent injection failed: %s", _e)

            if self.self_teacher:
                self.self_teacher.researcher = self.researcher  # pylint: disable=attribute-defined-outside-init

            try:
                self.brain = NiblitBrain(self.db, llm_enabled=True, internet=self.internet) if NiblitBrain else None
                if self.brain:
                    if hasattr(self.brain, "self_teacher"):
                        self.self_teacher = self.brain.self_teacher
                    if self.collector:
                        self.collector.self_teacher = self.self_teacher
                    if hasattr(self.brain, "self_implementer"):
                        self.brain.self_implementer = self.self_implementer
                    # Wire shared SemanticAgent + ClaudeEngine into brain
                    if getattr(self, "semantic_agent", None) and hasattr(self.brain, "semantic"):
                        self.brain.semantic = self.semantic_agent
                    if getattr(self, "claude_engine", None) and hasattr(self.brain, "claude"):
                        self.brain.claude = self.claude_engine
                    # Expose brain's HFBrain on core so component_report tracks it
                    self.hf_brain = getattr(self.brain, "hf_brain", None) or getattr(self, "hf", None)
            except Exception as e:
                log.debug(f"NiblitBrain failed: {e}")
                self.brain = None

            if NiblitRouter:
                try:
                    self.router = NiblitRouter(self, self.db, self)
                    self.router.start()
                except Exception as e:
                    log.debug(f"NiblitRouter failed: {e}")
                    self.router = None
            else:
                self.router = None

            self.startup_report.add("brain_router", "ready")
            log.info("✅ Brain and router initialized")
            # ── Inject cognitive components into BrainTrainer (additive) ─────
            _bt = getattr(self.brain, "brain_trainer", None) if getattr(self, "brain", None) else None
            if _bt is not None:
                if hasattr(_bt, 'hybrid_manager') and hasattr(self, 'hybrid_qdrant'):
                    _bt.hybrid_manager = self.hybrid_qdrant
                if hasattr(_bt, 'kernel') and hasattr(self, 'kernel'):
                    _bt.kernel = self.kernel
                if hasattr(self, 'kernel') and self.kernel:
                    self.kernel.register_module("BrainTrainer", _bt)
            self._init_personality()
        except Exception as e:
            log.error(f"Brain/router init failed: {e}")
            self.startup_report.add("brain_router", "degraded", str(e))

    def _init_personality(self) -> None:
        """Initialize NiblitPersonality for conversational responses."""
        try:
            if NiblitPersonality:
                self.personality = NiblitPersonality(
                    db=getattr(self, 'db', None),
                    researcher=getattr(self, 'researcher', None),
                    brain=getattr(self, 'brain', None),
                    internet=getattr(self, 'internet', None),
                    serpex_agent=getattr(self, 'serpex_research_agent', None),
                )
                log.info("✅ NiblitPersonality initialized")
        except Exception as e:
            log.debug(f"NiblitPersonality init failed: {e}")

    def _init_learning_systems(self):
        """Initialize learning-related systems."""
        try:
            self.niblit_hf = safe_call(NiblitHF) if NiblitHF else None
            self.learning = safe_call(NiblitLearning, self.db) if NiblitLearning else None

            if NiblitTasks and self.brain and self.db:
                try:
                    self.tasks = NiblitTasks(self.brain, self.db)
                    self.tasks.start()
                except Exception as e:
                    log.debug(f"NiblitTasks failed: {e}")
                    self.tasks = None
            else:
                self.tasks = None

            self.idea_generator = safe_call(
                SelfIdeaGenerator,
                db=self.db,
                collector=self.collector
            ) if SelfIdeaGenerator else None

            if self.idea_generator and hasattr(self.idea_generator, "autonomous_loop"):
                threading.Thread(target=self.idea_generator.autonomous_loop, daemon=True).start()

            # Initialize SelfIdeaImplementation with db + self_implementer
            if SelfIdeaImplementation:
                try:
                    self.idea_implementation = SelfIdeaImplementation(
                        db=self.db,
                        implementer=self.self_implementer,
                    )
                    log.info("✅ SelfIdeaImplementation initialized")
                    self.startup_report.add("idea_implementation", "ready")
                except Exception as e:
                    log.debug(f"SelfIdeaImplementation init failed: {e}")
                    self.idea_implementation = None
                    self.startup_report.add("idea_implementation", "degraded", str(e))

            # Wire reflect's learner to idea_implementation now that it's ready
            if self.reflect and self.idea_implementation:
                try:
                    self.reflect.learner = self.idea_implementation
                except Exception:
                    pass

            # Wire self_teacher's learner to idea_implementation
            if self.self_teacher and self.idea_implementation:
                try:
                    self.self_teacher.learner = self.idea_implementation  # pylint: disable=attribute-defined-outside-init
                except Exception:
                    pass

            self.startup_report.add("learning", "ready")
            log.info("✅ Learning systems initialized")
        except Exception as e:
            log.error(f"Learning systems init failed: {e}")
            self.startup_report.add("learning", "degraded", str(e))

    def _init_system_services(self):
        """Initialize system services."""
        try:
            self.network = safe_call(NiblitNetwork) if NiblitNetwork else None
            self.sensors = safe_call(NiblitSensors) if NiblitSensors else None
            self.voice = safe_call(NiblitVoice) if NiblitVoice else None
            self.actions = safe_call(NiblitActions) if NiblitActions else None
            self.manager = safe_call(NiblitManager) if NiblitManager else None

            self.startup_report.add("system_services", "ready")
            log.info("✅ System services initialized")
        except Exception as e:
            log.error(f"System services init failed: {e}")
            self.startup_report.add("system_services", "degraded", str(e))

    def _init_optional_services(self):
        """Initialize optional heavy modules including all improvements."""
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        try:
            self.membrane = safe_call(Membrane) if Membrane else None
            self.healer_obj = safe_call(Healer) if Healer else None
            self.generator = safe_call(Generator) if Generator else None
            # Wire SelfMaintenance with db, hybrid_manager, and self_monitor so
            # the real run() / run_with_learning() logic can fire.
            if SelfMaintenance is not None:
                try:
                    _sm_params = set(inspect.signature(SelfMaintenance.__init__).parameters)
                    if "db" in _sm_params:
                        self.self_maintenance = SelfMaintenance(
                            self.db,
                            hybrid_manager=getattr(self, "hybrid_manager", None),
                            self_monitor=getattr(self, "self_monitor", None),
                        )
                    else:
                        self.self_maintenance = SelfMaintenance()
                except Exception as _sme:
                    log.debug("[niblit_core] SelfMaintenance init error: %s", _sme)
                    self.self_maintenance = None
            else:
                self.self_maintenance = None

            self.slsa_manager = slsa_manager

            # ── Late-inject SemanticAgent + SearchcodeSearch into InternetManager ──
            # (InternetManager is built in _init_internet before SemanticAgent exists)
            if getattr(self, "internet", None):
                if getattr(self, "semantic_agent", None) and not getattr(self.internet, "semantic_agent", None):
                    try:
                        self.internet.semantic_agent = self.semantic_agent
                        log.info("✅ SemanticAgent wired into InternetManager")
                    except Exception as _e:
                        log.debug("[INIT] internet.semantic_agent injection failed: %s", _e)
                if getattr(self, "searchcode_search", None) and not getattr(self.internet, "searchcode_search", None):
                    try:
                        self.internet.searchcode_search = self.searchcode_search
                        log.info("✅ SearchcodeSearch wired into InternetManager")
                    except Exception as _e:
                        log.debug("[INIT] internet.searchcode_search injection failed: %s", _e)

            # ============================
            # SLSA ENGINE (initialized and auto-started so component report shows it)
            # ============================
            if SLSAGenerator:
                try:
                    self.slsa_engine = SLSAGenerator(
                        interval=20,
                        topics=["car", "computer", "phone"],
                        db=self.db,  # reuse existing DB — Vercel-safe, no new file write
                        internet=getattr(self, "internet", None),
                    )
                    # Auto-start the background generator thread
                    self.slsa_thread = self.slsa_engine.start()
                    log.info("✅ SLSAGenerator initialized and started")
                    self.startup_report.add("slsa_engine", "ready")
                except Exception as e:
                    log.warning(f"SLSAGenerator init failed: {e}")
                    self.startup_report.add("slsa_engine", "degraded", str(e))

            self.lifecycle = None
            if LifecycleEngine:
                try:
                    self.lifecycle = LifecycleEngine()
                except Exception as e:
                    log.debug(f"LifecycleEngine failed to start: {e}")

            # ============================
            # AIOS SCHEDULER (priority queue wrapper around LifecycleEngine)
            # ============================
            self.aios_scheduler = None
            if _AIOS_SCHEDULER_AVAILABLE and _AIOSScheduler:
                try:
                    self.aios_scheduler = _get_aios_scheduler()
                    self.aios_scheduler.start()
                    log.info("✅ AIOSScheduler initialized (priority task queues active)")
                    self.startup_report.add("aios_scheduler", "ready")
                except Exception as _ase:
                    log.debug("AIOSScheduler init failed: %s", _ase)
                    self.startup_report.add("aios_scheduler", "degraded", str(_ase))

            # ============================
            # AIOS HAL (unified hardware abstraction)
            # ============================
            self.aios_hal = None
            if _AIOS_HAL_AVAILABLE and _get_aios_hal:
                try:
                    self.aios_hal = _get_aios_hal()
                    log.info("✅ AIOS HAL initialized (hardware profile ready)")
                    self.startup_report.add("aios_hal", "ready")
                except Exception as _hale:
                    log.debug("AIOS HAL init failed: %s", _hale)
                    self.startup_report.add("aios_hal", "degraded", str(_hale))

            # ============================
            # OBSERVABILITY (AnomalyDetector + MetricsCollector + LogAggregator)
            # ============================
            self.anomaly_detector = None
            if _ANOMALY_DETECTOR_AVAILABLE and _AnomalyDetector:
                try:
                    self.anomaly_detector = _AnomalyDetector()
                    # Seed sensible thresholds for known system metrics
                    self.anomaly_detector.set_threshold("ale_cycle_s", mean=30.0, stddev=15.0)
                    self.anomaly_detector.set_threshold("memory_mb", mean=200.0, stddev=80.0)
                    log.info("✅ AnomalyDetector initialized")
                    self.startup_report.add("anomaly_detector", "ready")
                except Exception as _ade:
                    log.debug("AnomalyDetector init failed: %s", _ade)

            self.metrics_collector = None
            if _METRICS_COLLECTOR_AVAILABLE and _MetricsCollector:
                try:
                    self.metrics_collector = _MetricsCollector()
                    log.info("✅ MetricsCollector initialized")
                    self.startup_report.add("metrics_collector", "ready")
                except Exception as _mce:
                    log.debug("MetricsCollector init failed: %s", _mce)

            self.log_aggregator = None
            if _LOG_AGGREGATOR_AVAILABLE and _LogAggregator:
                try:
                    self.log_aggregator = _LogAggregator()
                    log.info("✅ LogAggregator initialized")
                    self.startup_report.add("log_aggregator", "ready")
                except Exception as _lage:
                    log.debug("LogAggregator init failed: %s", _lage)

            # ============================
            # GLOBAL CODE INTELLIGENCE
            # ============================
            self.pattern_graph = None
            if _PATTERN_GRAPH_AVAILABLE and _PatternGraphBuilder:
                try:
                    self.pattern_graph = _PatternGraphBuilder()
                    self.pattern_graph.seed_world_model()
                    log.info("✅ PatternGraphBuilder initialized (world model seeded)")
                    self.startup_report.add("pattern_graph", "ready")
                except Exception as _pge:
                    log.debug("PatternGraphBuilder init failed: %s", _pge)

            self.knowledge_reasoner = None
            if _KNOWLEDGE_REASONER_AVAILABLE and _KnowledgeReasoner:
                try:
                    self.knowledge_reasoner = _KnowledgeReasoner(
                        graph=getattr(self, "pattern_graph", None),
                    )
                    log.info("✅ KnowledgeReasoner initialized")
                    self.startup_report.add("knowledge_reasoner", "ready")
                except Exception as _kre:
                    log.debug("KnowledgeReasoner init failed: %s", _kre)

            self.architecture_detector = None
            if _ARCH_DETECTOR_AVAILABLE and _ArchitectureDetector:
                try:
                    self.architecture_detector = _ArchitectureDetector()
                    log.info("✅ ArchitectureDetector initialized")
                    self.startup_report.add("architecture_detector", "ready")
                except Exception as _arce:
                    log.debug("ArchitectureDetector init failed: %s", _arce)

            # ============================
            # KNOWLEDGE ENGINE
            # ============================
            self.knowledge_graph = None
            if _KNOWLEDGE_GRAPH_AVAILABLE and _KnowledgeGraphBuilder:
                try:
                    self.knowledge_graph = _KnowledgeGraphBuilder()
                    log.info("✅ KnowledgeGraphBuilder initialized")
                    self.startup_report.add("knowledge_graph", "ready")
                except Exception as _kge:
                    log.debug("KnowledgeGraphBuilder init failed: %s", _kge)

            self.repo_scanner = None
            if _REPO_SCANNER_AVAILABLE and _RepoScanner:
                try:
                    self.repo_scanner = _RepoScanner()
                    log.info("✅ RepoScanner initialized (GitHub repo discovery ready)")
                    self.startup_report.add("repo_scanner", "ready")
                except Exception as _rse:
                    log.debug("RepoScanner init failed: %s", _rse)

            self.embedding_pipeline = None
            if _EMBEDDING_PIPELINE_AVAILABLE and _EmbeddingPipeline:
                try:
                    self.embedding_pipeline = _EmbeddingPipeline(
                        vector_store=getattr(self, "vector_store", None),
                    )
                    log.info("✅ EmbeddingPipeline initialized")
                    self.startup_report.add("embedding_pipeline", "ready")
                except Exception as _epe:
                    log.debug("EmbeddingPipeline init failed: %s", _epe)

            # ============================
            # AI DEV LAB (SEADL)
            # ============================
            self.ai_dev_lab = None
            if _AI_DEV_LAB_AVAILABLE and _AIDevLab:
                try:
                    self.ai_dev_lab = _AIDevLab(
                        llm=getattr(self, "llm", None),
                        graph=getattr(self, "pattern_graph", None),
                    )
                    log.info("✅ AIDevLab (SEADL) initialized — autonomous experiment lab ready")
                    self.startup_report.add("ai_dev_lab", "ready")
                    # Inject into ALE as lab_controller if ALE supports it
                    if hasattr(self, "autonomous_engine") and self.autonomous_engine:
                        if not hasattr(self.autonomous_engine, "lab_controller"):
                            try:
                                self.autonomous_engine.lab_controller = self.ai_dev_lab
                                log.info("✅ AIDevLab wired into AutonomousLearningEngine")
                            except Exception:
                                pass
                except Exception as _laberr:
                    log.debug("AIDevLab init failed: %s", _laberr)
                    self.startup_report.add("ai_dev_lab", "degraded", str(_laberr))

            # module_loader can execute many optional module imports that may
            # be slow (or occasionally block on constrained Termux/proot
            # environments). Keep it off the DeferredInitThread critical path
            # so Phase-1 readiness can complete and the CLI can open.
            if load_modules:
                def _run_module_loader() -> None:
                    try:
                        load_modules()
                        log.info("✅ module_loader background load complete")
                    except Exception as e:
                        log.debug(f"load_modules failed: {e}")

                try:
                    _ml_thread = threading.Thread(
                        target=_run_module_loader,
                        daemon=True,
                        name="ModuleLoaderThread",
                    )
                    _ml_thread.start()
                    log.info("⏳ module_loader started in background thread (non-blocking)")
                    self.startup_report.add("module_loader", "background")
                except Exception as e:
                    log.debug(f"module_loader background start failed: {e}")
                    self.startup_report.add("module_loader", "degraded", str(e))

            # ============================
            # INITIALIZE 10 SELF-IMPROVEMENTS
            # ============================
            if self.config.enable_self_improvements:
                self._init_self_improvements()

            # ============================
            # INITIALIZE BUILDS INTEGRATOR
            # ============================
            if BuildsIntegrator:
                try:
                    self.builds_integrator = BuildsIntegrator()
                    log.info("✅ BuildsIntegrator initialized (builds/python scripts loaded)")
                    self.startup_report.add("builds_integrator", "ready")
                except Exception as _bie:
                    log.debug("BuildsIntegrator init failed: %s", _bie)
                    self.startup_report.add("builds_integrator", "degraded", str(_bie))

            # ============================
            # INITIALIZE AUTONOMOUS LEARNING ENGINE
            # ============================
            if self.config.enable_autonomous_engine and AutonomousLearningEngine:
                try:
                    # Build a niblit_agents.ResearchAgent (Serpex-backed, relevance-filtered)
                    # and expose it on self so other components can access it.
                    _serpex_agent = None
                    try:
                        from niblit_agents.research_agent import ResearchAgent as _NiblitResearchAgent
                        _serpex_agent = _NiblitResearchAgent()
                        self.serpex_research_agent = _serpex_agent
                        log.info("✅ niblit_agents.ResearchAgent (Serpex) ready for ALE step 27")
                    except Exception as _e:
                        log.debug("niblit_agents.ResearchAgent unavailable: %s", _e)
                        self.serpex_research_agent = None

                    # Build a ScrapyResearchAgent — direct Scrapy backend, no SerpexAPI shim.
                    _scrapy_agent = None
                    try:
                        from niblit_agents.scrapy_research_agent import ScrapyResearchAgent as _ScrapyRA
                        _scrapy_agent = _ScrapyRA()
                        self.scrapy_research_agent = _scrapy_agent
                        log.info("✅ niblit_agents.ScrapyResearchAgent ready")
                    except Exception as _e:
                        log.debug("niblit_agents.ScrapyResearchAgent unavailable: %s", _e)
                        self.scrapy_research_agent = None

                    # Wire Serpex agent into SelfResearcher so it is available as a
                    # primary research backend (now that the agent has been constructed).
                    if _serpex_agent and getattr(self, "researcher", None):
                        try:
                            self.researcher.serpex_agent = _serpex_agent  # pylint: disable=attribute-defined-outside-init
                            log.info("✅ Serpex agent wired into SelfResearcher")
                        except Exception as _e:
                            log.debug("[INIT] Late researcher.serpex_agent injection failed: %s", _e)

                    # Wire ScrapyResearchAgent into SelfResearcher as secondary web backend.
                    if _scrapy_agent and getattr(self, "researcher", None):
                        try:
                            self.researcher.scrapy_agent = _scrapy_agent  # pylint: disable=attribute-defined-outside-init
                            log.info("✅ Scrapy agent wired into SelfResearcher")
                        except Exception as _e:
                            log.debug("[INIT] Late researcher.scrapy_agent injection failed: %s", _e)

                    self.autonomous_engine = AutonomousLearningEngine(
                        core=self,
                        researcher=getattr(self, "researcher", None),
                        idea_generator=getattr(self, "idea_generator", None),
                        reflect_module=getattr(self, "reflect", None),
                        self_teacher=getattr(self, "self_teacher", None),
                        slsa_manager=getattr(self, "slsa_manager", None),
                        knowledge_db=self.db,
                        evolve_engine=getattr(self, "evolve_engine", None),
                        self_implementer=getattr(self, "self_implementer", None),
                        idea_implementation=getattr(self, "idea_implementation", None),
                        code_generator=getattr(self, "code_generator", None),
                        code_compiler=getattr(self, "code_compiler", None),
                        software_studier=getattr(self, "software_studier", None),
                        internet=getattr(self, "internet", None),
                        reasoning_engine=getattr(self, "reasoning_engine", None),
                        metacognition=getattr(self, "metacognition", None),
                        improvement_integrator=getattr(self, "improvements", None),
                        github_sync=getattr(self, "github_sync", None),
                        build_scanner=getattr(self, "build_scanner", None),
                        binary_studier=getattr(self, "binary_studier", None),
                        brain_trainer=(
                            getattr(self.brain, "brain_trainer", None)
                            if getattr(self, "brain", None) else None
                        ),
                        llm=getattr(self, "llm", None),
                        github_code_search=getattr(self, "github_code_search", None),
                        stackoverflow_search=getattr(self, "stackoverflow_search", None),
                        pypi_search=getattr(self, "pypi_search", None),
                        searchcode_search=getattr(self, "searchcode_search", None),
                        serpex_research_agent=_serpex_agent,
                        scrapy_research_agent=_scrapy_agent,
                        semantic_agent=getattr(self, "semantic_agent", None),
                        claude_engine=getattr(self, "claude_engine", None),
                        builds_integrator=getattr(self, "builds_integrator", None),
                    )
                    log.info("✅ AutonomousLearningEngine initialized")
                    self.startup_report.add("autonomous_engine", "ready")
                    # ── Inject cognitive components into ALE (additive) ───────
                    if hasattr(self, 'autonomous_engine') and self.autonomous_engine is not None:
                        if hasattr(self.autonomous_engine, 'hybrid_manager') and hasattr(self, 'hybrid_qdrant'):
                            self.autonomous_engine.hybrid_manager = self.hybrid_qdrant
                        if hasattr(self.autonomous_engine, 'self_monitor') and hasattr(self, 'self_monitor'):
                            self.autonomous_engine.self_monitor = self.self_monitor
                        if hasattr(self.autonomous_engine, 'kernel') and hasattr(self, 'kernel'):
                            self.autonomous_engine.kernel = self.kernel
                        if hasattr(self, 'kernel') and self.kernel:
                            self.kernel.register_module("ALE", self.autonomous_engine)

                    # ── ALECheckpointManager: install BEFORE starting ALE ─────
                    # (additive) The checkpoint manager wraps _run_autonomous_cycle
                    # to autosave state after each step, so a restart can resume
                    # from exactly where it left off instead of starting fresh.
                    if ALECheckpointManager:
                        try:
                            def _core_notify(msg: str) -> None:
                                try:
                                    q = getattr(self, "_notifications", None)
                                    if q is not None:
                                        q.append(msg)
                                except Exception:
                                    pass
                                try:
                                    from core.notification_queue import notif_queue
                                    notif_queue.push(msg)
                                except Exception:
                                    pass

                            self.ale_checkpoint = ALECheckpointManager(
                                ale=self.autonomous_engine,
                                notify=_core_notify,
                                autosave_on_step=True,
                            )
                            # Try to restore saved state before the first cycle
                            self.ale_checkpoint.try_resume()
                            # Install the checkpoint wrapper
                            self.ale_checkpoint.install()
                            log.info("✅ ALECheckpointManager installed — ALE state persists across restarts")
                            self.startup_report.add("ale_checkpoint", "ready")
                        except Exception as _ce:
                            log.debug("ALECheckpointManager install failed: %s", _ce)
                            self.startup_report.add("ale_checkpoint", "degraded", str(_ce))

                    # Auto-start: ALE runs in a daemon background thread so Niblit
                    # continuously learns at all times without any manual command.
                    # Use 'autonomous-learn stop' at the CLI to pause it if needed.
                    self.autonomous_engine.start()
                    log.info("🚀 AutonomousLearningEngine auto-started (continuous background learning)")
                except Exception as e:
                    log.warning(f"AutonomousLearningEngine init failed: {e}")
                    self.startup_report.add("autonomous_engine", "degraded", str(e))

            # ============================
            # TRADING BRAIN
            # ============================
            if TradingBrain:
                try:
                    self.trading_brain = TradingBrain(
                        memory=getattr(self, "memory", None),
                    )
                    log.info("✅ TradingBrain initialized (symbol=%s)", self.trading_brain.symbol)
                    self.startup_report.add("trading_brain", "ready")
                except Exception as e:
                    log.debug("TradingBrain init failed: %s", e)
                    self.startup_report.add("trading_brain", "degraded", str(e))

            # ============================
            # FILTERED SWING TRADER V3 (additive — continuous trend re-entry)
            # ============================
            if FilteredSwingTraderV3:
                try:
                    # Resolve notification callback: push to core._notifications or
                    # the global notification queue — whichever is available.
                    def _swing_notify(msg: str) -> None:
                        try:
                            q = getattr(self, "_notifications", None)
                            if q is not None:
                                q.append(msg)
                        except Exception:
                            pass
                        try:
                            from core.notification_queue import notif_queue
                            notif_queue.push(msg)
                        except Exception:
                            pass

                    self.swing_trader_v3 = FilteredSwingTraderV3(
                        memory=getattr(self, "memory", None),
                        notify=_swing_notify,
                        knowledge_db=getattr(self, "db", None),
                        paper_mode=True,  # safe default — user must explicitly switch to live
                    )
                    log.info("✅ FilteredSwingTraderV3 initialized (paper mode)")
                    self.startup_report.add("swing_trader_v3", "ready")
                except Exception as _e:
                    log.debug("FilteredSwingTraderV3 init failed: %s", _e)
                    self.startup_report.add("swing_trader_v3", "degraded", str(_e))

            # ============================
            # BACKGROUND TRAINER (additive — daemon thread, non-blocking)
            # ============================
            if BackgroundTrainer:
                try:
                    _brain_trainer_for_bg = (
                        getattr(self.brain, "brain_trainer", None)
                        if getattr(self, "brain", None)
                        else None
                    )
                    self.background_trainer = BackgroundTrainer(
                        db=getattr(self, "db", None),
                        brain_trainer=_brain_trainer_for_bg,
                    )
                    self.background_trainer.start()
                    log.info("✅ BackgroundTrainer daemon started")
                    self.startup_report.add("background_trainer", "ready")
                except Exception as _e:
                    log.debug("BackgroundTrainer init failed: %s", _e)
                    self.startup_report.add("background_trainer", "degraded", str(_e))
            # ── Inject cognitive components into BackgroundTrainer (additive) ─
            if hasattr(self, 'background_trainer') and self.background_trainer is not None:
                if hasattr(self.background_trainer, 'hybrid_manager') and hasattr(self, 'hybrid_qdrant'):
                    self.background_trainer.hybrid_manager = self.hybrid_qdrant
                if hasattr(self.background_trainer, 'kernel') and hasattr(self, 'kernel'):
                    self.background_trainer.kernel = self.kernel
                if hasattr(self, 'kernel') and self.kernel:
                    self.kernel.register_module("BackgroundTrainer", self.background_trainer)

            # ============================
            # GRADED CURRICULUM — education-system learning progression
            # ============================
            try:
                from modules.graded_curriculum import get_graded_curriculum
                self.graded_curriculum = get_graded_curriculum(
                    db=getattr(self, "db", None),
                    self_teacher=getattr(self, "self_teacher", None),
                )
                if self.graded_curriculum:
                    log.info(
                        "✅ GradedCurriculum started at %s",
                        self.graded_curriculum.current_grade.name,
                    )
                    self.startup_report.add("graded_curriculum", "ready")
            except Exception as _gc_err:
                log.debug("GradedCurriculum init failed: %s", _gc_err)
                self.startup_report.add("graded_curriculum", "degraded", str(_gc_err))


            # ============================
            # LATE-WIRE ReflectModule v2 dependencies
            # (brain_trainer, llm, trading_brain, vector_store are all built now)
            # ============================
            if getattr(self, "reflect", None):
                _brain_trainer = (
                    getattr(self.brain, "brain_trainer", None)
                    if getattr(self, "brain", None)
                    else None
                )
                _pairs = (
                    ("brain_trainer", _brain_trainer),
                    ("trading_brain", getattr(self, "trading_brain", None)),
                    ("llm", getattr(self, "llm", None)),
                    ("vector_store", getattr(self, "vector_store", None)),
                    ("searchcode_search", getattr(self, "searchcode_search", None)),
                )
                for _attr, _val in _pairs:
                    if _val is not None:
                        try:
                            setattr(self.reflect, _attr, _val)
                            log.debug("[INIT] reflect.%s wired ✅", _attr)
                        except Exception as _e:
                            log.debug("[INIT] reflect.%s wire failed: %s", _attr, _e)

            # Late-wire llm into self_teacher
            if getattr(self, "self_teacher", None) and getattr(self, "llm", None):
                try:
                    self.self_teacher.llm = self.llm  # pylint: disable=attribute-defined-outside-init
                    log.debug("[INIT] self_teacher.llm wired ✅")
                except Exception as _e:
                    log.debug("[INIT] self_teacher.llm wire failed: %s", _e)

            # Initialise KnowledgeDigest (purely additive — used by router and
            # self_teacher to rephrase raw research before KB storage)
            try:
                from modules.knowledge_digest import KnowledgeDigest as _KD
                self.knowledge_digest = _KD(llm=getattr(self, "llm", None))
                log.debug("[INIT] knowledge_digest initialised ✅")
            except Exception as _e:
                self.knowledge_digest = None  # type: ignore[assignment]
                log.debug("[INIT] knowledge_digest init failed: %s", _e)

            # Also wire reflect_module back into TradingBrain so each
            # cycle() call automatically stores a market-state reflection.
            if getattr(self, "trading_brain", None) and getattr(self, "reflect", None):
                try:
                    self.trading_brain.reflect_module = self.reflect
                    log.debug("[INIT] trading_brain.reflect_module wired ✅")
                except Exception as _e:
                    log.debug("[INIT] trading_brain.reflect_module wire failed: %s", _e)

            # ============================
            # MCP SERVER — attach NiblitCore so tools work
            # ============================
            if _MCP_AVAILABLE and _MCP_ENABLED and _mcp_attach_core:
                try:
                    _mcp_attach_core(self)
                    log.info("✅ MCP server wired to NiblitCore")
                    self.startup_report.add("mcp_server", "ready")
                except Exception as e:
                    log.debug(f"MCP attach_core failed: {e}")
                    self.startup_report.add("mcp_server", "degraded", str(e))

            self.startup_report.add("optional_services", "ready")
            log.info("✅ Optional services initialized")

            # ============================
            # LIVE UPDATER
            # ============================
            if LiveUpdater:
                try:
                    self.live_updater = LiveUpdater(base_dir=str(self.config.memory_path.parent)
                                                    if getattr(self.config, "memory_path", None) else None)
                    log.info("✅ LiveUpdater initialized")
                    self.startup_report.add("live_updater", "ready")
                except Exception as e:
                    log.debug(f"LiveUpdater init failed: {e}")
                    self.startup_report.add("live_updater", "degraded", str(e))

            # ============================
            # STRUCTURAL AWARENESS
            # ============================
            if StructuralAwareness:
                try:
                    self.structural_awareness = StructuralAwareness(core=self)
                    log.info("✅ StructuralAwareness initialized")
                    self.startup_report.add("structural_awareness", "ready")
                except Exception as e:
                    log.debug(f"StructuralAwareness init failed: {e}")
                    self.startup_report.add("structural_awareness", "degraded", str(e))

            # ============================
            # CODE GENERATOR
            # ============================
            if CodeGenerator:
                try:
                    self.code_generator = CodeGenerator(db=self.db)
                    log.info("✅ CodeGenerator initialized")
                    self.startup_report.add("code_generator", "ready")
                except Exception as e:
                    log.debug(f"CodeGenerator init failed: {e}")
                    self.startup_report.add("code_generator", "degraded", str(e))

            # ============================
            # CODE COMPILER
            # ============================
            if CodeCompiler:
                try:
                    self.code_compiler = CodeCompiler(db=self.db)
                    log.info("✅ CodeCompiler initialized")
                    self.startup_report.add("code_compiler", "ready")
                except Exception as e:
                    log.debug(f"CodeCompiler init failed: {e}")
                    self.startup_report.add("code_compiler", "degraded", str(e))

            # ============================
            # CODE ERROR FIXER
            # ============================
            if CodeErrorFixer:
                try:
                    self.code_error_fixer = CodeErrorFixer(db=self.db)
                    log.info("✅ CodeErrorFixer initialized")
                    self.startup_report.add("code_error_fixer", "ready")
                except Exception as e:
                    log.debug(f"CodeErrorFixer init failed: {e}")
                    self.startup_report.add("code_error_fixer", "degraded", str(e))

            # ============================
            # FILE MANAGER (enhanced)
            # ============================
            if FileManager:
                try:
                    self.file_manager = FileManager(
                        base_dir=str(self.config.memory_path.parent)
                        if getattr(self.config, "memory_path", None) else None,
                        db=self.db,
                    )
                    log.info("✅ FilesystemManager (enhanced) initialized")
                    self.startup_report.add("file_manager", "ready")
                except Exception as e:
                    log.debug(f"FilesystemManager init failed: {e}")
                    self.startup_report.add("file_manager", "degraded", str(e))

            # ============================
            # GITHUB SYNC
            # ============================
            if GitHubSync:
                try:
                    self.github_sync = GitHubSync(db=self.db)
                    log.info("✅ GitHubSync initialized")
                    self.startup_report.add("github_sync", "ready")
                except Exception as e:
                    log.debug(f"GitHubSync init failed: {e}")
                    self.startup_report.add("github_sync", "degraded", str(e))

            # ============================
            # BUILD SCANNER
            # ============================
            if BuildScanner:
                try:
                    self.build_scanner = BuildScanner(db=self.db)
                    log.info("✅ BuildScanner initialized")
                    self.startup_report.add("build_scanner", "ready")
                except Exception as e:
                    log.debug(f"BuildScanner init failed: {e}")
                    self.startup_report.add("build_scanner", "degraded", str(e))

            # ============================
            # BINARY STUDIER
            # ============================
            if BinaryStudier:
                try:
                    self.binary_studier = BinaryStudier(db=self.db)
                    log.info("✅ BinaryStudier initialized")
                    self.startup_report.add("binary_studier", "ready")
                except Exception as e:
                    log.debug(f"BinaryStudier init failed: {e}")
                    self.startup_report.add("binary_studier", "degraded", str(e))

            # ============================
            # SOFTWARE STUDIER
            # ============================
            if SoftwareStudier:
                try:
                    self.software_studier = SoftwareStudier(db=self.db)
                    log.info("✅ SoftwareStudier initialized")
                    self.startup_report.add("software_studier", "ready")
                except Exception as e:
                    log.debug(f"SoftwareStudier init failed: {e}")
                    self.startup_report.add("software_studier", "degraded", str(e))

            # ============================
            # EVOLVE ENGINE
            # ============================
            if EvolveEngine:
                try:
                    self.evolve_engine = EvolveEngine(
                        core=self,
                        researcher=getattr(self, "researcher", None),
                        code_generator=getattr(self, "code_generator", None),
                        code_compiler=getattr(self, "code_compiler", None),
                        software_studier=getattr(self, "software_studier", None),
                        self_teacher=getattr(self, "self_teacher", None),
                        reflect_module=getattr(self, "reflect", None),
                        idea_generator=getattr(self, "idea_generator", None),
                        implementer=getattr(self, "self_implementer", None),
                        knowledge_db=self.db,
                        internet=getattr(self, "internet", None),
                        idea_implementation=getattr(self, "idea_implementation", None),
                        slsa=getattr(self, "slsa_engine", None),
                        autonomous_engine=getattr(self, "autonomous_engine", None),
                        semantic_agent=getattr(self, "semantic_agent", None),
                        live_updater=getattr(self, "live_updater", None),
                        file_manager=getattr(self, "file_manager", None),
                        sub_step_timeout=300,  # increased from 30 s — avoids premature skips
                    )
                    # Back-wire autonomous_engine → evolve_engine once both are available
                    if self.autonomous_engine and not self.autonomous_engine.evolve_engine:
                        self.autonomous_engine.evolve_engine = self.evolve_engine
                    log.info("✅ EvolveEngine initialized")
                    self.startup_report.add("evolve_engine", "ready")
                except Exception as e:
                    log.debug(f"EvolveEngine init failed: {e}")
                    self.startup_report.add("evolve_engine", "degraded", str(e))

            # ============================
            # CIVILIZATION CONTROLLER (STACA — Self-Training AI Civilization Architecture)
            # Runs after EvolveEngine so it can share the same DB / ALE references.
            # ============================
            if _CivilizationController:
                try:
                    self.civilization = _CivilizationController(
                        knowledge_db=self.db,
                        github_code_search=getattr(self, "github_code_search", None),
                        hf_brain=getattr(self, "hf", None) or getattr(self, "hf_brain", None),
                    )
                    self.civilization.start()
                    log.info("✅ CivilizationController (STACA) initialized and started")
                    self.startup_report.add("civilization", "ready")
                    # Wire civilization into a SelfImprovementOrchestrator so it
                    # participates in the ALE/reflect/evolve improvement loop.
                    try:
                        from modules.self_improvement_orchestrator import SelfImprovementOrchestrator
                        self.self_improvement_orchestrator = SelfImprovementOrchestrator(
                            ale=getattr(self, "autonomous_engine", None),
                            evolve=getattr(self, "evolve_engine", None),
                            reflect=getattr(self, "reflect", None),
                            agentic=getattr(self, "agentic_workflows", None),
                            github=getattr(self, "github_sync", None),
                            db=self.db,
                            civilization=self.civilization,
                        )
                        log.info("✅ SelfImprovementOrchestrator wired with civilization")
                        self.startup_report.add("self_improvement_orchestrator", "ready")
                    except Exception as _sio_err:
                        log.debug("SelfImprovementOrchestrator wire failed: %s", _sio_err)
                        self.startup_report.add("self_improvement_orchestrator", "degraded", str(_sio_err))
                except Exception as _civ_e:
                    log.debug("CivilizationController init failed: %s", _civ_e)
                    self.startup_report.add("civilization", "degraded", str(_civ_e))
        except Exception as e:
            log.error(f"Optional services init failed: {e}")
            self.startup_report.add("optional_services", "degraded", str(e))

        # ============================
        # GRAPH-RAG BRIDGE — KnowledgeDB ↔ GraphRAGPipeline sync
        # Runs after the main optional-services block so KnowledgeDB and
        # optional VectorStore are both available.  The boot ingest is
        # dispatched to a daemon thread so init never blocks.
        # ============================
        try:
            from modules.graph_rag_bridge import get_graph_rag_bridge, install_kb_hook
            from modules.graph_rag import get_graph_rag_pipeline
            _grp = get_graph_rag_pipeline(
                vector_store=getattr(self, "vector_store", None)
            )
            self.graph_rag_bridge = get_graph_rag_bridge(
                knowledge_db=self.db,
                graph_rag_pipeline=_grp,
            )
            # Install real-time hook so every future add_fact() feeds the graph
            install_kb_hook(self.db, self.graph_rag_bridge)
            # Kick off background boot ingest (non-blocking)
            self.graph_rag_bridge.ingest_from_kb(background=True)
            # Start periodic background watch thread
            self.graph_rag_bridge.start_watch()
            log.info("✅ GraphRAGBridge initialized (KB→Graph sync active)")
            self.startup_report.add("graph_rag_bridge", "ready")
        except Exception as _grb_err:
            self.graph_rag_bridge = None  # type: ignore[assignment]
            log.debug("GraphRAGBridge init failed: %s", _grb_err)
            self.startup_report.add("graph_rag_bridge", "degraded", str(_grb_err))

        # ============================
        # CHAT COMPLETIONS — conversational response engine
        # ============================
        try:
            from modules.chat_completions import get_chat_completions
            _grp_for_cc = getattr(self, "graph_rag_bridge", None)
            _grp_for_cc = getattr(_grp_for_cc, "_grp", None) if _grp_for_cc else None
            self.chat_completions = get_chat_completions(
                llm_provider_manager=getattr(
                    getattr(self, "brain", None), "llm_provider_manager", None
                ),
                graph_rag_pipeline=_grp_for_cc,
            )
            log.info("✅ ChatCompletions engine initialized")
            self.startup_report.add("chat_completions", "ready")
        except Exception as _cc_err:
            self.chat_completions = None  # type: ignore[assignment]
            log.debug("ChatCompletions init failed: %s", _cc_err)
            self.startup_report.add("chat_completions", "degraded", str(_cc_err))

        # ── LanguageModule ─────────────────────────────────────────────────
        try:
            from modules.language_module import get_language_module as _get_lm
            self.language_module = _get_lm()
            log.info("✅ LanguageModule initialized (%d vocabulary words)", len(self.language_module.vocabulary))
            self.startup_report.add("language_module", "ready")
        except Exception as _lm_err:
            self.language_module = None  # type: ignore[assignment]
            log.debug("LanguageModule init failed: %s", _lm_err)
            self.startup_report.add("language_module", "degraded", str(_lm_err))

        # ── AcademicStudyModule ────────────────────────────────────────────
        try:
            from modules.academic_study_module import get_academic_study_module as _get_asm
            _grp_for_asm = getattr(getattr(self, "graph_rag_bridge", None), "_grp", None)
            self.academic_study = _get_asm(
                knowledge_db=getattr(self, "db", None) or getattr(self, "memory", None),
                graph_rag_pipeline=_grp_for_asm,
                language_module=self.language_module,
            )
            # Seed subject facts into the knowledge pipeline in the background
            self.academic_study.seed_knowledge_pipeline(background=True)
            log.info(
                "✅ AcademicStudyModule initialized (%d subjects, %d topics)",
                len(self.academic_study.subjects),
                sum(len(s.topics) for s in self.academic_study.subjects.values()),
            )
            self.startup_report.add("academic_study", "ready")
        except Exception as _asm_err:
            self.academic_study = None  # type: ignore[assignment]
            log.debug("AcademicStudyModule init failed: %s", _asm_err)
            self.startup_report.add("academic_study", "degraded", str(_asm_err))

        # ── PhasedResearchEngine ───────────────────────────────────────────
        try:
            from modules.phased_research_engine import get_phased_research_engine as _get_pre
            self.phased_research_engine = _get_pre(
                knowledge_db=getattr(self, "db", None) or getattr(self, "memory", None),
                graph_rag_bridge=getattr(self, "graph_rag_bridge", None),
                language_module=self.language_module,
                internet=getattr(self, "internet", None),
                scrapy_agent=getattr(
                    getattr(self, "autonomous_engine", None), "scrapy_research_agent", None
                ),
                serpex_agent=getattr(
                    getattr(self, "autonomous_engine", None), "serpex_research_agent", None
                ),
                github_code_search=getattr(self, "github_code_search", None),
            )
            # Back-wire into ALE so _phased_research() uses the singleton
            if self.autonomous_engine:
                try:
                    self.autonomous_engine.language_module = self.language_module
                    self.autonomous_engine.graph_rag_bridge = getattr(
                        self, "graph_rag_bridge", None
                    )
                except Exception:
                    pass
            log.info("✅ PhasedResearchEngine initialized")
            self.startup_report.add("phased_research_engine", "ready")
        except Exception as _pre_err:
            self.phased_research_engine = None  # type: ignore[assignment]
            log.debug("PhasedResearchEngine init failed: %s", _pre_err)
            self.startup_report.add("phased_research_engine", "degraded", str(_pre_err))

        # ============================
        # DYNAMIC TOPIC MANAGER (LLM/hybrid Qdrant-based topic enrichment)
        # These run after the main optional-services try/except so that a
        # failure here never masks earlier service initialisation errors.
        # ============================
        if _DynamicTopicManager is not None:
            try:
                _tc = None
                try:
                    from modules.topic_constructor import TopicConstructor as _TC
                    _tc = _TC()
                except Exception as _tce:
                    log.debug("[INIT] TopicConstructor unavailable for DynamicTopicManager: %s", _tce)

                self.dynamic_topic_manager = _DynamicTopicManager(
                    db=self.db,
                    topic_constructor=_tc,
                    vector_store=getattr(self, "vector_store", None),
                )
                log.info("✅ DynamicTopicManager initialized")
                self.startup_report.add("dynamic_topic_manager", "ready")
            except Exception as _dtme:
                log.warning("DynamicTopicManager init failed: %s", _dtme)
                self.startup_report.add("dynamic_topic_manager", "degraded", str(_dtme))

        # ── One-time Qdrant batch population from KnowledgeDB ─────────────────
        # Run in a daemon thread so it never blocks _init_optional_services()
        # (and therefore never blocks _deferred_init_event from being set).
        # The model download + 2,000 HTTP upserts can take minutes; keeping
        # them off the DeferredInitThread lets the CLI open on time.
        if _batch_populate_qdrant is not None and self.db is not None:
            _bpq_db = self.db
            _bpq_vs = getattr(self, "vector_store", None)
            _bpq_report = self.startup_report

            def _run_batch_populate() -> None:
                try:
                    _added = _batch_populate_qdrant(_bpq_db, vector_store=_bpq_vs)
                    log.info(
                        "✅ Qdrant batch population complete: %d facts upserted", _added
                    )
                    _bpq_report.add(
                        "qdrant_batch_populate", "ready", f"{_added} facts upserted"
                    )
                except Exception as _bpe:
                    log.debug(
                        "Qdrant batch population failed (non-critical): %s", _bpe
                    )
                    _bpq_report.add(
                        "qdrant_batch_populate", "degraded", str(_bpe)
                    )

            _bpq_thread = threading.Thread(
                target=_run_batch_populate,
                daemon=True,
                name="QdrantBatchPopulate",
            )
            _bpq_thread.start()
            log.info(
                "⏳ Qdrant batch population started in background thread"
                " (will not block init)"
            )

        # ── Background topic refresh thread ───────────────────────────────────
        if (_start_background_refresh is not None
                and self.dynamic_topic_manager is not None):
            try:
                self._topic_refresh_stop_event = threading.Event()
                self._topic_refresh_thread = _start_background_refresh(
                    dtm=self.dynamic_topic_manager,
                    ale=getattr(self, "autonomous_engine", None),
                    interval_secs=600,
                    batch_size=10,
                    stop_event=self._topic_refresh_stop_event,
                    initial_delay_secs=120,
                )
                log.info("✅ BackgroundTopicRefresh thread started")
                self.startup_report.add("background_topic_refresh", "ready")
            except Exception as _btre:
                log.debug("BackgroundTopicRefresh thread failed to start: %s", _btre)
                self.startup_report.add("background_topic_refresh", "degraded", str(_btre))

        # ── Event-bus subscription: LEARNING_CYCLE_COMPLETED → topic refresh ──
        try:
            from core.event_bus import EventType as _EventType, Event as _Event
            _event_bus = getattr(self, "event_bus", None)
            _dtm_ref = getattr(self, "dynamic_topic_manager", None)
            _ale_ref = getattr(self, "autonomous_engine", None)
            if _event_bus is not None and _dtm_ref is not None:
                def _on_learning_cycle(_event: _Event) -> None:
                    try:
                        _new = _dtm_ref.propose_new_topics(batch_size=5)
                        if _new and _ale_ref is not None:
                            if hasattr(_ale_ref, "update_research_topics"):
                                _ale_ref.update_research_topics(_new)
                            elif hasattr(_ale_ref, "research_topics"):
                                _existing = set(_ale_ref.research_topics)
                                for _t in _new:
                                    if _t not in _existing:
                                        _ale_ref.research_topics.append(_t)
                                        _existing.add(_t)
                        log.debug("[EventBus] LEARNING_CYCLE_COMPLETED → injected %d topics",
                                  len(_new))
                    except Exception as _ev_exc:
                        log.debug("[EventBus] Topic refresh handler error: %s", _ev_exc)

                _event_bus.subscribe(_EventType.LEARNING_CYCLE_COMPLETED, _on_learning_cycle)
                log.info("✅ Event-bus: LEARNING_CYCLE_COMPLETED → topic refresh handler registered")
        except Exception as _eb_exc:
            log.debug("[INIT] Event-bus topic refresh subscription skipped: %s", _eb_exc)

        # ── ParameterManager background sync (additive) ───────────────────────
        # Start the background parameter-sync daemon thread so parameters are
        # automatically reloaded from file/remote without blocking the shell.
        # Results are pushed to the notification queue, not printed directly.
        if _PARAMETER_MANAGER_AVAILABLE and _parameter_manager is not None:
            try:
                _parameter_manager.start_background_sync(interval=60.0, initial_delay=30.0)
                log.info("✅ ParameterManager background sync thread started")
                self.startup_report.add("parameter_manager_sync", "ready")
            except Exception as _pme:
                log.debug("[INIT] ParameterManager sync failed to start: %s", _pme)

        # ── LeanEngine (additive) ─────────────────────────────────────────────
        # Initialise the LEAN CLI wrapper with access to the KnowledgeDB so
        # back-test results and metrics can be persisted for RAG retrieval.
        if _LEAN_ENGINE_AVAILABLE and _get_lean_engine is not None:
            try:
                self.lean_engine = _get_lean_engine(knowledge_db=self.db)
                log.info("✅ LeanEngine initialised (workspace=%s)", self.lean_engine.workspace)
                self.startup_report.add("lean_engine", "ready")
            except Exception as _lee:
                log.debug("[INIT] LeanEngine init failed: %s", _lee)
                self.startup_report.add("lean_engine", "degraded", str(_lee))

        # ── MarketDataProviders (additive) ────────────────────────────────────
        # Unified gateway for yfinance, CCXT, TwelveData, OANDA, Alpaca data.
        if _MARKET_DATA_AVAILABLE and _get_market_data_providers is not None:
            try:
                self.market_data_providers = _get_market_data_providers(knowledge_db=self.db)
                log.info("✅ MarketDataProviders initialised")
                self.startup_report.add("market_data_providers", "ready")
            except Exception as _mde2:
                log.debug("[INIT] MarketDataProviders init failed: %s", _mde2)
                self.startup_report.add("market_data_providers", "degraded", str(_mde2))

        # ── LeanDeployEngine (additive) ───────────────────────────────────────
        # QuantConnect REST API client for cloud live trading deployment.
        if _LEAN_DEPLOY_AVAILABLE and _get_lean_deploy_engine is not None:
            try:
                self.lean_deploy_engine = _get_lean_deploy_engine(
                    knowledge_db=self.db,
                    reflect_module=getattr(self, "reflect", None),
                )
                log.info("✅ LeanDeployEngine initialised")
                self.startup_report.add("lean_deploy_engine", "ready")
            except Exception as _ldee:
                log.debug("[INIT] LeanDeployEngine init failed: %s", _ldee)
                self.startup_report.add("lean_deploy_engine", "degraded", str(_ldee))

        # ── LeanAlgoManager (additive) ────────────────────────────────────────
        # Bridges TradingBrain with the niblit-lean-algos repo and QC Cloud.
        if _LEAN_ALGO_MANAGER_AVAILABLE and _get_lean_algo_manager is not None:
            try:
                self.lean_algo_manager = _get_lean_algo_manager(
                    trading_brain=getattr(self, "trading_brain", None),
                    lean_deploy_engine=self.lean_deploy_engine,
                    knowledge_db=self.db,
                )
                log.info("✅ LeanAlgoManager initialised")
                self.startup_report.add("lean_algo_manager", "ready")
            except Exception as _lame:
                log.debug("[INIT] LeanAlgoManager init failed: %s", _lame)
                self.startup_report.add("lean_algo_manager", "degraded", str(_lame))

        # ── DistributedRuntimeCoordinator (additive) ──────────────────────────
        # Canonical cross-repo runtime contract and federation-readiness state.
        if (
            _DISTRIBUTED_RUNTIME_COORDINATOR_AVAILABLE
            and _get_distributed_runtime_coordinator is not None
        ):
            try:
                self.runtime_coordinator = _get_distributed_runtime_coordinator()
                self.runtime_coordinator.refresh()
                log.info("✅ DistributedRuntimeCoordinator initialised")
                self.startup_report.add("distributed_runtime_coordinator", "ready")
            except Exception as _drce:
                log.debug("[INIT] DistributedRuntimeCoordinator init failed: %s", _drce)
                self.startup_report.add("distributed_runtime_coordinator", "degraded", str(_drce))

        # ── TradingStudy (additive) ───────────────────────────────────────────
        # Study/reflect/metacognition engine for trading improvement.
        if _TRADING_STUDY_AVAILABLE and _get_trading_study is not None:
            try:
                self.trading_study = _get_trading_study(
                    knowledge_db=self.db,
                    trading_brain=getattr(self, "trading_brain", None),
                    lean_engine=getattr(self, "lean_engine", None),
                    lean_deploy_engine=getattr(self, "lean_deploy_engine", None),
                    market_data=getattr(self, "market_data_providers", None),
                    brain_trainer=getattr(self, "background_trainer", None),
                    reflect_module=getattr(self, "reflect", None),
                    llm=getattr(self, "llm", None),
                )
                # Wire reflect_module back into LeanDeployEngine
                if self.lean_deploy_engine is not None:
                    self.lean_deploy_engine._reflect = self.trading_study  # pylint: disable=protected-access
                log.info("✅ TradingStudy initialised")
                self.startup_report.add("trading_study", "ready")
            except Exception as _tse2:
                log.debug("[INIT] TradingStudy init failed: %s", _tse2)
                self.startup_report.add("trading_study", "degraded", str(_tse2))

        # ── KnowledgeFilter (additive) ────────────────────────────────────────
        # Wire the LLM into the filter so it can produce richer summaries.
        if _KNOWLEDGE_FILTER_AVAILABLE and _get_knowledge_filter is not None:
            try:
                kf = _get_knowledge_filter(llm=getattr(self, "llm", None))
                log.info("✅ KnowledgeFilter initialised")
                self.startup_report.add("knowledge_filter", "ready")
                # Expose on core for any module that wants to call it directly
                self.knowledge_filter = kf
            except Exception as _kfe2:
                log.debug("[INIT] KnowledgeFilter init failed: %s", _kfe2)
                self.startup_report.add("knowledge_filter", "degraded", str(_kfe2))

        # ── PlatformBootstrap (additive) ──────────────────────────────────────
        if _PLATFORM_BOOTSTRAP_AVAILABLE and _get_platform_bootstrap is not None:
            try:
                self.platform_bootstrap = _get_platform_bootstrap()
                log.info("✅ PlatformBootstrap initialised — platform=%s",
                         self.platform_bootstrap.platform_type)
                self.startup_report.add("platform_bootstrap", "ready")
            except Exception as _pbe2:
                log.debug("[INIT] PlatformBootstrap init failed: %s", _pbe2)
                self.startup_report.add("platform_bootstrap", "degraded", str(_pbe2))

        # ── HardwareScanner (additive) ────────────────────────────────────────
        if _HARDWARE_SCANNER_AVAILABLE and _get_hardware_scanner is not None:
            try:
                self.hardware_scanner = _get_hardware_scanner(
                    knowledge_db=getattr(self, "db", None),
                    autoscan=True,
                )
                log.info("✅ HardwareScanner initialised (background scan started)")
                self.startup_report.add("hardware_scanner", "ready")
            except Exception as _hse2:
                log.debug("[INIT] HardwareScanner init failed: %s", _hse2)
                self.startup_report.add("hardware_scanner", "degraded", str(_hse2))

        # ── OSIntegration (additive) ──────────────────────────────────────────
        if _OS_INTEGRATION_AVAILABLE and _get_os_integration is not None:
            try:
                self.os_integration = _get_os_integration(
                    hardware_scanner=getattr(self, "hardware_scanner", None),
                )
                log.info("✅ OSIntegration initialised — platform=%s",
                         type(self.os_integration._installer).__name__)  # pylint: disable=protected-access
                self.startup_report.add("os_integration", "ready")
            except Exception as _oie2:
                log.debug("[INIT] OSIntegration init failed: %s", _oie2)
                self.startup_report.add("os_integration", "degraded", str(_oie2))

        # ── BIOSIntegration (additive) ────────────────────────────────────────
        if _BIOS_INTEGRATION_AVAILABLE and _get_bios_integration is not None:
            try:
                self.bios_integration = _get_bios_integration(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ BIOSIntegration initialised — uefi=%s",
                         self.bios_integration.get_profile().get("uefi_boot"))
                self.startup_report.add("bios_integration", "ready")
            except Exception as _biose2:
                log.debug("[INIT] BIOSIntegration init failed: %s", _biose2)
                self.startup_report.add("bios_integration", "degraded", str(_biose2))

        # ── KernelIntegration (additive) ──────────────────────────────────────
        if _KERNEL_INTEGRATION_AVAILABLE and _get_kernel_integration is not None:
            try:
                self.kernel_integration = _get_kernel_integration(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ KernelIntegration initialised — kernel=%s",
                         self.kernel_integration.get_profile().get("kernel_version", "?")[:40])
                self.startup_report.add("kernel_integration", "ready")
            except Exception as _kie2:
                log.debug("[INIT] KernelIntegration init failed: %s", _kie2)
                self.startup_report.add("kernel_integration", "degraded", str(_kie2))

        # ── DeviceControl (additive) ──────────────────────────────────────────
        if _DEVICE_CONTROL_AVAILABLE and _get_device_control is not None:
            try:
                self.device_control = _get_device_control(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ DeviceControl initialised")
                self.startup_report.add("device_control", "ready")
            except Exception as _dce2:
                log.debug("[INIT] DeviceControl init failed: %s", _dce2)
                self.startup_report.add("device_control", "degraded", str(_dce2))

        # ── DeviceMesh (additive) ─────────────────────────────────────────────
        if _DEVICE_MESH_AVAILABLE and _get_device_mesh is not None:
            try:
                self.device_mesh = _get_device_mesh(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ DeviceMesh initialised (spread=%s)",
                         getattr(self.device_mesh, "_spread_enabled", False))
                self.startup_report.add("device_mesh", "ready")
            except Exception as _dme2:
                log.debug("[INIT] DeviceMesh init failed: %s", _dme2)
                self.startup_report.add("device_mesh", "degraded", str(_dme2))

        # ── GitHubDeepResearch (additive) ─────────────────────────────────────
        if _GITHUB_DEEP_AVAILABLE and _get_github_deep_research is not None:
            try:
                self.github_deep_research = _get_github_deep_research(
                    knowledge_db=getattr(self, "db", None),
                    improvement_integrator=getattr(self, "improvements", None),
                )
                log.info("✅ GitHubDeepResearch initialised (%d tracked repos)",
                         len(self.github_deep_research.tracked_repos))
                self.startup_report.add("github_deep_research", "ready")
                # Late-wire into SelfResearcher and ALE now that the instance exists.
                if getattr(self, "researcher", None):
                    try:
                        self.researcher.github_deep_research = self.github_deep_research  # pylint: disable=attribute-defined-outside-init
                        log.info("✅ GitHubDeepResearch wired into SelfResearcher")
                    except Exception as _gdr_e:
                        log.debug("[INIT] researcher.github_deep_research injection failed: %s", _gdr_e)
                if getattr(self, "autonomous_engine", None):
                    try:
                        self.autonomous_engine.github_deep_research = self.github_deep_research  # pylint: disable=attribute-defined-outside-init
                        log.info("✅ GitHubDeepResearch wired into ALE")
                    except Exception as _gda_e:
                        log.debug("[INIT] ALE.github_deep_research injection failed: %s", _gda_e)
            except Exception as _ghde2:
                log.debug("[INIT] GitHubDeepResearch init failed: %s", _ghde2)
                self.startup_report.add("github_deep_research", "degraded", str(_ghde2))

        # ── SecurityMembrane (additive) ───────────────────────────────────────
        if _SECURITY_MEMBRANE_AVAILABLE and _get_security_membrane is not None:
            try:
                self.security_membrane = _get_security_membrane(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ SecurityMembrane initialised")
                self.startup_report.add("security_membrane", "ready")
            except Exception as _sme2:
                log.debug("[INIT] SecurityMembrane init failed: %s", _sme2)
                self.startup_report.add("security_membrane", "degraded", str(_sme2))

        # ── CyberMembrane (advanced adaptive cyber layer) ─────────────────────
        if _CYBER_MEMBRANE_AVAILABLE and _get_cyber_membrane is not None:
            try:
                self.cyber_membrane = _get_cyber_membrane(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ CyberMembrane (advanced) initialised")
                self.startup_report.add("cyber_membrane", "ready")
            except Exception as _cme2:
                log.debug("[INIT] CyberMembrane init failed: %s", _cme2)
                self.startup_report.add("cyber_membrane", "degraded", str(_cme2))

        # ── DefensiveEvolutionLoop (self-evolving immunity) ────────────────────
        if (_EVOLUTION_LOOP_AVAILABLE and _get_evolution_loop is not None
                and self.cyber_membrane is not None):
            try:
                self.evolution_loop = _get_evolution_loop(membrane=self.cyber_membrane)
                # Wire the loop back into the membrane so _store_threat() can trigger it
                self.cyber_membrane.evolution_loop = self.evolution_loop
                self.evolution_loop.start()
                log.info("✅ DefensiveEvolutionLoop initialised and started")
                self.startup_report.add("evolution_loop", "ready")
            except Exception as _elo2:
                log.debug("[INIT] DefensiveEvolutionLoop init failed: %s", _elo2)
                self.startup_report.add("evolution_loop", "degraded", str(_elo2))
        elif _EVOLUTION_LOOP_AVAILABLE and self.cyber_membrane is None:
            log.debug(
                "[INIT] DefensiveEvolutionLoop skipped: CyberMembrane not available "
                "(evolution loop requires an active membrane to attach to)."
            )
            self.startup_report.add("evolution_loop", "skipped_no_membrane")

        # ── EnvStateManager (additive) ────────────────────────────────────────
        if _ENV_STATE_AVAILABLE and _get_env_state_manager is not None:
            try:
                self.env_state_manager = _get_env_state_manager(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ EnvStateManager initialised (session=%s…)",
                         self.env_state_manager.snapshot().session_id[:8])
                self.startup_report.add("env_state_manager", "ready")
            except Exception as _ese2:
                log.debug("[INIT] EnvStateManager init failed: %s", _ese2)
                self.startup_report.add("env_state_manager", "degraded", str(_ese2))

        # ── EnvAdapterRegistry (additive) ────────────────────────────────────
        if _ENV_ADAPTER_AVAILABLE and _get_env_adapter_registry is not None:
            try:
                self.env_adapter_registry = _get_env_adapter_registry(
                    knowledge_db=getattr(self, "db", None),
                )
                log.info("✅ EnvAdapterRegistry initialised (adapters: %s)",
                         self.env_adapter_registry.adapter_names())
                self.startup_report.add("env_adapter_registry", "ready")
            except Exception as _eae2:
                log.debug("[INIT] EnvAdapterRegistry init failed: %s", _eae2)
                self.startup_report.add("env_adapter_registry", "degraded", str(_eae2))

        # ── NiblitRuntime (additive) ──────────────────────────────────────────
        if _NIBLIT_RUNTIME_AVAILABLE and _get_niblit_runtime is not None:
            try:
                self.niblit_runtime = _get_niblit_runtime(
                    knowledge_db=getattr(self, "db", None),
                    env_adapter_registry=getattr(self, "env_adapter_registry", None),
                    env_state_manager=getattr(self, "env_state_manager", None),
                )
                self.niblit_runtime.start()
                log.info("✅ NiblitRuntime initialised (level=%.4f)", self.niblit_runtime.level)
                self.startup_report.add("niblit_runtime", "ready")
            except Exception as _nre2:
                log.debug("[INIT] NiblitRuntime init failed: %s", _nre2)
                self.startup_report.add("niblit_runtime", "degraded", str(_nre2))

        # ── GameEngine (additive) ─────────────────────────────────────────────
        if _GAME_ENGINE_AVAILABLE and _get_game_engine is not None:
            try:
                self.game_engine = _get_game_engine()
                log.info("✅ GameEngine initialised (headless mode)")
                self.startup_report.add("game_engine", "ready")
            except Exception as _gee:
                log.debug("[INIT] GameEngine init failed: %s", _gee)
                self.startup_report.add("game_engine", "degraded", str(_gee))

        # ── UniversalFileManager (additive) ───────────────────────────────────
        if _UNIVERSAL_FILE_MANAGER_AVAILABLE and _get_file_manager is not None:
            try:
                self.universal_file_manager = _get_file_manager()
                log.info("✅ UniversalFileManager initialised")
                self.startup_report.add("universal_file_manager", "ready")
            except Exception as _ufme:
                log.debug("[INIT] UniversalFileManager init failed: %s", _ufme)
                self.startup_report.add("universal_file_manager", "degraded", str(_ufme))

        # ── Phase-2 Agent Architecture (additive) ────────────────────────────
        # Initialise RuntimeManager and all Phase-2 agents, register them with
        # the orchestrator, and start the background dispatch loop.
        # ── HybridQdrantManager & SelfMonitor (additive) ─────────────────────
        if _HYBRID_QDRANT_AVAILABLE and _get_hybrid_manager:
            try:
                self.hybrid_qdrant = _get_hybrid_manager()
                log.info("[Core] HybridQdrantManager ready")
            except Exception as _e:
                log.debug(f"[Core] HybridQdrantManager init failed: {_e}")
                self.hybrid_qdrant = None
        else:
            self.hybrid_qdrant = None

        if _SELF_MONITOR_AVAILABLE and _get_self_monitor:
            try:
                self.self_monitor = _get_self_monitor()
                log.info("[Core] SelfMonitor ready")
            except Exception as _e:
                log.debug(f"[Core] SelfMonitor init failed: {_e}")
                self.self_monitor = None
        else:
            self.self_monitor = None

        # ── NiblitKernel (additive) ───────────────────────────────────────────
        if _NIBLIT_KERNEL_AVAILABLE and _get_kernel:
            try:
                self.kernel = _get_kernel()
                # Inject hybrid_manager and self_monitor into kernel
                if self.hybrid_qdrant:
                    self.kernel.hybrid_manager = self.hybrid_qdrant
                if self.self_monitor:
                    self.kernel.self_monitor = self.self_monitor
                # Build Niblit's self-identity model
                self.kernel.update_self_identity("hybrid_qdrant_active", self.hybrid_qdrant is not None)
                self.kernel.update_self_identity("self_monitor_active", self.self_monitor is not None)
                log.info("[Core] NiblitKernel ready")
            except Exception as _e:
                log.debug(f"[Core] NiblitKernel init failed: {_e}")
                self.kernel = None
        else:
            self.kernel = None

        # ── NiblitOSKernel (OS abstraction layer) ────────────────────────────
        if _NIBLIT_OS_KERNEL_AVAILABLE and _get_os_kernel:
            try:
                self.os_kernel = _get_os_kernel()
                log.info("[Core] NiblitOSKernel ready (v%s)", self.os_kernel.VERSION)
            except Exception as _e:
                log.debug(f"[Core] NiblitOSKernel init failed: {_e}")
                self.os_kernel = None
        else:
            self.os_kernel = None

        # ============================
        # DEPLOYMENT BRIDGE
        # ============================
        if _DEPLOYMENT_BRIDGE_AVAILABLE and get_deployment_bridge:
            try:
                self.deployment_bridge = get_deployment_bridge()
                # Load previous deployment state into this instance
                load_msg = self.deployment_bridge.load(self)
                log.info("✅ DeploymentBridge loaded: %s", load_msg)
                # Start autosave loop
                self.deployment_bridge.start_autosave(self)
                self.startup_report.add("deployment_bridge", "ready")
            except Exception as _e:
                log.debug("[Core] DeploymentBridge init failed: %s", _e)
                self.startup_report.add("deployment_bridge", "degraded", str(_e))

        # ============================
        # AUTONOMOUS NETWORK BUILDER
        # ============================
        if _AUTONOMOUS_NETWORK_AVAILABLE and get_autonomous_network:
            try:
                self.autonomous_network = get_autonomous_network(core=self)
                # Seed known endpoints from existing internet/search modules
                if self.internet:
                    for ep in getattr(self.internet, "_known_endpoints", []):
                        self.autonomous_network.register(ep, tags=["internet"])
                self.autonomous_network.start()
                log.info("✅ AutonomousNetworkBuilder started")
                self.startup_report.add("autonomous_network", "ready")
            except Exception as _e:
                log.debug("[Core] AutonomousNetworkBuilder init failed: %s", _e)
                self.startup_report.add("autonomous_network", "degraded", str(_e))

        # ============================
        # MODULE AUTONOMY FRAMEWORK
        # ============================
        if _MODULE_AUTONOMY_AVAILABLE and get_module_autonomy:
            try:
                self.module_autonomy = get_module_autonomy(core=self)
                count = self.module_autonomy.register_all_from_core(self)
                self.module_autonomy.start()
                log.info("✅ ModuleAutonomy started (%d modules registered)", count)
                self.startup_report.add("module_autonomy", "ready")
            except Exception as _e:
                log.debug("[Core] ModuleAutonomy init failed: %s", _e)
                self.startup_report.add("module_autonomy", "degraded", str(_e))

        # ── Cognitive Kernel v2 (local reasoning, no LLM) ────────────────────
        # REQUIRED: core loop depends on v2 for embedding + local synthesis.
        try:
            from modules.niblit_core_kernel_v2 import get_niblit_core_kernel_v2
            self.kernel_v2 = get_niblit_core_kernel_v2()
            log.info("✅ NiblitCoreKernelV2 initialised (local reasoning enabled)")
            self.startup_report.add("kernel_v2", "ready")
        except Exception as _kv2_err:
            log.warning("[Core] NiblitCoreKernelV2 init failed (degraded): %s", _kv2_err)
            self.startup_report.add("kernel_v2", "degraded", str(_kv2_err))

        # ── MWDS MemoryStore (adaptive memory weighting) ──────────────────────
        # REQUIRED: memory lifecycle management.
        try:
            from modules.memory_weighting import get_memory_store
            self.memory_store = get_memory_store()
            log.info("✅ MemoryStore (MWDS v2) initialised")
            self.startup_report.add("memory_store", "ready")
        except Exception as _ms_err:
            log.warning("[Core] MemoryStore init failed (degraded): %s", _ms_err)
            self.startup_report.add("memory_store", "degraded", str(_ms_err))

        # ── SyncEngine (LCSP v1 local↔cloud sync) ─────────────────────────────
        try:
            from modules.sync_engine import get_sync_engine
            _km = getattr(getattr(self, "brain", None), "memory", None) or \
                  getattr(self, "kernel", None) and \
                  getattr(getattr(self, "kernel", None), "memory", None)
            self.sync_engine = get_sync_engine(
                memory_store=self.memory_store,
                kernel_memory=_km,
            )
            log.info("✅ SyncEngine (LCSP v1) initialised — mode=%s", self.sync_engine.mode)
            self.startup_report.add("sync_engine", "ready")
        except Exception as _se_err:
            log.warning("[Core] SyncEngine init failed (degraded): %s", _se_err)
            self.startup_report.add("sync_engine", "degraded", str(_se_err))

        # ── Cognitive Kernel v3 (fused v1+v2+KCB+agents+reward) ──────────────
        # REQUIRED: master cognitive controller — BrainRouter + agent dispatch.
        try:
            from modules.niblit_kernel_v3 import get_niblit_kernel_v3
            self.kernel_v3 = get_niblit_kernel_v3(
                kernel_v1=self.cognitive_kernel if hasattr(self, "cognitive_kernel") else None,
                kernel_v2=self.kernel_v2,
            )
            log.info("✅ NiblitCognitiveKernelV3 initialised (fused v1+v2+KCB)")
            self.startup_report.add("kernel_v3", "ready")
        except Exception as _kv3_err:
            log.warning("[Core] NiblitCognitiveKernelV3 init failed (degraded): %s", _kv3_err)
            self.startup_report.add("kernel_v3", "degraded", str(_kv3_err))

        # ── Cognitive Graph Kernel v1.0 (unified event-driven runtime) ────────
        # REQUIRED: event-driven graph substrate; all subsystem mutations flow here.
        try:
            from modules.niblit_cognitive_graph_kernel import get_cognitive_graph_kernel
            self.cognitive_graph_kernel = get_cognitive_graph_kernel(
                membrane=self.cyber_membrane,
                knowledge_db=getattr(self, "db", None),
            )
            self.cognitive_graph_kernel.start()
            log.info("✅ CognitiveGraphKernel v1.0 initialised (event-driven unified runtime)")
            self.startup_report.add("cognitive_graph_kernel", "ready")
        except Exception as _cgk_err:
            log.warning("[Core] CognitiveGraphKernel init failed (degraded): %s", _cgk_err)
            self.startup_report.add("cognitive_graph_kernel", "degraded", str(_cgk_err))

        # ── MSG Layer v1 (Meta-Cognitive Self-Governance) ─────────────────────
        # REQUIRED: strategic intent, self-model, meta-evaluation, resource allocation.
        try:
            from modules.meta_cognition import get_msg_layer
            self.msg_layer = get_msg_layer()
            log.info("✅ MSGLayer v1 initialised (SelfModel+IntentEngine+MetaEvaluator+…)")
            self.startup_report.add("msg_layer", "ready")
        except Exception as _msg_err:
            log.warning("[Core] MSGLayer init failed (degraded): %s", _msg_err)
            self.startup_report.add("msg_layer", "degraded", str(_msg_err))

        # ── Local Brain (Qwen2.5-0.5B — primary brain, always on) ─────────────
        # REQUIRED: local-first intelligence for offline / toggle-llm-off mode.
        try:
            from modules.local_brain import get_local_brain
            self.local_brain = get_local_brain()
            log.info("✅ QwenLocalBrain registered (lazy-loads Qwen2.5-0.5B on first generate)")
            self.startup_report.add("local_brain", "ready")
            try:
                _lb_status = self.local_brain.status()
                _model_files = _lb_status.get("model_files", [])
                if _lb_status.get("installed_locally"):
                    if _model_files:
                        _first_model_file = _model_files[0]
                        log.info(
                            "✅ Local Qwen model detected in cache (%d files): %s",
                            len(_model_files),
                            _first_model_file,
                        )
                        self.startup_report.add("local_brain_model", "ready", _first_model_file)
                    else:
                        _msg = "Local Qwen model marked installed but no model files were listed."
                        log.warning("[Core] %s", _msg)
                        self.startup_report.add("local_brain_model", "degraded", _msg)
                else:
                    _repo_cache_dir = _lb_status.get("repo_cache_dir", "unknown")
                    _msg = (
                        f"Local Qwen model files not found in cache ({_repo_cache_dir}). "
                        "Run: python tools/install_local_qwen_model.py"
                    )
                    log.warning("[Core] %s", _msg)
                    self.startup_report.add("local_brain_model", "degraded", _msg)
            except Exception as _lb_status_err:
                _msg = f"Local brain cache-status check failed: {_lb_status_err}"
                log.warning("[Core] %s", _msg)
                self.startup_report.add("local_brain_model", "degraded", _msg)
        except Exception as _lb_err:
            log.warning("[Core] QwenLocalBrain init failed (degraded): %s", _lb_err)
            self.startup_report.add("local_brain", "degraded", str(_lb_err))

        # ── Brain Router (intelligent multi-brain routing) ────────────────────
        # REQUIRED: routes prompts between local/cloud/memory brains.
        try:
            from modules.brain_router import get_brain_router, reset_brain_router
            reset_brain_router()
            _lb = getattr(self, "local_brain", None)
            # Cloud callable — prefer brain.brain_router cloud_brain if brain exists,
            # otherwise wire directly to hf_brain / llm_provider_manager
            _brain_obj = getattr(self, "brain", None)
            _pm   = getattr(_brain_obj, "llm_provider_manager", None)
            _hfb  = getattr(_brain_obj, "hf_brain", None) or getattr(self, "hf_brain", None)

            def _core_cloud_fn(p: str) -> str:
                if _pm:
                    try:
                        return _pm.ask(p) or ""
                    except Exception:
                        pass
                if _hfb:
                    try:
                        return _hfb.ask_single(p) or ""
                    except Exception:
                        pass
                return ""

            self.brain_router = get_brain_router(
                local_brain=_lb,
                cloud_brain=_core_cloud_fn,
            )
            log.info("✅ BrainRouter initialised (mode=%s)", self.brain_router.mode)
            self.startup_report.add("brain_router", "ready")
        except Exception as _br_err:
            log.warning("[Core] BrainRouter init failed (degraded): %s", _br_err)
            self.startup_report.add("brain_router", "degraded", str(_br_err))

        # ============================
        # SDAL: NiblitState + EventBus + CognitiveIdentity + EvaluationEngine + DecisionEngine
        # ============================
        if _NIBLIT_STATE_AVAILABLE and _get_niblit_state is not None:
            try:
                self.niblit_state = _get_niblit_state()
                log.info("✅ NiblitState initialised (shared SDAL state active)")
                self.startup_report.add("niblit_state", "ready")
            except Exception as _nse:
                log.debug("NiblitState init failed: %s", _nse)
                self.startup_report.add("niblit_state", "degraded", str(_nse))

        if _SDAL_EVENT_BUS_AVAILABLE and _get_sdal_event_bus is not None:
            try:
                self.sdal_event_bus = _get_sdal_event_bus()
                log.info("✅ SDAL EventBus initialised (pub/sub wiring active)")
                self.startup_report.add("sdal_event_bus", "ready")
            except Exception as _ebe:
                log.debug("SDAL EventBus init failed: %s", _ebe)
                self.startup_report.add("sdal_event_bus", "degraded", str(_ebe))

        if _COGNITIVE_IDENTITY_AVAILABLE and _get_cognitive_identity is not None:
            try:
                self.cognitive_identity = _get_cognitive_identity()
                log.info(
                    "✅ CognitiveIdentity initialised (style=%s risk=%.2f)",
                    self.cognitive_identity.get_decision_style(),
                    self.cognitive_identity.get_risk_tolerance(),
                )
                self.startup_report.add("cognitive_identity", "ready")
                # Sync identity profile into shared NiblitState.
                if self.niblit_state is not None:
                    _profile = self.cognitive_identity.get_profile()
                    self.niblit_state.update_identity(
                        decision_style=_profile.decision_style,
                        risk_tolerance=_profile.risk_tolerance,
                        response_bias=dict(_profile.response_bias),
                        total_decisions=_profile.total_decisions,
                    )
            except Exception as _cie:
                log.debug("CognitiveIdentity init failed: %s", _cie)
                self.startup_report.add("cognitive_identity", "degraded", str(_cie))

        if _EVALUATION_ENGINE_AVAILABLE and _get_evaluation_engine is not None:
            try:
                self.evaluation_engine = _get_evaluation_engine(
                    knowledge_db=getattr(self, "db", None),
                    identity=self.cognitive_identity,
                )
                log.info("✅ EvaluationEngine initialised (adaptive weight loop active)")
                self.startup_report.add("evaluation_engine", "ready")
            except Exception as _eee:
                log.debug("EvaluationEngine init failed: %s", _eee)
                self.startup_report.add("evaluation_engine", "degraded", str(_eee))

        if _DECISION_ENGINE_AVAILABLE and _get_decision_engine is not None:
            try:
                self.decision_engine = _get_decision_engine(
                    knowledge_db=getattr(self, "db", None),
                    evaluation_engine=self.evaluation_engine,
                )
                log.info("✅ DecisionEngine initialised (competitive SDAL gate active)")
                self.startup_report.add("decision_engine", "ready")
            except Exception as _dee:
                log.debug("DecisionEngine init failed: %s", _dee)
                self.startup_report.add("decision_engine", "degraded", str(_dee))

        if _META_ENGINE_AVAILABLE and _get_meta_engine is not None:
            try:
                self.meta_engine = _get_meta_engine(
                    evaluation_engine=self.evaluation_engine,
                    niblit_state=self.niblit_state,
                    cognitive_identity=self.cognitive_identity,
                    # PolicyOptimizer is initialised after MetaEngine.
                    # niblit_core back-wires meta_engine._policy_optimizer
                    # once PolicyOptimizer is ready (see block below).
                    policy_optimizer=None,
                )
                log.info("✅ MetaEngine initialised (meta-cognition active)")
                self.startup_report.add("meta_engine", "ready")
            except Exception as _mee:
                log.debug("MetaEngine init failed: %s", _mee)
                self.startup_report.add("meta_engine", "degraded", str(_mee))

        if _POLICY_OPTIMIZER_AVAILABLE and _get_policy_optimizer is not None:
            try:
                self.policy_optimizer = _get_policy_optimizer(
                    cognitive_identity=self.cognitive_identity,
                )
                log.info("✅ PolicyOptimizer initialised (context-aware policy learning active)")
                self.startup_report.add("policy_optimizer", "ready")
                # Back-wire to DecisionEngine so it can apply context overrides.
                if self.decision_engine is not None and hasattr(
                    self.decision_engine, "set_policy_optimizer"
                ):
                    self.decision_engine.set_policy_optimizer(self.policy_optimizer)
                # Back-wire to MetaEngine so patterns feed the optimizer.
                if self.meta_engine is not None and hasattr(
                    self.meta_engine, "set_policy_optimizer"
                ):
                    self.meta_engine.set_policy_optimizer(self.policy_optimizer)
            except Exception as _poe:
                log.debug("PolicyOptimizer init failed: %s", _poe)
                self.startup_report.add("policy_optimizer", "degraded", str(_poe))

        self._init_agents()

    def _init_agents(self) -> None:
        """Initialise the Phase-2 agent architecture (additive).

        Creates a RuntimeManager (EventBus + TaskQueue + Orchestrator) and
        registers all available Phase-2 agents.  The dispatch loop runs in a
        background daemon thread so agent work never blocks the shell.

        All resources are attached to ``self`` for access by the router and
        other modules:
        - ``self.runtime_manager`` — :class:`~core.runtime_manager.RuntimeManager`
        - ``self.phase2_agents``   — dict mapping task_type → agent instance
        """
        # pylint: disable=too-many-branches,too-many-statements
        if not _RUNTIME_MANAGER_AVAILABLE or _RuntimeManager is None:
            log.debug("[INIT] RuntimeManager not available — skipping Phase-2 agent init")
            return

        try:
            rm = _RuntimeManager()
            self.runtime_manager = rm

            # Build a shared brain_trainer reference (used by ReflectionAgent)
            _brain_trainer = (
                getattr(self.brain, "brain_trainer", None)
                if getattr(self, "brain", None) else None
            )

            # ── Instantiate agents ────────────────────────────────────────────
            agents_registered: int = 0

            if _PlannerAgent is not None:
                try:
                    pa = _PlannerAgent(
                        task_queue=rm.task_queue,
                        llm=getattr(self, "llm", None),
                    )
                    for tt in pa.HANDLED_TASK_TYPES:
                        rm.register_agent(tt, pa.handle)
                    self.phase2_agents[pa.HANDLED_TASK_TYPES[0]] = pa
                    agents_registered += 1
                    log.debug("[INIT] PlannerAgent registered (%s)", pa.HANDLED_TASK_TYPES)
                except Exception as _e:
                    log.debug("[INIT] PlannerAgent registration failed: %s", _e)

            if _ResearchAgent is not None:
                try:
                    ra = _ResearchAgent(
                        internet_manager=getattr(self, "internet", None),
                        github_code_search=getattr(self, "github_code_search", None),
                        stackoverflow_search=getattr(self, "stackoverflow_search", None),
                        knowledge_db=self.db,
                    )
                    for tt in ra.HANDLED_TASK_TYPES:
                        rm.register_agent(tt, ra.handle)
                    self.phase2_agents[ra.HANDLED_TASK_TYPES[0]] = ra
                    agents_registered += 1
                    log.debug("[INIT] ResearchAgent registered (%s)", ra.HANDLED_TASK_TYPES)
                except Exception as _e:
                    log.debug("[INIT] ResearchAgent registration failed: %s", _e)

            if _CodingAgent is not None:
                try:
                    ca = _CodingAgent(
                        hf_llm=getattr(self, "llm", None),
                        code_generator=getattr(self, "code_generator", None),
                        knowledge_db=self.db,
                    )
                    for tt in ca.HANDLED_TASK_TYPES:
                        rm.register_agent(tt, ca.handle)
                    self.phase2_agents[ca.HANDLED_TASK_TYPES[0]] = ca
                    agents_registered += 1
                    log.debug("[INIT] CodingAgent registered (%s)", ca.HANDLED_TASK_TYPES)
                except Exception as _e:
                    log.debug("[INIT] CodingAgent registration failed: %s", _e)

            if _TestingAgent is not None:
                try:
                    ta = _TestingAgent(
                        code_compiler=getattr(self, "code_compiler", None),
                        code_error_fixer=getattr(self, "code_error_fixer", None),
                    )
                    for tt in ta.HANDLED_TASK_TYPES:
                        rm.register_agent(tt, ta.handle)
                    self.phase2_agents[ta.HANDLED_TASK_TYPES[0]] = ta
                    agents_registered += 1
                    log.debug("[INIT] TestingAgent registered (%s)", ta.HANDLED_TASK_TYPES)
                except Exception as _e:
                    log.debug("[INIT] TestingAgent registration failed: %s", _e)

            if _ReflectionAgent is not None:
                try:
                    rfa = _ReflectionAgent(
                        knowledge_db=self.db,
                        brain_trainer=_brain_trainer,
                    )
                    for tt in rfa.HANDLED_TASK_TYPES:
                        rm.register_agent(tt, rfa.handle)
                    self.phase2_agents[rfa.HANDLED_TASK_TYPES[0]] = rfa
                    agents_registered += 1
                    log.debug("[INIT] ReflectionAgent registered (%s)", rfa.HANDLED_TASK_TYPES)
                except Exception as _e:
                    log.debug("[INIT] ReflectionAgent registration failed: %s", _e)

            if _ArchitectureAgent is not None:
                try:
                    aarch = _ArchitectureAgent(
                        build_scanner=getattr(self, "build_scanner", None),
                        github_code_search=getattr(self, "github_code_search", None),
                        knowledge_db=self.db,
                    )
                    for tt in aarch.HANDLED_TASK_TYPES:
                        rm.register_agent(tt, aarch.handle)
                    self.phase2_agents[aarch.HANDLED_TASK_TYPES[0]] = aarch
                    agents_registered += 1
                    log.debug("[INIT] ArchitectureAgent registered (%s)", aarch.HANDLED_TASK_TYPES)
                except Exception as _e:
                    log.debug("[INIT] ArchitectureAgent registration failed: %s", _e)

            # ── Start background dispatch loop ────────────────────────────────
            rm.start_loop(poll_interval=2.0)
            log.info(
                "✅ Phase-2 agent architecture ready: %d agent(s) registered, "
                "dispatch loop running",
                agents_registered,
            )
            self.startup_report.add("phase2_agents", "ready",
                                    f"{agents_registered} agent(s)")

        except Exception as _init_exc:
            log.warning("[INIT] Phase-2 agent init failed: %s", _init_exc)
            self.startup_report.add("phase2_agents", "degraded", str(_init_exc))

    def _init_self_improvements(self):
        """Initialize 10 self-improvement modules."""
        # pylint: disable=too-many-branches,too-many-statements
        log.info("[SELF-IMPROVEMENTS] Initializing 10 modules...")

        try:
            if ParallelLearner and self.researcher:
                self.parallel_learner = ParallelLearner(self.researcher, max_workers=3)
                log.info("[SELF-IMPROVEMENTS] ✅ ParallelLearner")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] ParallelLearner failed: {e}")

        try:
            if ReasoningEngine and self.db:
                self.reasoning_engine = ReasoningEngine(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ ReasoningEngine")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] ReasoningEngine failed: {e}")

        try:
            if GapAnalyzer and self.db and self.researcher:
                self.gap_analyzer = GapAnalyzer(self.db, self.researcher)
                log.info("[SELF-IMPROVEMENTS] ✅ GapAnalyzer")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] GapAnalyzer failed: {e}")

        try:
            if KnowledgeSynthesizer and self.db:
                self.synthesizer = KnowledgeSynthesizer(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ KnowledgeSynthesizer")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] KnowledgeSynthesizer failed: {e}")

        try:
            if PredictionEngine and self.db:
                self.predictor = PredictionEngine(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ PredictionEngine")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] PredictionEngine failed: {e}")

        try:
            if MemoryOptimizer and self.db:
                self.memory_optimizer = MemoryOptimizer(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ MemoryOptimizer")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] MemoryOptimizer failed: {e}")

        try:
            if AdaptiveLearning:
                _qf = None
                try:
                    from modules.quality_feedback import get_quality_feedback  # noqa: PLC0415
                    _qf = get_quality_feedback()
                except Exception as _qf_err:
                    log.debug(f"[SELF-IMPROVEMENTS] AdaptiveLearning QualityFeedback unavailable: {_qf_err}")
                self.adaptive_learning = AdaptiveLearning(
                    knowledge_db=self.db,
                    quality_feedback=_qf,
                )
                log.info("[SELF-IMPROVEMENTS] ✅ AdaptiveLearning")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] AdaptiveLearning failed: {e}")

        try:
            if Metacognition and self.db:
                self.metacognition = Metacognition(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ Metacognition")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] Metacognition failed: {e}")

        try:
            if CollaborativeLearner:
                self.collaborative_learner = CollaborativeLearner()
                log.info("[SELF-IMPROVEMENTS] ✅ CollaborativeLearner")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] CollaborativeLearner failed: {e}")

        try:
            if ImprovementIntegrator:
                self.improvements = ImprovementIntegrator(self, self.db, self.researcher)
                log.info("[SELF-IMPROVEMENTS] ✅ ImprovementIntegrator")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] ImprovementIntegrator failed: {e}")

        try:
            if AgenticWorkflow:
                self.agentic_workflows = AgenticWorkflow(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ AgenticWorkflow")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] AgenticWorkflow failed: {e}")

        try:
            if EnterpriseUtility:
                self.enterprise_utility = EnterpriseUtility(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ EnterpriseUtility")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] EnterpriseUtility failed: {e}")

        try:
            if MultimodalIntelligence:
                self.multimodal_intelligence = MultimodalIntelligence(self.db)
                log.info("[SELF-IMPROVEMENTS] ✅ MultimodalIntelligence")
        except Exception as e:
            log.debug(f"[SELF-IMPROVEMENTS] MultimodalIntelligence failed: {e}")

        log.info("[SELF-IMPROVEMENTS] ✅ All modules initialized (13 total)!")

    def _start_background_services(self):
        """Start background services and loops."""
        if not self.config.enable_background_loops:
            log.info("Background loops disabled via config")
            return

        # Acquire a Termux CPU wake-lock so Android does not freeze the
        # background loops when the screen turns off or Termux goes to the
        # background.  On non-Termux platforms this is a silent no-op.
        if self.wakelock is not None:
            self.wakelock.acquire()

        self._start_sync_loops()

        if self.config.enable_async_loops:
            self._start_async_loops()

    def _start_sync_loops(self):
        """Start synchronous background loops."""
        if self.config.enable_background_loops:
            self._start_background_loop(self._health_loop, "HealthLoop")
            self._start_background_loop(self._trainer_loop, "TrainerLoop")
            self._start_background_loop(self._auto_research_loop, "ResearchLoop")
            self._start_background_loop(self._self_heal_loop, "HealLoop")
            self._start_background_loop(self._dump_monitoring_loop, "DumpMonitoringLoop")
            # Start LCSP v1 sync loop when SyncEngine is available
            if self.sync_engine is not None:
                try:
                    self.sync_engine.start_background_loop()
                    log.info("[Core] SyncEngine background loop started")
                except Exception as _se_loop_err:
                    log.debug("[Core] SyncEngine loop start failed: %s", _se_loop_err)

    def _start_async_loops(self):
        """Start asynchronous background loops."""
        try:
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)

            tasks = [
                self._async_health_loop(),
                self._async_trainer_loop(),
                self._async_auto_research_loop(),
                self._async_self_heal_loop(),
            ]

            for task in tasks:
                self._async_tasks.add(self._event_loop.create_task(task))

            self._start_background_loop(
                lambda: self._event_loop.run_forever(),
                "AsyncEventLoop"
            )
        except Exception as e:
            log.warning(f"Failed to start async loops: {e}")

    def _start_background_loop(self, target: Callable, name: str):
        """Start a background thread and track it."""
        try:
            # Prune finished threads before adding a new one so the list
            # does not grow without bound over the process lifetime.
            self._background_threads = [t for t in self._background_threads if t.is_alive()]
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._background_threads.append(thread)
            thread.start()
            log.debug(f"Started background thread: {name}")
        except Exception as e:
            log.error(f"Failed to start background thread {name}: {e}")

    # ============================
    # DUMP LOOP MONITORING (NO STARTUP DUMP)
    # ============================

    def _dump_monitoring_loop(self):
        """Monitor dump loop health and log periodically. NO DUMP AT STARTUP."""
        log.info("[DUMP LOOP] Monitoring started (delayed start, no initial dump)")
        check_count = 0

        while self.running:
            try:
                current_time = time.time()
                elapsed = current_time - self._last_dump_check

                if elapsed >= self.config.dump_loop_log_interval:
                    self._dump_loop_count += 1
                    mem_count = self._get_memory_count()

                    log.info(
                        f"[DUMP LOOP] Cycle #{self._dump_loop_count}: "
                        f"elapsed={int(elapsed)}s, memory_entries={mem_count}"
                    )

                    try:
                        if self.db and hasattr(self.db, "dump_state"):
                            safe_call(self.db.dump_state)
                            log.debug("[DUMP LOOP] Database state dumped successfully")
                    except Exception as e:
                        log.warning(f"[DUMP LOOP] Database dump failed: {e}")

                    self._last_dump_check = current_time
                    check_count += 1

                time.sleep(10)
            except Exception as e:
                loop_tracer.record("DumpMonitoringLoop", e)
                log.error(f"[DUMP LOOP] Monitoring error: {e}")
                time.sleep(10)

        log.info(f"[DUMP LOOP] Monitoring stopped after {self._dump_loop_count} cycles")

    # ============================
    # ASYNC LOOPS
    # ============================

    async def _async_health_loop(self):
        """Async version of health loop."""
        last = -1
        while self.running:
            uptime = int(time.time() - self.start_ts)
            if uptime // 120 != last:
                last = uptime // 120
                mem = self._get_memory_count()
                log.info(f"[HEALTH] uptime={uptime}s mem={mem}")
            await asyncio.sleep(5)

    async def _async_trainer_loop(self):
        """Async version of trainer loop."""
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
            await asyncio.sleep(90)

    async def _async_auto_research_loop(self):
        """Async version of auto research loop.

        For each queued topic: search → reflect → teach → store ale_learned memory.
        """
        # pylint: disable=too-many-branches,too-many-statements
        while self.running:
            try:
                if self.db and hasattr(self.db, "get_learning_queue") and self.researcher:
                    queued = self.db.get_learning_queue()
                    pending = [
                        item for item in queued
                        if isinstance(item, dict) and item.get("status") == "queued"
                    ]
                    for item in pending[-5:]:
                        topic = item.get("topic")
                        if not topic:
                            continue

                        log.info(f"[AUTO RESEARCH] {topic}")
                        if self.internet:
                            self.researcher.internet = self.internet  # pylint: disable=attribute-defined-outside-init
                        result = None
                        if hasattr(self.researcher, "search"):
                            result = safe_call(self.researcher.search, topic)

                        if result and self.db and hasattr(self.db, "add_fact"):
                            # Convert result list to clean joined text — never use str(list)
                            if isinstance(result, list):
                                result_text = "\n".join(
                                    (r.get("snippet") or r.get("text") or r.get("description")
                                     or r.get("content") or r.get("summary") or str(r))
                                    if isinstance(r, dict) else str(r)
                                    for r in result if r
                                )
                            else:
                                result_text = str(result)
                            result_text = result_text.strip()
                            # Store clean research text via store_research() so it
                            # produces a fully-structured record (key, value, tags,
                            # source, ts) rather than a raw string via add_fact().
                            try:
                                self.db.store_research(
                                    f"auto_research:{topic}",
                                    result_text,
                                    tags=["research", "auto"],
                                    source="async_auto_research_loop",
                                )
                            except Exception:
                                pass

                            # Reflect on the research result using topic + clean text
                            reflection_output = ""
                            reflect = getattr(self, "reflect", None)
                            if reflect:
                                try:
                                    if hasattr(reflect, "reflect_on_research"):
                                        reflection_output = str(
                                            reflect.reflect_on_research(topic, result_text[:600]) or ""
                                        )
                                    elif hasattr(reflect, "collect_and_summarize"):
                                        reflection_output = str(
                                            reflect.collect_and_summarize(topic) or ""
                                        )
                                    if getattr(self, '_loops_verbose', True):
                                        log.info(f"[AUTO RESEARCH] Reflected on '{topic}'")
                                except Exception as _re:
                                    log.debug(f"[AUTO RESEARCH] Reflection failed: {_re}")

                            # Feed to self-teacher with clean topic only
                            self_teacher = getattr(self, "self_teacher", None)
                            if self_teacher and hasattr(self_teacher, "teach"):
                                try:
                                    safe_call(self_teacher.teach, topic)
                                    if getattr(self, '_loops_verbose', True):
                                        log.info(f"[AUTO RESEARCH] Taught '{topic}' to self-teacher")
                                except Exception as _te:
                                    log.debug(f"[AUTO RESEARCH] Teaching failed: {_te}")

                            # Consolidated memory entry so 'recall <topic>' returns results.
                            # Use millisecond timestamp to avoid same-second key collisions.
                            try:
                                topic_tag = topic.split()[0].lower() if topic.split() else "general"
                                self.db.add_fact(
                                    f"ale_learned:{topic.replace(' ', '_')}:{int(time.time() * 1000)}",
                                    {
                                        "topic": topic,
                                        "research": result_text[:500],
                                        "reflection": reflection_output[:400],
                                        "source": "async_auto_research_loop",
                                    },
                                    tags=["ale_learned", "memory", "auto_research", topic_tag],
                                )
                            except Exception:
                                pass

                        if hasattr(self.db, "mark_learning_done"):
                            try:
                                self.db.mark_learning_done(topic)
                            except Exception:
                                pass
            except Exception:
                pass
            await asyncio.sleep(150)

    async def _async_self_heal_loop(self):
        """Async version of self heal loop."""
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
            # Also run memory maintenance (prune old interactions, condense KB)
            try:
                maintenance = getattr(self, "self_maintenance", None)
                if maintenance is not None:
                    fn = getattr(maintenance, "run_with_learning",
                                 getattr(maintenance, "run", None))
                    if fn is not None:
                        safe_call(fn)
            except Exception:
                pass
            await asyncio.sleep(300)

    # ============================
    # SYNC LOOPS
    # ============================

    def _health_loop(self):
        """Monitor system health periodically."""
        last = -1
        while self.running:
            try:
                uptime = int(time.time() - self.start_ts)
                if uptime // self.config.health_check_interval != last:
                    last = uptime // self.config.health_check_interval
                    mem = self._get_memory_count()
                    if getattr(self, '_loops_verbose', True):
                        log.info(f"[HEALTH] uptime={uptime}s mem={mem}")
                time.sleep(5)
            except Exception as e:
                loop_tracer.record("HealthLoop", e)
                log.debug(f"Health loop error: {e}")
                time.sleep(5)

    def _trainer_loop(self):
        """Run training cycles periodically."""
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
            except Exception as e:
                loop_tracer.record("TrainerLoop", e)
            time.sleep(90)

    def _auto_research_loop(self):
        """Run autonomous research loop periodically.

        For each queued topic: search → reflect → teach → store ale_learned memory.
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        while self.running:
            try:
                # Skip if ALE is already running — it covers all research steps
                # and calling researcher.search() concurrently would saturate
                # the network stack and serialise on internal locks.
                _ale = getattr(self, "autonomous_engine", None)
                if _ale is not None and getattr(_ale, "running", False):
                    time.sleep(150)
                    continue

                if self.db and hasattr(self.db, "get_learning_queue") and self.researcher:
                    queued = self.db.get_learning_queue()
                    pending = [
                        item for item in queued
                        if isinstance(item, dict) and item.get("status") == "queued"
                    ]
                    for item in pending[-self.config.research_queue_limit:]:
                        topic = item.get("topic")
                        if not topic:
                            continue

                        if getattr(self, '_loops_verbose', True):
                            log.info(f"[AUTO RESEARCH] {topic}")

                        cache_key = self.research_cache.cache_key(topic)
                        cached = self.research_cache.get(cache_key)
                        result = None

                        if cached:
                            if getattr(self, '_loops_verbose', True):
                                log.info(f"[AUTO RESEARCH] Cache hit for {topic}")
                            result = cached
                        else:
                            if self.internet:
                                self.researcher.internet = self.internet  # pylint: disable=attribute-defined-outside-init
                            if hasattr(self.researcher, "search"):
                                # Run search in a daemon thread with a hard 60s
                                # timeout so a stalled network call never freezes
                                # the entire ResearchLoop thread indefinitely.
                                _result_box: list = [None]

                                def _do_search(_t=topic):
                                    _result_box[0] = safe_call(self.researcher.search, _t)

                                _st = threading.Thread(target=_do_search, daemon=True)
                                _st.start()
                                _st.join(timeout=300)
                                if not _st.is_alive():
                                    result = _result_box[0]
                                else:
                                    log.debug(
                                        "[AUTO RESEARCH] Search timed out for '%s' — skipping",
                                        topic,
                                    )
                                if result:
                                    self.research_cache.set(cache_key, result)

                        if result and self.db and hasattr(self.db, "add_fact"):
                            # Convert result list to clean joined text — never use str(list)
                            if isinstance(result, list):
                                result_text = "\n".join(
                                    (r.get("snippet") or r.get("text") or r.get("description")
                                     or r.get("content") or r.get("summary") or str(r))
                                    if isinstance(r, dict) else str(r)
                                    for r in result if r
                                )
                            else:
                                result_text = str(result)
                            result_text = result_text.strip()
                            # Store clean research text via store_research() so it
                            # produces a fully-structured record (key, value, tags,
                            # source, ts) rather than a raw string via add_fact().
                            try:
                                self.db.store_research(
                                    f"auto_research:{topic}",
                                    result_text,
                                    tags=["research", "auto"],
                                    source="auto_research_loop",
                                )
                            except Exception:
                                pass

                            # Reflect on the research result using topic + clean text
                            reflection_output = ""
                            reflect = getattr(self, "reflect", None)
                            if reflect:
                                try:
                                    if hasattr(reflect, "reflect_on_research"):
                                        reflection_output = str(
                                            reflect.reflect_on_research(topic, result_text[:600]) or ""
                                        )
                                    elif hasattr(reflect, "collect_and_summarize"):
                                        reflection_output = str(
                                            reflect.collect_and_summarize(topic) or ""
                                        )
                                    if getattr(self, '_loops_verbose', True):
                                        log.info(f"[AUTO RESEARCH] Reflected on '{topic}'")
                                except Exception as _re:
                                    log.debug(f"[AUTO RESEARCH] Reflection failed: {_re}")

                            # Feed to self-teacher with clean topic only
                            self_teacher = getattr(self, "self_teacher", None)
                            if self_teacher and hasattr(self_teacher, "teach"):
                                try:
                                    safe_call(self_teacher.teach, topic)
                                    if getattr(self, '_loops_verbose', True):
                                        log.info(f"[AUTO RESEARCH] Taught '{topic}' to self-teacher")
                                except Exception as _te:
                                    log.debug(f"[AUTO RESEARCH] Teaching failed: {_te}")

                            # Store consolidated memory entry (ale_learned) so that
                            # 'recall <topic>' returns the full research+reflection pair.
                            # Use millisecond timestamp to avoid same-second key collisions.
                            try:
                                topic_tag = topic.split()[0].lower() if topic.split() else "general"
                                self.db.add_fact(
                                    f"ale_learned:{topic.replace(' ', '_')}:{int(time.time() * 1000)}",
                                    {
                                        "topic": topic,
                                        "research": result_text[:500],
                                        "reflection": reflection_output[:400],
                                        "source": "auto_research_loop",
                                    },
                                    tags=["ale_learned", "memory", "auto_research", topic_tag],
                                )
                            except Exception:
                                pass

                        if hasattr(self.db, "mark_learning_done"):
                            try:
                                self.db.mark_learning_done(topic)
                            except Exception:
                                pass
            except Exception as e:
                loop_tracer.record("ResearchLoop", e)
            # Periodically check if the current grade exam should be run
            try:
                gc = getattr(self, "graded_curriculum", None)
                if gc is not None:
                    gc.maybe_run_exam()
            except Exception:
                pass
            time.sleep(150)

    def _self_heal_loop(self):
        """Run self-healing loop periodically."""
        while self.running:
            try:
                if self.self_healer:
                    if hasattr(self.self_healer, "run_cycle"):
                        safe_call(self.self_healer.run_cycle)
                    elif hasattr(self.self_healer, "repair"):
                        safe_call(self.self_healer.repair)
                    elif hasattr(self.self_healer, "full_heal"):
                        safe_call(self.self_healer.full_heal, self)
            except Exception as e:
                loop_tracer.record("HealLoop", e)
            # Also run memory maintenance (prune old interactions, condense KB)
            try:
                maintenance = getattr(self, "self_maintenance", None)
                if maintenance is not None:
                    fn = getattr(maintenance, "run_with_learning",
                                 getattr(maintenance, "run", None))
                    if fn is not None:
                        safe_call(fn)
            except Exception as _me:
                log.debug("[HealLoop] SelfMaintenance error: %s", _me)
            time.sleep(300)

    # ============================
    # ORCHESTRATOR METHODS
    # ============================

    def _run_audit(self) -> str:
        """Run repository audit via orchestrator tools."""
        try:
            if not ORCHESTRATOR_AVAILABLE or not RepoAuditor:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Running audit...")
            if safe_call:
                safe_call(RepoAuditor)
            log.info("[ORCHESTRATOR] Audit completed")
            return "[Audit completed]"
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Audit failed: {e}")
            return f"[Audit failed: {e}]"

    def _run_self_heal_orchestrated(self) -> str:
        """Run self-heal via orchestrator tools."""
        try:
            if not ORCHESTRATOR_AVAILABLE or not self_heal_main:
                return "[Orchestrator not available]"
            log.info("[ORCHESTRATOR] Running self-heal...")
            safe_call(self_heal_main)
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
            db = LocalDB() if LocalDB is not None else self.db
            fg = FixGuideGenerator(db)
            _guide_dir = BASE_DIR if os.access(BASE_DIR, os.W_OK) else tempfile.gettempdir()
            fix_guide_path = os.path.join(_guide_dir, "Fix_Guide.txt")
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
                result += f"\nFailed (first 5): {', '.join(failed_modules[:5])}"
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

            with self._lock:
                if self._orchestration_running:
                    return "[Orchestration already running]"
                self._orchestration_running = True

            try:
                log.info("[ORCHESTRATOR] Pipeline started")
                results = [
                    "=== ORCHESTRATION PIPELINE ===",
                    self._run_audit(),
                    self._run_self_heal_orchestrated(),
                    self._generate_fix_guide(),
                    self._verify_imports_orchestrated(),
                ]
                log.info("[ORCHESTRATOR] Pipeline completed")
                return "\n".join(results)
            finally:
                with self._lock:
                    self._orchestration_running = False
        except Exception as e:
            log.error(f"[ORCHESTRATOR] Pipeline failed: {e}")
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
    # SLSA MANAGEMENT
    # ============================

    def _start_slsa_engine(self, topics: Optional[List[str]] = None) -> str:
        """Start SLSA generator engine."""
        try:
            if not SLSAGenerator:
                return "[SLSAGenerator not available]"

            if self.slsa_engine and self.slsa_thread and self.slsa_thread.is_alive():
                return "[SLSA engine already running]"

            log.info(f"[SLSA] Starting SLSA engine with topics: {topics}")
            self.slsa_engine = SLSAGenerator(
                interval=20,
                topics=topics or ["car", "computer", "phone"],
                db=getattr(self, "db", None),
                internet=self.internet,
            )
            self.slsa_thread = self.slsa_engine.start()
            log.info("[SLSA] SLSA engine started successfully")
            return f"[SLSA] Generator started with topics: {topics or ['car', 'computer', 'phone']}"
        except Exception as e:
            log.error(f"[SLSA] Failed to start engine: {e}")
            return f"[SLSA start failed: {e}]"

    def _stop_slsa_engine(self) -> str:
        """Stop SLSA generator engine."""
        try:
            if not self.slsa_engine:
                return "[SLSA engine not running]"

            log.info("[SLSA] Stopping SLSA engine...")
            self.slsa_engine.stop()  # join is now handled inside SLSAGenerator.stop()

            self.slsa_engine = None
            self.slsa_thread = None
            log.info("[SLSA] SLSA engine stopped successfully")
            return "[SLSA] Generator stopped"
        except Exception as e:
            log.error(f"[SLSA] Failed to stop engine: {e}")
            return f"[SLSA stop failed: {e}]"

    def _restart_slsa_engine(self, topics: Optional[List[str]] = None) -> str:
        """Restart SLSA generator engine."""
        try:
            log.info(f"[SLSA] Restarting SLSA engine with topics: {topics}")
            self._stop_slsa_engine()
            time.sleep(0.5)
            return self._start_slsa_engine(topics)
        except Exception as e:
            log.error(f"[SLSA] Failed to restart engine: {e}")
            return f"[SLSA restart failed: {e}]"

    def _get_slsa_status(self) -> str:
        """Get SLSA engine status."""
        try:
            if not self.slsa_engine:
                return "[SLSA] Engine not initialized"

            running = getattr(self.slsa_engine, "is_running", False) or (
                self.slsa_thread and self.slsa_thread.is_alive()
            )
            topics = getattr(self.slsa_engine, "topics", [])
            if running:
                return f"[SLSA] Generator is running with topics: {topics}"
            return f"[SLSA] Generator is initialized but not running (topics: {topics})"
        except Exception as e:
            log.error(f"[SLSA] Failed to get status: {e}")
            return f"[SLSA status unavailable: {e}]"

    # ============================
    # UTILITY METHODS
    # ============================

    def _get_memory_count(self) -> int:
        """Return the number of stored memory entries, or 0 if unavailable."""
        try:
            if self.db:
                if hasattr(self.db, "recent_interactions"):
                    return len(self.db.recent_interactions(self.config.max_memory_entries))
                if hasattr(self.db, "get_learning_log"):
                    return len(self.db.get_learning_log())
        except Exception:
            pass
        return 0

    def get_memory_count(self) -> int:
        """Public accessor for the number of stored memory entries."""
        return self._get_memory_count()

    def _trigger_learning(self, user_input: str, response: str):
        """Invoke NiblitLearning on each conversation turn, queue follow-up tasks."""
        # ── Phase 20: advance temporal epoch ─────────────────────────────────
        _epoch_tag: Optional[int] = None
        if getattr(self, "_tcl", None) is not None:
            try:
                _epoch_tag = self._tcl.tick()
            except Exception:
                pass

        # Record user activity (not idle)
        if self.autonomous_engine:
            try:
                if hasattr(self.autonomous_engine, "record_user_activity"):
                    self.autonomous_engine.record_user_activity()
            except Exception as e:
                log.debug(f"Failed to record user activity: {e}")

        if self.tasks:
            try:
                self.tasks.add_task("remember", {"input": user_input, "response": response})
            except Exception as _e:
                log.debug(f"NiblitTasks.add_task failed: {_e}")

        # ── Quality scoring → unified learning loop ───────────────────────────
        # Score every response with QualityFeedback so KB facts are reinforced
        # or decayed and the PolicyOptimizer accumulates an episode for this
        # conversation turn.  Uses the DB attached to NiblitCore when available.
        _qf_result = None
        if user_input and response:
            try:
                from modules.quality_feedback import get_quality_feedback
                qf = get_quality_feedback()
                kb = getattr(self, "db", None)
                _qf_result = qf.record_answer_quality(
                    query=user_input,
                    answer=response,
                    knowledge_db=kb,
                )
            except Exception as _qf_err:
                log.debug("_trigger_learning QualityFeedback failed: %s", _qf_err)

        if self.learning:
            try:
                _eval_quality = None
                _chosen_advisor = ""
                if getattr(self, "evaluation_engine", None) is not None:
                    try:
                        _eval_quality = self.evaluation_engine.last_quality_score()
                        _eval_history = self.evaluation_engine.get_history()
                        if _eval_history:
                            _chosen_advisor = str(_eval_history[-1].get("chosen_advisor", ""))
                    except Exception:
                        pass
                _feedback_score = (
                    float(_qf_result.get("score"))
                    if isinstance(_qf_result, dict) and _qf_result.get("score") is not None
                    else None
                )
                _feedback_arbitration = self._arbitrate_turn_quality(
                    evaluation_quality=_eval_quality,
                    feedback_quality=_feedback_score,
                )
                self._last_feedback_arbitration = _feedback_arbitration
                # Stamp arbitration result with current epoch for traceability
                if _epoch_tag is not None and getattr(self, "_tcl", None) is not None:
                    try:
                        self._tcl.tag_decision(_feedback_arbitration)
                    except Exception:
                        pass
                self.learning.process_interaction(
                    user_message=user_input,
                    ai_response=response,
                    quality_score=_eval_quality,
                    feedback_score=_feedback_score,
                    chosen_advisor=_chosen_advisor,
                    loop_source="niblit_core",
                    epoch_tag=_epoch_tag,
                    # Phase 21: propagate multi-axis quality to the learning record
                    quality_axes=_feedback_arbitration.get("quality_axes")
                    if isinstance(_feedback_arbitration, dict)
                    else None,
                )
                # ── Phase 20: cadence-gated evolve() ─────────────────────────
                # evolve() aggregates the full window every call — gate it to
                # the MEDIUM tier (default ≥60 s) to avoid O(n) cost every turn.
                _should_evolve = True
                if getattr(self, "_tcl", None) is not None:
                    try:
                        _should_evolve = self._tcl.should_adapt("MEDIUM")
                    except Exception:
                        pass
                if _should_evolve:
                    self.learning.evolve()
                    if getattr(self, "_tcl", None) is not None:
                        try:
                            self._tcl.record_heartbeat("MEDIUM")
                        except Exception:
                            pass
            except Exception as _e:
                log.debug(f"NiblitLearning unified loop update failed: {_e}")

        # Feed the same interaction into AdaptiveLearning so preference strategy
        # and topic guidance evolve alongside the phase-19 unified loop.
        if getattr(self, "adaptive_learning", None):
            try:
                _turn_quality = None
                _arb = getattr(self, "_last_feedback_arbitration", None)
                if isinstance(_arb, dict):
                    _turn_quality = _arb.get("resolved_quality")
                if _turn_quality is None and getattr(self, "evaluation_engine", None) is not None:
                    try:
                        _turn_quality = self.evaluation_engine.last_quality_score()
                    except Exception:
                        _turn_quality = None
                if _turn_quality is not None:
                    _turn_quality = max(0.0, min(1.0, float(_turn_quality)))
                    _satisfaction = int(round(1.0 + (_turn_quality * 4.0)))
                else:
                    _satisfaction = 3
                _satisfaction = max(1, min(5, _satisfaction))
                self.adaptive_learning.record_feedback(
                    query=user_input,
                    response=response,
                    satisfaction=_satisfaction,
                    propagate_quality=False,
                )
            except Exception as _al_err:
                log.debug("AdaptiveLearning turn feedback failed: %s", _al_err)

        self._refresh_unified_feedback_status()

    def health_check(self) -> HealthCheckResult:
        """Comprehensive system health check."""
        components = {}
        errors = []

        checks = [
            ("database", self.db),
            ("brain", self.brain),
            ("router", self.router),
            ("identity", self.identity),
            ("guard", self.guard),
            ("internet", self.internet),
            ("learning", self.learning),
            ("llm", self.llm),
            ("improvements", self.improvements),
            ("autonomous_engine", self.autonomous_engine),
        ]

        for name, component in checks:
            if component is None:
                components[name] = "unavailable"
            else:
                try:
                    if hasattr(component, "health_check"):
                        result = component.health_check()
                        components[name] = "healthy" if result else "degraded"
                    else:
                        components[name] = "ok"
                except Exception as e:
                    components[name] = "error"
                    errors.append(f"{name}: {e}")

        if errors:
            status = "critical" if len(errors) > 2 else "degraded"
        else:
            status = "healthy"

        return HealthCheckResult(
            status=status,
            components=components,
            uptime_seconds=int(time.time() - self.start_ts),
            memory_entries=self._get_memory_count(),
            errors=errors,
        )

    # ============================
    # COMMAND HANDLER (CLEAN & SIMPLE)
    # ============================

    def handle(self, text: str) -> str:
        """Process a user command and return a response."""
        start_time = time.time()
        try:
            result = self._handle_impl(text)
            elapsed_ms = (time.time() - start_time) * 1000
            self.metrics.record_operation("handle", elapsed_ms, success=True)
            return result
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            self.metrics.record_operation("handle", elapsed_ms, success=False)
            log.error(f"Handler exception: {e}", exc_info=True)
            raise

    def _handle_impl(self, text: str) -> str:  # pylint: disable=too-many-return-statements
        """
        Main handler with clean layered architecture.

        Flow:
        1. CommandRegistry (commands only - zero LLM)
        2. Brain commands (self-research, self-idea, reflect - uses modules, NOT LLM)
        3. SLSA commands
        4. Orchestrator commands
        5. System commands (status, health, metrics)
        6. Autonomous Learning commands (NEW)
        7. Self-Improvement commands (handled in _handle_impl BEFORE registry)
        8. Intent parsing (core commands)
        9. Internet commands (search, summary - uses internet directly, NOT LLM)
        10. Router fallback (complex routing)
        11. Brain.think() (ONLY for general chat)
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        ltext = text.lower().strip()

        log.debug(f"[HANDLE] Input: '{text[:50]}...' | Normalized: '{ltext[:50]}...'")

        # ============================
        # LAYER 1: COMMAND REGISTRY (if enabled)
        # ============================
        if self.command_registry:
            try:
                result = self.command_registry.execute(ltext)
                if result:
                    log.debug("[COMMAND_REGISTRY] Command executed")
                    self._trigger_learning(text, result)
                    return result
            except Exception as e:
                log.debug(f"[COMMAND_REGISTRY] Failed: {e}")

        # ============================
        # LAYER 2: BRAIN COMMANDS (uses modules, NOT LLM)
        # ============================
        # Direct module commands — handled by _cmd_* methods which use modules directly
        direct_module_commands = (
            "self-research", "self-heal", "self-idea", "self-implement",
            "reflect", "auto-reflect", "self-teach", "idea-implement",
        )
        if any(ltext.startswith(cmd) for cmd in direct_module_commands):
            log.debug(f"[MODULE-CMD] Intercepted: {ltext.split()[0]}")
            # Try direct module handlers first
            if ltext.startswith("self-research"):
                return self._cmd_self_research(text)
            if ltext.startswith("self-idea"):
                return self._cmd_self_idea(text)
            if ltext.startswith("self-implement"):
                return self._cmd_self_implement(text)
            if ltext.startswith("reflect"):
                return self._cmd_reflect(text)
            if ltext.startswith("self-teach"):
                return self._cmd_self_teach(text)
            if ltext.startswith("idea-implement"):
                return self._cmd_idea_implement(text)
            # Remaining (self-heal, auto-reflect): fall through to brain
            if self.brain:
                try:
                    response = safe_call(self.brain.handle_command, text)
                    if response:
                        self._trigger_learning(text, response)
                        return response
                except Exception as e:
                    log.warning(f"Brain command failed: {e}")
                    return f"[Brain command failed: {e}]"

        # ============================
        # LAYER 3: SLSA COMMANDS
        # ============================
        if ltext == "slsa-status" or ltext == "status-slsa":
            log.debug("[SLSA-CMD] Intercepted: status")
            return self._get_slsa_status()

        if ltext.startswith("start_slsa"):
            log.debug("[SLSA-CMD] Intercepted: start")
            rest = ltext[len("start_slsa"):].strip()
            topics = rest.split() if rest else None
            return self._start_slsa_engine(topics)

        if ltext.startswith("stop_slsa"):
            log.debug("[SLSA-CMD] Intercepted: stop")
            return self._stop_slsa_engine()

        if ltext.startswith("restart_slsa"):
            log.debug("[SLSA-CMD] Intercepted: restart")
            rest = ltext[len("restart_slsa"):].strip()
            topics = rest.split() if rest else None
            return self._restart_slsa_engine(topics)

        # ============================
        # LAYER 4: ORCHESTRATOR COMMANDS
        # ============================
        if ltext.startswith("orchestrate audit"):
            log.debug("[ORCH-CMD] Intercepted: audit")
            return self._run_audit()
        if ltext.startswith("orchestrate self-heal"):
            log.debug("[ORCH-CMD] Intercepted: self-heal")
            return self._run_self_heal_orchestrated()
        if ltext.startswith("orchestrate fix-guide"):
            log.debug("[ORCH-CMD] Intercepted: fix-guide")
            return self._generate_fix_guide()
        if ltext.startswith("orchestrate verify"):
            log.debug("[ORCH-CMD] Intercepted: verify")
            return self._verify_imports_orchestrated()
        if ltext.startswith("orchestrate pipeline"):
            log.debug("[ORCH-CMD] Intercepted: pipeline")
            return self._run_orchestration_pipeline()

        if ltext.startswith("hf-task "):
            log.debug("[HF-CMD] Intercepted")
            task_prompt = text[8:].strip()
            return self._hf_task(task_prompt)

        # ============================
        # LAYER 4b: DIAGNOSTIC / TESTER COMMANDS
        # ============================
        if ltext.startswith("run-diagnostics"):
            log.debug("[DIAG-CMD] Intercepted: run-diagnostics")
            return self._cmd_run_diagnostics(text)

        if ltext.startswith("run-live-test"):
            log.debug("[LIVE-TEST-CMD] Intercepted: run-live-test")
            return self._cmd_run_live_test(text)

        if ltext.startswith("loop-errors"):
            log.debug("[DIAG-CMD] Intercepted: loop-errors")
            return self.loop_tracer_summary()

        # ============================
        # LAYER 5: SYSTEM STATUS COMMANDS
        # ============================
        if ltext.startswith("health"):
            log.debug("[STATUS-CMD] Intercepted: health")
            return self._cmd_health(text)

        if ltext.startswith("metrics"):
            log.debug("[STATUS-CMD] Intercepted: metrics")
            return self._cmd_metrics(text)

        if ltext.startswith("dump"):
            log.debug("[STATUS-CMD] Intercepted: dump")
            return f"[DUMP] Loop cycles: {self._dump_loop_count}, Memory: {self._get_memory_count()}"

        # ============================
        # LAYER 6: AUTONOMOUS LEARNING COMMANDS
        # ============================
        if ltext.startswith("autonomous-learn"):
            if "start" in ltext:
                return self._cmd_autonomous_start(text)
            if "stop" in ltext:
                return self._cmd_autonomous_stop(text)
            if "code-status" in ltext:
                return self._cmd_autonomous_code_status(text)
            if "status" in ltext:
                return self._cmd_autonomous_status(text)
            if "add-topic" in ltext:
                return self._cmd_autonomous_add_topic(text)

        # ============================
        # LAYER 7: SELF-IMPROVEMENT COMMANDS (BEFORE INTENT PARSING)
        # ============================
        if ltext == "show improvements":
            log.debug("[IMPROVE-CMD] Intercepted: show improvements")
            return self._cmd_show_improvements(text)

        if ltext == "run improvement-cycle":
            log.debug("[IMPROVE-CMD] Intercepted: run improvement-cycle")
            return self._cmd_run_improvement_cycle(text)

        if ltext == "improvement-status":
            log.debug("[IMPROVE-CMD] Intercepted: improvement-status")
            return self._cmd_improvement_status(text)

        if ltext in ("new commands", "show new commands", "what's new", "whats new",
                     "new features", "recent commands", "added commands"):
            log.debug("[IMPROVE-CMD] Intercepted: new commands")
            return self._cmd_show_new_commands(text)

        # ============================
        # LAYER 7b: LIVE UPDATER COMMANDS
        # ============================
        if ltext.startswith("reload "):
            mod_name = text[len("reload "):].strip()
            if mod_name:
                log.debug(f"[UPDATER-CMD] Intercepted: reload {mod_name}")
                return self._cmd_reload_module(mod_name)

        if ltext in ("upgrade", "update-self", "update self"):
            log.debug("[UPDATER-CMD] Intercepted: upgrade")
            return self._cmd_upgrade()

        if ltext in ("update-history", "reload-history"):
            log.debug("[UPDATER-CMD] Intercepted: update-history")
            return self._cmd_update_history()

        # ============================
        # LAYER 7c: STRUCTURAL AWARENESS COMMANDS
        # ============================
        if ltext in ("my structure", "show structure", "niblit structure", "struct"):
            log.debug("[SA-CMD] Intercepted: my structure")
            return self._cmd_sa_structure()

        if ltext in ("my threads", "active threads", "threads"):
            log.debug("[SA-CMD] Intercepted: my threads")
            return self._cmd_sa_threads()

        if ltext in ("my loops", "active loops", "loops", "background loops"):
            log.debug("[SA-CMD] Intercepted: my loops")
            return self._cmd_sa_loops()

        if ltext in ("my modules", "loaded modules", "modules"):
            log.debug("[SA-CMD] Intercepted: my modules")
            return self._cmd_sa_modules()

        if ltext in ("my commands", "all commands"):
            log.debug("[SA-CMD] Intercepted: my commands")
            return self._cmd_sa_commands()

        if ltext in ("runtime status", "live status", "dashboard"):
            log.debug("[SA-CMD] Intercepted: dashboard")
            return self._cmd_sa_dashboard()

        if ltext in ("how do i work", "operational flow", "my flow", "loop flow"):
            log.debug("[SA-CMD] Intercepted: operational flow")
            return self._cmd_sa_flow()

        if ltext in ("resource usage", "my resources", "memory usage"):
            log.debug("[SA-CMD] Intercepted: resource usage")
            return self._cmd_sa_resources()

        # ============================
        # LAYER 7d: CODE & FILE CAPABILITY COMMANDS
        # ============================

        # Generate code
        if ltext.startswith("generate code ") or ltext.startswith("generate-code "):
            rest = text[text.index(" ", text.index(" ") + 1):].strip()
            log.debug("[CODE-CMD] generate code: %s", rest[:40])
            return self._cmd_generate_code(rest)

        # Run / compile / execute code
        if ltext.startswith("run code ") or ltext.startswith("run-code "):
            rest = text[text.index(" ", text.index(" ") + 1):].strip()
            log.debug("[CODE-CMD] run code: %s", rest[:40])
            return self._cmd_run_code(rest)

        # Validate syntax
        if ltext.startswith("validate "):
            rest = text[len("validate "):].strip()
            log.debug("[CODE-CMD] validate: %s", rest[:40])
            return self._cmd_validate_code(rest)

        # Execute a file
        if ltext.startswith("execute file ") or ltext.startswith("exec file "):
            filepath = text.split(None, 2)[-1].strip()
            log.debug("[FILE-CMD] execute file: %s", filepath)
            return self._cmd_execute_file(filepath)

        # File operations: read, write, list, delete, info
        if ltext.startswith("read file "):
            filepath = text[len("read file "):].strip()
            log.debug("[FILE-CMD] read: %s", filepath)
            return self._cmd_read_file(filepath)

        if ltext.startswith("write file "):
            rest = text[len("write file "):].strip()
            log.debug("[FILE-CMD] write: %s", rest[:40])
            return self._cmd_write_file(rest)

        if ltext.startswith("list files") or ltext in ("ls", "list dir", "list directory"):
            dirpath = text.split(None, 2)[-1].strip() if len(text.split()) > 2 else "."
            log.debug("[FILE-CMD] list: %s", dirpath)
            return self._cmd_list_files(dirpath)

        if ltext in ("file environment", "filesystem info", "fs info"):
            log.debug("[FILE-CMD] environment info")
            return self._cmd_file_environment()

        # Language study
        if ltext.startswith("study language ") or ltext.startswith("learn language "):
            lang = text.split(None, 2)[-1].strip()
            log.debug("[STUDY-CMD] study language: %s", lang)
            return self._cmd_study_language(lang)

        if ltext.startswith("code templates") or ltext == "list templates":
            lang = text.split(None, 2)[-1].strip() if len(text.split()) > 2 else ""
            log.debug("[CODE-CMD] list templates")
            return self._cmd_list_templates(lang)

        # Software study
        if ltext.startswith("study software ") or ltext.startswith("learn software "):
            cat = text.split(None, 2)[-1].strip()
            log.debug("[STUDY-CMD] study software: %s", cat)
            return self._cmd_study_software(cat)

        if ltext.startswith("software categories") or ltext == "list software":
            log.debug("[STUDY-CMD] list categories")
            return self._cmd_software_categories()

        if ltext.startswith("analyze architecture ") or ltext.startswith("study architecture "):
            arch = text.split(None, 2)[-1].strip()
            log.debug("[STUDY-CMD] analyze architecture: %s", arch)
            return self._cmd_analyze_architecture(arch)

        if ltext.startswith("design software ") or ltext.startswith("design-software "):
            desc = text.split(None, 2)[-1].strip()
            log.debug("[STUDY-CMD] design software: %s", desc[:40])
            return self._cmd_design_software(desc)

        if ltext in ("what have i studied", "studied software", "software studied"):
            log.debug("[STUDY-CMD] what i've studied")
            return self._cmd_software_studied()

        if ltext in ("available languages", "compiler languages", "supported languages"):
            log.debug("[CODE-CMD] available languages")
            return self._cmd_available_languages()

        # ============================
        # LAYER 7e: EVOLVE + CODE RESEARCH COMMANDS
        # ============================

        if ltext in ("evolve", "evolve step", "run evolve"):
            log.debug("[EVOLVE-CMD] step")
            return self._cmd_evolve_step()

        if ltext in ("evolve start", "start evolving", "start evolution"):
            log.debug("[EVOLVE-CMD] start")
            return self._cmd_evolve_start()

        if ltext in ("evolve stop", "stop evolving", "stop evolution"):
            log.debug("[EVOLVE-CMD] stop")
            return self._cmd_evolve_stop()

        if ltext in ("evolve status", "evolution status"):
            log.debug("[EVOLVE-CMD] status")
            return self._cmd_evolve_status()

        if ltext in ("evolve history", "evolution history"):
            log.debug("[EVOLVE-CMD] history")
            return self._cmd_evolve_history()

        if ltext.startswith("research code ") or ltext.startswith("research-code "):
            rest = text.split(None, 2)[-1].strip()
            log.debug("[CODE-RESEARCH-CMD] %s", rest[:40])
            return self._cmd_research_code(rest)

        # ============================
        # LAYER 7f: KNOWLEDGE RECALL & ACQUIRED DATA COMMANDS
        # ============================

        if ltext.startswith("recall ") or ltext == "recall":
            log.debug("[KNOWLEDGE-CMD] recall")
            return self._cmd_recall(text)

        if ltext.startswith("acquired data") or ltext.startswith("acquired-data"):
            log.debug("[KNOWLEDGE-CMD] acquired data")
            return self._cmd_acquired_data(text)

        if ltext in ("knowledge stats", "knowledge-stats", "kb stats", "kb-stats"):
            log.debug("[KNOWLEDGE-CMD] knowledge stats")
            return self._cmd_knowledge_stats(text)

        if ltext in ("ale processes", "ale-processes", "show ale", "niblit processes",
                     "how do you learn", "learning processes", "all processes"):
            log.debug("[KNOWLEDGE-CMD] ale processes")
            return self._cmd_ale_process_awareness(text)

        # ============================
        # LAYER 7g: LOCAL COPILOT COMMANDS (llama3 / qwen)
        # Direct dispatch via router.handle_command() — ensures these are NEVER
        # accidentally forwarded to brain.think() / the cloud LLM.
        # ============================
        if ltext == "llama3" or ltext.startswith("llama3 "):
            log.debug("[LLAMA3-CMD] Direct dispatch: %s", ltext.split()[0])
            if self.router:
                return self.router.handle_command(text)
            return "⚠️  Router not available — cannot handle llama3 command."

        if ltext == "qwen" or ltext.startswith("qwen "):
            log.debug("[QWEN-CMD] Direct dispatch: %s", ltext.split()[0])
            if self.router:
                return self.router.handle_command(text)
            return "⚠️  Router not available — cannot handle qwen command."

        # ============================
        # LAYER 8: INTENT PARSING & CORE COMMANDS
        # ============================
        intent, meta = parse_intent(text)
        log.debug(f"[INTENT] Parsed: {intent}")

        if intent == "help":
            log.debug("[CORE-CMD] Intercepted: help")
            return self._cmd_help(text)
        if intent == "time":
            log.debug("[CORE-CMD] Intercepted: time")
            return self._cmd_time(text)
        if intent == "status":
            log.debug("[CORE-CMD] Intercepted: status")
            return self._cmd_status(text)
        if intent == "remember":
            log.debug("[CORE-CMD] Intercepted: remember")
            if self.db and hasattr(self.db, "add_fact"):
                safe_call(self.db.add_fact, meta["key"], meta["value"])
            return "Saved."
        if intent == "learn":
            log.debug("[CORE-CMD] Intercepted: learn")
            if self.db and hasattr(self.db, "queue_learning"):
                safe_call(self.db.queue_learning, meta.get("topic"))
            return "Queued for autonomous research."
        if intent == "toggle_llm":
            log.debug("[CORE-CMD] Intercepted: toggle-llm")
            turning_on = str(meta.get("state")).lower() in ("on", "true", "1")
            self.llm_enabled = turning_on
            # Propagate pause/resume to HFBrain for chat history preservation
            brain = getattr(self, "brain", None)
            hf = getattr(brain, "hf_brain", None) if brain else None
            if hf:
                if turning_on:
                    if hasattr(hf, "enable"):
                        hf.enable()
                else:
                    if hasattr(hf, "disable"):
                        hf.disable()
            # Sync BrainRouter mode: off→local, on→balanced (respects NIBLIT_BRAIN_MODE env)
            try:
                from modules.brain_router import get_brain_router
                _br = get_brain_router()
                if turning_on:
                    _env_mode = os.environ.get("NIBLIT_BRAIN_MODE", "balanced").lower()
                    _br.set_mode(_env_mode if _env_mode in {"balanced", "power"} else "balanced")
                else:
                    _br.set_mode("local")
            except Exception as _tl_br_err:
                log.debug("[Core] toggle-llm BrainRouter mode sync failed: %s", _tl_br_err)
            if self.llm_enabled:
                return "LLM resumed (BrainRouter→balanced)"
            return "LLM paused — Qwen local brain active (BrainRouter→local)"

        # ── Brain mode / status commands ──────────────────────────────────────
        if ltext.startswith("brain mode ") or ltext.startswith("brain-mode "):
            _mode_arg = text.split(None, 2)[-1].strip().lower()
            try:
                from modules.brain_router import get_brain_router
                _br2 = get_brain_router()
                _br2.set_mode(_mode_arg)
                return f"🧠 BrainRouter mode set to: {_mode_arg}"
            except ValueError as _bm_err:
                return f"Invalid mode: {_bm_err}"
            except Exception as _bm_err2:
                return f"BrainRouter unavailable: {_bm_err2}"

        if ltext in ("brain status", "brain-status"):
            try:
                from modules.brain_router import get_brain_router
                _br3 = get_brain_router()
                _lb3 = getattr(self, "local_brain", None)
                _lb_status = _lb3.status() if _lb3 else {"loaded": False}
                lines = [
                    "🧠 Hybrid Brain Architecture Status",
                    f"  BrainRouter mode : {_br3.mode}",
                    f"  Local Brain      : {'✅ loaded' if _lb_status.get('loaded') else '⏳ pending (lazy)'}",
                    f"  Local model      : {_lb_status.get('model_name', '?')}",
                    f"  Cloud brain      : {'✅ available' if _br3.cloud_brain else '❌ unavailable'}",
                    f"  Routing stats    : {json.dumps(_br3.stats().get('routing_counts', {}))}",
                ]
                return "\n".join(lines)
            except Exception as _bs_err:
                return f"Brain status unavailable: {_bs_err}"

        if intent == "ideas":
            log.debug("[CORE-CMD] Intercepted: ideas")
            topic = meta.get("topic", "")
            return f"Ideas for {topic}: Prototype -> Test -> Evolve"

        # ============================
        # LAYER 9: INTERNET COMMANDS (uses internet directly, NOT LLM)
        # ============================
        if ltext.startswith("summary ") and self.internet:
            log.debug("[INTERNET-CMD] Intercepted: summary")
            return self._cmd_summary(text)

        if ltext.startswith("search ") and self.internet:
            log.debug("[INTERNET-CMD] Intercepted: search")
            return self._cmd_search(text)

        # ============================
        # LAYER 10: SHUTDOWN
        # ============================
        if intent == "shutdown":
            log.debug("[CORE-CMD] Intercepted: shutdown")
            threading.Thread(target=self.shutdown, daemon=True).start()
            return "Shutdown scheduled."

        # Check personality for natural questions
        if self.personality and hasattr(self.personality, 'handle_natural_question'):
            try:
                personality_response = self.personality.handle_natural_question(text)
                if personality_response:
                    return personality_response
            except Exception:
                pass

        # ============================
        # LAYER 11: ROUTER FALLBACK
        # ============================
        log.debug("[ROUTER] Fallback routing (no direct match)")
        if self.router and not self._routing:
            try:
                self._routing = True
                r = self.router.process(text)
                if r and r.strip() != text:
                    self._trigger_learning(text, r)
                    return r
            except Exception as e:
                log.warning(f"Router failed: {e}")
            finally:
                self._routing = False

        # ============================
        # LAYER 12: GENERAL CONVERSATION — routed through SDAL gate
        # ============================
        # All general chat passes through the DecisionEngine (competitive SDAL).
        # All five advisors run independently; the highest effective_score wins.
        # After the decision, EvaluationEngine.score_outcome() scores the
        # response, updates adaptive advisor weights, and emits
        # response.complete so ALE can trigger the next learning cycle.
        # When the DecisionEngine is unavailable we fall back to brain.think().
        # ============================
        log.debug("[SDAL] General chat — routing through competitive DecisionEngine")

        response = None
        _sdal_result = None

        if self.decision_engine is not None:
            try:
                # Build the LLM callable from brain_router (preferred) or brain.think.
                _llm_fn = None
                _br = getattr(self, "brain_router", None)
                if _br is not None and callable(getattr(_br, "route", None)):
                    _llm_fn = _br.route
                elif self.brain is not None and callable(getattr(self.brain, "think", None)):
                    _llm_fn = self.brain.think

                # Update shared state context before calling advisors.
                _state = getattr(self, "niblit_state", None)
                if _state is not None and hasattr(_state, "update_context"):
                    _state.update_context(user_input=text, last_topic=text[:80])

                _sdal_result = self.decision_engine.decide(
                    state=_state,
                    user_input=text,
                    llm_fn=_llm_fn,
                )
                response = _sdal_result.action or None
                log.debug(
                    "[SDAL] Winner: advisor=%s eff=%.3f conf=%.2f",
                    _sdal_result.chosen_advisor,
                    next(
                        (s.effective_score for s in _sdal_result.signals
                         if s.name == _sdal_result.chosen_advisor),
                        0.0,
                    ),
                    _sdal_result.confidence,
                )
            except Exception as _sdal_err:
                log.debug("[SDAL] DecisionEngine.decide failed, falling back: %s", _sdal_err)

        # Fallback: call brain.think directly if SDAL produced nothing.
        if not response and self.brain:
            try:
                response = safe_call(self.brain.think, text)
            except Exception as e:
                log.debug("Brain.think fallback failed: %s", e)

        if not response:
            response = f"I hear you: {text}"

        # ── Evaluation feedback loop ──────────────────────────────────────────
        # Score the response, update adaptive weights, persist to identity.
        if self.evaluation_engine is not None:
            try:
                self.evaluation_engine.score_outcome(
                    user_input=text,
                    response=response,
                    decision_result=_sdal_result,
                )
                # Sync updated identity profile (including decision_policy)
                # back into shared NiblitState so DecisionEngine reads it
                # on the next call.
                if self.cognitive_identity is not None and self.niblit_state is not None:
                    _ci_profile = self.cognitive_identity.get_profile()
                    self.niblit_state.update_identity(
                        decision_style=_ci_profile.decision_style,
                        risk_tolerance=_ci_profile.risk_tolerance,
                        response_bias=dict(_ci_profile.response_bias),
                        decision_policy=dict(_ci_profile.decision_policy),
                        total_decisions=_ci_profile.total_decisions,
                    )
            except Exception as _eval_err:
                log.debug("[SDAL] EvaluationEngine.score_outcome failed: %s", _eval_err)

        # ── PolicyOptimizer episode recording ─────────────────────────────────
        # Record the full (context, advisor, confidences, reward) tuple so the
        # PolicyOptimizer can learn from longitudinal trajectories.
        if self.policy_optimizer is not None and _sdal_result is not None:
            try:
                _ctx_type = (
                    getattr(self.niblit_state, "context", {}).get("_context_type", "chat")
                    if self.niblit_state is not None else "chat"
                )
                _advisor_confs = {
                    s.name: s.confidence for s in _sdal_result.signals
                } if _sdal_result.signals else {}
                _outcome_score = (
                    self.evaluation_engine.last_quality_score()
                    if self.evaluation_engine is not None
                    and hasattr(self.evaluation_engine, "last_quality_score")
                    else _sdal_result.confidence
                ) or _sdal_result.confidence
                self.policy_optimizer.record_episode(
                    context_type=_ctx_type,
                    advisor_chosen=_sdal_result.chosen_advisor,
                    advisor_confidences=_advisor_confs,
                    outcome_score=float(_outcome_score),
                )
            except Exception as _po_err:
                log.debug("[SDAL] PolicyOptimizer.record_episode failed: %s", _po_err)

        # ── MSG Layer closed-loop governance tick ──────────────────────────────
        # Runs every 20 _handle_impl calls to avoid overhead on every request.
        # Syncs SelfModel confidence scores with MetaEvaluator, drives ALE with
        # priority topics for weak subsystems, and feeds health scores into
        # PolicyOptimizer so routing improves based on system-health signal.
        if getattr(self, "msg_layer", None) is not None:
            try:
                _handle_calls = getattr(self.metrics, "operation_counts", {}).get("handle", 0)
                if _handle_calls % 20 == 0:
                    _msg_result = self.msg_layer.closed_loop_tick(
                        ale=getattr(self, "autonomous_engine", None)
                    )
                    # Feed subsystem health scores into PolicyOptimizer
                    if self.policy_optimizer is not None and isinstance(_msg_result, dict):
                        for _subsys, _score in _msg_result.get("scores", {}).items():
                            try:
                                self.policy_optimizer.record_episode(
                                    context_type="meta_governance",
                                    advisor_chosen=f"msg_{_subsys}",
                                    advisor_confidences={f"msg_{_subsys}": float(_score)},
                                    outcome_score=float(_score),
                                )
                            except Exception:
                                pass
            except Exception as _msg_tick_err:
                log.debug("[MSG] closed_loop_tick failed: %s", _msg_tick_err)

        self._trigger_learning(text, response)
        return response

    def help_text(self) -> str:
        """Return the complete Niblit command reference."""
        base_help = (
            "=== NIBLIT COMMAND REFERENCE ===\n\n"
            "--- CORE ---\n"
            "help                     — Show the complete Niblit command reference\n"
            "time                     — Display current date and time\n"
            "status                   — Show overall system status (modules, threads, memory)\n"
            "health                   — Run a comprehensive health check across all subsystems\n"
            "metrics                  — Show real-time performance metrics (CPU, RAM, latency)\n"
            "dump                     — Show memory dump-loop stats and last snapshot info\n"
            "\n--- MEMORY & LEARNING ---\n"
            "remember key:value       — Persist a key-value fact to canonical niblit_memory\n"
            "learn about <topic>      — Queue a topic for autonomous background research (ALE Step 1)\n"
            "ideas about <topic>      — Run SelfIdeaGenerator to produce creative implementation ideas\n"
            "dump visible             — Enable verbose niblit_memory dump output in logs\n"
            "dump invisible           — Silence niblit_memory dump output (default)\n"
            "\n--- KNOWLEDGE RECALL & ACQUIRED DATA ---\n"
            "recall <topic>           — Full-text search across KnowledgeDB facts for any stored topic\n"
            "acquired data            — Browse all facts acquired by the Autonomous Learning Engine\n"
            "acquired data <category> — Filter ALE facts by category:\n"
            "                           research / ideas / code / compiled / reflection /\n"
            "                           software_study / implementation / all\n"
            "knowledge stats          — KnowledgeDB statistics: fact counts, top tags, ALE step breakdown\n"
            "ale processes            — Describe all 28 ALE pipeline steps with data-flow and status\n"
            "\n--- AUTONOMOUS LEARNING ENGINE (ALE — 28 STEPS) ---\n"
            "autonomous-learn start              — Resume the 28-step ALE background loop\n"
            "autonomous-learn stop               — Pause ALE (all stored knowledge is retained)\n"
            "autonomous-learn status             — View cycle count, current topic, step timings, KB facts\n"
            "autonomous-learn add-topic <topic>  — Inject a new topic into the ALE rotation queue\n"
            "autonomous-learn code-status        — Show code-generation literacy loop status\n"
            "autonomous-learn serpex-research    — Trigger ALE Step 27: Serpex live web research\n"
            "autonomous-learn serpex-search <q>  — Ad-hoc Serpex web search → KnowledgeDB\n"
            "\n--- ALE PIPELINE (28 STEPS, RUNS CONTINUOUSLY) ---\n"
            "  Step  1: Research          — SelfResearcher+Internet → KnowledgeDB     (tag: ale_step1)\n"
            "  Step  2: Ideas             — SelfIdeaGenerator generates ideas          (tag: ale_step2)\n"
            "  Step  3: Implement         — SelfImplementer executes ideas             (tag: ale_step3)\n"
            "  Step  4: Reflection        — ReflectModule summarises+stores            (tag: ale_step4)\n"
            "  Step  5: SLSA              — Generates semantic knowledge artifacts     (tag: ale_step5)\n"
            "  Step  6: Learning          — SelfTeacher internalises (→ niblit_memory) (tag: ale_step6)\n"
            "  Step  7: Evolve            — EvolveEngine one self-evolution step       (tag: ale_step7)\n"
            "  Step  8: Code Research     — ResearcherEngine → CodeGenerator           (tag: ale_step8)\n"
            "  Step  9: Code Generate     — generate_from_research() → new module      (tag: ale_step9)\n"
            "  Step 10: Code Compile      — CodeCompiler validates / runs output       (tag: ale_step10)\n"
            "  Step 11: Code Reflect      — ReflectModule studies compilation output   (tag: ale_step11)\n"
            "  Step 12: SW Study          — SoftwareStudier+Internet patterns          (tag: ale_step12)\n"
            "  Step 13: Cmd Awareness     — Catalogue all registered commands          (tag: ale_step13)\n"
            "  Step 14: Cmd Execution     — Run safe diagnostic commands               (tag: ale_step14)\n"
            "  Step 15: Topic Seeding     — Derive + inject new research topics        (tag: ale_step15)\n"
            "  Step 16: Reasoning         — Build knowledge graph + infer new facts    (tag: ale_step16)\n"
            "  Step 17: Metacognition     — Self-knowledge evaluation                  (tag: ale_step17)\n"
            "  Step 18: Improvement       — 10-module self-improvement cycle           (tag: ale_step18)\n"
            "  Step 19: Collab Learning   — CollaborativeLearner peer sync             (tag: ale_step19)\n"
            "  Step 20: Parallel Research — ParallelLearner multi-topic batch          (tag: ale_step20)\n"
            "  Step 21: Binary Study      — BinaryTools binary/hex domain seeding      (tag: ale_step21)\n"
            "  Step 22: Build Scan        — BuildScanner self-source summarisation     (tag: ale_step22)\n"
            "  Step 23: Metrics           — MetricsObservability performance snapshot  (tag: ale_step23)\n"
            "  Step 24: GitHub Push       — GitHubSync push evolved files              (tag: ale_step24)\n"
            "  Step 25: Infer Topics      — Infer new topics from recent KB facts      (tag: ale_step25)\n"
            "  Step 26: GitHub Discovery  — GitHubCodeSearch discover patterns         (tag: ale_step26)\n"
            "  Step 27: Serpex Research   — niblit_agents.ResearchAgent live web fetch (tag: ale_step27)\n"
            "  Step 28: Searchcode Disc.  — SearchcodeSearch discover open-source code (tag: ale_step28)\n"
            "  All output persisted in KnowledgeDB.  Browse: 'recall <topic>'\n"
            "\n--- AUTO RESEARCH ---\n"
            "auto-research start      — Start SelfResearcher continuous research + ALE\n"
            "auto-research stop       — Stop SelfResearcher auto-research loop and pause ALE\n"
            "auto-research status     — Show auto-research enabled/disabled state and last topic\n"
            "auto-research pause      — Temporarily pause without clearing the topic queue\n"
            "auto-research resume     — Resume a paused auto-research session\n"
            "\n--- 10 SELF-IMPROVEMENTS (CONTINUOUS VIA ALE STEP 18) ---\n"
            "show improvements        — List all 10 self-improvement modules and their states\n"
            "run improvement-cycle    — Manually trigger one full improvement cycle\n"
            "improvement-status       — Show last run time, success rate, and output per improvement\n"
            "\n--- INTERNET & RESEARCH ---\n"
            "search <query>           — Live internet search via SerpEx → DuckDuckGo fallback\n"
            "summary <query>          — Fetch a concise web summary and store in KnowledgeDB\n"
            "self-research <topic>    — SelfResearcher: Serpex (1) → Searchcode (2) → Engine (3) → Internet (4)\n"
            "research code <lang>     — Research a language/framework → feed CodeGenerator\n"
            "\n--- SELF-TEACHER & LEARNER ---\n"
            "self-teach <topic>       — SelfTeacher: research → store in niblit_memory → feed learner → reflect\n"
            "learn about <topic>      — Queue topic; ALE calls SelfTeacher in Step 6\n"
            "\n--- BRAIN / SELF-IMPLEMENTATION ---\n"
            "self-idea <prompt>       — Generate idea via SelfIdeaGenerator and auto-implement it\n"
            "self-implement [plan]    — Enqueue implementation plan directly to SelfImplementer\n"
            "idea-implement [prompt]  — Full pipeline: generate idea → implement → compile → store\n"
            "reflect [text]           — Run ReflectModule on text and store reflection in KnowledgeDB\n"
            "auto-reflect             — Auto-reflect on recent interactions and store insights\n"
            "self-heal                — Run SelfHealer to detect and repair common runtime issues\n"
            "\n--- EVOLUTION ENGINE ---\n"
            "evolve                   — Run one EvolveEngine step (research → code → teach → reflect)\n"
            "evolve start             — Start the EvolveEngine continuous background loop\n"
            "evolve stop              — Stop background evolution (current cycle completes first)\n"
            "evolve status            — Show evolution loop state, last step, and improvements made\n"
            "evolve history           — List recent evolution steps with direction and outcome\n"
            "\n--- CODE GENERATION & COMPILATION ---\n"
            "generate code <lang> [template] [key=val]  — Generate a complete code module\n"
            "run code <lang> <code>          — Execute inline code and return stdout / errors\n"
            "validate <lang> <code>          — Validate syntax without executing\n"
            "execute file <path>             — Execute a script file and capture output\n"
            "code templates [lang]           — List all available templates (filtered by language)\n"
            "study language <lang>           — Fetch best practices and idioms for a language\n"
            "available languages             — List all CodeGenerator-supported languages\n"
            "\n--- FILE MANAGER ---\n"
            "read file <path>            — Read and display a file from the filesystem\n"
            "write file <path> <content> — Write content to a file (creates if absent)\n"
            "list files [dir]            — List directory contents (defaults to cwd)\n"
            "file environment            — Show filesystem environment info (paths, disk, OS)\n"
            "\n--- SOFTWARE STUDY ---\n"
            "study software <cat>     — Deep-study a software category and store patterns in KnowledgeDB\n"
            "software categories      — List all available SoftwareStudier categories\n"
            "analyze architecture <n> — Analyse a named architecture pattern and store insights\n"
            "design software <desc>   — Generate a software design document and persist it\n"
            "what have i studied      — Show all software categories studied this session\n"
            "\n--- STRUCTURAL SELF-AWARENESS (INTROSPECTION) ---\n"
            "my structure             — Full structural inventory: modules, adapters, engines, memory\n"
            "my threads               — List every active thread with name, state, and daemon flag\n"
            "my loops                 — Show all background loops with interval and running state\n"
            "my modules               — List loaded Python modules and their wiring status\n"
            "my commands              — Enumerate every registered command with handler and priority\n"
            "dashboard                — Full runtime dashboard: threads, loops, memory, ALE, modules\n"
            "operational flow         — Explain how routing, background loops, and memory connect\n"
            "resource usage           — Show RAM usage, CPU percent, and process uptime\n"
            "\n--- SLSA ENGINE ---\n"
            "slsa-status              — Show SLSA engine running state and last artifact built\n"
            "start_slsa [topics]      — Start SLSA knowledge-artifact generation\n"
            "stop_slsa                — Stop the SLSA background loop\n"
            "restart_slsa [topics]    — Restart SLSA with an updated topic list\n"
            "\n--- LIVE UPDATE ---\n"
            "reload <module.name>     — Hot-reload a single Python module without restarting\n"
            "upgrade                  — Detect and hot-reload all changed modules in one pass\n"
            "update-history           — Show history of hot-reloaded modules with timestamps\n"
            "\n--- SETTINGS ---\n"
            "toggle-llm on            — Enable cloud brain (HF/Anthropic); BrainRouter→balanced\n"
            "toggle-llm off           — Disable cloud brain; Qwen local brain becomes primary\n"
            "brain status             — Show Hybrid Brain Architecture status (local/cloud/router)\n"
            "brain mode <mode>        — Set BrainRouter mode: local | balanced | power | offline\n"
            "shutdown                 — Save state, stop all threads, and exit gracefully\n"
            "\n--- DIAGNOSTICS ---\n"
            "run-diagnostics          — Execute the full Niblit diagnostic suite across all subsystems\n"
            "run-live-test            — Run the interactive live command tester (smoke-tests all routes)\n"
            "loop-errors              — Display all errors captured by the LoopTracer since startup"
        )

        if self.orchestrator_available:
            orchestrator_help = (
                "\n\n--- ORCHESTRATOR ---\n"
                "orchestrate audit       — Run a full repository audit (imports, wiring, missing symbols)\n"
                "orchestrate self-heal   — Orchestrate automated self-healing across detected issues\n"
                "orchestrate fix-guide   — Generate a structured fix guide for all outstanding issues\n"
                "orchestrate verify      — Verify all imports and inter-module dependencies\n"
                "orchestrate pipeline    — Run the complete full-upgrade pipeline end-to-end\n"
                "hf-task <prompt>        — Execute a HuggingFace task with the given prompt"
            )
            return base_help + orchestrator_help

        return base_help


    def get_loop_errors(self) -> List[Dict]:
        """Return all loop errors captured by the LoopTracer since startup."""
        return loop_tracer.get_errors()

    def loop_tracer_summary(self) -> str:
        """Return a human-readable summary of all loop errors."""
        return loop_tracer.summary()

    # ── Fused Memory API ─────────────────────────────────────────────────────

    def store_task_result(
        self,
        task_id: str,
        result: dict,
        vector: Optional[List[float]] = None,
    ) -> None:
        """Persist a task result via the fused memory backend.

        Writes the structured *result* dict to SQLite and, when *vector* is
        provided, also upserts the embedding into Qdrant/FAISS so the task
        can be retrieved by semantic similarity later.

        Args:
            task_id: Unique task identifier.
            result:  Arbitrary result dict.
            vector:  Optional pre-computed float embedding.
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                fused.insert_record(task_id, result)
                if vector:
                    fused.insert_vector(task_id, vector, payload=result)
                return
            except Exception as exc:
                log.debug("[NiblitCore] fused store_task_result failed: %s", exc)
        # Fallback: store in NiblitMemory learning log
        if hasattr(self.memory, "store_learning"):
            self.memory.store_learning({"task_id": task_id, **result})

    def retrieve_task_result(self, task_id: str) -> dict:
        """Load a previously stored task result.

        Args:
            task_id: Unique task identifier.

        Returns:
            Result dict, or empty dict when not found.
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                rec = fused.get_record(task_id)
                if rec is not None:
                    return rec
            except Exception as exc:
                log.debug("[NiblitCore] fused retrieve_task_result failed: %s", exc)
        return {}

    def search_related_tasks(
        self,
        embedding: List[float],
        top_k: int = 5,
    ) -> List[dict]:
        """Find task results semantically similar to *embedding*.

        Uses the fused Qdrant/FAISS vector search when available, returning
        at most *top_k* results.

        Args:
            embedding: Query float vector.
            top_k:     Maximum results.

        Returns:
            List of result dicts.
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                return fused.query_vector(embedding, top_k=top_k)
            except Exception as exc:
                log.debug("[NiblitCore] fused search_related_tasks failed: %s", exc)
        return []

    def list_all_tasks(self) -> List[dict]:
        """Return all stored task results from the fused backend.

        Returns:
            List of ``{"record_id": str, "data": dict, "created_at": str}`` dicts.
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                return fused.list_records()
            except Exception as exc:
                log.debug("[NiblitCore] fused list_all_tasks failed: %s", exc)
        return []

    def fortress_tick(self) -> Dict[str, Any]:
        """
        Execute one complete FortressCycle via the CognitiveGraphKernel.

        Initialises the kernel on first call if not already done.
        Returns the cycle summary dict.
        """
        if self.cognitive_graph_kernel is None:
            try:
                from modules.niblit_cognitive_graph_kernel import get_cognitive_graph_kernel
                self.cognitive_graph_kernel = get_cognitive_graph_kernel(
                    membrane=getattr(self, "cyber_membrane", None),
                    knowledge_db=getattr(self, "db", None),
                )
            except Exception as _exc:
                return {"error": str(_exc), "success": False}
        try:
            return self.cognitive_graph_kernel.fortress_cycle()
        except AttributeError:
            # Older kernel build without fortress_cycle — fall back to plain tick
            n = self.cognitive_graph_kernel.tick()
            return {"success": True, "events_processed": n}

    def shutdown(self, timeout_seconds: Optional[float] = None):
        """Gracefully shutdown NiblitCore and all services."""
        # pylint: disable=too-many-branches
        timeout = timeout_seconds or self.config.shutdown_timeout_seconds
        log.info("✅ Shutdown initiated")
        self.running = False
        self._shutdown_event.set()

        # Release Termux CPU wake-lock so Android can enter normal power-saving
        # mode after Niblit exits.  No-op on non-Termux platforms.
        if self.wakelock is not None:
            try:
                self.wakelock.release()
            except Exception as e:
                log.debug(f"Wake-lock release failed: {e}")

        # Stop autonomous engine first
        if self.autonomous_engine and self.autonomous_engine.running:
            try:
                self.autonomous_engine.stop()
            except Exception as e:
                log.error(f"Autonomous engine shutdown failed: {e}")

        # Stop SyncEngine background loop
        if self.sync_engine is not None:
            try:
                self.sync_engine.stop()
                log.info("[SHUTDOWN] sync_engine stopped")
            except Exception as e:
                log.debug(f"[SHUTDOWN] sync_engine stop failed: {e}")

        # Stop SLSA engine
        if self.slsa_engine:
            try:
                self._stop_slsa_engine()
            except Exception as e:
                log.error(f"SLSA engine shutdown failed: {e}")

        # Stop all background threads with timeout
        total_threads = len(self._background_threads)
        if total_threads > 0:
            timeout_per_thread = timeout / total_threads
            for thread in self._background_threads:
                try:
                    thread.join(timeout=timeout_per_thread)
                    if thread.is_alive():
                        log.warning(f"Thread {thread.name} did not shutdown in time")
                except Exception as e:
                    log.error(f"Error joining thread {thread.name}: {e}")

        # Stop async event loop
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)

        # Shutdown services in reverse order
        services = [
            ("tasks", self.tasks),
            ("lifecycle", self.lifecycle),
            ("router", self.router),
            ("network", self.network),
            ("internet", self.internet),
            ("db", self.db),
        ]

        for name, service in services:
            if service:
                try:
                    if hasattr(service, "shutdown"):
                        service.shutdown()
                    log.info(f"[SHUTDOWN] {name} shut down")
                except Exception as e:
                    log.error(f"[SHUTDOWN] {name} failed: {e}")

        time.sleep(0.5)
        log.info("✅ Shutdown complete")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    core = NiblitCore()
    print("✨ Niblit Ready (All Systems: Production + Self-Improvement + Autonomous Learning)")
    print("Type 'help' for available commands or 'shutdown' to exit.\n")
    try:
        while core.running:
            _cmd_input = input("Niblit > ").strip()
            if _cmd_input:
                print(core.handle(_cmd_input))
    except KeyboardInterrupt:
        print("\nShutting down...")
        core.shutdown()
