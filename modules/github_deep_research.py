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


def _repo_meta(owner: str, repo: str) -> Optional[Dict]:
    return _gh_get(f"/repos/{owner}/{repo}")


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
        """Return top trending repos for a topic (or all _TRENDING_TOPICS)."""
        topics = [topic] if topic else _TRENDING_TOPICS
        results = []
        for t in topics[:4]:  # limit to 4 topics per call to avoid rate limits
            repos = _search_repos(f"topic:{t}", per_page=per_page)
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
            self.knowledge_db.add_fact(key, value[:400])
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
