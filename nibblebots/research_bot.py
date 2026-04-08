#!/usr/bin/env python3
"""
nibblebot-research  —  Enhanced Research Bot that studies GitHub repositories
LIVE using the GitHub REST API, accumulates a "knowledge layer" from past
nibblebot issues, and generates synthesised insights to make Niblit and
Nibblebot more knowledgeable about software.

This bot NEVER commits or pushes code.  It ONLY creates/updates GitHub
Issues labelled ``nibblebot-research``.

Phases:
  1. Load Knowledge Layer — read past nibblebot issues to extract accumulated
     knowledge and avoid re-researching the same things.
  2. Live Research      — search GitHub repos by topic, fetch metadata,
     READMEs, recent commits, contributor counts, language breakdowns,
     and open issue counts.
  3. Deep Analysis     — extract architectural patterns, algorithms,
     APIs, and best practices from each repo.
  4. Synthesis         — aggregate findings into cross-cutting insights,
     updated with existing knowledge.
  5. Report            — open/update a GitHub Issue with the full report
     and persist new knowledge for future runs.

Usage (local testing):
    GITHUB_TOKEN=ghp_... GITHUB_REPOSITORY=owner/repo python nibblebots/research_bot.py

Environment variables:
    GITHUB_TOKEN          — GitHub token with repo + issues scope
    GITHUB_REPOSITORY     — owner/repo  (set automatically in Actions)
    RESEARCH_TOPICS       — comma-separated topics (default: built-in list)
    RESEARCH_MAX_REPOS    — max repos per topic (default: 6)
    RESEARCH_DRY_RUN      — "true" to print instead of creating issue
    RESEARCH_DEEP_DIVE    — "true" to fetch per-repo language breakdown (slower)
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-Research/2.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
RESEARCH_DEEP_DIVE = os.environ.get("RESEARCH_DEEP_DIVE", "").lower() == "true"
DRY_RUN = os.environ.get("RESEARCH_DRY_RUN", "").lower() == "true"
MAX_REPOS = int(os.environ.get("RESEARCH_MAX_REPOS", "6"))
ISSUE_LABEL = "nibblebot-research"
ISSUE_TITLE_PREFIX = "🔬 Nibblebot Research Report"

_DEFAULT_TOPICS = (
    "ai-agent,llm-framework,autonomous-agent,"
    "knowledge-graph,vector-database,retrieval-augmented-generation,"
    "self-improving,continual-learning,online-learning,"
    "python-framework,software-architecture,design-patterns,"
    "devops-automation,ci-cd,deployment-automation"
)
TOPICS = [
    t.strip()
    for t in os.environ.get("RESEARCH_TOPICS", _DEFAULT_TOPICS).split(",")
    if t.strip()
]

# Topic → human-readable category
_TOPIC_CATEGORIES: Dict[str, str] = {}
for _cat, _keys in [
    ("AI Agents & LLMs", ["ai-agent", "llm-framework", "autonomous-agent"]),
    ("Knowledge & Memory", ["knowledge-graph", "vector-database", "retrieval-augmented-generation"]),
    ("Self-Improving Systems", ["self-improving", "continual-learning", "online-learning"]),
    ("Software Architecture", ["python-framework", "software-architecture", "design-patterns"]),
    ("Deployment & DevOps", ["devops-automation", "ci-cd", "deployment-automation"]),
]:
    for _k in _keys:
        _TOPIC_CATEGORIES[_k] = _cat


# ---------------------------------------------------------------------------
# GitHub REST API helpers
# ---------------------------------------------------------------------------

def _gh_request(
    path: str,
    body: Optional[Dict[str, Any]] = None,
    method: str = "GET",
) -> Any:
    """Core GitHub REST API v3 request helper."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data: Optional[bytes] = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=25) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API {method} error: {path} → {exc}", file=sys.stderr)
        return None


def gh_get(path: str) -> Any:
    """GET JSON from the GitHub REST API."""
    return _gh_request(path)


def gh_post(path: str, body: Dict[str, Any]) -> Any:
    """POST JSON to the GitHub REST API."""
    return _gh_request(path, body, "POST")


def gh_patch(path: str, body: Dict[str, Any]) -> Any:
    """PATCH JSON to the GitHub REST API."""
    return _gh_request(path, body, "PATCH")


def gh_search_code(query: str, per_page: int = 5) -> List[Dict[str, Any]]:
    """Search GitHub code index for a query string."""
    encoded = query.replace(" ", "+")
    data = gh_get(f"/search/code?q={encoded}&per_page={per_page}")
    if data and "items" in data:
        return data["items"]
    return []


def gh_search_repos(query: str, per_page: int = MAX_REPOS) -> List[Dict[str, Any]]:
    """Search GitHub repository index, sorted by stars."""
    encoded = query.replace(" ", "+")
    data = gh_get(f"/search/repositories?q={encoded}&sort=stars&per_page={per_page}")
    if data and "items" in data:
        return data["items"]
    return []


# ---------------------------------------------------------------------------
# Phase 1 — Load Knowledge Layer from past nibblebot issues
# ---------------------------------------------------------------------------

_KNOWLEDGE_LAYER_LABEL = "nibblebot-research"
_KL_MAX_ISSUES = 10  # read last 10 closed issues to build the layer


def load_knowledge_layer() -> Dict[str, Any]:
    """
    Read closed nibblebot-research issues to extract accumulated knowledge.

    Returns a dict with:
      - known_repos: set of repo full_names already studied
      - known_patterns: list of patterns already identified
      - past_topics: set of topics already covered
      - insights: list of key insight strings from past reports
    """
    print("  📚 Loading knowledge layer from past issues…")
    known_repos: Set[str] = set()
    known_patterns: List[str] = []
    past_topics: Set[str] = set()
    insights: List[str] = []

    # Try nibblebot-research label first, then fall back to nibblebot label
    for label in (ISSUE_LABEL, "nibblebot"):
        issues_data = gh_get(
            f"/repos/{REPO}/issues"
            f"?labels={label}&state=closed&per_page={_KL_MAX_ISSUES}&sort=updated"
        )
        if not issues_data:
            continue

        for issue in issues_data:
            body = issue.get("body") or ""

            # Extract repo names (owner/repo pattern)
            for m in re.finditer(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", body):
                candidate = m.group(0)
                if "/" in candidate and not candidate.startswith("http"):
                    known_repos.add(candidate)

            # Extract bullet-point insights (lines starting with •, -, *, or checkboxes)
            for line in body.splitlines():
                line = line.strip()
                if line.startswith(("- [x]", "✅", "💡", "🔑", "📌")):
                    text = re.sub(r"^[-\*•✅💡🔑📌\[\]x ]+", "", line).strip()
                    if len(text) > 20:
                        insights.append(text)

            # Extract patterns from table rows (pattern | count style)
            for m in re.finditer(r"\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|", body):
                pattern_name = m.group(1).strip()
                if len(pattern_name) > 3:
                    known_patterns.append(pattern_name)

            # Extract covered topics from headings
            for m in re.finditer(r"###?\s+([A-Za-z &]+)", body):
                past_topics.add(m.group(1).strip())

    # Deduplicate
    known_patterns = list(dict.fromkeys(known_patterns))[:50]
    insights = list(dict.fromkeys(insights))[:40]

    print(
        f"  ✓ Knowledge layer: {len(known_repos)} known repos, "
        f"{len(known_patterns)} patterns, {len(insights)} insights"
    )
    return {
        "known_repos": known_repos,
        "known_patterns": known_patterns,
        "past_topics": past_topics,
        "insights": insights,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Live Research via GitHub REST API
# ---------------------------------------------------------------------------

def _decode_readme(readme_data: Optional[Dict[str, Any]]) -> str:
    """Decode a base64-encoded README API response."""
    if not readme_data or "content" not in readme_data:
        return ""
    try:
        return base64.b64decode(readme_data["content"]).decode("utf-8", errors="replace")[:5000]
    except Exception:
        return ""


def fetch_repo_details(full_name: str) -> Dict[str, Any]:
    """
    Fetch enriched metadata for a single repository:
    README, recent commits, contributor count, language breakdown, open issues.
    """
    details: Dict[str, Any] = {}

    # README
    readme_data = gh_get(f"/repos/{full_name}/readme")
    details["readme"] = _decode_readme(readme_data)

    # Recent commits (last 5)
    commits_data = gh_get(f"/repos/{full_name}/commits?per_page=5")
    if isinstance(commits_data, list):
        details["recent_commits"] = [
            {
                "sha": c.get("sha", "")[:7],
                "message": (c.get("commit", {}).get("message") or "")[:100],
                "date": (c.get("commit", {}).get("author") or {}).get("date", "")[:10],
            }
            for c in commits_data
        ]
    else:
        details["recent_commits"] = []

    # Language breakdown (only in deep-dive mode to save API quota)
    if RESEARCH_DEEP_DIVE:
        lang_data = gh_get(f"/repos/{full_name}/languages")
        if isinstance(lang_data, dict):
            total_bytes = sum(lang_data.values()) or 1
            details["languages"] = {
                lang: f"{bytes_count / total_bytes * 100:.1f}%"
                for lang, bytes_count in sorted(
                    lang_data.items(), key=lambda x: x[1], reverse=True
                )[:5]
            }
        else:
            details["languages"] = {}
    else:
        details["languages"] = {}

    # Top-level file tree
    tree = gh_get(f"/repos/{full_name}/contents")
    details["top_files"] = (
        [f.get("name", "") for f in (tree or [])[:60]]
        if isinstance(tree, list) else []
    )

    return details


def research_topic(topic: str, known_repos: Set[str]) -> List[Dict[str, Any]]:
    """Search GitHub for repos matching *topic* and fetch enriched details."""
    print(f"  📡 Researching topic: {topic}")
    query = f"topic:{topic}" if " " not in topic else topic
    items = gh_search_repos(query, per_page=MAX_REPOS + 3)

    repos: List[Dict[str, Any]] = []
    new_count = 0
    for item in items:
        full_name = item.get("full_name", "")
        if not full_name or full_name in known_repos:
            continue  # skip already-studied repos
        if new_count >= MAX_REPOS:
            break

        print(f"    🔎 Fetching details: {full_name} ({item.get('stargazers_count', 0)}⭐)")
        details = fetch_repo_details(full_name)
        time.sleep(0.8)  # polite rate-limit

        repos.append({
            "full_name": full_name,
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "open_issues": item.get("open_issues_count", 0),
            "watchers": item.get("watchers_count", 0),
            "description": (item.get("description") or "")[:200],
            "language": item.get("language") or "Unknown",
            "topics": (item.get("topics") or [])[:15],
            "url": item.get("html_url", ""),
            "homepage": item.get("homepage") or "",
            "created_at": (item.get("created_at") or "")[:10],
            "updated_at": (item.get("updated_at") or "")[:10],
            "archived": item.get("archived", False),
            "source_topic": topic,
            "category": _TOPIC_CATEGORIES.get(topic, "General"),
            **details,
        })
        new_count += 1

    print(f"  ✓ {len(repos)} new repos for '{topic}'")
    return repos


def collect_research(known_repos: Set[str]) -> List[Dict[str, Any]]:
    """Research all topics and return a deduplicated list of repos."""
    all_repos: List[Dict[str, Any]] = []
    seen: Set[str] = set(known_repos)

    for topic in TOPICS:
        found = research_topic(topic, seen)
        for r in found:
            seen.add(r["full_name"])
        all_repos.extend(found)
        time.sleep(1.2)

    return all_repos


# ---------------------------------------------------------------------------
# Phase 3 — Deep Analysis of each repo
# ---------------------------------------------------------------------------

# Keyword categories for pattern detection
_PATTERN_KEYWORDS: Dict[str, List[str]] = {
    "Architecture Patterns": [
        "microkernel", "event-driven", "message bus", "pub/sub",
        "pipeline", "orchestrat", "plugin", "modular", "layered",
        "hexagonal", "clean architecture", "domain-driven",
    ],
    "AI/ML Techniques": [
        "reinforcement learning", "transformer", "attention", "embedding",
        "vector store", "rag", "retrieval", "fine-tun", "lora", "qlora",
        "chain-of-thought", "few-shot", "zero-shot", "agent",
    ],
    "Memory & Knowledge": [
        "knowledge graph", "memory", "long-term", "episodic",
        "semantic memory", "vector database", "chromadb", "faiss",
        "qdrant", "pinecone", "weaviate", "neo4j", "graph neural",
    ],
    "Self-Improvement": [
        "self-improv", "self-heal", "auto-tune", "meta-learn", "evolv",
        "continual learning", "lifelong", "online learning", "feedback loop",
        "self-optimiz", "curriculum learning",
    ],
    "Deployment & DevOps": [
        "docker", "kubernetes", "ci/cd", "github actions", "terraform",
        "monitoring", "observability", "tracing", "logging", "alerting",
        "canary", "blue-green", "rollback", "health check",
    ],
    "Code Quality": [
        "type hint", "mypy", "pylint", "ruff", "black", "pytest",
        "test coverage", "pre-commit", "linting", "static analysis",
    ],
}


def _match(text: str, keywords: List[str]) -> List[str]:
    lower = text.lower()
    return [kw for kw in keywords if kw in lower]


def analyse_repo(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Extract patterns and insights from a single repo."""
    readme = repo.get("readme", "")
    files_str = " ".join(repo.get("top_files", []))
    desc = repo.get("description", "")
    topics_str = " ".join(repo.get("topics", []))
    combined = f"{readme} {files_str} {desc} {topics_str}"

    patterns: Dict[str, List[str]] = {
        cat: _match(combined, kws)
        for cat, kws in _PATTERN_KEYWORDS.items()
    }
    total_patterns = sum(len(v) for v in patterns.values())

    # Health indicators from file tree
    top_files = repo.get("top_files", [])
    has_tests = any(f.startswith("test") for f in top_files)
    has_docker = "Dockerfile" in top_files or "docker-compose.yml" in top_files
    has_ci = ".github" in top_files
    has_docs = any(f.endswith(".md") for f in top_files)
    has_pyproject = "pyproject.toml" in top_files
    has_makefile = "Makefile" in top_files

    # Activity metric from recent commits
    recent_commits = repo.get("recent_commits", [])
    last_commit_date = recent_commits[0]["date"] if recent_commits else "unknown"

    return {
        "full_name": repo["full_name"],
        "stars": repo["stars"],
        "forks": repo["forks"],
        "open_issues": repo["open_issues"],
        "url": repo["url"],
        "description": desc,
        "language": repo["language"],
        "category": repo["category"],
        "source_topic": repo["source_topic"],
        "patterns": patterns,
        "total_patterns": total_patterns,
        "has_tests": has_tests,
        "has_docker": has_docker,
        "has_ci": has_ci,
        "has_docs": has_docs,
        "has_pyproject": has_pyproject,
        "has_makefile": has_makefile,
        "last_commit_date": last_commit_date,
        "top_files": top_files[:20],
        "languages": repo.get("languages", {}),
        "archived": repo.get("archived", False),
    }


def analyse_all(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyse all repos and return enriched records."""
    return [analyse_repo(r) for r in repos]


# ---------------------------------------------------------------------------
# Phase 4 — Synthesis with Knowledge Layer
# ---------------------------------------------------------------------------

def synthesise(
    analyses: List[Dict[str, Any]],
    knowledge: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Aggregate per-repo analyses into cross-cutting insights,
    enriched with the existing knowledge layer.
    """
    pattern_freq: Dict[str, Dict[str, int]] = {cat: {} for cat in _PATTERN_KEYWORDS}
    lang_counts: Dict[str, int] = {}

    for a in analyses:
        for cat, matched in a["patterns"].items():
            for kw in matched:
                pattern_freq[cat][kw] = pattern_freq[cat].get(kw, 0) + 1
        lang = a.get("language") or "Unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    def _top(d: Dict[str, int], n: int = 8) -> List[Tuple[str, int]]:
        return sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]

    # Identify high-value repos (many patterns + high stars)
    sorted_stars = sorted(a["stars"] for a in analyses)
    p75_idx = min(int(len(sorted_stars) * 0.75), len(sorted_stars) - 1)
    star_p75 = sorted_stars[p75_idx] if sorted_stars else 0
    high_value = sorted(
        [a for a in analyses if a["total_patterns"] >= 3 and a["stars"] >= star_p75],
        key=lambda x: x["total_patterns"] * x["stars"],
        reverse=True,
    )[:8]

    # New knowledge: patterns NOT in past knowledge layer
    past_patterns_set = set(p.lower() for p in knowledge.get("known_patterns", []))
    new_insights: List[str] = []
    for a in analyses:
        for cat, matched in a["patterns"].items():
            for kw in matched:
                if kw not in past_patterns_set:
                    new_insights.append(f"{kw} ({cat}) — found in {a['full_name']}")
    new_insights = list(dict.fromkeys(new_insights))[:20]

    return {
        "total_repos_studied": len(analyses),
        "pattern_freq": {cat: _top(freq) for cat, freq in pattern_freq.items()},
        "top_languages": _top(lang_counts, 6),
        "high_value_repos": high_value,
        "new_insights": new_insights,
        "past_insights": knowledge.get("insights", [])[:10],
        "categories": {a["category"] for a in analyses},
    }


# ---------------------------------------------------------------------------
# Phase 5 — Build the GitHub Issue body
# ---------------------------------------------------------------------------

def build_issue_body(
    analyses: List[Dict[str, Any]],
    synthesis: Dict[str, Any],
    knowledge: Dict[str, Any],
) -> str:
    """Render the full GitHub Issue markdown."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    past_count = len(knowledge.get("known_repos", set()))

    lines: List[str] = [
        "# 🔬 Nibblebot Research Report",
        "",
        f"**Generated:** {now}  ",
        f"**Repos studied this run:** {synthesis['total_repos_studied']}  ",
        f"**Known repos (from knowledge layer):** {past_count}  ",
        f"**Topics covered:** {', '.join(TOPICS[:8])}{'…' if len(TOPICS) > 8 else ''}",
        "",
        (
            "> This report is generated by the Nibblebot Research Bot using the GitHub REST API.\n"
            "> It accumulates knowledge across runs to make Niblit and Nibblebot progressively\n"
            "> more knowledgeable about software patterns and best practices."
        ),
        "",
    ]

    # ── Knowledge Layer Summary ──────────────────────────────────────────
    if knowledge.get("insights"):
        lines += [
            "## 📚 Knowledge Layer — Carried-Forward Insights",
            "",
            "_From previous research runs:_",
            "",
        ]
        for insight in knowledge["insights"][:8]:
            lines.append(f"- 📌 {insight}")
        lines.append("")

    # ── New Discoveries ──────────────────────────────────────────────────
    if synthesis["new_insights"]:
        lines += [
            "## 💡 New Discoveries (Not in Previous Reports)",
            "",
        ]
        for insight in synthesis["new_insights"][:15]:
            lines.append(f"- ✨ {insight}")
        lines.append("")

    # ── Pattern Frequency Tables ─────────────────────────────────────────
    lines += ["## 📊 Most Common Patterns Found Across Repos", ""]
    for cat, top_patterns in synthesis["pattern_freq"].items():
        if not top_patterns:
            continue
        lines += [
            f"### {cat}",
            "",
            "| Pattern | Repos |",
            "|---------|-------|",
        ]
        for kw, count in top_patterns:
            lines.append(f"| `{kw}` | {count} |")
        lines.append("")

    # ── Top Languages ────────────────────────────────────────────────────
    lines += [
        "## 🌐 Language Landscape",
        "",
        "| Language | Repos |",
        "|----------|-------|",
    ]
    for lang, count in synthesis["top_languages"]:
        lines.append(f"| {lang} | {count} |")
    lines.append("")

    # ── High-Value Repos ─────────────────────────────────────────────────
    if synthesis["high_value_repos"]:
        lines += [
            "## ⭐ High-Value Repositories (Deep-Study Candidates)",
            "",
            "| Repo | Stars | Category | Key Patterns | Last Commit |",
            "|------|-------|----------|-------------|------------|",
        ]
        for a in synthesis["high_value_repos"]:
            all_kws = [kw for kws in a["patterns"].values() for kw in kws][:4]
            kw_str = ", ".join(f"`{k}`" for k in all_kws) if all_kws else "—"
            lines.append(
                f"| [{a['full_name']}]({a['url']}) "
                f"| {a['stars']:,} "
                f"| {a['category']} "
                f"| {kw_str} "
                f"| {a['last_commit_date']} |"
            )
        lines.append("")

    # ── Per-Category Breakdown ────────────────────────────────────────────
    lines += ["## 🗂️ Research by Category", ""]
    categories_seen: Set[str] = set()
    for a in sorted(analyses, key=lambda x: x["category"]):
        cat = a["category"]
        if cat not in categories_seen:
            categories_seen.add(cat)
            lines += [f"### {cat}", ""]

        health_badges: List[str] = []
        if a["has_tests"]:
            health_badges.append("✅ tests")
        if a["has_docker"]:
            health_badges.append("🐳 docker")
        if a["has_ci"]:
            health_badges.append("⚙️ CI")
        if a["has_docs"]:
            health_badges.append("📄 docs")
        health_str = " · ".join(health_badges) if health_badges else "_no markers_"

        all_kws = [kw for kws in a["patterns"].values() for kw in kws][:5]
        kw_str = ", ".join(f"`{k}`" for k in all_kws) if all_kws else "—"

        lines += [
            f"**[{a['full_name']}]({a['url']})** — {a['stars']:,}⭐  ",
            f"_{a['description'] or 'No description'}_  ",
            f"Lang: `{a['language']}` | Health: {health_str}  ",
            f"Patterns: {kw_str}",
            "",
        ]

    # ── Actionable Recommendations for Niblit ───────────────────────────
    lines += [
        "## 🛠️ Actionable Recommendations for Niblit",
        "",
    ]
    # Build recommendations from top patterns
    rec_set: List[str] = []
    all_freq: Dict[str, int] = {}
    for cat, top_patterns in synthesis["pattern_freq"].items():
        for kw, cnt in top_patterns:
            all_freq[kw] = all_freq.get(kw, 0) + cnt
    top_overall = sorted(all_freq.items(), key=lambda x: x[1], reverse=True)[:5]

    for kw, cnt in top_overall:
        rec_set.append(
            f"- **`{kw}`** appeared in **{cnt}** studied repos — "
            f"consider whether Niblit already implements or could benefit from this pattern."
        )

    if not rec_set:
        rec_set.append("- No dominant patterns identified in this run. Expand RESEARCH_TOPICS for broader coverage.")
    lines += rec_set
    lines.append("")

    # ── Knowledge Growth Tracker ─────────────────────────────────────────
    lines += [
        "## 📈 Knowledge Growth",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Repos in knowledge layer (before this run) | {past_count} |",
        f"| New repos researched | {synthesis['total_repos_studied']} |",
        f"| New pattern insights discovered | {len(synthesis['new_insights'])} |",
        f"| Topics covered cumulatively | {len(TOPICS)} |",
        "",
    ]

    # Footer
    lines += [
        "---",
        "",
        "_Nibblebot Research Bot v2 — Live GitHub REST API + Knowledge Layer_  ",
        "_Part of the [Niblit](https://github.com/riddo9906/Niblit) project_",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------

def find_open_issue() -> Optional[int]:
    """Return the number of an existing open nibblebot-research issue, or None."""
    data = gh_get(
        f"/repos/{REPO}/issues?labels={ISSUE_LABEL}&state=open&per_page=10"
    )
    if not data:
        return None
    for issue in data:
        if ISSUE_TITLE_PREFIX in issue.get("title", ""):
            return issue["number"]
    return None


def create_or_update_issue(title: str, body: str) -> None:
    """Create a new issue or update the body of the existing one."""
    existing = find_open_issue()
    if existing:
        print(f"  ✏️  Updating existing issue #{existing}…")
        gh_patch(f"/repos/{REPO}/issues/{existing}", {"body": body})
        print(f"  ✓ Issue #{existing} updated.")
    else:
        print("  🆕 Creating new issue…")
        result = gh_post(
            f"/repos/{REPO}/issues",
            {"title": title, "body": body, "labels": [ISSUE_LABEL]},
        )
        if result:
            print(f"  ✓ Issue #{result.get('number')} created: {result.get('html_url')}")
        else:
            print("  ⚠ Failed to create issue.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Phase 6 — Niblit Integration: feed discoveries back into Niblit subsystems
# ---------------------------------------------------------------------------

def build_niblit_findings(
    analyses: List[Dict[str, Any]],
    synthesis: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a structured findings dict consumable by Niblit's
    ``SelfImprovementOrchestrator.ingest_research_findings()``.

    This is the bridge between the external research loop (nibblebot) and
    Niblit's internal self-improvement subsystems.
    """
    # Aggregate patterns across all analyses
    all_patterns: Dict[str, List[str]] = {}
    for a in analyses:
        for cat, kws in a.get("patterns", {}).items():
            if cat not in all_patterns:
                all_patterns[cat] = []
            for kw in kws:
                if kw not in all_patterns[cat]:
                    all_patterns[cat].append(kw)

    # Top repos as lightweight dicts for RAG indexing
    top_repos = [
        {
            "full_name": a["full_name"],
            "description": a.get("description", ""),
            "stars": a.get("stars", 0),
            "patterns": [kw for kws in a.get("patterns", {}).values() for kw in kws],
        }
        for a in sorted(analyses, key=lambda x: x.get("stars", 0), reverse=True)[:8]
    ]

    # Top-frequency recommendations
    all_freq: Dict[str, int] = {}
    for cat, top_patterns in synthesis.get("pattern_freq", {}).items():
        for kw, cnt in top_patterns:
            all_freq[kw] = all_freq.get(kw, 0) + cnt
    recommendations = [
        f"{kw} appeared in {cnt} studied repos"
        for kw, cnt in sorted(all_freq.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    return {
        "patterns": all_patterns,
        "new_insights": synthesis.get("new_insights", []),
        "top_repos": top_repos,
        "recommendations": recommendations,
    }


def niblit_integrate(findings: Dict[str, Any]) -> None:
    """
    Feed research findings into Niblit's SelfImprovementOrchestrator.

    This runs inside the nibblebot Action environment where Niblit's Python
    modules are available (they are in the repository root).  If the import
    fails (e.g. missing heavy dependencies) the function logs a warning and
    returns gracefully — the research report is always published regardless.
    """
    import sys as _sys
    import os as _os

    # Add repository root to sys.path so Niblit modules are importable
    _repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)

    try:
        from modules.self_improvement_orchestrator import SelfImprovementOrchestrator
        orchestrator = SelfImprovementOrchestrator()
        result = orchestrator.ingest_research_findings(
            findings, source="nibblebot-research"
        )
        print(
            f"  🔗 Niblit integration: "
            f"topics={result['ale_topics_queued']} "
            f"facts={result['facts_stored']} "
            f"docs={result['docs_indexed']}"
        )
    except ImportError as exc:
        print(f"  ℹ Niblit integration skipped (SelfImprovementOrchestrator not importable): {exc}")
    except Exception as exc:
        print(f"  ⚠ Niblit integration error: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("🔬 Nibblebot Research Bot v2 starting…")
    print(f"   Repo       : {REPO}")
    print(f"   Topics     : {', '.join(TOPICS[:5])}{'…' if len(TOPICS) > 5 else ''}")
    print(f"   Max repos  : {MAX_REPOS} per topic")
    print(f"   Deep dive  : {RESEARCH_DEEP_DIVE}")
    print(f"   Dry run    : {DRY_RUN}")
    print()

    if not TOKEN:
        print(
            "⚠ GITHUB_TOKEN not set — API calls will be unauthenticated and heavily rate-limited.",
            file=sys.stderr,
        )

    # Phase 1 — Knowledge Layer
    print("📚 Phase 1: Loading knowledge layer…")
    knowledge = load_knowledge_layer()
    print()

    # Phase 2 — Live Research
    print("📡 Phase 2: Live research on GitHub…")
    repos = collect_research(knowledge["known_repos"])
    if not repos:
        print("⚠ No new repos found. Expand RESEARCH_TOPICS or increase RESEARCH_MAX_REPOS.")
        return
    print(f"\n  ✓ Total new repos collected: {len(repos)}")
    print()

    # Phase 3 — Analysis
    print("🧠 Phase 3: Analysing repos…")
    analyses = analyse_all(repos)
    print(f"  ✓ Analysed {len(analyses)} repos")
    print()

    # Phase 4 — Synthesis
    print("⚗️  Phase 4: Synthesising findings with knowledge layer…")
    synthesis = synthesise(analyses, knowledge)
    print(f"  ✓ Found {len(synthesis['new_insights'])} new insights")
    print()

    # Phase 5 — Report
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    title = f"{ISSUE_TITLE_PREFIX} — {now_str} ({synthesis['total_repos_studied']} repos)"
    body = build_issue_body(analyses, synthesis, knowledge)

    if DRY_RUN:
        print("\n" + "=" * 70)
        print(f"DRY RUN — Issue title: {title}")
        print("=" * 70)
        print(body[:3000] + ("\n…[truncated]" if len(body) > 3000 else ""))
        print("=" * 70)
    else:
        print(f"📝 Phase 5: Publishing issue: {title}")
        create_or_update_issue(title, body)

    # Phase 6 — Feed discoveries into Niblit's self-improvement subsystems
    print("\n🔗 Phase 6: Feeding discoveries into Niblit…")
    findings = build_niblit_findings(analyses, synthesis)
    niblit_integrate(findings)

    print("\n✅ Nibblebot Research Bot finished.")


if __name__ == "__main__":
    main()
