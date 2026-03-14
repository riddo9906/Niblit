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

import time
import random
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("EvolveEngine")

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
    ):
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
        }

        log.info("[EvolveEngine] Initialized")

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
        research_result = self._research_direction(direction)
        if research_result:
            record["actions"].append(f"researched: {research_result[:60]}")

        # Step 2: Direct internet research (no LLM, raw web data)
        internet_result = self._internet_direct_research(direction)
        if internet_result:
            record["actions"].append(f"internet: {internet_result[:60]}")

        # Step 3: Research code patterns from internet → feed CodeGenerator
        code_research_result = self._research_code_direction(direction)
        if code_research_result:
            record["actions"].append(f"code_research: {code_research_result[:60]}")

        # Step 4: Study relevant software patterns
        study_result = self._study_patterns(direction)
        if study_result:
            record["actions"].append(f"studied: {study_result[:60]}")

        # Step 5: Generate code for the improvement
        code_result = self._generate_improvement_code(direction)
        if code_result:
            record["actions"].append(f"code_gen: {code_result[:60]}")
            record["mutations"].append(code_result)

        # Step 6: Teach myself what I learned
        teach_result = self._teach_improvement(direction, research_result)
        if teach_result:
            record["actions"].append(f"taught: {teach_result[:60]}")

        # Step 7: Reflect on the improvement
        reflect_result = self._reflect_on_step(direction, record)
        if reflect_result:
            record["actions"].append(f"reflected: {str(reflect_result or '')[:60]}")

        # Step 8: Generate and implement an idea via idea_implementation
        impl_result = self._implement_evolution_idea(direction, research_result)
        if impl_result:
            record["actions"].append(f"implemented: {impl_result[:60]}")

        # Step 9: Generate an implementation plan via idea_generator
        idea_result = self._generate_idea(direction)
        if idea_result:
            record["actions"].append(f"idea: {idea_result[:60]}")

        # Step 10: Run a SLSA semantic knowledge cycle
        slsa_result = self._run_slsa_cycle(direction)
        if slsa_result:
            record["actions"].append(f"slsa: {slsa_result[:60]}")

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
        }
        return {
            "running": self.running,
            "iteration": self.iteration,
            "stats": self._stats,
            "available_modules": available,
            "history_count": len(self._history),
            "last_direction": self._history[-1]["direction"] if self._history else None,
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
