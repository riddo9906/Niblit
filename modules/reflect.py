#!/usr/bin/env python3
# modules/reflect.py
from datetime import datetime

class ReflectModule:
    def __init__(self, db):
        self.db = db

    def collect_and_summarize(self, entry: str = None):
        """
        If entry is None -> prompt interactive input().
        Otherwise accept provided entry (non-interactive).
        Saves a brief summary to the DB.
        """
        try:
            if entry is None:
                entry = input('Reflection (type a short journal entry): ').strip()
        except Exception:
            entry = (entry or "").strip()

        if not entry:
            return 'No entry recorded.'
        ts = datetime.utcnow().isoformat()
        try:
            self.db.add_fact(f'reflect:{ts}', entry, tags=['reflect'])
        except Exception:
            pass
        # naive summary: top words
        words = [w.strip('.,!?') for w in entry.split() if len(w) > 3]
        top = sorted(set(words), key=lambda w: -words.count(w))[:5]
        summary = f"Saved reflection at {ts}. Top themes: {', '.join(top[:5])}"
        return summary

    def summarize_text(self, text, max_sentences=3):
        # ultra-simple summarizer: take first few sentences
        import re
        if not text:
            return ""
        sents = re.split(r'(?<=[.!?])\s+', text)
        return " ".join(sents[:max_sentences]).strip()
