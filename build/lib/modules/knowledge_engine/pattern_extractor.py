#!/usr/bin/env python3
"""
modules/knowledge_engine/pattern_extractor.py

Identify reusable programming patterns from parsed Python ASTs.

Detected patterns (heuristic-based, no external dependencies):
    - singleton
    - factory
    - observer
    - dependency_injection
    - pipeline
    - decorator_pattern
    - context_manager
    - repository_pattern

Usage::

    from modules.knowledge_engine.pattern_extractor import PatternExtractor
    extractor = PatternExtractor()
    patterns = extractor.detect_patterns(code_parser_result)
    all_patterns = extractor.analyse_directory_patterns(list_of_parse_results)
"""

import logging
import re
from typing import Any, Dict, List

log = logging.getLogger("PatternExtractor")

# ── pattern detection rules ───────────────────────────────────────────────────
# Each rule is a tuple of (pattern_name, list of heuristic checks).
# A check is a callable(parse_result) → bool.

_SINGLETON_KEYWORDS = {"_instance", "get_instance", "getInstance", "_singleton"}
_FACTORY_KEYWORDS = {"create", "build", "make", "factory", "from_"}
_OBSERVER_KEYWORDS = {"subscribe", "notify", "on_event", "listeners", "handlers", "emit"}
_DI_KEYWORDS = {"inject", "container", "provider", "register", "resolve"}
_PIPELINE_KEYWORDS = {"pipeline", "pipe", "stage", "transform", "processor", "step"}
_CONTEXT_KEYWORDS = {"__enter__", "__exit__", "contextmanager"}
_REPO_KEYWORDS = {"repository", "get_by_id", "find_by", "save", "delete", "query"}


class PatternExtractor:
    """
    Detect common design patterns from CodeParser output.

    All detection is done by inspecting names (functions, classes, methods)
    and import lists.  No code is executed.
    """

    # ── public API ────────────────────────────────────────────────────────────

    def detect_patterns(self, parse_result: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Detect patterns in a single parsed file.

        Args:
            parse_result: Output of CodeParser.parse_file().

        Returns:
            List of dicts with keys: pattern, confidence, location.
        """
        found: List[Dict[str, str]] = []

        all_names = self._collect_names(parse_result)
        classes = parse_result.get("classes", [])
        imports = set(parse_result.get("imports", []))

        found += self._check_singleton(all_names, classes)
        found += self._check_factory(all_names, classes)
        found += self._check_observer(all_names)
        found += self._check_dependency_injection(all_names, imports)
        found += self._check_pipeline(all_names, classes)
        found += self._check_context_manager(all_names)
        found += self._check_repository(all_names, classes)

        # Deduplicate by pattern name
        seen: set = set()
        unique: List[Dict[str, str]] = []
        for item in found:
            if item["pattern"] not in seen:
                seen.add(item["pattern"])
                unique.append(item)
        return unique

    def analyse_directory_patterns(
        self, parse_results: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Aggregate pattern counts across a list of parse results.

        Returns a dict mapping pattern name → occurrence count.
        """
        counts: Dict[str, int] = {}
        for result in parse_results:
            for p in self.detect_patterns(result):
                counts[p["pattern"]] = counts.get(p["pattern"], 0) + 1
        return counts

    def top_patterns(
        self, parse_results: List[Dict[str, Any]], top_n: int = 5
    ) -> List[str]:
        """Return the *top_n* most common pattern names."""
        counts = self.analyse_directory_patterns(parse_results)
        return sorted(counts, key=lambda k: counts[k], reverse=True)[:top_n]

    # ── detection helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _collect_names(result: Dict[str, Any]) -> set:
        names: set = set()
        for f in result.get("functions", []):
            names.add(f["name"].lower())
        for c in result.get("classes", []):
            names.add(c["name"].lower())
            for m in c.get("methods", []):
                names.add(m.lower())
        return names

    @staticmethod
    def _check_singleton(names: set, classes: List[Dict]) -> List[Dict[str, str]]:
        for kw in _SINGLETON_KEYWORDS:
            if kw.lower() in names:
                return [{"pattern": "singleton", "confidence": "high", "location": kw}]
        # Class-level: look for _instance class attribute heuristic
        for cls in classes:
            if any(re.search(r"_?instance", m, re.I) for m in cls.get("methods", [])):
                return [{"pattern": "singleton", "confidence": "medium", "location": cls["name"]}]
        return []

    @staticmethod
    def _check_factory(names: set, classes: List[Dict]) -> List[Dict[str, str]]:
        matches = names & {kw.lower() for kw in _FACTORY_KEYWORDS}
        if matches:
            return [{"pattern": "factory", "confidence": "medium", "location": next(iter(matches))}]
        return []

    @staticmethod
    def _check_observer(names: set) -> List[Dict[str, str]]:
        matches = names & {kw.lower() for kw in _OBSERVER_KEYWORDS}
        if len(matches) >= 2:
            return [{"pattern": "observer", "confidence": "high", "location": str(matches)}]
        if matches:
            return [{"pattern": "observer", "confidence": "low", "location": str(matches)}]
        return []

    @staticmethod
    def _check_dependency_injection(names: set, imports: set) -> List[Dict[str, str]]:
        name_matches = names & {kw.lower() for kw in _DI_KEYWORDS}
        import_matches = imports & {"dependency_injector", "injector", "pinject", "lagom"}
        if name_matches or import_matches:
            return [{"pattern": "dependency_injection", "confidence": "medium",
                     "location": str(name_matches | import_matches)}]
        return []

    @staticmethod
    def _check_pipeline(names: set, classes: List[Dict]) -> List[Dict[str, str]]:
        matches = names & {kw.lower() for kw in _PIPELINE_KEYWORDS}
        if matches:
            return [{"pattern": "pipeline", "confidence": "medium", "location": str(matches)}]
        return []

    @staticmethod
    def _check_context_manager(names: set) -> List[Dict[str, str]]:
        if "__enter__" in names and "__exit__" in names:
            return [{"pattern": "context_manager", "confidence": "high", "location": "__enter__/__exit__"}]
        if "contextmanager" in names:
            return [{"pattern": "context_manager", "confidence": "medium", "location": "contextmanager decorator"}]
        return []

    @staticmethod
    def _check_repository(names: set, classes: List[Dict]) -> List[Dict[str, str]]:
        matches = names & {kw.lower() for kw in _REPO_KEYWORDS}
        if len(matches) >= 3:
            return [{"pattern": "repository_pattern", "confidence": "high", "location": str(matches)}]
        return []


if __name__ == "__main__":
    print('Running pattern_extractor.py')
