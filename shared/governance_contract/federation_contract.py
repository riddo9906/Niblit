"""Federation contract/readiness metadata helpers."""

from __future__ import annotations

import time
from typing import Any

from .compatibility_matrix import compatibility_metadata, validate_compatibility


def federation_readiness_payload(
    *,
    node_id: str,
    role: str,
    capabilities: dict[str, Any] | None = None,
    compatibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return canonical federation advertisement payload."""
    compat = compatibility_metadata(compatibility)
    return {
        "timestamp": int(time.time()),
        "node_id": node_id,
        "role": role,
        "federation_ready": True,
        "mode": "passive",
        "capabilities": dict(capabilities or {}),
        "compatibility": compat,
        "compatibility_check": validate_compatibility(compat),
    }


if __name__ == "__main__":
    print('Running federation_contract.py')
