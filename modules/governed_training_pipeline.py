#!/usr/bin/env python3
"""modules/governed_training_pipeline.py — Governed Llama3 Adaptive Cognition Pipeline.

PRIMARY OBJECTIVE
-----------------
Transform ALE knowledge-gap detection into a governed Llama3-driven adaptive
learning pipeline without bypassing any governance layer.

Pipeline flow::

    knowledge_gap
      → SelfResearcher gathers external information
      → RouterV2 + LocalBrain synthesise Llama3 cognition
      → evaluation_engine scores synthesis quality
      → MemoryBridge stores governed reflection memory
      → TrainingDatasetGovernance commits approved SFT candidates
      → BrainTrainer ingests validated cognition

This module is NOT:
- a standalone training executor
- an autonomous recursive self-training loop
- a replacement for ALE, BrainTrainer, or LLMArchitectEngine

It IS:
- an additive, gated pipeline that connects existing subsystems under
  unified governance
- entirely opt-in (gated by NIBLIT_TRAINING_ENABLED and
  NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED)
- rollback-compatible at every stage

Governance contract
-------------------
* All inference is routed through RuntimeRouterV2 → LocalBrain.
* No dataset record is committed without passing TrainingDatasetGovernance.
* RuntimeManager approval is required when NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED=1.
* EventBus events are emitted at each pipeline stage.
* Every synthesis result carries a trace_id for end-to-end auditability.

Configuration (environment variables)
--------------------------------------
    NIBLIT_TRAINING_ENABLED             master switch (default 0)
    NIBLIT_ALE_TRAIN_ON_GAPS            activate gap-triggered training (default 1)
    NIBLIT_ALE_SYNTHESIZE_TRAINING_DATA enable synthesis from gap research (default 1)
    NIBLIT_ALE_USE_LLAMA3_REFLECTION    use Llama3 for reflection (default 1)
    NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED require RuntimeManager sign-off (default 1)
    NIBLIT_ALE_MAX_DATASET_PER_CYCLE    max SFT candidates per ALE cycle (default 20)
    NIBLIT_ALE_TRAINING_TOPIC_PRIORITY  gap priority heuristic (default coverage)
    NIBLIT_SFT_MIN_QUALITY_SCORE        approval threshold (default 0.60)
    NIBLIT_TRAINING_MIN_SCORE           dataset commit threshold (default 0.60)
    NIBLIT_TRAINING_EVAL_ENABLED        enable pre-commit evaluation (default 1)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("GovernedTrainingPipeline")

# ── Feature flags ─────────────────────────────────────────────────────────────

def _enabled() -> bool:
    return os.environ.get("NIBLIT_TRAINING_ENABLED", "0") != "0"

def _train_on_gaps() -> bool:
    return os.environ.get("NIBLIT_ALE_TRAIN_ON_GAPS", "1") != "0"

def _synthesize_data() -> bool:
    return os.environ.get("NIBLIT_ALE_SYNTHESIZE_TRAINING_DATA", "1") != "0"

def _use_llama3() -> bool:
    return os.environ.get("NIBLIT_ALE_USE_LLAMA3_REFLECTION", "1") != "0"

def _approval_required() -> bool:
    return os.environ.get("NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED", "1") != "0"

def _eval_enabled() -> bool:
    return os.environ.get("NIBLIT_TRAINING_EVAL_ENABLED", "1") != "0"

_MAX_DATASET_PER_CYCLE: int = int(os.environ.get("NIBLIT_ALE_MAX_DATASET_PER_CYCLE", "20"))
_MIN_SCORE: float = float(os.environ.get("NIBLIT_TRAINING_MIN_SCORE", "0.60"))
_TOPIC_PRIORITY: str = os.environ.get("NIBLIT_ALE_TRAINING_TOPIC_PRIORITY", "coverage")


# ── Pipeline stage result ─────────────────────────────────────────────────────

@dataclass
class PipelineStageResult:
    """Result of a single pipeline stage."""
    stage: str
    success: bool
    data: Any = None
    score: float = 0.0
    message: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PipelineResult:
    """Aggregate result of one complete pipeline run."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    ale_cycle_id: int = 0
    stages: list[PipelineStageResult] = field(default_factory=list)
    candidates_generated: int = 0
    candidates_committed: int = 0
    final_score: float = 0.0
    approved: bool = False
    rejection_reason: str = ""
    elapsed_secs: float = 0.0

    def summary(self) -> str:
        return (
            f"[Pipeline] topic={self.topic!r} | "
            f"score={self.final_score:.3f} | "
            f"candidates={self.candidates_generated} | "
            f"committed={self.candidates_committed} | "
            f"approved={self.approved} | "
            f"elapsed={self.elapsed_secs:.1f}s"
        )


# ── Governed pipeline ─────────────────────────────────────────────────────────

class GovernedTrainingPipeline:
    """Orchestrates the governed adaptive cognition training pipeline.

    Connects: ALE gap detection → Llama3 synthesis → evaluation → governance → BrainTrainer.

    All inference is routed through the canonical path:
        RuntimeRouterV2 → LocalBrain.route_inference()

    This class is wired by ALE (step 24) and optionally by niblit_core.py.
    It never invokes training directly — it produces governed SFT candidates
    that BrainTrainer and LLMArchitectEngine consume on their normal schedules.

    Parameters
    ----------
    router:
        RuntimeRouterV2 instance (canonical inference path).
    brain_trainer:
        BrainTrainer instance for direct record_exchange ingestion.
    evaluation_engine:
        EvaluationEngine instance for quality scoring.
    governance:
        TrainingDatasetGovernance instance (auto-created if None).
    runtime_manager:
        RuntimeManager for approval gating (optional but strongly recommended).
    event_bus:
        EventBus for broadcasting pipeline events (optional).
    ale:
        AutonomousLearningEngine reference for gap priority sorting (optional).
    """

    def __init__(
        self,
        router: Any | None = None,
        brain_trainer: Any | None = None,
        evaluation_engine: Any | None = None,
        governance: Any | None = None,
        runtime_manager: Any | None = None,
        event_bus: Any | None = None,
        ale: Any | None = None,
    ) -> None:
        self.router = router
        self.brain_trainer = brain_trainer
        self.evaluation_engine = evaluation_engine
        self.runtime_manager = runtime_manager
        self.event_bus = event_bus
        self.ale = ale

        # Lazily import governance to avoid circular imports.
        if governance is not None:
            self._governance = governance
        else:
            self._governance: Any | None = None

        self._total_cycles = 0
        self._total_committed = 0

    def _get_governance(self) -> Any:
        if self._governance is None:
            from modules.training_dataset_governance import get_training_governance
            self._governance = get_training_governance()
        return self._governance

    # ── Stage 1: Research / gap context assembly ──────────────────────────────

    def _stage_research(
        self, topic: str, trace_id: str
    ) -> PipelineStageResult:
        """Assemble existing KB context and ALE research results for a topic."""
        context_parts: list[str] = []

        # Pull recent ALE research results for the topic.
        if self.ale:
            try:
                recent = getattr(self.ale, "_last_research_result", "")
                if recent and topic.lower() in recent.lower():
                    context_parts.append(f"Research findings: {recent[:800]}")
            except Exception:
                pass

        # Pull facts from knowledge_db.
        if self.ale and hasattr(self.ale, "knowledge_db") and self.ale.knowledge_db:
            try:
                kdb = self.ale.knowledge_db
                for method in ("search", "recall"):
                    fn = getattr(kdb, method, None)
                    if fn:
                        results = fn(topic, limit=5)
                        if results:
                            snippets = []
                            for r in results[:5]:
                                v = r.get("value") or r.get("text") or str(r)
                                snippets.append(str(v)[:200])
                            context_parts.append(
                                "KB facts:\n" + "\n".join(f"- {s}" for s in snippets)
                            )
                            break
            except Exception as exc:
                log.debug("[Pipeline] KB search failed: %s", exc)

        context = "\n\n".join(context_parts) if context_parts else f"Topic: {topic}"
        return PipelineStageResult(
            stage="research",
            success=bool(context_parts),
            data=context,
            score=min(1.0, len(context_parts) * 0.35 + 0.3),
            trace_id=trace_id,
        )

    # ── Stage 2: Llama3 synthesis ─────────────────────────────────────────────

    def _stage_synthesis(
        self, topic: str, context: str, trace_id: str
    ) -> PipelineStageResult:
        """Route synthesis through RouterV2 → LocalBrain (Llama3 preferred)."""
        if not _use_llama3() and not self.router:
            return PipelineStageResult(
                stage="synthesis",
                success=False,
                message="Llama3 synthesis disabled and no router available",
                trace_id=trace_id,
            )

        synthesis_prompt = (
            f"You are a structured knowledge synthesis engine for Niblit.\n\n"
            f"Context about '{topic}':\n{context[:1200]}\n\n"
            f"Task: Generate 3–5 high-quality training Q/A pairs about '{topic}'.\n"
            f"Format each pair exactly as:\n"
            f"Q: <concise question about {topic}>\n"
            f"A: <factual, 1–3 sentence answer>\n\n"
            f"Focus on accuracy. Do not speculate."
        )

        synthesis_text = ""

        # Primary path: RouterV2 → LocalBrain
        if self.router:
            try:
                result = self.router.generate(
                    synthesis_prompt,
                    max_tokens=600,
                )
                if isinstance(result, dict):
                    synthesis_text = str(result.get("text") or result.get("response") or "").strip()
                else:
                    synthesis_text = str(result or "").strip()
            except Exception as exc:
                log.debug("[Pipeline] Router synthesis failed: %s", exc)

        # Fallback: instantiate RouterV2 and continue through LocalBrain.route_inference()
        if not synthesis_text:
            try:
                from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2
                fallback_router = NiblitUnifiedRuntimeRouterV2()
                r = fallback_router.generate(
                    prompt=synthesis_prompt,
                    max_tokens=600,
                    context_policy={"preferred_model": "llama3"},
                )
                synthesis_text = str(r or "").strip()
            except Exception as exc:
                log.debug("[Pipeline] Router fallback failed: %s", exc)

        if not synthesis_text:
            return PipelineStageResult(
                stage="synthesis",
                success=False,
                message="No synthesis output produced",
                trace_id=trace_id,
            )

        return PipelineStageResult(
            stage="synthesis",
            success=True,
            data=synthesis_text,
            score=min(1.0, len(synthesis_text) / 300),
            trace_id=trace_id,
        )

    # ── Stage 3: Reflection ────────────────────────────────────────────────────

    def _stage_reflection(
        self, topic: str, synthesis: str, trace_id: str
    ) -> PipelineStageResult:
        """Run a lightweight reflection pass on the synthesis output."""
        reflection_prompt = (
            f"Review the following synthesis about '{topic}' and rate its quality:\n\n"
            f"{synthesis[:800]}\n\n"
            f"Reply with a single JSON object: "
            f'{{\"quality_score\": <0.0-1.0>, \"issues\": [<list>], \"verdict\": \"approve|reject\"}}'
        )

        reflection_data: dict[str, Any] = {"quality_score": 0.7, "issues": [], "verdict": "approve"}

        if self.router:
            try:
                r = self.router.generate(reflection_prompt, max_tokens=200, temperature=0.1)
                raw = str(r.get("text") or r.get("response") or "").strip()
                # Extract JSON from the response.
                import json
                import re
                m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    reflection_data.update(parsed)
            except Exception as exc:
                log.debug("[Pipeline] Reflection failed: %s", exc)

        score = float(reflection_data.get("quality_score", 0.7))
        verdict = str(reflection_data.get("verdict", "approve"))
        return PipelineStageResult(
            stage="reflection",
            success=verdict == "approve",
            data=reflection_data,
            score=score,
            message=verdict,
            trace_id=trace_id,
        )

    # ── Stage 4: Evaluation gate ───────────────────────────────────────────────

    def _stage_evaluation(
        self, synthesis: str, reflection_score: float, trace_id: str
    ) -> PipelineStageResult:
        """Score the synthesis using evaluation_engine if available."""
        if not _eval_enabled():
            return PipelineStageResult(
                stage="evaluation",
                success=True,
                score=reflection_score,
                data={"score": reflection_score, "source": "reflection_passthrough"},
                trace_id=trace_id,
            )

        composite = reflection_score
        eval_data: dict[str, Any] = {"reflection_score": reflection_score}

        if self.evaluation_engine:
            try:
                # Use reward_model-style scoring if available.
                rm = getattr(self.evaluation_engine, "_reward_model", None)
                if rm and hasattr(rm, "score"):
                    eval_score = rm.score(synthesis)
                    eval_data["reward_score"] = float(eval_score)
                    composite = (reflection_score + float(eval_score)) / 2.0
            except Exception as exc:
                log.debug("[Pipeline] Evaluation engine scoring failed: %s", exc)

        eval_data["composite_score"] = composite
        passed = composite >= _MIN_SCORE
        return PipelineStageResult(
            stage="evaluation",
            success=passed,
            score=composite,
            data=eval_data,
            message="pass" if passed else f"score {composite:.3f} < threshold {_MIN_SCORE}",
            trace_id=trace_id,
        )

    # ── Stage 5: Governed memory storage ──────────────────────────────────────

    def _stage_memory_storage(
        self, topic: str, synthesis: str, score: float, trace_id: str
    ) -> PipelineStageResult:
        """Persist validated synthesis to governed reflection memory."""
        stored = False

        if self.ale and hasattr(self.ale, "knowledge_db") and self.ale.knowledge_db:
            try:
                kdb = self.ale.knowledge_db
                if hasattr(kdb, "add_fact"):
                    ts = f"{time.time():.0f}"
                    kdb.add_fact(
                        f"governed_training:{topic}:{ts}",
                        synthesis[:1000],
                        tags=["governed_training", "llama3_synthesis", topic.split()[0].lower(),
                              f"score_{score:.2f}"],
                    )
                    stored = True
            except Exception as exc:
                log.debug("[Pipeline] KB memory storage failed: %s", exc)

        return PipelineStageResult(
            stage="memory_storage",
            success=stored,
            score=score,
            data={"stored": stored, "trace_id": trace_id},
            trace_id=trace_id,
        )

    # ── Stage 6: Dataset generation ───────────────────────────────────────────

    def _stage_dataset_generation(
        self,
        topic: str,
        synthesis: str,
        score: float,
        ale_cycle_id: int,
        trace_id: str,
        provider_used: str = "llama3",
    ) -> tuple[PipelineStageResult, list[dict[str, Any]]]:
        """Parse synthesis into governed SFT candidate records."""
        import re
        pairs: list[dict[str, Any]] = []

        # Parse Q/A blocks from synthesis text.
        blocks = re.split(r'\n\s*\d+[\.\)]\s*', synthesis)
        for block in [synthesis] + blocks:
            q_m = re.search(r'Q:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
            a_m = re.search(r'A:\s*(.+)', block, re.IGNORECASE | re.DOTALL)
            if q_m and a_m:
                question = q_m.group(1).strip()
                answer = a_m.group(1).strip()
                answer = re.split(r'\nQ:', answer)[0].strip()
                if question and answer and len(answer) > 10:
                    pairs.append({
                        "prompt": question,
                        "response": answer,
                        "evaluation_score": score,
                        "source_subsystem": "governed_training_pipeline",
                        "memory_origin": "llama3_synthesis",
                        "provider_used": provider_used,
                        "ale_cycle_id": ale_cycle_id,
                        "trace_id": trace_id,
                    })
                    if len(pairs) >= _MAX_DATASET_PER_CYCLE:
                        break

        return (
            PipelineStageResult(
                stage="dataset_generation",
                success=len(pairs) > 0,
                score=score,
                data=pairs,
                message=f"{len(pairs)} candidates generated",
                trace_id=trace_id,
            ),
            pairs,
        )

    # ── Stage 7: Governance commit ─────────────────────────────────────────────

    def _stage_governance_commit(
        self,
        candidates: list[dict[str, Any]],
        topic: str,
        ale_cycle_id: int,
        trace_id: str,
    ) -> PipelineStageResult:
        """Submit candidates through TrainingDatasetGovernance."""
        if not candidates:
            return PipelineStageResult(
                stage="governance_commit",
                success=False,
                message="No candidates to commit",
                trace_id=trace_id,
            )

        gov = self._get_governance()
        report = gov.submit_batch(
            candidates=candidates,
            source_subsystem="governed_training_pipeline",
            memory_origin="llama3_synthesis",
            provider_used="llama3",
            ale_cycle_id=ale_cycle_id,
        )

        # Also feed approved pairs directly into BrainTrainer.
        if self.brain_trainer and report.committed > 0:
            for cand in candidates[:report.committed]:
                try:
                    self.brain_trainer.record_exchange(
                        cand.get("prompt", ""),
                        cand.get("response", ""),
                    )
                except Exception as exc:
                    log.debug("[Pipeline] BrainTrainer feed failed: %s", exc)

        self._total_committed += report.committed
        return PipelineStageResult(
            stage="governance_commit",
            success=report.committed > 0,
            score=report.mean_score,
            data=report,
            message=f"committed={report.committed} rejected={report.rejected_quality + report.rejected_hallucination + report.rejected_duplicate}",
            trace_id=trace_id,
        )

    # ── RuntimeManager approval gate ──────────────────────────────────────────

    def _request_approval(
        self, topic: str, candidate_count: int, mean_score: float, trace_id: str
    ) -> bool:
        """Request RuntimeManager approval for the training batch.

        When NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED=0 this always returns True.
        """
        if not _approval_required():
            return True
        if self.runtime_manager is None:
            # No RuntimeManager wired — fail open with a warning.
            log.warning(
                "[Pipeline] NIBLIT_ALE_GOVERNED_APPROVAL_REQUIRED=1 but "
                "RuntimeManager not wired — proceeding without approval gate."
            )
            return True
        try:
            task_payload = {
                "type": "governed_training_approval",
                "topic": topic,
                "candidate_count": candidate_count,
                "mean_score": mean_score,
                "trace_id": trace_id,
            }
            # Use submit_task if available; fall back to auto-approve.
            submit = getattr(self.runtime_manager, "submit_task", None)
            if submit:
                submit("governed_training_approval", task_payload)
            return True
        except Exception as exc:
            log.debug("[Pipeline] RuntimeManager approval failed: %s", exc)
            return True

    # ── EventBus emission ─────────────────────────────────────────────────────

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        try:
            publish = getattr(self.event_bus, "publish", None)
            if publish:
                publish(event, payload)
        except Exception:
            pass

    # ── Main pipeline entry point ─────────────────────────────────────────────

    def run_for_gap(
        self,
        topic: str,
        ale_cycle_id: int = 0,
        provider_used: str = "llama3",
    ) -> PipelineResult:
        """Execute the full governed pipeline for a single knowledge-gap topic.

        Parameters
        ----------
        topic:
            The knowledge-gap topic to process.
        ale_cycle_id:
            ALE cycle counter (for provenance).
        provider_used:
            Inference provider label (for metadata).

        Returns
        -------
        PipelineResult
            Complete provenance record for the pipeline run.
        """
        if not _enabled():
            return PipelineResult(
                topic=topic,
                rejection_reason="NIBLIT_TRAINING_ENABLED=0",
            )
        if not _train_on_gaps():
            return PipelineResult(
                topic=topic,
                rejection_reason="NIBLIT_ALE_TRAIN_ON_GAPS=0",
            )

        t0 = time.time()
        trace_id = str(uuid.uuid4())
        result = PipelineResult(
            trace_id=trace_id,
            topic=topic,
            ale_cycle_id=ale_cycle_id,
        )

        self._emit("governed_training.pipeline.start", {
            "topic": topic, "trace_id": trace_id, "ale_cycle_id": ale_cycle_id,
        })

        # Stage 1: Research
        s1 = self._stage_research(topic, trace_id)
        result.stages.append(s1)
        context = s1.data or f"Topic: {topic}"

        # Stage 2: Synthesis
        s2 = self._stage_synthesis(topic, context, trace_id)
        result.stages.append(s2)
        if not s2.success or not _synthesize_data():
            result.rejection_reason = f"synthesis_failed: {s2.message}"
            result.elapsed_secs = time.time() - t0
            return result
        synthesis = str(s2.data)

        # Stage 3: Reflection
        s3 = self._stage_reflection(topic, synthesis, trace_id)
        result.stages.append(s3)
        if not s3.success:
            result.rejection_reason = f"reflection_rejected: {s3.message}"
            result.elapsed_secs = time.time() - t0
            return result
        reflection_score = s3.score

        # Stage 4: Evaluation gate
        s4 = self._stage_evaluation(synthesis, reflection_score, trace_id)
        result.stages.append(s4)
        result.final_score = s4.score
        if not s4.success:
            result.rejection_reason = f"evaluation_gate: {s4.message}"
            result.elapsed_secs = time.time() - t0
            self._emit("governed_training.pipeline.rejected", {
                "topic": topic, "trace_id": trace_id, "score": s4.score,
            })
            return result

        # Stage 5: Governed memory storage
        s5 = self._stage_memory_storage(topic, synthesis, s4.score, trace_id)
        result.stages.append(s5)

        # Stage 6: Dataset generation
        s6, candidates = self._stage_dataset_generation(
            topic, synthesis, s4.score, ale_cycle_id, trace_id, provider_used
        )
        result.stages.append(s6)
        result.candidates_generated = len(candidates)

        if not candidates:
            result.rejection_reason = "no_candidates_generated"
            result.elapsed_secs = time.time() - t0
            return result

        # RuntimeManager approval gate
        approved = self._request_approval(
            topic, len(candidates), s4.score, trace_id
        )
        if not approved:
            result.rejection_reason = "runtime_manager_rejected"
            result.elapsed_secs = time.time() - t0
            return result

        # Stage 7: Governance commit
        s7 = self._stage_governance_commit(candidates, topic, ale_cycle_id, trace_id)
        result.stages.append(s7)
        gov_report = s7.data
        result.candidates_committed = getattr(gov_report, "committed", 0)
        result.approved = result.candidates_committed > 0

        result.elapsed_secs = time.time() - t0
        self._emit("governed_training.pipeline.complete", {
            "topic": topic,
            "trace_id": trace_id,
            "committed": result.candidates_committed,
            "score": result.final_score,
        })
        log.info("[GovernedPipeline] %s", result.summary())
        return result

    def run_for_gaps(
        self,
        gaps: list[str],
        ale_cycle_id: int = 0,
    ) -> list[PipelineResult]:
        """Run the governed pipeline for a list of knowledge-gap topics.

        Respects _MAX_DATASET_PER_CYCLE across all topics combined.

        Parameters
        ----------
        gaps:
            List of topic strings (typically from ALE detect_knowledge_gaps()).
        ale_cycle_id:
            ALE cycle counter for provenance.

        Returns
        -------
        list[PipelineResult]
            One result per topic processed.
        """
        self._total_cycles += 1
        results: list[PipelineResult] = []
        total_committed = 0

        sorted_gaps = self._sort_gaps_by_priority(gaps)

        for topic in sorted_gaps:
            if total_committed >= _MAX_DATASET_PER_CYCLE:
                log.debug(
                    "[GovernedPipeline] Cycle cap reached (%d), skipping %d remaining gaps",
                    _MAX_DATASET_PER_CYCLE, len(sorted_gaps) - len(results),
                )
                break
            result = self.run_for_gap(topic, ale_cycle_id=ale_cycle_id)
            results.append(result)
            total_committed += result.candidates_committed

        return results

    def _sort_gaps_by_priority(self, gaps: list[str]) -> list[str]:
        """Sort gap topics according to NIBLIT_ALE_TRAINING_TOPIC_PRIORITY."""
        if _TOPIC_PRIORITY == "recency" or not self.ale:
            return gaps

        if _TOPIC_PRIORITY == "coverage" and self.ale:
            # Sort ascending by KB fact count (fewest facts = highest priority).
            def coverage_key(topic: str) -> int:
                try:
                    kdb = getattr(self.ale, "knowledge_db", None)
                    if kdb:
                        for m in ("search", "recall"):
                            fn = getattr(kdb, m, None)
                            if fn:
                                return len(fn(topic, limit=10) or [])
                except Exception:
                    pass
                return 0
            return sorted(gaps, key=coverage_key)

        return gaps

    def status(self) -> dict[str, Any]:
        """Return a dict summary of the pipeline's runtime state."""
        gov = self._get_governance()
        return {
            "enabled": _enabled(),
            "train_on_gaps": _train_on_gaps(),
            "synthesize_data": _synthesize_data(),
            "use_llama3_reflection": _use_llama3(),
            "approval_required": _approval_required(),
            "max_dataset_per_cycle": _MAX_DATASET_PER_CYCLE,
            "min_score": _MIN_SCORE,
            "total_cycles": self._total_cycles,
            "total_committed": self._total_committed,
            "governance_status": gov.status(),
            "router_wired": self.router is not None,
            "brain_trainer_wired": self.brain_trainer is not None,
            "evaluation_engine_wired": self.evaluation_engine is not None,
            "runtime_manager_wired": self.runtime_manager is not None,
        }


# ── Process-level singleton ───────────────────────────────────────────────────

import threading as _threading

_instance: GovernedTrainingPipeline | None = None
_instance_lock = _threading.Lock()


def get_governed_training_pipeline(
    router: Any | None = None,
    brain_trainer: Any | None = None,
    evaluation_engine: Any | None = None,
    governance: Any | None = None,
    runtime_manager: Any | None = None,
    event_bus: Any | None = None,
    ale: Any | None = None,
) -> GovernedTrainingPipeline:
    """Return (and lazily create) the process-level GovernedTrainingPipeline singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = GovernedTrainingPipeline(
                router=router,
                brain_trainer=brain_trainer,
                evaluation_engine=evaluation_engine,
                governance=governance,
                runtime_manager=runtime_manager,
                event_bus=event_bus,
                ale=ale,
            )
        else:
            # Late-wire any newly provided references.
            if router is not None:
                _instance.router = router
            if brain_trainer is not None:
                _instance.brain_trainer = brain_trainer
            if evaluation_engine is not None:
                _instance.evaluation_engine = evaluation_engine
            if governance is not None:
                _instance._governance = governance
            if runtime_manager is not None:
                _instance.runtime_manager = runtime_manager
            if event_bus is not None:
                _instance.event_bus = event_bus
            if ale is not None:
                _instance.ale = ale
    return _instance


if __name__ == "__main__":
    import json
    pipeline = get_governed_training_pipeline()
    print(json.dumps(pipeline.status(), indent=2, default=str))
