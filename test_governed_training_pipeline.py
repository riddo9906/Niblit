"""test_governed_training_pipeline.py — Validation suite for the governed
adaptive cognition training pipeline (Phases 3, 5, 7, 8).

Covers:
- TrainingDatasetGovernance: submit, approve, reject, dedup, rollback, eviction
- GovernedTrainingPipeline: disabled gate, per-stage results, full run
- ALE hook: _run_governed_training_pipeline smoke-test
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_candidate(
    prompt: str = "What is X?",
    response: str = "X is a thing.",
    score: float = 0.75,
    source: str = "test",
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "response": response,
        "evaluation_score": score,
        "source_subsystem": source,
        "trace_id": str(uuid.uuid4()),
    }


# ══════════════════════════════════════════════════════════════════════════════
# TrainingDatasetGovernance tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTrainingDatasetGovernance:
    """Tests for modules/training_dataset_governance.py"""

    def _make_governance(self, tmp_path: Path):
        """Return a fresh governance instance pointing at a tmp dir."""
        from modules.training_dataset_governance import TrainingDatasetGovernance
        gov = TrainingDatasetGovernance()
        gov._dataset_path = tmp_path / "dataset.jsonl"
        gov._rollback_dir = tmp_path / "rollbacks"
        gov._seen_hashes = set()
        gov._loaded_hashes = True  # skip lazy load
        return gov

    def test_submit_approves_high_score(self, tmp_path):
        gov = self._make_governance(tmp_path)
        candidates = [_make_candidate(score=0.80)]
        report = gov.submit_batch(candidates, source_subsystem="test")
        assert report.approved == 1
        assert report.committed == 1
        assert report.rejected_quality == 0

    def test_submit_rejects_low_score(self, tmp_path):
        """Samples below the quality floor are rejected."""
        gov = self._make_governance(tmp_path)
        # Temporarily lower the threshold check by patching the module constant.
        with patch("modules.training_dataset_governance._MIN_QUALITY", 0.70):
            candidates = [_make_candidate(score=0.40)]
            report = gov.submit_batch(candidates)
        assert report.approved == 0
        assert report.rejected_quality == 1

    def test_deduplication_blocks_exact_duplicate(self, tmp_path):
        """Submitting the same prompt twice should only commit once."""
        gov = self._make_governance(tmp_path)
        c = _make_candidate(prompt="Unique prompt for dedup test.", score=0.80)
        r1 = gov.submit_batch([c])
        r2 = gov.submit_batch([c])  # exact duplicate
        assert r1.committed == 1
        assert r2.rejected_duplicate == 1
        assert r2.committed == 0

    def test_hallucination_check_rejects_flagged_text(self, tmp_path):
        """Samples with a pre-set high hallucination_score are quarantined."""
        gov = self._make_governance(tmp_path)
        # Directly set hallucination_score above the 0.5 threshold so the
        # governance layer quarantines this record regardless of the heuristic.
        c = _make_candidate(score=0.80)
        c["hallucination_score"] = 0.90
        report = gov.submit_batch([c])
        assert report.rejected_hallucination >= 1

    def test_load_approved_returns_committed_records(self, tmp_path):
        gov = self._make_governance(tmp_path)
        for i in range(5):
            gov.submit_batch([_make_candidate(
                prompt=f"Question {i}?", response=f"Answer {i}.", score=0.80
            )])
        records = gov.load_approved(limit=10)
        assert len(records) == 5
        assert all(r.approved for r in records)

    def test_rollback_removes_batch(self, tmp_path):
        """Rolling back a batch_id removes those records from the dataset."""
        gov = self._make_governance(tmp_path)
        report = gov.submit_batch(
            [_make_candidate(prompt="Rollback me?", score=0.80)]
        )
        batch_id = report.batch_id
        assert report.committed == 1

        success = gov.rollback_batch(batch_id)
        assert success is True
        records = gov.load_approved(limit=10)
        assert all(r.rollback_batch_id != batch_id for r in records)

    def test_rollback_nonexistent_batch_returns_false(self, tmp_path):
        gov = self._make_governance(tmp_path)
        assert gov.rollback_batch("nonexistent-batch-id") is False

    def test_evict_stale_removes_old_records(self, tmp_path):
        """Records older than the retention window are evicted."""
        from modules.training_dataset_governance import DatasetRecord
        gov = self._make_governance(tmp_path)

        # Write one old and one fresh record directly.
        old_rec = DatasetRecord(
            prompt="Old question?",
            response="Old answer.",
            evaluation_score=0.80,
            approved=True,
            timestamp=time.time() - (35 * 86400),  # 35 days ago
        )
        new_rec = DatasetRecord(
            prompt="New question?",
            response="New answer.",
            evaluation_score=0.80,
            approved=True,
            timestamp=time.time(),
        )
        with gov._dataset_path.open("w") as fh:
            fh.write(json.dumps(old_rec.to_dict()) + "\n")
            fh.write(json.dumps(new_rec.to_dict()) + "\n")

        with patch("modules.training_dataset_governance._RETENTION_DAYS", 30):
            evicted = gov.evict_stale()
        assert evicted == 1
        records = gov.load_approved()
        assert len(records) == 1
        assert records[0].prompt == "New question?"

    def test_status_returns_expected_keys(self, tmp_path):
        gov = self._make_governance(tmp_path)
        status = gov.status()
        for key in ("record_count", "min_quality_score", "deduplication_enabled",
                    "rollback_enabled", "total_submitted", "total_approved"):
            assert key in status

    def test_dataset_record_from_dict_roundtrip(self):
        from modules.training_dataset_governance import DatasetRecord
        rec = DatasetRecord(
            prompt="p", response="r",
            evaluation_score=0.85, approved=True,
            ale_cycle_id=7, provider_used="llama3",
        )
        d = rec.to_dict()
        rec2 = DatasetRecord.from_dict(d)
        assert rec2.prompt == rec.prompt
        assert rec2.evaluation_score == rec.evaluation_score
        assert rec2.ale_cycle_id == rec.ale_cycle_id

    def test_empty_batch_returns_zero_counts(self, tmp_path):
        gov = self._make_governance(tmp_path)
        report = gov.submit_batch([])
        assert report.submitted == 0
        assert report.committed == 0

    def test_missing_prompt_or_response_skipped(self, tmp_path):
        gov = self._make_governance(tmp_path)
        report = gov.submit_batch([{"prompt": "", "response": "", "evaluation_score": 0.9}])
        assert report.committed == 0


# ══════════════════════════════════════════════════════════════════════════════
# GovernedTrainingPipeline tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGovernedTrainingPipeline:
    """Tests for modules/governed_training_pipeline.py"""

    def _make_pipeline(self, tmp_path: Path, **kwargs):
        """Return a fresh pipeline with mocked governance backed by tmp dir."""
        from modules.governed_training_pipeline import GovernedTrainingPipeline
        from modules.training_dataset_governance import TrainingDatasetGovernance

        gov = TrainingDatasetGovernance()
        gov._dataset_path = tmp_path / "pipeline_dataset.jsonl"
        gov._rollback_dir = tmp_path / "pipeline_rollbacks"
        gov._seen_hashes = set()
        gov._loaded_hashes = True

        return GovernedTrainingPipeline(governance=gov, **kwargs)

    def test_disabled_returns_without_processing(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "0"}):
            result = pipeline.run_for_gap("python basics")
        assert not result.approved
        assert "NIBLIT_TRAINING_ENABLED=0" in result.rejection_reason

    def test_gaps_disabled_returns_without_processing(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "1",
                                     "NIBLIT_ALE_TRAIN_ON_GAPS": "0"}):
            result = pipeline.run_for_gap("python basics")
        assert not result.approved
        assert "NIBLIT_ALE_TRAIN_ON_GAPS=0" in result.rejection_reason

    def test_synthesis_failure_terminates_pipeline(self, tmp_path):
        """If synthesis returns nothing the pipeline must not commit anything."""
        pipeline = self._make_pipeline(tmp_path)

        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "1"}):
            # No router/local_brain available → synthesis fails.
            with patch("modules.governed_training_pipeline._synthesize_data", return_value=True):
                result = pipeline.run_for_gap("obscure topic")

        assert result.candidates_committed == 0

    def test_stage_research_returns_fallback_when_no_ale(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        stage = pipeline._stage_research("topic A", "trace-1")
        assert stage.stage == "research"
        # No ALE wired → success=False but data is always present.
        assert stage.data is not None

    def test_stage_dataset_generation_parses_qa_pairs(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        synthesis = (
            "Q: What is Python?\nA: Python is a programming language.\n\n"
            "Q: Why use Python?\nA: Python is easy to learn and widely used.\n"
        )
        stage, pairs = pipeline._stage_dataset_generation(
            "python", synthesis, 0.80, 1, "trace-1"
        )
        assert stage.success
        assert len(pairs) >= 2
        assert all("prompt" in p and "response" in p for p in pairs)

    def test_stage_dataset_generation_empty_synthesis(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        stage, pairs = pipeline._stage_dataset_generation(
            "topic", "", 0.80, 1, "trace-1"
        )
        assert not stage.success
        assert len(pairs) == 0

    def test_governance_commit_stage_calls_governance(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        candidates = [_make_candidate(score=0.80)]
        stage = pipeline._stage_governance_commit(candidates, "topic", 1, "trace-1")
        assert stage.stage == "governance_commit"
        # Should succeed since the candidate has a good score.
        assert stage.success

    def test_governance_commit_no_candidates(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        stage = pipeline._stage_governance_commit([], "topic", 1, "trace-1")
        assert not stage.success

    def test_run_for_gaps_empty_list(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "1"}):
            results = pipeline.run_for_gaps([])
        assert results == []

    def test_status_contains_expected_keys(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        status = pipeline.status()
        for key in ("enabled", "train_on_gaps", "max_dataset_per_cycle",
                    "min_score", "total_cycles", "total_committed"):
            assert key in status

    def test_singleton_late_wires_references(self, tmp_path):
        """get_governed_training_pipeline should update references on re-call."""
        import modules.governed_training_pipeline as gtp_mod

        # Reset singleton for isolated test.
        original = gtp_mod._instance
        gtp_mod._instance = None
        try:
            mock_router = MagicMock()
            p1 = gtp_mod.get_governed_training_pipeline(router=mock_router)
            assert p1.router is mock_router

            mock_bt = MagicMock()
            p2 = gtp_mod.get_governed_training_pipeline(brain_trainer=mock_bt)
            assert p2 is p1  # same singleton
            assert p1.brain_trainer is mock_bt
        finally:
            gtp_mod._instance = original

    def test_pipeline_result_summary_format(self):
        from modules.governed_training_pipeline import PipelineResult
        r = PipelineResult(
            topic="test topic",
            candidates_generated=5,
            candidates_committed=3,
            final_score=0.72,
            approved=True,
            elapsed_secs=1.23,
        )
        summary = r.summary()
        assert "test topic" in summary
        assert "0.720" in summary
        assert "committed=3" in summary


# ══════════════════════════════════════════════════════════════════════════════
# ALE integration hook smoke-test
# ══════════════════════════════════════════════════════════════════════════════

class TestALEGovernedHook:
    """Smoke-tests for the _run_governed_training_pipeline ALE method."""

    def _make_ale(self):
        """Construct a minimal ALE-like object with the new method."""
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        ale = AutonomousLearningEngine.__new__(AutonomousLearningEngine)
        ale.brain_trainer = MagicMock()
        ale.knowledge_db = None
        ale.learning_history = {}
        ale.core = None
        return ale

    def test_hook_returns_empty_when_training_disabled(self):
        ale = self._make_ale()
        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "0"}):
            result = ale._run_governed_training_pipeline()
        assert result == ""

    def test_hook_returns_empty_when_no_gaps(self):
        ale = self._make_ale()
        # detect_knowledge_gaps patched to return empty list.
        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "1"}):
            with patch.object(ale, "detect_knowledge_gaps", return_value=[]):
                result = ale._run_governed_training_pipeline()
        assert result == ""

    def test_hook_returns_string_summary_on_success(self, tmp_path):
        """Hook returns a non-empty summary when the pipeline commits candidates."""
        ale = self._make_ale()

        # Build a pipeline that will commit one candidate.
        from modules.governed_training_pipeline import GovernedTrainingPipeline, PipelineResult
        mock_pipeline = MagicMock(spec=GovernedTrainingPipeline)
        committed_result = PipelineResult(
            topic="test", candidates_committed=2, approved=True
        )
        mock_pipeline.run_for_gaps.return_value = [committed_result]

        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "1"}):
            with patch.object(ale, "detect_knowledge_gaps", return_value=["test"]):
                with patch(
                    "modules.governed_training_pipeline.get_governed_training_pipeline",
                    return_value=mock_pipeline,
                ):
                    result = ale._run_governed_training_pipeline()

        assert "GovernedPipeline" in result
        assert "2" in result  # committed count

    def test_hook_handles_import_error_gracefully(self):
        """If governed_training_pipeline is unavailable, the hook logs and returns ''."""
        ale = self._make_ale()
        with patch.dict(os.environ, {"NIBLIT_TRAINING_ENABLED": "1"}):
            with patch.object(ale, "detect_knowledge_gaps", return_value=["topic"]):
                with patch.dict(sys.modules, {"modules.governed_training_pipeline": None}):
                    result = ale._run_governed_training_pipeline()
        # Should not raise; returns empty string on error.
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# .env.example governance config smoke-test
# ══════════════════════════════════════════════════════════════════════════════

class TestEnvExampleTrainingConfig:
    """Verify that .env.example contains all required governed training vars."""

    _REQUIRED_VARS = [
        # Core training settings
        "NIBLIT_TRAINING_ENABLED",
        "NIBLIT_TRAINING_MODE",
        "NIBLIT_TRAINING_RUNTIME",
        "NIBLIT_TRAINING_MODEL",
        "NIBLIT_TRAINING_DEVICE",
        "NIBLIT_TRAINING_PRECISION",
        # LoRA hyperparameters
        "NIBLIT_LORA_R",
        "NIBLIT_LORA_ALPHA",
        "NIBLIT_LORA_DROPOUT",
        "NIBLIT_LORA_TARGET_MODULES",
        "NIBLIT_LORA_BIAS",
        "NIBLIT_LORA_TASK_TYPE",
        "NIBLIT_LORA_GRADIENT_CHECKPOINTING",
        "NIBLIT_LORA_FLASH_ATTENTION",
        "NIBLIT_LORA_SEQUENCE_LENGTH",
        "NIBLIT_LORA_CTX_EXTENSION",
        "NIBLIT_LORA_MICROBATCH_SIZE",
        "NIBLIT_LORA_GRAD_ACCUMULATION",
        "NIBLIT_LORA_EPOCHS",
        "NIBLIT_LORA_LEARNING_RATE",
        "NIBLIT_LORA_WEIGHT_DECAY",
        "NIBLIT_LORA_WARMUP_RATIO",
        "NIBLIT_LORA_SCHEDULER",
        # SFT hyperparameters
        "NIBLIT_SFT_ENABLED",
        "NIBLIT_SFT_DATASET_MAX_SIZE",
        "NIBLIT_SFT_DATASET_RETENTION_DAYS",
        "NIBLIT_SFT_MIN_QUALITY_SCORE",
        "NIBLIT_SFT_MAX_TRAINING_SAMPLES",
        "NIBLIT_SFT_SYNTHESIS_MODE",
        "NIBLIT_SFT_MERGE_MEMORY_TYPES",
        "NIBLIT_SFT_USE_REFLECTION_MEMORY",
        "NIBLIT_SFT_USE_MARKET_MEMORY",
        "NIBLIT_SFT_USE_ARCH_MEMORY",
        "NIBLIT_SFT_USE_RUNTIME_MEMORY",
        "NIBLIT_SFT_DEDUPLICATION",
        "NIBLIT_SFT_EVAL_BEFORE_TRAIN",
        "NIBLIT_SFT_EVAL_AFTER_TRAIN",
        # ALE training settings
        "NIBLIT_ALE_TRAIN_ON_GAPS",
        "NIBLIT_ALE_SYNTHESIZE_TRAINING_DATA",
        "NIBLIT_ALE_USE_LLAMA3_REFLECTION",
        "NIBLIT_ALE_TRAINING_TOPIC_PRIORITY",
        "NIBLIT_ALE_MEMORY_TO_DATASET",
        "NIBLIT_ALE_AUTO_CURRICULUM",
        "NIBLIT_ALE_MAX_DATASET_PER_CYCLE",
        "NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED",
        # Memory synthesis
        "NIBLIT_MEMORY_SYNTHESIS_ENABLED",
        "NIBLIT_MEMORY_TRAINING_COLLECTIONS",
        "NIBLIT_MEMORY_EPISODIC_EXPORT",
        "NIBLIT_MEMORY_REFLECTION_EXPORT",
        "NIBLIT_MEMORY_RUNTIME_EXPORT",
        "NIBLIT_MEMORY_MARKET_EXPORT",
        "NIBLIT_MEMORY_ARCH_EXPORT",
        # Evaluation and rollback
        "NIBLIT_TRAINING_EVAL_ENABLED",
        "NIBLIT_TRAINING_MIN_SCORE",
        "NIBLIT_TRAINING_REJECT_LOW_QUALITY",
        "NIBLIT_TRAINING_COMPARE_BASE_MODEL",
        "NIBLIT_TRAINING_HALLUCINATION_CHECK",
        "NIBLIT_TRAINING_ROLLBACK_ENABLED",
        # 16K context
        "NIBLIT_ROPE_SCALING_TYPE",
        "NIBLIT_ROPE_SCALING_FACTOR",
        "NIBLIT_GGUF_N_GPU_LAYERS",
        "NIBLIT_LLAMA_FLASH_ATTN",
        "NIBLIT_CONTEXT_HARD_TRUNCATION",
        "NIBLIT_CONTEXT_RESPONSE_RESERVE",
    ]

    def _read_env_example(self) -> str:
        env_path = Path(__file__).parent / ".env.example"
        if not env_path.exists():
            pytest.skip(".env.example not found")
        return env_path.read_text(encoding="utf-8")

    def test_all_required_vars_present(self):
        content = self._read_env_example()
        missing = [v for v in self._REQUIRED_VARS if v not in content]
        assert not missing, f"Missing vars in .env.example: {missing}"

    def test_niblit_training_enabled_default_is_zero(self):
        """Default should be 0 to avoid accidental training activation."""
        content = self._read_env_example()
        assert "NIBLIT_TRAINING_ENABLED=0" in content

    def test_approval_required_default_is_one(self):
        """Default governance approval should be ON."""
        content = self._read_env_example()
        assert "NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED=1" in content

    def test_rollback_enabled_default_is_one(self):
        content = self._read_env_example()
        assert "NIBLIT_TRAINING_ROLLBACK_ENABLED=1" in content
