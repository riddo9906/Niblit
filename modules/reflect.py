# modules/reflect.py
from datetime import datetime

class ReflectModule:
    def __init__(self, db):
        self.db = db

    def collect_and_summarize(self):
        # ask user for a short journal entry, store it, and produce a tiny summary
        entry = input('Reflection (type a short journal entry): ').strip()
        if not entry:
            return 'No entry recorded.'
        ts = datetime.utcnow().isoformat()
        self.db.add_fact(f'reflect:{ts}', entry, tags=['reflect'])
        # naive summary: store first sentence and top words
        words = [w.strip('.,!?') for w in entry.split() if len(w)>3]
        top = sorted(set(words), key=lambda w: -words.count(w))[:5]
        summary = f"Saved reflection at {ts}. Top themes: {', '.join(top[:5])}"
        return summary
