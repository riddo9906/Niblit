#!/usr/bin/env python3
# modules/self_teacher.py
"""
SelfTeacher — Autonomous LLM-Driven Teaching, Review, and Quizzing for Niblit

Features:
- LLM-based topic synthesis ("teach back" for understanding)
- Spaced repetition review queue for self-improvement
- Self-quizzing to identify knowledge gaps
- Stores summaries and quizzes as KB facts for traceability
"""

import time
import random

try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]


class SelfTeacher:
    def __init__(self, db=None, researcher=None, reflector=None, learner=None, llm=None):
        self.db = db or _GLOBAL_MEMORY
        self.researcher = researcher
        self.reflector = reflector
        self.learner = learner
        self.llm = llm  # Should have an .ask_single(prompt) method
        self.review_queue = []  # For spaced repetition
        self.last_reviewed = {}  # topic -> last review timestamp
        self._is_teaching = False  # Recursion protection

    def teach(self, topic):
        if not topic:
            return "No topic provided for self-teach."
        if self._is_teaching:
            return "Teaching skipped (recursion protection)."

        self._is_teaching = True
        learned = []

        # Try to get recent facts via researcher or memory
        if self.researcher:
            try:
                learned = self.researcher.search(topic)
            except Exception:
                learned = []
        else:
            # Fallback: Get from our memory/DB
            learned = self._get_recent_facts(topic, limit=5)

        # Synthesize using LLM/brain, or use plain summary
        summary = ""
        if self.llm and learned:
            llm_prompt = (
                f"Synthesize a short, original explanation of '{topic}' using the following context:\n"
                + "\n".join(str(f)[:300] for f in learned)
            )
            try:
                summary = self.llm.ask_single(llm_prompt).strip()
            except Exception as e:
                summary = f"LLM error explaining {topic}: {e}"
        elif learned:
            summary = str(learned[0])[:400]
        else:
            summary = f"No external data found for {topic}"

        # Store learning summary/fact
        ts = int(time.time())
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(
                    f"self_teach_summary:{topic}:{ts}",
                    summary,
                    tags=["learn", "self-teach", topic]
                )
            elif hasattr(self.db, "store_learning"):
                self.db.store_learning({
                    "topic": topic, "summary": summary,
                    "tags": ["learn", "self-teach", topic]
                })
        except Exception:
            pass

        # Feed into learner, if available
        if self.learner and summary:
            try:
                self.learner.learn(summary)
            except Exception:
                pass

        # Reflect, if available
        if self.reflector and summary:
            try:
                self.reflector.collect_and_summarize(
                    f"Learned about {topic}: {summary}"
                )
            except Exception:
                pass

        # --- NEW: Spaced Repetition Scheduling ---
        self._add_to_review_queue(topic)
        self.last_reviewed[topic] = ts

        # --- NEW: Self-Quizzing ---
        quiz = None
        if self.llm and learned:
            quiz_prompt = (
                f"Create a quiz question (with answer) about '{topic}' using:\n"
                + "\n".join(str(f)[:200] for f in learned)
            )
            try:
                quiz = self.llm.ask_single(quiz_prompt).strip()
                self.db.add_fact(
                    f"self_teach_quiz:{topic}:{ts}",
                    quiz,
                    tags=["self_teach", "quiz", topic]
                )
            except Exception:
                pass

        self._is_teaching = False
        return f"Self-teach completed for '{topic}'. Summary: {summary}" + (f"\nQuiz: {quiz}" if quiz else "")

    # --- Optionally called in the ALE cycle to review old knowledge ---
    def spaced_review(self, count=1, min_interval=60 * 60 * 2):
        '''
        Review up to `count` topics from the review queue that have not been reviewed in `min_interval` seconds.
        Calls teach() for each.
        '''
        now = int(time.time())
        due = [t for t in self.review_queue if now - self.last_reviewed.get(t, 0) > min_interval]
        random.shuffle(due)
        results = []
        for t in due[:count]:
            results.append(self.teach(t))
        return results

    def _get_recent_facts(self, topic, limit=5):
        # Tries to use DB's list_facts; fallback is empty
        if hasattr(self.db, "search_facts"):
            try:
                facts = self.db.search_facts(topic, limit=limit) or []
                return facts
            except Exception:
                pass
        try:
            facts = getattr(self.db, "list_facts", lambda n: [])(30)
        except Exception:
            facts = []
        results = []
        for f in facts or []:
            if isinstance(f, dict) and topic.lower() in str(f.get("key", "")).lower():
                results.append(f)
            elif isinstance(f, dict) and topic.lower() in str(f.get("value", "")).lower():
                results.append(f)
            if len(results) >= limit:
                break
        return results

    def _add_to_review_queue(self, topic):
        if topic not in self.review_queue:
            self.review_queue.append(topic)


if __name__ == "__main__":
    print("Running upgraded self_teacher.py")
