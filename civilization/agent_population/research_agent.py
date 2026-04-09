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

# Fallback repo list used only when GitHubCodeSearch is unavailable.
_FALLBACK_REPOS = [
    {"name": "niblit-core", "stars": 120, "topic": "general"},
    {"name": "niblit-research", "stars": 85, "topic": "research"},
    {"name": "transformer-bench", "stars": 340, "topic": "transformers"},
]


class ResearchAgent(BaseAgent):
    """Conducts literature and repository research.

    Uses ``modules.github_code_search.GitHubCodeSearch`` for live repository
    discovery when available; falls back to a static list when the module or
    network is unreachable.

    An optional ``github_code_search`` attribute (``GitHubCodeSearch`` instance)
    can be set after construction by ``CivilizationController`` to reuse the
    shared client rather than instantiating a new one per call.
    """

    def __init__(self, agent_id: str, role: str) -> None:
        super().__init__(agent_id, role)
        # Injected by CivilizationController when a shared instance is available.
        self.github_code_search: Optional[Any] = None

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute research task; return insights/sources/confidence dict."""
        goal = task.get("goal", task.get("topic", "unknown"))
        log.info("ResearchAgent %s: researching %s", self._agent_id, goal[:60])
        repos = self.search_repositories(goal)
        findings = [
            f"Finding: '{goal}' is studied across {len(repos)} relevant repositories.",
        ]
        # Enrich findings with repo descriptions if available
        for repo in repos[:3]:
            desc = repo.get("description") or repo.get("topic", "")
            name = repo.get("name") or repo.get("full_name", "")
            if name and desc:
                findings.append(f"Repo {name}: {desc[:120]}")

        # Synthesize a richer insight via the HuggingFace inference provider when
        # available.  The LLM summary is prepended so it surfaces first in the
        # ingest pipeline (SelfImprovementOrchestrator → ALE topics).
        repo_names = ", ".join(
            r.get("name") or r.get("full_name", "") for r in repos[:5] if r.get("name") or r.get("full_name")
        )
        llm_prompt = (
            f"In 2 concise sentences, summarize the key technical insights about: '{goal}'. "
            f"Relevant repositories: {repo_names or 'none found'}. "
            "Focus on what an autonomous AI system would learn from this topic."
        )
        llm_summary = self._ask_llm(llm_prompt)
        if llm_summary:
            # Strip [HFBrain Error] prefix if the provider returned a soft error string
            if not llm_summary.startswith("[HFBrain"):
                findings.insert(0, f"LLM Synthesis: {llm_summary[:300]}")

        result = {
            "insights": findings,
            "sources": [r.get("name") or r.get("full_name", "") for r in repos],
            "confidence": min(0.95, 0.60 + len(repos) * 0.05),
            "researched_at": time.time(),
        }
        self._record_task()
        return result

    def search_repositories(self, topic: str) -> List[Dict[str, Any]]:
        """Return repository results for *topic*.

        Prefers the injected ``self.github_code_search`` instance when set;
        otherwise instantiates a fresh ``GitHubCodeSearch``.  Falls back to
        the static fallback list if neither is available or raises.
        """
        try:
            gcs = self.github_code_search
            if gcs is None:
                from modules.github_code_search import GitHubCodeSearch
                gcs = GitHubCodeSearch()
            raw = gcs.search_repos(topic, max_results=5)
            if raw:
                # Normalise to a consistent {"name", "description", "stars"} shape
                normalized: List[Dict[str, Any]] = []
                for r in raw[:5]:
                    normalized.append({
                        "name": r.get("repo") or r.get("name", ""),
                        "full_name": r.get("repo") or r.get("full_name", ""),
                        "description": r.get("text", ""),
                        "stars": r.get("stars", 0),
                        "url": r.get("url", ""),
                    })
                return normalized
        except Exception as exc:
            log.debug(
                "ResearchAgent %s: GitHubCodeSearch unavailable (%s), using fallback",
                self._agent_id, exc,
            )
        # Fallback: return static list (always matches — same behaviour as before)
        return list(_FALLBACK_REPOS)[:3]

    def analyze_findings(self, findings: List[Any]) -> Dict[str, Any]:
        """Analyse a list of findings and return summary dict."""
        return {
            "finding_count": len(findings),
            "summary": f"Analysed {len(findings)} findings.",
            "confidence": min(1.0, 0.5 + len(findings) * 0.05),
        }
