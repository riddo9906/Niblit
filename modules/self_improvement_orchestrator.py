#!/usr/bin/env python3
"""
SELF-IMPROVEMENT ORCHESTRATOR
Coordinates Niblit's autonomous learning, testing, and (optionally) deployment.

The orchestrator ties together:
- AutonomousLearningEngine  — background research and knowledge building
- EvolveEngine              — continuous self-evolution steps
- ReflectModule             — structured reflection on recent activity
- AgenticWorkflow           — multi-step task pipelines
- AutonomousGitHubIntegration — push improvements back to GitHub (optional)

It can be driven in two modes:
1. **Single cycle** — call ``run_improvement_cycle()`` on demand.
2. **Continuous**   — call ``start()`` / ``stop()`` for a background thread.

All write operations via GitHub are guarded by the dry_run flag on the
AutonomousGitHubIntegration instance so nothing is pushed unless explicitly
configured.
"""

import logging
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("SelfImprovementOrchestrator")

class SelfImprovementOrchestrator:
    """
    Coordinates all of Niblit's self-improvement subsystems.

    Parameters
    ----------
    ale : AutonomousLearningEngine, optional
    evolve : EvolveEngine, optional
    reflect : ReflectModule, optional
    agentic : AgenticWorkflow, optional
    github : AutonomousGitHubIntegration, optional
    db : database, optional
    cycle_interval : int
        Seconds between automatic improvement cycles (default: 600).
    """

    def __init__(
        self,
        ale=None,
        evolve=None,
        reflect=None,
        agentic=None,
        github=None,
        db=None,
        cycle_interval: int = 600,
    ):
        self.ale = ale
        self.evolve = evolve
        self.reflect = reflect
        self.agentic = agentic
        self.github = github
        self.db = db
        self.cycle_interval = cycle_interval

        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cycle_count = 0
        self._history: List[Dict[str, Any]] = []

        log.info("[SelfImprovementOrchestrator] Initialized")

    # ------------------------------------------------------------------
    # Single improvement cycle
    # ------------------------------------------------------------------

    def run_improvement_cycle(self) -> Dict[str, Any]:
        """
        Execute one full improvement cycle across all available subsystems.

        Returns a dict summarising what happened.
        """
        self._cycle_count += 1
        ts = datetime.now(timezone.utc).isoformat()
        record: Dict[str, Any] = {
            "cycle": self._cycle_count,
            "ts": ts,
            "steps": {},
            "errors": [],
        }

        # 1. Autonomous Learning Engine — run one learn sequence
        if self.ale:
            try:
                result = self.ale.run_self_learn_sequence()
                record["steps"]["ale"] = str(result)[:120]
            except Exception as exc:
                record["errors"].append(f"ale: {exc}")
                log.warning("[Orchestrator] ALE step failed: %s", exc)

        # 2. EvolveEngine — one evolution step
        if self.evolve:
            try:
                result = self.evolve.step()
                record["steps"]["evolve"] = result.get("direction", "")[:80]
            except Exception as exc:
                record["errors"].append(f"evolve: {exc}")
                log.warning("[Orchestrator] EvolveEngine step failed: %s", exc)

        # 3. ReflectModule — reflect on recent activity
        if self.reflect:
            try:
                events = self._gather_recent_events()
                result = self.reflect.auto_reflect(events)
                record["steps"]["reflect"] = str(result)[:120]
            except Exception as exc:
                record["errors"].append(f"reflect: {exc}")
                log.warning("[Orchestrator] Reflect step failed: %s", exc)

        # 4. AgenticWorkflow — run the built-in self-improvement pipeline
        if self.agentic:
            try:
                result = self.agentic.run_workflow("self_improvement_cycle")
                record["steps"]["agentic"] = result.get("status", "")
            except Exception as exc:
                record["errors"].append(f"agentic: {exc}")
                log.warning("[Orchestrator] Agentic step failed: %s", exc)

        # 5. GitHub — push a cycle summary note (dry_run by default)
        if self.github:
            try:
                summary = self._build_cycle_note(record)
                push_result = self.github.push_file(
                    file_path=f"niblit_auto_notes/cycle_{self._cycle_count:05d}.md",
                    content=summary,
                    commit_message=f"niblit: autonomous cycle {self._cycle_count}",
                )
                record["steps"]["github"] = push_result.get("message", "")[:80]
            except Exception as exc:
                record["errors"].append(f"github: {exc}")
                log.warning("[Orchestrator] GitHub step failed: %s", exc)

        # Persist to DB
        self._persist_cycle(record)
        self._history.append(record)

        log.info(
            "[Orchestrator] Cycle %d complete — steps: %s | errors: %d",
            self._cycle_count,
            list(record["steps"].keys()),
            len(record["errors"]),
        )
        return record

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the continuous improvement loop in a background thread."""
        if self.running:
            log.warning("[Orchestrator] Already running")
            return False
        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(
            target=self._background_loop, daemon=True, name="OrchestratorLoop"
        )
        self._thread.start()
        log.info("[Orchestrator] Started (interval=%ds)", self.cycle_interval)
        return True

    def stop(self) -> bool:
        """Stop the continuous improvement loop."""
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15)
        log.info("[Orchestrator] Stopped after %d cycles", self._cycle_count)
        return True

    def _background_loop(self) -> None:
        while self.running and not self._stop_event.is_set():
            try:
                self.run_improvement_cycle()
            except Exception as exc:
                log.error("[Orchestrator] Unhandled cycle error: %s", exc)
            self._stop_event.wait(timeout=self.cycle_interval)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gather_recent_events(self) -> List[str]:
        """Collect recent interactions and facts from the DB for reflection."""
        events: List[str] = []
        if self.db:
            try:
                interactions = self.db.list_interactions(limit=5)
                for interaction in interactions:
                    content = interaction.get("content", "")
                    if content:
                        events.append(str(content)[:200])
            except Exception:
                pass
        return events

    def _build_cycle_note(self, record: Dict[str, Any]) -> str:
        """Build a Markdown note summarising one improvement cycle."""
        lines = [
            f"# Niblit Autonomous Improvement — Cycle {record['cycle']}",
            f"",
            f"**Timestamp:** {record['ts']}",
            f"",
            f"## Steps Completed",
            "",
        ]
        for step, outcome in record["steps"].items():
            lines.append(f"- **{step}**: {outcome}")
        if record["errors"]:
            lines += ["", "## Errors", ""]
            for err in record["errors"]:
                lines.append(f"- {err}")
        return "\n".join(lines) + "\n"

    def _persist_cycle(self, record: Dict[str, Any]) -> None:
        """Store the cycle record in the database if available."""
        if not self.db:
            return
        try:
            self.db.add_fact(
                f"orchestrator:cycle:{record['cycle']}:{record['ts']}",
                json.dumps(record),
                tags=["orchestrator", "autonomous"],
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of the orchestrator's current state."""
        return {
            "running": self.running,
            "cycle_count": self._cycle_count,
            "cycle_interval": self.cycle_interval,
            "subsystems": {
                "ale": bool(self.ale),
                "evolve": bool(self.evolve),
                "reflect": bool(self.reflect),
                "agentic": bool(self.agentic),
                "github": bool(self.github),
            },
            "last_cycle": self._history[-1] if self._history else None,
        }

    def summary(self) -> str:
        """Human-readable status summary."""
        status = self.get_status()
        active = [k for k, v in status["subsystems"].items() if v]
        return (
            f"🤖 SelfImprovementOrchestrator | "
            f"cycles={self._cycle_count} | "
            f"running={self.running} | "
            f"active_subsystems=[{', '.join(active)}]"
        )

    # ------------------------------------------------------------------
    # Research findings ingestion
    # ------------------------------------------------------------------

    def ingest_research_findings(
        self,
        findings: Dict[str, Any],
        source: str = "nibblebot-research",
    ) -> Dict[str, Any]:
        """
        Ingest structured research findings from a Nibblebot research report.

        This wires the external knowledge discovery loop (nibblebots/research_bot.py)
        back into Niblit's autonomous learning and self-improvement subsystems.

        ``findings`` is expected to have this shape (all keys optional)::

            {
                "patterns": {"Architecture Patterns": ["pipeline", ...], ...},
                "top_repos": [{"full_name": "...", "stars": 123, ...}, ...],
                "new_insights": ["pattern (category) — found in repo", ...],
                "recommendations": ["agent appeared in 12 repos — ...", ...],
            }

        The method:
          1. Feeds each new insight as a learning topic to the ALE (if wired).
          2. Stores each pattern/insight in the knowledge DB (if wired).
          3. Indexes high-value repo summaries into the RAG pipeline VectorStore.
          4. Returns a summary dict.
        """
        ingested: Dict[str, Any] = {
            "source": source,
            "ale_topics_queued": 0,
            "facts_stored": 0,
            "docs_indexed": 0,
            "errors": [],
        }

        new_insights: List[str] = findings.get("new_insights", [])
        patterns: Dict[str, List[str]] = findings.get("patterns", {})
        top_repos: List[Dict[str, Any]] = findings.get("top_repos", [])

        # 1. Feed patterns as ALE learning topics ─────────────────────
        if self.ale:
            try:
                all_patterns = [kw for kws in patterns.values() for kw in kws]
                unique_patterns = list(dict.fromkeys(all_patterns))[:10]
                for pat in unique_patterns:
                    try:
                        if hasattr(self.ale, "add_research_topic"):
                            self.ale.add_research_topic(pat)
                        elif hasattr(self.ale, "research_topics") and isinstance(
                            self.ale.research_topics, list
                        ):
                            if pat not in self.ale.research_topics:
                                self.ale.research_topics.append(pat)
                        ingested["ale_topics_queued"] += 1
                    except Exception as exc:
                        ingested["errors"].append(f"ale_topic({pat}): {exc}")
            except Exception as exc:
                ingested["errors"].append(f"ale_bulk: {exc}")
                log.warning("[Orchestrator] ALE topic ingestion failed: %s", exc)

        # 2. Store insights in knowledge DB ───────────────────────────
        if self.db:
            for insight in new_insights[:20]:
                try:
                    self.db.add_fact(
                        f"{source}:insight:{insight[:60]}",
                        insight,
                        tags=[source, "research", "insight"],
                    )
                    ingested["facts_stored"] += 1
                except Exception as exc:
                    ingested["errors"].append(f"db_insight: {exc}")

        # 3. Index top-repo summaries into RAG pipeline ───────────────
        try:
            from modules.rag_pipeline import get_rag_pipeline
            rag = get_rag_pipeline()
            for repo in top_repos[:8]:
                name = repo.get("full_name", "")
                desc = repo.get("description", "")
                repo_patterns = repo.get("patterns", [])
                if not name:
                    continue
                text = (
                    f"Repository: {name}\n"
                    f"Description: {desc}\n"
                    f"Patterns: {', '.join(repo_patterns)}\n"
                    f"Stars: {repo.get('stars', 0)}"
                )
                doc_id = f"{source}:repo:{name}"
                if rag.add_document(doc_id, text):
                    ingested["docs_indexed"] += 1
        except Exception as exc:
            ingested["errors"].append(f"rag_index: {exc}")
            log.debug("[Orchestrator] RAG indexing skipped: %s", exc)

        # 4. Record in history ────────────────────────────────────────
        self._history.append({
            "cycle": self._cycle_count,
            "ts": datetime.now(timezone.utc).isoformat(),
            "steps": {"research_ingestion": ingested},
            "errors": ingested["errors"],
        })

        log.info(
            "[Orchestrator] Research findings ingested — topics=%d facts=%d docs=%d errors=%d",
            ingested["ale_topics_queued"],
            ingested["facts_stored"],
            ingested["docs_indexed"],
            len(ingested["errors"]),
        )
        return ingested
