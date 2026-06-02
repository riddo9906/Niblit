from __future__ import annotations

from pathlib import Path

from modules.unified_runtime import NiblitUnifiedRuntime


def test_hypothesis_events_do_not_reenter_hypothesis_engine(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")

    before = len(rt.hypothesis_engine.list_hypotheses())

    rt.ingest_external_event(
        event_type="trade_reflection.ingested",
        source="lean_algo_manager",
        payload={
            "trace_id": "loop-guard-trace-1",
            "topic": "loop guard check",
            "summary": "initial external event",
            "confidence_score": 0.51,
        },
    )

    after_external = len(rt.hypothesis_engine.list_hypotheses())
    assert after_external >= before + 1

    rt.ingest_external_event(
        event_type="hypothesis.created",
        source="HypothesisEngine",
        payload={
            "trace_id": "loop-guard-trace-2",
            "topic": "internal hypothesis event",
            "summary": "should not be re-ingested",
        },
    )

    after_internal = len(rt.hypothesis_engine.list_hypotheses())
    assert after_internal == after_external
