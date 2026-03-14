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
        Report Niblit-specific loaded modules.
        By default shows only modules whose name starts with 'modules.'
        """
        niblit_mods = {
            name: mod
            for name, mod in sorted(sys.modules.items())
            if name.startswith(filter_prefix)
        }
        if not niblit_mods:
            return f"No loaded modules matching prefix '{filter_prefix}'."

        lines = [f"📦 **Loaded Modules** (prefix='{filter_prefix}', {len(niblit_mods)} found):\n"]
        for name, mod in niblit_mods.items():
            spec = getattr(mod, "__spec__", None)
            origin = spec.origin if spec and spec.origin else "—"
            # Shorten path
            if origin and len(origin) > 60:
                origin = "…" + origin[-57:]
            lines.append(f"  ✅ {name:<45}  {origin}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # 4. COMMAND REGISTRY
    # ──────────────────────────────────────────────────────
    def command_report(self, router: Any = None) -> str:
        """
        Return a structured list of all registered commands.
        Tries the router's help_text() first, then the core's CommandRegistry.
        """
        lines = ["📋 **Registered Commands**:\n"]

        # Try router help_text
        if router and hasattr(router, "help_text"):
            try:
                help_str = router.help_text()
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
