#!/usr/bin/env python3
# modules/reflect.py

from datetime import datetime
import re

_default_instance = None


class ReflectModule:
    def __init__(self, db, self_teacher=None, learner=None):
        """
        db: database object
        self_teacher: optional SelfTeacher module
        learner: optional SelfIdeaImplementation module
        """
        self.db = db
        self.self_teacher = self_teacher
        self.learner = learner

    def collect_and_summarize(self, entry=None):
        if not entry:
            return "No reflection entry."

        ts = datetime.utcnow().isoformat()

        # ───────── SAVE REFLECTION ─────────
        try:
            if self.db:
                self.db.add_fact(f"reflect:{ts}", entry, tags=["reflect"])
        except Exception:
            pass

        # ───────── EXTRACT TOP THEMES ─────────
        words = [w.strip(".,!?") for w in entry.split() if len(w) > 3]
        top = sorted(set(words), key=lambda x: words.count(x), reverse=True)
        themes = ", ".join(top[:5])

        # ───────── FEED INTO SELF-TEACHER ─────────
        if self.self_teacher:
            try:
                self.self_teacher.teach(entry)
            except Exception:
                pass

        # ───────── FEED INTO LEARNER MODULE ─────────
        if self.learner:
            try:
                self.learner.learn(entry)
            except Exception:
                pass

        return f"Reflection saved. Themes: {themes}"

    def auto_reflect(self, recent_events):
        if not recent_events:
            return "Nothing to reflect on."

        text = " | ".join(recent_events[:5])
        return self.collect_and_summarize(f"System reflection: {text}")


# ───────── ROUTER COMPATIBILITY FUNCTION ─────────

def collect_and_summarize(entry=None, db=None):
    """
    Router-safe wrapper.
    Allows router to call reflect.collect_and_summarize(...)
    without crashing if db is not passed.
    """
    global _default_instance

    if _default_instance is None:
        _default_instance = ReflectModule(db)

    return _default_instance.collect_and_summarize(entry)


if __name__ == "__main__":
    print("Running reflect.py")
