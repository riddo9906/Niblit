#!/usr/bin/env python3
# modules/self_teacher.py

class SelfTeacher:
    def __init__(self, db, researcher=None, reflector=None, learner=None):
        self.db = db
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

        # Store learning in DB (unchanged logic)
        try:
            self.db.add_fact(
                f"learn:{topic}",
                summary,
                tags=["learn", "self-teach"]
            )
        except Exception:
            pass

        # Feed into learner (SelfIdeaImplementation) if available
        if self.learner:
            try:
                self.learner.learn(summary)
            except Exception:
                pass

        # Reflect AFTER storing (same behavior as before)
        if self.reflector:
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
