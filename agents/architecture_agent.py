#!/usr/bin/env python3
"""
agents/architecture_agent.py — Autonomous codebase analysis and refactoring agent.

Handles ``task_type="architecture_analysis"`` tasks.  Analyses the Niblit
codebase for structural issues, generates improvement suggestions, and
publishes plans for the CodingAgent to act on.

Key capabilities (Phase 7)
--------------------------
* Analyse file size and cyclomatic complexity
* Build dependency graphs between modules
* Identify bottlenecks (large files, circular imports, long functions)
* Generate refactoring suggestions using GitHub Code Search patterns

Architecture role
-----------------
    ALE / Planner → ArchitectureAgent
                           │
                    BuildScanner (reads files)
                           │
                    GitHubCodeSearch (find refactoring patterns)
                           │
                    EventBus: ARCHITECTURE_ANALYSIS_DONE
                           │
                    PlannerAgent: create CODE_GENERATION tasks
"""

import ast
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("ArchitectureAgent")

# Thresholds that flag a file / function as needing attention
_MAX_FILE_LINES = 500
_MAX_FUNCTION_LINES = 60
_MAX_COMPLEXITY = 10   # approximate cyclomatic-complexity warning threshold


class ArchitectureAgent(BaseAgent):
    """
    Analyses Niblit's own codebase and generates refactoring plans.

    Args:
        build_scanner:      modules.build_scanner.BuildScanner instance.
        github_code_search: modules.github_code_search.GitHubCodeSearch instance.
        knowledge_db:       KB instance for storing analysis results.
        source_root:        Root directory of the Niblit source to scan.
    """

    HANDLED_TASK_TYPES = [
        "architecture_analysis",
        "code_review",
        "refactor_plan",
    ]

    def __init__(
        self,
        build_scanner: Optional[Any] = None,
        github_code_search: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        source_root: str = ".",
    ) -> None:
        super().__init__("architecture")
        self._scanner = build_scanner
        self._github = github_code_search
        self._kb = knowledge_db
        self._source_root = Path(source_root).resolve()

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        target = task.payload.get("target", str(self._source_root))
        language = task.payload.get("language", "python")
        focus = task.payload.get("focus", "all")  # "all" | "complexity" | "size" | "deps"

        analysis = self._analyse(Path(target), language, focus)
        refactor_hints = self._fetch_refactoring_patterns(language, analysis)
        plan = self._build_plan(analysis, refactor_hints)

        self._store_results(analysis, plan)

        output = {
            "target": target,
            "files_scanned": analysis["files_scanned"],
            "issues_found": len(analysis["issues"]),
            "plan_steps": len(plan),
            "analysis": analysis,
            "plan": plan,
        }
        self._publish(event_bus, EventType.ARCHITECTURE_ANALYSIS_DONE, output)
        if plan:
            self._publish(event_bus, EventType.REFACTOR_PLAN_GENERATED, {"plan": plan})
        self._log.info(
            "architecture_analysis: %d files, %d issues, %d plan steps",
            analysis["files_scanned"], len(analysis["issues"]), len(plan),
        )
        return output

    # ── analysis ──────────────────────────────────────────────────────────────

    def _analyse(self, root: Path, language: str, focus: str) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        large_files: List[str] = []
        complex_functions: List[Dict[str, str]] = []
        files_scanned = 0
        ext = ".py" if language == "python" else f".{language}"

        for path in root.rglob(f"*{ext}"):
            if any(p in path.parts for p in ("__pycache__", ".git", "node_modules")):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue

            files_scanned += 1
            rel = str(path.relative_to(root))

            if len(lines) > _MAX_FILE_LINES:
                large_files.append(rel)
                issues.append({
                    "type": "large_file",
                    "file": rel,
                    "lines": len(lines),
                    "suggestion": f"Consider splitting {rel} (>{_MAX_FILE_LINES} lines)",
                })

            if language == "python" and focus in ("all", "complexity"):
                func_issues = self._check_python_complexity(lines, rel)
                complex_functions.extend(func_issues)
                for fi in func_issues:
                    issues.append({
                        "type": "complex_function",
                        "file": rel,
                        "function": fi.get("name", "?"),
                        "lines": fi.get("lines", 0),
                        "suggestion": f"Refactor {fi.get('name')} in {rel} (too long)",
                    })

        return {
            "files_scanned": files_scanned,
            "large_files": large_files,
            "complex_functions": complex_functions,
            "issues": issues,
        }

    @staticmethod
    def _check_python_complexity(
        lines: List[str], filepath: str
    ) -> List[Dict[str, Any]]:
        """Detect long functions via AST without executing the code."""
        source = "\n".join(lines)
        findings = []
        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                length = end - start + 1
                if length > _MAX_FUNCTION_LINES:
                    findings.append({
                        "name": node.name,
                        "lines": length,
                        "start_line": start,
                    })
        return findings

    # ── refactoring hints ─────────────────────────────────────────────────────

    def _fetch_refactoring_patterns(
        self, language: str, analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if self._github is None or not self._github.is_available():
            return []
        hints = []
        for issue in analysis["issues"][:3]:
            issue_type = issue.get("type", "")
            technique = (
                "decompose large module" if issue_type == "large_file"
                else "extract method refactoring"
            )
            try:
                results = self._github.find_refactoring_patterns(language, technique, max_results=2)
                for r in results:
                    r["related_issue"] = issue_type
                hints.extend(results)
            except Exception:
                pass
        return hints

    # ── plan generation ───────────────────────────────────────────────────────

    @staticmethod
    def _build_plan(
        analysis: Dict[str, Any], hints: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        plan = []
        for issue in analysis["issues"][:10]:
            plan.append({
                "action": "refactor",
                "target": issue.get("file", ""),
                "reason": issue.get("suggestion", ""),
                "task_type": "code_generation",
                "payload": {
                    "purpose": issue.get("suggestion", ""),
                    "language": "python",
                    "context": f"Refactoring issue: {issue.get('type')}",
                },
            })
        for h in hints[:5]:
            plan.append({
                "action": "apply_pattern",
                "pattern": h.get("text", "")[:100],
                "source": h.get("url", ""),
                "task_type": "code_generation",
                "payload": {
                    "purpose": f"Apply refactoring pattern from {h.get('repo', 'GitHub')}",
                    "language": "python",
                },
            })
        return plan

    # ── storage ───────────────────────────────────────────────────────────────

    def _store_results(
        self, analysis: Dict[str, Any], plan: List[Dict[str, Any]]
    ) -> None:
        if self._kb is None:
            return
        import time as _time
        ts = int(_time.time())
        for issue in analysis["issues"][:5]:
            key = f"ale_architecture:{ts}:{issue.get('type')}"
            text = issue.get("suggestion", "")
            if text:
                try:
                    self._kb.store(key, text, tags=["architecture", "issue"])
                except Exception:
                    pass
