"""ResearchAgent — autonomous research over topics using simulated sources.

Usage example::

    agent = ResearchAgent()
    result = agent.research("neural architecture search")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

log = logging.getLogger("ResearchAgent")

_SIMULATED_SOURCES = [
    "arxiv.org",
    "papers.niblit.ai",
    "github.com/niblit",
    "docs.niblit.ai",
]


class ResearchAgent:
    """Conducts topic research and maintains a history of findings."""

    def __init__(self) -> None:
        self._history: List[Dict[str, Any]] = []

    # ── public API ──

    def research(self, topic: str) -> Dict[str, Any]:
        """Research *topic* and return findings dict."""
        log.info("ResearchAgent: researching %s", topic[:60])
        findings = [
            f"Finding 1: {topic} has shown promising results in recent studies.",
            f"Finding 2: Key techniques in {topic} include iterative refinement.",
            f"Finding 3: Benchmarks for {topic} indicate ~15% improvement over baseline.",
        ]
        result: Dict[str, Any] = {
            "topic": topic,
            "findings": findings,
            "sources": _SIMULATED_SOURCES[:2],
            "researched_at": time.time(),
        }
        self._history.append(result)
        return result

    def get_history(self) -> List[Dict[str, Any]]:
        """Return all past research results."""
        return list(self._history)
