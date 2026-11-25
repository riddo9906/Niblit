"""Offline adoption lease tests. Never imports a broker transport."""
import concurrent.futures
import copy
import pytest
from modules.mt5_adoption_lease import StagingLeaseRegistry, review_handover


def evidence():
    return {
        "state": "observed", "account_mode": "demo",
        "account_binding_verified": True, "observation_handover_eligible": True,
        "broker_pending_order_count": 0,
        "position_claims": [{"ticket": "591704289", "position_identifier": "591704289",
                             "symbol": "BTCUSDm", "matching_core_order_count": 1,
                             "native_open_deal_receipt_found": True,
                             "account_binding_verified": True, "protected": True}],
    }


def test_matched_evidence_still_needs_explicit_original_owner_release():
    first = review_handover(evidence(), prior_owner_released=False)
    assert not first["review_passed"]
    assert not first["execution_authorized"]
    assert not first["trading_ownership_transferred"]
    assert "Original runtime has not issued an explicit ownership release" in first["blockers"]


def test_review_never_mints_execution_permission_even_after_release():
    result = review_handover(evidence(), prior_owner_released=True)
    assert result["review_passed"]
    assert result["execution_authorized"] is False
    assert result["trading_ownership_transferred"] is False


@pytest.mark.parametrize("mutation", [
    lambda x: x.update(account_mode="live"),
    lambda x: x.update(account_binding_verified=False),
    lambda x: x.update(observation_handover_eligible=False),
    lambda x: x.update(broker_pending_order_count=1),
    lambda x: x["position_claims"][0].update(protected=False),
    lambda x: x["position_claims"][0].update(matching_core_order_count=2),
    lambda x: x["position_claims"][0].update(native_open_deal_receipt_found=False),
    lambda x: x["position_claims"][0].update(ticket="broken"),
    lambda x: x["position_claims"].append(copy.deepcopy(x["position_claims"][0])),
])
def test_incomplete_evidence_cannot_pass(mutation):
    x = evidence()
    mutation(x)
    assert not review_handover(x, prior_owner_released=True)["review_passed"]


def test_unclaimed_then_single_holder_and_exact_release(tmp_path):
    db = tmp_path / "advisory.sqlite3"
    registry = StagingLeaseRegistry(db)
    assert registry.status("demo:btc")["state"] == "unclaimed"
    assert registry.acquire(position_key="demo:btc", holder="r13a",
                            fingerprint="proof1", now=100, ttl=30)
    assert not registry.acquire(position_key="demo:btc", holder="r13b",
                                fingerprint="proof1", now=131, ttl=30)
    assert not registry.release(position_key="demo:btc", holder="r13b", fingerprint="proof1")
    assert not registry.release(position_key="demo:btc", holder="r13a", fingerprint="wrong")
    assert registry.status("demo:btc")["state"] == "held"
    assert registry.release(position_key="demo:btc", holder="r13a", fingerprint="proof1")
    assert registry.status("demo:btc")["state"] == "unclaimed"


def test_concurrent_simulated_workers_cannot_both_acquire(tmp_path):
    db = tmp_path / "race.sqlite3"
    registry = StagingLeaseRegistry(db)
    def attempt(n):
        return registry.acquire(position_key="demo:btc", holder=f"worker{n}",
                                fingerprint="proof1", now=100, ttl=30)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(results) == 1


@pytest.mark.parametrize("ttl", [0, 301, float("nan"), float("inf"), True])
def test_invalid_lease_time_rejected(tmp_path, ttl):
    registry = StagingLeaseRegistry(tmp_path / "lease.sqlite3")
    with pytest.raises(ValueError):
        registry.acquire(position_key="demo:btc", holder="w", fingerprint="p",
                         now=100, ttl=ttl)
