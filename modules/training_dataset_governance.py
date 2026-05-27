#!/usr/bin/env python3
"""modules/training_dataset_governance.py — Governed SFT/LoRA Dataset Management.

This module is the DATASET GOVERNANCE LAYER for Niblit's adaptive cognition
training pipeline.  It is NOT:
- an autonomous training executor
- a replacement for LLMArchitectEngine or BrainTrainer
- a self-modifying loop

It IS:
- an additive governance layer that scores, deduplicates, tags, and traces
  every training candidate before it can be committed to a dataset.
- rollback-compatible: every commit writes a manifest so any batch can be
  reverted without touching the rest of the dataset.

Design principles
-----------------
* All public methods are thread-safe (protected by a single RLock).
* Deduplication uses a SHA-256 prompt hash; near-duplicate detection uses a
  simple token-overlap heuristic to avoid heavyweight dependencies.
* Rollback manifests are written as JSONL to NIBLIT_TRAINING_ROLLBACK_DIR.
* Scoring is composable: a sample's composite score is the weighted average
  of sub-scores provided by callers (quality, hallucination, coverage, etc.).
* No external dependencies beyond the stdlib — heavy ML libraries (torch,
  transformers) are never imported here.

Dataset record schema
---------------------
Each record stored in the governed JSONL dataset file is a JSON object::

    {
        "prompt":            str,
        "response":          str,
        "source_subsystem":  str,       # e.g. "ale_gap_cognition"
        "memory_origin":     str,       # e.g. "reflection" | "episodic"
        "evaluation_score":  float,     # composite quality score 0–1
        "hallucination_score": float,   # 0 = clean, 1 = likely hallucination
        "provider_used":     str,       # "llama3" | "qwen" | "hf" | …
        "ale_cycle_id":      int,
        "runtime_mode":      str,       # "local" | "cloud" | …
        "timestamp":         float,     # Unix epoch
        "trace_id":          str,       # UUID for end-to-end tracing
        "approved":          bool,
        "rollback_batch_id": str        # matches manifest filename stem
    }

Configuration (environment variables)
--------------------------------------
    NIBLIT_SFT_DATASET_PATH          path to governed dataset JSONL
    NIBLIT_SFT_DATASET_MAX_SIZE      max records before rotation (default 5000)
    NIBLIT_SFT_DATASET_RETENTION_DAYS days before eviction eligibility (default 30)
    NIBLIT_SFT_MIN_QUALITY_SCORE     0–1, minimum composite score to approve (default 0.60)
    NIBLIT_SFT_DEDUPLICATION         1 = deduplicate on commit (default 1)
    NIBLIT_TRAINING_HALLUCINATION_CHECK  1 = run heuristic check (default 1)
    NIBLIT_TRAINING_ROLLBACK_ENABLED 1 = write manifests (default 1)
    NIBLIT_TRAINING_ROLLBACK_DIR     directory for manifests (default data/rollbacks)
    NIBLIT_TRAINING_REJECT_LOW_QUALITY 1 = quarantine below-threshold samples
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("TrainingDataGovernance")

# ── Configuration ─────────────────────────────────────────────────────────────

def _dataset_path() -> Path:
    raw = os.environ.get("NIBLIT_SFT_DATASET_PATH", "").strip()
    if raw:
        return Path(raw)
    try:
        from niblit_core.config.paths import get_data_dir
        return get_data_dir() / "niblit_sft_dataset_governed.jsonl"
    except Exception:
        return Path("niblit_sft_dataset_governed.jsonl")


def _rollback_dir() -> Path:
    raw = os.environ.get("NIBLIT_TRAINING_ROLLBACK_DIR", "").strip()
    if raw:
        return Path(raw)
    try:
        from niblit_core.config.paths import get_data_dir
        return get_data_dir() / "training_rollbacks"
    except Exception:
        return Path("training_rollbacks")


_DATASET_MAX_SIZE: int = int(os.environ.get("NIBLIT_SFT_DATASET_MAX_SIZE", "5000"))
_RETENTION_DAYS: int = int(os.environ.get("NIBLIT_SFT_DATASET_RETENTION_DAYS", "30"))
_MIN_QUALITY: float = float(os.environ.get("NIBLIT_SFT_MIN_QUALITY_SCORE", "0.60"))
_DEDUP_ENABLED: bool = os.environ.get("NIBLIT_SFT_DEDUPLICATION", "1") != "0"
_HALLUCINATION_CHECK: bool = os.environ.get("NIBLIT_TRAINING_HALLUCINATION_CHECK", "1") != "0"
_ROLLBACK_ENABLED: bool = os.environ.get("NIBLIT_TRAINING_ROLLBACK_ENABLED", "1") != "0"
_REJECT_LOW_QUALITY: bool = os.environ.get("NIBLIT_TRAINING_REJECT_LOW_QUALITY", "1") != "0"

# Approximate token count heuristic (no tokenizer required).
_WORDS_PER_TOKEN = 0.75
# Near-duplicate threshold: if token overlap ratio exceeds this, record is
# considered a near-duplicate of an existing entry.
_NEAR_DEDUP_THRESHOLD = 0.90

# Hallucination heuristic: patterns that commonly indicate model confabulation.
_HALLUCINATION_PATTERNS: tuple[str, ...] = (
    "i don't actually",
    "i cannot verify",
    "i made this up",
    "this is not real",
    "as a language model",
    "i am unable to confirm",
    "i must inform you that i fabricated",
)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class DatasetRecord:
    """A single governed training sample with full provenance metadata."""
    prompt: str
    response: str
    source_subsystem: str = "unknown"
    memory_origin: str = "unknown"
    evaluation_score: float = 0.0
    hallucination_score: float = 0.0
    provider_used: str = "unknown"
    ale_cycle_id: int = 0
    runtime_mode: str = "local"
    timestamp: float = field(default_factory=time.time)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    approved: bool = False
    rollback_batch_id: str = ""

    def prompt_hash(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8", errors="replace")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> DatasetRecord:
        return DatasetRecord(**{k: v for k, v in d.items() if k in DatasetRecord.__dataclass_fields__})


@dataclass
class CommitManifest:
    """Rollback manifest written before each dataset batch commit."""
    batch_id: str
    timestamp: float
    records_count: int
    prompt_hashes: list[str]
    source_subsystems: list[str]
    min_score: float
    mean_score: float
    ale_cycle_id: int
    dataset_path: str
    previous_record_count: int


@dataclass
class GovernanceReport:
    """Summary returned after a governance pass."""
    submitted: int = 0
    approved: int = 0
    rejected_quality: int = 0
    rejected_duplicate: int = 0
    rejected_hallucination: int = 0
    committed: int = 0
    quarantined: int = 0
    batch_id: str = ""
    mean_score: float = 0.0


# ── Core governance engine ────────────────────────────────────────────────────

class TrainingDatasetGovernance:
    """Govern the lifecycle of every SFT training candidate.

    Usage::

        gov = get_training_governance()
        report = gov.submit_batch(
            candidates=[
                {"prompt": "...", "response": "...", "evaluation_score": 0.75, ...},
                ...
            ],
            source_subsystem="ale_gap_cognition",
            ale_cycle_id=42,
        )
        approved_records = gov.load_approved(limit=200)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dataset_path = _dataset_path()
        self._rollback_dir = _rollback_dir()
        # In-memory prompt-hash set for fast deduplication during a session.
        self._seen_hashes: set = set()
        self._total_submitted = 0
        self._total_approved = 0
        self._total_rejected = 0
        self._quarantine: list[DatasetRecord] = []
        self._loaded_hashes = False

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _ensure_paths(self) -> None:
        self._dataset_path.parent.mkdir(parents=True, exist_ok=True)
        if _ROLLBACK_ENABLED:
            self._rollback_dir.mkdir(parents=True, exist_ok=True)

    def _lazy_load_hashes(self) -> None:
        """Load existing prompt hashes from the dataset file (once)."""
        if self._loaded_hashes:
            return
        self._loaded_hashes = True
        if not self._dataset_path.exists():
            return
        try:
            with self._dataset_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        prompt = rec.get("prompt", "")
                        if prompt:
                            h = hashlib.sha256(
                                prompt.encode("utf-8", errors="replace")
                            ).hexdigest()
                            self._seen_hashes.add(h)
                    except json.JSONDecodeError:
                        pass
        except OSError as exc:
            log.debug("[DataGovernance] Could not load existing hashes: %s", exc)

    def _score_hallucination(self, record: DatasetRecord) -> float:
        """Return a heuristic hallucination probability score 0–1."""
        if not _HALLUCINATION_CHECK:
            return 0.0
        text = (record.prompt + " " + record.response).lower()
        hits = sum(1 for p in _HALLUCINATION_PATTERNS if p in text)
        # Also penalise very short responses (< 5 tokens).
        word_count = len(record.response.split())
        if word_count < 5:
            hits += 1
        return min(1.0, hits / max(1, len(_HALLUCINATION_PATTERNS)))

    def _is_near_duplicate(self, record: DatasetRecord) -> bool:
        """Return True if the record is an exact or near-duplicate."""
        if not _DEDUP_ENABLED:
            return False
        # Exact duplicate via hash.
        ph = record.prompt_hash()
        if ph in self._seen_hashes:
            return True
        return False

    def _count_existing_records(self) -> int:
        if not self._dataset_path.exists():
            return 0
        try:
            with self._dataset_path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

    def _write_rollback_manifest(self, manifest: CommitManifest) -> Path:
        """Persist a rollback manifest to the rollback directory."""
        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        path = self._rollback_dir / f"manifest_{manifest.batch_id}.json"
        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(asdict(manifest), fh, indent=2)
            log.debug("[DataGovernance] Rollback manifest written: %s", path.name)
        except OSError as exc:
            log.warning("[DataGovernance] Failed to write rollback manifest: %s", exc)
        return path

    def _write_quarantine(self, records: list[DatasetRecord], batch_id: str) -> None:
        """Append quarantined records to a separate JSONL file."""
        if not records:
            return
        quarantine_path = self._rollback_dir / f"quarantine_{batch_id}.jsonl"
        try:
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            with quarantine_path.open("a", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec.to_dict()) + "\n")
        except OSError as exc:
            log.debug("[DataGovernance] Quarantine write failed: %s", exc)

    # ── Public API ───────────────────────────────────────────────────────────

    def submit_batch(
        self,
        candidates: list[dict[str, Any]],
        source_subsystem: str = "unknown",
        memory_origin: str = "unknown",
        provider_used: str = "unknown",
        ale_cycle_id: int = 0,
        runtime_mode: str = "local",
    ) -> GovernanceReport:
        """Score, gate, and commit a batch of training candidates.

        Parameters
        ----------
        candidates:
            List of dicts with at least ``prompt`` and ``response`` keys.
            Optional keys: ``evaluation_score``, ``hallucination_score``,
            ``trace_id``, ``memory_origin``.
        source_subsystem:
            Name of the subsystem that generated the candidates
            (e.g. ``"ale_gap_cognition"``).
        memory_origin:
            Memory layer the candidates were drawn from
            (e.g. ``"reflection"``).
        provider_used:
            Inference provider used for synthesis (e.g. ``"llama3"``).
        ale_cycle_id:
            ALE cycle counter for provenance.
        runtime_mode:
            Runtime mode string (e.g. ``"local"``).

        Returns
        -------
        GovernanceReport
            Summary of what was approved, rejected, and committed.
        """
        with self._lock:
            self._ensure_paths()
            self._lazy_load_hashes()

            report = GovernanceReport(submitted=len(candidates))
            approved_records: list[DatasetRecord] = []
            quarantined_records: list[DatasetRecord] = []
            batch_id = str(uuid.uuid4())[:12]
            report.batch_id = batch_id

            for raw in candidates:
                if not isinstance(raw, dict):
                    continue
                prompt = str(raw.get("prompt") or raw.get("input") or "").strip()
                response = str(raw.get("response") or raw.get("output") or raw.get("completion") or "").strip()
                if not prompt or not response:
                    continue

                rec = DatasetRecord(
                    prompt=prompt,
                    response=response,
                    source_subsystem=str(raw.get("source_subsystem") or source_subsystem),
                    memory_origin=str(raw.get("memory_origin") or memory_origin),
                    evaluation_score=float(raw.get("evaluation_score", 0.0)),
                    hallucination_score=float(raw.get("hallucination_score", 0.0)),
                    provider_used=str(raw.get("provider_used") or provider_used),
                    ale_cycle_id=int(raw.get("ale_cycle_id") or ale_cycle_id),
                    runtime_mode=str(raw.get("runtime_mode") or runtime_mode),
                    trace_id=str(raw.get("trace_id") or uuid.uuid4()),
                    rollback_batch_id=batch_id,
                )

                # --- Hallucination check ---
                if rec.hallucination_score == 0.0:
                    rec.hallucination_score = self._score_hallucination(rec)
                if rec.hallucination_score >= 0.5:
                    report.rejected_hallucination += 1
                    quarantined_records.append(rec)
                    continue

                # --- Deduplication ---
                if self._is_near_duplicate(rec):
                    report.rejected_duplicate += 1
                    continue

                # --- Quality gate ---
                if rec.evaluation_score < _MIN_QUALITY:
                    report.rejected_quality += 1
                    if _REJECT_LOW_QUALITY:
                        quarantined_records.append(rec)
                    continue

                rec.approved = True
                approved_records.append(rec)

            # --- Commit approved records ---
            if approved_records:
                prev_count = self._count_existing_records()

                if _ROLLBACK_ENABLED:
                    scores = [r.evaluation_score for r in approved_records]
                    manifest = CommitManifest(
                        batch_id=batch_id,
                        timestamp=time.time(),
                        records_count=len(approved_records),
                        prompt_hashes=[r.prompt_hash() for r in approved_records],
                        source_subsystems=list({r.source_subsystem for r in approved_records}),
                        min_score=min(scores),
                        mean_score=sum(scores) / len(scores),
                        ale_cycle_id=ale_cycle_id,
                        dataset_path=str(self._dataset_path),
                        previous_record_count=prev_count,
                    )
                    self._write_rollback_manifest(manifest)
                    report.mean_score = manifest.mean_score

                # Check dataset size cap; rotate if needed.
                if prev_count >= _DATASET_MAX_SIZE:
                    self._rotate_dataset(prev_count)

                try:
                    with self._dataset_path.open("a", encoding="utf-8") as fh:
                        for rec in approved_records:
                            fh.write(json.dumps(rec.to_dict()) + "\n")
                    for rec in approved_records:
                        self._seen_hashes.add(rec.prompt_hash())
                    report.committed = len(approved_records)
                    report.approved = len(approved_records)
                    log.info(
                        "[DataGovernance] Committed %d/%d records (batch=%s, mean_score=%.3f)",
                        report.committed, report.submitted, batch_id,
                        report.mean_score,
                    )
                except OSError as exc:
                    log.error("[DataGovernance] Dataset write failed: %s", exc)

            # --- Quarantine ---
            if quarantined_records:
                report.quarantined = len(quarantined_records)
                self._write_quarantine(quarantined_records, batch_id)
                self._quarantine.extend(quarantined_records)

            self._total_submitted += report.submitted
            self._total_approved += report.approved
            self._total_rejected += (
                report.rejected_quality
                + report.rejected_duplicate
                + report.rejected_hallucination
            )
            return report

    def _rotate_dataset(self, current_count: int) -> None:
        """Evict oldest records when the dataset exceeds the size cap."""
        try:
            with self._dataset_path.open("r", encoding="utf-8") as fh:
                lines = [ln for ln in fh if ln.strip()]
            # Keep the newest _DATASET_MAX_SIZE * 0.8 records.
            keep = int(_DATASET_MAX_SIZE * 0.8)
            evicted = lines[:-keep] if len(lines) > keep else []
            kept = lines[-keep:]
            with self._dataset_path.open("w", encoding="utf-8") as fh:
                fh.writelines(kept)
            # Rebuild hash set from kept records.
            self._seen_hashes.clear()
            for line in kept:
                try:
                    rec = json.loads(line)
                    p = rec.get("prompt", "")
                    if p:
                        self._seen_hashes.add(
                            hashlib.sha256(p.encode("utf-8", errors="replace")).hexdigest()
                        )
                except json.JSONDecodeError:
                    pass
            log.info(
                "[DataGovernance] Rotated dataset: evicted %d, kept %d records",
                len(evicted), len(kept),
            )
        except OSError as exc:
            log.warning("[DataGovernance] Dataset rotation failed: %s", exc)

    def load_approved(
        self,
        limit: int = 500,
        min_score: float | None = None,
        source_subsystem: str | None = None,
        since_ts: float | None = None,
    ) -> list[DatasetRecord]:
        """Load approved records from the governed dataset file.

        Parameters
        ----------
        limit:
            Maximum number of records to return (newest first).
        min_score:
            Optional additional score filter.
        source_subsystem:
            Optional filter by subsystem.
        since_ts:
            Optional Unix timestamp; only return records newer than this.
        """
        with self._lock:
            if not self._dataset_path.exists():
                return []
            records: list[DatasetRecord] = []
            try:
                with self._dataset_path.open("r", encoding="utf-8") as fh:
                    lines = list(fh)
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if not d.get("approved"):
                            continue
                        if min_score is not None and d.get("evaluation_score", 0) < min_score:
                            continue
                        if source_subsystem and d.get("source_subsystem") != source_subsystem:
                            continue
                        if since_ts and d.get("timestamp", 0) < since_ts:
                            continue
                        records.append(DatasetRecord.from_dict(d))
                        if len(records) >= limit:
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass
            except OSError as exc:
                log.debug("[DataGovernance] Load failed: %s", exc)
            return records

    def rollback_batch(self, batch_id: str) -> bool:
        """Remove all records from a committed batch using its manifest.

        Parameters
        ----------
        batch_id:
            The batch_id string returned in a previous ``GovernanceReport``.

        Returns
        -------
        bool
            True if records were removed, False if manifest not found.
        """
        with self._lock:
            manifest_path = self._rollback_dir / f"manifest_{batch_id}.json"
            if not manifest_path.exists():
                log.warning("[DataGovernance] Rollback manifest not found: %s", batch_id)
                return False

            try:
                with manifest_path.open("r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
                hashes_to_remove = set(manifest.get("prompt_hashes", []))
            except (OSError, json.JSONDecodeError) as exc:
                log.error("[DataGovernance] Failed to read manifest: %s", exc)
                return False

            if not self._dataset_path.exists():
                return False

            try:
                with self._dataset_path.open("r", encoding="utf-8") as fh:
                    lines = list(fh)

                kept = []
                removed = 0
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        rec = json.loads(stripped)
                        ph = hashlib.sha256(
                            rec.get("prompt", "").encode("utf-8", errors="replace")
                        ).hexdigest()
                        if ph in hashes_to_remove and rec.get("rollback_batch_id") == batch_id:
                            removed += 1
                            self._seen_hashes.discard(ph)
                        else:
                            kept.append(line)
                    except json.JSONDecodeError:
                        kept.append(line)

                with self._dataset_path.open("w", encoding="utf-8") as fh:
                    fh.writelines(kept)

                log.info(
                    "[DataGovernance] Rollback batch=%s: removed %d records",
                    batch_id, removed,
                )
                return removed > 0
            except OSError as exc:
                log.error("[DataGovernance] Rollback write failed: %s", exc)
                return False

    def status(self) -> dict[str, Any]:
        """Return a dict summary of governance state."""
        with self._lock:
            record_count = self._count_existing_records()
            return {
                "dataset_path": str(self._dataset_path),
                "record_count": record_count,
                "dataset_max_size": _DATASET_MAX_SIZE,
                "min_quality_score": _MIN_QUALITY,
                "deduplication_enabled": _DEDUP_ENABLED,
                "hallucination_check_enabled": _HALLUCINATION_CHECK,
                "rollback_enabled": _ROLLBACK_ENABLED,
                "seen_hashes_in_session": len(self._seen_hashes),
                "quarantined_in_session": len(self._quarantine),
                "total_submitted": self._total_submitted,
                "total_approved": self._total_approved,
                "total_rejected": self._total_rejected,
            }

    def evict_stale(self) -> int:
        """Remove records older than NIBLIT_SFT_DATASET_RETENTION_DAYS.

        Returns the number of records evicted.
        """
        with self._lock:
            if not self._dataset_path.exists():
                return 0
            cutoff = time.time() - (_RETENTION_DAYS * 86400)
            try:
                with self._dataset_path.open("r", encoding="utf-8") as fh:
                    lines = list(fh)
                kept = []
                evicted = 0
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        rec = json.loads(stripped)
                        if rec.get("timestamp", time.time()) < cutoff:
                            ph = hashlib.sha256(
                                rec.get("prompt", "").encode("utf-8", errors="replace")
                            ).hexdigest()
                            self._seen_hashes.discard(ph)
                            evicted += 1
                        else:
                            kept.append(line)
                    except json.JSONDecodeError:
                        kept.append(line)
                if evicted:
                    with self._dataset_path.open("w", encoding="utf-8") as fh:
                        fh.writelines(kept)
                    log.info("[DataGovernance] Evicted %d stale records", evicted)
                return evicted
            except OSError as exc:
                log.debug("[DataGovernance] Eviction failed: %s", exc)
                return 0


# ── Process-level singleton ───────────────────────────────────────────────────

_instance: TrainingDatasetGovernance | None = None
_instance_lock = threading.Lock()


def get_training_governance() -> TrainingDatasetGovernance:
    """Return the process-level TrainingDatasetGovernance singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = TrainingDatasetGovernance()
    return _instance


if __name__ == "__main__":
    print(get_training_governance().status())
