#!/usr/bin/env python3
"""
nibblebot-aios-integration  —  Nibblebot that researches top AI repositories
on GitHub and proposes how their best patterns and ideas can be integrated
into Niblit to make it a complete, working AI Operating System.

The bot studies successful open-source AI projects — LLM frameworks, agent
orchestrators, AI operating systems, edge-AI runtimes, and self-improving
AI — then extracts transferable patterns, identifies gaps in Niblit, and
produces a prioritised integration roadmap published as a GitHub Issue.

IMPORTANT: This bot NEVER commits or pushes code.  It ONLY creates or
updates GitHub Issues with integration proposals.

Runs as a scheduled GitHub Action (like Dependabot).

Usage (local testing):
    GITHUB_TOKEN=ghp_... python nibblebots/aios_integration_bot.py

Environment variables:
    GITHUB_TOKEN           — GitHub token with repo + issues scope
    GITHUB_REPOSITORY      — owner/repo  (set automatically in Actions)
    INTEGRATION_TOPICS     — comma-separated override for search topics
    INTEGRATION_MAX_REPOS  — max repos per category to study (default: 5)
    INTEGRATION_DRY_RUN    — set to "true" to print instead of creating issue
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-AIOS-Integration/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
MAX_REPOS = int(os.environ.get("INTEGRATION_MAX_REPOS", "5"))
DRY_RUN = os.environ.get("INTEGRATION_DRY_RUN", "").lower() == "true"
ISSUE_LABEL = "nibblebot-aios"
ISSUE_TITLE_PREFIX = "🔗 Nibblebot AIOS Integration Roadmap"

# Categories of AI repos to study, each with search queries.
DEFAULT_CATEGORIES: Dict[str, List[str]] = {
    "LLM Frameworks": [
        "langchain", "llamaindex", "vllm-project/vllm",
        "ollama/ollama", "huggingface/transformers",
    ],
    "AI Agents": [
        "microsoft/autogen", "joaomdmoura/crewAI",
        "yoheinakajima/babyagi",
    ],
    "AI Operating Systems": [
        "agiresearch/AIOS", "microsoft/JARVIS",
        "OpenInterpreter/open-interpreter",
    ],
    "Edge / Embedded AI": [
        "onnxruntime", "tflite-micro",
        "Tencent/ncnn",
    ],
    "Self-Improving AI": [
        "MineDojo/Voyager", "joonspk-research/generative_agents",
    ],
}

# Allow env-var override of categories (flat comma-separated repo queries)
_env_topics = os.environ.get("INTEGRATION_TOPICS", "")
if _env_topics.strip():
    DEFAULT_CATEGORIES = {
        "Custom": [t.strip() for t in _env_topics.split(",") if t.strip()]
    }


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def gh_get(path: str) -> Any:
    """GET from GitHub REST API v3.  Returns parsed JSON or None on error."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API GET error: {path} → {exc}", file=sys.stderr)
        return None


def gh_post(path: str, body: Dict[str, Any]) -> Any:
    """POST to GitHub REST API v3.  Returns parsed JSON or None."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    data = json.dumps(body).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API POST error: {path} → {exc}", file=sys.stderr)
        return None


def gh_patch(path: str, body: Dict[str, Any]) -> Any:
    """PATCH to GitHub REST API v3.  Returns parsed JSON or None."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    data = json.dumps(body).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, data=data, headers=headers, method="PATCH")
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API PATCH error: {path} → {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 1. Research top AI repos
# ---------------------------------------------------------------------------

def _search_repo(query: str) -> Optional[Dict[str, Any]]:
    """Search GitHub for a single repo by name/query and return metadata."""
    # If the query looks like "owner/repo", try direct lookup first.
    if "/" in query and " " not in query:
        data = gh_get(f"/repos/{query}")
        if data and "full_name" in data:
            return data
    # Fall back to search
    safe_q = query.replace(" ", "+")
    data = gh_get(f"/search/repositories?q={safe_q}&sort=stars&per_page=1")
    if data and data.get("items"):
        return data["items"][0]
    return None


def _fetch_repo_details(item: Dict[str, Any]) -> Dict[str, Any]:
    """Given a repo API object, fetch its README and file tree."""
    full_name = item.get("full_name", "")

    # Top-level file list
    tree = gh_get(f"/repos/{full_name}/contents")
    top_files: List[str] = []
    if isinstance(tree, list):
        top_files = [f.get("name", "") for f in tree[:60]]

    # README content (first ~3000 chars for deeper analysis)
    readme_text = ""
    readme_data = gh_get(f"/repos/{full_name}/readme")
    if readme_data and "content" in readme_data:
        try:
            raw = base64.b64decode(readme_data["content"]).decode(
                "utf-8", errors="replace"
            )
            readme_text = raw[:3000]
        except Exception:
            pass

    return {
        "full_name": full_name,
        "stars": item.get("stargazers_count", 0),
        "description": (item.get("description") or "")[:250],
        "language": item.get("language", ""),
        "topics": (item.get("topics") or [])[:12],
        "top_files": top_files,
        "readme_snippet": readme_text,
        "url": item.get("html_url", ""),
    }


def research_repos(
    categories: Dict[str, List[str]],
    max_per_cat: int = MAX_REPOS,
) -> Dict[str, List[Dict[str, Any]]]:
    """Research repos across all categories.  Returns {category: [repo_info]}."""
    results: Dict[str, List[Dict[str, Any]]] = {}
    for cat_name, queries in categories.items():
        cat_repos: List[Dict[str, Any]] = []
        for query in queries[:max_per_cat]:
            print(f"  📡 [{cat_name}] Searching: {query}")
            item = _search_repo(query)
            if item:
                info = _fetch_repo_details(item)
                cat_repos.append(info)
                print(f"      ✓ {info['full_name']} (★{info['stars']:,})")
            else:
                print(f"      ✗ Not found: {query}")
            time.sleep(0.8)  # polite rate-limit
        results[cat_name] = cat_repos
    return results


# ---------------------------------------------------------------------------
# 2. Extract integration opportunities
# ---------------------------------------------------------------------------

# Pattern keywords to look for in READMEs and file structures
PATTERN_KEYWORDS: Dict[str, Dict[str, str]] = {
    "plugin": {
        "label": "Plugin / Extension Architecture",
        "difficulty": "Medium",
        "impact": "High",
    },
    "tool": {
        "label": "Tool-Use / Function Calling",
        "difficulty": "Medium",
        "impact": "High",
    },
    "memory": {
        "label": "Long-Term Memory / RAG",
        "difficulty": "Medium",
        "impact": "High",
    },
    "vector": {
        "label": "Vector Store Integration",
        "difficulty": "Medium",
        "impact": "High",
    },
    "scheduler": {
        "label": "Task Scheduler / Planner",
        "difficulty": "Hard",
        "impact": "High",
    },
    "sandbox": {
        "label": "Code Sandbox / Safe Execution",
        "difficulty": "Hard",
        "impact": "High",
    },
    "benchmark": {
        "label": "Benchmark / Eval Suite",
        "difficulty": "Easy",
        "impact": "Medium",
    },
    "docker": {
        "label": "Containerised Deployment",
        "difficulty": "Easy",
        "impact": "Medium",
    },
    "api": {
        "label": "REST / gRPC API Layer",
        "difficulty": "Easy",
        "impact": "Medium",
    },
    "multi-agent": {
        "label": "Multi-Agent Collaboration",
        "difficulty": "Hard",
        "impact": "High",
    },
    "self-heal": {
        "label": "Self-Healing / Auto-Recovery",
        "difficulty": "Medium",
        "impact": "High",
    },
    "fine-tun": {
        "label": "Fine-Tuning Pipeline",
        "difficulty": "Hard",
        "impact": "Medium",
    },
    "quantiz": {
        "label": "Model Quantization / Optimization",
        "difficulty": "Hard",
        "impact": "Medium",
    },
    "stream": {
        "label": "Streaming / Real-Time Output",
        "difficulty": "Easy",
        "impact": "Medium",
    },
    "embed": {
        "label": "Embedding Generation",
        "difficulty": "Easy",
        "impact": "Medium",
    },
    "workflow": {
        "label": "Workflow / DAG Orchestration",
        "difficulty": "Hard",
        "impact": "High",
    },
    "observ": {
        "label": "Observability / Tracing",
        "difficulty": "Medium",
        "impact": "Medium",
    },
    "permiss": {
        "label": "Permission / Access Control",
        "difficulty": "Medium",
        "impact": "Medium",
    },
    "event": {
        "label": "Event-Driven Architecture",
        "difficulty": "Medium",
        "impact": "High",
    },
    "cli": {
        "label": "CLI Interface",
        "difficulty": "Easy",
        "impact": "Medium",
    },
}


def extract_patterns(repo: Dict[str, Any]) -> List[Dict[str, str]]:
    """Scan a repo's README and file list for integration-worthy patterns."""
    readme_lower = repo.get("readme_snippet", "").lower()
    files_lower = " ".join(f.lower() for f in repo.get("top_files", []))
    combined = readme_lower + " " + files_lower

    found: List[Dict[str, str]] = []
    for keyword, meta in PATTERN_KEYWORDS.items():
        if keyword in combined:
            # Grab a brief context snippet from the README
            idx = readme_lower.find(keyword)
            snippet = ""
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(readme_lower), idx + 100)
                snippet = repo.get("readme_snippet", "")[start:end].strip()
                snippet = re.sub(r"\s+", " ", snippet)[:140]
            found.append({
                "pattern": meta["label"],
                "source_repo": repo["full_name"],
                "source_url": repo["url"],
                "difficulty": meta["difficulty"],
                "impact": meta["impact"],
                "context_snippet": snippet,
            })
    return found


def extract_all_opportunities(
    categorised_repos: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, str]]:
    """Extract integration opportunities across all studied repos."""
    all_opps: List[Dict[str, str]] = []
    for _cat, repos in categorised_repos.items():
        for repo in repos:
            opps = extract_patterns(repo)
            all_opps.extend(opps)
    return all_opps


# ---------------------------------------------------------------------------
# 3. Cross-reference with Niblit local checkout
# ---------------------------------------------------------------------------

def scan_niblit_codebase() -> Dict[str, Any]:
    """Scan the local Niblit checkout to understand its current capabilities."""
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    if not root.is_dir():
        root = Path(".").resolve()

    py_files: List[str] = []
    modules: List[str] = []
    test_files: List[str] = []
    total_lines = 0

    for p in root.rglob("*.py"):
        if any(part.startswith(".") for part in p.parts):
            continue
        rel = str(p.relative_to(root))
        if "__pycache__" in rel or "node_modules" in rel:
            continue
        py_files.append(rel)
        try:
            total_lines += sum(1 for _ in p.open())
        except OSError:
            pass
        if p.name.startswith("test_"):
            test_files.append(rel)

    # Identify Niblit-specific modules by naming patterns
    niblit_keywords = [
        "memory", "brain", "router", "sensor", "voice", "net",
        "guard", "heal", "learn", "identity", "orchestrat", "agent",
        "tool", "core", "io", "env", "task", "manager", "sqlite",
        "deploy", "model", "cache", "action", "pipeline", "evolve",
    ]
    capability_map: Dict[str, bool] = {}
    all_names = " ".join(py_files).lower()
    for kw in niblit_keywords:
        capability_map[kw] = kw in all_names

    # Top-level directories
    top_dirs = sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

    top_files = sorted(
        f.name for f in root.iterdir()
        if f.is_file() and not f.name.startswith(".")
    )

    return {
        "py_count": len(py_files),
        "test_count": len(test_files),
        "total_lines": total_lines,
        "capabilities": capability_map,
        "top_dirs": top_dirs[:30],
        "top_files": top_files[:40],
        "py_files": py_files,
    }


def gap_analysis(
    niblit: Dict[str, Any],
    opportunities: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[str], List[str]]:
    """Compare opportunities against Niblit capabilities.

    Returns:
        gaps:      opportunities Niblit is missing
        strengths: capabilities Niblit already has
        present:   pattern labels already partially covered
    """
    caps = niblit.get("capabilities", {})
    all_files_lower = " ".join(niblit.get("py_files", [])).lower()

    strengths: List[str] = []
    for kw, present in caps.items():
        if present:
            strengths.append(kw)

    # Determine which patterns Niblit already has some coverage for
    present_labels: List[str] = []
    gaps: List[Dict[str, str]] = []

    seen_patterns: set = set()
    for opp in opportunities:
        label = opp["pattern"]
        if label in seen_patterns:
            continue
        seen_patterns.add(label)

        # Rough check: does Niblit already have something related?
        label_lower = label.lower()
        related_kws = [w for w in label_lower.split() if len(w) > 3]
        has_coverage = any(kw in all_files_lower for kw in related_kws)

        if has_coverage:
            present_labels.append(label)
        else:
            gaps.append(opp)

    return gaps, strengths, present_labels


# ---------------------------------------------------------------------------
# 4. Generate integration roadmap
# ---------------------------------------------------------------------------

DIFFICULTY_ORDER = {"Easy": 0, "Medium": 1, "Hard": 2}
IMPACT_ORDER = {"High": 0, "Medium": 1, "Low": 2}

# Map patterns to the Niblit module they most likely relate to
MODULE_MAP: Dict[str, str] = {
    "Plugin / Extension Architecture": "module_loader.py / niblit_router.py",
    "Tool-Use / Function Calling": "niblit_tools/",
    "Long-Term Memory / RAG": "niblit_memory.py / niblit_memory/",
    "Vector Store Integration": "niblit_memory/",
    "Task Scheduler / Planner": "niblit_tasks.py / niblit_orchestrator.py",
    "Code Sandbox / Safe Execution": "niblit_guard.py",
    "Benchmark / Eval Suite": "test_*.py files",
    "Containerised Deployment": "Dockerfile / fly.toml",
    "REST / gRPC API Layer": "server.py / api/",
    "Multi-Agent Collaboration": "niblit_agents/ / agents/",
    "Self-Healing / Auto-Recovery": "self_maintenance_full.py / healer_full.py",
    "Fine-Tuning Pipeline": "niblit_models/ / trainer_full.py",
    "Model Quantization / Optimization": "niblit_models/",
    "Streaming / Real-Time Output": "run_realtime.py / niblit_io.py",
    "Embedding Generation": "niblit_memory/ / niblit_hf.py",
    "Workflow / DAG Orchestration": "niblit_orchestrator.py / orchestrator.py",
    "Observability / Tracing": "niblit_full_pipeline.log / events.jsonl",
    "Permission / Access Control": "niblit_guard.py / niblit_identity.py",
    "Event-Driven Architecture": "events.jsonl / lifecycle_engine.py",
    "CLI Interface": "main.py / live_command_tester.py",
}


def _priority_tier(difficulty: str, impact: str) -> str:
    """Classify an item into Quick-Win / Medium-Term / Long-Term."""
    d = DIFFICULTY_ORDER.get(difficulty, 1)
    i = IMPACT_ORDER.get(impact, 1)
    if d == 0 and i <= 1:
        return "quick_win"
    if d <= 1 and i == 0:
        return "quick_win"
    if d == 2 and i <= 1:
        return "long_term"
    return "medium_term"


def build_roadmap(
    gaps: List[Dict[str, str]],
) -> Dict[str, List[Dict[str, str]]]:
    """Build a prioritised integration roadmap from gap analysis results."""
    roadmap: Dict[str, List[Dict[str, str]]] = {
        "quick_win": [],
        "medium_term": [],
        "long_term": [],
    }

    for gap in gaps:
        tier = _priority_tier(gap.get("difficulty", "Medium"),
                              gap.get("impact", "Medium"))
        niblit_module = MODULE_MAP.get(gap["pattern"], "TBD")
        roadmap[tier].append({
            "pattern": gap["pattern"],
            "source_repo": gap["source_repo"],
            "source_url": gap["source_url"],
            "difficulty": gap["difficulty"],
            "impact": gap["impact"],
            "niblit_module": niblit_module,
            "context": gap.get("context_snippet", ""),
        })

    # Sort each tier: high-impact first, then easy-difficulty first
    for tier_items in roadmap.values():
        tier_items.sort(
            key=lambda x: (
                IMPACT_ORDER.get(x.get("impact", "Medium"), 1),
                DIFFICULTY_ORDER.get(x.get("difficulty", "Medium"), 1),
            )
        )

    return roadmap


# ---------------------------------------------------------------------------
# 5. Format GitHub Issue body
# ---------------------------------------------------------------------------

def _flat_repos(categorised: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Flatten categorised repos into a single list, deduped."""
    seen: set = set()
    flat: List[Dict[str, Any]] = []
    for repos in categorised.values():
        for r in repos:
            if r["full_name"] not in seen:
                seen.add(r["full_name"])
                flat.append(r)
    return flat


def format_issue_body(
    categorised_repos: Dict[str, List[Dict[str, Any]]],
    niblit: Dict[str, Any],
    gaps: List[Dict[str, str]],
    strengths: List[str],
    present_labels: List[str],
    roadmap: Dict[str, List[Dict[str, str]]],
) -> str:
    """Render the full integration roadmap as a Markdown GitHub Issue body."""
    lines: List[str] = []
    today = datetime.date.today().isoformat()

    # Header
    lines.append("## 🔗 AIOS Integration Roadmap\n")
    lines.append(
        "This issue was automatically generated by **Nibblebot AIOS Integration** — "
        "a bot that studies top AI repositories on GitHub and proposes how their "
        "best patterns can be integrated into Niblit to build a complete AI OS.\n"
    )
    lines.append(f"**Generated:** {today}  ")
    all_repos = _flat_repos(categorised_repos)
    lines.append(f"**Repos studied:** {len(all_repos)}  ")
    lines.append(f"**Integration gaps found:** {len(gaps)}  ")
    lines.append(f"**Niblit capabilities confirmed:** {len(strengths)}\n")

    # ── Repos studied ─────────────────────────────────────────────────
    lines.append("---\n### 📚 Repos Studied by Category\n")
    for cat_name, repos in categorised_repos.items():
        if not repos:
            continue
        lines.append(f"**{cat_name}**\n")
        lines.append("| Repo | ★ Stars | Language | Description |")
        lines.append("|------|--------:|----------|-------------|")
        for r in repos:
            desc = (r.get("description") or "—")[:90]
            lines.append(
                f"| [{r['full_name']}]({r['url']}) "
                f"| {r.get('stars', 0):,} "
                f"| {r.get('language', '—')} "
                f"| {desc} |"
            )
        lines.append("")

    # ── Gap analysis ──────────────────────────────────────────────────
    lines.append("---\n### 🔍 Gap Analysis\n")

    if strengths:
        lines.append("**✅ Niblit already covers:**  ")
        lines.append(", ".join(f"`{s}`" for s in sorted(strengths)))
        lines.append("")

    if present_labels:
        lines.append("**🟡 Partially covered (but can be improved):**  ")
        lines.append(", ".join(f"*{p}*" for p in present_labels))
        lines.append("")

    if gaps:
        lines.append("**❌ Missing capabilities (gaps):**\n")
        lines.append("| Pattern | Source Repo | Difficulty | Impact |")
        lines.append("|---------|------------|:----------:|:------:|")
        seen: set = set()
        for g in gaps:
            key = g["pattern"]
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"| {g['pattern']} "
                f"| [{g['source_repo']}]({g['source_url']}) "
                f"| {g['difficulty']} "
                f"| {g['impact']} |"
            )
        lines.append("")

    # ── Integration Roadmap ───────────────────────────────────────────
    lines.append("---\n### 🗺️ Integration Roadmap\n")

    tier_meta = {
        "quick_win": ("🚀 Quick Wins", "Easy to add, high return on effort"),
        "medium_term": ("⚙️ Medium-Term Goals", "Significant features, moderate work"),
        "long_term": ("🏗️ Long-Term Vision", "Major architectural additions"),
    }

    for tier_key in ("quick_win", "medium_term", "long_term"):
        items = roadmap.get(tier_key, [])
        title, desc = tier_meta[tier_key]
        lines.append(f"#### {title}")
        lines.append(f"*{desc}*\n")
        if not items:
            lines.append("_No items in this tier._\n")
            continue
        for item in items:
            lines.append(f"- [ ] **{item['pattern']}**  ")
            lines.append(
                f"  Source: [{item['source_repo']}]({item['source_url']}) "
                f"| Difficulty: {item['difficulty']} "
                f"| Impact: {item['impact']}  "
            )
            lines.append(f"  Niblit module: `{item['niblit_module']}`  ")
            if item.get("context"):
                ctx = item["context"].replace("\n", " ").strip()[:120]
                lines.append(f"  Context: _{ctx}_  ")
            lines.append("")

    # ── Concrete next steps ───────────────────────────────────────────
    lines.append("---\n### ✅ Recommended Next Steps\n")

    quick_items = roadmap.get("quick_win", [])
    if quick_items:
        lines.append("**Immediate (this sprint):**\n")
        for item in quick_items[:5]:
            lines.append(
                f"- [ ] Integrate **{item['pattern']}** pattern from "
                f"[{item['source_repo']}]({item['source_url']}) "
                f"into `{item['niblit_module']}`"
            )
        lines.append("")

    med_items = roadmap.get("medium_term", [])
    if med_items:
        lines.append("**Next month:**\n")
        for item in med_items[:5]:
            lines.append(
                f"- [ ] Design and implement **{item['pattern']}** "
                f"(ref: [{item['source_repo']}]({item['source_url']}))"
            )
        lines.append("")

    long_items = roadmap.get("long_term", [])
    if long_items:
        lines.append("**Longer-term:**\n")
        for item in long_items[:5]:
            lines.append(
                f"- [ ] Research and plan **{item['pattern']}** "
                f"(ref: [{item['source_repo']}]({item['source_url']}))"
            )
        lines.append("")

    # ── Niblit codebase snapshot ──────────────────────────────────────
    lines.append("---\n### 📊 Niblit Codebase Snapshot\n")
    lines.append(f"- **Python files:** {niblit.get('py_count', 0)}")
    lines.append(f"- **Test files:** {niblit.get('test_count', 0)}")
    lines.append(f"- **Total lines:** {niblit.get('total_lines', 0):,}")
    top_dirs = niblit.get("top_dirs", [])
    if top_dirs:
        lines.append(f"- **Top-level dirs:** {', '.join(f'`{d}`' for d in top_dirs[:15])}")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(
        "<sub>🤖 Generated by "
        "[Nibblebot AIOS Integration]"
        "(https://github.com/riddo9906/Niblit/tree/main/nibblebots) — "
        "the Niblit integration research bot.  "
        "Override search topics with `INTEGRATION_TOPICS` in the workflow.  "
        f"Run date: {today}</sub>"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. Create or update the GitHub Issue
# ---------------------------------------------------------------------------

def ensure_label_exists() -> None:
    """Create the 'nibblebot-aios' label if it doesn't already exist."""
    existing = gh_get(f"/repos/{REPO}/labels/{ISSUE_LABEL}")
    if existing and "name" in existing:
        return
    gh_post(f"/repos/{REPO}/labels", {
        "name": ISSUE_LABEL,
        "color": "1d76db",
        "description": "AIOS integration proposals from Nibblebot",
    })


def find_open_issue() -> Optional[int]:
    """Find an existing open issue with our label and title prefix."""
    data = gh_get(
        f"/repos/{REPO}/issues?labels={ISSUE_LABEL}&state=open&per_page=5"
    )
    if not data or not isinstance(data, list):
        return None
    for issue in data:
        title = issue.get("title", "")
        if title.startswith(ISSUE_TITLE_PREFIX):
            return issue["number"]
    return None


def create_or_update_issue(body: str) -> None:
    """Create a new GitHub Issue or update the existing one.

    IMPORTANT: This function ONLY creates/updates issues.
    It never commits, pushes, or modifies code.
    """
    ensure_label_exists()
    existing_number = find_open_issue()
    date_str = datetime.date.today().isoformat()
    title = f"{ISSUE_TITLE_PREFIX} — {date_str}"

    if existing_number:
        print(f"  📝 Updating existing issue #{existing_number}")
        result = gh_patch(
            f"/repos/{REPO}/issues/{existing_number}",
            {"title": title, "body": body},
        )
        if result and "html_url" in result:
            print(f"  ✅ Updated: {result['html_url']}")
        else:
            print("  ⚠ Failed to update issue", file=sys.stderr)
    else:
        print("  📝 Creating new issue")
        result = gh_post(f"/repos/{REPO}/issues", {
            "title": title,
            "body": body,
            "labels": [ISSUE_LABEL],
        })
        if result and "html_url" in result:
            print(f"  ✅ Created: {result['html_url']}")
        else:
            print("  ⚠ Failed to create issue", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the AIOS Integration Bot.

    Pipeline:
        1. Research top AI repos across multiple categories
        2. Extract transferable patterns and integration opportunities
        3. Scan the local Niblit codebase for current capabilities
        4. Perform gap analysis (what Niblit has vs. what it's missing)
        5. Build a prioritised integration roadmap
        6. Publish results as a GitHub Issue
    """
    print("🔗 Nibblebot AIOS Integration Bot starting...")
    print(f"   Repository:     {REPO}")
    cat_names = ", ".join(DEFAULT_CATEGORIES.keys())
    print(f"   Categories:     {cat_names}")
    print(f"   Max repos/cat:  {MAX_REPOS}")
    print(f"   Dry run:        {DRY_RUN}")
    print()

    if not TOKEN:
        print(
            "⚠ GITHUB_TOKEN not set — API requests will be unauthenticated "
            "and rate-limited.",
            file=sys.stderr,
        )

    # Step 1: Research repos
    print("━" * 50)
    print("Step 1/5: Researching top AI repositories...\n")
    categorised = research_repos(DEFAULT_CATEGORIES, MAX_REPOS)
    total_repos = sum(len(v) for v in categorised.values())
    print(f"\n  📊 Total repos studied: {total_repos}\n")

    # Step 2: Extract opportunities
    print("━" * 50)
    print("Step 2/5: Extracting integration opportunities...\n")
    opportunities = extract_all_opportunities(categorised)
    print(f"  📊 Raw opportunities found: {len(opportunities)}\n")

    # Step 3: Scan Niblit codebase
    print("━" * 50)
    print("Step 3/5: Scanning Niblit codebase...\n")
    niblit = scan_niblit_codebase()
    print(f"  Python files: {niblit['py_count']}")
    print(f"  Test files:   {niblit['test_count']}")
    print(f"  Total lines:  {niblit['total_lines']:,}\n")

    # Step 4: Gap analysis
    print("━" * 50)
    print("Step 4/5: Performing gap analysis...\n")
    gaps, strengths, present = gap_analysis(niblit, opportunities)
    print(f"  Strengths:          {len(strengths)}")
    print(f"  Partially covered:  {len(present)}")
    print(f"  Gaps (missing):     {len(gaps)}\n")

    # Step 5: Build roadmap & publish
    print("━" * 50)
    print("Step 5/5: Building roadmap & publishing...\n")
    roadmap = build_roadmap(gaps)
    qw = len(roadmap.get("quick_win", []))
    mt = len(roadmap.get("medium_term", []))
    lt = len(roadmap.get("long_term", []))
    print(f"  Roadmap: {qw} quick wins, {mt} medium-term, {lt} long-term")

    body = format_issue_body(
        categorised, niblit, gaps, strengths, present, roadmap,
    )

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN — Issue body preview:")
        print("=" * 60)
        print(body)
        return

    print("\n  📤 Publishing to GitHub...")
    create_or_update_issue(body)
    print("\n✅ AIOS Integration Bot complete!")


if __name__ == "__main__":
    main()
