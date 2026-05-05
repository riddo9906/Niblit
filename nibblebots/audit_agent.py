#!/usr/bin/env python3
"""
nibblebots/audit_agent.py — Phase 15 Background Audit Worker

Ruflo-inspired background worker: scans for security and exception-handling
issues and emits AgentObservation events on the EventBus rather than writing
fixes directly.  The evolution_planner then decides which observations to act
on based on the current goal and risk budget.

Detected issue types
--------------------
bare_except      — bare ``except:`` clause (catches SystemExit/KeyboardInterrupt)
bare_except_pass — ``except Exception: pass`` (silences errors with no log)
security_issue   — eval/exec usage, os.system(), hardcoded secrets patterns

Usage (standalone)::

    python nibblebots/audit_agent.py
    AUDIT_DRY_RUN=true  python nibblebots/audit_agent.py
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

# Ensure repo root is on sys.path when invoked directly (same pattern as
# autonomous_evolution_agent.py)
_ws_root = str(Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve())
if _ws_root not in sys.path:
    sys.path.insert(0, _ws_root)

from nibblebots.agent_registry import AgentObservation, AGENT_REGISTRY  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_AGENT_NAME  = "audit_agent"
_WORKSPACE   = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
_DRY_RUN     = os.environ.get("AUDIT_DRY_RUN", "").lower() == "true"
_MAX_OBS     = int(os.environ.get("AUDIT_MAX_OBSERVATIONS", "50"))

# Patterns that flag a security concern in source code
_SECURITY_PATTERNS: List[re.Pattern] = [
    re.compile(r'\beval\s*\('),
    re.compile(r'\bexec\s*\('),
    re.compile(r'\bos\.system\s*\('),
    re.compile(r'\bsubprocess\.call\s*\(.*shell\s*=\s*True'),
    re.compile(r'\bpassword\s*=\s*["\'][^"\']{3,}["\']'),
    re.compile(r'\bsecret\s*=\s*["\'][^"\']{3,}["\']'),
    re.compile(r'\bapi_key\s*=\s*["\'][^"\']{3,}["\']'),
]

_BARE_EXCEPT_RE      = re.compile(r'(?m)^\s*except\s*:\s*$')
_BARE_EXCEPT_PASS_RE = re.compile(r'(?m)^\s*except\s+Exception\s*:\s*\n\s*pass\s*$')

# Directories to audit (mirrors autonomous_evolution_agent scan dirs + root files)
_SCAN_DIRS = (
    "modules", "niblit_agents", "niblit_memory",
    "nibblebots", "niblit_tools", "agents", "core", "kernel", "boot", "api",
)
_SKIP_PARTS = frozenset({
    "__pycache__", ".git", ".github", "node_modules",
    ".build", "build", "dist", ".tox", "venv", ".venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------

def _collect_files() -> List[Path]:
    files: List[Path] = []
    for scan_dir in _SCAN_DIRS:
        d = _WORKSPACE / scan_dir
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if not any(part in _SKIP_PARTS for part in p.parts):
                    files.append(p)
    # Also scan root-level .py files
    for p in sorted(_WORKSPACE.glob("*.py")):
        files.append(p)
    return files


def _scan_bare_except(content: str) -> int:
    return len(_BARE_EXCEPT_RE.findall(content))


def _scan_bare_except_pass(content: str) -> int:
    return len(_BARE_EXCEPT_PASS_RE.findall(content))


def _scan_security(content: str) -> int:
    count = 0
    for pat in _SECURITY_PATTERNS:
        count += len(pat.findall(content))
    return count


# ---------------------------------------------------------------------------
# Observation builder
# ---------------------------------------------------------------------------

def _make_obs(
    obs_type: str,
    file_path: Path,
    count: int,
    severity: float,
    description: str,
) -> AgentObservation:
    rel = str(file_path.relative_to(_WORKSPACE))
    return AgentObservation(
        agent_name=_AGENT_NAME,
        obs_type=obs_type,
        file_path=rel,
        count=count,
        severity=severity,
        description=description,
    )


# ---------------------------------------------------------------------------
# Main scan logic
# ---------------------------------------------------------------------------

def run_audit(workspace: Optional[Path] = None) -> List[AgentObservation]:
    """Scan the workspace and return all audit observations.

    Parameters
    ----------
    workspace : override the default workspace root (used in tests)

    Returns a list of AgentObservation objects sorted by severity desc.
    """
    ws = workspace or _WORKSPACE
    files = _collect_files()
    observations: List[AgentObservation] = []

    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Skip string-literal-only bare excepts (e.g. test fixtures)
        # by checking if the match is inside a multiline string
        raw_bare = _scan_bare_except(content)
        if raw_bare:
            try:
                tree = ast.parse(content)
                bare_count = sum(
                    1
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ExceptHandler) and node.type is None
                )
            except SyntaxError:
                bare_count = raw_bare
            if bare_count:
                observations.append(_make_obs(
                    obs_type="bare_except",
                    file_path=path,
                    count=bare_count,
                    severity=0.75,
                    description=(
                        f"bare except: clause catches SystemExit/KeyboardInterrupt "
                        f"({bare_count} instance{'s' if bare_count > 1 else ''})"
                    ),
                ))

        # bare except pass
        bep = _scan_bare_except_pass(content)
        if bep:
            observations.append(_make_obs(
                obs_type="bare_except_pass",
                file_path=path,
                count=bep,
                severity=0.55,
                description=f"silent except-pass swallows errors ({bep} instance{'s' if bep > 1 else ''})",
            ))

        # security patterns (skip test files — false-positive heavy)
        if "test_" not in path.name and path.name != "conftest.py":
            sec = _scan_security(content)
            if sec:
                observations.append(_make_obs(
                    obs_type="security_issue",
                    file_path=path,
                    count=sec,
                    severity=0.85,
                    description=f"potential security issue: eval/exec/os.system/hardcoded secret ({sec} match{'es' if sec > 1 else ''})",
                ))

    observations.sort(key=lambda o: (-o.severity, -o.count))
    return observations[:_MAX_OBS]


# ---------------------------------------------------------------------------
# EventBus emission (best-effort)
# ---------------------------------------------------------------------------

def emit_observations(observations: List[AgentObservation]) -> None:
    """Publish each observation as EVENT_AGENT_OBSERVATION on the EventBus."""
    if not observations:
        return
    try:
        from modules.event_bus import get_event_bus, NiblitEvent, EVENT_AGENT_OBSERVATION  # noqa: PLC0415
        bus = get_event_bus()
        for obs in observations:
            bus.publish(NiblitEvent(
                type=EVENT_AGENT_OBSERVATION,
                source=_AGENT_NAME,
                payload=obs.to_dict(),
            ))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"🔍 Niblit Audit Agent — workspace: {_WORKSPACE}")
    observations = run_audit()

    if not observations:
        print("✅ No audit issues found.")
        return 0

    print(f"\n📋 Audit observations ({len(observations)}):")
    for obs in observations:
        sev_bar = "🔴" if obs.severity >= 0.75 else ("🟡" if obs.severity >= 0.55 else "🟢")
        print(f"  {sev_bar} [{obs.obs_type}] {obs.file_path} — {obs.description}")

    if not _DRY_RUN:
        emit_observations(observations)
        print(f"\n📡 {len(observations)} observation(s) emitted on EventBus.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
