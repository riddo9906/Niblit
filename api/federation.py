"""Federation API helpers (Niblit-side equivalent of federation stub layer)."""

from __future__ import annotations

from typing import Any

from modules.federation_foundation import get_federation_foundation


def federation_status() -> dict[str, Any]:
    return get_federation_foundation().status()


def federation_sync_placeholder() -> dict[str, Any]:
    return get_federation_foundation().sync_placeholders()


if __name__ == "__main__":
    print('Running federation.py')
