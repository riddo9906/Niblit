# modules/self_healer.py
import time

class SelfHealer:
    def __init__(self, db):
        self.db = db

    def repair(self):
        repaired = 0
        facts = self.db.list_facts(500)
        for f in facts:
            if f.get('value') is None or str(f.get('value')).strip()=='':
                self.db.add_fact(f['key'], '[REPAIRED EMPTY FACT]', tags=f.get('tags',[]))
                repaired += 1
        return f"Repaired {repaired} broken or empty facts."
