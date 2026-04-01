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

_REVIEW_QUEUE_KEY = "self_teacher:review_queue"
_MAX_INTERVAL_DAYS = 30.0
_SECONDS_PER_DAY = 86400.0


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

        # Interval-based spaced repetition queue (persisted to KB)
        self._review_queue = []
        self._queue_lock = threading.Lock()
        self._load_review_queue()

        # Lightweight topic list + timestamp map (used by spaced_review())
        self.review_queue = []
        self.last_reviewed = {}

    # ── Spaced repetition (interval-based, persisted) ─────────────────────

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
        self._add_to_review_queue(topic)

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
        now = time.time()
        with self._queue_lock:
            for entry in self._review_queue:
                if entry.get("topic") == topic:
                    new_interval = min(entry.get("interval_days", 1.0) * 2.0, _MAX_INTERVAL_DAYS)
                    entry["interval_days"] = new_interval
                    entry["next_review"] = now + new_interval * _SECONDS_PER_DAY
                    entry["repetitions"] = entry.get("repetitions", 0) + 1
                    break
        self.last_reviewed[topic] = int(now)
        self._save_review_queue()

    def _add_to_review_queue(self, topic):
        if topic not in self.review_queue:
            self.review_queue.append(topic)

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

    # ── Fact retrieval fallback ────────────────────────────────────────────

    def _get_recent_facts(self, topic, limit=5):
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

    # ── Core teaching ──────────────────────────────────────────────────────

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
            learned = self._get_recent_facts(topic, limit=5)

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
                self.reflector.collect_and_summarize(
                    f"Learned about {topic}: {summary}"
                )
            except Exception:
                pass

        if self.reflector and learned:
            try:
                self.reflector.collect_and_summarize(f"Review-learned about {topic}: {summary}")
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

    def spaced_review(self, count=1, min_interval=60 * 60 * 2):
        """Review up to `count` topics due for review.

        Uses teach_review() for each due topic so that interval tracking and
        quiz generation are applied consistently.  `min_interval` (seconds) is
        used as a fallback guard when the interval-based queue has no entries.
        """
        now = int(time.time())
        # First try interval-based queue; fall back to timestamp-based list
        due = self.get_due_reviews(max_items=count)
        if not due:
            due = [t for t in self.review_queue if now - self.last_reviewed.get(t, 0) > min_interval]
            random.shuffle(due)
            due = due[:count]
        results = []
        for t in due:
            results.append(self.teach_review(t))
        return results


if __name__ == "__main__":
    print("Running upgraded self_teacher.py")
