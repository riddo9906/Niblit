"""Mobile gateway contract tests: no live broker, no network, no Core writes."""
from fastapi.testclient import TestClient
import pytest
from modules import mobile_runtime_service as mobile

client=TestClient(mobile.app)
ADMIN={"name":"operator","role":"admin","account_id":"test-account","tier":"community"}
VIEWER={"name":"observer","role":"viewer","account_id":"test-account","tier":"community"}


@pytest.fixture(autouse=True)
def safe_portal(monkeypatch):
    monkeypatch.setattr(mobile,"portal_session",lambda authorization: (
        ADMIN if authorization=="Bearer admin-test" else VIEWER
        if authorization=="Bearer viewer-test" else
        (_ for _ in ()).throw(mobile.HTTPException(401,"Sign in required"))))
    monkeypatch.setenv("NIBLIT_API_PORT","5202")


def scope():
    return {"symbol":"ETHUSDm","minutes":60,"volume_lots":.10,"max_trades":3,
            "max_positions":1,"risk_pct":.25,"risk_cash":25}


def test_mobile_gateway_health_local():
    r=client.get("/mobile/health")
    assert r.status_code==200
    assert r.json()["binding"]=="127.0.0.1"


def test_market_view_requires_auth():
    assert client.get("/mobile/observations").status_code==401


def test_viewer_cannot_review_or_activate():
    for route,body in [
        ("/mobile/trading/readiness",scope()),
        ("/mobile/trading/propose",scope()),
        ("/mobile/trading/activate",{"id":"a"*32,"spec_hash":"b"*32}),
        ("/mobile/trading/stop",{"id":None}),
    ]:
        assert client.post(route,headers={"Authorization":"Bearer viewer-test"},
                           json=body).status_code==403


def test_invalid_scope_rejected_before_core(monkeypatch):
    monkeypatch.setattr(mobile,"core_json",lambda *args,**kwargs: pytest.fail("No Core access expected"))
    for body in ({**scope(),"volume_lots":.11},
                 {**scope(),"minutes":500},
                 {**scope(),"risk_pct":1.0},
                 {**scope(),"max_trades":100},
                 {**scope(),"symbol":"BTCUSD"}):
        r=client.post("/mobile/trading/readiness",headers={"Authorization":"Bearer admin-test"},json=body)
        assert r.status_code==422


def test_review_propose_activate_stop_round_trip_uses_fixed_paths(monkeypatch):
    calls=[]
    def core(path,body=None):
        calls.append((path,body))
        if path.endswith("readiness"):return {"activation_eligible":True,"blockers":[]}
        if path.endswith("propose"):return {"id":"a"*32,"spec_hash":"b"*32,
                                              "state":"pending","spec":{"symbol":"ETHUSDm","seconds":3600}}
        if path.endswith("activate"):return {"id":"a"*32,"state":"active",
                                                "spec":{"symbol":"ETHUSDm"},"expires":12345}
        if path.endswith("stop"):return {"state":"stopped","observation_continues":True}
        raise AssertionError(path)
    monkeypatch.setattr(mobile,"core_json",core)
    headers={"Authorization":"Bearer admin-test"}
    assert client.post("/mobile/trading/readiness",headers=headers,json=scope()).json()["execution_performed"] is False
    proposal=client.post("/mobile/trading/propose",headers=headers,json=scope()).json()
    assert proposal["duration_seconds"]==3600
    assert client.post("/mobile/trading/activate",headers=headers,
                       json={"id":proposal["id"],"spec_hash":proposal["spec_hash"]}).json()["state"]=="active"
    assert client.post("/mobile/trading/stop",headers=headers,json={"id":None}).json()["state"]=="stopped"
    assert calls[0][1]["limits"]["max_volume"]==.10
    assert calls[0][1]["limits"]["max_entries"]==3
    assert calls[0][1]["limits"]["max_positions"]==1
    assert calls[0][1]["limits"]["risk_fraction"]==.0025
    assert calls[0][1]["limits"]["risk_cash"]==25
    assert calls[2][1]["acknowledgement"]=="ACTIVATE_BOUNDED_DEMO_SESSION"
    assert all(x[0] in {"/api/trading/sessions/"+p for p in ("readiness","propose","activate","stop")} for x in calls)


def test_session_response_never_leaks_operator_nonce(monkeypatch):
    monkeypatch.setattr(mobile,"core_json",lambda *args,**kwargs:{
        "operator_nonce":"private_secret","sessions":[{"id":"abc","state":"active",
        "expires":123,"spec":{"symbol":"ETHUSDm","adapter":"mt5","seconds":3600}}],
        "orders":[{"adapter":"mt5","state":"open","symbol":"ETHUSDm","result":"secret"}]})
    data=client.get("/mobile/trading/sessions",headers={"Authorization":"Bearer admin-test"}).json()
    assert "operator_nonce" not in str(data)
    assert "private_secret" not in str(data)
    assert "secret" not in str(data)
    assert data["sessions"][0]["symbol"]=="ETHUSDm"
