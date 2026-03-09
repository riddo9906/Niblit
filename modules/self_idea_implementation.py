#!/usr/bin/env python3
# modules/self_idea_implementation.py — Upgraded with SLSA + persistent Niblit memory + SelfImplementer queue

from typing import List
from modules.self_researcher import SelfResearcher
from modules.self_implementer import SelfImplementer  # ✅ import queue engine
from datetime import datetime
import threading
import time
import logging

# ✅ SLSA generator
from slsa_generator_full import SLSAGenerator
# ✅ Niblit canonical memory
from niblit_memory import MemoryManager

log = logging.getLogger("SelfIdeaImpl")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s')


# ---------------------------------------------------
# GLOBAL MEMORY INSTANCE
# ---------------------------------------------------
GLOBAL_MEMORY = MemoryManager()


class SelfIdeaImplementation:
    """
    Implements ideas with:
    - Safe DB interactions
    - Autonomous execution
    - SLSA integration
    - Persistent Niblit memory logging
    - Auto queue to SelfImplementer
    """

    def __init__(self, db, implementer: SelfImplementer = None):
        self.db = db
        self.implementer = implementer  # ✅ reference to SelfImplementer instance
        registry = getattr(db, "runtime_registry", {}) if db else {}

        # -----------------------------
        # SelfResearcher init
        # -----------------------------
        try:
            self.researcher = SelfResearcher(db, modules_registry=registry)
        except Exception:
            self.researcher = SelfResearcher(db)

        # -----------------------------
        # SLSA generator init
        # -----------------------------
        self.slsa = None
        try:
            self.slsa = SLSAGenerator(interval=20, db_path="niblit.db")
            threading.Thread(target=self.slsa.run, daemon=True).start()
            log.info("SLSA Generator initialized and running.")
        except Exception as e:
            log.warning(f"SLSA initialization failed: {e}")

        # -----------------------------
        # Persistent memory
        # -----------------------------
        self.memory = GLOBAL_MEMORY

        # -----------------------------
        # Autonomous loop control
        # -----------------------------
        self.running = True

    # ============================================================
    # SAFE DB WRAPPERS
    # ============================================================

    def _safe_add_fact(self, key, value, tags=None):
        if not self.db:
            return
        try:
            self.db.add_fact(key, value, tags=tags or [])
            return
        except TypeError:
            pass
        try:
            self.db.add_fact(key, value)
            return
        except Exception:
            pass
        try:
            if hasattr(self.db, "insert"):
                self.db.insert(key, value)
        except Exception:
            pass

    def _safe_add_interaction(self, src, text):
        if not self.db:
            return
        try:
            if hasattr(self.db, "add_interaction"):
                self.db.add_interaction(src, text)
        except Exception:
            pass

    # ============================================================
    # IMPLEMENT IDEAS
    # ============================================================

    def implement_ideas(self, limit: int = 10) -> str:
        implemented = 0
        try:
            ideas = []
            if hasattr(self.db, "list_facts"):
                ideas = [
                    f for f in self.db.list_facts(500)
                    if f.get('key', '').startswith('idea:')
                    and 'implemented' not in (f.get('tags') or [])
                ]
            for item in ideas[:limit]:
                new_key = item['key'].replace('idea:', 'implemented:')
                self._safe_add_fact(
                    new_key,
                    item['value'],
                    tags=(item.get('tags') or []) + [
                        'implemented',
                        'auto_implemented',
                        'system_learning'
                    ]
                )
                # ✅ Memory logging
                self.memory.add_interaction(user_input=item['value'], response="Auto-implemented", source="self_idea")
                # ✅ Enqueue plan into SelfImplementer
                if self.implementer:
                    self.implementer.enqueue_plan(item['value'])
                implemented += 1
        except Exception:
            pass
        return f"Implemented {implemented} ideas into facts."

    def implement_idea(self, idea_prompt: str) -> str:
        idea_prompt = (idea_prompt or "").strip()
        if not idea_prompt:
            return self.implement_ideas()

        # -----------------------------
        # WEB + INTERNAL RESEARCH
        # -----------------------------
        research_results: List[str] = []
        try:
            raw = self.researcher.search(idea_prompt)
            for r in raw[:8]:
                if isinstance(r, dict):
                    research_results.append(r.get("summary") or r.get("text") or str(r))
                else:
                    research_results.append(str(r))
        except Exception:
            research_results = []

        # -----------------------------
        # BUILD IMPLEMENTATION PLAN
        # -----------------------------
        plan_lines = [
            f"Implementation plan for '{idea_prompt}':",
            f"Generated: {datetime.utcnow().isoformat()}",
            ""
        ]

        if research_results:
            for i, res in enumerate(research_results, 1):
                plan_lines.append(f"{i}. Integrate finding: {res}")
        else:
            plan_lines.append("No external findings; running internal brainstorming + SLSA integration.")

            # -----------------------------
            # SLSA HOOK
            # -----------------------------
            if self.slsa and hasattr(self.slsa.db, "list_facts"):
                slsa_artifacts = [
                    f["value"] for f in self.slsa.db.list_facts()
                    if f.get("tags") and "slsa" in f["tags"]
                ][:3]
                for a in slsa_artifacts:
                    concept = a.get("concept", "unknown")
                    snippet = a.get("definition") or a.get("extract") or "No detail"
                    plan_lines.append(f"Integrate SLSA artifact: {concept} → {snippet[:200]}")

        plan = "\n".join(plan_lines)

        # -----------------------------
        # STORE SAFELY + MEMORY LOGGING
        # -----------------------------
        try:
            self._safe_add_interaction("self_idea_implementation", plan)
            self._safe_add_fact(
                f"impl:{idea_prompt}",
                plan,
                tags=['implemented', 'idea_execution', 'system_learning']
            )
            # ✅ Persist plan in memory
            self.memory.add_interaction(user_input=idea_prompt, response=plan, source="self_idea")
            # ✅ Enqueue plan into SelfImplementer
            if self.implementer:
                self.implementer.enqueue_plan(plan)
        except Exception:
            pass

        return plan

    # ============================================================
    # AUTONOMOUS GENERATION
    # ============================================================

    def generate_and_implement(self, limit: int = 5) -> List[str]:
        results = []
        try:
            ideas_to_run = []
            if hasattr(self.db, "list_facts"):
                ideas_to_run = [
                    f.get("value") for f in self.db.list_facts(500)
                    if f.get('key', '').startswith('idea:')
                    and 'implemented' not in (f.get('tags') or [])
                ][:limit]

            for idea in ideas_to_run:
                plan = self.implement_idea(idea)
                results.append(plan)
                log.info(f"Auto-implemented idea: {idea}")

        except Exception as e:
            log.error(f"generate_and_implement error: {e}")

        return results

    # ============================================================
    # AUTONOMOUS LOOP
    # ============================================================

    def autonomous_loop(self, poll_interval: int = 180):
        while self.running:
            try:
                self.generate_and_implement(limit=3)
            except Exception as e:
                log.error(f"Autonomous loop error: {e}")
            time.sleep(poll_interval)

    # ============================================================
    # STOP LOOP
    # ============================================================

    def stop(self):
        self.running = False
        if self.slsa:
            self.slsa.stop()


# ---------------------------------------------------
if __name__ == "__main__":
    print('Running SelfIdeaImplementation with SLSA + persistent Niblit memory + SelfImplementer queue')
