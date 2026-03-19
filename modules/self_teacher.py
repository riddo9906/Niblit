#!/usr/bin/env python3
# modules/self_teacher.py
"""SelfTeacher — teaches Niblit about topics via research + persistence.

All learning is stored in the canonical niblit_memory module so that
facts are available to every other subsystem.
"""
try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]


class SelfTeacher:
    def __init__(self, db=None, researcher=None, reflector=None, learner=None):
        # Accept either a legacy KnowledgeDB/LocalDB *or* a NiblitMemory instance.
        # Fall back to the canonical GLOBAL_MEMORY singleton when nothing is passed.
        self.db = db or _GLOBAL_MEMORY
        self.researcher = researcher
        self.reflector = reflector
        self.learner = learner

        # Recursion protection
        self._is_teaching = False

    def teach(self, topic):
        if not topic:
            return "No topic provided for self-teach."

        # 🔒 Prevent reflect <-> teach infinite loop
        if self._is_teaching:
            return "Teaching skipped (recursion protection)."

        self._is_teaching = True

        learned = []

        if self.researcher:
            try:
                learned = self.researcher.search(topic)
            except Exception:
                learned = []

        summary = ""
        if learned:
            summary = learned[0]
        else:
            summary = f"No external data found for {topic}"

        # Store learning in memory — skip when no real data was found
        if learned:
            try:
                if hasattr(self.db, "add_fact"):
                    self.db.add_fact(
                        f"learn:{topic}",
                        summary,
                        tags=["learn", "self-teach"]
                    )
                elif hasattr(self.db, "store_learning"):
                    self.db.store_learning({"topic": topic, "summary": summary, "tags": ["learn", "self-teach"]})
            except Exception:
                pass

        # Feed into learner (SelfIdeaImplementation) if available — skip on no data
        if self.learner and learned:
            try:
                self.learner.learn(summary)
            except Exception:
                pass

        # Reflect AFTER storing (same behavior as before) — skip on no data
        if self.reflector and learned:
            try:
                self.reflector.collect_and_summarize(
                    f"Learned about {topic}: {summary}"
                )
            except Exception:
                pass

        self._is_teaching = False

        return f"Self-teach completed for '{topic}'."


if __name__ == "__main__":
    print("Running self_teacher.py")

