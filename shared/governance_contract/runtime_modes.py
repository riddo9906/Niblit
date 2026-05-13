"""Canonical runtime/governance mode semantics."""

from __future__ import annotations

GOVERNANCE_RUNTIME_MODES = ("normal", "cautious", "survival", "lockdown")
_MODE_ALIASES = {
    "constrained": "cautious",
}


def normalize_runtime_mode(mode: object, default: str = "normal") -> str:
    """Normalize runtime mode to canonical four-mode contract."""
    candidate = str(mode or default).strip().lower()
    candidate = _MODE_ALIASES.get(candidate, candidate)
    if candidate not in GOVERNANCE_RUNTIME_MODES:
        return default
    return candidate


def mode_rank(mode: object) -> int:
    """Return escalating risk rank for canonical mode."""
    normalized = normalize_runtime_mode(mode)
    return {
        "normal": 0,
        "cautious": 1,
        "survival": 2,
        "lockdown": 3,
    }[normalized]


if __name__ == "__main__":
    print('Running runtime_modes.py')
