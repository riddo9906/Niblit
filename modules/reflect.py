#!/usr/bin/env python3
# modules/reflect.py

from datetime import datetime
import re
import json
import logging

log = logging.getLogger("ReflectModule")

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
        """
        Auto-reflect on recent events/interactions.
        Keeps all original logic but fixes the dict-to-string conversion issue.
        
        Args:
            recent_events: List of recent events (can be dicts or strings)
        """
        if not recent_events:
            return "Nothing to reflect on."
        
        # ✅ FIX: Convert dicts to strings safely
        events_text = []
        for event in recent_events:
            try:
                if isinstance(event, dict):
                    # Extract text from dict - try multiple fields
                    if event.get("input"):
                        events_text.append(str(event["input"]))
                    elif event.get("response"):
                        events_text.append(str(event["response"]))
                    elif event.get("event"):
                        events_text.append(str(event["event"]))
                    else:
                        # Fallback: convert dict to short JSON string
                        events_text.append(json.dumps(event)[:100])
                else:
                    # Already a string
                    events_text.append(str(event))
            except Exception:
                pass
        
        if not events_text:
            return "Nothing to reflect on."
        
        # ✅ Original logic preserved: join and summarize
        text = " | ".join(events_text[:5])
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
