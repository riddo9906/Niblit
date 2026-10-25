"""
modules/graded_curriculum.py
─────────────────────────────
Curriculum-based learning progression for Niblit, modelled on the education
system a person goes through from Grade 1 (basic facts) up to University
(self-directed, cross-domain synthesis).

Architecture
────────────
• GradeLevel  — dataclass describing a single grade (topics, passing score, …)
• GradeExam   — lightweight quiz that evaluates knowledge depth from KnowledgeDB
• GradedCurriculum — orchestrator; runs exams, advances grades, queues research

Integration
────────────
* Wired in niblit_core._init_optional_services() as self.graded_curriculum
* Router command: "curriculum <sub>" → _handle_curriculum()
* ALE/SelfTeacher teach topics from the *current* grade automatically
* Passing the exam for a grade unlocks the next grade's topics

CLI examples
────────────
  curriculum status          → show current grade and progress
  curriculum exam            → run the exam for the current grade right now
  curriculum topics          → list topics in the current grade
  curriculum advance         → manually advance grade (skip exam — for testing)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("NiblitCurriculum")

# ─────────────────────────────────────────────────────────────
# Grade definitions
# ─────────────────────────────────────────────────────────────

@dataclass
class GradeLevel:
    """A single grade (learning stage) with its curriculum topics and pass threshold."""

    name: str                           # e.g. "Grade 1", "University"
    level: int                          # 1 = lowest, 12+ = university
    topics: List[str]                   # research topics to study this grade
    passing_score: float = 0.6          # fraction of topics that need ≥ min_facts
    min_facts_per_topic: int = 2        # facts needed per topic to consider it "known"
    description: str = ""


# The full curriculum ladder.  Each grade's topics seed the KnowledgeDB learning
# queue; an "exam" checks how many of those topics have been researched
# sufficiently before advancing.
CURRICULUM: List[GradeLevel] = [
    GradeLevel(
        name="Grade 1", level=1,
        description="Basic world facts — colours, numbers, animals, shapes",
        topics=["primary colors", "counting numbers", "common animals", "basic shapes",
                "days of the week", "seasons of the year"],
        passing_score=0.6, min_facts_per_topic=1,
    ),
    GradeLevel(
        name="Grade 2", level=2,
        description="Reading and simple arithmetic",
        topics=["alphabet letters", "simple addition", "simple subtraction",
                "common words vocabulary", "telling time", "money basics"],
        passing_score=0.6, min_facts_per_topic=1,
    ),
    GradeLevel(
        name="Grade 3", level=3,
        description="Multiplication, basic science, geography",
        topics=["multiplication tables", "basic division", "plant life cycle",
                "water cycle", "continents and oceans", "weather patterns"],
        passing_score=0.6, min_facts_per_topic=2,
    ),
    GradeLevel(
        name="Grade 4", level=4,
        description="History, fractions, ecosystems",
        topics=["ancient civilizations", "fractions and decimals", "food chain",
                "states of matter", "human body systems", "map reading"],
        passing_score=0.65, min_facts_per_topic=2,
    ),
    GradeLevel(
        name="Grade 5", level=5,
        description="Algebra foundations, chemistry basics, world geography",
        topics=["basic algebra equations", "periodic table elements",
                "photosynthesis", "world history overview",
                "sentence structure grammar", "data and statistics"],
        passing_score=0.65, min_facts_per_topic=2,
    ),
    GradeLevel(
        name="Grade 6", level=6,
        description="Middle school: ratios, cell biology, world cultures",
        topics=["ratio and proportion", "cell biology", "genetics basics",
                "world religions overview", "literary devices", "probability"],
        passing_score=0.65, min_facts_per_topic=3,
    ),
    GradeLevel(
        name="Grade 7", level=7,
        description="Pre-algebra, earth science, civics",
        topics=["linear equations", "earth layers and tectonics",
                "chemical reactions", "government and democracy",
                "Shakespeare overview", "nutrition and health"],
        passing_score=0.7, min_facts_per_topic=3,
    ),
    GradeLevel(
        name="Grade 8", level=8,
        description="Algebra I, physics, history",
        topics=["quadratic equations", "Newton laws of motion",
                "electricity and magnetism", "industrial revolution",
                "essay writing techniques", "computer science basics"],
        passing_score=0.7, min_facts_per_topic=3,
    ),
    GradeLevel(
        name="Grade 9", level=9,
        description="High school — biology, geometry, literature",
        topics=["geometry theorems", "evolution and natural selection",
                "atomic theory", "world war history",
                "rhetoric and argumentation", "programming introduction"],
        passing_score=0.7, min_facts_per_topic=3,
    ),
    GradeLevel(
        name="Grade 10", level=10,
        description="Chemistry, trigonometry, economics",
        topics=["stoichiometry chemistry", "trigonometry functions",
                "supply and demand economics", "human genetics",
                "comparative literature", "data structures overview"],
        passing_score=0.75, min_facts_per_topic=3,
    ),
    GradeLevel(
        name="Grade 11", level=11,
        description="Pre-calculus, physics, psychology",
        topics=["calculus limits and derivatives", "thermodynamics",
                "psychology fundamentals", "organic chemistry",
                "statistics and probability advanced", "software engineering principles"],
        passing_score=0.75, min_facts_per_topic=4,
    ),
    GradeLevel(
        name="Grade 12", level=12,
        description="Calculus, advanced sciences, college preparation",
        topics=["integral calculus", "quantum mechanics introduction",
                "molecular biology", "macroeconomics",
                "philosophy of science", "algorithm design and complexity"],
        passing_score=0.75, min_facts_per_topic=4,
    ),
    GradeLevel(
        name="University", level=13,
        description="Self-directed, cross-domain synthesis and research",
        topics=["machine learning fundamentals", "distributed systems",
                "advanced mathematics proofs", "neuroscience overview",
                "ethical AI and alignment", "autonomous systems research",
                "knowledge synthesis methodology"],
        passing_score=0.8, min_facts_per_topic=5,
    ),
]

# Lookup map  level → GradeLevel
_GRADE_MAP: Dict[int, GradeLevel] = {g.level: g for g in CURRICULUM}
MAX_LEVEL = max(_GRADE_MAP)


# ─────────────────────────────────────────────────────────────
# GradeExam
# ─────────────────────────────────────────────────────────────

class GradeExam:
    """Evaluates whether Niblit has learned enough to pass the current grade.

    The exam queries KnowledgeDB (or the raw facts store) for facts associated
    with each topic in the grade.  A topic is "passed" if it has at least
    *min_facts_per_topic* stored facts.  The overall score is the fraction of
    topics passed; the grade is passed when the score ≥ *passing_score*.
    """

    def __init__(self, grade: GradeLevel, db: Any) -> None:
        self.grade = grade
        self.db = db

    def _count_facts_for_topic(self, topic: str) -> int:
        """Return how many stored facts are relevant to *topic*."""
        count = 0
        try:
            # KnowledgeDB.get_facts() returns a list of fact dicts
            if hasattr(self.db, "get_facts"):
                facts = self.db.get_facts() or []
                topic_lower = topic.lower()
                for fact in facts:
                    key = str(fact.get("key", "")).lower()
                    tags = [str(t).lower() for t in fact.get("tags", [])]
                    value = str(fact.get("value", "")).lower()
                    if (topic_lower in key
                            or any(topic_lower in t for t in tags)
                            or topic_lower in value):
                        count += 1
        except Exception as exc:
            log.debug("[GradeExam] fact count failed for %r: %s", topic, exc)
        return count

    def run(self) -> Dict[str, Any]:
        """Run the exam and return a result dict."""
        results: Dict[str, Any] = {
            "grade": self.grade.name,
            "level": self.grade.level,
            "topics_total": len(self.grade.topics),
            "topics_passed": 0,
            "topic_scores": {},
            "score": 0.0,
            "passed": False,
            "ts": time.time(),
        }
        if not self.grade.topics:
            results["passed"] = True
            results["score"] = 1.0
            return results

        for topic in self.grade.topics:
            count = self._count_facts_for_topic(topic)
            passed = count >= self.grade.min_facts_per_topic
            results["topic_scores"][topic] = {
                "facts_found": count,
                "required": self.grade.min_facts_per_topic,
                "passed": passed,
            }
            if passed:
                results["topics_passed"] += 1

        score = results["topics_passed"] / len(self.grade.topics)
        results["score"] = round(score, 3)
        results["passed"] = score >= self.grade.passing_score
        return results


# ─────────────────────────────────────────────────────────────
# GradedCurriculum
# ─────────────────────────────────────────────────────────────

class GradedCurriculum:
    """Orchestrates Niblit's education-system-style learning progression.

    Behaviour
    ─────────
    1. On startup, ensure the current grade's topics are all in the
       KnowledgeDB learning queue so background research will study them.
    2. Periodically (or on demand) run the grade exam.
    3. If the exam is passed, advance to the next grade and seed its topics.
    4. The cycle repeats until the University grade has been passed.

    State is persisted via KnowledgeDB facts with the key prefix
    "curriculum:".
    """

    _STATE_KEY = "curriculum:state"

    def __init__(
        self,
        db: Any,
        self_teacher: Optional[Any] = None,
        exam_interval_secs: int = 3600,   # run exam check every hour
        defer_teaching: bool = False,
    ) -> None:
        self.db = db
        self.self_teacher = self_teacher
        self.exam_interval_secs = exam_interval_secs
        self._defer_teaching = bool(defer_teaching)

        self._current_level: int = self._load_level()
        # Initialise to now so the first automatic exam runs after a full
        # interval rather than immediately on startup.
        self._last_exam_ts: float = time.time()
        self._exam_history: List[Dict[str, Any]] = []
        # Teaching is optional work and must never hold up Core readiness.
        # The process-level BackgroundJobManager is stopped by NiblitCore.
        self._teaching_lock = threading.Lock()
        self._teaching_cancel = threading.Event()
        self._scheduled_teaching_levels: set[int] = set()
        self._teaching_status: Dict[int, Dict[str, Any]] = {}

        log.info(
            "[GradedCurriculum] Initialized at %s",
            _GRADE_MAP.get(self._current_level, GradeLevel("?", 0, [])).name,
        )

    # ── persistence ──────────────────────────────────────────

    def _load_level(self) -> int:
        """Load current grade level from KnowledgeDB, default to 1."""
        try:
            if hasattr(self.db, "get_fact"):
                val = self.db.get_fact(self._STATE_KEY)
                if val and isinstance(val, dict) and "level" in val:
                    return int(val["level"])
        except Exception:
            pass
        return 1

    def _save_level(self) -> None:
        """Persist current level."""
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(
                    self._STATE_KEY,
                    {"level": self._current_level, "ts": time.time()},
                    tags=["curriculum", "state"],
                )
        except Exception as exc:
            log.debug("[GradedCurriculum] Save level failed: %s", exc)

    # ── topic seeding ─────────────────────────────────────────

    def _seed_grade_topics(self, grade: GradeLevel) -> None:
        """Queue grade topics immediately and schedule optional teaching once.

        Queueing is local and remains part of curriculum initialization. Research
        and self-teaching may use external providers, so that work is submitted
        to Core's managed background-job lifecycle rather than run inline.
        """
        log.info("[GradedCurriculum] Seeding topics for %s", grade.name)
        queue_errors = []
        for topic in grade.topics:
            try:
                if hasattr(self.db, "queue_learning"):
                    self.db.queue_learning(topic)
            except Exception as exc:
                queue_errors.append({"topic": topic, "error": str(exc)})
                log.exception("[GradedCurriculum] Failed to queue topic %r", topic)

        with self._teaching_lock:
            state = self._teaching_status.setdefault(grade.level, {})
            state["queued_topics"] = len(grade.topics) - len(queue_errors)
            state["queue_errors"] = queue_errors

        if self._defer_teaching:
            with self._teaching_lock:
                self._teaching_status[grade.level].setdefault("state", "deferred")
            return

        if not self.self_teacher or not hasattr(self.self_teacher, "teach"):
            with self._teaching_lock:
                self._teaching_status[grade.level].setdefault("state", "unavailable")
            return

        with self._teaching_lock:
            if grade.level in self._scheduled_teaching_levels:
                return
            self._scheduled_teaching_levels.add(grade.level)
            self._teaching_status[grade.level].update(
                state="scheduled", completed_topics=0, failed_topics=[]
            )

        try:
            from modules.background_jobs import bg_jobs

            bg_jobs.add(
                lambda: self._teach_grade_topics(grade),
                name=f"GradedCurriculum-Teach-Grade-{grade.level}",
                initial_delay=0.0,
            )
        except Exception as exc:
            with self._teaching_lock:
                self._teaching_status[grade.level].update(
                    state="failed", scheduling_error=str(exc)
                )
            log.exception(
                "[GradedCurriculum] Could not schedule teaching for %s", grade.name
            )

    def _teach_grade_topics(self, grade: GradeLevel) -> Dict[str, Any]:
        """Run SelfTeacher outside readiness and retain visible task status."""
        with self._teaching_lock:
            self._teaching_status[grade.level]["state"] = "running"
        failures = []
        unavailable = []
        completed = 0
        for topic in grade.topics:
            if self._teaching_cancel.is_set():
                break
            try:
                result = self.self_teacher.teach(topic)
                completed += 1
                # SelfTeacher intentionally converts an empty research result
                # into a user-facing message. Preserve that outcome in health
                # state instead of presenting it as successful ingestion.
                if isinstance(result, str) and result.startswith("No external data found"):
                    unavailable.append(topic)
            except Exception as exc:
                failures.append({"topic": topic, "error": str(exc)})
                log.exception(
                    "[GradedCurriculum] SelfTeacher failed for topic %r", topic
                )

        state = "cancelled" if self._teaching_cancel.is_set() else (
            "failed" if failures else "partial" if unavailable else "complete"
        )
        with self._teaching_lock:
            self._teaching_status[grade.level].update(
                state=state,
                completed_topics=completed,
                failed_topics=failures,
                unavailable_topics=unavailable,
            )
        if unavailable:
            log.warning(
                "[GradedCurriculum] Research returned no data for %d topic(s): %s",
                len(unavailable), unavailable,
            )
        return {
            "state": state,
            "completed_topics": completed,
            "failures": failures,
            "unavailable_topics": unavailable,
        }

    def shutdown(self) -> None:
        """Prevent queued curriculum teaching from starting more topics."""
        self._teaching_cancel.set()

    def start_teaching(self) -> None:
        """Release startup deferral and schedule learning under Core ownership."""
        self._defer_teaching = False
        self._seed_grade_topics(self.current_grade)

    # ── public API ────────────────────────────────────────────

    @property
    def current_grade(self) -> GradeLevel:
        return _GRADE_MAP.get(self._current_level, CURRICULUM[0])

    def status(self) -> Dict[str, Any]:
        """Return a status dict suitable for display."""
        grade = self.current_grade
        with self._teaching_lock:
            teaching = {
                level: dict(state) for level, state in self._teaching_status.items()
            }
        return {
            "current_grade": grade.name,
            "level": grade.level,
            "description": grade.description,
            "topics": grade.topics,
            "passing_score": grade.passing_score,
            "min_facts_per_topic": grade.min_facts_per_topic,
            "max_level": MAX_LEVEL,
            "last_exam_ts": self._last_exam_ts,
            "exam_history_count": len(self._exam_history),
            "teaching": teaching,
        }

    def run_exam(self) -> Dict[str, Any]:
        """Run the exam for the current grade and advance if passed."""
        grade = self.current_grade
        exam = GradeExam(grade, self.db)
        result = exam.run()
        self._last_exam_ts = result["ts"]
        self._exam_history.append(result)

        # Persist exam result
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(
                    f"curriculum:exam:{grade.level}:{int(result['ts'])}",
                    result,
                    tags=["curriculum", "exam", f"grade_{grade.level}"],
                )
        except Exception:
            pass

        if result["passed"] and grade.level < MAX_LEVEL:
            self._advance_grade()

        return result

    def _advance_grade(self) -> None:
        """Move up one grade level and seed the new topics."""
        old = self._current_level
        self._current_level = min(self._current_level + 1, MAX_LEVEL)
        self._save_level()
        new_grade = self.current_grade
        log.info(
            "[GradedCurriculum] 🎓 Advanced from level %d to %s!",
            old, new_grade.name,
        )
        self._seed_grade_topics(new_grade)

    def advance_manual(self) -> str:
        """Force-advance one grade (for testing / admin use)."""
        if self._current_level >= MAX_LEVEL:
            return f"Already at maximum level ({self.current_grade.name})"
        old_name = self.current_grade.name
        self._advance_grade()
        return f"Manually advanced: {old_name} → {self.current_grade.name}"

    def maybe_run_exam(self) -> Optional[Dict[str, Any]]:
        """Run the exam only if the exam interval has elapsed."""
        if time.time() - self._last_exam_ts >= self.exam_interval_secs:
            return self.run_exam()
        return None

    def start(self) -> None:
        """Seed the starting grade and schedule optional SelfTeacher work."""
        self._seed_grade_topics(self.current_grade)


# ─────────────────────────────────────────────────────────────
# Singleton factory
# ─────────────────────────────────────────────────────────────

_instance: Optional[GradedCurriculum] = None


def get_graded_curriculum(
    db: Optional[Any] = None,
    self_teacher: Optional[Any] = None,
    exam_interval_secs: int = 3600,
    defer_teaching: bool = False,
) -> Optional[GradedCurriculum]:
    """Return (and lazily create) the process-level GradedCurriculum singleton."""
    global _instance  # pylint: disable=global-statement
    if _instance is None and db is not None:
        _instance = GradedCurriculum(
            db=db,
            self_teacher=self_teacher,
            exam_interval_secs=exam_interval_secs,
            defer_teaching=defer_teaching,
        )
        _instance.start()
    elif _instance is not None:
        if self_teacher is not None:
            _instance.self_teacher = self_teacher
        if not defer_teaching and _instance._defer_teaching:
            _instance.start_teaching()
    return _instance


if __name__ == "__main__":
    print('Running graded_curriculum.py')
