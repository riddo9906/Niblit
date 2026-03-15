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

# ============================================================
# STDLIB IMPORTS
# ============================================================
import os
import sys
import time
import asyncio
import threading
import logging
import inspect
import importlib.util
import hashlib
import json
import uuid
import contextvars
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from functools import lru_cache
from enum import Enum
from abc import ABC, abstractmethod

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
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)
log = logging.getLogger("NiblitCore")

# Context variable for correlation ID
correlation_id_var = contextvars.ContextVar('correlation_id', default=None)

# ============================================================
# IMPROVEMENT IMPORTS (from modules/)
# ============================================================
try:
    from modules.command_registry import CommandRegistry
except Exception as e:
    log.debug(f"CommandRegistry import failed: {e}")
    CommandRegistry = None

try:
    from modules.structured_logging import StructuredLogger, RequestContext
except Exception as e:
    log.debug(f"StructuredLogger import failed: {e}")
    StructuredLogger = None

try:
    from modules.async_first import AsyncTaskCoordinator, AsyncTask
except Exception as e:
    log.debug(f"AsyncTaskCoordinator import failed: {e}")
    AsyncTaskCoordinator = None

try:
    from modules.event_sourcing import EventStore, Event, EventType
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
    from modules.plugin_architecture import PluginManager, PluginInterface
except Exception as e:
    log.debug(f"PluginManager import failed: {e}")
    PluginManager = None

try:
    from modules.monitoring_alerting import AlertManager, Alert, AlertSeverity
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
    from modules.termux_wakelock import TermuxWakeLock
except Exception as e:
    log.debug(f"TermuxWakeLock import failed: {e}")
    TermuxWakeLock = None

# ============================================================
# GLOBAL FLAGS & COMMAND LIST
# ============================================================
DEBUG_MODE = True
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
        return cls(
            memory_path=Path(os.getenv("NIBLIT_MEMORY_PATH", "")),
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
    operation_times: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
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
        times = self.operation_times.get(name, [])
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
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key not in self.cache:
            return None
        if time.time() - self.timestamps[key] > self.ttl:
            del self.cache[key]
            del self.timestamps[key]
            return None
        return self.cache[key]
    
    def set(self, key: str, value: Any):
        """Set cached value with timestamp."""
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
        expired_keys = [
            k for k in self.timestamps 
            if current_time - self.timestamps[k] > self.ttl
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

def safe_call(fn: Callable, *a, **kw) -> Optional[Any]:
    """Call fn(*a, **kw) safely, logging and returning None on failure."""
    try:
        return fn(*a, **kw)
    except Exception as e:
        log.debug(f"safe_call failed for {fn}: {e}")
        return None


def parse_intent(text: str) -> Tuple[str, Dict[str, str]]:
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
        return "bad_remember", {}
    if t.startswith("learn about "):
        topic = text[len("learn about "):].strip()
        return "learn", {"topic": topic}
    if t.startswith("learn "):
        topic = text[len("learn "):].strip()
        return "learn", {"topic": topic}
    if t.startswith("ideas about "):
        topic = text[len("ideas about "):].strip()
        return "ideas", {"topic": topic}
    if t.startswith("ideas "):
        topic = text[len("ideas "):].strip()
        return "ideas", {"topic": topic}
    if t in ("toggle-llm on", "llm on"):
        return "toggle_llm", {"state": "on"}
    if t in ("toggle-llm off", "llm off"):
        return "toggle_llm", {"state": "off"}
    if t in ("shutdown", "exit", "quit"):
        return "shutdown", {}
    return "chat", {}


class Stub:
    """Placeholder for optional modules that are unavailable."""
    def __init__(self, *a, **k):
        pass
    def __getattr__(self, name):
        return lambda *a, **k: None


class _FallbackDB:
    """Minimal no-op stub used when KnowledgeDB is unavailable."""
    def __getattr__(self, name):
        return lambda *a, **kw: None


def safe_import(name: str, default=None):
    """Import a class from the modules/ package, returning default on failure."""
    try:
        mod = __import__(f"modules.{name}", fromlist=[name])
        cls = "".join(x.capitalize() for x in name.split("_"))
        return getattr(mod, cls, default)
    except Exception as e:
        log.debug(f"Module {name} not available: {e}")
        return default or Stub


# ============================================================
# SAFE IMPORTS
# ============================================================

try:
    from modules.knowledge_db import KnowledgeDB
except Exception as _e:
    log.debug(f"KnowledgeDB failed to import: {_e}")
    KnowledgeDB = None

try:
    from modules.db import LocalDB
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
    from modules import internet_manager
except Exception as _e:
    log.debug(f"internet_manager failed to import: {_e}")
    internet_manager = None

try:
    from collector_full import Collector
except Exception as _e:
    log.debug(f"Collector failed to import: {_e}")
    Collector = None

try:
    from trainer_full import Trainer
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
    from niblit_io import NiblitIO
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

try:
    from modules.internet_manager import InternetManager
except Exception as _e:
    log.debug(f"InternetManager not available: {_e}")
    InternetManager = None

slsa_manager = None
try:
    from modules.slsa_manager import slsa_manager as sm
    slsa_manager = sm
    log.debug("slsa_manager imported from modules.slsa_manager")
except Exception as _e:
    log.debug(f"slsa_manager not available: {_e}")

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
        self._errors: List[Dict] = []

    # ----------------------------------------------------------
    @staticmethod
    def _parse_frames(tb_str: str) -> List[Dict]:
        import re
        frames = []
        pattern = re.compile(r'File "([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)')
        lines = tb_str.splitlines()
        for i, line in enumerate(lines):
            m = pattern.search(line)
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
        import traceback as _tb
        tb_str = _tb.format_exc()
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

    def __init__(self, config: Optional[NiblitConfig] = None, memory_path: Optional[str] = None):
        """Initialize NiblitCore with optional config."""
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
        
        # SLSA state
        self.slsa_engine = None
        self.slsa_thread = None

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

        # NEW: Live Updater + Structural Awareness
        self.live_updater: Optional[LiveUpdater] = None
        self.structural_awareness: Optional[StructuralAwareness] = None

        # NEW: Code capabilities + enhanced filesystem + software studier
        self.code_generator: Optional[CodeGenerator] = None
        self.code_compiler: Optional[CodeCompiler] = None
        self.file_manager: Optional[FileManager] = None
        self.software_studier: Optional[SoftwareStudier] = None
        self.evolve_engine: Optional[EvolveEngine] = None

        # NEW: SelfIdeaImplementation (research + implement + SLSA + memory)
        self.idea_implementation = None
        
        log.info("✨ Booting Niblit (Production Enhanced + Self-Improving + Autonomous Learning)...")
        
        try:
            if self.config.enable_improvements:
                self._init_improvements()
            
            self._initialize_core()
            self._initialize_modules()
            self._start_background_services()
            
            if self.startup_report.is_healthy():
                log.info("✅ NIBLIT READY (All Systems Go)")
            else:
                log.warning(f"⚠️ Degraded startup: {self.startup_report.summary()}")
        except Exception as e:
            log.error(f"Fatal initialization error: {e}", exc_info=True)
            raise

    # ============================
    # IMPROVEMENT INITIALIZATION
    # ============================

    def _init_improvements(self):
        """Initialize all production improvements."""
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

    def _register_commands(self):
        """Register commands with CommandRegistry."""
        if not self.command_registry:
            return
        
        # Core commands (no LLM)
        self.command_registry.register(
            "help", self._cmd_help, "Show available commands", "core", priority=100
        )
        self.command_registry.register(
            "status", self._cmd_status, "Show system status", "core", priority=100
        )
        self.command_registry.register(
            "health", self._cmd_health, "System health check", "core", priority=100
        )
        self.command_registry.register(
            "metrics", self._cmd_metrics, "Performance metrics", "core", priority=100
        )
        self.command_registry.register(
            "time", self._cmd_time, "Show current time", "core", priority=100
        )
        
        # Autonomous Learning Commands
        self.command_registry.register(
            "autonomous-learn start", self._cmd_autonomous_start, "Start autonomous learning", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn stop", self._cmd_autonomous_stop, "Stop autonomous learning", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn status", self._cmd_autonomous_status, "View autonomous status", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn add-topic", self._cmd_autonomous_add_topic, "Add research topic", "autonomous", priority=98
        )
        self.command_registry.register(
            "autonomous-learn code-status", self._cmd_autonomous_code_status,
            "View code literacy status", "autonomous", priority=98
        )

        # Knowledge recall & acquired data commands
        self.command_registry.register(
            "recall", self._cmd_recall, "Recall acquired data from KnowledgeDB", "knowledge", priority=95
        )
        self.command_registry.register(
            "acquired data", self._cmd_acquired_data, "Browse acquired data by category", "knowledge", priority=95
        )
        self.command_registry.register(
            "knowledge stats", self._cmd_knowledge_stats, "KnowledgeDB statistics and summary", "knowledge", priority=95
        )
        self.command_registry.register(
            "ale processes", self._cmd_ale_process_awareness, "ALE process awareness", "knowledge", priority=95
        )
        
        # SLSA commands
        self.command_registry.register(
            "slsa-status", self._cmd_slsa_status, "SLSA status", "slsa", priority=90
        )
        self.command_registry.register(
            "start_slsa", self._cmd_slsa_start, "Start SLSA", "slsa", priority=90
        )
        self.command_registry.register(
            "stop_slsa", self._cmd_slsa_stop, "Stop SLSA", "slsa", priority=90
        )
        self.command_registry.register(
            "restart_slsa", self._cmd_slsa_restart, "Restart SLSA", "slsa", priority=90
        )
        
        # Brain commands (use internet, NOT LLM)
        self.command_registry.register(
            "self-research", self._cmd_self_research, "Research topic", "brain", priority=85
        )
        self.command_registry.register(
            "self-idea", self._cmd_self_idea, "Generate ideas", "brain", priority=85
        )
        self.command_registry.register(
            "reflect", self._cmd_reflect, "Reflect on topic", "brain", priority=85
        )
        self.command_registry.register(
            "self-implement", self._cmd_self_implement, "Implement concept", "brain", priority=85
        )
        self.command_registry.register(
            "self-teach", self._cmd_self_teach, "Teach a topic", "brain", priority=85
        )
        self.command_registry.register(
            "idea-implement", self._cmd_idea_implement, "Generate and implement idea", "brain", priority=85
        )
        
        # Internet commands
        self.command_registry.register(
            "search", self._cmd_search, "Search internet", "internet", priority=80
        )
        self.command_registry.register(
            "summary", self._cmd_summary, "Get summary", "internet", priority=80
        )
        
        # Orchestrator commands
        if ORCHESTRATOR_AVAILABLE:
            self.command_registry.register(
                "orchestrate audit", self._run_audit, "Run audit", "orchestrator", priority=70
            )
            self.command_registry.register(
                "orchestrate pipeline", self._run_orchestration_pipeline, 
                "Run pipeline", "orchestrator", priority=70
            )

        # Diagnostic / tester commands
        self.command_registry.register(
            "run-diagnostics", self._cmd_run_diagnostics,
            "Run niblit diagnostic suite", "diagnostics", priority=65
        )
        self.command_registry.register(
            "run-live-test", self._cmd_run_live_test,
            "Run live command tester", "diagnostics", priority=65
        )

        # Structural awareness commands — short-form aliases
        self.command_registry.register(
            "sa-structure", self._cmd_sa_structure,
            "Full component inventory", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-threads", self._cmd_sa_threads,
            "All active Python threads", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-loops", self._cmd_sa_loops,
            "Background loop status", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-modules", self._cmd_sa_modules,
            "Loaded Niblit modules", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-commands", self._cmd_sa_commands,
            "All registered commands", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-dashboard", self._cmd_sa_dashboard,
            "Full runtime dashboard", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-flow", self._cmd_sa_flow,
            "Operational flow description", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-resources", self._cmd_sa_resources,
            "RAM, CPU, uptime", "structural_awareness", priority=75
        )
        self.command_registry.register(
            "sa-awareness", self._cmd_sa_awareness,
            "All structural awareness in one view", "structural_awareness", priority=75
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

    def _cmd_autonomous_start(self, text: str) -> str:
        """Start autonomous learning engine."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        
        result = self.autonomous_engine.start()
        return "🚀 [AUTONOMOUS] Learning started ✅" if result else "ℹ️ [AUTONOMOUS] Already running"

    def _cmd_autonomous_stop(self, text: str) -> str:
        """Stop autonomous learning engine."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        
        result = self.autonomous_engine.stop()
        return "⏹️ [AUTONOMOUS] Learning stopped ✅" if result else "ℹ️ [AUTONOMOUS] Not running"

    def _cmd_autonomous_status(self, text: str) -> str:
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

📚 Topics: {stats.get('research_topics', 0)} | Code Topics: {stats.get('code_research_topics', 0)} | SW Categories: {stats.get('software_study_categories', 0)}
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

    def _cmd_autonomous_code_status(self, text: str) -> str:
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
            f"\n🔌 Module Availability:",
            f"  internet         : {'✅' if mods.get('internet') else '❌'}",
            f"  code_generator   : {'✅' if mods.get('code_generator') else '❌'}",
            f"  code_compiler    : {'✅' if mods.get('code_compiler') else '❌'}",
            f"  software_studier : {'✅' if mods.get('software_studier') else '❌'}",
            f"  researcher       : {'✅' if mods.get('researcher') else '❌'}",
            f"\n📋 Pending:",
            f"  Compilations     : {stats.get('pending_compilations', 0)}",
            f"  Reflections      : {stats.get('pending_reflections', 0)}",
            f"\n⚙️ Loop runs during idle time. Use 'autonomous-learn start' to enable.",
        ]
        return "\n".join(lines)

    def _cmd_autonomous_add_topic(self, text: str) -> str:
        """Add research topic to autonomous engine."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        
        topic = text[len("autonomous-learn add-topic"):].strip()
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

    def _cmd_knowledge_stats(self, text: str) -> str:
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

    def _cmd_ale_process_awareness(self, text: str) -> str:
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
            f"  Step 6 — Learning       : SelfTeacher internalizes  [see KB: learning]",
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

    def _cmd_show_improvements(self, text: str) -> str:
        """Show all 10 self-improvement modules."""
        if not self.improvements:
            return "[❌ Self-improvements not available]"
        
        status = self.improvements.get_improvement_status()
        result = "🚀 **10 SELF-IMPROVEMENT MODULES:**\n\n"
        
        for i, (name, desc) in enumerate(status.items(), 1):
            result += f"{i}. {desc}\n"
        
        return result

    def _cmd_run_improvement_cycle(self, text: str) -> str:
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

    def _cmd_improvement_status(self, text: str) -> str:
        """Show improvement system status."""
        if not self.improvements:
            return "[❌ Self-improvements not available]"
        
        status = self.improvements.get_improvement_status()
        result = "📊 **IMPROVEMENT SYSTEM STATUS:**\n\n"
        
        active = sum(1 for s in status.values() if "✅" in str(s))
        total = len(status)
        
        result += f"Active Improvements: {active}/{total}\n\n"
        result += "Details:\n"
        for name, state in status.items():
            result += f"  {state}\n"
        
        return result

    def _cmd_show_new_commands(self, text: str = "") -> str:
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
            "\n--- REASONING & METACOGNITION ---\n"
            "self-research <topic>              — Autonomous research + KB storage\n"
            "reflect [text]                     — Reflect on topic (results stored in ale_learned)\n"
            "auto-reflect                       — Auto reflection on recent events\n"
            "\n--- EVOLUTION ---\n"
            "evolve                             — One self-evolution step\n"
            "evolve start                       — Continuous background evolution\n"
            "evolve stop                        — Stop background evolution\n"
            "evolve status                      — Evolution status\n"
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

    def _cmd_agentic_list(self, text: str = "") -> str:
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

    def _cmd_agentic_status(self, text: str = "") -> str:
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

    def _cmd_enterprise_summary(self, text: str = "") -> str:
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

    def _cmd_enterprise_health(self, text: str = "") -> str:
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

    def _cmd_enterprise_sla(self, text: str = "") -> str:
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

    def _cmd_multimodal_status(self, text: str = "") -> str:
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

    def _cmd_reasoning_build(self, text: str = "") -> str:
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

    def _cmd_reasoning_status(self, text: str = "") -> str:
        """Show reasoning engine status."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        graph_size = len(self.reasoning_engine.graph)
        chain_count = len(self.reasoning_engine.reasoning_chains)
        return (f"🧠 **REASONING ENGINE STATUS:**\n"
                f"Knowledge graph concepts: {graph_size}\n"
                f"Reasoning chains stored: {chain_count}\n"
                f"Status: {'Ready — run \"reasoning build\" to populate graph' if graph_size == 0 else 'Active'}")

    def _cmd_reasoning_chain(self, concept: str) -> str:
        """Create a reasoning chain from the given concept."""
        if not self.reasoning_engine:
            return "[❌ ReasoningEngine not available]"
        if not concept.strip():
            return "Usage: reasoning chain <concept>"
        chain = self.reasoning_engine.create_reasoning_chain(concept.strip())
        return f"🔗 **REASONING CHAIN from '{concept}':**\n{' → '.join(chain)}"

    def _cmd_reasoning_infer(self, text: str = "") -> str:
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

    # ──────────────────────────────────────
    # COLLABORATIVE SYSTEMS COMMANDS
    # ──────────────────────────────────────

    def _cmd_collab_status(self, text: str = "") -> str:
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
            import importlib, sys as _sys
            mod = _sys.modules.get(module_name)
            if mod is None:
                mod = importlib.import_module(module_name)
            importlib.reload(mod)
            return f"✅ Module '{module_name}' reloaded (direct fallback)."
        except Exception as e:
            return f"❌ Reload failed for '{module_name}': {e}"

    def _cmd_upgrade(self, text: str = "") -> str:
        """Reload all modules whose files changed on disk."""
        if self.live_updater:
            changed = self.live_updater.reload_all_changed()
            if not changed:
                return "✅ All modules are up-to-date — no changes detected on disk."
            msgs = [r["message"] for r in changed]
            return "🔄 **Self-Upgrade Complete:**\n" + "\n".join(f"  • {m}" for m in msgs)
        return "[LiveUpdater not available — restart to pick up file changes]"

    def _cmd_update_history(self, text: str = "") -> str:
        """Show recent hot-reload history."""
        if self.live_updater:
            return self.live_updater.summarize_history()
        return "[LiveUpdater not available]"

    # ──────────────────────────────────────
    # STRUCTURAL AWARENESS COMMANDS
    # ──────────────────────────────────────

    def _cmd_sa_structure(self, text: str = "") -> str:
        """Show full component inventory."""
        if self.structural_awareness:
            return self.structural_awareness.component_report(self)
        return "[StructuralAwareness not available]"

    def _cmd_sa_threads(self, text: str = "") -> str:
        """Show all active threads."""
        if self.structural_awareness:
            return self.structural_awareness.thread_report()
        import threading
        lines = [f"🧵 Active threads ({threading.active_count()}):"]
        for t in threading.enumerate():
            lines.append(f"  • {t.name} ({'alive' if t.is_alive() else 'dead'})")
        return "\n".join(lines)

    def _cmd_sa_loops(self, text: str = "") -> str:
        """Show background loop status."""
        if self.structural_awareness:
            return self.structural_awareness.loop_report(self)
        return "[StructuralAwareness not available]"

    def _cmd_sa_modules(self, text: str = "") -> str:
        """Show loaded Niblit modules."""
        if self.structural_awareness:
            return self.structural_awareness.module_report()
        return "[StructuralAwareness not available]"

    def _cmd_sa_commands(self, text: str = "") -> str:
        """Show all registered commands."""
        if self.structural_awareness:
            return self.structural_awareness.command_report(router=self.router)
        if self.router and hasattr(self.router, "help_text"):
            return self.router.help_text()
        return self.help_text()

    def _cmd_sa_dashboard(self, text: str = "") -> str:
        """Show full runtime dashboard."""
        if self.structural_awareness:
            return self.structural_awareness.runtime_dashboard(
                core=self, router=self.router
            )
        return self._cmd_status("")

    def _cmd_sa_flow(self, text: str = "") -> str:
        """Show operational flow description."""
        if self.structural_awareness:
            return self.structural_awareness.operational_flow()
        return "[StructuralAwareness not available]"

    def _cmd_sa_resources(self, text: str = "") -> str:
        """Show resource usage."""
        if self.structural_awareness:
            return self.structural_awareness.resource_report()
        return "[StructuralAwareness not available]"

    def _cmd_sa_awareness(self, text: str = "") -> str:
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

    # ──────────────────────────────────────
    # EXTENDED AUTONOMOUS LEARNING COMMANDS
    # ──────────────────────────────────────

    def _cmd_autonomous_self_learn(self, text: str) -> str:
        """Run the structural self-learn sequence immediately."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "run_self_learn_sequence"):
            return "[❌ Self-learn sequence not available in this engine version]"
        result = self.autonomous_engine.run_self_learn_sequence()
        return result or "✅ Self-learn sequence completed"

    def _cmd_autonomous_evolve_sequence(self, text: str) -> str:
        """Run the structured evolve sequence immediately."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "run_evolve_sequence"):
            return "[❌ Evolve sequence not available in this engine version]"
        result = self.autonomous_engine.run_evolve_sequence()
        return result or "✅ Evolve sequence completed"

    def _cmd_autonomous_command_awareness(self, text: str) -> str:
        """Trigger ALE Step 13: catalogue all registered commands into KnowledgeDB."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_command_awareness"):
            return "[❌ Command awareness step not available]"
        result = self.autonomous_engine._autonomous_command_awareness()
        return result or "✅ Command awareness complete"

    def _cmd_autonomous_command_exec(self, text: str) -> str:
        """Trigger ALE Step 14: execute safe diagnostic commands autonomously."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_command_execution"):
            return "[❌ Command execution step not available]"
        result = self.autonomous_engine._autonomous_command_execution()
        return result or "✅ Command execution complete"

    def _cmd_autonomous_topic_seed(self, text: str) -> str:
        """Trigger ALE Step 15: derive new topics from KB and seed to ALE + SLSA + KB queue."""
        if not self.autonomous_engine:
            return "[❌ Autonomous engine not available]"
        if not hasattr(self.autonomous_engine, "_autonomous_topic_seeding"):
            return "[❌ Topic seeding step not available]"
        result = self.autonomous_engine._autonomous_topic_seeding()
        return result or "✅ Topic seeding complete"

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
        """Run code: 'python print(\"hello\")'"""
        if not self.code_compiler:
            return "[CodeCompiler not available]"
        parts = spec.split(None, 1)
        if len(parts) < 2:
            return "Usage: run code <language> <code>"
        language, code = parts[0], parts[1]
        result = self.code_compiler.run(language, code)
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

    def _cmd_available_languages(self, text: str = "") -> str:
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
        preview = content[:1000] if len(content) > 1000 else content
        suffix = "...[truncated]" if len(content) > 1000 else ""
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

    def _cmd_file_environment(self, text: str = "") -> str:
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

    def _cmd_software_categories(self, text: str = "") -> str:
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

    def _cmd_software_studied(self, text: str = "") -> str:
        """Show what software has been studied."""
        if not self.software_studier:
            return "[SoftwareStudier not available]"
        return self.software_studier.what_ive_studied()

    # ──────────────────────────────────────
    # EVOLVE ENGINE COMMANDS
    # ──────────────────────────────────────

    def _cmd_evolve_step(self, text: str = "") -> str:
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

    def _cmd_evolve_start(self, text: str = "") -> str:
        """Start background evolution."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        self.evolve_engine.refresh_from_core()
        ok = self.evolve_engine.start_background_evolution()
        return "✅ Background evolution started." if ok else "⚠️ Evolution already running."

    def _cmd_evolve_stop(self, text: str = "") -> str:
        """Stop background evolution."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        self.evolve_engine.stop_background_evolution()
        return "✅ Background evolution stopped."

    def _cmd_evolve_status(self, text: str = "") -> str:
        """Show evolution status."""
        if not self.evolve_engine:
            return "[EvolveEngine not available]"
        status = self.evolve_engine.get_status()
        lines = [
            "🧬 **EvolveEngine Status:**",
            f"  Running    : {'✅ Yes' if status['running'] else '❌ No'}",
            f"  Iterations : {status['iteration']}",
            f"  Stats      : {status['stats']}",
            f"  Last Dir   : {status.get('last_direction', 'none')}",
            f"  Modules    :",
        ]
        for mod, avail in status.get("available_modules", {}).items():
            lines.append(f"    {'✅' if avail else '❌'} {mod}")
        return "\n".join(lines)

    def _cmd_evolve_history(self, text: str = "") -> str:
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
        return f"[research_code not available — upgrade self_researcher.py]"

    def _cmd_help(self, text: str) -> str:
        """Help command."""
        return self.help_text()

    def _cmd_status(self, text: str) -> str:
        """Status command."""
        try:
            mem_count = self._get_memory_count()
            improvements = "✅ Active" if self.improvements else "❌ Inactive"
            autonomous = "✅ Running" if (self.autonomous_engine and self.autonomous_engine.running) else "❌ Stopped"
            return f"Status: OK | Memory: {mem_count} | Improvements: {improvements} | Autonomous: {autonomous}"
        except Exception as e:
            log.error(f"Status command failed: {e}")
            return f"Status: Error - {e}"

    def _cmd_health(self, text: str) -> str:
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

    def _cmd_metrics(self, text: str) -> str:
        """Metrics command."""
        result = "Performance Metrics:\n"
        for op_name in sorted(self.metrics.operation_counts.keys()):
            stats = self.metrics.get_stats(op_name)
            if stats:
                result += f"  {op_name}: {stats['count']} calls, "
                result += f"{stats['errors']} errors, "
                result += f"avg {stats['avg_ms']:.2f}ms\n"
        return result

    def _cmd_time(self, text: str) -> str:
        """Time command."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _cmd_slsa_status(self, text: str) -> str:
        """SLSA status command."""
        return self._get_slsa_status()

    def _cmd_slsa_start(self, text: str) -> str:
        """SLSA start command."""
        rest = text[len("start_slsa"):].strip()
        topics = rest.split() if rest else None
        return self._start_slsa_engine(topics)

    def _cmd_slsa_stop(self, text: str) -> str:
        """SLSA stop command."""
        return self._stop_slsa_engine()

    def _cmd_slsa_restart(self, text: str) -> str:
        """SLSA restart command."""
        rest = text[len("restart_slsa"):].strip()
        topics = rest.split() if rest else None
        return self._restart_slsa_engine(topics)

    def _cmd_self_research(self, text: str) -> str:
        """Self-research command — uses self_researcher + internet directly, NOT LLM."""
        topic = text[len("self-research"):].strip() or "general"
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
        prompt = text[len("self-idea"):].strip() or "system improvement"
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

    def _cmd_reflect(self, text: str) -> str:
        """Reflect command — uses ReflectModule directly, NOT LLM."""
        topic = text[len("reflect"):].strip() or ""
        # Direct module path: use reflect directly
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
        plan = text[len("self-implement"):].strip() or ""
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

    def _cmd_run_diagnostics(self, text: str) -> str:
        """
        Run the full niblit diagnostic suite (run_diagnostics.py) and return
        its output as a string so it can be displayed inline during a session.
        """
        import subprocess
        import sys
        script = os.path.join(BASE_DIR, "run_diagnostics.py")
        try:
            log.info("[DIAGNOSTICS] Running run_diagnostics.py ...")
            result = subprocess.run(
                [sys.executable, script],
                capture_output=True, text=True, timeout=120,
                cwd=BASE_DIR,
            )
            output = result.stdout or ""
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr
            log.info(f"[DIAGNOSTICS] Exited with code {result.returncode}")
            return output.strip() or "[Diagnostics produced no output]"
        except subprocess.TimeoutExpired:
            return "[DIAGNOSTICS] Timed out after 120 s"
        except Exception as e:
            log.error(f"[DIAGNOSTICS] Failed: {e}")
            return f"[DIAGNOSTICS] Failed: {e}"

    def _cmd_run_live_test(self, text: str) -> str:
        """
        Run the live command tester (live_command_tester.py) and return its
        output inline so results can be inspected without leaving the REPL.
        """
        import subprocess
        import sys
        script = os.path.join(BASE_DIR, "live_command_tester.py")
        try:
            log.info("[LIVE-TEST] Running live_command_tester.py ...")
            result = subprocess.run(
                [sys.executable, script],
                capture_output=True, text=True, timeout=180,
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
        """Initialize internet manager."""
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

    def _initialize_modules(self):
        """Initialize all modules with dependency management."""
        with self.logger.context("initialize_modules"):
            # Phase 1: Foundation modules
            self._init_ai_adapters()
            
            # Phase 2: Intelligent systems
            self._init_brain_and_router()
            self._init_learning_systems()
            
            # Phase 3: System services
            self._init_system_services()
            
            # Phase 4: Optional heavy modules
            self._init_optional_services()

    def _init_ai_adapters(self):
        """Initialize AI adapter modules."""
        try:
            self.reflect = safe_call(Reflect_mod, self.db) if Reflect_mod else None
            self.self_healer = safe_call(SelfHealer_mod, self.db) if SelfHealer_mod else None
            self.llm = safe_call(LLMAdapter) if LLMAdapter else None
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
        try:
            self.researcher = safe_call(SelfResearcher, self.db, self.modules) if SelfResearcher else None
            # Alias used by structural_awareness.component_report() and live_updater
            self.self_researcher = self.researcher

            if self.researcher and self.internet:
                self.researcher.internet = self.internet
            if self.self_teacher:
                self.self_teacher.researcher = self.researcher
            
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
        except Exception as e:
            log.error(f"Brain/router init failed: {e}")
            self.startup_report.add("brain_router", "degraded", str(e))

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
                    self.self_teacher.learner = self.idea_implementation
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
        try:
            self.membrane = safe_call(Membrane) if Membrane else None
            self.healer_obj = safe_call(Healer) if Healer else None
            self.generator = safe_call(Generator) if Generator else None
            self.self_maintenance = safe_call(SelfMaintenance) if SelfMaintenance else None
            
            self.slsa_manager = slsa_manager

            # ============================
            # SLSA ENGINE (initialized at startup so component report shows it)
            # ============================
            if SLSAGenerator:
                try:
                    self.slsa_engine = SLSAGenerator(
                        interval=20,
                        topics=["car", "computer", "phone"],
                        internet=getattr(self, "internet", None),
                    )
                    log.info("✅ SLSAGenerator initialized")
                    self.startup_report.add("slsa_engine", "ready")
                except Exception as e:
                    log.debug(f"SLSAGenerator init failed: {e}")
                    self.startup_report.add("slsa_engine", "degraded", str(e))

            self.lifecycle = None
            if LifecycleEngine:
                try:
                    self.lifecycle = LifecycleEngine()
                except Exception as e:
                    log.debug(f"LifecycleEngine failed to start: {e}")
            
            if load_modules:
                try:
                    load_modules()
                except Exception as e:
                    log.debug(f"load_modules failed: {e}")
            
            # ============================
            # INITIALIZE 10 SELF-IMPROVEMENTS
            # ============================
            if self.config.enable_self_improvements:
                self._init_self_improvements()
            
            # ============================
            # INITIALIZE AUTONOMOUS LEARNING ENGINE
            # ============================
            if self.config.enable_autonomous_engine and AutonomousLearningEngine:
                try:
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
                    )
                    log.info("✅ AutonomousLearningEngine initialized")
                    self.startup_report.add("autonomous_engine", "ready")
                    # Auto-start: ALE runs in a daemon background thread so Niblit
                    # continuously learns at all times without any manual command.
                    # Use 'autonomous-learn stop' at the CLI to pause it if needed.
                    self.autonomous_engine.start()
                    log.info("🚀 AutonomousLearningEngine auto-started (continuous background learning)")
                except Exception as e:
                    log.warning(f"AutonomousLearningEngine init failed: {e}")
                    self.startup_report.add("autonomous_engine", "degraded", str(e))
            
            self.startup_report.add("optional_services", "ready")
            log.info("✅ Optional services initialized")

            # ============================
            # LIVE UPDATER
            # ============================
            if LiveUpdater:
                try:
                    self.live_updater = LiveUpdater(base_dir=str(self.config.memory_path.parent)
                                                    if hasattr(self.config, "memory_path") else None)
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
            # FILE MANAGER (enhanced)
            # ============================
            if FileManager:
                try:
                    self.file_manager = FileManager(
                        base_dir=str(self.config.memory_path.parent)
                        if hasattr(self.config, "memory_path") else None,
                        db=self.db,
                    )
                    log.info("✅ FilesystemManager (enhanced) initialized")
                    self.startup_report.add("file_manager", "ready")
                except Exception as e:
                    log.debug(f"FilesystemManager init failed: {e}")
                    self.startup_report.add("file_manager", "degraded", str(e))

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
                    )
                    # Back-wire autonomous_engine → evolve_engine once both are available
                    if self.autonomous_engine and not self.autonomous_engine.evolve_engine:
                        self.autonomous_engine.evolve_engine = self.evolve_engine
                    log.info("✅ EvolveEngine initialized")
                    self.startup_report.add("evolve_engine", "ready")
                except Exception as e:
                    log.debug(f"EvolveEngine init failed: {e}")
                    self.startup_report.add("evolve_engine", "degraded", str(e))
        except Exception as e:
            log.error(f"Optional services init failed: {e}")
            self.startup_report.add("optional_services", "degraded", str(e))

    def _init_self_improvements(self):
        """Initialize 10 self-improvement modules."""
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
                self.adaptive_learning = AdaptiveLearning()
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
                self._async_tasks.add(asyncio.create_task(task))
            
            self._start_background_loop(
                lambda: self._event_loop.run_forever(),
                "AsyncEventLoop"
            )
        except Exception as e:
            log.warning(f"Failed to start async loops: {e}")

    def _start_background_loop(self, target: Callable, name: str):
        """Start a background thread and track it."""
        try:
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
                            self.researcher.internet = self.internet
                        result = None
                        if hasattr(self.researcher, "search"):
                            result = safe_call(self.researcher.search, topic)

                        if result and self.db and hasattr(self.db, "add_fact"):
                            result_text = str(result)
                            # Store raw research result
                            try:
                                self.db.add_fact(
                                    f"auto_research:{topic}",
                                    result_text,
                                    tags=["research", "auto"]
                                )
                            except Exception:
                                pass

                            # Reflect on the research result
                            reflection_output = ""
                            reflect = getattr(self, "reflect", None)
                            if reflect and hasattr(reflect, "collect_and_summarize"):
                                try:
                                    reflection_output = str(
                                        reflect.collect_and_summarize(
                                            f"Auto-research topic: {topic}\n\n"
                                            f"Findings:\n{result_text[:600]}"
                                        ) or ""
                                    )
                                    log.info(f"[AUTO RESEARCH] Reflected on '{topic}'")
                                except Exception as _re:
                                    log.debug(f"[AUTO RESEARCH] Reflection failed: {_re}")

                            # Feed to self-teacher so the content is internalised
                            self_teacher = getattr(self, "self_teacher", None)
                            if self_teacher and hasattr(self_teacher, "teach"):
                                try:
                                    safe_call(
                                        self_teacher.teach,
                                        f"{topic}: {result_text[:300]}"
                                    )
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
        while self.running:
            try:
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

                        log.info(f"[AUTO RESEARCH] {topic}")

                        cache_key = self.research_cache.cache_key(topic)
                        cached = self.research_cache.get(cache_key)
                        result = None

                        if cached:
                            log.info(f"[AUTO RESEARCH] Cache hit for {topic}")
                            result = cached
                        else:
                            if self.internet:
                                self.researcher.internet = self.internet
                            if hasattr(self.researcher, "search"):
                                result = safe_call(self.researcher.search, topic)
                                if result:
                                    self.research_cache.set(cache_key, result)

                        if result and self.db and hasattr(self.db, "add_fact"):
                            # Store raw research result
                            result_text = str(result)
                            try:
                                self.db.add_fact(
                                    f"auto_research:{topic}",
                                    result_text,
                                    tags=["research", "auto"]
                                )
                            except Exception:
                                pass

                            # Reflect on the research result
                            reflection_output = ""
                            reflect = getattr(self, "reflect", None)
                            if reflect and hasattr(reflect, "collect_and_summarize"):
                                try:
                                    reflection_output = str(
                                        reflect.collect_and_summarize(
                                            f"Auto-research topic: {topic}\n\n"
                                            f"Findings:\n{result_text[:600]}"
                                        ) or ""
                                    )
                                    log.info(f"[AUTO RESEARCH] Reflected on '{topic}'")
                                except Exception as _re:
                                    log.debug(f"[AUTO RESEARCH] Reflection failed: {_re}")

                            # Feed to self-teacher so the content is internalised
                            self_teacher = getattr(self, "self_teacher", None)
                            if self_teacher and hasattr(self_teacher, "teach"):
                                try:
                                    safe_call(
                                        self_teacher.teach,
                                        f"{topic}: {result_text[:300]}"
                                    )
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
            self.slsa_engine = SLSAGenerator(interval=20, topics=topics or ["car", "computer", "phone"], internet=self.internet)
            self.slsa_thread = threading.Thread(target=self.slsa_engine.run, daemon=True, name="SLSA-Generator")
            self.slsa_thread.start()
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
            self.slsa_engine.stop()
            
            if self.slsa_thread:
                self.slsa_thread.join(timeout=5)
                if self.slsa_thread.is_alive():
                    log.warning("[SLSA] Engine thread did not stop within timeout")
            
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
            
            if self.slsa_thread and self.slsa_thread.is_alive():
                topics = self.slsa_engine.topics if self.slsa_engine else []
                return f"[SLSA] Generator is running with topics: {topics}"
            else:
                return "[SLSA] Generator is stopped"
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
        # Record user activity (not idle)
        if self.autonomous_engine:
            try:
                if hasattr(self.autonomous_engine, "record_user_activity"):
                    self.autonomous_engine.record_user_activity()
            except Exception as e:
                log.debug(f"Failed to record user activity: {e}")
        
        if self.learning:
            try:
                self.learning.process_interaction(user_input, response)
            except Exception as _e:
                log.debug(f"NiblitLearning.process_interaction failed: {_e}")

        if self.tasks:
            try:
                self.tasks.add_task("remember", {"input": user_input, "response": response})
            except Exception as _e:
                log.debug(f"NiblitTasks.add_task failed: {_e}")

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

    def _handle_impl(self, text: str) -> str:
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
        ltext = text.lower().strip()
        
        log.debug(f"[HANDLE] Input: '{text[:50]}...' | Normalized: '{ltext[:50]}...'")
        
        # ============================
        # LAYER 1: COMMAND REGISTRY (if enabled)
        # ============================
        if self.command_registry:
            try:
                result = self.command_registry.execute(ltext)
                if result:
                    log.debug(f"[COMMAND_REGISTRY] Command executed")
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
            elif "stop" in ltext:
                return self._cmd_autonomous_stop(text)
            elif "code-status" in ltext:
                return self._cmd_autonomous_code_status(text)
            elif "status" in ltext:
                return self._cmd_autonomous_status(text)
            elif "add-topic" in ltext:
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
            self.llm_enabled = str(meta.get("state")).lower() in ("on", "true", "1")
            return f"LLM {'enabled' if self.llm_enabled else 'disabled'}"
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
        # LAYER 12: GENERAL CONVERSATION (brain.think ONLY)
        # ============================
        log.debug("[BRAIN] General chat fallback - brain.think() only")
        response = None
        
        if self.brain:
            try:
                response = safe_call(self.brain.think, text)
            except Exception as e:
                log.debug(f"Brain.think failed: {e}")

        if not response:
            response = f"I hear you: {text}"

        self._trigger_learning(text, response)
        return response

    def help_text(self) -> str:
        """Return help text including all features."""
        base_help = (
            "=== NIBLIT HELP ===\n\n"
            "--- CORE ---\n"
            "help                     — Show this help\n"
            "time                     — Show current time\n"
            "status                   — Show system status\n"
            "health                   — Comprehensive health check\n"
            "metrics                  — Performance metrics\n"
            "dump                     — Show dump loop stats\n"
            "\n--- MEMORY & LEARNING ---\n"
            "remember key:value       — Store a fact\n"
            "learn about <topic>      — Queue for research\n"
            "ideas about <topic>      — Get creative ideas\n"
            "\n--- KNOWLEDGE RECALL & ACQUIRED DATA ---\n"
            "recall <topic>           — Search KnowledgeDB for topic (searches all stored facts)\n"
            "acquired data            — Browse all acquired facts from ALE processes\n"
            "acquired data <category> — Filter by: research, ideas, code, compiled,\n"
            "                           reflection, software_study, implementation, all\n"
            "knowledge stats          — Full KnowledgeDB summary (counts, top tags, ALE breakdown)\n"
            "ale processes            — Explain all 18 ALE steps + data storage + module status\n"
            "\n--- AUTONOMOUS LEARNING ---\n"
            "autonomous-learn start              — Resume learning after a stop (auto-starts with Niblit)\n"
            "autonomous-learn stop               — Pause background learning\n"
            "autonomous-learn status             — View full learning statistics\n"
            "autonomous-learn add-topic <topic>  — Add research topic\n"
            "autonomous-learn code-status        — View programming literacy status\n"
            "\n--- CONTINUOUS LEARNING (18 STEPS, RUNS ALL THE TIME) ---\n"
            "  ALE runs every cycle regardless of idle state:\n"
            "  Step  1: Research       — researcher+internet → KB (tag: ale_step1)\n"
            "  Step  2: Ideas          — SelfIdeaImpl generates ideas    (tag: ale_step2)\n"
            "  Step  3: Implement      — SelfImplementer executes ideas  (tag: ale_step3)\n"
            "  Step  4: Reflection     — ReflectModule summarizes+stores (tag: ale_step4)\n"
            "                            Research results stored as ale_learned after reflection\n"
            "  Step  5: SLSA           — generates knowledge artifacts   (tag: ale_step5)\n"
            "  Step  6: Learning       — SelfTeacher internalizes        (tag: ale_step6)\n"
            "  Step  7: Evolve         — EvolveEngine self-evolves       (tag: ale_step7)\n"
            "  Step  8: Code Research  — internet → CodeGenerator        (tag: ale_step8)\n"
            "  Step  9: Code Generate  — idea+implementer → code         (tag: ale_step9)\n"
            "  Step 10: Code Compile   — CodeCompiler runs it            (tag: ale_step10)\n"
            "  Step 11: Code Reflect   — ReflectModule studies output    (tag: ale_step11)\n"
            "  Step 12: SW Study       — SoftwareStudier+internet        (tag: ale_step12)\n"
            "  Step 13: Cmd Awareness  — Catalogue all commands          (tag: ale_step13)\n"
            "  Step 14: Cmd Execution  — Run safe diagnostic commands    (tag: ale_step14)\n"
            "  Step 15: Topic Seeding  — Derive + feed new topics        (tag: ale_step15)\n"
            "  Step 16: Reasoning      — Build knowledge graph+infer     (tag: ale_step16)\n"
            "  Step 17: Metacognition  — Self-knowledge evaluation       (tag: ale_step17)\n"
            "  Step 18: Improvement    — 10-module improvement cycle     (tag: ale_step18)\n"
            "  All output stored in KnowledgeDB.  Recall: 'recall <topic>'\n"
            "\n--- 10 SELF-IMPROVEMENTS (NOW CONTINUOUS VIA STEP 18) ---\n"
            "show improvements        — View all 10 improvements\n"
            "run improvement-cycle    — Manually trigger improvement cycle\n"
            "improvement-status       — View improvement status\n"
            "\n--- NEW COMMANDS ---\n"
            "new commands             — Show all recently added commands\n"
            "\n--- INTERNET & RESEARCH ---\n"
            "search <query>           — Search the internet\n"
            "summary <query>          — Get quick summary\n"
            "self-research <topic>    — Research autonomously\n"
            "research code <lang> [topic] — Research language from internet → CodeGenerator\n"
            "\n--- BRAIN / SELF-IMPROVEMENT COMMANDS ---\n"
            "self-idea <prompt>       — Generate & implement idea\n"
            "self-implement [plan]    — Enqueue plan to SelfImplementer\n"
            "self-teach <topic>       — Teach topic via SelfTeacher + research\n"
            "idea-implement [prompt]  — Generate and implement ideas\n"
            "reflect [text]           — Reflect on topic\n"
            "auto-reflect             — Auto reflection on recent events\n"
            "self-heal                — Self-healing\n"
            "\n--- EVOLUTION ENGINE ---\n"
            "evolve                   — Run one self-evolution step\n"
            "evolve start             — Start continuous background evolution\n"
            "evolve stop              — Stop background evolution\n"
            "evolve status            — Show evolution status\n"
            "evolve history           — Show recent evolution steps\n"
            "\n--- CODE GENERATION & COMPILATION ---\n"
            "generate code <lang> [template] [key=val]  — Generate code\n"
            "run code <lang> <code>          — Execute code inline\n"
            "validate <lang> <code>          — Validate syntax\n"
            "execute file <path>             — Execute a script file\n"
            "code templates [lang]           — List templates\n"
            "study language <lang>           — Best practices for language\n"
            "available languages             — Show supported languages\n"
            "\n--- FILE MANAGER ---\n"
            "read file <path>         — Read file\n"
            "write file <path> <content> — Write file\n"
            "list files [dir]         — List files\n"
            "file environment         — Filesystem info\n"
            "\n--- SOFTWARE STUDY ---\n"
            "study software <cat>     — Study a software category\n"
            "software categories      — List all categories\n"
            "analyze architecture <n> — Analyze architecture pattern\n"
            "design software <desc>   — Generate software design\n"
            "what have i studied      — Show studied this session\n"
            "\n--- STRUCTURAL SELF-AWARENESS (INTROSPECTION) ---\n"
            "my structure             — Full component inventory\n"
            "my threads               — All active threads\n"
            "my loops                 — Background loop status\n"
            "my modules               — Loaded modules\n"
            "my commands              — All registered commands\n"
            "dashboard                — Full runtime dashboard\n"
            "operational flow         — How loops/routing work\n"
            "resource usage           — RAM, CPU, uptime\n"
            "\n--- SLSA ENGINE ---\n"
            "slsa-status              — SLSA status\n"
            "start_slsa [topics]      — Start SLSA\n"
            "stop_slsa                — Stop SLSA\n"
            "restart_slsa [topics]    — Restart SLSA\n"
            "\n--- LIVE UPDATE ---\n"
            "reload <module.name>     — Hot-reload a module\n"
            "upgrade                  — Reload all changed modules\n"
            "update-history           — Show reload history\n"
            "\n--- SETTINGS ---\n"
            "toggle-llm on/off        — Enable/disable LLM\n"
            "shutdown                 — Graceful shutdown\n"
            "\n--- DIAGNOSTICS ---\n"
            "run-diagnostics          — Run full niblit diagnostic suite\n"
            "run-live-test            — Run live command tester\n"
            "loop-errors              — Show background loop error summary"
        )

        if self.orchestrator_available:
            orchestrator_help = (
                "\n\n--- ORCHESTRATOR ---\n"
                "orchestrate audit       — Run repository audit\n"
                "orchestrate self-heal   — Run self-healing\n"
                "orchestrate fix-guide   — Generate fix guide\n"
                "orchestrate verify      — Verify imports\n"
                "orchestrate pipeline    — Run full pipeline\n"
                "hf-task <prompt>        — Execute HF task"
            )
            return base_help + orchestrator_help

        return base_help

    def get_loop_errors(self) -> List[Dict]:
        """Return all loop errors captured by the LoopTracer since startup."""
        return loop_tracer.get_errors()

    def loop_tracer_summary(self) -> str:
        """Return a human-readable summary of all loop errors."""
        return loop_tracer.summary()

    def shutdown(self, timeout_seconds: Optional[float] = None):
        """Gracefully shutdown NiblitCore and all services."""
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
            cmd = input("Niblit > ").strip()
            if cmd:
                print(core.handle(cmd))
    except KeyboardInterrupt:
        print("\nShutting down...")
        core.shutdown()
