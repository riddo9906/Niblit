# modules/idea_generator.py
import random

class IdeaGenerator:
    def __init__(self, db):
        self.db = db

    def generate(self, topic):
        # generate a few idea seeds using simple heuristics
        seeds = [
            f"Create an educational micro-course about {topic} targeted at beginners.",
            f"Build a lightweight monitoring dashboard that tracks {topic} trends.",
            f"Offer a data-driven newsletter with weekly insights on {topic}.",
            f"Prototype an automation that solves a repetitive problem in {topic} workflows.",
        ]
        chosen = random.sample(seeds, k=min(3,len(seeds)))
        # store ideas
        for i, s in enumerate(chosen):
            self.db.add_fact(f'idea:{topic}:{i+1}', s, tags=['idea','auto'])
        return '\n'.join(chosen)
