#!/usr/bin/env python3
"""
modules/ai_dev_lab/research_agent.py

Gather supporting evidence for hypotheses from GitHub, Stack Overflow,
and documentation sources.

Uses existing Niblit API clients:
    - GitHubCodeSearch  (modules/github_code_search.py)
    - StackOverflowSearch (modules/stackoverflow_search.py)
    - InternetManager   (modules/internet_manager.py)

Usage::

    from modules.ai_dev_lab.research_agent import ResearchAgent
    agent = ResearchAgent()
    findings = agent.research("graph neural networks for dependency resolution")
"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("ResearchAgent")


class ResearchAgent:
    """
    Gather research evidence from multiple sources.

    All sources are optional — the agent degrades gracefully when
    external APIs are unavailable.
    """

    def __init__(
        self,
        github_search: Optional[Any] = None,
        stackoverflow: Optional[Any] = None,
        internet: Optional[Any] = None,
    ) -> None:
        self._github = self._init_github(github_search)
        self._so = self._init_so(stackoverflow)
        self._internet = self._init_internet(internet)

    # ── public API ────────────────────────────────────────────────────────────

    def research(
        self, topic: str, max_results: int = 5
    ) -> Dict[str, Any]:
        """
        Research a topic from all available sources.

        Returns dict with keys:
            topic, github, stackoverflow, web, summary
        """
        result: Dict[str, Any] = {
            "topic": topic,
            "github": [],
            "stackoverflow": [],
            "web": [],
            "summary": "",
        }

        # 1 — GitHub
        if self._github is not None:
            try:
                items = self._github.search_code(topic, max_results=max_results)
                result["github"] = [
                    {"name": i.get("name", ""), "snippet": i.get("text_match", "")[:200]}
                    for i in (items or [])
                ]
            except Exception as exc:  # noqa: BLE001
                log.debug("ResearchAgent: GitHub search failed: %s", exc)

        # 2 — StackOverflow
        if self._so is not None:
            try:
                items = self._so.search(topic, max_results=max_results)
                result["stackoverflow"] = [
                    {"title": i.get("title", ""), "link": i.get("link", "")}
                    for i in (items or [])
                ]
            except Exception as exc:  # noqa: BLE001
                log.debug("ResearchAgent: SO search failed: %s", exc)

        # 3 — Web
        if self._internet is not None:
            try:
                items = self._internet.search(topic, max_results=max_results)
                result["web"] = [
                    {"text": (i.get("text", str(i)) if isinstance(i, dict) else str(i))[:200]}
                    for i in (items or [])
                ]
            except Exception as exc:  # noqa: BLE001
                log.debug("ResearchAgent: Internet search failed: %s", exc)

        # Build summary
        all_snippets = (
            [g["snippet"] for g in result["github"] if g.get("snippet")]
            + [s["title"] for s in result["stackoverflow"] if s.get("title")]
            + [w["text"] for w in result["web"] if w.get("text")]
        )
        if all_snippets:
            result["summary"] = " | ".join(all_snippets[:3])

        return result

    def synthesize(
        self,
        findings: Dict[str, Any],
    ) -> str:
        """
        Combine research findings into a concise synthesis string.
        """
        parts: List[str] = [f"Research on: {findings.get('topic', '')}"]
        if findings.get("github"):
            parts.append(f"GitHub ({len(findings['github'])} results)")
        if findings.get("stackoverflow"):
            parts.append(f"StackOverflow ({len(findings['stackoverflow'])} results)")
        if findings.get("web"):
            parts.append(f"Web ({len(findings['web'])} results)")
        if findings.get("summary"):
            parts.append(f"Summary: {findings['summary'][:300]}")
        return " | ".join(parts)

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _init_github(provided: Optional[Any]) -> Optional[Any]:
        if provided is not None:
            return provided
        try:
            from modules.github_code_search import GitHubCodeSearch  # type: ignore[import]
            return GitHubCodeSearch()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _init_so(provided: Optional[Any]) -> Optional[Any]:
        if provided is not None:
            return provided
        try:
            from modules.stackoverflow_search import StackOverflowSearch  # type: ignore[import]
            return StackOverflowSearch()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _init_internet(provided: Optional[Any]) -> Optional[Any]:
        if provided is not None:
            return provided
        try:
            from modules.internet_manager import InternetManager  # type: ignore[import]
            return InternetManager()
        except Exception:  # noqa: BLE001
            return None
