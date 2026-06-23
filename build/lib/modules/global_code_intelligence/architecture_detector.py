#!/usr/bin/env python3
"""
modules/global_code_intelligence/architecture_detector.py

Detect software architecture patterns from repository metadata, directory
structures, and file-level signals.

Detected architectures:
    microservices, monolithic, mvc, layered, event_driven,
    plugin, serverless, cqrs, hexagonal, actor_model

The detector works from lightweight signals (folder names, file names, import
keywords) without cloning or executing code.

Usage::

    from modules.global_code_intelligence.architecture_detector import ArchitectureDetector
    detector = ArchitectureDetector()
    arch = detector.detect_from_structure(folder_list, file_list)
    arch = detector.detect_from_topics(["event-driven", "kafka", "microservices"])
    arch = detector.detect_from_imports(["fastapi", "celery", "redis"])
"""

import logging
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("ArchitectureDetector")

# ── signal maps ───────────────────────────────────────────────────────────────
_DIR_SIGNALS: Dict[str, List[str]] = {
    "mvc":           ["controllers", "models", "views", "templates"],
    "layered":       ["api", "service", "services", "repository", "repositories", "infrastructure"],
    "microservices": ["services", "gateway", "service_mesh"],
    "plugin":        ["plugins", "extensions", "addons"],
    "hexagonal":     ["adapters", "ports", "domain", "application"],
    "cqrs":          ["commands", "queries", "events", "handlers"],
}

_TOPIC_SIGNALS: Dict[str, List[str]] = {
    "event_driven":  ["event-driven", "event-sourcing", "cqrs", "kafka", "rabbitmq", "pubsub"],
    "microservices": ["microservices", "micro-services", "service-mesh", "kubernetes"],
    "serverless":    ["serverless", "lambda", "faas", "cloud-function"],
    "actor_model":   ["actor", "akka", "erlang", "elixir", "pykka"],
    "monolithic":    ["monolith", "monolithic"],
}

_IMPORT_SIGNALS: Dict[str, List[str]] = {
    "event_driven":  ["celery", "kafka_python", "pika", "aio_pika", "redis"],
    "microservices": ["grpc", "httpx", "requests", "consul", "etcd3"],
    "actor_model":   ["pykka", "thespian", "ray"],
    "plugin":        ["pluggy", "stevedore", "yapsy"],
    "serverless":    ["mangum", "aws_lambda_powertools"],
}


class ArchitectureDetector:
    """
    Multi-signal software architecture detector.

    No repository cloning required — works from directory listings, topic tags,
    and import lists already captured by the ecosystem scanner.
    """

    # ── public API ────────────────────────────────────────────────────────────

    def detect_from_structure(
        self,
        folder_names: List[str],
        file_names: Optional[List[str]] = None,
    ) -> Tuple[str, float]:
        """
        Detect architecture from directory and file names.

        Returns (architecture_name, confidence_score 0.0–1.0).
        """
        lower_folders = {f.lower() for f in folder_names}
        scores: Dict[str, int] = {}

        for arch, signals in _DIR_SIGNALS.items():
            hits = sum(1 for s in signals if s in lower_folders)
            if hits > 0:
                scores[arch] = hits

        if not scores:
            return "unknown", 0.0

        best = max(scores, key=lambda k: scores[k])
        total_signals = len(_DIR_SIGNALS[best])
        confidence = min(1.0, scores[best] / max(total_signals, 1))
        return best, round(confidence, 2)

    def detect_from_topics(
        self, topics: List[str]
    ) -> Tuple[str, float]:
        """Detect architecture from repository topic tags."""
        lower_topics = {t.lower() for t in topics}
        scores: Dict[str, int] = {}

        for arch, signals in _TOPIC_SIGNALS.items():
            hits = sum(1 for s in signals if s in lower_topics)
            if hits > 0:
                scores[arch] = hits

        if not scores:
            return "unknown", 0.0

        best = max(scores, key=lambda k: scores[k])
        return best, min(1.0, round(scores[best] / max(len(_TOPIC_SIGNALS[best]), 1), 2))

    def detect_from_imports(
        self, imports: List[str]
    ) -> Tuple[str, float]:
        """Detect architecture from top-level imports."""
        lower_imports = {i.lower() for i in imports}
        scores: Dict[str, int] = {}

        for arch, signals in _IMPORT_SIGNALS.items():
            hits = sum(1 for s in signals if s in lower_imports)
            if hits > 0:
                scores[arch] = hits

        if not scores:
            return "unknown", 0.0

        best = max(scores, key=lambda k: scores[k])
        return best, min(1.0, round(scores[best] / max(len(_IMPORT_SIGNALS[best]), 1), 2))

    def detect_combined(
        self,
        folder_names: Optional[List[str]] = None,
        topics: Optional[List[str]] = None,
        imports: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        """
        Run all detection methods and return the highest-confidence result.

        Returns dict with keys: architecture, confidence, method.
        """
        candidates: List[Tuple[str, float, str]] = []

        if folder_names:
            a, c = self.detect_from_structure(folder_names)
            if a != "unknown":
                candidates.append((a, c, "structure"))

        if topics:
            a, c = self.detect_from_topics(topics)
            if a != "unknown":
                candidates.append((a, c, "topics"))

        if imports:
            a, c = self.detect_from_imports(imports)
            if a != "unknown":
                candidates.append((a, c, "imports"))

        if not candidates:
            return {"architecture": "unknown", "confidence": 0.0, "method": "none"}

        best_a, best_c, best_m = max(candidates, key=lambda x: x[1])
        return {"architecture": best_a, "confidence": best_c, "method": best_m}

    def describe(self, architecture: str) -> str:
        """Return a human-readable description of an architecture."""
        descriptions: Dict[str, str] = {
            "mvc":           "Model-View-Controller: separates data (model), logic (controller), and presentation (view).",
            "layered":       "Layered / N-tier: API → service → repository → database.",
            "microservices": "Microservices: independently deployable services communicating via APIs or messages.",
            "event_driven":  "Event-driven: producers publish events; consumers react asynchronously.",
            "plugin":        "Plugin architecture: core engine extended by independently loaded plugins.",
            "serverless":    "Serverless / FaaS: stateless functions triggered by events without managing servers.",
            "actor_model":   "Actor model: concurrent, isolated actors communicating via message passing.",
            "cqrs":          "CQRS: separate read (query) and write (command) models.",
            "hexagonal":     "Hexagonal (ports & adapters): core domain isolated from external systems via ports.",
            "monolithic":    "Monolithic: all components in a single deployable unit.",
        }
        return descriptions.get(architecture, f"Architecture '{architecture}' — no description available.")


if __name__ == "__main__":
    print('Running architecture_detector.py')
