#!/usr/bin/env python3
"""
modules/knowledge_engine/learning_scheduler.py

Coordinate and schedule the full SEKE pipeline.

The scheduler ties together:
    RepoScanner → RepoDownloader → CodeParser → PatternExtractor
    → ArchitectureAnalyzer → EmbeddingPipeline → KnowledgeGraphBuilder

It can run one-shot or in a continuous loop with configurable intervals.

Usage::

    from modules.knowledge_engine.learning_scheduler import LearningScheduler
    scheduler = LearningScheduler(query="machine learning language:python")
    scheduler.run_once()                        # process one batch
    scheduler.run_loop(interval_seconds=3600)   # hourly background loop
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

from modules.knowledge_engine.repo_scanner import RepoScanner
from modules.knowledge_engine.repo_downloader import RepoDownloader
from modules.knowledge_engine.code_parser import CodeParser
from modules.knowledge_engine.pattern_extractor import PatternExtractor
from modules.knowledge_engine.architecture_analyzer import ArchitectureAnalyzer
from modules.knowledge_engine.embedding_pipeline import EmbeddingPipeline
from modules.knowledge_engine.knowledge_graph_builder import KnowledgeGraphBuilder

log = logging.getLogger("LearningScheduler")

_DEFAULT_QUERY = "machine learning language:python stars:>200"
_DEFAULT_MAX_REPOS = 5
_DEFAULT_INTERVAL = 3600  # 1 hour

class LearningScheduler:
    """
    Orchestrate the Self-Expanding Knowledge Engine pipeline.

    Args:
        query:          GitHub search query used by RepoScanner.
        max_repos:      Maximum repos to process per cycle.
        knowledge_db:   Optional KnowledgeDB instance — patterns/architectures
                        are also saved there when provided.
        on_cycle_done:  Optional callback(cycle_result) called after each cycle.
    """

    def __init__(
        self,
        query: str = _DEFAULT_QUERY,
        max_repos: int = _DEFAULT_MAX_REPOS,
        knowledge_db: Optional[Any] = None,
        on_cycle_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.query = query
        self.max_repos = max_repos
        self.knowledge_db = knowledge_db
        self.on_cycle_done = on_cycle_done
        self._running = False

        # Sub-system instances
        self.scanner = RepoScanner()
        self.downloader = RepoDownloader()
        self.parser = CodeParser()
        self.extractor = PatternExtractor()
        self.arch_analyzer = ArchitectureAnalyzer()
        self.embedder = EmbeddingPipeline()
        self.graph = KnowledgeGraphBuilder()

        # Stats
        self.cycles_completed: int = 0
        self.total_repos_processed: int = 0
        self.total_patterns_found: int = 0

    # ── public API ────────────────────────────────────────────────────────────

    def run_once(self) -> Dict[str, Any]:
        """
        Execute one full pipeline cycle.

        Returns a summary dict.
        """
        log.info("LearningScheduler: starting cycle %d", self.cycles_completed + 1)
        cycle_result: Dict[str, Any] = {
            "cycle": self.cycles_completed + 1,
            "repos_found": 0,
            "repos_processed": 0,
            "patterns": {},
            "architectures": [],
            "chunks_embedded": 0,
            "graph_edges": 0,
        }

        # 1 — Scan
        repos = self.scanner.search(self.query, max_results=self.max_repos)
        cycle_result["repos_found"] = len(repos)
        if not repos:
            log.info("LearningScheduler: no repos found for query '%s'", self.query)
            self.cycles_completed += 1
            return cycle_result

        for repo in repos:
            self._process_repo(repo, cycle_result)

        # Finalise stats
        self.cycles_completed += 1
        self.total_repos_processed += cycle_result["repos_processed"]
        self.total_patterns_found += sum(cycle_result["patterns"].values())
        cycle_result["graph_summary"] = self.graph.summary()

        log.info(
            "LearningScheduler: cycle %d done — %d repos, %d patterns, %d chunks",
            self.cycles_completed,
            cycle_result["repos_processed"],
            sum(cycle_result["patterns"].values()),
            cycle_result["chunks_embedded"],
        )

        if self.on_cycle_done:
            try:
                self.on_cycle_done(cycle_result)
            except Exception as exc:  # noqa: BLE001
                log.warning("LearningScheduler: on_cycle_done callback failed: %s", exc)

        return cycle_result

    def run_loop(
        self,
        interval_seconds: int = _DEFAULT_INTERVAL,
        max_cycles: Optional[int] = None,
    ) -> None:
        """
        Run the pipeline in a continuous loop with *interval_seconds* sleep
        between cycles.  Runs indefinitely unless *max_cycles* is set.
        """
        self._running = True
        log.info("LearningScheduler: entering continuous loop (interval=%ds)", interval_seconds)
        try:
            while self._running:
                self.run_once()
                if max_cycles and self.cycles_completed >= max_cycles:
                    break
                log.info(
                    "LearningScheduler: sleeping %ds before next cycle", interval_seconds
                )
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            log.info("LearningScheduler: loop interrupted by user")
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the scheduler loop to stop after the current cycle."""
        self._running = False

    def stats(self) -> Dict[str, Any]:
        return {
            "cycles_completed": self.cycles_completed,
            "total_repos_processed": self.total_repos_processed,
            "total_patterns_found": self.total_patterns_found,
            "graph": self.graph.summary(),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _process_repo(self, repo: Dict[str, Any], cycle_result: Dict[str, Any]) -> None:
        """Clone, parse, extract patterns and embeddings for a single repo."""
        clone_url = repo.get("clone_url", "")
        name = repo.get("full_name", "").replace("/", "_") or "repo"
        if not clone_url:
            return

        # 2 — Download
        local_path = self.downloader.clone(clone_url, name=name)
        if not local_path:
            log.debug("LearningScheduler: clone failed for %s", clone_url)
            return

        try:
            # 3 — Parse
            parse_results = self.parser.parse_directory(local_path, max_files=50)

            # 4 — Extract patterns
            patterns = self.extractor.analyse_directory_patterns(parse_results)
            for k, v in patterns.items():
                cycle_result["patterns"][k] = cycle_result["patterns"].get(k, 0) + v

            # 5 — Architecture
            arch = self.arch_analyzer.analyze(local_path)
            cycle_result["architectures"].append({
                "repo": name,
                "architecture": arch["architecture"],
                "confidence": arch["confidence"],
            })

            # 6 — Embeddings
            added = self.embedder.ingest_batch(parse_results)
            cycle_result["chunks_embedded"] += added

            # 7 — Knowledge graph
            graph_edges = self.graph.load_from_parse_results(parse_results)
            cycle_result["graph_edges"] = (
                cycle_result.get("graph_edges", 0) + graph_edges
            )

            # 8 — Persist to KnowledgeDB if available
            if self.knowledge_db:
                self._save_to_kb(name, patterns, arch)

            cycle_result["repos_processed"] += 1
        finally:
            self.downloader.cleanup(local_path)

    def _save_to_kb(
        self,
        repo_name: str,
        patterns: Dict[str, int],
        arch: Dict[str, Any],
    ) -> None:
        try:
            for pattern_name, count in patterns.items():
                self.knowledge_db.save(
                    f"seke:pattern:{repo_name}:{pattern_name}",
                    f"{pattern_name} pattern seen {count}x in {repo_name}",
                    tags=["seke", "pattern"],
                )
            self.knowledge_db.save(
                f"seke:architecture:{repo_name}",
                f"{repo_name} uses {arch['architecture']} architecture (confidence: {arch['confidence']})",
                tags=["seke", "architecture"],
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("LearningScheduler: KB save failed: %s", exc)
