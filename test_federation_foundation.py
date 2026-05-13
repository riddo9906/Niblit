from __future__ import annotations

from modules.federation_foundation import get_federation_foundation


def test_federation_readiness_payload_contains_compatibility() -> None:
    foundation = get_federation_foundation()
    readiness = foundation.readiness()
    assert readiness["federation_ready"] is True
    assert "compatibility" in readiness
    assert readiness["compatibility_check"]["compatible"] is True


def test_federation_sync_placeholder_advances_count() -> None:
    foundation = get_federation_foundation()
    start = foundation.status()["sync_count"]
    _ = foundation.sync_placeholders()
    after = foundation.status()["sync_count"]
    assert after >= start + 1


if __name__ == "__main__":
    print('Running test_federation_foundation.py')
