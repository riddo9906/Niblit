#!/usr/bin/env python3
"""
nibblebot-improve  —  Nibblebot that studies top GitHub repos, compares
patterns with the Niblit codebase, and opens a GitHub Issue listing
actionable improvement suggestions.

Runs as a scheduled GitHub Action (like Dependabot).

Usage (local testing):
    GITHUB_TOKEN=ghp_... python nibblebots/improvement_bot.py

Environment variables:
    GITHUB_TOKEN          — GitHub token with repo + issues scope
    GITHUB_REPOSITORY     — owner/repo  (set automatically in Actions)
    NIBBLEBOT_TOPICS      — comma-separated topics to study (default: ai-agent,llm-framework)
    NIBBLEBOT_MAX_REPOS   — max reference repos per topic (default: 5)
    NIBBLEBOT_DRY_RUN     — set to "true" to print the issue instead of creating it
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-Improve/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
TOPICS = [
    t.strip()
    for t in os.environ.get("NIBBLEBOT_TOPICS", "ai-agent,llm-framework").split(",")
    if t.strip()
]
MAX_REPOS = int(os.environ.get("NIBBLEBOT_MAX_REPOS", "5"))
DRY_RUN = os.environ.get("NIBBLEBOT_DRY_RUN", "").lower() == "true"
ISSUE_LABEL = "nibblebot"
ISSUE_TITLE_PREFIX = "🤖 Nibblebot Improvement Report"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def gh_get(path: str) -> Any:
    """GET from GitHub REST API v3."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API error: {path} → {exc}", file=sys.stderr)
        return None


def gh_post(path: str, body: Dict[str, Any]) -> Any:
    """POST to GitHub REST API v3."""
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
        with urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API POST error: {path} → {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 1. Study reference repos
# ---------------------------------------------------------------------------

def fetch_trending_repos(topic: str, max_repos: int = MAX_REPOS) -> List[Dict[str, Any]]:
    """Search GitHub for top-starred repos matching a topic."""
    print(f"  📡 Searching repos for topic: {topic}")
    query = f"topic:{topic}" if " " not in topic else topic
    data = gh_get(f"/search/repositories?q={query}&sort=stars&per_page={max_repos}")
    if not data or "items" not in data:
        return []
    repos: List[Dict[str, Any]] = []
    for item in data["items"][:max_repos]:
        full_name = item.get("full_name", "")
        if not full_name:
            continue
        # Fetch top-level file list
        tree = gh_get(f"/repos/{full_name}/contents")
        top_files = [f.get("name", "") for f in (tree or [])[:50]] if isinstance(tree, list) else []
        # Fetch README
        readme_text = ""
        readme_data = gh_get(f"/repos/{full_name}/readme")
        if readme_data and "content" in readme_data:
            try:
                readme_text = base64.b64decode(readme_data["content"]).decode("utf-8", errors="replace")[:2000]
            except Exception:
                pass
        repos.append({
            "full_name": full_name,
            "stars": item.get("stargazers_count", 0),
            "description": (item.get("description") or "")[:200],
            "language": item.get("language", ""),
            "topics": (item.get("topics") or [])[:10],
            "top_files": top_files,
            "readme_snippet": readme_text[:1200],
            "url": item.get("html_url", ""),
        })
        time.sleep(0.6)  # polite rate-limit
    return repos


# ---------------------------------------------------------------------------
# 2. Study own repo
# ---------------------------------------------------------------------------

def study_own_repo() -> Dict[str, Any]:
    """Introspect the local Niblit codebase (runs inside the checkout)."""
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    if not root.is_dir():
        root = Path(".").resolve()

    py_files: List[str] = []
    test_files: List[str] = []
    doc_files: List[str] = []
    config_files: List[str] = []
    swift_files: List[str] = []
    total_py_lines = 0

    for p in root.rglob("*"):
        if any(part.startswith(".") for part in p.parts):
            continue
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if "__pycache__" in rel or "node_modules" in rel or ".build" in rel:
            continue
        if p.suffix == ".py":
            py_files.append(rel)
            try:
                total_py_lines += sum(1 for _ in p.open())
            except OSError:
                pass
            if p.name.startswith("test_"):
                test_files.append(rel)
        elif p.suffix == ".swift":
            swift_files.append(rel)
        elif p.suffix == ".md":
            doc_files.append(rel)
        elif p.name in (
            ".env.example", "fly.toml", "vercel.json", "Dockerfile",
            "requirements.txt", "requirements-dev.txt", "Cargo.toml",
            "Package.swift", "package.json", "tsconfig.json", "pyproject.toml",
            "Makefile", ".pre-commit-config.yaml",
        ):
            config_files.append(rel)

    top_level = sorted(f.name for f in root.iterdir() if not f.name.startswith("."))

    return {
        "py_files": len(py_files),
        "swift_files": len(swift_files),
        "test_files": len(test_files),
        "doc_files": len(doc_files),
        "total_py_lines": total_py_lines,
        "top_level": top_level[:40],
        "config_files": config_files,
        "has_ci": (root / ".github" / "workflows").is_dir(),
        "has_tests": len(test_files) > 0,
        "has_docs": len(doc_files) >= 3,
        "has_docker": (root / "Dockerfile").is_file(),
        "has_typing": any(root.rglob("py.typed")),
        "has_pyproject": (root / "pyproject.toml").is_file(),
        "has_makefile": (root / "Makefile").is_file(),
        "has_precommit": (root / ".pre-commit-config.yaml").is_file(),
        "has_contributing": (root / "CONTRIBUTING.md").is_file(),
        "has_changelog": (root / "CHANGELOG.md").is_file(),
    }


# ---------------------------------------------------------------------------
# 3. Compare & generate suggestions
# ---------------------------------------------------------------------------

def compare_and_suggest(
    own: Dict[str, Any],
    refs: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Generate improvement suggestions by comparing own repo with references."""
    suggestions: List[Dict[str, str]] = []

    # ── Test coverage ratio ───────────────────────────────────────────────
    py = own.get("py_files", 0)
    tests = own.get("test_files", 0)
    if py > 0 and tests / py < 0.25:
        suggestions.append({
            "title": "📊 Increase test coverage",
            "priority": "HIGH",
            "category": "Testing",
            "detail": (
                f"Only **{tests}** test files for **{py}** source files "
                f"(**{tests/py*100:.0f}%** ratio). "
                "Top AI repos maintain ≥25 % test-to-source ratio. "
                "Consider adding unit tests for critical modules like "
                "`niblit_memory`, `niblit_router`, and `niblit_brain`."
            ),
        })

    # ── Type hints / py.typed ─────────────────────────────────────────────
    if not own.get("has_typing"):
        suggestions.append({
            "title": "🏷️ Add `py.typed` marker & type annotations",
            "priority": "MEDIUM",
            "category": "Code Quality",
            "detail": (
                "A `py.typed` marker file signals PEP 561 compliance. "
                "Combined with type hints it enables IDE autocompletion "
                "and static analysis with mypy / pyright."
            ),
        })

    # ── pyproject.toml ────────────────────────────────────────────────────
    if not own.get("has_pyproject"):
        suggestions.append({
            "title": "📦 Add `pyproject.toml`",
            "priority": "MEDIUM",
            "category": "Packaging",
            "detail": (
                "Modern Python projects use `pyproject.toml` (PEP 621) "
                "instead of `setup.py` / `setup.cfg`. It consolidates "
                "build config, tool settings (black, ruff, mypy), and metadata."
            ),
        })

    # ── Makefile ──────────────────────────────────────────────────────────
    if not own.get("has_makefile"):
        suggestions.append({
            "title": "🔧 Add a `Makefile` for common tasks",
            "priority": "LOW",
            "category": "Developer Experience",
            "detail": (
                "A `Makefile` with targets like `make test`, `make lint`, "
                "`make build` lowers the barrier for contributors and "
                "standardises the development workflow."
            ),
        })

    # ── Pre-commit hooks ──────────────────────────────────────────────────
    if not own.get("has_precommit"):
        suggestions.append({
            "title": "🪝 Add `.pre-commit-config.yaml`",
            "priority": "MEDIUM",
            "category": "Code Quality",
            "detail": (
                "Pre-commit hooks catch lint / formatting issues before "
                "they reach CI. Popular hooks: ruff, black, mypy, "
                "trailing-whitespace, end-of-file-fixer."
            ),
        })

    # ── CONTRIBUTING.md ───────────────────────────────────────────────────
    if not own.get("has_contributing"):
        suggestions.append({
            "title": "🤝 Add `CONTRIBUTING.md`",
            "priority": "LOW",
            "category": "Community",
            "detail": (
                "A contribution guide helps new contributors understand "
                "how to set up the dev environment, run tests, and "
                "submit pull requests."
            ),
        })

    # ── CHANGELOG.md ──────────────────────────────────────────────────────
    if not own.get("has_changelog"):
        suggestions.append({
            "title": "📋 Add `CHANGELOG.md`",
            "priority": "LOW",
            "category": "Community",
            "detail": (
                "A changelog (following Keep a Changelog format) helps "
                "users track what changed between releases."
            ),
        })

    # ── Large file detection ──────────────────────────────────────────────
    total_lines = own.get("total_py_lines", 0)
    file_count = max(own.get("py_files", 1), 1)
    avg = total_lines / file_count
    if avg > 400:
        suggestions.append({
            "title": "✂️ Refactor large Python files",
            "priority": "MEDIUM",
            "category": "Architecture",
            "detail": (
                f"Average Python file is **~{avg:.0f} lines**. "
                "Industry best practice targets <300 lines per module. "
                "Consider splitting the largest files (e.g. `niblit_core.py`, "
                "`niblit_router.py`) into focused sub-modules."
            ),
        })

    # ── Patterns from reference repos ─────────────────────────────────────
    ref_files_union: set = set()
    ref_topics_union: set = set()
    for r in refs:
        ref_files_union.update(f.lower() for f in r.get("top_files", []))
        ref_topics_union.update(t.lower() for t in r.get("topics", []))

    # Common files seen in reference repos but missing locally
    own_lower = {f.lower() for f in own.get("top_level", [])}
    good_files = {"license", "makefile", "pyproject.toml", ".pre-commit-config.yaml"}
    missing = (good_files & ref_files_union) - own_lower
    if missing:
        suggestions.append({
            "title": f"📁 Add project files: {', '.join(sorted(missing))}",
            "priority": "LOW",
            "category": "Project Health",
            "detail": (
                "These files are common in top reference repos and improve "
                "discoverability, contributor experience, and tooling support."
            ),
        })

    # Highlight interesting reference repos
    for r in refs[:3]:
        readme = r.get("readme_snippet", "").lower()
        patterns_found: List[str] = []
        if "openapi" in readme or "swagger" in readme:
            patterns_found.append("OpenAPI/Swagger docs")
        if "docker compose" in readme or "docker-compose" in readme:
            patterns_found.append("Docker Compose setup")
        if "benchmark" in readme:
            patterns_found.append("benchmark suite")
        if "plugin" in readme:
            patterns_found.append("plugin architecture")

        if patterns_found:
            suggestions.append({
                "title": f"💡 Pattern from {r['full_name']} (★{r['stars']})",
                "priority": "LOW",
                "category": "Inspiration",
                "detail": (
                    f"[{r['full_name']}]({r['url']}) uses: "
                    f"{', '.join(patterns_found)}. "
                    f"Description: {r['description'][:100]}"
                ),
            })

    return suggestions


# ---------------------------------------------------------------------------
# 4. Format as GitHub Issue body
# ---------------------------------------------------------------------------

def format_issue_body(
    suggestions: List[Dict[str, str]],
    refs: List[Dict[str, Any]],
    topics: List[str],
) -> str:
    """Render the suggestions as a Markdown GitHub issue body."""
    lines: List[str] = []
    lines.append("## 🤖 Nibblebot Improvement Report\n")
    lines.append(
        "This issue was automatically created by **Nibblebot** — "
        "the Niblit improvement bot that studies top GitHub repositories "
        "and compares them with this project.\n"
    )
    lines.append(f"**Topics studied:** {', '.join(topics)}")
    lines.append(f"**Reference repos analyzed:** {len(refs)}\n")

    if not suggestions:
        lines.append("✅ No new suggestions — the project looks great!\n")
        return "\n".join(lines)

    # Group by priority
    for priority in ("HIGH", "MEDIUM", "LOW"):
        group = [s for s in suggestions if s.get("priority") == priority]
        if not group:
            continue
        emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}[priority]
        lines.append(f"\n### {emoji} {priority} Priority\n")
        for s in group:
            cat = s.get("category", "General")
            lines.append(f"#### {s.get('title', 'Untitled')}")
            lines.append(f"**Category:** {cat}\n")
            lines.append(s.get("detail", "") + "\n")

    # Reference repos section
    if refs:
        lines.append("\n---\n### 📚 Reference Repos Studied\n")
        lines.append("| Repo | Stars | Language | Description |")
        lines.append("|------|------:|----------|-------------|")
        for r in refs:
            desc = (r.get("description") or "")[:80]
            lines.append(
                f"| [{r['full_name']}]({r['url']}) "
                f"| {r.get('stars', 0):,} "
                f"| {r.get('language', '?')} "
                f"| {desc} |"
            )

    lines.append("\n---")
    lines.append(
        "<sub>🤖 This report was generated by "
        "[Nibblebot](https://github.com/riddo9906/Niblit/tree/main/nibblebots) "
        "— the Niblit improvement bot. "
        "To adjust scanning topics, edit `NIBBLEBOT_TOPICS` in the workflow.</sub>"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. Create (or update) the GitHub Issue
# ---------------------------------------------------------------------------

def ensure_label_exists() -> None:
    """Create the 'nibblebot' label if it doesn't exist."""
    existing = gh_get(f"/repos/{REPO}/labels/{ISSUE_LABEL}")
    if existing and "name" in existing:
        return
    gh_post(f"/repos/{REPO}/labels", {
        "name": ISSUE_LABEL,
        "color": "7057ff",
        "description": "Automated improvement suggestion from Nibblebot",
    })


def find_open_issue() -> Optional[int]:
    """Find an existing open Nibblebot issue to update."""
    data = gh_get(
        f"/repos/{REPO}/issues?labels={ISSUE_LABEL}&state=open&per_page=5"
    )
    if not data or not isinstance(data, list):
        return None
    for issue in data:
        if (issue.get("title") or "").startswith(ISSUE_TITLE_PREFIX):
            return issue["number"]
    return None


def create_or_update_issue(body: str) -> None:
    """Create a new issue or update the existing one."""
    ensure_label_exists()
    existing = find_open_issue()

    import datetime
    date_str = datetime.date.today().isoformat()
    title = f"{ISSUE_TITLE_PREFIX} — {date_str}"

    if existing:
        print(f"  📝 Updating existing issue #{existing}")
        # PATCH to update body
        url = f"{GITHUB_API}/repos/{REPO}/issues/{existing}"
        data = json.dumps({"body": body, "title": title}).encode()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
            "Content-Type": "application/json",
        }
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        req = Request(url, data=data, headers=headers, method="PATCH")
        try:
            with urlopen(req, timeout=20) as resp:  # noqa: S310
                result = json.loads(resp.read().decode())
                print(f"  ✅ Updated issue #{existing}: {result.get('html_url', '')}")
        except (URLError, OSError) as exc:
            print(f"  ⚠ Failed to update issue: {exc}", file=sys.stderr)
    else:
        print("  📝 Creating new issue")
        result = gh_post(f"/repos/{REPO}/issues", {
            "title": title,
            "body": body,
            "labels": [ISSUE_LABEL],
        })
        if result and "html_url" in result:
            print(f"  ✅ Created issue: {result['html_url']}")
        else:
            print("  ⚠ Failed to create issue", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the Nibblebot improvement scan."""
    print("🤖 Nibblebot Improvement Bot starting...")
    print(f"   Repository: {REPO}")
    print(f"   Topics:     {', '.join(TOPICS)}")
    print(f"   Max repos:  {MAX_REPOS}")
    print(f"   Dry run:    {DRY_RUN}")
    print()

    if not TOKEN:
        print("⚠ GITHUB_TOKEN not set — API requests will be rate-limited.", file=sys.stderr)

    # 1. Study reference repos
    all_refs: List[Dict[str, Any]] = []
    for topic in TOPICS:
        refs = fetch_trending_repos(topic, MAX_REPOS)
        all_refs.extend(refs)
        print(f"  ✓ Found {len(refs)} repos for '{topic}'")
        time.sleep(1)

    # Deduplicate by full_name
    seen: set = set()
    unique_refs: List[Dict[str, Any]] = []
    for r in all_refs:
        if r["full_name"] not in seen:
            seen.add(r["full_name"])
            unique_refs.append(r)

    print(f"\n📊 Total unique reference repos: {len(unique_refs)}")

    # 2. Study own repo
    print("\n🔍 Studying own repo...")
    own = study_own_repo()
    print(f"  Python files: {own['py_files']}, Tests: {own['test_files']}, "
          f"Docs: {own['doc_files']}, Lines: {own['total_py_lines']:,}")

    # 3. Compare & suggest
    print("\n🧠 Comparing patterns...")
    suggestions = compare_and_suggest(own, unique_refs)
    print(f"  Generated {len(suggestions)} suggestion(s)")

    # 4. Format issue
    body = format_issue_body(suggestions, unique_refs, TOPICS)

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN — Issue body:")
        print("=" * 60)
        print(body)
        return

    # 5. Create/update issue
    print("\n📤 Publishing to GitHub...")
    create_or_update_issue(body)
    print("\n✅ Nibblebot scan complete!")


if __name__ == "__main__":
    main()
