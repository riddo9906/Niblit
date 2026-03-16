"""ResearchAgent — civilisation agent specialised for knowledge research.

Usage example::

    agent = ResearchAgent("r1", "researcher")
    result = agent.execute({"goal": "survey transformer models"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from .base_agent import BaseAgent

log = logging.getLogger("ResearchAgent")

_MOCK_REPOS = [
    {"name": "niblit-core", "stars": 120, "topic": "general"},
    {"name": "niblit-research", "stars": 85, "topic": "research"},
    {"name": "transformer-bench", "stars": 340, "topic": "transformers"},
]


class ResearchAgent(BaseAgent):
    """Conducts literature and repository research."""

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute research task; return insights/sources/confidence dict."""
        goal = task.get("goal", task.get("topic", "unknown"))
        log.info("ResearchAgent %s: researching %s", self._agent_id, goal[:60])
        repos = self.search_repositories(goal)
        findings = [f"Finding: {goal} is well studied with {len(repos)} relevant repositories."]
        result = {
            "insights": findings,
            "sources": [r["name"] for r in repos],
            "confidence": 0.75,
            "researched_at": time.time(),
        }
        self._record_task()
        return result

    def search_repositories(self, topic: str) -> List[Dict[str, Any]]:
        """Return simulated repository results for *topic*."""
        return [r for r in _MOCK_REPOS if topic.lower() in r["topic"] or True][:3]

    def analyze_findings(self, findings: List[Any]) -> Dict[str, Any]:
        """Analyse a list of findings and return summary dict."""
        return {
            "finding_count": len(findings),
            "summary": f"Analysed {len(findings)} findings.",
            "confidence": min(1.0, 0.5 + len(findings) * 0.05),
        }
