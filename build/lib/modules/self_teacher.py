#!/usr/bin/env python3
# modules/self_teacher.py
"""SelfTeacher — Autonomous LLM-Driven Teaching, Review, and Quizzing for Niblit.

Features:
- LLM-based topic synthesis via query_llm
- Spaced repetition review queue (2x interval doubling, persisted to KB)
- Self-quizzing to identify knowledge gaps
- Stores summaries and quizzes as KB facts for traceability
"""

import json
import random
import threading
import time
from typing import List

try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]

_REVIEW_QUEUE_KEY = "self_teacher:review_queue"
_MAX_INTERVAL_DAYS = 30.0
_SECONDS_PER_DAY = 86400.0
# Minimum spaced-repetition interval: 6 hours. Below this, re-testing too
# quickly yields no meaningful retention benefit.
_MIN_REVIEW_INTERVAL_DAYS: float = 0.25


class SelfTeacher:
    def __init__(self, db=None, researcher=None, reflector=None, learner=None, llm=None):
        self.db = db or _GLOBAL_MEMORY
        self.researcher = researcher
        self.reflector = reflector
        self.learner = learner
        self.llm = llm

        self._is_teaching = False

        # Interval-based spaced repetition queue (persisted to KB)
        self._review_queue = []
        self._queue_lock = threading.Lock()
        self._load_review_queue()

        # Lightweight topic list + timestamp map (used by spaced_review() fallback)
        self.review_queue = []
        self.last_reviewed = {}

        # KnowledgeDigest: rewrites raw research in Niblit's own words before
        # storage (purely additive — created once, updated when self.llm changes)
        try:
            from modules.knowledge_digest import KnowledgeDigest as _KD
            self._knowledge_digest = _KD(llm=self.llm)
        except Exception:
            self._knowledge_digest = None  # type: ignore[assignment]

    # ── Spaced repetition (interval-based, persisted) ─────────────────────

    @staticmethod
    def _is_placeholder(result) -> bool:
        """Return True if *result* is a "No data found" placeholder string."""
        return isinstance(result, str) and result.strip().lower().startswith("no data found")

    def _filter_placeholders(self, results):
        """Remove placeholder "No data found" entries from a results list."""
        return [r for r in results if not self._is_placeholder(r)]

    def _load_review_queue(self):
        try:
            if self.db and hasattr(self.db, "get_fact"):
                raw = self.db.get_fact(_REVIEW_QUEUE_KEY)
                if raw:
                    # get_fact() returns the full fact dict {key, value, tags, ...};
                    # extract the stored list from the "value" field.
                    if isinstance(raw, dict):
                        data = raw.get("value", [])
                    elif isinstance(raw, list):
                        data = raw
                    else:
                        try:
                            data = json.loads(raw)
                        except Exception:
                            data = []
                    if isinstance(data, list):
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

        if self.researcher:
            try:
                learned = self.researcher.search(topic)
            except Exception:
                learned = []
        else:
            learned = self._get_recent_facts(topic, limit=5)

        # Discard placeholder "No data found" entries — they are not real knowledge
        learned = self._filter_placeholders(learned)

        summary = self._synthesize_with_llm(topic, learned) if learned else f"No external data found for {topic}"

        if learned:
            # Digest the summary into Niblit's own words before persisting
            # (purely additive: falls back to the cleaned summary when no LLM)
            try:
                if self._knowledge_digest is not None:
                    # Re-sync llm in case it was wired after __init__
                    self._knowledge_digest.llm = self.llm
                    summary = self._knowledge_digest.digest(topic, summary)
            except Exception:
                pass

            ts = int(time.time())
            try:
                if hasattr(self.db, "add_fact"):
                    self.db.add_fact(
                        f"self_teach_summary:{topic}:{ts}",
                        summary,
                        tags=["learn", "self-teach", topic]
                    )
                    # Update the per-topic learning ledger — single authoritative entry
                    # for this topic so recall always returns the latest digest.
                    self.db.add_fact(
                        f"topic_knowledge:{topic}",
                        summary,
                        tags=["knowledge", "ledger", topic]
                    )
                elif hasattr(self.db, "store_learning"):
                    self.db.store_learning({"topic": topic, "summary": summary, "tags": ["learn", "self-teach", topic]})
            except Exception:
                pass

        if learned:
            try:
                quiz = self._generate_quiz(topic, summary)
                if self.db and hasattr(self.db, "add_fact"):
                    self.db.add_fact(f"quiz:{topic}:{ts}", quiz, tags=["quiz", "self-teach"])
            except Exception:
                pass

            self.schedule_for_review(topic)
            self.last_reviewed[topic] = ts

        if self.learner and learned:
            try:
                self.learner.learn(summary)
            except Exception:
                pass

        if self.reflector and learned:
            try:
                self.reflector.collect_and_summarize(f"Learned about {topic}: {summary}")
            except Exception:
                pass

        # ── Additive: comprehension pass ─────────────────────────────────────
        # Extract concepts + schedule self-questions from what we just learned.
        # Runs after the reflector so the ledger is already primed; comprehension
        # either enriches it with concept structure or leaves it unchanged.
        if learned:
            try:
                from modules.knowledge_comprehension import get_knowledge_comprehension
                comp = get_knowledge_comprehension(
                    knowledge_db=self.db,
                    self_teacher=self,
                    llm=self.llm,
                )
                # Convert mixed result types to plain strings for the extractor
                snippets = [str(r) for r in learned if r]
                comp.process(topic, snippets)
            except Exception:
                pass

        self._is_teaching = False
        return f"Self-teach completed for '{topic}'."

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
        else:
            learned = self._get_recent_facts(topic, limit=5)

        # Discard placeholder "No data found" entries — they are not real knowledge
        learned = self._filter_placeholders(learned)

        summary = self._synthesize_with_llm(topic, learned) if learned else f"No external data found for {topic}"

        # Digest the summary into Niblit's own words before persisting
        # (purely additive: falls back to the cleaned summary when no LLM)
        if learned:
            try:
                if self._knowledge_digest is not None:
                    self._knowledge_digest.llm = self.llm
                    summary = self._knowledge_digest.digest(topic, summary)
            except Exception:
                pass

        if learned:
            try:
                if hasattr(self.db, "add_fact"):
                    self.db.add_fact(
                        f"self_teach_summary:{topic}:{int(time.time())}",
                        summary,
                        tags=["learn", "self-teach", "review"]
                    )
                    # Update the per-topic learning ledger with the refreshed digest.
                    self.db.add_fact(
                        f"topic_knowledge:{topic}",
                        summary,
                        tags=["knowledge", "ledger", topic, "review"]
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
        due = self.get_due_reviews(max_items=count)
        if not due:
            due = [t for t in self.review_queue if now - self.last_reviewed.get(t, 0) > min_interval]
            random.shuffle(due)
            due = due[:count]
        results = []
        for t in due:
            results.append(self.teach_review(t))
        return results

    # ── Self-test (active recall) ──────────────────────────────────────────

    def self_test(self, max_items: int = 3) -> str:
        """Execute active-recall tests for due quiz questions.

        This closes the spaced-repetition loop: instead of only *storing*
        quiz questions, Niblit now attempts to *answer* them by looking up
        its own knowledge base and then scores the answer.

        For each due quiz:
        1. Retrieve the stored answer from the KB (``quiz:<question>`` fact).
        2. Attempt an answer using ``think_about(question)`` (KB synthesis).
        3. Score the attempted answer against the known correct answer using
           the RewardModel.
        4. If score ≥ 0.6  → mark reviewed (double the interval), reinforce
           the underlying KB facts.
        5. If score <  0.6  → shrink the review interval (re-test sooner),
           queue the topic for re-research via quality_feedback.

        Returns a short summary string for the ALE cycle log.
        """
        if not self.db:
            return "[SelfTest] No knowledge DB — skipped."

        due_questions = self.get_due_reviews(max_items=max_items)
        if not due_questions:
            return "[SelfTest] No questions due for review."

        # Lazy-load helpers
        _rm = None
        try:
            from modules.reward_model import get_reward_model
            _rm = get_reward_model()
        except Exception:
            pass

        _qf = None
        try:
            from modules.quality_feedback import get_quality_feedback
            _qf = get_quality_feedback(reward_model=_rm)
        except Exception:
            pass

        passed = 0
        failed = 0
        retried: List[str] = []

        for question in due_questions:
            try:
                # 1. Look up the stored answer (from quiz generation)
                known_answer = self._find_quiz_answer(question)

                # 2. Attempt answer from KB synthesis
                if hasattr(self.db, "think_about"):
                    attempted = self.db.think_about(question)
                elif hasattr(self.db, "smart_recall"):
                    facts = self.db.smart_recall(question, limit=5) or []
                    attempted = " ".join(
                        str(f.get("value", "")) for f in facts if isinstance(f, dict)
                    )[:600]
                else:
                    attempted = ""

                if not attempted or attempted.startswith("["):
                    # No KB knowledge to test against — re-queue immediately
                    self._shorten_review_interval(question)
                    failed += 1
                    retried.append(question)
                    continue

                # 3. Score: use known_answer as the "gold" context when available
                snippets = [known_answer] if known_answer else []
                score = 0.5
                if _rm is not None:
                    try:
                        score = float(_rm.score(question, attempted, snippets))
                    except Exception:
                        pass

                # 4. Update intervals + propagate quality feedback
                if score >= 0.60:
                    self._mark_reviewed(question)
                    if _qf is not None:
                        _qf.record_answer_quality(
                            query=question,
                            answer=attempted,
                            knowledge_db=self.db,
                            snippets=snippets,
                        )
                    passed += 1
                    log.debug(
                        "[SelfTest] PASS (%.2f) %r — interval doubled",
                        score, question[:60],
                    )
                else:
                    self._shorten_review_interval(question)
                    if _qf is not None:
                        _qf.record_answer_quality(
                            query=question,
                            answer=attempted,
                            knowledge_db=self.db,
                            snippets=snippets,
                        )
                    failed += 1
                    retried.append(question)
                    log.debug(
                        "[SelfTest] FAIL (%.2f) %r — interval halved, re-queued",
                        score, question[:60],
                    )

            except Exception as exc:
                log.debug("[SelfTest] error on %r: %s", question, exc)
                failed += 1

        summary = f"[SelfTest] {passed} passed, {failed} failed"
        if retried:
            summary += f" (re-queued: {retried[:3]})"
        log.info("%s", summary)
        return summary

    def _find_quiz_answer(self, question: str) -> str:
        """Look up the stored answer for a quiz question.

        Returns the answer string or an empty string when not found.
        """
        if not self.db or not hasattr(self.db, "list_facts"):
            return ""
        try:
            facts = self.db.list_facts(limit=500) or []
            prefix = f"quiz:{question}:"
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                key = str(fact.get("key", ""))
                if key.startswith(prefix) or key == f"quiz:{question}":
                    value = fact.get("value")
                    if isinstance(value, dict):
                        return str(value.get("answer", ""))
                    return str(value)[:400]
        except Exception:
            pass
        return ""

    def _shorten_review_interval(self, topic: str) -> None:
        """Halve the review interval so a failed topic is retested sooner."""
        now = time.time()
        with self._queue_lock:
            for entry in self._review_queue:
                if entry.get("topic") == topic:
                    old = float(entry.get("interval_days", 1.0))
                    entry["interval_days"] = max(_MIN_REVIEW_INTERVAL_DAYS, old / 2.0)
                    entry["next_review"] = now + entry["interval_days"] * _SECONDS_PER_DAY
                    break
        self._save_review_queue()


if __name__ == "__main__":
    print("Running upgraded self_teacher.py")
