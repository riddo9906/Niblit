#!/usr/bin/env python3
"""Copilot-safe refactor intelligence layer for NRR-v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

CHANGE_SAFE = "SAFE_CHANGE"
CHANGE_PERFORMANCE = "PERFORMANCE_CHANGE"
CHANGE_ARCHITECTURAL = "ARCHITECTURAL_CHANGE"
CHANGE_DESTRUCTIVE = "DESTRUCTIVE_CHANGE"


@dataclass
class ChangeAssessment:
    change_type: str
    blocked: bool
    risks: List[str]
    rationale: str
    safer_alternative: Optional[str] = None


class CopilotChangeAnalyzer:
    """Classifies changes and blocks risky/destructive modifications."""

    def classify_change(self, change: Dict[str, object]) -> ChangeAssessment:
        risks = self.detect_regressions(change)

        if self._is_destructive(change, risks):
            return ChangeAssessment(
                change_type=CHANGE_DESTRUCTIVE,
                blocked=True,
                risks=risks,
                rationale="Destructive change violates runtime safety constraints.",
                safer_alternative=self._safer_alternative(change, risks),
            )

        if self._looks_architectural(change):
            return ChangeAssessment(
                change_type=CHANGE_ARCHITECTURAL,
                blocked=bool(risks),
                risks=risks,
                rationale="Architectural change affects routing/memory/embedding paths.",
                safer_alternative=self._safer_alternative(change, risks) if risks else None,
            )

        if self._looks_performance(change):
            return ChangeAssessment(
                change_type=CHANGE_PERFORMANCE,
                blocked=bool(risks),
                risks=risks,
                rationale="Performance-focused change; allowed only when regression risks are absent.",
                safer_alternative=self._safer_alternative(change, risks) if risks else None,
            )

        return ChangeAssessment(
            change_type=CHANGE_SAFE,
            blocked=bool(risks),
            risks=risks,
            rationale="No high-impact behavior change detected.",
            safer_alternative=self._safer_alternative(change, risks) if risks else None,
        )

    def detect_regressions(self, change: Dict[str, object]) -> List[str]:
        """Detect required NRR-v2 regression risks before change application."""
        risks: List[str] = []
        touched_files = [str(p) for p in change.get("touched_files", [])] if isinstance(change.get("touched_files"), list) else []
        imports = [str(i) for i in change.get("imports", [])] if isinstance(change.get("imports"), list) else []
        summary = str(change.get("summary", "")).lower()

        if bool(change.get("dual_backend_execution")) or "dual backend" in summary:
            risks.append("backend duplication risk")

        model_paths = [str(p) for p in change.get("model_paths", [])] if isinstance(change.get("model_paths"), list) else []
        if any(path.startswith("/root") for path in model_paths):
            risks.append("model path corruption (/root usage)")

        embedding_dim = change.get("embedding_dim")
        if embedding_dim is not None and int(embedding_dim) != 384:
            risks.append("embedding dimension mismatch risk")

        if self._has_circular_import_risk(imports):
            risks.append("circular import risk")

        if bool(change.get("removes_memory_loop")) or "remove memory loop" in summary:
            risks.append("memory loop disruption")

        qdrant_dim = change.get("qdrant_vector_dim")
        if qdrant_dim is not None and int(qdrant_dim) != 384:
            risks.append("Qdrant schema drift")

        if any(path.endswith("modules/local_brain.py") for path in touched_files) and bool(change.get("rewrites_local_brain")):
            risks.append("destructive LocalBrain rewrite")

        return risks

    @staticmethod
    def _looks_performance(change: Dict[str, object]) -> bool:
        kind = str(change.get("kind", "")).lower()
        summary = str(change.get("summary", "")).lower()
        return "performance" in kind or "latency" in summary or "speed" in summary

    @staticmethod
    def _looks_architectural(change: Dict[str, object]) -> bool:
        touched_files = [str(p) for p in change.get("touched_files", [])] if isinstance(change.get("touched_files"), list) else []
        hot_paths = ("runtime_router", "memory_loop", "embedding", "qdrant", "local_brain")
        return any(any(key in path for key in hot_paths) for path in touched_files)

    @staticmethod
    def _has_circular_import_risk(imports: List[str]) -> bool:
        normalized = [entry.strip() for entry in imports if entry.strip()]
        seen = set()
        for entry in normalized:
            if entry in seen:
                return True
            seen.add(entry)
        return False

    @staticmethod
    def _is_destructive(change: Dict[str, object], risks: List[str]) -> bool:
        if bool(change.get("force_destructive")):
            return True
        if any(
            risk in risks
            for risk in [
                "model path corruption (/root usage)",
                "embedding dimension mismatch risk",
                "Qdrant schema drift",
                "destructive LocalBrain rewrite",
                "circular import risk",
            ]
        ):
            return True
        return False

    @staticmethod
    def _safer_alternative(change: Dict[str, object], risks: List[str]) -> str:
        if not risks:
            return "Proceed with normal validation."
        if "model path corruption (/root usage)" in risks:
            return "Use only /data/data/com.termux/files/home/models/ for model paths."
        if "embedding dimension mismatch risk" in risks or "Qdrant schema drift" in risks:
            return "Keep embeddings and Qdrant vectors fixed at 384-dim and enforce validation middleware."
        if "backend duplication risk" in risks:
            return "Route each request through a single backend using RouterV2 deterministic priority."
        if "memory loop disruption" in risks:
            return "Preserve the full loop: embed, retrieve, rerank, generate, store."
        if "circular import risk" in risks:
            return "Split shared interfaces into leaf modules and avoid bidirectional imports."
        return "Refactor using wrapper modules without rewriting stable subsystems."
