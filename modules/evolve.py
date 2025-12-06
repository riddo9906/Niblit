#!/usr/bin/env python3
# modules/evolve.py
"""
Evolve module: small orchestration to run a self-improvement cycle.
It is intentionally conservative: it collects short research, generates ideas,
attempts one implementation plan and stores a lesson. Designed to be safe.
"""
from typing import Optional

class Evolve:
    def __init__(self, db):
        self.db = db

    def run_cycle(self, topic: Optional[str] = None):
        topic = (topic or "self-improvement").strip()
        out = []
        # 1) research
        try:
            researcher = (getattr(self.db, "runtime_registry", {}) or {}).get("self_researcher")
            if not researcher:
                # try to create one dynamically if modules available in registry
                researcher = (getattr(self.db, "runtime_registry", {}) or {}).get("self_researcher")
            if researcher and hasattr(researcher, "search"):
                results = researcher.search(topic, max_results=4)
            else:
                results = []
        except Exception:
            results = []

        out.append(f"Research snippets: {len(results)}")

        # 2) idea generation (if available)
        try:
            ig = (getattr(self.db, "runtime_registry", {}) or {}).get("idea_generator")
            if ig and hasattr(ig, "generate"):
                idea = ig.generate(topic)
            else:
                idea = f"Propose small improvement for {topic}."
        except Exception as e:
            idea = f"[idea error] {e}"
        out.append(f"Idea: {idea}")

        # 3) implementation plan (best-effort)
        try:
            impl = (getattr(self.db, "runtime_registry", {}) or {}).get("self_idea_implementation")
            if impl and hasattr(impl, "implement_idea"):
                plan = impl.implement_idea(topic)
            else:
                plan = "No implementer available."
        except Exception as e:
            plan = f"[implement error] {e}"
        out.append(f"Plan: {plan.splitlines()[0]}")

        # 4) generate a lesson
        try:
            teacher = (getattr(self.db, "runtime_registry", {}) or {}).get("self_teacher")
            if teacher and hasattr(teacher, "teach"):
                lesson = teacher.teach(topic, limit=1)
            else:
                lesson = "No teacher available."
        except Exception as e:
            lesson = f"[teach error] {e}"
        out.append(f"Lesson: {str(lesson)[:200]}")

        # persist small summary
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(f"evolve:{topic}", "\n".join(out), tags=['evolve'])
        except Exception:
            pass

        return "\n".join(out)
