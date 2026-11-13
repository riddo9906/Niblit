import copy
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from modules.remote_broker_gateway import GatewayProfile, RemoteBrokerGateway
from modules.trading_session_api import register_trading_routes
from modules.trading_session_selftest import fixture

ACCOUNT = dict(broker="XM fixture", login="100000001", server="XMGlobal-MT5 12",
               currency="USD", environment="live", terminal_id="a"*20)

@pytest.fixture
def remote(tmp_path):
    token=tmp_path/"observation.token"
    token.write_text("a"*64)
    state=dict(status=200,calls=0,auth=None,payload={
        "schema_version":"0.2","gateway_version":"0.2.0","execution_enabled":False,
        "effective_config":{"account":ACCOUNT},"broker_fresh":True,
        "reported_at":time.time(),"observation_age_seconds":0,
        "operations":dict(open=False,modify=False,close=False,cancel=False,switch_account=False),
        "account_observation":{"account":ACCOUNT,"observed_at":time.time(),"positions":[],"orders":[]},
        "breaker":"ENTRY_SUSPENDED","history":{"history_orders":[],"history_deals":[]}})
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["calls"]+=1
            state["auth"]=self.headers.get("Authorization")
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(json.dumps(state["payload"]).encode())
        def log_message(self,*args): pass
    with HTTPServer(("127.0.0.1",0),Handler) as server:
        thread=threading.Thread(target=server.serve_forever)
        thread.start()
        now=[10]
        client=RemoteBrokerGateway(GatewayProfile(
            f"http://127.0.0.1:{server.server_port}",token,ACCOUNT,.3),clock=lambda:now[0])
        try: yield client,state,now
        finally:
            server.shutdown()
            thread.join()

def test_real_http_identity_and_coalescing(remote):
    client,state,now=remote
    first=client.status()
    assert first["broker_verified"] and not first["execution_enabled"]
    assert state["auth"]=="Bearer "+"a"*64
    for _ in range(10): assert client.status()["request_id"]==first["request_id"]
    assert state["calls"]==1

@pytest.mark.parametrize("case",["account","server","schema","authority","stale","nan","auth","redirect","offline"])
def test_fail_closed_and_recovery(remote,case):
    client,state,now=remote
    original=copy.deepcopy(state["payload"])
    if case=="account":state["payload"]["effective_config"]["account"]={**ACCOUNT,"login":"99"}
    elif case=="server":state["payload"]["effective_config"]["account"]={**ACCOUNT,"server":"wrong"}
    elif case=="schema":state["payload"]["schema_version"]="0.1"
    elif case=="authority":state["payload"]["operations"]["close"]=True
    elif case=="stale":state["payload"]["reported_at"]=time.time()-60
    elif case=="nan":state["payload"]["reported_at"]=float("nan")
    else:
        state["status"]={"auth":401,"redirect":302,"offline":503}[case]
        if case=="offline":state["payload"]["broker_fresh"]=False
    result=client.status()
    assert not result["broker_verified"]
    assert result["observation"] is None
    state["payload"]=original
    state["status"]=200
    now[0]+=31
    assert client.status()["broker_verified"]

def test_core_status_without_local_broker(tmp_path,remote):
    client,state,now=remote
    f=fixture(tmp_path)
    f.service.remote_gateway=client
    def forbidden(*args,**kwargs): raise AssertionError("Local MT5 fallback")
    f.bridge.snapshot=forbidden
    f.service.status()
    app=FastAPI()
    register_trading_routes(app,lambda:f.service)
    with TestClient(app) as http:
        response=http.get("/api/trading/sessions")
        assert response.status_code==200
        assert response.json()["remote_gateway"]["broker_verified"]
        assert response.json()["real_money_enabled"] is False
        assert http.get("/api/trading/sessions",headers={"host":"bad.example"}).status_code==403
    with pytest.raises(PermissionError):f.service.observe("mt5","EURUSD",threaded=False)
    with pytest.raises(PermissionError):f.service.propose("mt5","EURUSD")
    assert not f.api.sent

def test_public_transport_rejected(tmp_path):
    path=tmp_path/"remote.json"
    path.write_text(json.dumps(dict(schema_version="0.2",endpoint="http://example.com:18765",
                                   token_file=str(tmp_path/"secret"),account=ACCOUNT)))
    with pytest.raises(ValueError):GatewayProfile.load(path)


def test_actual_gateway_protocol_to_core_route(tmp_path):
    import sys
    folder=Path(__file__).resolve().parents[1]/"deploy/vps-gateway"
    sys.path.insert(0,str(folder))
    try:
        from gateway import GatewayServer, Handler, Monitor
        from broker import observe
        from test_gateway import BrokerDouble
    finally:
        sys.path.remove(str(folder))
    terminal=tmp_path/"terminal64.exe"
    terminal.touch()
    broker=BrokerDouble(terminal)
    broker.account.login=100000001
    broker.account.server="XMGlobal-MT5 12"
    binding=observe(broker,terminal)
    monitor=Monitor(dict(account=binding,terminal=str(terminal),port=18765,
                        limits=dict(max_positions=0,min_equity="1",max_margin_fraction="0")),
                    tmp_path/"gateway.sqlite3")
    monitor.reconcile(observe(broker,terminal,binding))
    token=tmp_path/"read.token"
    token.write_text("a"*64)
    with GatewayServer(("127.0.0.1",0),Handler) as server:
        server.monitor=monitor
        server.authorization=b"Bearer "+b"a"*64
        server.stop_authorization=b"Bearer "+b"b"*64
        worker=threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            client=RemoteBrokerGateway(GatewayProfile(
                f"http://127.0.0.1:{server.server_port}",token,binding))
            f=fixture(tmp_path/"core")
            f.service.remote_gateway=client
            app=FastAPI()
            register_trading_routes(app,lambda:f.service)
            with TestClient(app) as http:
                result=http.get("/api/trading/sessions").json()["remote_gateway"]
                assert result["broker_verified"]
                assert result["gateway_version"] in ("0.2.1","0.2.2","0.3.0","0.3.1","0.3.2","0.3.3","0.4.0")
                assert result["observation"]["history_checkpoint"]>0
                assert result["execution_enabled"] is False
        finally:
            server.shutdown()
            worker.join()


def test_market_desk_serves_remote_panel_on_existing_entrypoint(tmp_path):
    from modules.trading_desk import Desk, create_app
    app=create_app(Desk(tmp_path),core_hosted=True)
    with TestClient(app) as client:
        page=client.get("/")
        assert page.status_code==200
        assert 'id="remote-gateway-status"' in page.text
        script=client.get("/sessions.js")
        assert script.status_code==200
        assert "data.remote_gateway" in script.text
        assert "CORE UNAVAILABLE" in script.text
        assert "REAL-MONEY EXECUTION DISABLED" in script.text

def test_remote_profile_blocks_preexisting_local_proposal_and_worker(tmp_path,remote):
    client,_,_=remote
    f=fixture(tmp_path)
    proposal=f.service.propose("mt5","EURUSD",60)
    f.service.remote_gateway=client
    def forbidden(*args,**kwargs):raise AssertionError("Local broker touched")
    f.bridge.snapshot=forbidden
    with pytest.raises(PermissionError):
        f.service.activate(proposal["id"],proposal["spec_hash"],threaded=False)
    f.bot.step()
    assert "blocked" in f.bot.error
    assert not f.api.sent

def test_remote_transitions_share_canonical_outbox_and_deduplicate(tmp_path,remote):
    client,state,now=remote
    f=fixture(tmp_path)
    f.service.remote_gateway=client
    first=f.service.remote_status()
    second=f.service.remote_status()
    assert first["canonical_journal"]["recorded"]
    assert first["canonical_journal"]==second["canonical_journal"]
    with f.gateway.db() as db:
        assert db.execute("SELECT count(*) FROM trading_events WHERE kind='remote_broker_state'").fetchone()[0]==1
        receipt=db.execute("SELECT memory_receipt FROM trading_events WHERE kind='remote_broker_state'").fetchone()[0]
        assert db.execute("SELECT count(*) FROM ingestion_outbox WHERE id=?",(receipt,)).fetchone()[0]==1
    state["status"]=503
    state["payload"]["broker_fresh"]=False
    now[0]+=31
    failed=f.service.remote_status()
    assert not failed["broker_verified"]
    assert failed["canonical_journal"]["recorded"]
    state["status"]=200
    state["payload"]["broker_fresh"]=True
    now[0]+=31
    recovered=f.service.remote_status()
    assert recovered["broker_verified"]
    assert recovered["canonical_journal"]["event_id"]!=first["canonical_journal"]["event_id"]
    with f.gateway.db() as db:
        assert db.execute("SELECT count(*) FROM trading_events WHERE kind='remote_broker_state'").fetchone()[0]==3
    assert not f.api.sent

def test_remote_observer_is_single_and_shutdown_is_controlled(tmp_path,remote):
    client,_,_=remote
    f=fixture(tmp_path)
    f.service.remote_gateway=client
    f.service.start_remote_observer()
    worker=f.service.remote_worker
    f.service.start_remote_observer()
    assert f.service.remote_worker is worker
    f.service.shutdown()
    assert not worker.is_alive()
    assert not f.api.sent


def test_verified_observation_survives_latched_execution_breaker(remote):
    client,state,now=remote
    state["status"]=503
    state["payload"]["breaker"]="RECONCILIATION_REQUIRED"
    result=client.status()
    assert result["gateway_reachable"] and result["broker_verified"]
    assert result["observation_enabled"] and not result["execution_enabled"]
    assert result["breaker"]=="RECONCILIATION_REQUIRED"

def test_reported_config_is_not_observed_account_proof(remote):
    client,state,now=remote
    state["payload"]["account_observation"]={"account":{**ACCOUNT,"login":"99"}}
    result=client.status()
    assert not result["broker_verified"]
    assert result["observation"] is None

def test_canonical_history_survives_client_restart_during_outage(tmp_path,remote):
    from modules.trading_session_selftest import fixture
    from modules.remote_broker_gateway import RemoteBrokerGateway
    client,state,now=remote
    state["payload"]["account_observation"].update(balance=21.03,equity="21.03",margin=0,free_margin=21.03)
    f=fixture(tmp_path);f.service.remote_gateway=client
    assert f.service.remote_status()["canonical_journal"]["recorded"]
    replacement=RemoteBrokerGateway(client.profile,clock=lambda:now[0])
    f.service.remote_gateway=replacement
    state["status"]=503;state["payload"]["broker_fresh"]=False
    result=f.service.remote_status()
    assert not result["broker_verified"]
    assert result["broker_observation"]["balances"]["equity"] is None
    assert result["broker_observation"]["last_verified"]["equity"]=="21.03"
    assert result["broker_observation"]["last_verified"]["breaker"]=="ENTRY_SUSPENDED"
    assert not f.api.sent

def test_local_port_conflict_never_receives_gateway_token(remote):
    from dataclasses import replace
    import os
    if os.name!="nt":pytest.skip("Windows ownership contract")
    client,state,_=remote
    class ForbiddenToken:
        def read_text(self,**kwargs):
            raise AssertionError("Credential read before SSH ownership verified")
    client.profile=replace(client.profile,token_file=ForbiddenToken(),ssh_peer={
        "host":"192.0.2.10","user":"Administrator","key_file":"C:/fixture/key","known_hosts_file":"C:/fixture/hosts"})
    result=client.status()
    assert not result["gateway_reachable"] and not result["broker_verified"]
    assert state["calls"]==0 and state["auth"] is None

@pytest.mark.parametrize("mutation",["host","executable","strict","key","forward","duplicate"])
def test_ssh_arguments_are_bound_to_transport(tmp_path,mutation):
    import os
    from modules.ssh_forward_identity import validate_ssh_arguments
    exe=str(Path(os.environ.get("WINDIR","C:/Windows"))/"System32/OpenSSH/ssh.exe")
    peer={"host":"192.0.2.10","user":"Administrator","key_file":str(tmp_path/"key"),"known_hosts_file":str(tmp_path/"hosts")}
    args=[exe,"-N","-T","-i",peer["key_file"],"-o","UserKnownHostsFile="+peer["known_hosts_file"],
          "-o","StrictHostKeyChecking=yes","-o","BatchMode=yes","-o","ExitOnForwardFailure=yes",
          "-L","127.0.0.1:18765:127.0.0.1:18765","Administrator@192.0.2.10"]
    assert validate_ssh_arguments(exe,args,peer,18765)
    if mutation=="host":args[-1]="Administrator@other.invalid"
    elif mutation=="executable":exe=str(tmp_path/"ssh.exe")
    elif mutation=="strict":args[args.index("StrictHostKeyChecking=yes")]="StrictHostKeyChecking=no"
    elif mutation=="key":args[4]=str(tmp_path/"other-key")
    elif mutation=="forward":args[-2]="0.0.0.0:18765:127.0.0.1:18765"
    else:args[1:1]=["-o","StrictHostKeyChecking=no"]
    with pytest.raises(PermissionError):validate_ssh_arguments(exe,args,peer,18765)
