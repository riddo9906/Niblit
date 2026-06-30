from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
for entry in list(sys.path):
    if entry in {str(REPO_ROOT), str(REPO_ROOT.parent)}:
        sys.path.remove(entry)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT.parent) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT.parent))

import shared_import_fixer  # noqa: E402


def test_shared_governance_contract_imports_cleanly() -> None:
    from shared.governance_contract import (
        CANONICAL_EVENTS,
        validate_runtime_contract,
    )
    from shared.governance_contract import runtime_modes
    from shared.governance_contract.memory_contracts import normalize_memory_payload

    assert CANONICAL_EVENTS
    assert runtime_modes.normalize_runtime_mode("safe") == "normal"
    assert callable(normalize_memory_payload)
    assert callable(validate_runtime_contract)
