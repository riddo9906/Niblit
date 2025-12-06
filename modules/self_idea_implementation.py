#!/usr/bin/env python3
# modules/self_idea_implementation.py
from typing import List
from modules.self_researcher import SelfResearcher

class SelfIdeaImplementation:
    """Implements ideas, using self-researcher for guidance."""

    def __init__(self, db):
        self.db = db
        registry = getattr(db, "runtime_registry", {}) if db else {}
        try:
            self.researcher = SelfResearcher(db, modules_registry=registry)
        except Exception:
            self.researcher = SelfResearcher(db)

    def implement_ideas(self, limit: int = 10) -> str:
        """Find stored ideas and convert them into implemented facts (simple)."""
        implemented = 0
        try:
            ideas = []
            if hasattr(self.db, "list_facts"):
                ideas = [f for f in self.db.list_facts(500) if f.get('key','').startswith('idea:')]
            for i, item in enumerate(ideas[:limit]):
                k = item['key'].replace('idea:', 'implemented:')
                self.db.add_fact(k, item['value'], tags=item.get('tags', []) + ['implemented'])
                implemented += 1
        except Exception:
            pass
        return f"Implemented {implemented} ideas into facts."

    def implement_idea(self, idea_prompt: str) -> str:
        """
        Take an idea and research it, then provide an implementation plan.
        """
        idea_prompt = (idea_prompt or "").strip()
        if not idea_prompt:
            return self.implement_ideas()

        research_results: List[str] = []
        try:
            research_results = self.researcher.search(idea_prompt)[:8]
        except Exception:
            research_results = []

        plan_lines = [f"Implementation plan for '{idea_prompt}':"]
        if research_results:
            for i, res in enumerate(research_results, 1):
                plan_lines.append(f"{i}. Integrate finding: {res}")
        else:
            plan_lines.append("No external findings; run internal brainstorming and SLSA cycles.")

        plan = "\n".join(plan_lines)
        try:
            if hasattr(self.db, "add_interaction"):
                self.db.add_interaction("self_idea_implementation", plan)
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(f"impl:{idea_prompt}", plan, tags=['implemented'])
        except Exception:
            pass
        return plan
