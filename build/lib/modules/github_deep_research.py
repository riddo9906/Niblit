"""
github_deep_research.py — Niblit Deep GitHub Research & Software Updater
=========================================================================
Continuously mines GitHub for:

  1. **Trending repos** — top starred repos in key technology areas
  2. **Major-repo PR / issue updates** — reads latest PRs and open issues
     from repos Niblit depends on or wants to track, distils insights, and
     proposes self-improvement tasks
  3. **Self-update intelligence** — compares Niblit's own capabilities
     against what the wider ecosystem is doing and surfaces upgrade ideas

All findings are:
  • Stored in Niblit's knowledge-base via KnowledgeDB.add_fact()
  • Summarised and queued as self-improvement proposals for the ALE
  • Available via CLI: ``github-deep scan``, ``github-deep trending``,
    ``github-deep updates <repo>``, ``github-deep status``

Authentication
--------------
A GitHub token (GITHUB_TOKEN env var) extends the rate-limit from
60 req/h (unauthenticated) to 5000 req/h.  All operations degrade
gracefully when unauthenticated.

Singleton access via ``get_github_deep_research()``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request, error as url_error
from urllib.parse import urlencode

log = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

_GH_API = "https://api.github.com"

# Repos Niblit tracks for update intelligence
_TRACKED_REPOS = [
    "python/cpython",
    "pytorch/pytorch",
    "huggingface/transformers",
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
    "fastapi/fastapi",
    "tiangolo/fastapi",
    "psf/requests",
    "langchain-ai/langchain",
    "microsoft/autogen",
    "BerriAI/litellm",
    "ggerganov/llama.cpp",
    "ollama/ollama",
    "vllm-project/vllm",
    "deepseek-ai/DeepSeek-V3",
]

# Technology categories for trending search
_TRENDING_TOPICS = [
    "artificial-intelligence",
    "machine-learning",
    "large-language-model",
    "autonomous-agent",
    "robotics",
    "iot",
    "embedded-systems",
    "os-development",
]

_SCAN_INTERVAL_SECS = 3600 * 6   # 6 hours
_MAX_MODEL_ENHANCED_REPOS = 10  # max repos sent to GitHub Models per scan


def _writable_path(filename: str) -> Path:
    data_dir = os.environ.get("NIBLIT_DATA_DIR")
    if data_dir and os.access(data_dir, os.W_OK):
        return Path(data_dir) / filename
    root = Path(__file__).resolve().parent.parent
    if os.access(str(root), os.W_OK):
        return root / filename
    import tempfile
    return Path(tempfile.gettempdir()) / filename


# ── GitHub API helpers ────────────────────────────────────────────────────────

def _gh_get(path: str, params: Optional[Dict] = None, timeout: int = 15) -> Any:
    """Make a GitHub API GET request and return parsed JSON."""
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"{_GH_API}{path}"
    if params:
        url += "?" + urlencode(params)
    req = request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except url_error.HTTPError as e:
        log.debug("[GHDeep] HTTP %s for %s", e.code, url)
        return None
    except Exception as e:
        log.debug("[GHDeep] request error: %s", e)
        return None


def _search_repos(query: str, sort: str = "stars", per_page: int = 10) -> List[Dict]:
    data = _gh_get("/search/repositories", {
        "q": query, "sort": sort, "order": "desc", "per_page": per_page
    })
    if data and "items" in data:
        return data["items"]
    return []


def _repo_prs(owner: str, repo: str, state: str = "open", per_page: int = 5) -> List[Dict]:
    data = _gh_get(f"/repos/{owner}/{repo}/pulls",
                   {"state": state, "sort": "updated", "direction": "desc",
                    "per_page": per_page})
    return data if isinstance(data, list) else []


def _repo_issues(owner: str, repo: str, state: str = "open", per_page: int = 5) -> List[Dict]:
    data = _gh_get(f"/repos/{owner}/{repo}/issues",
                   {"state": state, "sort": "updated", "direction": "desc",
                    "per_page": per_page})
    return data if isinstance(data, list) else []


def _topic_to_gh_slug(topic: str) -> Optional[str]:
    """Convert a free-text topic into a valid GitHub topic slug.

    GitHub topic slugs must be lowercase, contain only letters, digits, and
    hyphens, and must not start or end with a hyphen.  Multi-word phrases
    are converted by replacing spaces with hyphens.  Slugs longer than
    35 characters (GitHub's documented limit) are rejected.

    Returns None when the topic cannot be represented as a valid slug —
    the caller should fall back to keyword-only search in that case.
    """
    if not topic or not isinstance(topic, str):
        return None
    # Lowercase, replace spaces and underscores with hyphens
    slug = topic.strip().lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove characters not allowed in GitHub topic slugs
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Collapse multiple consecutive hyphens
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug or len(slug) > 35:
        return None
    return slug


# ─────────────────────────────────────────────────────────────────────────────
# GitHubDeepResearch
# ─────────────────────────────────────────────────────────────────────────────

class GitHubDeepResearch:
    """
    Mines GitHub trending repos, tracked-repo PRs/issues, and surfaces
    self-improvement proposals for Niblit's ALE.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        improvement_integrator: Optional[Any] = None,
        autoscan: bool = False,
        tracked_repos: Optional[List[str]] = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self.improvement_integrator = improvement_integrator
        self.tracked_repos: List[str] = tracked_repos or list(_TRACKED_REPOS)
        self._cache_path = _writable_path("github_deep_cache.json")
        self._cache: Dict[str, Any] = self._load_cache()
        self._last_scan: float = 0.0
        self._lock = threading.Lock()
        self._proposals: List[str] = []

        if autoscan:
            self._start_bg()

    # ── Public API ────────────────────────────────────────────────────────────

    def scan_trending(self, topic: Optional[str] = None, per_page: int = 10) -> List[Dict]:
        """Return top trending repos for a topic (or all _TRENDING_TOPICS).

        Each topic is sanitized into a valid GitHub topic slug before use.
        When a free-text topic cannot be reduced to a valid slug (e.g. a
        multi-word phrase like "c advanced programming techniques") it is
        tried as a keyword-only search (without the ``topic:`` prefix) so
        we still get relevant repos without mis-using the GitHub topic API.
        """
        topics = [topic] if topic else _TRENDING_TOPICS
        results = []
        for t in topics[:4]:  # limit to 4 topics per call to avoid rate limits
            slug = _topic_to_gh_slug(t)
            if slug:
                # Prefer topic: search for valid slugs (precise, topic-tagged results)
                repos = _search_repos(f"topic:{slug}", per_page=per_page)
                if not repos:
                    # Fall back to keyword search if no topic-tagged repos found
                    repos = _search_repos(slug, per_page=per_page)
            else:
                # Invalid slug (multi-word phrase, too long, etc.) — use keyword search
                log.debug("[GHDeep] %r is not a valid GitHub topic slug; using keyword search", t)
                repos = _search_repos(t, per_page=per_page)
            for r in repos:
                entry = {
                    "topic": t,
                    "full_name": r.get("full_name", ""),
                    "description": (r.get("description") or "")[:120],
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language", ""),
                    "url": r.get("html_url", ""),
                    "updated_at": r.get("updated_at", ""),
                }
                results.append(entry)
                self._store_fact(
                    f"github_trending_{t}",
                    f"Trending: {entry['full_name']} ⭐{entry['stars']} — {entry['description']}"
                )
        return results

    def scan_tracked_repo(self, repo_full: str) -> Dict[str, Any]:
        """Scan a single tracked repo for recent PRs and issues."""
        owner, _, name = repo_full.partition("/")
        if not name:
            return {"error": f"Invalid repo format: {repo_full}"}

        meta = _repo_meta(owner, name)
        prs = _repo_prs(owner, name)
        issues = [i for i in _repo_issues(owner, name) if "pull_request" not in i]

        result: Dict[str, Any] = {
            "repo": repo_full,
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stars": meta.get("stargazers_count", 0) if meta else 0,
            "open_issues": meta.get("open_issues_count", 0) if meta else 0,
            "description": (meta.get("description") or "")[:120] if meta else "",
            "prs": [{"title": p.get("title", "")[:80],
                     "number": p.get("number"),
                     "updated": p.get("updated_at", ""),
                     "url": p.get("html_url", "")} for p in prs],
            "issues": [{"title": i.get("title", "")[:80],
                        "number": i.get("number"),
                        "labels": [l.get("name") for l in i.get("labels", [])],
                        "url": i.get("html_url", "")} for i in issues],
        }

        # Store compact facts
        pr_titles = "; ".join(p["title"] for p in result["prs"][:3])
        issue_titles = "; ".join(i["title"] for i in result["issues"][:3])
        self._store_fact(
            f"github_repo_{repo_full.replace('/', '_')}",
            f"{repo_full} ⭐{result['stars']} | PRs: {pr_titles} | Issues: {issue_titles}"
        )

        # Generate improvement proposal
        if result["prs"] or result["issues"]:
            proposal = (
                f"Repo {repo_full} has updates — review PRs/issues for ideas: "
                + (pr_titles or "") + ("; " + issue_titles if issue_titles else "")
            )
            with self._lock:
                self._proposals.append(proposal)
            self._push_proposal(proposal)

        return result

    def scan_all_tracked(self) -> Dict[str, Any]:
        """Scan all tracked repos and return a summary."""
        summary: Dict[str, Any] = {}
        for repo in self.tracked_repos[:10]:  # cap at 10 per run
            try:
                summary[repo] = self.scan_tracked_repo(repo)
                time.sleep(0.5)  # polite rate-limiting
            except Exception as e:
                log.debug("[GHDeep] scan_tracked_repo %s failed: %s", repo, e)
                summary[repo] = {"error": str(e)}
        self._last_scan = time.time()
        self._save_cache({"tracked": summary})
        self._model_enhanced_proposals(summary)
        return summary

    def add_tracked_repo(self, repo_full: str) -> str:
        if repo_full not in self.tracked_repos:
            self.tracked_repos.append(repo_full)
            return f"✅ Added '{repo_full}' to tracked repos ({len(self.tracked_repos)} total)"
        return f"'{repo_full}' is already tracked"

    def proposals(self, n: int = 10) -> str:
        with self._lock:
            items = self._proposals[-n:]
        if not items:
            return "No improvement proposals yet (run 'github-deep scan')"
        return "\n".join(f"  • {p}" for p in items)

    def generate_refactor_proposals(
        self,
        language: str = "python",
        techniques: Optional[List[str]] = None,
        target_snippets: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Discover refactoring patterns on GitHub and enrich them with GitHub Models.

        This method:
        1. Calls ``GitHubCodeSearch.find_refactoring_patterns`` for each
           *technique* to collect real-world refactoring snippets.
        2. If ``USE_GH_MODEL_REPORTS=true``, sends the snippets (plus optional
           *target_snippets* from Niblit's own codebase) to GitHub Models to
           generate a **refactoring recipe** and Niblit-specific suggestions.
        3. Stores each recipe as a fact in the knowledge DB (via ``_store_fact``)
           and pushes it as an improvement proposal (via ``_push_proposal``).

        Args:
            language:        Programming language to search (default ``"python"``).
            techniques:      List of technique names (default: ``async``, ``type_hints``,
                             ``error_handling``).
            target_snippets: Optional list of ``{"file": "…", "code": "…"}`` dicts
                             from Niblit's own codebase to include in the model prompt.

        Returns:
            List of recipe dicts produced by
            ``GitHubModelsClient.generate_refactor_recipes``, one per technique.
        """
        if techniques is None:
            techniques = ["async", "type_hints", "error_handling"]

        recipes: List[Dict[str, Any]] = []

        try:
            from modules.github_code_search import GitHubCodeSearch
            gcs = GitHubCodeSearch()
        except Exception as exc:
            log.warning("[GHDeep] GitHubCodeSearch unavailable: %s", exc)
            return recipes

        try:
            from modules.github_models_client import GitHubModelsClient, USE_GH_MODEL_REPORTS
            client = GitHubModelsClient() if USE_GH_MODEL_REPORTS else None
        except Exception as exc:
            log.warning("[GHDeep] GitHubModelsClient unavailable: %s", exc)
            client = None

        for technique in techniques:
            try:
                examples = gcs.find_refactoring_patterns(
                    language=language, technique=technique, max_results=5
                )
                if not examples:
                    continue

                recipe: Dict[str, Any] = {}
                if client is not None:
                    try:
                        recipe = client.generate_refactor_recipes(
                            language=language,
                            technique=technique,
                            examples=examples,
                            target_snippets=target_snippets or [],
                        )
                    except Exception as exc:
                        log.warning("[GHDeep] Model recipe error for %s: %s", technique, exc)

                if recipe:
                    recipe["language"] = language
                    recipe["technique"] = technique
                    recipes.append(recipe)

                    # Persist to knowledge DB
                    desc = (recipe.get("recipe") or {}).get("description", "")
                    self._store_fact(
                        f"refactor_recipe:{language}:{technique}",
                        desc[:350] if desc else f"Recipe: {technique}",
                    )

                    # Surface as improvement proposal
                    suggestions = recipe.get("suggestions", [])
                    for sug in suggestions[:3]:
                        file_hint = sug.get("file", "")
                        summary = sug.get("summary", "")
                        if summary:
                            proposal = (
                                f"[{technique}] {file_hint}: {summary}"
                                if file_hint
                                else f"[{technique}] {summary}"
                            )
                            self._push_proposal(proposal)
                            with self._lock:
                                self._proposals.append(proposal)
            except Exception as exc:
                log.warning("[GHDeep] refactor proposal error for %s: %s", technique, exc)

        return recipes

    def _model_enhanced_proposals(self, scan_summary: Optional[Dict[str, Any]] = None) -> None:
        """Use GitHub Models to turn tracked repo scans into improvement proposals.

        Calls ``GitHubModelsClient.summarise_repos`` with compact metadata built
        from *scan_summary* (the dict already produced by ``scan_all_tracked``),
        stores a short summary in the knowledge DB, and surfaces one human-readable
        improvement proposal.

        Args:
            scan_summary: Mapping of ``repo_full -> scan_result`` as returned by
                          ``scan_all_tracked``.  When ``None`` (e.g. when called
                          standalone) a fresh scan of up to
                          ``_MAX_MODEL_ENHANCED_REPOS`` tracked repos is performed.

        No-ops when ``USE_GH_MODEL_REPORTS`` is not set to ``true`` or when the
        models client is unavailable.  Never raises.
        """
        try:
            from modules.github_models_client import (
                GitHubModelsClient,
                USE_GH_MODEL_REPORTS,
            )
        except Exception as exc:
            log.debug("[GHDeep] GitHubModelsClient import failed: %s", exc)
            return

        if not USE_GH_MODEL_REPORTS:
            return

        # Build compact payloads from the already-available scan results
        if scan_summary is None:
            # Standalone call: scan repos now (rare; avoid in hot paths)
            scan_summary = {}
            for repo in self.tracked_repos[:_MAX_MODEL_ENHANCED_REPOS]:
                try:
                    scan_summary[repo] = self.scan_tracked_repo(repo)
                except Exception as exc:
                    log.debug("[GHDeep] standalone scan(%s) failed: %s", repo, exc)

        compact: List[Dict[str, Any]] = []
        for repo, r in list(scan_summary.items())[:_MAX_MODEL_ENHANCED_REPOS]:
            if "error" in r:
                continue
            compact.append({
                "full_name": repo,
                "stars": r.get("stars", 0),
                "open_issues": r.get("open_issues", 0),
                "description": r.get("description", ""),
                "recent_prs": [p.get("title", "") for p in r.get("prs", [])[:3]],
                "recent_issues": [i.get("title", "") for i in r.get("issues", [])[:3]],
            })

        if not compact:
            return

        try:
            client = GitHubModelsClient()
            md = client.summarise_repos(
                "deep-research-tracked-repos",
                compact,
                knowledge={},
            )
        except Exception as exc:
            log.debug("[GHDeep] summarise_repos failed in _model_enhanced_proposals: %s", exc)
            return

        if not md:
            return

        self._store_fact("deep_research:model_summary", md[:400])
        proposal = "Updated model-enhanced deep research summary (see knowledge DB)"
        with self._lock:
            self._proposals.append(proposal)
        self._push_proposal(proposal)

    def status(self) -> str:
        age = time.time() - self._last_scan
        age_str = f"{age / 3600:.1f}h ago" if self._last_scan > 0 else "never"
        token_ok = bool(os.environ.get("GITHUB_TOKEN"))
        with self._lock:
            n_proposals = len(self._proposals)
        return (
            f"GitHubDeepResearch | last_scan={age_str} | "
            f"tracked={len(self.tracked_repos)} repos | "
            f"proposals={n_proposals} | github_token={'✅' if token_ok else '❌ (60 req/h limit)'}"
        )

    def trending_summary(self, topic: str = "machine-learning") -> str:
        repos = self.scan_trending(topic=topic, per_page=5)
        if not repos:
            return f"No trending repos found for '{topic}' (check rate limits)"
        lines = [f"🔥 Trending GitHub repos for '{topic}':"]
        for r in repos[:8]:
            lines.append(f"  ⭐{r['stars']:,}  {r['full_name']}  — {r['description'][:60]}")
        return "\n".join(lines)

    def repo_report(self, repo_full: str) -> str:
        r = self.scan_tracked_repo(repo_full)
        if "error" in r:
            return f"⚠️  {r['error']}"
        lines = [
            f"📦 {repo_full}  ⭐{r['stars']:,}  open issues: {r['open_issues']}",
            f"   {r['description']}",
        ]
        if r["prs"]:
            lines.append("  Recent PRs:")
            for p in r["prs"][:3]:
                lines.append(f"    #{p['number']}  {p['title']}")
        if r["issues"]:
            lines.append("  Recent Issues:")
            for i in r["issues"][:3]:
                labels = ",".join(i["labels"][:2])
                lines.append(f"    #{i['number']}  {i['title']}  [{labels}]")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _store_fact(self, key: str, value: str) -> None:
        if self.knowledge_db is None:
            return
        try:
            # Prefix every stored fact with an ISO-8601 UTC timestamp so the
            # knowledge DB can accurately track when the research was captured.
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.knowledge_db.add_fact(key, f"[{ts}] {value}"[:400])
        except Exception as e:
            log.debug("[GHDeep] KB store failed: %s", e)

    def _push_proposal(self, proposal: str) -> None:
        if self.improvement_integrator is None:
            return
        try:
            if hasattr(self.improvement_integrator, "add_proposal"):
                self.improvement_integrator.add_proposal(proposal)
        except Exception:
            pass

    def _load_cache(self) -> Dict[str, Any]:
        try:
            if self._cache_path.exists():
                return json.loads(self._cache_path.read_text())
        except Exception:
            pass
        return {}

    def _save_cache(self, data: Dict[str, Any]) -> None:
        try:
            merged = {**self._cache, **data}
            self._cache_path.write_text(json.dumps(merged, indent=2))
            self._cache = merged
        except Exception as e:
            log.debug("[GHDeep] cache save failed: %s", e)

    def _start_bg(self) -> None:
        def _loop():
            time.sleep(10)  # let core finish booting first
            while True:
                try:
                    self.scan_all_tracked()
                except Exception as e:
                    log.debug("[GHDeep] bg scan error: %s", e)
                time.sleep(_SCAN_INTERVAL_SECS)
        t = threading.Thread(target=_loop, daemon=True, name="niblit-gh-deep")
        t.start()


# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: Optional[GitHubDeepResearch] = None
_LOCK = threading.Lock()


def get_github_deep_research(
    knowledge_db: Optional[Any] = None,
    improvement_integrator: Optional[Any] = None,
) -> GitHubDeepResearch:
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = GitHubDeepResearch(
                    knowledge_db=knowledge_db,
                    improvement_integrator=improvement_integrator,
                    autoscan=bool(os.environ.get("NIBLIT_GH_DEEP_AUTOSCAN")),
                )
    return _INSTANCE


if __name__ == "__main__":
    print('Running github_deep_research.py')
