"""Phase 5V regressions for non-blocking curriculum startup and readiness."""

from contextlib import contextmanager

import pytest

from modules import graded_curriculum as curriculum_module
from modules.graded_curriculum import GradedCurriculum
from niblit_core import NiblitCore


class FakeDB:
    def __init__(self):
        self.queued = []

    def get_fact(self, _key):
        return None

    def queue_learning(self, topic):
        self.queued.append(topic)


class FakeJobs:
    def __init__(self):
        self.jobs = []

    def add(self, fn, **kwargs):
        self.jobs.append((fn, kwargs))
        return object()


class FakeTeacher:
    def __init__(self, *, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def teach(self, topic):
        self.calls.append(topic)
        if topic == self.fail_on:
            raise TimeoutError("controlled provider timeout")
        return f"taught {topic}"


def test_curriculum_queues_topics_without_blocking_on_teacher(monkeypatch):
    db, teacher, jobs = FakeDB(), FakeTeacher(), FakeJobs()
    monkeypatch.setattr(curriculum_module, "_instance", None)
    monkeypatch.setattr("modules.background_jobs.bg_jobs", jobs)
    curriculum = GradedCurriculum(db, teacher)

    curriculum.start()

    assert db.queued == curriculum.current_grade.topics
    assert teacher.calls == []
    assert len(jobs.jobs) == 1
    assert jobs.jobs[0][1]["name"] == "GradedCurriculum-Teach-Grade-1"
    # Core schedules teaching after optional initialization completes, so no
    # startup delay is needed here. The task itself remains background-owned.
    assert jobs.jobs[0][1]["initial_delay"] == 0.0
    assert curriculum.status()["teaching"][1]["state"] == "scheduled"


def test_curriculum_teaching_is_once_per_grade_and_remains_functional(monkeypatch):
    db, teacher, jobs = FakeDB(), FakeTeacher(), FakeJobs()
    monkeypatch.setattr("modules.background_jobs.bg_jobs", jobs)
    curriculum = GradedCurriculum(db, teacher)

    curriculum.start()
    curriculum.start()
    result = jobs.jobs[0][0]()

    assert len(jobs.jobs) == 1
    assert teacher.calls == curriculum.current_grade.topics
    assert result["state"] == "complete"
    assert result["completed_topics"] == len(curriculum.current_grade.topics)
    assert curriculum.status()["teaching"][1]["state"] == "complete"


def test_core_can_defer_curriculum_teaching_until_optional_init_finishes(monkeypatch):
    db, teacher, jobs = FakeDB(), FakeTeacher(), FakeJobs()
    monkeypatch.setattr("modules.background_jobs.bg_jobs", jobs)
    curriculum = GradedCurriculum(db, teacher, defer_teaching=True)

    curriculum.start()
    assert db.queued == curriculum.current_grade.topics
    assert jobs.jobs == []
    assert curriculum.status()["teaching"][1]["state"] == "deferred"

    curriculum.start_teaching()
    curriculum.start_teaching()

    assert len(jobs.jobs) == 1
    assert jobs.jobs[0][1]["initial_delay"] == 0.0
    assert jobs.jobs[0][0]()["state"] == "complete"


def test_curriculum_reports_teacher_failures_and_continues(monkeypatch, caplog):
    db = FakeDB()
    grade = curriculum_module.CURRICULUM[0]
    teacher = FakeTeacher(fail_on=grade.topics[0])
    jobs = FakeJobs()
    monkeypatch.setattr("modules.background_jobs.bg_jobs", jobs)
    curriculum = GradedCurriculum(db, teacher)

    curriculum.start()
    result = jobs.jobs[0][0]()

    assert len(teacher.calls) == len(grade.topics)
    assert result["state"] == "failed"
    assert result["failures"] == [{"topic": grade.topics[0], "error": "controlled provider timeout"}]
    assert curriculum.status()["teaching"][1]["state"] == "failed"
    assert "SelfTeacher failed" in caplog.text


def test_curriculum_marks_empty_research_as_partial_health(monkeypatch, caplog):
    class EmptyResearchTeacher:
        def teach(self, _topic):
            return "No external data found for topic"

    jobs = FakeJobs()
    monkeypatch.setattr("modules.background_jobs.bg_jobs", jobs)
    curriculum = GradedCurriculum(FakeDB(), EmptyResearchTeacher())
    curriculum.start()

    result = jobs.jobs[0][0]()

    assert result["state"] == "partial"
    assert result["unavailable_topics"] == curriculum.current_grade.topics
    assert curriculum.status()["teaching"][1]["unavailable_topics"] == curriculum.current_grade.topics
    assert "Research returned no data" in caplog.text


def test_curriculum_shutdown_cancels_before_next_topic(monkeypatch):
    db, teacher, jobs = FakeDB(), FakeTeacher(), FakeJobs()
    monkeypatch.setattr("modules.background_jobs.bg_jobs", jobs)
    curriculum = GradedCurriculum(db, teacher)
    curriculum.start()
    curriculum.shutdown()

    result = jobs.jobs[0][0]()

    assert teacher.calls == []
    assert result["state"] == "cancelled"
    assert curriculum.status()["teaching"][1]["state"] == "cancelled"


def test_curriculum_schedule_failure_is_visible(monkeypatch):
    class BrokenJobs:
        def add(self, *_args, **_kwargs):
            raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("modules.background_jobs.bg_jobs", BrokenJobs())
    curriculum = GradedCurriculum(FakeDB(), FakeTeacher())

    curriculum.start()

    assert curriculum.status()["teaching"][1]["state"] == "failed"
    assert curriculum.status()["teaching"][1]["scheduling_error"] == "scheduler unavailable"


class _Report:
    def summary(self):
        return {"ready": 1, "degraded": 1}


def _core_for_readiness(phase="complete", failures=None, optional="degraded"):
    core = object.__new__(NiblitCore)
    core._deferred_init_phase = phase
    core._deferred_init_event = __import__("threading").Event()
    core._essential_init_event = __import__("threading").Event()
    core._essential_init_failures = list(failures or [])
    core._essential_ready = phase != "failed" and not failures
    core._optional_init_status = optional
    core.startup_report = _Report()
    if phase in {"complete", "failed"}:
        core._deferred_init_event.set()
    if core._essential_ready or phase == "failed":
        core._essential_init_event.set()
    return core


def test_wait_for_ready_means_essential_ready_optional_health_is_separate():
    core = _core_for_readiness()

    assert core.wait_for_ready(timeout=0)
    assert core.wait_for_ready(timeout=0)
    assert core.readiness_status() == {
        "initialization": "complete",
        "essential_ready": True,
        "essential_failures": [],
        "optional_services": "degraded",
        "component_health": {"ready": 1, "degraded": 1},
    }


def test_wait_for_ready_is_false_after_essential_failure():
    core = _core_for_readiness(phase="failed", failures=["2-AI-Adapters"])

    assert not core.wait_for_ready(timeout=0)
    assert not core.readiness_status()["essential_ready"]


def test_wait_for_ready_can_succeed_while_optional_layer_is_running():
    core = _core_for_readiness(phase="running", optional="initializing")

    assert core.wait_for_ready(timeout=0)
    assert core.readiness_status()["initialization"] == "running"
    assert core.readiness_status()["optional_services"] == "initializing"


def test_initialize_modules_does_not_continue_after_essential_failure():
    class NullLogger:
        @contextmanager
        def context(self, _name):
            yield

    core = object.__new__(NiblitCore)
    core.logger = NullLogger()
    core._essential_init_failures = []
    core._essential_init_event = __import__("threading").Event()
    core._essential_ready = False
    core._optional_init_status = "pending"
    core._deferred_init_phase = "running"
    core._INIT_LAYER5_TIMEOUT_DEFAULT = 0.1
    core._push_init_progress = lambda _message: None
    core._init_vector_store = lambda: None
    core._init_ai_adapters = lambda: None
    core._init_brain_and_router = lambda: None
    core._init_learning_systems = lambda: None
    core._init_system_services = lambda: None
    core._init_optional_services = lambda: pytest.fail("optional services must not start")
    core._verify_unified_loop = lambda: None

    calls = []

    def run_layer(fn, name, timeout=0):
        calls.append(name)
        if name == "2-AI-Adapters":
            return False
        fn()
        return True

    core._init_with_timeout = run_layer

    with pytest.raises(RuntimeError, match="Essential initialization failed"):
        NiblitCore._initialize_modules(core)

    assert "2-AI-Adapters" in core._essential_init_failures
    assert core.wait_for_ready(timeout=0) is False
    assert "5-Optional" not in calls


def test_optional_layer_failure_keeps_essential_readiness_true():
    class NullLogger:
        @contextmanager
        def context(self, _name):
            yield

    core = object.__new__(NiblitCore)
    core.logger = NullLogger()
    core._essential_init_failures = []
    core._essential_init_event = __import__("threading").Event()
    core._essential_ready = False
    core._optional_init_status = "pending"
    core._deferred_init_phase = "running"
    core._INIT_LAYER5_TIMEOUT_DEFAULT = 0.1
    core._push_init_progress = lambda _message: None
    core._init_vector_store = lambda: None
    core._init_ai_adapters = lambda: None
    core._init_brain_and_router = lambda: None
    core._init_learning_systems = lambda: None
    core._init_system_services = lambda: None
    core._init_optional_services = lambda: (_ for _ in ()).throw(RuntimeError("optional failure"))
    core._verify_unified_loop = lambda: None

    def run_layer(fn, _name, timeout=0):
        try:
            fn()
            return True
        except RuntimeError:
            return False

    core._init_with_timeout = run_layer
    NiblitCore._initialize_modules(core)

    assert core.wait_for_ready(timeout=0) is True
    assert core.readiness_status()["essential_ready"] is True
    assert core.readiness_status()["optional_services"] == "failed"
