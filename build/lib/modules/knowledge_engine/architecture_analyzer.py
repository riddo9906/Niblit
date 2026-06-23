#!/usr/bin/env python3
"""
modules/knowledge_engine/architecture_analyzer.py

Extract high-level software architecture from a repository's directory
structure and import patterns.

Detected architectures:
    mvc          — controllers/ + models/ + views/ (or templates/)
    layered      — api/ + service/ + repository/  (or similar layering)
    microservices— multiple service sub-directories each with their own main
    event_driven — event_bus / event handlers / queue modules
    plugin       — plugin/ or extension/ directories
    monolithic   — single large source file
    library      — no main entry point, mostly utility modules

Results are stored as architecture templates for use during code generation.

Usage::

    from modules.knowledge_engine.architecture_analyzer import ArchitectureAnalyzer
    analyzer = ArchitectureAnalyzer()
    result = analyzer.analyze("/path/to/cloned/repo")
"""

import logging
import os
import re
from typing import Any, Dict, List

log = logging.getLogger("ArchitectureAnalyzer")

# ── heuristics ────────────────────────────────────────────────────────────────
_MVC_DIRS = {"controllers", "models", "views", "templates", "static"}
_LAYERED_DIRS = {"api", "service", "services", "repository", "repositories", "db", "database"}
_MICROSERVICE_SIGNALS = {"docker-compose", "kubernetes", "k8s", "helm"}
_EVENT_KEYWORDS = {"event_bus", "event_handler", "events", "queue", "message_broker", "pubsub"}
_PLUGIN_DIRS = {"plugins", "extensions", "addons"}


class ArchitectureAnalyzer:
    """Detect software architecture style from folder structure and file contents."""

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(self, directory: str) -> Dict[str, Any]:
        """
        Analyze *directory* and return architecture metadata.

        Returns dict with keys:
            path, architecture, confidence, components, signals
        """
        if not os.path.isdir(directory):
            return {"path": directory, "architecture": "unknown", "confidence": "none",
                    "components": [], "signals": []}

        top_dirs = self._top_dirs(directory)
        top_files = self._top_files(directory)
        all_names = {d.lower() for d in top_dirs} | {f.lower() for f in top_files}

        arch, confidence, components, signals = self._classify(directory, top_dirs, all_names)
        return {
            "path": directory,
            "architecture": arch,
            "confidence": confidence,
            "components": components,
            "signals": signals,
        }

    def analyze_multiple(
        self, directories: List[str]
    ) -> List[Dict[str, Any]]:
        return [self.analyze(d) for d in directories]

    def architecture_template(self, arch_name: str) -> str:
        """Return a plain-text template description for the named architecture."""
        templates = {
            "mvc": "controller layer → service layer → model layer → view/template layer",
            "layered": "api layer → service layer → repository layer → database layer",
            "microservices": "independent services ← api gateway → service mesh",
            "event_driven": "producer → event bus → consumer → state store",
            "plugin": "core engine + plugin loader + extensions registry",
            "monolithic": "single application module with embedded sub-systems",
            "library": "public API module + utility helpers + no entry point",
        }
        return templates.get(arch_name, "unknown architecture")

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _top_dirs(directory: str) -> List[str]:
        try:
            return [
                d for d in os.listdir(directory)
                if os.path.isdir(os.path.join(directory, d)) and not d.startswith(".")
            ]
        except OSError:
            return []

    @staticmethod
    def _top_files(directory: str) -> List[str]:
        try:
            return [
                f for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f)) and not f.startswith(".")
            ]
        except OSError:
            return []

    def _classify(
        self,
        directory: str,
        top_dirs: List[str],
        all_names: set,
    ):
        lower_dirs = {d.lower() for d in top_dirs}
        components: List[str] = []
        signals: List[str] = []

        # MVC
        mvc_hits = lower_dirs & _MVC_DIRS
        if len(mvc_hits) >= 2:
            components = sorted(mvc_hits)
            return "mvc", "high", components, signals

        # Layered / Clean architecture
        layered_hits = lower_dirs & _LAYERED_DIRS
        if len(layered_hits) >= 2:
            components = sorted(layered_hits)
            return "layered", "high", components, signals

        # Event-driven
        event_hits = all_names & _EVENT_KEYWORDS
        if event_hits:
            signals = sorted(event_hits)
            return "event_driven", "medium", list(lower_dirs), signals

        # Plugin
        plugin_hits = lower_dirs & _PLUGIN_DIRS
        if plugin_hits:
            return "plugin", "medium", sorted(plugin_hits), signals

        # Microservices
        ms_files = {f.lower().replace("-", "_") for f in self._top_files(directory)}
        ms_hits = {k for k in _MICROSERVICE_SIGNALS if k.replace("-", "_") in ms_files}
        if ms_hits or len([d for d in top_dirs if os.path.isfile(
                os.path.join(directory, d, "main.py"))]) >= 2:
            signals = sorted(ms_hits)
            return "microservices", "medium", list(lower_dirs), signals

        # Monolithic — one big Python file
        py_files = [f for f in self._top_files(directory) if f.endswith(".py")]
        if len(py_files) == 1:
            return "monolithic", "high", py_files, signals

        # Library fallback
        has_setup = any(f in all_names for f in {"setup.py", "pyproject.toml", "setup.cfg"})
        has_main = any(f in all_names for f in {"main.py", "__main__.py", "app.py"})
        if has_setup and not has_main:
            return "library", "medium", [], signals

        return "mixed", "low", list(lower_dirs[:5]), signals

    def find_pattern_files(self, directory: str, pattern: str) -> List[str]:
        """Return file paths whose basenames match the regex *pattern*.

        This method makes the ``re`` import functional: architecture analysis
        often needs to locate files by naming convention (e.g. ``*_controller.py``,
        ``*Service.java``) rather than fixed directory names.

        Parameters
        ----------
        directory:  Root directory to search (non-recursive, top-level only).
        pattern:    Python regex tested against the file *basename* only.

        Returns
        -------
        list[str]: Matching file paths sorted alphabetically.
        """
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return [f"invalid regex {pattern!r}: {exc}"]
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        return sorted(
            os.path.join(directory, n)
            for n in names
            if rx.search(n)
        )


if __name__ == "__main__":
    print('Running architecture_analyzer.py')
