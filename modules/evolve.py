#!/usr/bin/env python3
"""
EVOLVE MODULE — Niblit's Self-Evolution Engine

Continuously improves Niblit over time by:
1. Using all available modules to identify gaps
2. Researching improvements via self_researcher + internet
3. Generating new code/modules via code_generator
4. Compiling and testing improvements via code_compiler
5. Studying software patterns via software_studier
6. Teaching itself what it learns via self_teacher
7. Reflecting on improvements via reflect
8. Implementing ideas via idea_implementation + implementer
9. Running SLSA cycles to build semantic knowledge artifacts
10. Storing all knowledge in the knowledge DB
"""

import os
import time
import random
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("EvolveEngine")

# Default Termux deployment path for Niblit self-updates.
# When Niblit is running inside Termux this is the live installation directory.
# Evolved code is written here so the running process can hot-reload it.
TERMUX_DEPLOY_PATH = Path(
    "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
)


def _detect_termux() -> bool:
    """Return True if running inside a Termux environment."""
    return (
        "TERMUX_VERSION" in os.environ
        or os.path.isdir("/data/data/com.termux")
        or "termux" in os.environ.get("PREFIX", "").lower()
    )

# Possible evolution directions — expanded to cover all module capabilities
_EVOLUTION_DIRECTIONS = [
    "code generation quality",
    "autonomous research depth",
    "language pattern learning",
    "self-reflection accuracy",
    "knowledge synthesis",
    "command routing efficiency",
    "error recovery patterns",
    "internet research speed",
    "module integration depth",
    "memory utilization",
    "idea generation and implementation",
    "semantic knowledge building",
    "self-teaching effectiveness",
    "code research from internet",
    "autonomous learning efficiency",
]


class EvolveEngine:
    """
    Niblit's self-evolution engine.

    Orchestrates ALL available modules to improve Niblit's capabilities
    over time through research, code generation, teaching, reflection,
    idea implementation, internet research, and SLSA semantic building.

    Usage:
        evolve = EvolveEngine(core=niblit_core)
        evolve.step()
        evolve.start_background_evolution()
    """

    def __init__(
        self,
        core: Any = None,
        researcher=None,
        code_generator=None,
        code_compiler=None,
        software_studier=None,
        self_teacher=None,
        reflect_module=None,
        idea_generator=None,
        implementer=None,
        knowledge_db=None,
        internet=None,
        idea_implementation=None,
        slsa=None,
        autonomous_engine=None,
        evolution_interval: int = 300,
        sub_step_timeout: int = 10,
        live_updater=None,
        file_manager=None,
        deploy_path: Optional[str] = None,
    ):
        """Initialise the EvolveEngine.

        Args:
            core: NiblitCore instance; used by refresh_from_core() to pull references.
            researcher: SelfResearcher — fetches info on improvement directions.
            code_generator: CodeGenerator — produces new Python code artefacts.
            code_compiler: CodeCompiler — validates/compiles generated code.
            software_studier: SoftwareStudier — studies software patterns.
            self_teacher: SelfTeacher — teaches Niblit what it learns.
            reflect_module: ReflectModule — reflects on evolution steps.
            idea_generator: SelfIdeaGenerator — generates implementation ideas.
            implementer: SelfImplementer — raw implementation executor.
            knowledge_db: KnowledgeDB — stores evolution facts/events.
            internet: InternetManager — direct web research.
            idea_implementation: SelfIdeaImplementation — full idea-to-code pipeline.
            slsa: SLSAManager — builds semantic knowledge artefacts.
            autonomous_engine: AutonomousLearningEngine — coordinates broader learning.
            evolution_interval: Seconds between background evolution loop iterations.
            sub_step_timeout: Default maximum seconds any single sub-step may
                run before being skipped (default 10).  Individual calls to
                ``_run_sub_step`` can override this with a *timeout* argument —
                network-heavy sub-steps like 'research' and 'slsa_cycle' use
                60 s so they are not prematurely cancelled.
            live_updater: LiveUpdater — hot-reloads changed modules at runtime.
            file_manager: FilesystemManager — writes generated files to disk.
            deploy_path: Explicit filesystem path where self-updates are written.
                When None (default) the path is auto-detected: on Termux it
                resolves to TERMUX_DEPLOY_PATH; on other environments no files
                are written.
        """
        self.core = core
        self.researcher = researcher
        self.code_generator = code_generator
        self.code_compiler = code_compiler
        self.software_studier = software_studier
        self.self_teacher = self_teacher
        self.reflect = reflect_module
        self.idea_generator = idea_generator
        self.implementer = implementer
        self.knowledge_db = knowledge_db
        self.internet = internet
        self.idea_implementation = idea_implementation
        self.slsa = slsa
        self.autonomous_engine = autonomous_engine
        self.evolution_interval = evolution_interval
        self.sub_step_timeout = sub_step_timeout
        self.live_updater = live_updater
        self.file_manager = file_manager

        # Resolve the deploy path: explicit arg → Termux default if on Termux → None
        if deploy_path is not None:
            self.deploy_path: Optional[Path] = Path(deploy_path)
        elif _detect_termux():
            self.deploy_path = TERMUX_DEPLOY_PATH
        else:
            self.deploy_path = None

        self.iteration = 0
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._history: List[Dict[str, Any]] = []

        self._stats: Dict[str, int] = {
            "steps": 0,
            "researched": 0,
            "code_generated": 0,
            "taught": 0,
            "reflected": 0,
            "ideas_implemented": 0,
            "code_researched": 0,
            "slsa_cycles": 0,
            "deploy_writes": 0,
            "live_upgrades": 0,
        }

        log.info("[EvolveEngine] Initialized")

    # ──────────────────────────────────────────────
    # TIMEOUT HELPER
    # ──────────────────────────────────────────────

    def _run_sub_step(self, name: str, func, timeout: Optional[int] = None) -> Optional[str]:
        """Run *func()* in a daemon thread with a per-sub-step timeout.

        Returns the result on success, or None if the sub-step raises or
        exceeds the effective timeout.  Using a daemon thread (rather than a
        ``ThreadPoolExecutor`` context manager) ensures ``join(timeout=...)``
        returns immediately without waiting for the thread to finish — the
        thread will eventually complete or be discarded when the process exits.

        Args:
            name: Human-readable name used in log messages.
            func: Zero-argument callable to execute in the worker thread.
            timeout: Override timeout in seconds for this sub-step.  When
                *None* (default) ``self.sub_step_timeout`` is used.
        """
        effective_timeout = timeout if timeout is not None else self.sub_step_timeout
        result_box: List[Any] = [None]
        error_box: List[Any] = [None]

        def _target():
            try:
                result_box[0] = func()
            except Exception as exc:
                error_box[0] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=effective_timeout)

        if thread.is_alive():
            log.warning(
                "[EvolveEngine] Sub-step '%s' timed out after %ds — skipping",
                name, effective_timeout,
            )
            return None

        if error_box[0] is not None:
            log.debug("[EvolveEngine] Sub-step '%s' failed: %s", name, error_box[0])
            return None

        return result_box[0]

    # ──────────────────────────────────────────────
    # CORE STEP
    # ──────────────────────────────────────────────

    def step(self) -> Dict[str, Any]:
        """Execute one evolution step using ALL available modules."""
        self.iteration += 1
        ts = datetime.now(timezone.utc).isoformat()
        direction = random.choice(_EVOLUTION_DIRECTIONS)

        record: Dict[str, Any] = {
            "iteration": self.iteration,
            "ts": ts,
            "direction": direction,
            "actions": [],
            "mutations": [],
        }

        # Step 1: Research the improvement direction via self_researcher
        research_result = self._run_sub_step("research", lambda: self._research_direction(direction), timeout=60)
        if research_result:
            record["actions"].append(f"researched: {research_result[:60]}")

        # Step 2: Direct internet research (no LLM, raw web data)
        internet_result = self._run_sub_step("internet_research", lambda: self._internet_direct_research(direction))
        if internet_result:
            record["actions"].append(f"internet: {internet_result[:60]}")

        # Step 3: Research code patterns from internet → feed CodeGenerator
        code_research_result = self._run_sub_step("code_research", lambda: self._research_code_direction(direction))
        if code_research_result:
            record["actions"].append(f"code_research: {code_research_result[:60]}")

        # Step 4: Study relevant software patterns
        study_result = self._run_sub_step("study_patterns", lambda: self._study_patterns(direction))
        if study_result:
            record["actions"].append(f"studied: {study_result[:60]}")

        # Step 5: Generate code for the improvement
        code_result = self._run_sub_step("code_gen", lambda: self._generate_improvement_code(direction))
        if code_result:
            record["actions"].append(f"code_gen: {code_result[:60]}")
            record["mutations"].append(code_result)

        # Step 6: Teach myself what I learned
        teach_result = self._run_sub_step("teach", lambda: self._teach_improvement(direction, research_result))
        if teach_result:
            record["actions"].append(f"taught: {teach_result[:60]}")

        # Step 7: Reflect on the improvement
        reflect_result = self._run_sub_step("reflect", lambda: self._reflect_on_step(direction, record))
        if reflect_result:
            record["actions"].append(f"reflected: {str(reflect_result or '')[:60]}")

        # Step 8: Generate and implement an idea via idea_implementation
        impl_result = self._run_sub_step("implement_idea", lambda: self._implement_evolution_idea(direction, research_result))
        if impl_result:
            record["actions"].append(f"implemented: {impl_result[:60]}")

        # Step 9: Generate an implementation plan via idea_generator
        idea_result = self._run_sub_step("idea_gen", lambda: self._generate_idea(direction))
        if idea_result:
            record["actions"].append(f"idea: {idea_result[:60]}")

        # Step 10: Run a SLSA semantic knowledge cycle
        slsa_result = self._run_sub_step("slsa_cycle", lambda: self._run_slsa_cycle(direction), timeout=60)
        if slsa_result:
            record["actions"].append(f"slsa: {slsa_result[:60]}")

        # Step 11: Write generated code to deploy path (Termux live installation)
        deploy_result = self._run_sub_step(
            "deploy_write",
            lambda: self._write_to_deploy_path(direction, record),
        )
        if deploy_result:
            record["actions"].append(f"deployed: {deploy_result[:60]}")

        # Step 12: Hot-reload any written improvements into the running process
        upgrade_result = self._run_sub_step(
            "live_upgrade",
            lambda: self._live_upgrade_step(),
        )
        if upgrade_result:
            record["actions"].append(f"live_upgraded: {upgrade_result[:60]}")

        # Update stats
        self._stats["steps"] += 1
        record["stats_snapshot"] = dict(self._stats)

        # Store in history
        self._history.append(record)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        # Persist to knowledge DB
        self._persist_step(record)

        log.info("[EvolveEngine] Step %d: direction=%s, actions=%d",
                 self.iteration, direction, len(record["actions"]))

        return record

    # ──────────────────────────────────────────────
    # SUB-STEPS
    # ──────────────────────────────────────────────

    def _research_direction(self, direction: str) -> Optional[str]:
        """Use self_researcher to fetch info on the improvement direction."""
        if not self.researcher:
            return None
        try:
            results = self.researcher.search(
                f"how to improve {direction} in AI systems",
                max_results=2,
                use_llm=False,
                synthesize=False,
                enable_autonomous_learning=True,
            )
            self._stats["researched"] += 1
            return str(results[0])[:200] if results else None
        except Exception as exc:
            log.debug("[EvolveEngine] Research failed: %s", exc)
            return None

    def _study_patterns(self, direction: str) -> Optional[str]:
        """Use software_studier to study patterns relevant to the direction."""
        if not self.software_studier:
            return None
        try:
            # Map direction keywords to software categories
            cat_map = {
                "code generation": "compilers_interpreters",
                "research": "ai_ml_systems",
                "language": "compilers_interpreters",
                "memory": "databases",
                "routing": "networking",
                "command": "operating_systems_software",
                "synthesis": "ai_ml_systems",
                "reflection": "ai_ml_systems",
            }
            cat = "ai_ml_systems"  # default
            for kw, c in cat_map.items():
                if kw in direction:
                    cat = c
                    break
            result = self.software_studier.study_category(cat)
            return result[:200] if result else None
        except Exception as exc:
            log.debug("[EvolveEngine] Study failed: %s", exc)
            return None

    def _generate_improvement_code(self, direction: str) -> Optional[str]:
        """Generate code for the improvement direction."""
        if not self.code_generator:
            return None
        try:
            # Map direction to language
            lang = "python"
            name = direction.replace(" ", "_").replace("-", "_")
            result = self.code_generator.generate(
                lang,
                "function",
                name=f"improve_{name}",
                docstring=f"Improvement function for: {direction}",
                body=f'"""Auto-generated improvement for: {direction}"""\n    pass',
            )
            if result.get("success"):
                self._stats["code_generated"] += 1
                return f"Generated improve_{name}() in Python"
            return None
        except Exception as exc:
            log.debug("[EvolveEngine] Code gen failed: %s", exc)
            return None

    def _teach_improvement(self, direction: str, research: Optional[str]) -> Optional[str]:
        """Feed what we learned to self_teacher."""
        if not self.self_teacher:
            return None
        try:
            topic = f"evolution improvement: {direction}"
            if research:
                topic = f"{topic}\n\nResearch finding: {research[:200]}"
            result = self.self_teacher.teach(topic)
            self._stats["taught"] += 1
            return str(result or "taught")[:100]
        except Exception as exc:
            log.debug("[EvolveEngine] Teach failed: %s", exc)
            return None

    def _reflect_on_step(self, direction: str, record: Dict) -> Optional[str]:
        """Reflect on this evolution step."""
        if not self.reflect:
            return None
        try:
            entry = (
                f"Evolution step {self.iteration}: direction={direction}\n"
                f"Actions taken: {len(record['actions'])}\n"
                f"Total steps so far: {self._stats['steps']}\n"
                f"Research count: {self._stats['researched']}"
            )
            result = self.reflect.collect_and_summarize(entry)
            self._stats["reflected"] += 1
            return result
        except Exception as exc:
            log.debug("[EvolveEngine] Reflect failed: %s", exc)
            return None

    def _generate_idea(self, direction: str) -> Optional[str]:
        """Generate an idea for future implementation."""
        if not self.idea_generator:
            return None
        try:
            if hasattr(self.idea_generator, "generate_plan"):
                idea_text = f"Improve {direction} capability in Niblit"
                self.idea_generator.generate_plan(idea_text)
                return f"Queued idea: {idea_text[:80]}"
        except Exception as exc:
            log.debug("[EvolveEngine] Idea gen failed: %s", exc)
        return None

    def _internet_direct_research(self, direction: str) -> Optional[str]:
        """Use internet manager directly to fetch the latest info on the direction."""
        if not self.internet:
            return None
        try:
            query = f"latest advances in {direction} for AI systems"
            results = self.internet.search(query, max_results=2)
            if results:
                first = results[0]
                text = first.get("text", str(first)) if isinstance(first, dict) else str(first)
                self._stats["researched"] += 1
                # Store to knowledge DB
                if self.knowledge_db and hasattr(self.knowledge_db, "add_fact"):
                    self.knowledge_db.add_fact(
                        f"internet_research:{direction}:{int(time.time())}",
                        text[:400],
                        tags=["internet", "evolution", "research"]
                    )
                return text[:200]
        except Exception as exc:
            log.debug("[EvolveEngine] Internet research failed: %s", exc)
        return None

    def _research_code_direction(self, direction: str) -> Optional[str]:
        """Use self_researcher.research_code_and_feed_generator for code-related directions."""
        if not self.researcher:
            return None
        if not hasattr(self.researcher, "research_code_and_feed_generator"):
            return None
        # Only run for code/language directions
        code_keywords = ["code", "language", "compile", "pattern", "python", "generation"]
        if not any(kw in direction.lower() for kw in code_keywords):
            return None
        try:
            lang = "python"
            # Build topic from direction by removing generic words
            stop_words = {"code", "generation", "language", "pattern", "quality", "learning"}
            topic_words = [w for w in direction.split() if w.lower() not in stop_words]
            topic = " ".join(topic_words).strip() or "best practices"
            result = self.researcher.research_code_and_feed_generator(
                lang, topic, code_generator=self.code_generator
            )
            self._stats["code_researched"] += 1
            return str(result)[:200] if result else None
        except Exception as exc:
            log.debug("[EvolveEngine] Code research failed: %s", exc)
        return None

    def _implement_evolution_idea(self, direction: str, research: Optional[str]) -> Optional[str]:
        """Use idea_implementation to implement an idea derived from this evolution step."""
        if not self.idea_implementation:
            return None
        try:
            idea_prompt = f"Evolution improvement for {direction}"
            if research:
                idea_prompt += f": {research[:100]}"
            if hasattr(self.idea_implementation, "implement_idea"):
                result = self.idea_implementation.implement_idea(idea_prompt)
                self._stats["ideas_implemented"] += 1
                return str(result)[:200] if result else None
        except Exception as exc:
            log.debug("[EvolveEngine] Idea implementation failed: %s", exc)
        return None

    def _run_slsa_cycle(self, direction: str) -> Optional[str]:
        """Trigger an SLSA semantic knowledge generation cycle for the direction."""
        if not self.slsa:
            return None
        try:
            if hasattr(self.slsa, "generate_cycle"):
                topic = direction.replace(" ", "_")
                result = self.slsa.generate_cycle(topic)
                self._stats["slsa_cycles"] += 1
                if result:
                    return f"SLSA artifact: {str(result.get('concept', topic))[:80]}"
                return f"SLSA cycle ran for: {topic[:60]}"
        except Exception as exc:
            log.debug("[EvolveEngine] SLSA cycle failed: %s", exc)
        return None

    def _write_to_deploy_path(self, direction: str, record: Dict) -> Optional[str]:
        """Write generated code mutations to the Termux deployment directory.

        Each evolution step that produced code mutations writes them as Python
        files under *self.deploy_path / "evolved"* so they are ready for
        hot-reload by the live updater or on the next process start.
        """
        if not self.deploy_path:
            return None
        mutations = record.get("mutations", [])
        if not mutations:
            return None

        try:
            evolved_dir = self.deploy_path / "evolved"
            evolved_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_dir = direction.replace(" ", "_")[:40]
            step_dir = evolved_dir / f"step_{self.iteration:04d}_{safe_dir}_{ts}"
            step_dir.mkdir(parents=True, exist_ok=True)

            written: List[str] = []
            for idx, code in enumerate(mutations):
                fname = step_dir / f"improvement_{idx + 1}.py"
                header = (
                    f"# Auto-generated by EvolveEngine step {self.iteration}\n"
                    f"# Direction: {direction}\n"
                    f"# Timestamp: {ts}\n\n"
                )
                try:
                    fname.write_text(header + str(code), encoding="utf-8")
                    written.append(fname.name)
                except OSError as exc:
                    log.debug("[EvolveEngine] Deploy write failed for %s: %s", fname, exc)

            if written:
                self._stats["deploy_writes"] += 1
                log.info(
                    "[EvolveEngine] Wrote %d improvement file(s) to %s",
                    len(written), step_dir,
                )
                # Also log to knowledge DB
                if self.knowledge_db and hasattr(self.knowledge_db, "add_fact"):
                    try:
                        self.knowledge_db.add_fact(
                            f"evolve_deploy:{self.iteration}:{int(time.time())}",
                            {"path": str(step_dir), "files": written, "direction": direction},
                            tags=["evolution", "deploy", "write"],
                        )
                    except Exception:
                        pass
                return f"Wrote {len(written)} file(s) to {str(step_dir)[-50:]}"

        except Exception as exc:
            log.debug("[EvolveEngine] Deploy write step failed: %s", exc)

        return None

    def _live_upgrade_step(self) -> Optional[str]:
        """Hot-reload any evolution-generated code into the running process.

        Uses *self.live_updater* (LiveUpdater) to:
        1. Reload all modules whose source files have been modified since they
           were last loaded (picks up improvements written by other steps).
        2. Reload any module whose file now lives inside *self.deploy_path*
           when the deploy path is set.

        Returns a short summary string or None if nothing was reloaded.
        """
        if not self.live_updater:
            return None

        reloaded: List[str] = []

        try:
            # Reload all modules changed in the current base_dir
            if hasattr(self.live_updater, "reload_all_changed"):
                results = self.live_updater.reload_all_changed()
                for r in results or []:
                    if r.get("success"):
                        reloaded.append(r.get("module", "?"))
        except Exception as exc:
            log.debug("[EvolveEngine] live_upgrade reload_all_changed failed: %s", exc)

        if reloaded:
            self._stats["live_upgrades"] += 1
            log.info("[EvolveEngine] Live-upgraded %d module(s): %s", len(reloaded), reloaded)
            return f"Hot-reloaded {len(reloaded)} module(s): {', '.join(reloaded[:3])}"

        return None

    def _persist_step(self, record: Dict) -> None:
        """Store evolution step in knowledge DB."""
        if not self.knowledge_db:
            return
        try:
            key = f"evolution_step:{self.iteration}:{int(time.time())}"
            value = f"Step {self.iteration}: {record['direction']} — {len(record['actions'])} actions"
            if hasattr(self.knowledge_db, "add_fact"):
                self.knowledge_db.add_fact(key, value, tags=["evolution", "improvement"])
        except Exception as exc:
            log.debug("[EvolveEngine] Persist failed: %s", exc)

    # ──────────────────────────────────────────────
    # BACKGROUND LOOP
    # ──────────────────────────────────────────────

    def start_background_evolution(self) -> bool:
        """Start the background evolution thread."""
        if self.running:
            return False
        self.running = True
        self._thread = threading.Thread(
            target=self._background_loop, daemon=True, name="EvolveLoop"
        )
        self._thread.start()
        log.info("[EvolveEngine] Background evolution started (interval=%ds)",
                 self.evolution_interval)
        return True

    def stop_background_evolution(self) -> bool:
        """Stop the background evolution thread."""
        self.running = False
        log.info("[EvolveEngine] Background evolution stopped after %d iterations",
                 self.iteration)
        return True

    def _background_loop(self) -> None:
        """Background evolution loop."""
        while self.running:
            try:
                self.step()
            except Exception as exc:
                log.error("[EvolveEngine] Background step error: %s", exc)
            time.sleep(self.evolution_interval)

    # ──────────────────────────────────────────────
    # REFRESH REFERENCES
    # ──────────────────────────────────────────────

    def refresh_from_core(self) -> None:
        """Re-pull all module references from core (call after core is fully initialized)."""
        if not self.core:
            return
        self.researcher = getattr(self.core, "researcher", self.researcher)
        self.code_generator = getattr(self.core, "code_generator", self.code_generator)
        self.code_compiler = getattr(self.core, "code_compiler", self.code_compiler)
        self.software_studier = getattr(self.core, "software_studier", self.software_studier)
        self.self_teacher = getattr(self.core, "self_teacher", self.self_teacher)
        self.reflect = getattr(self.core, "reflect", self.reflect)
        self.idea_generator = getattr(self.core, "idea_generator", self.idea_generator)
        self.implementer = getattr(self.core, "self_implementer", self.implementer)
        self.knowledge_db = getattr(self.core, "db", self.knowledge_db)
        self.internet = getattr(self.core, "internet", self.internet)
        self.idea_implementation = getattr(self.core, "idea_implementation", self.idea_implementation)
        self.slsa = getattr(self.core, "slsa_engine", self.slsa)
        self.autonomous_engine = getattr(self.core, "autonomous_engine", self.autonomous_engine)
        self.live_updater = getattr(self.core, "live_updater", self.live_updater)
        self.file_manager = getattr(self.core, "file_manager", self.file_manager)
        log.info("[EvolveEngine] References refreshed from core")

    # ──────────────────────────────────────────────
    # STATUS
    # ──────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current evolution status."""
        available = {
            "researcher": bool(self.researcher),
            "code_generator": bool(self.code_generator),
            "code_compiler": bool(self.code_compiler),
            "software_studier": bool(self.software_studier),
            "self_teacher": bool(self.self_teacher),
            "reflect": bool(self.reflect),
            "idea_generator": bool(self.idea_generator),
            "implementer": bool(self.implementer),
            "knowledge_db": bool(self.knowledge_db),
            "internet": bool(self.internet),
            "idea_implementation": bool(self.idea_implementation),
            "slsa": bool(self.slsa),
            "autonomous_engine": bool(self.autonomous_engine),
            "live_updater": bool(self.live_updater),
            "file_manager": bool(self.file_manager),
        }
        return {
            "running": self.running,
            "iteration": self.iteration,
            "stats": self._stats,
            "available_modules": available,
            "history_count": len(self._history),
            "last_direction": self._history[-1]["direction"] if self._history else None,
            "deploy_path": str(self.deploy_path) if self.deploy_path else None,
        }

    def summarize_history(self) -> str:
        """Return a human-readable summary of recent evolution steps."""
        if not self._history:
            return "No evolution steps yet."
        lines = [f"🧬 **Evolution History (last {min(5, len(self._history))} steps):**\n"]
        for record in self._history[-5:]:
            lines.append(
                f"  Step {record['iteration']:3d} | {record['direction'][:35]:<35} | "
                f"{len(record['actions'])} actions"
            )
        lines.append(f"\n📊 Stats: {self._stats}")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# MODULE-LEVEL SINGLETON (backward compatible)
# ──────────────────────────────────────────────
engine = EvolveEngine()


def step():
    """Backward-compatible module-level step function."""
    return engine.step()


if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== EvolveEngine self-test ===\n")

    ev = EvolveEngine()
    result = ev.step()
    print(f"Step {result['iteration']}: direction={result['direction']}")
    print(f"Actions: {result['actions']}")
    print(f"\nStatus: {ev.get_status()}")
    print("\nEvolveEngine OK")
