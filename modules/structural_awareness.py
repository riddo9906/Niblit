#!/usr/bin/env python3
"""
STRUCTURAL AWARENESS MODULE
Niblit's real-time self-awareness of his own architecture.

Provides live insight into:
- Active threads and their status
- Background loop health
- Loaded Python modules (from sys.modules) and their origin
- Registered commands
- Memory & resource usage
- Full operational dashboard
"""

import sys
import os
import time
import threading
import logging
import platform
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("StructuralAwareness")


# ──────────────────────────────────────────────────────────
# KNOWN LOOP NAMES → friendly description
# ──────────────────────────────────────────────────────────
_LOOP_DESCRIPTIONS: Dict[str, str] = {
    "HealthLoop":        "Monitors system health, memory, and CPU periodically",
    "TrainerLoop":       "Triggers Trainer.step_if_needed() on captured interactions",
    "ResearchLoop":      "Auto-researches queued learning topics in background",
    "HealLoop":          "Runs SelfHealer checks and auto-repair cycles",
    "DumpMonitoringLoop":"Watches for diagnostic dump requests",
    "AsyncEventLoop":    "asyncio event loop for async background tasks",
    "SLSA-Generator":    "Continuous knowledge artifact generator (Wikipedia + weather)",
    "AutonomousLearning":"Autonomous research + idea generation when Niblit is idle",
    "OrchestrationLoop": "Top-level orchestration heartbeat",
}


class StructuralAwareness:
    """
    Real-time self-awareness engine.

    Wired into NiblitCore.  Access via:
        core.structural_awareness.runtime_dashboard()
        core.structural_awareness.thread_report()
        core.structural_awareness.loop_report(core)
        core.structural_awareness.module_report()
        core.structural_awareness.command_report(router)
    """

    def __init__(self, core: Any = None):
        self.core = core
        self._boot_time = time.time()
        log.debug("[StructuralAwareness] Initialized.")

    # ──────────────────────────────────────────────────────
    # 1. THREADS
    # ──────────────────────────────────────────────────────
    def thread_report(self) -> str:
        """Return a formatted list of all live Python threads."""
        threads = threading.enumerate()
        lines = [f"🧵 **Active Threads** ({len(threads)} total):\n"]
        for t in sorted(threads, key=lambda x: x.name):
            status = "alive" if t.is_alive() else "dead"
            daemon = "[daemon]" if t.daemon else "[non-daemon]"
            desc = _LOOP_DESCRIPTIONS.get(t.name, "")
            desc_str = f"  ↳ {desc}" if desc else ""
            lines.append(f"  • {t.name:<30} {status:6}  {daemon}{desc_str}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 2. BACKGROUND LOOPS (from NiblitCore)
    # ──────────────────────────────────────────────────────
    def loop_report(self, core: Any = None) -> str:
        """
        Report the status of NiblitCore background loops.

        Reads core._background_threads; falls back to thread enumeration.
        """
        target = core or self.core
        bg_threads: List[threading.Thread] = getattr(target, "_background_threads", [])
        if not bg_threads:
            # Fallback: show all threads that look like loops
            bg_threads = [
                t for t in threading.enumerate()
                if any(keyword in t.name for keyword in ("Loop", "Generator", "Autonomous"))
            ]

        if not bg_threads:
            return "⚙️ No background loops registered."

        lines = [f"⚙️ **Background Loops** ({len(bg_threads)}):\n"]
        for t in bg_threads:
            status_icon = "🟢" if t.is_alive() else "🔴"
            desc = _LOOP_DESCRIPTIONS.get(t.name, "background task")
            lines.append(f"  {status_icon} {t.name:<32}  {desc}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 3. LOADED MODULES
    # ──────────────────────────────────────────────────────
    def module_report(self, filter_prefix: str = "modules") -> str:
        """
        Full filesystem inventory of every Python script in the repo, organised
        by directory (main dir + every subdirectory).  Also shows which of those
        files are currently imported (loaded) in sys.modules.

        The legacy ``filter_prefix`` parameter is preserved for compatibility but
        the report always covers the whole project tree.
        """
        # Determine project root from this file's location
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        _SKIP_DIRS = {"__pycache__", ".git", ".github", ".devcontainer",
                      "node_modules", ".vercel", "venv", ".venv", "env"}

        # Build tree: rel_dir -> [filename, ...]
        tree: Dict[str, List[str]] = defaultdict(list)

        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            rel_dir = os.path.relpath(dirpath, base)
            if rel_dir == ".":
                rel_dir = "(root)"
            py_files = sorted(
                f for f in filenames
                if f.endswith(".py") and not f.startswith(".")
            )
            if py_files:
                tree[rel_dir].extend(py_files)

        # Build loaded-module lookup
        loaded_stems: set = set()
        for mod_name in sys.modules:
            loaded_stems.add(mod_name.split(".")[-1])
            loaded_stems.add(mod_name.replace(".", "/"))

        total_files = sum(len(v) for v in tree.values())
        lines = [
            f"\U0001f4e6 **Niblit Script Inventory** "
            f"({total_files} scripts in {len(tree)} dirs):\n"
        ]

        sorted_dirs = sorted(tree.keys(), key=lambda d: ("" if d == "(root)" else d))
        for rel_dir in sorted_dirs:
            files = tree[rel_dir]
            lines.append(f"\n  \U0001f4c2 {rel_dir}/ ({len(files)} scripts)")
            for fname in files:
                stem = os.path.splitext(fname)[0]
                mod_key_slash = (
                    stem if rel_dir == "(root)"
                    else f"{rel_dir.replace(os.sep, '/')}/{stem}"
                )
                mod_key_dot = mod_key_slash.replace("/", ".")

                loaded = (
                    stem in loaded_stems
                    or mod_key_slash in loaded_stems
                    or mod_key_dot in sys.modules
                )
                icon = "\u2705" if loaded else "\u2b1c"

                script_key = (
                    fname if rel_dir == "(root)"
                    else f"{rel_dir.replace(os.sep, '/')}/{fname}"
                )
                desc = self._KNOWN_SCRIPTS.get(script_key, "")
                desc_part = f"  \u2014 {desc}" if desc else ""
                lines.append(f"    {icon} {fname}{desc_part}")

        loaded_count = sum(
            1 for rd, files in tree.items()
            for fname in files
            if (os.path.splitext(fname)[0] in loaded_stems)
               or (
                   (("" if rd == "(root)" else rd.replace(os.sep, ".") + ".")
                    + os.path.splitext(fname)[0])
                   in sys.modules
               )
        )
        lines.append(
            f"\n  \u2705 Loaded: ~{loaded_count}  \u2b1c Not imported  |  Total: {total_files}"
        )
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 3b. ALL REPO SCRIPTS INVENTORY
    # ──────────────────────────────────────────────────────

    _KNOWN_SCRIPTS: Dict[str, str] = {
        # Core orchestration
        "niblit_core.py":             "Main NiblitCore class — wires every subsystem",
        "niblit_router.py":           "NiblitRouter — routes text commands to handlers",
        "niblit_brain.py":            "NiblitBrain — LLM reasoning + memory access",
        "niblit_memory/__init__.py":  "Canonical memory: FusedMemory, KnowledgeDB, NiblitMemory",
        "niblit_memory.py":           "Backward-compat shim for niblit_memory/__init__.py",
        "niblit_orchestrator.py":     "High-level orchestration wrapper",
        "niblit_actions.py":          "File I/O, shell execution, directory listing actions",
        "niblit_sqlite_db.py":        "SQLite-backed persistent store (companion to JSON LocalDB)",
        "app.py":                     "FastAPI app entry-point (local / production)",
        "server.py":                  "Alternative FastAPI server entry-point",
        "api/index.py":               "Vercel serverless FastAPI handler",
        "main.py":                    "Interactive CLI entry-point",
        # Modules
        "modules/autonomous_learning_engine.py": "ALE — drives Niblit's self-learning cycles",
        "modules/ale_checkpoint.py":  "ALE checkpoint manager (persist/restore ALE state)",
        "modules/self_researcher.py": "SelfResearcher — multi-backend autonomous research",
        "modules/self_teacher.py":    "SelfTeacher — ingests research into KnowledgeDB",
        "modules/self_healer.py":     "SelfHealer — detects and repairs code faults",
        "modules/self_implementer.py":"SelfImplementer — turns ideas into code",
        "modules/self_idea_generator.py": "SelfIdeaGenerator — generates improvement ideas",
        "modules/self_maintenance.py":"SelfMaintenance — periodic system maintenance",
        "modules/self_monitor.py":    "SelfMonitor — experience tracking & trend analysis",
        "modules/improvement_integrator.py": "ImprovementIntegrator — applies ALE improvements",
        "modules/code_generator.py":  "CodeGenerator — generates code templates & utilities",
        "modules/code_compiler.py":   "CodeCompiler — compiles and validates generated code",
        "modules/code_error_fixer.py":"CodeErrorFixer — detects & fixes code errors",
        "modules/evolve.py":          "EvolveEngine — evolutionary self-improvement",
        "modules/structural_awareness.py": "StructuralAwareness — component/thread/loop inventory",
        "modules/knowledge_digest.py":"KnowledgeDigest — rephrases research in Niblit's words",
        "modules/knowledge_synthesizer.py": "KnowledgeSynthesizer — cross-domain fact synthesis",
        "modules/live_updater.py":    "LiveUpdater — hot-reload and patch modules at runtime",
        "modules/filesystem_manager.py": "FilesystemManager — safe filesystem CRUD operations",
        "modules/deployment_bridge.py": "DeploymentBridge — cross-deployment state persistence",
        "modules/autonomous_network.py": "AutonomousNetworkBuilder — self-evolving network layer",
        "modules/module_autonomy.py": "ModuleAutonomy — robustness/intelligence/unification framework",
        "modules/trading_brain.py":   "TradingBrain — autonomous crypto trading cycle",
        "modules/trading_swing_v3.py":"SwingTraderV3 — continuous trend re-entry model",
        "modules/lean_engine.py":     "LeanEngine — QuantConnect/LEAN backtesting & live trading",
        "modules/game_engine.py":     "GameEngine — headless game simulation (pong/gravity/adventure)",
        "modules/universal_file_manager.py": "UniversalFileManager — pluggable file handler registry",
        "modules/internet_manager.py":"InternetManager — web search, Wikipedia, Hackernews",
        "modules/llm_adapter.py":     "LLMAdapter — unified LLM interface (OpenAI/Anthropic/HF)",
        "modules/hf_adapter.py":      "HuggingFace model adapter",
        "modules/hf_brain.py":        "HFBrain — stateful HuggingFace Router LLM (Kimi-K2 / any HF model)",
        "modules/anthropic_adapter.py":"Anthropic Claude adapter",
        "modules/openai_adapter.py":  "OpenAI GPT adapter",
        "modules/local_llm_adapter.py":"Local LLM (Ollama/etc) adapter",
        "modules/parameter_manager.py":"ParameterManager — env/file/remote config with hot-reload",
        "modules/plugin_architecture.py": "PluginManager — hot-loadable plugin system",
        "modules/command_registry.py":"CommandRegistry — central command registration",
        "modules/rate_limiting.py":   "RateLimiter — per-operation rate limiting",
        "modules/circuit_breaker.py": "CircuitBreaker — fail-fast protection",
        "modules/metacognition.py":   "Metacognition — self-awareness of reasoning processes",
        "modules/reasoning_engine.py":"ReasoningEngine — structured multi-step reasoning",
        "modules/gap_analyzer.py":    "GapAnalyzer — detects and prioritises knowledge gaps",
        "modules/memory_optimizer.py":"MemoryOptimizer — memory usage and deduplication",
        "modules/adaptive_learning.py":"AdaptiveLearning — adjusts learning rate dynamically",
        "modules/fused_memory_primary.py": "FusedMemoryPrimary — raw vector + record API",
        "modules/vector_store.py":    "VectorStore / FusedStorage — vector persistence shim",
        "modules/hybrid_qdrant_manager.py": "HybridQdrantManager — multi-model vector search",
        "modules/multi_level_caching.py":   "Multi-level cache (memory + Redis)",
        "modules/builds_integrator.py":     "BuildsIntegrator — wraps all builds/python scripts",
        "modules/software_studier.py":      "SoftwareStudier — studies own source for self-knowledge",
        "modules/mcp_server.py":      "MCP server — registers FastAPI routes for MCP protocol",
        "modules/slsa_generator.py":  "SLSAGenerator — continuous semantic learning & structuring",
        "modules/slsa_manager.py":    "SLSAManager — manages SLSA artifact lifecycle",
        "modules/storage.py":         "KnowledgeDB (legacy storage shim)",
        "modules/permission_manager.py": "PermissionManager — user-granted permission store",
        "modules/terminal_tools.py":  "TerminalTools — safe subprocess + file write helpers",
        "modules/background_topic_refresh.py": "Background topic refresh loop",
        "modules/dynamic_topic_manager.py": "Dynamic topic lifecycle management",
        "modules/parallel_learning_engine.py": "Parallel concurrent learning pipeline",
        "modules/collaborative_learner.py": "Collaborative multi-agent learning",
        "modules/agentic_workflows.py": "Agentic multi-step workflow engine",
        "modules/analytics.py":       "Analytics — telemetry and usage metrics",
        "modules/dashboard.py":       "Runtime dashboard renderer",
        "modules/realtime_stream.py": "Real-time WebSocket stream manager",
        "modules/prediction_engine.py": "PredictionEngine — temporal forecasting",
        # Agents package
        "agents/__init__.py":         "Phase-2 agent package (Planner/Research/Code/Test/Reflect/Arch)",
        "agents/planner_agent.py":    "PlannerAgent — decomposes goals into tasks",
        "agents/research_agent.py":   "ResearchAgent — autonomous research tasks",
        "agents/coding_agent.py":     "CodingAgent — generates and validates code",
        "agents/testing_agent.py":    "TestingAgent — runs and evaluates tests",
        "agents/reflection_agent.py": "ReflectionAgent — gap detection & contradiction resolution",
        "agents/architecture_agent.py":"ArchitectureAgent — architectural planning",
        # Tools
        "tools/FixGuideGenerator.py": "Generates bash fix guides for missing __main__ blocks",
        "tools/repo_audit.py":        "Audits repository for writable-path compliance",
        "tools/self_heal_auto.py":    "Automated self-healing runner",
        # Other top-level scripts
        "trainer_full.py":            "BackgroundTrainer — daemon training loop",
        "slsa_generator_full.py":     "SLSAGenerator (full) — production SLSA generator wired to core",
        "Slsa_generator_full.py":     "Full SLSA generator (production variant)",
        "run_diagnostics.py":         "Live command tester & diagnostics runner",
        "live_command_tester.py":     "Command tester with JSON report output",
        "niblit_full_upgrade_pipeline.py": "Full upgrade pipeline (GitHub/HF/news ingestion)",
        "workspace_init.py":          "WorkspaceInitializer — creates project directory structure",
        "niblit_manager.py":          "Manager entrypoint for automated maintenance",
        "conftest.py":                "Pytest configuration and fixtures",
    }

    def all_scripts_report(self) -> str:
        """Return a human-readable inventory of every repo script and its purpose."""
        lines = [f"📋 **All Repo Scripts** ({len(self._KNOWN_SCRIPTS)} entries):\n"]
        for path, desc in self._KNOWN_SCRIPTS.items():
            lines.append(f"  📄 {path}\n       └─ {desc}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 4. COMMAND REGISTRY
    # ──────────────────────────────────────────────────────
    def command_report(self, router: Any = None) -> str:
        """Return a structured list of all registered commands.

        Tries the router help_text() first, then the core CommandRegistry.
        """
        lines = ["📋 **Registered Commands**:\n"]

        # Try router help_text
        r = router or (getattr(self.core, "router", None) if self.core else None)
        if r and hasattr(r, "help_text"):
            try:
                help_str = r.help_text()
                return "📋 **Full Command Reference**:\n\n" + help_str
            except Exception as e:
                lines.append(f"  (router.help_text() failed: {e})")

        # Fallback: core command_registry
        core = self.core
        if core and hasattr(core, "command_registry") and core.command_registry:
            try:
                commands = core.command_registry.list_commands()
                for cmd in commands:
                    lines.append(f"  • {cmd}")
                return "\n".join(lines)
            except Exception as e:
                lines.append(f"  (command_registry failed: {e})")

        lines.append("  (No command registry available — use 'help' for commands)")
        return "\n".join(lines)

    def command_awareness_report(self, router: Any = None) -> Dict[str, Any]:
        """
        Return a structured dict of all commands with names, descriptions, and categories.
        Used by the autonomous engine to study and understand available commands.
        """
        commands: List[Dict[str, str]] = []
        core = self.core
        r = router or (getattr(core, "router", None) if core else None)

        # Primary: CommandRegistry — richest source (name + description + category)
        if core and hasattr(core, "command_registry") and core.command_registry:
            try:
                registry = core.command_registry
                if hasattr(registry, "commands"):
                    for name, entry in registry.commands.items():
                        commands.append({
                            "name": name,
                            "description": str(getattr(entry, "description", entry[1] if isinstance(entry, (list, tuple)) and len(entry) > 1 else "")),
                            "category": str(getattr(entry, "category", entry[2] if isinstance(entry, (list, tuple)) and len(entry) > 2 else "core")),
                        })
            except Exception:
                pass

        # Secondary: COMMAND_PREFIXES from router
        if not commands and r and hasattr(r, "COMMAND_PREFIXES"):
            for prefix in r.COMMAND_PREFIXES:
                commands.append({"name": prefix, "description": "", "category": "router"})

        # Build category map
        by_category: Dict[str, List[str]] = {}
        for entry in commands:
            cat = entry.get("category", "misc")
            by_category.setdefault(cat, []).append(entry["name"])

        return {
            "total": len(commands),
            "commands": commands,
            "by_category": by_category,
            "categories": sorted(by_category.keys()),
        }

    # ──────────────────────────────────────────────────────
    # 5. RESOURCE USAGE
    # ──────────────────────────────────────────────────────
    def resource_report(self) -> str:
        """Return basic memory and CPU snapshot."""
        lines = ["💾 **Resource Usage**:\n"]

        # Python process memory via resource or psutil
        rss_mb: Optional[float] = None
        cpu_pct: Optional[float] = None

        try:
            import psutil
            proc = psutil.Process(os.getpid())
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            cpu_pct = proc.cpu_percent(interval=0.1)
        except ImportError:
            pass
        except Exception:
            pass

        if rss_mb is None:
            try:
                import resource as _res
                rss_kb = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss
                rss_mb = rss_kb / 1024  # Linux reports KB
            except Exception:
                pass

        lines.append(f"  RAM (RSS) : {f'{rss_mb:.1f} MB' if rss_mb else 'N/A'}")
        lines.append(f"  CPU       : {f'{cpu_pct:.1f}%' if cpu_pct is not None else 'N/A'}")
        lines.append(f"  Python    : {platform.python_version()}")
        lines.append(f"  OS        : {platform.system()} {platform.release()}")
        lines.append(f"  Threads   : {threading.active_count()}")
        lines.append(f"  Modules   : {len(sys.modules)} loaded")

        # Uptime
        uptime_s = time.time() - self._boot_time
        h, rem = divmod(int(uptime_s), 3600)
        m, s = divmod(rem, 60)
        lines.append(f"  SA Uptime : {h:02d}h {m:02d}m {s:02d}s")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 6. CORE COMPONENT INVENTORY
    # ──────────────────────────────────────────────────────
    def component_report(self, core: Any = None) -> str:
        """
        Show NiblitCore's major components and whether they're live.
        """
        target = core or self.core
        if target is None:
            return "⚙️ Core not available — component report unavailable."

        # Ordered list of (attr_name, friendly_name)
        components = [
            ("db",                  "KnowledgeDB / LocalDB"),
            ("brain",               "NiblitBrain"),
            ("router",              "NiblitRouter"),
            ("memory",              "MemoryManager"),
            ("network",             "NiblitNetwork"),
            ("internet",            "InternetManager"),
            ("tasks",               "NiblitTasks"),
            ("lifecycle",           "LifecycleEngine"),
            ("collector",           "Collector"),
            ("trainer",             "Trainer"),
            ("self_healer",         "SelfHealer"),
            ("self_teacher",        "SelfTeacher"),
            ("self_researcher",     "SelfResearcher"),
            ("self_implementer",    "SelfImplementer"),
            ("idea_generator",      "SelfIdeaGenerator"),
            ("reflect",             "ReflectModule"),
            ("llm",                 "LLMAdapter"),
            ("improvements",        "ImprovementIntegrator"),
            ("autonomous_engine",   "AutonomousLearningEngine"),
            ("slsa_engine",         "SLSAGenerator"),
            ("live_updater",        "LiveUpdater"),
            ("structural_awareness","StructuralAwareness"),
            ("code_generator",      "CodeGenerator"),
            ("code_compiler",       "CodeCompiler"),
            ("file_manager",        "FilesystemManager"),
            ("software_studier",    "SoftwareStudier"),
            ("evolve_engine",       "EvolveEngine"),
            # Production modules
            ("command_registry",    "CommandRegistry"),
            ("rate_limiter",        "RateLimiter"),
            ("circuit_breakers",    "CircuitBreakers"),
            ("plugin_manager",      "PluginManager"),
            ("metacognition",       "Metacognition"),
            ("reasoning_engine",    "ReasoningEngine"),
            ("gap_analyzer",        "GapAnalyzer"),
            ("memory_optimizer",    "MemoryOptimizer"),
            ("adaptive_learning",   "AdaptiveLearning"),
            # Cross-deployment & autonomous intelligence (additive)
            ("deployment_bridge",   "DeploymentBridge"),
            ("autonomous_network",  "AutonomousNetworkBuilder"),
            ("module_autonomy",     "ModuleAutonomy"),
            # HFBrain (brain-level HuggingFace LLM)
            ("hf_brain",            "HFBrain"),
            # Additional wired modules
            ("background_trainer",  "BackgroundTrainer"),
            ("trading_brain",       "TradingBrain"),
            ("lean_engine",         "LeanEngine"),
            ("game_engine",         "GameEngine"),
            ("universal_file_manager", "UniversalFileManager"),
            ("hybrid_qdrant",       "HybridQdrantManager"),
            ("self_monitor",        "SelfMonitor"),
            ("kernel",              "NiblitKernel"),
            ("builds_integrator",   "BuildsIntegrator"),
        ]

        lines = [f"🔩 **Component Inventory** ({len(components)} tracked):\n"]
        online, offline = 0, 0
        for attr, friendly in components:
            val = getattr(target, attr, None)
            if val is not None:
                online += 1
                lines.append(f"  🟢 {friendly:<35}  ✔ {type(val).__name__}")
            else:
                offline += 1
                lines.append(f"  ⚫ {friendly:<35}  — not loaded")

        lines.append(f"\n  Online: {online}  /  Offline: {offline}  /  Total: {online+offline}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 7. LOOP FLOW EXPLANATION
    # ──────────────────────────────────────────────────────
    def operational_flow(self) -> str:
        """Human-readable explanation of how Niblit's loops work."""
        return """🔄 **How Niblit's Internal Loops Work:**

┌─────────────────────────────────────────────────────────────────┐
│                      NIBLIT RUNTIME FLOW                        │
└─────────────────────────────────────────────────────────────────┘

📥  USER INPUT
    │
    ▼
🔀  niblit_core.handle(text)
    ├─ CommandRegistry  → exact command match (fast path)
    ├─ NiblitRouter.process() → intent detection + routing
    │     ├─ self_introspection  → reflective self-answers
    │     ├─ self_referential    → "what are you?" etc.
    │     ├─ research            → internet + knowledge base
    │     ├─ autonomous-learn    → background learning control
    │     └─ chat                → LLM or research fallback
    └─ LLM (HFBrain / LLMAdapter) if no command match

🔁  BACKGROUND LOOPS (always running as daemon threads):

  HealthLoop      → every ~30s  : checks component health, logs warnings
  TrainerLoop     → every ~60s  : calls Trainer.step_if_needed() on buffer
  ResearchLoop    → every ~120s : processes get_learning_queue(), runs research
  HealLoop        → every ~300s : SelfHealer.run() — diagnose & patch issues
  DumpMonitorLoop → every ~60s  : checks for diagnostic dump requests
  SLSA-Generator  → every ~20s  : fetches Wikipedia/weather, stores artifacts
  AsyncEventLoop  → continuous  : handles async tasks if enabled

🧠  AUTONOMOUS LEARNING (when idle):
  AutonomousLearningEngine runs in background.
  When no user input for >30s:
    1. Picks a topic from the learning queue
    2. Researches it via InternetManager
    3. Generates ideas via SelfIdeaGenerator
    4. Stores results in KnowledgeDB
    5. Runs SelfReflection on recent facts

💾  MEMORY FLOW:
  Collector.capture() → KnowledgeDB.store_interaction()
                      → Trainer.step_if_needed() (every 8 interactions)
                      → SelfTeacher.teach() (for research/llm sources)

🔧  SELF-IMPROVEMENT:
  ImprovementIntegrator orchestrates:
  ParallelLearner, ReasoningEngine, GapAnalyzer, KnowledgeSynthesizer,
  PredictionEngine, MemoryOptimizer, AdaptiveLearning, Metacognition,
  CollaborativeLearner → run_improvement_cycle() on demand

♻️  HOT-UPDATE (LiveUpdater):
  reload <module>  → importlib.reload() with backup/rollback
  upgrade          → reload all modules changed on disk
  apply-patch      → write new source → validate → reload → rollback on error

💻  CODE CAPABILITIES:
  generate code <lang> [template] → CodeGenerator fills template → saves to generated/
  run code <lang> <code>          → CodeCompiler validates syntax → subprocess → result
  validate <lang> <code>          → AST syntax check (Python) or quick pre-run check
  study language <lang>           → CodeGenerator returns idioms + best practices

📁  FILE MANAGER:
  read/write/append/edit/delete/copy/move/execute for all file types
  Termux support: detects Termux environment automatically
  run code strings directly via temp files (Python, Bash, JS)

📦  SOFTWARE STUDIER:
  study software <category>  → deep study of OS, web, AI, databases, compilers, etc.
  analyze architecture <name>→ pros/cons of microservices, monolith, event-driven, etc.
  design software <desc>     → auto-generates architecture outline for any project"""

    # ──────────────────────────────────────────────────────
    # 8. FULL RUNTIME DASHBOARD
    # ──────────────────────────────────────────────────────
    def runtime_dashboard(self, core: Any = None, router: Any = None) -> str:  # pylint: disable=unused-argument
        """
        Master dashboard: threads + loops + components + resources.
        """
        target = core or self.core

        core_uptime = ""
        if target:
            core_start = getattr(target, "start_ts", None)
            if core_start:
                u = time.time() - core_start
                h, rem = divmod(int(u), 3600)
                m, s = divmod(rem, 60)
                core_uptime = f"  Core uptime : {h:02d}h {m:02d}m {s:02d}s\n"

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        header = f"🖥️  **NIBLIT RUNTIME DASHBOARD**  [{ts}]\n" + core_uptime

        sections = [
            header,
            self.thread_report(),
            "",
            self.loop_report(target),
            "",
            self.component_report(target),
            "",
            self.resource_report(),
        ]
        return "\n".join(sections)


# ──────────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== StructuralAwareness self-test ===\n")
    sa = StructuralAwareness()
    print(sa.thread_report())
    print()
    print(sa.loop_report())
    print()
    print(sa.module_report())
    print()
    print(sa.resource_report())
    print()
    print(sa.operational_flow())
    print("\nStructuralAwareness OK")
