#!/usr/bin/env python3
"""
modules/ai_dev_lab/architecture_designer.py

Design software architectures based on hypotheses and research findings.

The designer maps hypothesis topics to known architecture patterns and
produces structured architecture specifications that the CodeSynthesizer
can use to generate code.

Usage::

    from modules.ai_dev_lab.architecture_designer import ArchitectureDesigner
    designer = ArchitectureDesigner()
    spec = designer.design(hypothesis)
    print(spec["description"])
"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("ArchitectureDesigner")

# ── Architecture catalogue ────────────────────────────────────────────────────
_ARCHITECTURES: Dict[str, Dict[str, Any]] = {
    "distributed_agent": {
        "description": "Distributed learning agent system",
        "components": ["planner_agent", "memory_engine", "reasoning_engine", "execution_sandbox"],
        "patterns": ["event_driven", "actor_model"],
        "interfaces": ["event_bus", "shared_memory", "result_store"],
    },
    "pipeline": {
        "description": "Data transformation pipeline",
        "components": ["ingestion", "transform", "analysis", "output"],
        "patterns": ["pipeline", "chain_of_responsibility"],
        "interfaces": ["stage_interface", "data_contract"],
    },
    "knowledge_retrieval": {
        "description": "Hybrid knowledge retrieval system",
        "components": ["vector_store", "knowledge_graph", "query_engine", "ranker"],
        "patterns": ["repository_pattern", "strategy"],
        "interfaces": ["retriever", "ranker", "knowledge_store"],
    },
    "self_improving": {
        "description": "Self-improving autonomous system",
        "components": ["monitor", "analyser", "improver", "validator", "deployer"],
        "patterns": ["observer", "strategy", "command"],
        "interfaces": ["metric_collector", "improvement_plan", "deployment_target"],
    },
    "microservice": {
        "description": "Microservice with API gateway",
        "components": ["gateway", "service_a", "service_b", "message_bus"],
        "patterns": ["microservices", "event_driven"],
        "interfaces": ["rest_api", "message_queue"],
    },
}

# Keyword → architecture name mapping
_KEYWORD_MAP: Dict[str, str] = {
    "agent":       "distributed_agent",
    "actor":       "distributed_agent",
    "planning":    "distributed_agent",
    "pipeline":    "pipeline",
    "transform":   "pipeline",
    "etl":         "pipeline",
    "knowledge":   "knowledge_retrieval",
    "retrieval":   "knowledge_retrieval",
    "graph":       "knowledge_retrieval",
    "vector":      "knowledge_retrieval",
    "evolv":       "self_improving",
    "self":        "self_improving",
    "improve":     "self_improving",
    "microservice": "microservice",
    "service":     "microservice",
}


class ArchitectureDesigner:
    """
    Design software architectures for SEADL experiments.
    """

    # ── public API ────────────────────────────────────────────────────────────

    def design(
        self, hypothesis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Choose and return an architecture specification for the hypothesis.

        Args:
            hypothesis: Output of HypothesisGenerator.generate()

        Returns dict with keys:
            name, description, components, patterns, interfaces, hypothesis
        """
        arch_name = self._select_architecture(hypothesis)
        spec = dict(_ARCHITECTURES.get(arch_name, _ARCHITECTURES["pipeline"]))
        spec["name"] = arch_name
        spec["hypothesis"] = hypothesis.get("hypothesis", "")
        log.info("ArchitectureDesigner: selected '%s' for hypothesis", arch_name)
        return spec

    def design_custom(
        self,
        components: List[str],
        patterns: Optional[List[str]] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        """Create a custom architecture specification."""
        return {
            "name": "custom",
            "description": description or "Custom architecture",
            "components": components,
            "patterns": patterns or [],
            "interfaces": [],
            "hypothesis": "",
        }

    def list_architectures(self) -> List[str]:
        """Return names of all available architecture templates."""
        return list(_ARCHITECTURES.keys())

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve a named architecture template."""
        return dict(_ARCHITECTURES[name]) if name in _ARCHITECTURES else None

    def components_for(self, architecture_name: str) -> List[str]:
        """Return the components list for the named architecture."""
        spec = _ARCHITECTURES.get(architecture_name, {})
        return list(spec.get("components", []))

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _select_architecture(hypothesis: Dict[str, Any]) -> str:
        """Choose the best architecture template based on hypothesis keywords."""
        text = (
            hypothesis.get("hypothesis", "")
            + " "
            + hypothesis.get("domain", "")
            + " "
            + hypothesis.get("tech_a", "")
            + " "
            + hypothesis.get("tech_b", "")
        ).lower()

        for keyword, arch_name in _KEYWORD_MAP.items():
            if keyword in text:
                return arch_name

        return "pipeline"  # safe default


if __name__ == "__main__":
    print('Running architecture_designer.py')
