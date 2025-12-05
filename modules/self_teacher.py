# modules/self_teacher.py
class SelfTeacher:
    def __init__(self, db):
        self.db = db

    def generate_lessons(self, limit=5):
        interactions = self.db.recent_interactions(200)
        lessons = []
        for it in reversed(interactions):
            if it['role']=='user' and len(lessons) < limit:
                excerpt = it['text'][:240]
                key = f"lesson:{len(lessons)+1}"
                self.db.add_fact(key, excerpt, tags=['lesson'])
                lessons.append(excerpt)
        return f"Generated {len(lessons)} internal lessons."
