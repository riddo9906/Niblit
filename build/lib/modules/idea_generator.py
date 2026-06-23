#!/usr/bin/env python3
# modules/idea_generator.py
import random
from typing import List
from modules.self_researcher import SelfResearcher

class IdeaGenerator:
    """Generates ideas, optionally using online research."""

    def __init__(self, db):
        self.db = db
        # prefer registry-provided researcher if possible
        registry = getattr(db, "runtime_registry", {}) if db else {}
        try:
            # pass registry to researcher so it can reuse InternetManager if present
            self.researcher = SelfResearcher(db, modules_registry=registry)
        except Exception:
            self.researcher = SelfResearcher(db)

    def generate(self, prompt: str) -> str:
        """Primary method used by niblit_core: generate(topic)."""
        return self.generate_idea(prompt)

    def generate_idea(self, prompt: str) -> str:
        """
        Generate an idea based on the prompt.
        Can fetch data from the Internet for richer ideas.
        Returns a single idea string (keeps output compact).
        """
        prompt = (prompt or "").strip() or "general"
        research_data: List[str] = []
        try:
            research_data = self.researcher.search(prompt)[:5]
        except Exception:
            research_data = []

        base_ideas = [
            f"Create a tutorial series about '{prompt}' aimed at beginners.",
            f"Develop a lightweight monitoring dashboard that tracks '{prompt}' trends.",
            f"Offer a data-driven micro-newsletter with weekly insights on '{prompt}'.",
            f"Prototype an automation that solves a repetitive problem around '{prompt}'.",
        ]

        # mix in research-driven seeds
        seeds = list(base_ideas)
        for rd in research_data[:3]:
            seeds.append(f"Based on research: {rd.split('.')[0]}")

        idea = random.choice(seeds)
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(f"idea:{prompt.lower()}", idea, tags=['idea','auto'])
            elif hasattr(self.db, "add_interaction"):
                self.db.add_interaction("idea_generator", idea)
        except Exception:
            pass
        return idea
if __name__ == "__main__":
    print('Running idea_generator.py')
