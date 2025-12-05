# modules/slsa_generator.py
import random

class SLSAGenerator:
    def __init__(self, db):
        self.db = db

    def generate(self, topic="default", steps=4):
        steps_list = []
        for i in range(steps):
            steps_list.append(f"Step {i+1}: analyze -> plan -> implement for {topic}")
        out = "\n".join(steps_list)
        self.db.add_fact(f"slsa:{topic}", out, tags=['slsa'])
        return out
