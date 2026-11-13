import copy,time
import pytest
from modules.broker_observation import normalize,number,VERSION

def state():
    return dict(gateway_reachable=True,broker_verified=True,breaker="RECONCILIATION_REQUIRED",
      observation={"account_observation":{"account":{"login":"100000001"},"observed_at":1000,
      "balance":21.03,"equity":"21.03","margin":0,"free_margin":21.03,"positions":[],"orders":[]},
      "gateway_id":"a"*64,"history":{"history_orders":[],"history_deals":[{"type":2}]},
      "history_checkpoint":1000,"reconciliation":{"status":"REVIEW_REQUIRED","complete":False}})

def test_fresh_inventory_does_not_clear_execution_breaker():
    r=normalize(state(),now=1001,received_at=1001)
    assert r["schema_version"]==VERSION and r["inventory_fresh"]
    assert r["broker_authenticated"] and r["execution_breaker_latched"]
    assert not r["execution_permitted"] and r["balances"]["margin"]==0

@pytest.mark.parametrize("bad",[None,False,True,"NaN",float("inf"),"unknown"])
def test_unknown_money_is_not_zero(bad):
    s=state();s["observation"]["account_observation"]["equity"]=bad
    r=normalize(s,now=1001)
    assert r["balances"]["equity"] is None
    assert "account_fields_unknown" in r["warnings"]

def test_outage_retains_only_historical_labelled_values():
    s=state();old=copy.deepcopy(s["observation"]["account_observation"])
    s.update(broker_verified=False,gateway_reachable=False,observation=None)
    r=normalize(s,now=1050,last_verified=old)
    assert r["freshness"]=="stale" and r["balances"]["equity"] is None
    assert r["last_verified"]["equity"]=="21.03"
    assert r["positions"] is None and r["pending_orders"] is None
    assert r["broker_authenticated"] is None

def test_source_timestamp_and_inventory_required():
    s=state();snap=s["observation"]["account_observation"]
    snap["observed_at"]=None
    assert normalize(s,now=1001)["freshness"]=="unavailable"
    snap["observed_at"]=1000;snap["positions"]=None
    assert not normalize(s,now=1001)["inventory_fresh"]

def test_account_history_is_never_implied_complete():
    r=normalize(state(),now=1001)
    assert r["reconciliation"]["complete"] is False
    assert "reconciliation_incomplete" in r["execution_disabled_reasons"]


def test_hosted_remote_desk_rejects_desktop_fallback(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from modules.trading_desk import Desk,create_app
    monkeypatch.setenv("NIBLIT_VPS_GATEWAY_PROFILE","explicit-remote-profile")
    app=create_app(Desk(tmp_path),core_hosted=True)
    with TestClient(app) as client:
        page=client.get("/")
        assert 'data-remote-observation="true"' in page.text
        assert client.get("/api/mt5/snapshot").status_code==403
        assert client.get("/api/charts/snapshot?environment=mt5").status_code==403
        assert client.get("/remote-observation.js").status_code==200
