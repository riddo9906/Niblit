#!/usr/bin/env python3
"""
nibblebots/testgap_agent.py — Phase 15 Background Test-Gap Worker

Ruflo-inspired background worker: detects Python source files that have no
corresponding ``test_*.py`` module and emits AgentObservation events on the
EventBus.  The evolution_planner / testgap tooling then decides whether to
scaffold a test skeleton.

Gap detection logic
-------------------
For every non-test ``.py`` file found under the scanned directories, the agent
checks whether a file named ``test_<stem>.py`` exists anywhere in the repo.
If not, it emits an observation with severity proportional to the module's
public surface (number of public ``def``/``class`` symbols).

Usage (standalone)::

    python nibblebots/testgap_agent.py
    TESTGAP_DRY_RUN=true  python nibblebots/testgap_agent.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

_ws_root = str(Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve())
if _ws_root not in sys.path:
    sys.path.insert(0, _ws_root)

from nibblebots.agent_registry import AgentObservation  # noqa: E402

_AGENT_NAME = "testgap_agent"
_WORKSPACE  = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
_DRY_RUN    = os.environ.get("TESTGAP_DRY_RUN", "").lower() == "true"
_MAX_OBS    = int(os.environ.get("TESTGAP_MAX_OBSERVATIONS", "40"))

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
# Helpers
# ---------------------------------------------------------------------------

def _collect_source_files() -> List[Path]:
    files: List[Path] = []
    for scan_dir in _SCAN_DIRS:
        d = _WORKSPACE / scan_dir
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if not any(part in _SKIP_PARTS for part in p.parts):
                    if not p.name.startswith("test_") and p.name != "conftest.py":
                        files.append(p)
    return files


def _collect_test_stems(workspace: Path) -> Set[str]:
    """Return the set of stems covered by existing test files."""
    stems: Set[str] = set()
    for p in workspace.rglob("test_*.py"):
        if not any(part in _SKIP_PARTS for part in p.parts):
            # test_foo.py → foo
            stems.add(p.stem[len("test_"):])
    return stems


def _public_symbol_count(path: Path) -> int:
    """Count public functions and classes defined at module level."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return 0
    count = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                count += 1
    return count


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def run_testgap(workspace: Optional[Path] = None) -> List[AgentObservation]:
    """Return AgentObservation list for every untested source file."""
    ws = workspace or _WORKSPACE
    test_stems = _collect_test_stems(ws)
    observations: List[AgentObservation] = []

    for path in _collect_source_files():
        stem = path.stem
        if stem in test_stems or stem == "__init__":
            continue

        pub_count = _public_symbol_count(path)
        if pub_count == 0:
            continue  # no testable surface

        # Severity scales with public surface: more exposed functions → higher priority
        severity = min(0.90, 0.40 + pub_count * 0.05)

        rel = str(path.relative_to(_WORKSPACE))
        observations.append(AgentObservation(
            agent_name=_AGENT_NAME,
            obs_type="test_gap",
            file_path=rel,
            count=pub_count,
            severity=round(severity, 3),
            description=(
                f"no test_{ stem }.py found; "
                f"{pub_count} public symbol{'s' if pub_count != 1 else ''} untested"
            ),
        ))

    observations.sort(key=lambda o: (-o.severity, -o.count))
    return observations[:_MAX_OBS]


# ---------------------------------------------------------------------------
# EventBus emission
# ---------------------------------------------------------------------------

def emit_observations(observations: List[AgentObservation]) -> None:
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
    print(f"🧪 Niblit TestGap Agent — workspace: {_WORKSPACE}")
    observations = run_testgap()

    if not observations:
        print("✅ No test gaps found.")
        return 0

    print(f"\n📋 Test gap observations ({len(observations)}):")
    for obs in observations:
        sev_bar = "🔴" if obs.severity >= 0.75 else ("🟡" if obs.severity >= 0.55 else "🟢")
        print(f"  {sev_bar} [{obs.file_path}] — {obs.description}")

    if not _DRY_RUN:
        emit_observations(observations)
        print(f"\n📡 {len(observations)} observation(s) emitted on EventBus.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
