"""ResearchAgent — civilisation agent specialised for knowledge research.

Usage example::

    agent = ResearchAgent("r1", "researcher")
    result = agent.execute({"goal": "survey transformer models"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent

log = logging.getLogger("ResearchAgent")

_MOCK_REPOS = [
    {"name": "niblit-core", "stars": 120, "topic": "general"},
    {"name": "niblit-research", "stars": 85, "topic": "research"},
    {"name": "transformer-bench", "stars": 340, "topic": "transformers"},
]


class ResearchAgent(BaseAgent):
    """Conducts literature and repository research.

    An optional ``github_code_search`` attribute (``GitHubCodeSearch`` instance)
    can be set after construction to enable live GitHub repository search.  When
    unavailable the agent falls back to a small static mock repository list.
    """

    def __init__(self, agent_id: str, role: str) -> None:
        super().__init__(agent_id, role)
        # Injected by CivilizationController when available
        self.github_code_search: Optional[Any] = None

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute research task; return insights/sources/confidence dict."""
        goal = task.get("goal", task.get("topic", "unknown"))
        log.info("ResearchAgent %s: researching %s", self._agent_id, goal[:60])
        repos = self.search_repositories(goal)
        findings = [
            f"Research: '{goal}' — found {len(repos)} relevant sources via civilization research agent."
        ]
        for r in repos[:3]:
            name = r.get("name") or r.get("repo") or r.get("text", "")[:80]
            if name:
                findings.append(f"Source: {name}")
        result = {
            "insights": findings,
            "sources": [
                r.get("name") or r.get("repo") or r.get("text", "")[:60]
                for r in repos
            ],
            "confidence": 0.75 if repos else 0.4,
            "researched_at": time.time(),
        }
        self._record_task()
        return result

    def search_repositories(self, topic: str) -> List[Dict[str, Any]]:
        """Search for repositories relevant to *topic*.

        Uses the injected ``github_code_search`` (real GitHub API) when available;
        falls back to the static mock list otherwise.
        """
        # Real search via GitHubCodeSearch
        if self.github_code_search is not None:
            try:
                raw = self.github_code_search.search_code(
                    f"{topic} multi-agent OR evolutionary OR civilization",
                    language="python",
                    max_results=5,
                )
                if raw:
                    log.debug(
                        "ResearchAgent %s: GitHub search returned %d results",
                        self._agent_id, len(raw),
                    )
                    return raw
            except Exception as exc:
                log.debug("ResearchAgent %s: GitHub search failed — %s", self._agent_id, exc)

        # Fallback: static mock
        return [r for r in _MOCK_REPOS if topic.lower() in r["topic"]][:3] or _MOCK_REPOS[:3]

    def analyze_findings(self, findings: List[Any]) -> Dict[str, Any]:
        """Analyse a list of findings and return summary dict."""
        return {
            "finding_count": len(findings),
            "summary": f"Analysed {len(findings)} findings.",
            "confidence": min(1.0, 0.5 + len(findings) * 0.05),
        }
