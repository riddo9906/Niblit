#!/usr/bin/env python3
# modules/self_teacher.py
"""SelfTeacher — teaches Niblit about topics via research + persistence.

All learning is stored in the canonical niblit_memory module so that
facts are available to every other subsystem.
"""
import json
import time
import threading

try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]

_REVIEW_QUEUE_KEY = "self_teacher:review_queue"
_MAX_INTERVAL_DAYS = 30.0
_SECONDS_PER_DAY = 86400.0


class SelfTeacher:
    def __init__(self, db=None, researcher=None, reflector=None, learner=None, llm=None):
        # Accept either a legacy KnowledgeDB/LocalDB *or* a NiblitMemory instance.
        # Fall back to the canonical GLOBAL_MEMORY singleton when nothing is passed.
        self.db = db or _GLOBAL_MEMORY
        self.researcher = researcher
        self.reflector = reflector
        self.learner = learner
        self.llm = llm

        # Recursion protection
        self._is_teaching = False

        # Spaced repetition review queue
        self._review_queue = []
        self._queue_lock = threading.Lock()
        self._load_review_queue()

    # ── Spaced repetition ──────────────────────────────────────────────────

    def _load_review_queue(self):
        try:
            if self.db and hasattr(self.db, "get_fact"):
                raw = self.db.get_fact(_REVIEW_QUEUE_KEY)
                if raw:
                    data = raw if isinstance(raw, list) else json.loads(raw)
                    with self._queue_lock:
                        self._review_queue = data
        except Exception:
            pass

    def _save_review_queue(self):
        try:
            if self.db and hasattr(self.db, "add_fact"):
                with self._queue_lock:
                    payload = list(self._review_queue)
                self.db.add_fact(_REVIEW_QUEUE_KEY, payload, tags=["self-teach", "review-queue"])
        except Exception:
            pass

    def schedule_for_review(self, topic):
        with self._queue_lock:
            for entry in self._review_queue:
                if entry.get("topic") == topic:
                    return
            self._review_queue.append({
                "topic": topic,
                "next_review": time.time() + _SECONDS_PER_DAY,
                "interval_days": 1.0,
                "repetitions": 0,
            })
        self._save_review_queue()

    def get_due_reviews(self, max_items=3):
        now = time.time()
        due = []
        with self._queue_lock:
            for entry in self._review_queue:
                if entry.get("next_review", float("inf")) <= now:
                    due.append(entry["topic"])
                if len(due) >= max_items:
                    break
        return due

    def _mark_reviewed(self, topic):
        with self._queue_lock:
            for entry in self._review_queue:
                if entry.get("topic") == topic:
                    new_interval = min(entry.get("interval_days", 1.0) * 2.0, _MAX_INTERVAL_DAYS)
                    entry["interval_days"] = new_interval
                    entry["next_review"] = time.time() + new_interval * _SECONDS_PER_DAY
                    entry["repetitions"] = entry.get("repetitions", 0) + 1
                    break
        self._save_review_queue()

    # ── LLM synthesis ──────────────────────────────────────────────────────

    def _synthesize_with_llm(self, topic, facts):
        if self.llm and hasattr(self.llm, "query_llm"):
            try:
                messages = [{"role": "user", "content": f"Summarize these facts about {topic} in 2-3 sentences: {facts}"}]
                result = self.llm.query_llm(messages, max_tokens=200)
                if result:
                    return str(result).strip()
            except Exception:
                pass
        joined = "; ".join(str(f) for f in facts) if isinstance(facts, list) else str(facts)
        return joined[:500]

    # ── Self-quiz generation ───────────────────────────────────────────────

    def _generate_quiz(self, topic, summary):
        if self.llm and hasattr(self.llm, "query_llm"):
            try:
                messages = [{"role": "user", "content": f"Generate one quiz question and answer about: {summary[:300]}. Format: Q: ... A: ..."}]
                raw = self.llm.query_llm(messages, max_tokens=150)
                if raw:
                    raw = str(raw)
                    q_part = ""
                    a_part = ""
                    if "Q:" in raw and "A:" in raw:
                        q_part = raw.split("Q:", 1)[1].split("A:", 1)[0].strip()
                        a_part = raw.split("A:", 1)[1].strip()
                    if q_part and a_part:
                        return {"question": q_part, "answer": a_part}
            except Exception:
                pass
        return {"question": f"What is {topic}?", "answer": summary[:200]}

    # ── Core teaching ──────────────────────────────────────────────────────

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

        summary = self._synthesize_with_llm(topic, learned) if learned else f"No external data found for {topic}"

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

            try:
                quiz = self._generate_quiz(topic, summary)
                if self.db and hasattr(self.db, "add_fact"):
                    self.db.add_fact(f"quiz:{topic}:{int(time.time())}", quiz, tags=["quiz", "self-teach"])
            except Exception:
                pass

            self.schedule_for_review(topic)

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

        return summary

    def teach_review(self, topic):
        if not topic:
            return "No topic provided for review-teach."

        if self._is_teaching:
            return "Teaching skipped (recursion protection)."

        self._is_teaching = True

        learned = []

        if self.researcher:
            try:
                learned = self.researcher.search(topic)
            except Exception:
                learned = []

        summary = self._synthesize_with_llm(topic, learned) if learned else f"No external data found for {topic}"

        if learned:
            try:
                if hasattr(self.db, "add_fact"):
                    self.db.add_fact(
                        f"learn:{topic}",
                        summary,
                        tags=["learn", "self-teach", "review"]
                    )
                elif hasattr(self.db, "store_learning"):
                    self.db.store_learning({"topic": topic, "summary": summary, "tags": ["learn", "self-teach", "review"]})
            except Exception:
                pass

            try:
                quiz = self._generate_quiz(topic, summary)
                if self.db and hasattr(self.db, "add_fact"):
                    self.db.add_fact(f"quiz:{topic}:{int(time.time())}", quiz, tags=["quiz", "self-teach", "review"])
            except Exception:
                pass

        if self.learner and learned:
            try:
                self.learner.learn(summary)
            except Exception:
                pass

        if self.reflector and learned:
            try:
                self.reflector.collect_and_summarize(
                    f"Review-learned about {topic}: {summary}"
                )
            except Exception:
                pass

        self._mark_reviewed(topic)

        with self._queue_lock:
            reps = next(
                (e.get("repetitions", 1) for e in self._review_queue if e.get("topic") == topic),
                1,
            )

        self._is_teaching = False

        return f"Review-teach completed for '{topic}' (rep #{reps})."


if __name__ == "__main__":
    print("Running self_teacher.py")

