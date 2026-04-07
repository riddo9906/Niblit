#!/usr/bin/env python3
"""
nibblebot-aios  —  Research bot that scans GitHub for AI operating system,
hardware-adaptive AI, and self-improving system repos to gather ideas for
building "Niblit AI OS Complete".

This bot NEVER commits or pushes code.  It ONLY creates/updates GitHub
Issues with its findings, labelled ``nibblebot-aios``.

Phases: Research → Analysis → Synthesis → Report (GitHub Issue).

Usage (local)::

    GITHUB_TOKEN=ghp_... python nibblebots/aios_research_bot.py

Environment variables:
    GITHUB_TOKEN        GitHub token with repo + issues scope.
    GITHUB_REPOSITORY   owner/repo (auto-set in Actions).
    AIOS_TOPICS         Override topics (comma-separated).
    AIOS_MAX_REPOS      Max repos per topic (default: 8).
    AIOS_DRY_RUN        "true" to print instead of creating issue.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

# -- Config --
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-AIOS/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
DEFAULT_TOPICS = (
    "ai-os,autonomous-system,intelligent-os,"
    "edge-ai,tinyml,embedded-ai,hardware-ai,"
    "self-improving,autonomous-agent,evolving-ai,"
    "cross-platform-ai,portable-ai,universal-ai"
)
TOPICS = [
    t.strip()
    for t in os.environ.get("AIOS_TOPICS", DEFAULT_TOPICS).split(",")
    if t.strip()
]
MAX_REPOS = int(os.environ.get("AIOS_MAX_REPOS", "8"))
DRY_RUN = os.environ.get("AIOS_DRY_RUN", "").lower() == "true"
ISSUE_LABEL = "nibblebot-aios"
ISSUE_TITLE_PREFIX = "\U0001f9e0 Nibblebot AIOS Research Report"

# Topic → human-readable category
TOPIC_CATEGORIES: Dict[str, str] = {}
for _cat, _keys in [
    ("AI Operating Systems", ["ai-os", "autonomous-system", "intelligent-os"]),
    ("Hardware-Adaptive AI", ["edge-ai", "tinyml", "embedded-ai", "hardware-ai"]),
    ("Self-Improving Systems", ["self-improving", "autonomous-agent", "evolving-ai"]),
    ("Multi-Platform AI", ["cross-platform-ai", "portable-ai", "universal-ai"]),
]:
    for _k in _keys:
        TOPIC_CATEGORIES[_k] = _cat

# -- GitHub API helpers  (mirrors improvement_bot.py) --

def _gh_request(path: str, body: Optional[Dict[str, Any]] = None,
                method: str = "GET") -> Any:
    """Send a request to the GitHub REST API v3."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  \u26a0 API {method} error: {path} \u2192 {exc}", file=sys.stderr)
        return None

def gh_get(path: str) -> Any:
    """GET from GitHub REST API."""
    return _gh_request(path)

def gh_post(path: str, body: Dict[str, Any]) -> Any:
    """POST to GitHub REST API."""
    return _gh_request(path, body, "POST")

def gh_patch(path: str, body: Dict[str, Any]) -> Any:
    """PATCH to GitHub REST API."""
    return _gh_request(path, body, "PATCH")

# -- 1. Research Phase — search GitHub for repos per topic --

def search_repos_for_topic(topic: str, max_repos: int = MAX_REPOS) -> List[Dict[str, Any]]:
    """Search GitHub for top-starred repos matching *topic*."""
    print(f"  \U0001f4e1 Searching repos for topic: {topic}")
    query = f"topic:{topic}" if " " not in topic else topic
    data = gh_get(f"/search/repositories?q={query}&sort=stars&per_page={max_repos}")
    if not data or "items" not in data:
        return []

    repos: List[Dict[str, Any]] = []
    for item in data["items"][:max_repos]:
        full_name = item.get("full_name", "")
        if not full_name:
            continue

        tree = gh_get(f"/repos/{full_name}/contents")
        top_files = (
            [f.get("name", "") for f in (tree or [])[:50]]
            if isinstance(tree, list) else []
        )

        readme_text = ""
        readme_data = gh_get(f"/repos/{full_name}/readme")
        if readme_data and "content" in readme_data:
            try:
                readme_text = base64.b64decode(
                    readme_data["content"]
                ).decode("utf-8", errors="replace")[:4000]
            except Exception:
                pass

        repos.append({
            "full_name": full_name,
            "stars": item.get("stargazers_count", 0),
            "description": (item.get("description") or "")[:200],
            "language": item.get("language", ""),
            "topics": (item.get("topics") or [])[:15],
            "top_files": top_files,
            "readme_snippet": readme_text,
            "url": item.get("html_url", ""),
            "source_topic": topic,
        })
        time.sleep(0.6)  # polite rate-limit
    return repos

def collect_all_repos(topics: List[str], max_repos: int) -> List[Dict[str, Any]]:
    """Fetch and deduplicate repos across all topics."""
    all_repos: List[Dict[str, Any]] = []
    for topic in topics:
        found = search_repos_for_topic(topic, max_repos)
        all_repos.extend(found)
        print(f"  \u2713 Found {len(found)} repos for '{topic}'")
        time.sleep(1)

    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for r in all_repos:
        if r["full_name"] not in seen:
            seen.add(r["full_name"])
            unique.append(r)
    return unique

# -- 2. Analysis Phase — extract patterns from each repo --

# Keyword sets for pattern detection in READMEs / file trees.
_ARCH_KW = [
    "kernel", "microkernel", "scheduler", "runtime", "daemon", "message bus",
    "event loop", "pipeline", "orchestrat", "plugin", "modular",
    "layered architecture", "service mesh",
]
_HW_KW = [
    "hardware abstraction", "hal", "device driver", "gpio", "cuda", "opencl",
    "vulkan", "metal", "tpu", "npu", "arm", "risc-v", "riscv", "fpga",
    "edge device", "quantiz", "model compression", "onnx", "tflite",
]
_SI_KW = [
    "self-improv", "self-heal", "auto-tune", "automl",
    "reinforcement learning", "meta-learn", "evolv", "genetic algorithm",
    "neural architecture search", "continual learning", "lifelong learning",
    "online learning", "feedback loop", "self-optimiz",
]
_MOD_KW = [
    "plugin system", "extension", "add-on", "addon", "module loader",
    "registry", "hook", "middleware", "component", "subsystem",
    "microservice", "package manager",
]

def _match_keywords(text: str, keywords: List[str]) -> List[str]:
    """Return keywords found in *text* (case-insensitive)."""
    lower = text.lower()
    return [kw for kw in keywords if kw in lower]

def analyse_repo(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Extract AIOS-relevant patterns from a single repo."""
    readme = repo.get("readme_snippet", "")
    files_str = " ".join(repo.get("top_files", []))
    combined = f"{readme} {files_str} {repo.get('description', '')}"

    return {
        "full_name": repo["full_name"],
        "stars": repo["stars"],
        "url": repo["url"],
        "language": repo.get("language", ""),
        "description": repo.get("description", ""),
        "category": TOPIC_CATEGORIES.get(repo.get("source_topic", ""), "Other"),
        "architecture_patterns": _match_keywords(combined, _ARCH_KW),
        "hardware_abstractions": _match_keywords(combined, _HW_KW),
        "self_improvement": _match_keywords(combined, _SI_KW),
        "module_systems": _match_keywords(combined, _MOD_KW),
        "top_files": repo.get("top_files", [])[:20],
        "topics": repo.get("topics", []),
    }

def analyse_all(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyse every repo and return enriched records."""
    return [analyse_repo(r) for r in repos]

# -- 3. Synthesis Phase — aggregate findings into a report --

def synthesise(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate individual analyses into cross-cutting insights."""
    buckets: Dict[str, Dict[str, int]] = {
        "arch": {}, "hw": {}, "si": {}, "mod": {},
    }
    field_map = [
        ("architecture_patterns", "arch"), ("hardware_abstractions", "hw"),
        ("self_improvement", "si"), ("module_systems", "mod"),
    ]
    for a in analyses:
        for field, bucket in field_map:
            for kw in a[field]:
                buckets[bucket][kw] = buckets[bucket].get(kw, 0) + 1

    def _top(d: Dict[str, int], n: int = 8) -> List[Tuple[str, int]]:
        return sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]

    deep_study: List[Dict[str, Any]] = []
    for a in analyses:
        score = sum(len(a[f]) for f, _ in field_map)
        if score >= 3:
            deep_study.append({**a, "relevance_score": score})
    deep_study.sort(key=lambda x: x["relevance_score"], reverse=True)

    lang_counts: Dict[str, int] = {}
    for a in analyses:
        lang = a.get("language") or "Unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    return {
        "top_architecture": _top(buckets["arch"]),
        "top_hardware": _top(buckets["hw"]),
        "top_self_improvement": _top(buckets["si"]),
        "top_module_systems": _top(buckets["mod"]),
        "deep_study_repos": deep_study[:10],
        "language_distribution": _top(lang_counts, 10),
        "total_repos": len(analyses),
    }

# -- 4. Report Phase — format as GitHub Issue body --

def _fmt_kw_table(items: List[Tuple[str, int]], heading: str) -> List[str]:
    """Render a keyword frequency table as Markdown."""
    lines: List[str] = []
    if not items:
        lines.append(f"_No {heading.lower()} patterns detected._\n")
        return lines
    lines.append(f"| {heading} | Repos |")
    lines.append("|---|---:|")
    for kw, count in items:
        lines.append(f"| `{kw}` | {count} |")
    lines.append("")
    return lines

def format_issue_body(
    synthesis: Dict[str, Any], analyses: List[Dict[str, Any]],
    topics: List[str],
) -> str:
    """Render the full research report as a Markdown issue body."""
    lines: List[str] = []  # accumulates Markdown output
    total = synthesis["total_repos"]
    date_str = datetime.date.today().isoformat()

    lines.append("## \U0001f9e0 Nibblebot AIOS Research Report\n")
    lines.append(
        "This issue was automatically created by **Nibblebot AIOS** \u2014 "
        "the research bot that scans GitHub for AI OS, hardware-adaptive AI, "
        "and self-improving system projects to gather ideas for "
        "**Niblit AI OS Complete**.\n"
    )
    lines.append(f"**Date:** {date_str}")
    lines.append(f"**Topics searched:** `{'`, `'.join(topics)}`")
    lines.append(f"**Unique repos analysed:** {total}\n")
    if total == 0:
        lines.append("_No repositories found for the given topics._\n")
        return "\n".join(lines)

    # Sections: pattern tables
    for emoji, title, key, desc in [
        ("\U0001f3d7\ufe0f", "Architecture Patterns", "top_architecture",
         "Common architectural patterns for structuring an AI OS."),
        ("\U0001f527", "Hardware Abstraction Strategies", "top_hardware",
         "Hardware targets, model compression, and device driver keywords."),
        ("\U0001f504", "Self-Improvement Mechanisms", "top_self_improvement",
         "Autonomous learning, self-healing, and adaptation approaches."),
        ("\U0001f9e9", "Module & Integration Systems", "top_module_systems",
         "Extensible components, plugins, and sub-system patterns."),
    ]:
        lines.append(f"---\n### {emoji} {title}\n")
        lines.append(f"{desc}\n")
        lines.extend(_fmt_kw_table(synthesis[key], title.split()[0]))

    # Language distribution
    lang = synthesis.get("language_distribution", [])
    if lang:
        lines.append("### \U0001f4ca Language Distribution\n")
        lines.append("| Language | Repos |\n|---|---:|")
        for name, count in lang:
            lines.append(f"| {name} | {count} |")
        lines.append("")

    # Comparison table
    lines.append("---\n### \U0001f4da Reference Repo Comparison\n")
    lines.append("| Repo | \u2b50 | Language | Category | Arch | HW | Self-Imp | Modules |")
    lines.append("|---|---:|---|---|---:|---:|---:|---:|")
    for a in sorted(analyses, key=lambda x: x["stars"], reverse=True)[:20]:
        lines.append(
            f"| [{a['full_name']}]({a['url']}) "
            f"| {a['stars']:,} | {a.get('language', '?')} "
            f"| {a.get('category', '')} "
            f"| {len(a['architecture_patterns'])} "
            f"| {len(a['hardware_abstractions'])} "
            f"| {len(a['self_improvement'])} "
            f"| {len(a['module_systems'])} |"
        )
    lines.append("")

    # Deep-study repos
    deep = synthesis.get("deep_study_repos", [])
    if deep:
        lines.append("### \U0001f50d Repos to Study Further\n")
        lines.append("Highest-scoring repos across multiple AIOS categories.\n")
        for r in deep[:8]:
            score = r.get("relevance_score", 0)
            desc = (r.get("description") or "")[:120]
            lines.append(f"#### [{r['full_name']}]({r['url']}) "
                     f"\u2b50 {r['stars']:,} \u00b7 relevance {score}\n")
            lines.append(f"> {desc}\n")
            lines.append(f"- **Arch:** {', '.join(r['architecture_patterns'][:4]) or '\u2014'}")
            lines.append(f"- **HW:** {', '.join(r['hardware_abstractions'][:4]) or '\u2014'}")
            lines.append(f"- **Self-imp:** {', '.join(r['self_improvement'][:4]) or '\u2014'}\n")

    # Recommendations
    lines.append("---\n### \u2705 Actionable Recommendations for Niblit AIOS Complete\n")
    _add_recommendations(lines, synthesis)

    lines.append("\n---")
    lines.append(
        "<sub>\U0001f9e0 Generated by "
        "[Nibblebot AIOS](https://github.com/riddo9906/Niblit/tree/main/nibblebots) "
        "\u2014 set `AIOS_TOPICS` in the workflow to adjust.</sub>"
    )
    return "\n".join(lines)

def _add_recommendations(lines: List[str], synthesis: Dict[str, Any]) -> None:
    """Append concrete recommendations based on synthesis data."""
    recs: List[str] = []
    arch = dict(synthesis.get("top_architecture", []))
    hw = dict(synthesis.get("top_hardware", []))
    si = dict(synthesis.get("top_self_improvement", []))
    mod = dict(synthesis.get("top_module_systems", []))

    if arch.get("plugin") or arch.get("modular"):
        recs.append(
            "**Adopt a plugin architecture** \u2014 expose a stable plugin "
            "API so new capabilities can be added without modifying core.")
    if arch.get("pipeline") or arch.get("orchestrat"):
        recs.append(
            "**Use a pipeline / orchestration layer** \u2014 structure work "
            "as composable stages with a lightweight DAG scheduler.")
    if hw.get("onnx") or hw.get("tflite"):
        recs.append(
            "**Standardise on ONNX / TFLite** \u2014 these formats dominate "
            "edge-AI repos and enable CPU/GPU/NPU/MCU portability.")
    if hw.get("quantiz"):
        recs.append(
            "**Integrate model quantisation** \u2014 INT8/INT4 support lets "
            "Niblit scale from cloud to Raspberry Pi.")
    if any(k in hw for k in ("arm", "risc-v", "riscv")):
        recs.append(
            "**Target ARM and RISC-V** \u2014 ensure the core can "
            "cross-compile and run on these architectures.")
    if si.get("feedback loop") or si.get("self-optimiz"):
        recs.append(
            "**Build a feedback loop** \u2014 add a telemetry \u2192 "
            "evaluation \u2192 update cycle for self-tuning.")
    if si.get("self-heal"):
        recs.append(
            "**Strengthen self-healing** \u2014 extend `niblit_guard.py` "
            "with watchdog timers and auto-restart on failure.")
    if mod.get("registry") or mod.get("module loader"):
        recs.append(
            "**Create a module registry** \u2014 central catalogue with "
            "version tracking and dependency resolution.")
    recs.append(
        "**Recommended stack** \u2014 Python orchestration, Rust/C for HAL, "
        "ONNX Runtime for inference, SQLite for state, gRPC/ZeroMQ for IPC.")
    for i, rec in enumerate(recs, 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

# -- 5. Create / update the GitHub Issue --

def ensure_label_exists() -> None:
    """Create the ``nibblebot-aios`` label if it doesn't already exist."""
    existing = gh_get(f"/repos/{REPO}/labels/{ISSUE_LABEL}")
    if existing and "name" in existing:
        return
    gh_post(f"/repos/{REPO}/labels", {
        "name": ISSUE_LABEL,
        "color": "1d76db",
        "description": "Automated AIOS research report from Nibblebot",
    })

def find_open_issue() -> Optional[int]:
    """Find an existing open AIOS research issue to update."""
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

    date_str = datetime.date.today().isoformat()
    title = f"{ISSUE_TITLE_PREFIX} \u2014 {date_str}"

    if existing:
        print(f"  \U0001f4dd Updating existing issue #{existing}")
        result = gh_patch(f"/repos/{REPO}/issues/{existing}", {
            "body": body,
            "title": title,
        })
        if result and "html_url" in result:
            print(f"  \u2705 Updated issue #{existing}: {result['html_url']}")
        else:
            print("  \u26a0 Failed to update issue", file=sys.stderr)
    else:
        print("  \U0001f4dd Creating new issue")
        result = gh_post(f"/repos/{REPO}/issues", {
            "title": title,
            "body": body,
            "labels": [ISSUE_LABEL],
        })
        if result and "html_url" in result:
            print(f"  \u2705 Created issue: {result['html_url']}")
        else:
            print("  \u26a0 Failed to create issue", file=sys.stderr)

# -- Main --

def main() -> None:
    """Run the Nibblebot AIOS research scan."""
    print("\U0001f9e0 Nibblebot AIOS Research Bot starting...")
    print(f"   Repo: {REPO}  Topics: {len(TOPICS)}  "
          f"Max: {MAX_REPOS}  Dry: {DRY_RUN}\n")
    if not TOKEN:
        print("\u26a0 GITHUB_TOKEN not set \u2014 rate-limited.", file=sys.stderr)

    # Phase 1 — Research
    print("\U0001f50d Phase 1: Research")
    repos = collect_all_repos(TOPICS, MAX_REPOS)
    print(f"  Total unique repos: {len(repos)}\n")

    # Phase 2 — Analysis
    print("\U0001f9ea Phase 2: Analysis")
    analyses = analyse_all(repos)
    matched = sum(1 for a in analyses if any(
        a[f] for f in ("architecture_patterns", "hardware_abstractions",
                        "self_improvement", "module_systems")))
    print(f"  AIOS-relevant: {matched}/{len(analyses)}\n")

    # Phase 3 — Synthesis
    print("\U0001f9e0 Phase 3: Synthesis")
    synthesis = synthesise(analyses)
    print(f"  Arch: {len(synthesis['top_architecture'])}  "
          f"HW: {len(synthesis['top_hardware'])}  "
          f"SI: {len(synthesis['top_self_improvement'])}  "
          f"Deep: {len(synthesis.get('deep_study_repos', []))}\n")

    # Phase 4 — Report
    print("\U0001f4cb Phase 4: Report")
    body = format_issue_body(synthesis, analyses, TOPICS)
    if DRY_RUN:
        print("\n" + "=" * 60 + "\nDRY RUN:\n" + "=" * 60)
        print(body)
        return

    print("\n\U0001f4e4 Publishing to GitHub...")
    create_or_update_issue(body)
    print("\n\u2705 Nibblebot AIOS research scan complete!")

if __name__ == "__main__":
    main()
