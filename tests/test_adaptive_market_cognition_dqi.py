"""DQI must measure decision evidence, not reflection verbosity (Task 06).

The v1 reflection term was ``min(1, len(reflection.split()) / 40)``, so a longer
reflection raised the decision-quality index without any extra evidence. These
tests pin the v2 contract: the reflection term scores what the text *asserts*
against what the episode recorded, repetition and padding add nothing, and
unsupported claims cost credit.
"""
import json
from unittest.mock import patch

import pytest

from modules.adaptive_market_cognition import AdaptiveMarketCognitionLayer
from shared.governance_contract.memory_contracts import governed_recall_allowed

POLICY = AdaptiveMarketCognitionLayer._DQI_POLICY
SECTIONS = ("observed", "inferred", "predicted", "verified_outcome", "risk")


class _FakeCluster:
    def __init__(self):
        self.writes = []

    def write_memory(self, text, memory_type=None, payload=None):
        self.writes.append({"text": text, "memory_type": memory_type, "payload": dict(payload or {})})


def _record(layer, trace_id, **payload):
    cluster = _FakeCluster()
    target = "niblit_memory.governed_qdrant_memory.get_governed_qdrant_memory_cluster"
    with patch(target, return_value=cluster):
        record = layer.observe_event(
            "market_regime.forecast",
            "test",
            {"trace_id": trace_id, "symbol": "EURUSD", "regime": "bull", "evaluation_score": 0.5, **payload},
        )
    return record, cluster.writes


def _calm(**overrides):
    payload = {
        "volatility": 0.0,
        "drawdown": 0.0,
        "exposure": 0.0,
        "concentration_risk": 0.0,
        "uncertainty": 0.0,
    }
    payload.update(overrides)
    return payload


def _rebuild(layer, record, *, extra="", override=None):
    """Reassemble the record's own reflection sections, with optional padding."""
    sections = layer._reflection_sections(record["reflection"])
    sections.update(override or {})
    body = "; ".join(f"{tag}=[{sections[tag]}]{extra}" for tag in SECTIONS)
    return f"Market reflection for {record['topic']}: {body}."


def _score(layer, record, reflection):
    return layer._compute_dqi({**record, "reflection": reflection})


# --- policy versioning ------------------------------------------------------


def test_records_carry_the_new_policy_and_a_breakdown():
    layer = AdaptiveMarketCognitionLayer()
    record, writes = _record(layer, "policy-v2", volatility=0.4)
    status = layer.status()

    assert POLICY == "evidence-aware-v2"
    assert record["dqi_policy"] == status["dqi_policy"] == status["dqi_scores"][-1]["dqi_policy"] == POLICY
    assert status["dqi_policy_versions"] == {POLICY: 1}
    assert record["dqi_components"]["policy"] == POLICY
    assert record["dqi_components"]["score"] == record["dqi_score"]
    assert set(record["dqi_components"]["terms"]) == set(record["dqi_components"]["weights"])
    assert abs(sum(record["dqi_components"]["weights"].values()) - 1.0) < 1e-9
    for write in writes:
        assert write["payload"]["dqi_policy"] == POLICY
        assert write["payload"]["dqi_score"] == record["dqi_score"]
        assert write["payload"]["dqi_reasoning_quality"] == record["dqi_components"]["terms"]["reasoning"]


def test_legacy_scores_are_persisted_without_being_restamped_or_rescored(monkeypatch):
    writes = []
    target = "niblit_memory.governed_qdrant_memory.get_governed_qdrant_memory_cluster"

    class Cluster:
        def write_memory(self, text, *, memory_type, payload):
            writes.append(dict(payload))

    monkeypatch.setattr(target, lambda: Cluster())
    legacy = {
        "trace_id": "legacy-row",
        "topic": "synthetic",
        "regime": "bull",
        "volatility_regime": "unknown",
        "risk_score": 0.0,
        "risk_state": {"risk_evidence": {"state": "missing", "missing": ["volatility"]}},
        "dqi_score": 0.2935,
        "dqi_policy": "evidence-aware-v1",
        "reflection": "legacy word-count reflection " * 4,
        "outcome_state": {"label": "unknown"},
        "causal_chain": [],
    }
    AdaptiveMarketCognitionLayer()._persist_experience(legacy)

    assert [payload["dqi_policy"] for payload in writes] == ["evidence-aware-v1", "evidence-aware-v1"]
    assert [payload["dqi_score"] for payload in writes] == [0.2935, 0.2935]
    # No v2 reasoning term is invented for a record that was never scored with it.
    assert all(payload["dqi_reasoning_quality"] is None for payload in writes)


# --- verbosity neutrality ---------------------------------------------------


def test_identical_evidence_scores_the_same_short_and_long():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "verbosity", volatility=0.4)

    verbose = _rebuild(
        layer,
        record,
        extra=" and this sentence adds only prose about the very same recorded facts",
    )
    concise = (
        f"Market reflection for {record['topic']}: "
        f"observed=[evaluation_score={record['evaluation_score']}]; "
        "inferred=[regime_context=bull (assumed)]; "
        "predicted=[none]; "
        "verified_outcome=[none]; "
        f"risk={layer._reflection_sections(record['reflection'])['risk']}."
    )

    assert len(verbose.split()) > len(record["reflection"].split())
    assert len(concise.split()) < len(record["reflection"].split())
    assert "partial" in concise
    assert _score(layer, record, verbose) == record["dqi_score"]
    assert _score(layer, record, concise) == record["dqi_score"]
    assert record["dqi_components"]["terms"]["reasoning"] == 1.0


def test_repeating_the_reflection_does_not_raise_dqi():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "repeat", volatility=0.4)

    repeated = f"{record['reflection']} {record['reflection']}"
    assert _score(layer, record, repeated) == record["dqi_score"]

    tripled = " ".join([record["reflection"]] * 3)
    assert _score(layer, record, tripled) == record["dqi_score"]


def test_long_evidence_free_reflection_earns_no_reasoning_credit():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "junk", volatility=0.4)

    score, detail = layer._reasoning_quality(
        {**record, "reflection": "market looked fine and the trade was good " * 12},
        record["risk_state"],
    )
    assert score == 0.0
    assert detail["checks_passed"] == 0
    assert _score(layer, record, "x " * 400) < record["dqi_score"]


# --- unsupported statements -------------------------------------------------


def test_unsupported_prediction_lowers_dqi():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "fake-prediction", volatility=0.4)
    assert "none recorded for this episode" in record["reflection"]

    fabricated = _rebuild(
        layer, record, override={"predicted": "p(bull=0.9000) (recorded forecast, unverified)"}
    )
    assert _score(layer, record, fabricated) < record["dqi_score"]
    checks = layer._reasoning_quality({**record, "reflection": fabricated}, record["risk_state"])[1]["checks"]
    assert checks["predictions_separated"] is False


def test_unverified_outcome_cannot_be_described_as_verified():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "overclaim", volatility=0.4, realized_outcome=0.2)
    assert record["risk_state"]["risk_evidence"]["state"] == "partial"

    honest_checks = record["dqi_components"]["reasoning_evidence"]["checks"]
    assert honest_checks["outcomes_not_conflated"] is True

    overclaimed = _rebuild(layer, record, override={"verified_outcome": "0.2 (verified)"})
    assert _score(layer, record, overclaimed) < record["dqi_score"]
    assert (
        layer._reasoning_quality({**record, "reflection": overclaimed}, record["risk_state"])[1]["checks"][
            "outcomes_not_conflated"
        ]
        is False
    )


def test_verified_and_unverified_outcomes_stay_distinguishable():
    layer = AdaptiveMarketCognitionLayer()
    verified, _ = _record(layer, "verified", volatility=0.4, realized_outcome=0.2, outcome_verified=True)
    unverified, _ = _record(layer, "unverified", volatility=0.4, realized_outcome=0.2)

    assert "0.2 (verified)" in verified["reflection"]
    assert "verification unmarked" in unverified["reflection"]
    for record in (verified, unverified):
        assert record["dqi_components"]["reasoning_evidence"]["checks"]["outcomes_not_conflated"] is True
        assert record["dqi_components"]["terms"]["reasoning"] == 1.0


def test_missing_risk_evidence_cannot_be_reported_as_measured():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "fake-measured")
    assert record["risk_state"]["risk_evidence"]["state"] == "missing"

    fabricated = _rebuild(layer, record, override={"risk": "0.0000 (measured, 5/5 risk inputs)"})
    assert _score(layer, record, fabricated) < record["dqi_score"]
    checks = layer._reasoning_quality({**record, "reflection": fabricated}, record["risk_state"])[1]["checks"]
    assert checks["risk_evidence_reported"] is False


def test_missing_evidence_never_outscores_the_same_measured_evidence():
    layer = AdaptiveMarketCognitionLayer()
    missing, _ = _record(layer, "ordering-missing", confidence=0.5)
    partial, _ = _record(layer, "ordering-partial", confidence=0.5, volatility=0.0)
    complete, _ = _record(layer, "ordering-complete", confidence=0.5, **_calm())

    assert missing["dqi_score"] < partial["dqi_score"] < complete["dqi_score"]
    assert (
        missing["dqi_components"]["terms"]["risk_awareness"]
        < partial["dqi_components"]["terms"]["risk_awareness"]
        < complete["dqi_components"]["terms"]["risk_awareness"]
    )
    for record in (missing, partial, complete):
        assert record["dqi_components"]["terms"]["reasoning"] == 1.0


# --- invalid input ----------------------------------------------------------


def test_non_finite_and_invalid_inputs_stay_finite():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "invalid", volatility=0.4)

    for bad in (float("nan"), float("inf"), float("-inf")):
        score = layer._compute_dqi({**record, "reflection": record["reflection"]}, risk_credit=bad)
        assert 0.0 <= score <= 1.0
        assert score == score  # not NaN
    for reflection in (None, 42, float("nan"), ["observed=[0.5]"]):
        score = layer._compute_dqi({**record, "reflection": reflection})
        assert 0.0 <= score <= 1.0
    json.dumps(record["dqi_components"], allow_nan=False)

    snapshot = layer._dqi_snapshot(
        [
            {"latest": float("nan"), "dqi_policy": POLICY},
            {"latest": float("inf"), "dqi_policy": POLICY},
        ],
        [{"dqi_score": float("nan"), "dqi_policy": POLICY}],
    )
    assert snapshot["recent_average"] == 0.0
    assert snapshot["similar_average"] == 0.0
    json.dumps(snapshot, allow_nan=False)


# --- determinism ------------------------------------------------------------


def test_scoring_is_deterministic_across_repeated_evaluations():
    payload = {"volatility": 0.4, "drawdown": 0.2, "evaluation_score": 0.5, "confidence": 0.5}
    first, _ = _record(AdaptiveMarketCognitionLayer(), "deterministic", **payload)
    second, _ = _record(AdaptiveMarketCognitionLayer(), "deterministic", **payload)

    assert first["dqi_score"] == second["dqi_score"]
    assert first["dqi_components"]["terms"] == second["dqi_components"]["terms"]
    assert first["dqi_components"]["reasoning_evidence"] == second["dqi_components"]["reasoning_evidence"]

    layer = AdaptiveMarketCognitionLayer()
    assert layer._compute_dqi(first) == layer._compute_dqi(first) == first["dqi_score"]


# --- historical / retrieval snapshots ---------------------------------------


def test_legacy_scores_are_excluded_from_current_policy_averages():
    layer = AdaptiveMarketCognitionLayer()
    history = [
        {"latest": 0.90, "dqi_policy": "evidence-aware-v1"},
        {"latest": 0.10, "dqi_policy": "evidence-aware-v1"},
        {"latest": 0.60, "dqi_policy": POLICY},
        {"latest": 0.40, "dqi_policy": POLICY},
    ]
    snapshot = layer._dqi_snapshot(history, [{"dqi_score": 0.80, "dqi_policy": "evidence-aware-v1"}])

    assert snapshot["policy"] == POLICY
    assert snapshot["recent_average"] == pytest.approx(0.5)
    assert snapshot["latest"] == 0.4
    assert snapshot["latest_policy"] == POLICY
    assert snapshot["latest_is_current_policy"] is True
    assert snapshot["similar_average"] == pytest.approx(0.5)  # legacy similar record ignored
    assert snapshot["legacy_records_excluded"] == 2
    assert snapshot["legacy_similar_excluded"] == 1
    assert snapshot["policies"] == {"evidence-aware-v1": 2, POLICY: 2}


def test_a_purely_legacy_store_still_reports_its_scores():
    layer = AdaptiveMarketCognitionLayer()
    snapshot = layer._dqi_snapshot(
        [
            {"latest": 0.2, "dqi_policy": "evidence-aware-v1"},
            {"latest": 0.4, "dqi_policy": "evidence-aware-v1"},
        ],
        [],
    )
    assert snapshot["recent_average"] == pytest.approx(0.3)
    assert snapshot["latest_policy"] == "evidence-aware-v1"
    assert snapshot["latest_is_current_policy"] is False


def test_retrieval_bundle_exposes_the_scoring_policy():
    layer = AdaptiveMarketCognitionLayer()
    record, _writes = _record(layer, "bundle", volatility=0.4)
    bundle = layer.build_market_retrieval_bundle(query="bull regime view", core=None)

    assert bundle.dqi_snapshot["policy"] == POLICY
    assert bundle.dqi_snapshot["latest"] == round(record["dqi_score"], 4)
    assert bundle.dqi_snapshot["latest_is_current_policy"] is True
    assert "evidence-aware-v2" in bundle.context


# --- governed memory compatibility -----------------------------------------


def test_low_dqi_still_retrieves_through_governed_memory():
    layer = AdaptiveMarketCognitionLayer()
    record, writes = _record(layer, "governed", evaluation_score=0.0, confidence=0.0)
    assert record["dqi_score"] < 0.3

    for write in writes:
        payload = write["payload"]
        assert payload["dqi_policy"] == POLICY
        assert payload["coherence_score"] >= 0.3
        assert payload["coherence_score"] != payload["dqi_score"]
        assert governed_recall_allowed({**payload, "memory_type": write["memory_type"]})
        json.dumps(payload, allow_nan=False)
