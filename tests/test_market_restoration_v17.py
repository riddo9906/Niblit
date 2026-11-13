import pytest
from modules.trading_desk import Desk
from modules.memory_laboratory.gateway import MemoryGateway
from modules.memory_laboratory.setup import Config
from test_memory_laboratory_gateway import Backend

CONFIG = dict(timeframe="5m",exchange="binance",trading_mode="futures")

def feed(monkeypatch, bars):
    monkeypatch.setattr("modules.trading_desk.time.time",lambda: 3000)
    calls=[]
    def fetch(self,pair,**kwargs):
        calls.append((pair,kwargs)); return bars
    monkeypatch.setattr("modules.market_data_providers.MarketDataProviders.ccxt_bars",fetch)
    return calls

def test_stopped_engine_uses_existing_provider_without_mutation(monkeypatch):
    calls=feed(monkeypatch,[[2100000,10,12,9,11,1],[2400000,11,13,10,12,2],[3000000,12,14,11,13,1]])
    d=Desk.__new__(Desk); paths=[]
    def api(path):
        paths.append(path); return {"data":[],"columns":[]}
    d.api=api
    result=d.market("BTC/USDT:USDT",CONFIG)
    assert result["fresh"] and len(result["candles"])==2
    assert result["signal"]=="WAIT" and not result["native_signals_available"]
    assert result["quality"]["contiguous"]
    assert calls[0][0]=="BTC/USDT:USDT" and calls[0][1]["exchange"]=="binanceusdm"
    assert all(p.startswith("pair_candles?") for p in paths)
    d.market("BTC/USDT:USDT",CONFIG)
    assert len(calls)==1

@pytest.mark.parametrize("bars",[[],"offline",[[2400000,11,10,9,12,2]],[[2400000,11,13,10,12,-1]],[[2400000,11,13,10,float("nan"),2]],[[2100000,10,12,9,11,1],[2100000,10,12,9,11,1]],[[1800000,10,12,9,11,1],[2400000,11,13,10,12,2]]])
def test_invalid_public_feed_abstains(monkeypatch,bars):
    feed(monkeypatch,bars)
    result=Desk.__new__(Desk).public_market("BTC/USDT:USDT",CONFIG)
    assert not result["fresh"] and result["signal"]=="STALE"

def test_stale_public_feed_and_instrument_mismatch(monkeypatch):
    calls=feed(monkeypatch,[[300000,10,12,9,11,1]])
    d=Desk.__new__(Desk)
    assert not d.public_market("BTC/USDT:USDT",CONFIG)["fresh"]
    assert not d.public_market("BTC/USDT:USDT",dict(CONFIG,trading_mode="spot"))["fresh"]
    assert len(calls)==1

def authority(monkeypatch):
    class Grants:
        perms={"memory.ingest.desktop":True,"memory.read.desktop":True}
        def check(self,key): return self.perms.get(key,False)
    grants=Grants()
    monkeypatch.setattr("modules.core_tool_runtime._permission_manager",lambda:grants)
    return grants

def test_partition_restart_projection_isolation_and_revocation(tmp_path,monkeypatch):
    grants=authority(monkeypatch); backend=Backend(); ledger=tmp_path/"ledger.sqlite3"
    g=MemoryGateway(Config(url="http://127.0.0.1:6333"),ledger,setup=backend)
    identity=["binance","BTC/USDT:USDT","5m","dry-run","account-a"]
    scope=g.register_market_partition("desktop",identity,"six-rules","desktop_operator")
    g.ingest([("Market observation is unverified research.","market://test")],source="market://test",namespace=scope,principal="desktop_operator")
    reopened=MemoryGateway(Config(url="http://127.0.0.1:6333"),ledger,setup=backend)
    assert reopened.retrieve("Market",namespace=scope,principal="desktop_operator")["results"]
    for index,value in [(3,"paper"),(4,"account-b"),(1,"ETH/USDT:USDT")]:
        other=identity.copy(); other[index]=value
        isolated=reopened.register_market_partition("desktop",other,"six-rules","desktop_operator")
        assert not reopened.retrieve("Market",namespace=isolated,principal="desktop_operator")["results"]
    with pytest.raises(PermissionError): reopened.require("read",scope,"other-actor")
    with pytest.raises(PermissionError): reopened.require("read","market."+"a"*40,"desktop_operator")
    grants.perms["memory.read."+scope]=False
    with pytest.raises(PermissionError): reopened.require("read",scope,"desktop_operator")
    del grants.perms["memory.read."+scope]
    grants.perms["memory.read.desktop"]=False
    with pytest.raises(PermissionError): reopened.require("read",scope,"desktop_operator")
    grants.perms["memory.ingest.desktop"]=False
    with pytest.raises(PermissionError): reopened.register_market_partition("desktop",identity,"changed","desktop_operator")

def test_custom_authorizer_never_inherits_parent(tmp_path):
    g=MemoryGateway(Config(url="http://127.0.0.1:6333"),tmp_path/"ledger.sqlite3",setup=Backend(),authorize=lambda action,ns,actor: ns=="desktop")
    scope=g.register_market_partition("desktop",["v","s","5m","paper","a"],"rules","operator")
    with pytest.raises(PermissionError): g.require("read",scope,"operator")


def test_concurrent_cold_core_requests_share_one_instance(monkeypatch):
    import server
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    calls=[]
    def constructor():
        calls.append(True); time.sleep(.05); return object()
    monkeypatch.setattr(server,"_core",None)
    monkeypatch.setattr(server,"NiblitCore",constructor)
    barrier=threading.Barrier(6)
    def request(_): barrier.wait(timeout=5); return server.get_core()
    with ThreadPoolExecutor(max_workers=6) as pool: instances=list(pool.map(request,range(6)))
    assert len(calls)==1 and all(value is instances[0] for value in instances)
    bound=object(); server.bind_core(bound)
    assert server.get_core() is bound
