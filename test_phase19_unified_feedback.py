from __future__ import annotations

import sys
import types


def test_quality_feedback_score_override_and_status():
    from modules.quality_feedback import QualityFeedback

    qf = QualityFeedback()
    result = qf.record_answer_quality(
        query="hello",
        answer="hi there",
        knowledge_db=None,
        score_override=0.8,
    )

    assert result["score"] == 0.8
    assert result["verdict"] == "good"

    status = qf.status()
    assert status["total_scores"] == 1
    assert status["recent_avg_score"] == 0.8
    assert status["verdict_counts"]["good"] == 1


def test_adaptive_learning_routes_feedback_into_quality_loop():
    from modules.adaptive_learning import AdaptiveLearning

    calls = {}

    class DummyQF:
        def record_answer_quality(self, **kwargs):
            calls.update(kwargs)
            return {"score": kwargs.get("score_override", 0.5)}

    class DummyDB:
        pass

    al = AdaptiveLearning(knowledge_db=DummyDB(), quality_feedback=DummyQF())
    al.record_feedback("what is AI?", "AI is machine intelligence.", 4)

    assert calls["query"] == "what is AI?"
    assert calls["answer"] == "AI is machine intelligence."
    assert calls["knowledge_db"] is not None
    assert calls["score_override"] == 0.8


def test_adaptive_learning_can_skip_quality_feedback_propagation():
    from modules.adaptive_learning import AdaptiveLearning

    called = {"count": 0}

    class DummyQF:
        def record_answer_quality(self, **kwargs):
            called["count"] += 1
            return {"score": kwargs.get("score_override", 0.5)}

    al = AdaptiveLearning(knowledge_db=object(), quality_feedback=DummyQF())
    al.record_feedback("hello", "hi", 4, propagate_quality=False)

    assert called["count"] == 0


def test_niblit_learning_stores_quality_aware_entries_and_evolves():
    from niblit_learning import NiblitLearning

    class DummyMemory:
        def __init__(self):
            self.log = []
            self.prefs = {}

        def store_learning(self, entry):
            self.log.append(entry)

        def get_learning_log(self):
            return list(self.log)

        def store_preferences(self, prefs):
            self.prefs = prefs

    mem = DummyMemory()
    learning = NiblitLearning(mem)

    learning.process_interaction(
        "How does memory work?",
        "Memory works by storing structured facts.\n- recall\n- reinforce",
        quality_score=0.7,
        feedback_score=0.9,
        chosen_advisor="memory",
    )
    learning.process_interaction(
        "thanks this is good",
        "Glad it helped.",
        quality_score=0.8,
        feedback_score=0.8,
        chosen_advisor="quality",
    )

    assert len(mem.log) == 2
    assert mem.log[0]["learning_type"] == "interaction_feedback"
    assert mem.log[0]["interaction_quality"] == 0.8
    assert mem.log[0]["chosen_advisor"] == "memory"

    prefs = learning.evolve()
    assert prefs is not None
    assert prefs["interactions"] == 2
    assert prefs["avg_interaction_quality"] >= 0.79
    assert "feedback_loop_coherence" in prefs
    assert mem.prefs["interactions"] == 2


def test_system_health_monitor_reads_runtime_status_from_public_apis(monkeypatch):
    import nibblebots.system_health_monitor as shm

    fake_eval = types.SimpleNamespace(
        status=lambda: {"avg_quality": 0.73},
        get_history=lambda: [],
        last_quality_score=lambda: 0.73,
    )
    fake_qf = types.SimpleNamespace(
        status=lambda: {"recent_avg_score": 0.61, "total_scores": 4}
    )

    monkeypatch.setitem(
        sys.modules,
        "modules.evaluation_engine",
        types.SimpleNamespace(get_evaluation_engine=lambda: fake_eval),
    )
    monkeypatch.setitem(
        sys.modules,
        "modules.quality_feedback",
        types.SimpleNamespace(get_quality_feedback=lambda: fake_qf),
    )

    assert shm._get_evaluation_engine_score() == 0.73
    assert shm._get_quality_feedback_score() == 0.61


def test_niblit_core_trigger_learning_closes_loop(monkeypatch):
    from niblit_core import NiblitCore

    class DummyAE:
        def __init__(self):
            self.called = 0

        def record_user_activity(self):
            self.called += 1

    class DummyTasks:
        def __init__(self):
            self.items = []

        def add_task(self, name, payload):
            self.items.append((name, payload))

    class DummyLearning:
        def __init__(self):
            self.kwargs = None
            self.evolved = 0

        def process_interaction(self, **kwargs):
            self.kwargs = kwargs

        def evolve(self):
            self.evolved += 1

    class DummyEval:
        def last_quality_score(self):
            return 0.71

        def get_history(self):
            return [{"chosen_advisor": "llm"}]

        def status(self):
            return {"avg_quality": 0.71}

    class DummyQF:
        def __init__(self):
            self.calls = 0

        def record_answer_quality(self, **kwargs):
            self.calls += 1
            return {"score": 0.83}

        def status(self):
            return {"recent_avg_score": 0.83, "total_scores": 1}

    class DummyAdaptiveLearning:
        def __init__(self):
            self.calls = []
            self.learning_strategy = "balanced"
            self.feedback_history = []

        def record_feedback(self, **kwargs):
            self.calls.append(kwargs)
            self.feedback_history.append({"satisfaction": kwargs.get("satisfaction", 3)})

        def get_recommended_topics(self, count=3):
            return ["memory", "reasoning"][:count]

    qf = DummyQF()

    monkeypatch.setitem(
        sys.modules,
        "modules.quality_feedback",
        types.SimpleNamespace(get_quality_feedback=lambda: qf),
    )

    core = NiblitCore.__new__(NiblitCore)
    core.autonomous_engine = DummyAE()
    core.learning = DummyLearning()
    core.tasks = DummyTasks()
    core.db = object()
    core.evaluation_engine = DummyEval()
    core.adaptive_learning = DummyAdaptiveLearning()
    core.brain = object()
    core._unified_loop_status = {}

    core._refresh_unified_feedback_status = NiblitCore._refresh_unified_feedback_status.__get__(core, NiblitCore)
    core._trigger_learning = NiblitCore._trigger_learning.__get__(core, NiblitCore)

    core._trigger_learning("hi", "hello")

    assert core.autonomous_engine.called == 1
    assert core.learning.evolved == 1
    assert core.tasks.items
    assert core.learning.kwargs["quality_score"] == 0.71
    assert core.learning.kwargs["feedback_score"] == 0.83
    assert core.learning.kwargs["chosen_advisor"] == "llm"
    assert core._unified_loop_status["recent_loop_quality"] == 0.77
    assert len(core.adaptive_learning.calls) == 1
    assert core.adaptive_learning.calls[0]["propagate_quality"] is False
    assert qf.calls == 1
    assert core._unified_loop_status["adaptive_learning"]["feedback_count"] == 1
