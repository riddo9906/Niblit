#!/usr/bin/env python3
"""
nibblebot-deploy  —  Deployment Bot that monitors failed GitHub Actions builds,
diagnoses the root-cause errors, and opens/updates a GitHub Issue with
actionable fix suggestions.

Runs as a scheduled GitHub Action (and on workflow_run completion events).

This bot NEVER commits or pushes code.  It ONLY creates/updates GitHub
Issues labelled ``nibblebot-deploy``.

Usage (local testing):
    GITHUB_TOKEN=ghp_... GITHUB_REPOSITORY=owner/repo python nibblebots/deployment_bot.py

Environment variables:
    GITHUB_TOKEN          — GitHub token with repo, issues, and actions scope
    GITHUB_REPOSITORY     — owner/repo  (set automatically in Actions)
    DEPLOY_BOT_LOOKBACK   — number of hours to look back for failed runs (default: 48)
    DEPLOY_BOT_MAX_RUNS   — max failed runs to inspect (default: 10)
    DEPLOY_BOT_DRY_RUN    — set to "true" to print instead of creating issue
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-Deploy/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
LOOKBACK_HOURS = int(os.environ.get("DEPLOY_BOT_LOOKBACK", "48"))
MAX_RUNS = int(os.environ.get("DEPLOY_BOT_MAX_RUNS", "10"))
DRY_RUN = os.environ.get("DEPLOY_BOT_DRY_RUN", "").lower() == "true"
ISSUE_LABEL = "nibblebot-deploy"
ISSUE_TITLE_PREFIX = "🚨 Nibblebot Deploy Report"

# ---------------------------------------------------------------------------
# Error pattern library
# ---------------------------------------------------------------------------
_ERROR_PATTERNS: List[Tuple[str, str, str, str]] = [
    # (regex, error_type, severity, fix_hint)
    (
        r"SyntaxError:.*",
        "Python SyntaxError",
        "CRITICAL",
        "Check the file for syntax issues. Run `python -m py_compile <file>` locally to confirm.",
    ),
    (
        r"IndentationError:.*",
        "Python IndentationError",
        "CRITICAL",
        "Fix inconsistent indentation. Use `autopep8 --in-place <file>` or your editor's auto-format.",
    ),
    (
        r"(ModuleNotFoundError|ImportError):.*",
        "Import / Module Error",
        "HIGH",
        "A required package is missing. Ensure `requirements.txt` lists it and re-run `pip install -r requirements.txt`.",
    ),
    (
        r"pip.*ERROR.*",
        "pip Installation Error",
        "HIGH",
        "A pip package failed to install. Check network access, version constraints in requirements.txt, and Python version compatibility.",
    ),
    (
        r"(FAILED|ERROR)\s+tests?/",
        "Test Failure",
        "HIGH",
        "One or more tests failed. Run the failing test locally: `pytest <test_file>::<test_name> -v`.",
    ),
    (
        r"AssertionError.*",
        "Assertion Error (test or runtime)",
        "HIGH",
        "An assertion failed. Check the assertion condition and the data it tests.",
    ),
    (
        r"TimeoutError|timed out|timeout",
        "Timeout Error",
        "MEDIUM",
        "A network request or process timed out. Check external service health, increase timeout values, or add retry logic.",
    ),
    (
        r"401 Unauthorized|403 Forbidden|authentication fail",
        "Authentication / Authorization Error",
        "HIGH",
        "A secret or token is missing or expired. Verify GitHub Actions secrets (Settings → Secrets) are still valid.",
    ),
    (
        r"404 Not Found",
        "Resource Not Found (404)",
        "MEDIUM",
        "An API endpoint or file was not found. Verify URLs, paths, and that required files are committed.",
    ),
    (
        r"ConnectionRefusedError|connection refused",
        "Connection Refused",
        "MEDIUM",
        "A service or port was not reachable. Check that required services are running and that ports are open.",
    ),
    (
        r"MemoryError|out of memory|OOM",
        "Out-of-Memory Error",
        "HIGH",
        "The job ran out of memory. Reduce batch sizes, stream data, or upgrade the runner.",
    ),
    (
        r"docker.*error|Dockerfile.*error",
        "Docker Build Error",
        "HIGH",
        "A Docker build step failed. Check the Dockerfile for syntax errors and verify base image availability.",
    ),
    (
        r"fatal:.*git|git.*fatal",
        "Git Error",
        "MEDIUM",
        "A git command failed. Verify the checkout step completed, and that the GITHUB_TOKEN has sufficient permissions.",
    ),
    (
        r"error:.*pylint|pylint.*error",
        "Pylint / Linting Error",
        "LOW",
        "Linting found code style issues. Run `pylint <module>` locally and fix reported problems.",
    ),
    (
        r"(E\d{3}|W\d{3})\s+",
        "Linting Warning/Error Code",
        "LOW",
        "A lint rule was violated. Review the specific error code and fix the flagged line.",
    ),
    (
        r"Process completed with exit code [1-9]",
        "Non-zero Exit Code",
        "HIGH",
        "A step exited with a failure code. Review the preceding output lines for the root cause.",
    ),
]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _gh_request(
    path: str,
    body: Optional[Dict[str, Any]] = None,
    method: str = "GET",
    follow_redirect: bool = False,
    raw: bool = False,
) -> Any:
    """Send a request to the GitHub REST API v3."""
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
        import urllib.request
        opener = urllib.request.build_opener()
        if not follow_redirect:
            opener = urllib.request.build_opener(
                urllib.request.HTTPRedirectHandler()
            )
        with opener.open(req, timeout=30) as resp:  # noqa: S310
            content = resp.read()
            if raw:
                return content.decode("utf-8", errors="replace")
            return json.loads(content)
    except HTTPError as exc:
        if exc.code == 302 and follow_redirect:
            location = exc.headers.get("Location", "")
            if location:
                return _gh_request(location, method="GET", raw=raw)
        print(f"  ⚠ API {method} HTTP {exc.code}: {path}", file=sys.stderr)
        return None
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API {method} error: {path} → {exc}", file=sys.stderr)
        return None


def gh_get(path: str) -> Any:
    """GET JSON from GitHub REST API."""
    return _gh_request(path)


def gh_get_raw(path: str) -> Optional[str]:
    """GET raw text (e.g. log files) from GitHub REST API, following redirects."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in (302, 301):
            location = exc.headers.get("Location", "")
            if location:
                try:
                    with urlopen(location, timeout=30) as r2:  # noqa: S310
                        return r2.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
        print(f"  ⚠ log fetch HTTP {exc.code}: {path}", file=sys.stderr)
        return None
    except (URLError, OSError) as exc:
        print(f"  ⚠ log fetch error: {path} → {exc}", file=sys.stderr)
        return None


def gh_post(path: str, body: Dict[str, Any]) -> Any:
    """POST JSON to GitHub REST API."""
    return _gh_request(path, body, "POST")


def gh_patch(path: str, body: Dict[str, Any]) -> Any:
    """PATCH JSON to GitHub REST API."""
    return _gh_request(path, body, "PATCH")


# ---------------------------------------------------------------------------
# 1. Fetch failed workflow runs
# ---------------------------------------------------------------------------

def fetch_failed_runs() -> List[Dict[str, Any]]:
    """Return recent failed workflow runs within the lookback window."""
    print(f"  🔍 Fetching failed workflow runs (last {LOOKBACK_HOURS}h)…")
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=LOOKBACK_HOURS)
    # GitHub Actions API — list runs with failure status
    data = gh_get(f"/repos/{REPO}/actions/runs?status=failure&per_page=50")
    if not data or "workflow_runs" not in data:
        print("  ⚠ Could not retrieve workflow runs.", file=sys.stderr)
        return []

    runs: List[Dict[str, Any]] = []
    for run in data["workflow_runs"]:
        created_at_str = run.get("created_at", "")
        try:
            created_at = datetime.datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        if created_at < cutoff:
            continue
        runs.append(run)
        if len(runs) >= MAX_RUNS:
            break

    print(f"  ✓ Found {len(runs)} failed run(s) in window")
    return runs


# ---------------------------------------------------------------------------
# 2. Fetch jobs and logs for a run
# ---------------------------------------------------------------------------

def fetch_failed_jobs(run_id: int) -> List[Dict[str, Any]]:
    """Return the failed jobs for a given workflow run."""
    data = gh_get(f"/repos/{REPO}/actions/runs/{run_id}/jobs")
    if not data or "jobs" not in data:
        return []
    return [j for j in data["jobs"] if j.get("conclusion") == "failure"]


def fetch_job_log(job_id: int) -> str:
    """Fetch the plain-text log for a job (follows redirect)."""
    log = gh_get_raw(f"/repos/{REPO}/actions/jobs/{job_id}/logs")
    return (log or "")[:20000]  # cap at 20 KB for analysis


# ---------------------------------------------------------------------------
# 3. Diagnose errors in log text
# ---------------------------------------------------------------------------

_Diagnosis = Dict[str, Any]


def diagnose_log(log_text: str, job_name: str) -> _Diagnosis:
    """Match known error patterns in a job log and return a diagnosis."""
    matches: List[Dict[str, str]] = []
    seen_types: set = set()

    lines = log_text.splitlines()

    for pattern, error_type, severity, fix_hint in _ERROR_PATTERNS:
        compiled = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            m = compiled.search(line)
            if m and error_type not in seen_types:
                seen_types.add(error_type)
                # Grab surrounding context (2 lines before, 2 after)
                idx = lines.index(line)
                context = lines[max(0, idx - 1): idx + 3]
                matches.append({
                    "error_type": error_type,
                    "severity": severity,
                    "fix_hint": fix_hint,
                    "matched_line": line.strip()[:200],
                    "context": "\n".join(l.strip() for l in context)[:400],
                })
                break  # one match per pattern per job

    # Sort: CRITICAL → HIGH → MEDIUM → LOW
    _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    matches.sort(key=lambda x: _sev_order.get(x["severity"], 9))

    return {
        "job_name": job_name,
        "errors_found": len(matches),
        "matches": matches,
        "unrecognised": len(matches) == 0,
        "log_tail": "\n".join(lines[-30:]) if lines else "",
    }


# ---------------------------------------------------------------------------
# 4. Synthesise diagnoses across runs
# ---------------------------------------------------------------------------

def synthesise_diagnoses(
    run_analyses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate per-run diagnoses into a cross-run report."""
    error_freq: Dict[str, int] = {}
    all_fixes: Dict[str, str] = {}

    for run_data in run_analyses:
        for diag in run_data["diagnoses"]:
            for m in diag["matches"]:
                et = m["error_type"]
                error_freq[et] = error_freq.get(et, 0) + 1
                all_fixes[et] = m["fix_hint"]

    sorted_errors = sorted(error_freq.items(), key=lambda x: x[1], reverse=True)

    # Overall severity: if any CRITICAL match exists → CRITICAL, else max of all
    _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    overall_severity = "LOW"
    for run_data in run_analyses:
        for diag in run_data["diagnoses"]:
            for m in diag["matches"]:
                if _sev_order.get(m["severity"], 9) < _sev_order.get(overall_severity, 9):
                    overall_severity = m["severity"]

    return {
        "total_failed_runs": len(run_analyses),
        "overall_severity": overall_severity,
        "top_errors": sorted_errors[:10],
        "fix_map": all_fixes,
    }


# ---------------------------------------------------------------------------
# 5. Build the issue body
# ---------------------------------------------------------------------------

_SEV_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def build_issue_body(
    run_analyses: List[Dict[str, Any]],
    synthesis: Dict[str, Any],
) -> str:
    """Render the full GitHub Issue markdown."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sev = synthesis["overall_severity"]
    sev_emoji = _SEV_EMOJI.get(sev, "⚪")

    lines: List[str] = [
        f"# 🚨 Nibblebot Deployment Bot Report",
        f"",
        f"**Generated:** {now}  ",
        f"**Overall Severity:** {sev_emoji} {sev}  ",
        f"**Failed Runs Inspected:** {synthesis['total_failed_runs']}",
        f"",
        f"> This report is automatically generated by the Nibblebot Deployment Bot.",
        f"> It diagnoses failed GitHub Actions builds and proposes fixes.",
        f"> Review findings and apply the suggested fixes — the bot never modifies code directly.",
        f"",
    ]

    # Top errors summary
    if synthesis["top_errors"]:
        lines += [
            "## 📊 Most Frequent Error Types",
            "",
            "| Error Type | Occurrences | Suggested Fix |",
            "|-----------|-------------|--------------|",
        ]
        for error_type, count in synthesis["top_errors"]:
            fix = synthesis["fix_map"].get(error_type, "_See details below_")[:120]
            lines.append(f"| {error_type} | {count} | {fix} |")
        lines.append("")

    # Per-run details
    lines += ["## 🔬 Run-by-Run Analysis", ""]

    for run_data in run_analyses:
        run = run_data["run"]
        wf_name = run.get("name", "Unknown Workflow")
        run_id = run.get("id", "?")
        run_url = run.get("html_url", "")
        branch = run.get("head_branch", "?")
        sha = run.get("head_sha", "")[:7]
        created_at = run.get("created_at", "")[:16].replace("T", " ")

        lines += [
            f"### ❌ [{wf_name} #{run_id}]({run_url})",
            f"",
            f"**Branch:** `{branch}` | **Commit:** `{sha}` | **Started:** {created_at}",
            f"",
        ]

        if not run_data["diagnoses"]:
            lines += ["_No failed jobs found or log unavailable._", ""]
            continue

        for diag in run_data["diagnoses"]:
            job_name = diag["job_name"]
            lines += [f"#### 🔧 Job: `{job_name}`", ""]

            if diag["unrecognised"]:
                lines += [
                    "⚠️ **No recognised error pattern matched.**",
                    "",
                    "<details><summary>Last 30 log lines</summary>",
                    "",
                    "```",
                    diag["log_tail"][:2000],
                    "```",
                    "",
                    "</details>",
                    "",
                ]
                continue

            for m in diag["matches"]:
                sev_e = _SEV_EMOJI.get(m["severity"], "⚪")
                lines += [
                    f"**{sev_e} {m['severity']} — {m['error_type']}**",
                    f"",
                    f"- **Matched line:** `{m['matched_line']}`",
                    f"- **Fix:** {m['fix_hint']}",
                    f"",
                    "<details><summary>Context</summary>",
                    "",
                    "```",
                    m["context"],
                    "```",
                    "",
                    "</details>",
                    "",
                ]

    # Footer
    lines += [
        "---",
        "",
        "## 🛠️ General Deployment Health Checklist",
        "",
        "- [ ] All required secrets are valid (Settings → Secrets and variables → Actions)",
        "- [ ] `requirements.txt` is up to date (`pip freeze > requirements.txt`)",
        "- [ ] Python syntax passes locally (`python -m py_compile app.py server.py`)",
        "- [ ] Tests pass locally (`pytest -q`)",
        "- [ ] No hardcoded credentials in code (`git grep -i 'password\\|secret\\|token'`)",
        "- [ ] Dockerfile builds locally (`docker build .`)",
        "",
        "_Nibblebot Deployment Bot — part of the [Niblit](https://github.com/riddo9906/Niblit) project_",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. Create or update the GitHub Issue
# ---------------------------------------------------------------------------

def find_open_issue() -> Optional[int]:
    """Return the number of an existing open nibblebot-deploy issue, or None."""
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
    """Create a new issue or update the body of an existing one."""
    existing = find_open_issue()
    if existing:
        print(f"  ✏️  Updating existing issue #{existing}…")
        gh_patch(f"/repos/{REPO}/issues/{existing}", {"body": body})
        print(f"  ✓ Issue #{existing} updated.")
    else:
        print(f"  🆕 Creating new issue…")
        result = gh_post(
            f"/repos/{REPO}/issues",
            {"title": title, "body": body, "labels": [ISSUE_LABEL]},
        )
        if result:
            print(f"  ✓ Issue #{result.get('number')} created: {result.get('html_url')}")
        else:
            print("  ⚠ Failed to create issue.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("🚀 Nibblebot Deployment Bot starting…")
    print(f"   Repo       : {REPO}")
    print(f"   Lookback   : {LOOKBACK_HOURS} hours")
    print(f"   Max runs   : {MAX_RUNS}")
    print(f"   Dry run    : {DRY_RUN}")
    print()

    if not TOKEN:
        print("⚠ GITHUB_TOKEN not set — API calls will be unauthenticated and rate-limited.", file=sys.stderr)

    # Step 1 — find failed runs
    failed_runs = fetch_failed_runs()
    if not failed_runs:
        print("✅ No failed workflow runs found in the lookback window. Nothing to report.")
        return

    # Step 2 — analyse each run
    run_analyses: List[Dict[str, Any]] = []
    for run in failed_runs:
        run_id = run["id"]
        run_name = run.get("name", str(run_id))
        print(f"\n  🔬 Analysing run: {run_name} (#{run_id})")

        failed_jobs = fetch_failed_jobs(run_id)
        diagnoses: List[_Diagnosis] = []

        for job in failed_jobs[:5]:  # cap at 5 jobs per run
            job_id = job["id"]
            job_name = job.get("name", str(job_id))
            print(f"    📋 Fetching log for job: {job_name}")
            log_text = fetch_job_log(job_id)
            diag = diagnose_log(log_text, job_name)
            diagnoses.append(diag)
            print(
                f"    ✓ {diag['errors_found']} error pattern(s) found"
                + (" (unrecognised)" if diag["unrecognised"] else "")
            )
            time.sleep(0.5)

        run_analyses.append({"run": run, "diagnoses": diagnoses})
        time.sleep(0.5)

    # Step 3 — synthesise
    print("\n  🧠 Synthesising findings…")
    synthesis = synthesise_diagnoses(run_analyses)

    # Step 4 — build issue
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    title = f"{ISSUE_TITLE_PREFIX} — {now_str} ({synthesis['overall_severity']})"
    body = build_issue_body(run_analyses, synthesis)

    if DRY_RUN:
        print("\n" + "=" * 70)
        print(f"DRY RUN — Issue title: {title}")
        print("=" * 70)
        print(body)
        print("=" * 70)
    else:
        print(f"\n  📝 Publishing issue: {title}")
        create_or_update_issue(title, body)

    print("\n✅ Nibblebot Deployment Bot finished.")


if __name__ == "__main__":
    main()
