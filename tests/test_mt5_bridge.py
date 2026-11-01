from types import SimpleNamespace as Obj
from unittest.mock import Mock
import time
import pytest
from fastapi.testclient import TestClient
from modules.mt5_bridge import MT5Bridge, MT5Unavailable
from modules.trading_desk import create_app


@pytest.fixture
def bridge():
    api=Mock()
    for name,value in dict(ACCOUNT_TRADE_MODE_DEMO=0,TIMEFRAME_M5=5,TRADE_ACTION_DEAL=1,
        ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,
        ORDER_FILLING_RETURN=2,ORDER_TIME_GTC=0).items(): setattr(api,name,value)
    api.initialize.return_value=True
    api.account_info.return_value=Obj(login=12345678,server='Example-Demo',trade_mode=0,
        currency='USD',balance=1000,equity=1000,profit=0,margin=0,margin_free=1000,
        leverage=1,trade_allowed=True)
    api.terminal_info.return_value=Obj(connected=True,build=1,trade_allowed=False,tradeapi_disabled=False)
    api.symbols_get.return_value=[Obj(name='EURUSD',visible=True)]
    api.symbol_info.return_value=Obj(visible=True,volume_min=.01,volume_max=100,volume_step=.01,filling_mode=1)
    api.symbol_info_tick.return_value=Obj(time_msc=int((time.time()+7200)*1000),time=int(time.time()+7200),bid=1.1,ask=1.1001)
    api.copy_rates_from_pos.return_value=[dict(time=int(time.time())+7200-300,open=1.,high=2.,low=.5,close=1.1,tick_volume=10)]
    api.positions_get.return_value=[]
    api.orders_get.return_value=[]
    api.order_check.return_value=Obj(retcode=0,comment='Done',margin=11,margin_free=989)
    return MT5Bridge(api)


def advance(bridge):
    bridge.snapshot()
    bridge._api.symbol_info_tick.return_value.time_msc+=1000


def test_snapshot_preserves_broker_clock_and_does_not_expose_login(bridge):
    first=bridge.snapshot()
    assert not first['quote']['fresh']
    assert first['candles']  # completed bar index is authoritative even with server clock offset
    assert 'login' not in first['account'] and 'name' not in first['account']
    bridge._api.symbol_info_tick.return_value.time_msc+=1000
    assert bridge.snapshot()['quote']['fresh']
    assert bridge._api.copy_rates_from_pos.call_args.args[2]==1
    bridge._api.order_send.assert_not_called()
    bridge._api.login.assert_not_called()


def test_unchanged_tick_becomes_stale(bridge,monkeypatch):
    advance(bridge)
    monkeypatch.setattr('modules.mt5_bridge.time.monotonic',lambda:100)
    bridge.snapshot()
    monkeypatch.setattr('modules.mt5_bridge.time.monotonic',lambda:161)
    assert not bridge.snapshot()['quote']['fresh']


@pytest.mark.parametrize('mode',[1,2])
def test_non_demo_preflight_blocked(bridge,mode):
    bridge._api.account_info.return_value.trade_mode=mode
    with pytest.raises(ValueError,match='demo'):
        bridge.check_order('EURUSD','buy',.01,'irrelevant')
    bridge._api.order_check.assert_not_called()
    bridge._api.order_send.assert_not_called()


def test_check_only_does_not_enable_trading_or_send_order(bridge):
    advance(bridge)
    identity=bridge.identity(bridge._api.account_info())
    result=bridge.check_order('EURUSD','buy',.01,identity)
    assert result['accepted'] and not result['order_submitted']
    assert not result['terminal_execution_allowed']
    bridge._api.order_send.assert_not_called()
    bridge._api.login.assert_not_called()


def test_account_switch_and_oversize_volume_are_rejected(bridge):
    with pytest.raises(ValueError,match='changed'):
        bridge.check_order('EURUSD','buy',.01,'different-account')
    with pytest.raises(ValueError,match='0.01'):
        bridge.check_order('EURUSD','buy',1,bridge.identity(bridge._api.account_info()))


def test_disconnected_terminal_does_not_report_ready(bridge):
    bridge._api.terminal_info.return_value.connected=False
    with pytest.raises(MT5Unavailable): bridge.snapshot()


def test_mt5_routes_enforce_origin_and_session_token(bridge,tmp_path):
    from modules.trading_desk import Desk
    client=TestClient(create_app(Desk(tmp_path,Mock()),mt5=bridge))
    s=client.get('/api/mt5/snapshot').json()
    assert s['connected']
    body=dict(symbol='EURUSD',side='buy',volume=.01,account_identity=s['account']['identity'])
    assert client.post('/api/mt5/check-order',json=body).status_code==403
    token=client.get('/').text.split('name="desk-token" content="')[1].split('"')[0]
    advance(bridge)
    assert client.post('/api/mt5/check-order',json=body,headers={
        'origin':'http://127.0.0.1:8767','x-desk-token':token}).status_code==200
    assert client.post('/api/mt5/order-send',json=body).status_code!=200
