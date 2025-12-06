#!/usr/bin/env python3
# modules/self_teacher.py
from modules.self_researcher import SelfResearcher

class SelfTeacher:
    def __init__(self, db):
        self.db = db
        registry = getattr(db, "runtime_registry", {}) if db else {}
        try:
            self.researcher = SelfResearcher(db, modules_registry=registry)
        except Exception:
            self.researcher = SelfResearcher(db)

    def generate_lessons(self, limit=5):
        interactions = []
        try:
            interactions = self.db.recent_interactions(200)
        except Exception:
            interactions = []
        lessons = []
        for it in reversed(interactions):
            if it.get('role') == 'user' and len(lessons) < limit:
                excerpt = it.get('text', '')[:240]
                key = f"lesson:{len(lessons)+1}"
                try:
                    self.db.add_fact(key, excerpt, tags=['lesson'])
                except Exception:
                    pass
                lessons.append(excerpt)
        return f"Generated {len(lessons)} internal lessons."

    def teach(self, topic: str, limit=5):
        """
        Produce a small set of 'lessons' about a topic using internet research and internal interactions.
        """
        topic = (topic or "").strip()
        if not topic:
            return self.generate_lessons(limit)

        results = []
        try:
            results = self.researcher.search(topic, max_results=limit)
        except Exception:
            results = []

        lessons = []
        for i, r in enumerate(results[:limit], 1):
            lesson = f"Lesson {i}: {r}"
            key = f"lesson:{topic}:{i}"
            try:
                self.db.add_fact(key, lesson, tags=['lesson','external'])
            except Exception:
                pass
            lessons.append(lesson)
        return f"Generated {len(lessons)} lessons for '{topic}'."
