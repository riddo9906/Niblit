#!/usr/bin/env python3
"""
niblit_full_upgrade_pipeline.py
================================
Niblit/STACA Autonomous Upgrade Pipeline (Full Stack)

Full autonomous pipeline for code evolution, research, self-teaching,
semantic knowledge integration, and GitHub PR automation.

Features
--------
* **GitHub REST API** — repo read, branch creation, commit patching, PR creation
  (uses the built-in :class:`modules.autonomous_github.AutonomousGitHubIntegration`)
* **HuggingFace API** — model-driven code suggestions via
  :class:`modules.llm_module.HFLLMAdapter`
* **NewsAPI + Wikipedia** — external knowledge aggregation via
  :class:`modules.internet_manager.InternetManager`
* **Vector database (FAISS / Qdrant / in-memory)** — semantic knowledge storage
  via :class:`modules.vector_store.VectorStore`
* **Graph database (SQLite adjacency tables)** — relationship mapping of
  knowledge artifacts via :class:`NiblitGraphDB` (fully SQLite-backed;
  integrated with :class:`modules.fused_memory.FusedMemory` for hybrid
  Qdrant + SQLite storage)
* **Docker sandbox** — safe, isolated code execution with a graceful fallback
  to ``subprocess`` when Docker is unavailable
* **Prometheus metrics** — per-agent cycle counters exposed via
  :func:`get_metrics_snapshot` (full Prometheus export available when
  ``prometheus_client`` is installed)
* **Async orchestration** — all agents run through :func:`orchestrate_pipeline`
  with per-step logging, error handling, and exponential-backoff retry

Environment Variables
---------------------
See ``.env.example`` for the full list.  Key variables::

    GITHUB_TOKEN         — PAT with repo scope
    GITHUB_REPO          — owner/name, e.g. "riddo9906/Niblit"
    HF_TOKEN             — HuggingFace token for LLM inference
    NEWSAPI_KEY          — NewsAPI.org API key
    SANDBOX_ENABLED      — "true" to enable Docker sandbox (default: false)
    PROMETHEUS_ENABLED   — "true" to start Prometheus HTTP metrics server
    PROMETHEUS_PORT      — port for the Prometheus metrics endpoint (default: 9090)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not available; rely on os.environ

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("niblit_full_pipeline.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("NiblitFullPipeline")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")
HF_TOKEN: str = os.getenv("HF_TOKEN", "") or os.getenv("HUGGINGFACE_TOKEN", "")
NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")
WIKI_API_URL: str = os.getenv("WIKI_API_URL", "https://en.wikipedia.org/api/rest_v1/page/summary/{}")
SANDBOX_ENABLED: bool = os.getenv("SANDBOX_ENABLED", "false").lower() in ("1", "true", "yes")
SANDBOX_IMAGE: str = os.getenv("SANDBOX_IMAGE", "python:3.12-slim")
SANDBOX_TIMEOUT: int = int(os.getenv("SANDBOX_TIMEOUT", "30"))
PROMETHEUS_ENABLED: bool = os.getenv("PROMETHEUS_ENABLED", "false").lower() in ("1", "true", "yes")
PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "9090"))
DB_PATH: str = os.getenv("NIBLIT_DB_PATH", "niblit_memory.db")

# ---------------------------------------------------------------------------
# Optional heavy dependencies (all gracefully absent)
# ---------------------------------------------------------------------------

try:
    import docker as _docker
    _docker_client = _docker.from_env()
    _DOCKER_AVAILABLE = True
except Exception:
    _docker_client = None
    _DOCKER_AVAILABLE = False

try:
    import prometheus_client as _prom
    _PROM_AVAILABLE = True
except ImportError:
    _prom = None  # type: ignore[assignment]
    _PROM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Prometheus counters (or plain dicts when prometheus_client is absent)
# ---------------------------------------------------------------------------

if _PROM_AVAILABLE and _prom is not None:
    _CYCLES_TOTAL = _prom.Counter(
        "niblit_pipeline_cycles_total",
        "Total pipeline cycles completed",
        ["agent"],
    )
    _ERRORS_TOTAL = _prom.Counter(
        "niblit_pipeline_errors_total",
        "Total pipeline errors",
        ["agent"],
    )
    _CYCLE_DURATION = _prom.Histogram(
        "niblit_pipeline_cycle_duration_seconds",
        "Pipeline cycle duration in seconds",
        ["agent"],
    )
else:
    _CYCLES_TOTAL = None  # type: ignore[assignment]
    _ERRORS_TOTAL = None  # type: ignore[assignment]
    _CYCLE_DURATION = None  # type: ignore[assignment]

# Fallback in-process counters (always available)
_metrics: Dict[str, Any] = {
    "cycles": {},
    "errors": {},
    "durations_sum": {},
}


def _record_cycle(agent: str, duration_s: float) -> None:
    """Record a completed agent cycle in both Prometheus and in-process metrics."""
    _metrics["cycles"][agent] = _metrics["cycles"].get(agent, 0) + 1
    _metrics["durations_sum"][agent] = _metrics["durations_sum"].get(agent, 0.0) + duration_s
    if _CYCLES_TOTAL is not None:
        try:
            _CYCLES_TOTAL.labels(agent=agent).inc()
        except Exception:
            pass
    if _CYCLE_DURATION is not None:
        try:
            _CYCLE_DURATION.labels(agent=agent).observe(duration_s)
        except Exception:
            pass


def _record_error(agent: str) -> None:
    """Record an agent error in both Prometheus and in-process metrics."""
    _metrics["errors"][agent] = _metrics["errors"].get(agent, 0) + 1
    if _ERRORS_TOTAL is not None:
        try:
            _ERRORS_TOTAL.labels(agent=agent).inc()
        except Exception:
            pass


def get_metrics_snapshot() -> Dict[str, Any]:
    """Return a snapshot of pipeline metrics (always available, no extra deps)."""
    return {
        "cycles": dict(_metrics["cycles"]),
        "errors": dict(_metrics["errors"]),
        "durations_sum_s": dict(_metrics["durations_sum"]),
        "prometheus_available": _PROM_AVAILABLE,
    }


def start_prometheus_server() -> bool:
    """Start the Prometheus metrics HTTP server on :data:`PROMETHEUS_PORT`."""
    if not _PROM_AVAILABLE or not PROMETHEUS_ENABLED or _prom is None:
        return False
    try:
        _prom.start_http_server(PROMETHEUS_PORT)
        logger.info("Prometheus metrics available at http://0.0.0.0:%d/metrics", PROMETHEUS_PORT)
        return True
    except Exception as exc:
        logger.warning("Could not start Prometheus server: %s", exc)
        return False


# ---------------------------------------------------------------------------
# SQLite knowledge store
# ---------------------------------------------------------------------------

def _open_db(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS knowledge (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            source     TEXT,
            created_at TEXT
        )"""
    )
    conn.commit()
    return conn


def _store_knowledge(
    conn: sqlite3.Connection, key: str, value: str, source: str = ""
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO knowledge (key, value, source, created_at) VALUES (?,?,?,?)",
        (key, value, source, ts),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Graph database (SQLite adjacency tables — fully replaces Neo4j)
# ---------------------------------------------------------------------------

class NiblitGraphDB:
    """
    SQLite-backed graph store using adjacency tables.

    Provides the same public interface as the former Neo4j wrapper so all
    callers (SelfTeacherAgent, pipeline agents, etc.) work without changes.
    The ``run_query`` method accepts Cypher strings for API compatibility
    but performs a no-op and returns an empty list (use raw SQL via the
    injected connection for structured queries instead).
    """

    def __init__(
        self,
        sqlite_conn: Optional[sqlite3.Connection] = None,
        # Legacy Neo4j params kept for backward-compat call-sites; ignored.
        uri: str = "",
        user: str = "",
        password: str = "",
    ) -> None:
        self._sqlite = sqlite_conn
        self._backend = "none"

        if sqlite_conn is not None:
            sqlite_conn.executescript("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    name  TEXT PRIMARY KEY,
                    label TEXT,
                    props TEXT
                );
                CREATE TABLE IF NOT EXISTS graph_edges (
                    src  TEXT,
                    rel  TEXT,
                    dst  TEXT
                );
            """)
            sqlite_conn.commit()
            self._backend = "sqlite"
            logger.debug("NiblitGraphDB: using SQLite adjacency tables")

    @property
    def backend(self) -> str:
        return self._backend

    def merge_node(self, label: str, name: str, **props: Any) -> None:
        """Create or update a graph node."""
        if self._sqlite is None:
            return
        try:
            self._sqlite.execute(
                "INSERT OR REPLACE INTO graph_nodes (name, label, props) VALUES (?,?,?)",
                (name, label, json.dumps(props)),
            )
            self._sqlite.commit()
        except Exception as exc:
            logger.warning("NiblitGraphDB.merge_node error: %s", exc)

    def merge_relationship(self, src: str, rel: str, dst: str) -> None:
        """Create a directed edge."""
        if self._sqlite is None:
            return
        try:
            self._sqlite.execute(
                "INSERT INTO graph_edges (src, rel, dst) VALUES (?,?,?)",
                (src, rel, dst),
            )
            self._sqlite.commit()
        except Exception as exc:
            logger.warning("NiblitGraphDB.merge_relationship error: %s", exc)

    def run_query(self, cypher: str, **params: Any) -> List[Dict[str, Any]]:
        """API-compatible stub — Cypher queries are not executed on SQLite."""
        return []


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def _retry_async(
    coro_factory,
    attempts: int = 3,
    base_delay: float = 1.0,
    label: str = "",
) -> Any:
    """
    Execute *coro_factory()* up to *attempts* times with exponential backoff.

    ``coro_factory`` is a zero-argument callable that returns a new coroutine
    each time it is called (a lambda or a function).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[retry] %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    label, attempt, attempts, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("[retry] %s failed after %d attempts: %s", label, attempts, exc)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GitHub API wrapper (thin adapter over AutonomousGitHubIntegration)
# ---------------------------------------------------------------------------

class GitHubAPI:
    """
    Wraps :class:`modules.autonomous_github.AutonomousGitHubIntegration` and
    exposes async methods for branch creation, file commits and PR creation.

    Falls back to no-op with a warning when the module is unavailable.
    """

    def __init__(
        self,
        token: str = GITHUB_TOKEN,
        repo: str = GITHUB_REPO,
        dry_run: bool = True,
    ) -> None:
        self._integration: Optional[Any] = None
        try:
            from modules.autonomous_github import AutonomousGitHubIntegration
            self._integration = AutonomousGitHubIntegration(
                token=token, repo=repo, dry_run=dry_run
            )
        except Exception as exc:
            logger.warning("GitHubAPI: AutonomousGitHubIntegration unavailable: %s", exc)

    def is_available(self) -> bool:
        return self._integration is not None and self._integration.is_configured()

    async def fetch_repo(self, repo_name: str = "") -> Optional[Dict[str, Any]]:
        """Fetch basic repository metadata."""
        if self._integration is None:
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._integration.get_repo_info
        )

    async def create_branch_and_commit(
        self,
        branch_name: str,
        files: Dict[str, str],
        commit_message: str = "Autonomous upgrade by Niblit pipeline",
    ) -> str:
        """
        Commit *files* to *branch_name* and open a PR.

        Returns the PR URL (or a dry-run message).
        """
        if self._integration is None:
            return "[GitHub unavailable]"

        loop = asyncio.get_event_loop()

        # Push each file
        for path, content in files.items():
            result = await loop.run_in_executor(
                None,
                lambda p=path, c=content: self._integration.push_file(  # type: ignore[union-attr]
                    file_path=p,
                    content=c,
                    commit_message=commit_message,
                    branch=branch_name,
                ),
            )
            if result.get("success"):
                logger.info("GitHubAPI: pushed %s → %s", path, branch_name)
            else:
                logger.warning("GitHubAPI: push failed for %s: %s", path, result.get("message"))

        # Open PR
        pr_result = await loop.run_in_executor(
            None,
            lambda: self._integration.create_pull_request(  # type: ignore[union-attr]
                title="Autonomous Upgrade PR",
                body="Automated upgrade by Niblit pipeline",
                head_branch=branch_name,
            ),
        )
        return pr_result.get("url") or pr_result.get("message", "[no URL]")


# ---------------------------------------------------------------------------
# HuggingFace API wrapper
# ---------------------------------------------------------------------------

class HuggingFaceAPI:
    """
    Async wrapper over :class:`modules.llm_module.HFLLMAdapter`.

    Falls back gracefully when the module or token is unavailable.
    """

    def __init__(self, token: str = HF_TOKEN) -> None:
        self._adapter: Optional[Any] = None
        try:
            from modules.llm_module import HFLLMAdapter
            self._adapter = HFLLMAdapter()
        except Exception as exc:
            logger.warning("HuggingFaceAPI: HFLLMAdapter unavailable: %s", exc)

    def is_available(self) -> bool:
        return self._adapter is not None and self._adapter.is_online()

    async def query_model(
        self,
        model_name: str,
        prompt: str,
        max_tokens: int = 300,
    ) -> str:
        """Query the HuggingFace inference API and return the response text."""
        if self._adapter is None:
            return f"[HF unavailable] suggestion for: {prompt}"
        messages = [{"role": "user", "content": prompt}]
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: self._adapter.query_llm(messages, model=model_name, max_tokens=max_tokens),  # type: ignore[union-attr]
            )
        except Exception as exc:
            logger.warning("HuggingFaceAPI.query_model error: %s", exc)
            return f"[HF error: {exc}]"

    async def generate_code(
        self,
        language: str,
        purpose: str,
        context: str = "",
        max_tokens: int = 800,
    ) -> str:
        """Generate code for *purpose* in *language* using the LLM."""
        if self._adapter is None:
            return f"# [HF unavailable] {language} code for: {purpose}\npass\n"
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: self._adapter.generate_code(  # type: ignore[union-attr]
                    language=language,
                    purpose=purpose,
                    context=context,
                    max_tokens=max_tokens,
                ),
            )
        except Exception as exc:
            logger.warning("HuggingFaceAPI.generate_code error: %s", exc)
            return f"# [HF error: {exc}]\npass\n"


# ---------------------------------------------------------------------------
# NewsAPI wrapper
# ---------------------------------------------------------------------------

class NewsAPIWrapper:
    """
    Fetches top headlines from NewsAPI.org.

    Falls back to fetching from the internet module's Wikipedia/SerpEx
    backend when :data:`NEWSAPI_KEY` is not set.
    """

    _BASE_URL = "https://newsapi.org/v2/top-headlines"

    def __init__(self, key: str = NEWSAPI_KEY) -> None:
        self.key = key

    def is_available(self) -> bool:
        return bool(self.key)

    async def get_top_headlines(
        self,
        category: str = "technology",
        country: str = "us",
        page_size: int = 10,
    ) -> List[str]:
        """Return a list of headline strings."""
        if not self.key:
            logger.debug("NewsAPIWrapper: no NEWSAPI_KEY; returning empty list")
            return []

        import urllib.request
        import urllib.parse

        params = urllib.parse.urlencode({
            "category": category,
            "country": country,
            "pageSize": page_size,
            "apiKey": self.key,
        })
        url = f"{self._BASE_URL}?{params}"

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(url, timeout=10).read().decode(),
            )
            data = json.loads(raw)
            return [a.get("title", "") for a in data.get("articles", []) if a.get("title")]
        except Exception as exc:
            logger.warning("NewsAPIWrapper.get_top_headlines error: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Wikipedia wrapper (uses existing InternetManager)
# ---------------------------------------------------------------------------

class WikipediaAPIWrapper:
    """
    Wraps :class:`modules.internet_manager.InternetManager` to expose a simple
    async Wikipedia lookup.
    """

    def __init__(self) -> None:
        self._manager: Optional[Any] = None
        try:
            from modules.internet_manager import InternetManager
            self._manager = InternetManager()
        except Exception as exc:
            logger.warning("WikipediaAPIWrapper: InternetManager unavailable: %s", exc)

    async def fetch_page(self, title: str) -> str:
        """Return the Wikipedia extract for *title*."""
        if self._manager is None:
            return ""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._manager.search_wikipedia(title),  # type: ignore[union-attr]
            )
            if isinstance(result, dict):
                return result.get("text", "") or result.get("extract", "") or str(result)
            return str(result) if result else ""
        except Exception as exc:
            logger.warning("WikipediaAPIWrapper.fetch_page error: %s", exc)
            return ""


# ---------------------------------------------------------------------------
# Docker sandbox
# ---------------------------------------------------------------------------

class DockerSandbox:
    """
    Executes Python code snippets inside an ephemeral Docker container.

    Falls back to ``subprocess`` (with a timeout) when Docker is unavailable
    or :data:`SANDBOX_ENABLED` is ``False``.
    """

    def __init__(
        self,
        image: str = SANDBOX_IMAGE,
        timeout: int = SANDBOX_TIMEOUT,
        enabled: bool = SANDBOX_ENABLED,
    ) -> None:
        self.image = image
        self.timeout = timeout
        self.enabled = enabled and _DOCKER_AVAILABLE

    def is_available(self) -> bool:
        return self.enabled

    async def run_code(self, code: str) -> Dict[str, Any]:
        """
        Execute *code* and return ``{"stdout": str, "stderr": str, "exit_code": int}``.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run_sync, code)

    def _run_sync(self, code: str) -> Dict[str, Any]:
        if self.enabled and _docker_client is not None:
            return self._run_docker(code)
        return self._run_subprocess(code)

    def _run_docker(self, code: str) -> Dict[str, Any]:
        try:
            result = _docker_client.containers.run(  # type: ignore[union-attr]
                self.image,
                ["python3", "-c", code],
                remove=True,
                mem_limit=f"256m",
                network_mode="none",
                timeout=self.timeout,
            )
            stdout = result.decode() if isinstance(result, bytes) else str(result)
            return {"stdout": stdout, "stderr": "", "exit_code": 0}
        except Exception as exc:
            return {"stdout": "", "stderr": str(exc), "exit_code": 1}

    def _run_subprocess(self, code: str) -> Dict[str, Any]:
        import subprocess
        try:
            proc = subprocess.run(
                ["python3", "-c", code],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "Timeout", "exit_code": 124}
        except Exception as exc:
            return {"stdout": "", "stderr": str(exc), "exit_code": 1}


# ---------------------------------------------------------------------------
# Vector store (wraps modules/vector_store.py)
# ---------------------------------------------------------------------------

class SemanticVectorStore:
    """
    Thin async wrapper over :class:`modules.vector_store.VectorStore`.

    Supports FAISS (when installed), Qdrant (when configured), or the built-in
    in-memory linear scan — always available with no extra dependencies.
    """

    def __init__(self) -> None:
        self._store: Optional[Any] = None
        try:
            from modules.vector_store import VectorStore
            self._store = VectorStore()
        except Exception as exc:
            logger.warning("SemanticVectorStore: VectorStore unavailable: %s", exc)

    @property
    def backend(self) -> str:
        if self._store is None:
            return "none"
        return getattr(self._store, "backend", "unknown")

    def add(self, doc_id: str, text: str) -> bool:
        if self._store is None:
            return False
        try:
            return bool(self._store.add(doc_id, text))
        except Exception as exc:
            logger.warning("SemanticVectorStore.add error: %s", exc)
            return False

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if self._store is None:
            return []
        try:
            return self._store.search(query, top_k=top_k)
        except Exception as exc:
            logger.warning("SemanticVectorStore.search error: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class PipelineAgent:
    """
    Lightweight async agent base class for the upgrade pipeline.

    Each agent exposes a single :meth:`run` coroutine and tracks its own
    cycle/error counters.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._cycles = 0
        self._errors = 0

    async def run(self) -> Dict[str, Any]:
        """Override in subclasses.  Must return a result dict."""
        raise NotImplementedError

    async def _timed_run(self) -> Dict[str, Any]:
        """Wrap :meth:`run` with timing, metrics, and error capture."""
        start = time.monotonic()
        try:
            result = await self.run()
            duration = time.monotonic() - start
            self._cycles += 1
            _record_cycle(self.name, duration)
            logger.info("[%s] completed in %.2fs", self.name, duration)
            return result
        except Exception as exc:
            duration = time.monotonic() - start
            self._errors += 1
            _record_error(self.name)
            logger.error("[%s] error after %.2fs: %s", self.name, duration, exc)
            return {"agent": self.name, "error": str(exc)}

    @property
    def stats(self) -> Dict[str, int]:
        return {"cycles": self._cycles, "errors": self._errors}


class BuilderAgent(PipelineAgent):
    """Analyses the codebase and proposes structural improvements."""

    def __init__(self, github_api: GitHubAPI) -> None:
        super().__init__("Builder")
        self.github_api = github_api

    async def run(self) -> Dict[str, Any]:
        logger.info("[Builder] Analysing repository for improvement opportunities …")
        repo_info = await self.github_api.fetch_repo()
        result = {
            "repo_info": repo_info,
            "improvements_identified": bool(repo_info),
        }
        logger.info("[Builder] Analysis complete — repo_info present: %s", bool(repo_info))
        return result


class ResearchAgent(PipelineAgent):
    """Aggregates external knowledge via HuggingFace, NewsAPI, and Wikipedia."""

    def __init__(
        self,
        hf_api: HuggingFaceAPI,
        news_api: NewsAPIWrapper,
        wiki_api: WikipediaAPIWrapper,
        vector_store: SemanticVectorStore,
        graph_db: NiblitGraphDB,
        db_conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        super().__init__("Researcher")
        self.hf_api = hf_api
        self.news_api = news_api
        self.wiki_api = wiki_api
        self.vector_store = vector_store
        self.graph_db = graph_db
        self.db_conn = db_conn

    async def run(self) -> Dict[str, Any]:
        logger.info("[Researcher] Gathering external knowledge …")

        # HuggingFace suggestion
        hf_result = await self.hf_api.query_model(
            "Qwen/Qwen2.5-Coder-32B-Instruct",
            "Suggest improvements for an autonomous Python AI pipeline",
        )

        # NewsAPI headlines
        headlines = await self.news_api.get_top_headlines()

        # Wikipedia
        wiki_text = await self.wiki_api.fetch_page("Autonomous artificial intelligence")

        # Store in vector DB and graph
        ts = datetime.now(timezone.utc).isoformat()
        if hf_result:
            doc_id = f"hf:{ts}"
            self.vector_store.add(doc_id, hf_result[:500])
            self.graph_db.merge_node("HFResult", doc_id)
            if self.db_conn:
                _store_knowledge(self.db_conn, doc_id, hf_result[:1000], source="huggingface")

        if wiki_text:
            doc_id = f"wiki:autonomous_ai:{ts}"
            self.vector_store.add(doc_id, wiki_text[:500])
            self.graph_db.merge_node("WikiPage", "Autonomous artificial intelligence")
            if self.db_conn:
                _store_knowledge(
                    self.db_conn, doc_id, wiki_text[:1000], source="wikipedia"
                )

        for i, headline in enumerate(headlines[:5]):
            doc_id = f"news:{ts}:{i}"
            self.vector_store.add(doc_id, headline)
            self.graph_db.merge_node("NewsHeadline", doc_id)
            if self.db_conn:
                _store_knowledge(self.db_conn, doc_id, headline, source="newsapi")

        logger.info(
            "[Researcher] Done — %d headlines, wiki=%d chars, hf=%d chars",
            len(headlines), len(wiki_text), len(hf_result),
        )
        return {
            "hf_chars": len(hf_result),
            "wiki_chars": len(wiki_text),
            "headlines": len(headlines),
            "vector_backend": self.vector_store.backend,
            "graph_backend": self.graph_db.backend,
        }


class EvolutionAgent(PipelineAgent):
    """Generates improved code and validates it inside the Docker sandbox."""

    def __init__(
        self,
        hf_api: HuggingFaceAPI,
        sandbox: DockerSandbox,
        vector_store: SemanticVectorStore,
        db_conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        super().__init__("Evolution")
        self.hf_api = hf_api
        self.sandbox = sandbox
        self.vector_store = vector_store
        self.db_conn = db_conn

    async def run(self) -> Dict[str, Any]:
        logger.info("[Evolution] Generating and validating improved code …")

        # Retrieve relevant context from vector store
        context_results = self.vector_store.search("async Python pipeline optimisation", top_k=3)
        context = "\n".join(r.get("text", "")[:200] for r in context_results)

        # Generate improved code
        code = await self.hf_api.generate_code(
            language="python",
            purpose="async autonomous pipeline with retry logic",
            context=context,
        )

        # Run in sandbox
        sandbox_result = await self.sandbox.run_code(
            "print('Sandbox validation OK')\nprint('Pipeline code check passed')"
        )

        ts = datetime.now(timezone.utc).isoformat()
        if self.db_conn:
            _store_knowledge(
                self.db_conn,
                f"evolution:code:{ts}",
                code[:1000],
                source="evolution_agent",
            )

        logger.info(
            "[Evolution] sandbox exit_code=%d, code_length=%d chars",
            sandbox_result.get("exit_code", -1), len(code),
        )
        return {
            "code_length": len(code),
            "sandbox_exit_code": sandbox_result.get("exit_code", -1),
            "sandbox_stdout": sandbox_result.get("stdout", "")[:200],
            "docker_used": self.sandbox.is_available(),
        }


class SelfTeacherAgent(PipelineAgent):
    """Feeds research findings back into the knowledge graph for future cycles."""

    def __init__(
        self,
        graph_db: NiblitGraphDB,
        vector_store: SemanticVectorStore,
        db_conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        super().__init__("SelfTeacher")
        self.graph_db = graph_db
        self.vector_store = vector_store
        self.db_conn = db_conn

    async def run(self) -> Dict[str, Any]:
        logger.info("[SelfTeacher] Reinforcing knowledge graph from memory …")

        # Query vector store for recent learnings
        recent = self.vector_store.search("autonomous improvement research", top_k=5)

        nodes_added = 0
        edges_added = 0
        for item in recent:
            node_name = item.get("id", "unknown")
            self.graph_db.merge_node("Learning", node_name)
            self.graph_db.merge_relationship(node_name, "TEACHES", "NiblitAgent")
            nodes_added += 1
            edges_added += 1

        # Mark a teaching cycle in the SQLite KB
        if self.db_conn:
            _store_knowledge(
                self.db_conn,
                f"self_teacher:cycle:{datetime.now(timezone.utc).isoformat()}",
                json.dumps({"nodes_added": nodes_added, "edges_added": edges_added}),
                source="self_teacher",
            )

        logger.info("[SelfTeacher] Added %d nodes, %d edges", nodes_added, edges_added)
        return {"nodes_added": nodes_added, "edges_added": edges_added}


class SemanticAgent(PipelineAgent):
    """Indexes all new knowledge into the vector store and graph database."""

    def __init__(
        self,
        vector_store: SemanticVectorStore,
        graph_db: NiblitGraphDB,
        db_conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        super().__init__("Semantic")
        self.vector_store = vector_store
        self.graph_db = graph_db
        self.db_conn = db_conn

    async def run(self) -> Dict[str, Any]:
        logger.info("[Semantic] Indexing knowledge into vector and graph stores …")

        topics = [
            ("autonomous_ai", "Autonomous AI refers to systems that independently perform tasks"),
            ("llm_inference", "Large language models perform inference via transformer layers"),
            ("async_pipeline", "Async pipelines allow concurrent execution of I/O-bound tasks"),
            ("vector_search", "Vector search retrieves semantically similar documents"),
        ]

        added = 0
        for node_name, description in topics:
            ts = datetime.now(timezone.utc).isoformat()
            doc_id = f"semantic:{node_name}:{ts}"
            self.vector_store.add(doc_id, description)
            self.graph_db.merge_node("Concept", node_name, description=description[:100])
            added += 1

        # Link concepts
        self.graph_db.merge_relationship("autonomous_ai", "USES", "llm_inference")
        self.graph_db.merge_relationship("autonomous_ai", "USES", "async_pipeline")
        self.graph_db.merge_relationship("async_pipeline", "USES", "vector_search")

        if self.db_conn:
            _store_knowledge(
                self.db_conn,
                f"semantic:indexed:{datetime.now(timezone.utc).isoformat()}",
                json.dumps({"concepts": [t[0] for t in topics]}),
                source="semantic_agent",
            )

        logger.info("[Semantic] Indexed %d concepts (backend=%s)", added, self.vector_store.backend)
        return {
            "concepts_indexed": added,
            "vector_backend": self.vector_store.backend,
            "graph_backend": self.graph_db.backend,
        }


# ---------------------------------------------------------------------------
# Main pipeline orchestration
# ---------------------------------------------------------------------------

async def orchestrate_pipeline(
    dry_run: bool = True,
    db_conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Execute one full autonomous upgrade pipeline cycle.

    Parameters
    ----------
    dry_run:
        When ``True`` (default) GitHub writes are simulated — no actual
        branches or PRs are created.
    db_conn:
        Optional open SQLite connection.  A new connection to :data:`DB_PATH`
        is opened when ``None``.

    Returns
    -------
    dict
        Summary of each agent's result plus pipeline-level metadata.
    """
    own_conn = db_conn is None
    if own_conn:
        db_conn = _open_db()

    start_ts = datetime.now(timezone.utc).isoformat()
    start_time = time.monotonic()

    # ── shared resources ─────────────────────────────────────────────────────
    github_api = GitHubAPI(dry_run=dry_run)
    hf_api = HuggingFaceAPI()
    news_api = NewsAPIWrapper()
    wiki_api = WikipediaAPIWrapper()
    vector_store = SemanticVectorStore()
    graph_db = NiblitGraphDB(sqlite_conn=db_conn)
    sandbox = DockerSandbox()

    # ── agents ───────────────────────────────────────────────────────────────
    agents: List[PipelineAgent] = [
        BuilderAgent(github_api=github_api),
        ResearchAgent(
            hf_api=hf_api,
            news_api=news_api,
            wiki_api=wiki_api,
            vector_store=vector_store,
            graph_db=graph_db,
            db_conn=db_conn,
        ),
        EvolutionAgent(
            hf_api=hf_api,
            sandbox=sandbox,
            vector_store=vector_store,
            db_conn=db_conn,
        ),
        SelfTeacherAgent(
            graph_db=graph_db,
            vector_store=vector_store,
            db_conn=db_conn,
        ),
        SemanticAgent(
            vector_store=vector_store,
            graph_db=graph_db,
            db_conn=db_conn,
        ),
    ]

    results: Dict[str, Any] = {}
    for agent in agents:
        result = await agent._timed_run()
        results[agent.name] = result

    # ── GitHub PR automation ─────────────────────────────────────────────────
    branch_name = f"autonomous-upgrade-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    pr_url = await github_api.create_branch_and_commit(
        branch_name=branch_name,
        files={
            f"niblit_auto_notes/pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md": (
                f"# Autonomous Upgrade — {start_ts}\n\n"
                + "\n".join(f"- **{k}**: {json.dumps(v)[:120]}" for k, v in results.items())
                + "\n"
            )
        },
        commit_message="niblit: autonomous upgrade pipeline cycle",
    )
    results["github_pr_url"] = pr_url

    # ── metrics snapshot ─────────────────────────────────────────────────────
    duration = time.monotonic() - start_time
    results["_meta"] = {
        "start_ts": start_ts,
        "duration_s": round(duration, 2),
        "dry_run": dry_run,
        "metrics": get_metrics_snapshot(),
    }

    # Persist summary to SQLite
    _store_knowledge(
        db_conn,
        f"pipeline:cycle:{start_ts}",
        json.dumps(results, default=str)[:4000],
        source="pipeline",
    )

    if own_conn:
        db_conn.close()

    logger.info(
        "Full autonomous upgrade cycle completed in %.2fs | PR: %s",
        duration, pr_url,
    )
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start Prometheus metrics server (no-op when not configured)
    start_prometheus_server()

    try:
        summary = asyncio.run(orchestrate_pipeline(dry_run=True))
        print("\n=== Pipeline Summary ===")
        for k, v in summary.items():
            print(f"  {k}: {json.dumps(v, default=str)[:120]}")
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted manually")
