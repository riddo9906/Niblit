import json
from types import SimpleNamespace as Obj
from unittest.mock import Mock
import pytest
from modules.mt5_orders import DemoOrders, MAGIC
from test_mt5_bridge import bridge, advance


@pytest.fixture
def orders(bridge,tmp_path):
    bridge._api.terminal_info.return_value.trade_allowed=True
    info=bridge._api.symbol_info.return_value
    info.point=.00001; info.digits=5; info.trade_stops_level=10
    bridge._api.order_calc_profit.return_value=-2
    bridge._api.order_calc_margin.return_value=10.
    bridge._api.order_send.return_value=Obj(retcode=10009,deal=45,order=44,volume=.01,price=1.1001,comment='Done')
    advance(bridge)
    bridge.snapshot()
    binding={k:v for k,v in bridge.account_record(bridge._api,bridge._api.account_info(),bridge._api.terminal_info()).items() if k!='login'}
    return DemoOrders(bridge,tmp_path/'mt5.sqlite3',expected_binding=binding,execution_transport=bridge._api.order_send)


def intent(orders,**extra):
    return dict(symbol='EURUSD',side='buy',volume=.01,
        account_identity=orders.bridge.identity(orders.bridge._api.account_info()),action='open',**extra)


def test_send_once_and_durable_replay(orders):
    key=orders.preview(intent(orders))['ticket']
    assert orders.confirm(key)['state']=='filled'
    other=DemoOrders(orders.bridge,orders.path)
    assert other.confirm(key)['state']=='filled'
    orders.bridge._api.order_send.assert_called_once()
    request=orders.bridge._api.order_send.call_args.args[0]
    assert request['sl']<request['price']<request['tp']
    assert request['volume']==.01 and request['magic']==MAGIC


def test_automatic_budget_rechecked_at_delivery(orders):
    body=intent(orders,max_stop_risk=2.1)
    key=orders.preview(body)['ticket']
    orders.bridge._api.order_calc_profit.return_value=-2.11
    with pytest.raises(ValueError,match='Automatic demo risk'): orders.confirm(key)
    orders.bridge._api.order_send.assert_not_called()


@pytest.mark.parametrize('mode',[1,2])
def test_funded_or_contest_never_sends(orders,mode):
    key=orders.preview(intent(orders))['ticket']
    orders.bridge._api.account_info.return_value.trade_mode=mode
    with pytest.raises(ValueError,match='demo'): orders.confirm(key)
    orders.bridge._api.order_send.assert_not_called()


def test_account_switch_rejects(orders):
    key=orders.preview(intent(orders))['ticket']
    orders.bridge._api.account_info.return_value.login=999
    with pytest.raises(ValueError,match='changed'): orders.confirm(key)
    orders.bridge._api.order_send.assert_not_called()


def test_unknown_delivery_blocks_all_other_tickets(orders):
    first=orders.preview(intent(orders))['ticket']
    second=orders.preview(intent(orders))['ticket']
    orders.bridge._api.order_send.side_effect=TimeoutError()
    assert orders.confirm(first)['state']=='unknown'
    assert orders.confirm(first)['state']=='unknown'
    with pytest.raises(ValueError,match='earlier'): orders.confirm(second)
    with pytest.raises(ValueError,match='unresolved'): orders.preview(intent(orders))
    orders.bridge._api.order_send.assert_called_once()


def test_expiry_and_excess_risk_never_send(orders):
    key=orders.preview(intent(orders))['ticket']
    with orders.db() as db: db.execute('UPDATE mt5_tickets SET created=0 WHERE id=?',(key,))
    with pytest.raises(ValueError,match='expired'): orders.confirm(key)
    orders.bridge._api.order_calc_profit.return_value=-100
    with pytest.raises(ValueError,match='risk'): orders.preview(intent(orders))
    orders.bridge._api.order_send.assert_not_called()


def test_cannot_close_other_positions(orders):
    body=intent(orders); body.update(action='close',position_ticket=100)
    orders.bridge._api.positions_get.return_value=[Obj(ticket=100,symbol='EURUSD',magic=0,volume=.01,type=0)]
    with pytest.raises(ValueError,match='exact'): orders.preview(body)
    orders.bridge._api.positions_get.return_value[0].magic=MAGIC
    key=orders.preview(body)['ticket']
    assert orders.confirm(key)['state']=='filled'
    sent=orders.bridge._api.order_send.call_args.args[0]
    assert sent['position']==100 and sent['type']==orders.bridge._api.ORDER_TYPE_SELL


def test_broker_check_rejection_never_sends(orders):
    orders.bridge._api.order_check.return_value.retcode=10016
    with pytest.raises(ValueError,match='preflight'): orders.preview(intent(orders))
    orders.bridge._api.order_send.assert_not_called()


def test_other_niblit_symbol_does_not_impersonate_eth_entry(orders, monkeypatch):
    monkeypatch.setenv("NIBLIT_MT5_EXECUTION_SYMBOLS", "ETHUSDm")
    orders.bridge._api.positions_get.return_value = [
        Obj(ticket=917, symbol="BTCUSDm", magic=MAGIC, volume=.01, type=0)
    ]
    # A pre-existing, protected BTC trade is accounted for by Core's aggregate
    # risk check. It is not a claim against the separate ETHUSDm instrument.
    request = intent(orders)
    request["symbol"] = "ETHUSDm"
    orders.bridge._api.symbols_get.return_value.append(Obj(name="ETHUSDm", visible=True))
    orders.bridge.snapshot("ETHUSDm")
    orders.bridge._api.symbol_info_tick.return_value.time_msc += 1000
    assert orders.inspect(request)["symbol"] == "ETHUSDm"
    orders.bridge._api.order_send.assert_not_called()


def test_same_symbol_exposure_is_not_reused(orders, monkeypatch):
    monkeypatch.setenv("NIBLIT_MT5_EXECUTION_SYMBOLS", "ETHUSDm")
    orders.bridge._api.positions_get.return_value = [
        Obj(ticket=918, symbol="ETHUSDm", magic=0, volume=.01, type=0)
    ]
    request = intent(orders)
    request["symbol"] = "ETHUSDm"
    orders.bridge._api.symbols_get.return_value.append(Obj(name="ETHUSDm", visible=True))
    orders.bridge.snapshot("ETHUSDm")
    orders.bridge._api.symbol_info_tick.return_value.time_msc += 1000
    with pytest.raises(ValueError, match="selected symbol"):
        orders.inspect(request)
    orders.bridge._api.order_send.assert_not_called()


def test_demo_symbol_scope_rejects_btc(orders, monkeypatch):
    monkeypatch.setenv("NIBLIT_MT5_EXECUTION_SYMBOLS", "ETHUSDm")
    with pytest.raises(PermissionError, match="outside"):
        orders.inspect(intent(orders))
    orders.bridge._api.order_send.assert_not_called()


def test_competing_core_refuses_delivery_without_consuming_ticket(orders, monkeypatch):
    import psutil
    monkeypatch.setenv("NIBLIT_API_PORT", "5202")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_PORTS", "5200")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_IMAGE", r"C:\older\niblit.exe")
    key = orders.preview(intent(orders))["ticket"]
    listener = Mock(status=psutil.CONN_LISTEN, laddr=Mock(port=5200))
    monkeypatch.setattr("psutil.net_connections", lambda kind: [listener])
    with pytest.raises(PermissionError, match="Another trading Core"):
        orders.confirm(key)
    with orders.db() as db:
        assert db.execute("SELECT state FROM mt5_tickets WHERE id=?", (key,)).fetchone()["state"] == "preview"
    orders.bridge._api.order_send.assert_not_called()


def test_competing_core_reappears_after_preview_guard(orders, monkeypatch):
    import psutil
    monkeypatch.setenv("NIBLIT_API_PORT", "5202")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_PORTS", "5200")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_IMAGE", r"C:\older\niblit.exe")
    key = orders.preview(intent(orders))["ticket"]
    calls = {"count": 0}

    def connections(kind):
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        return [Mock(status=psutil.CONN_LISTEN, laddr=Mock(port=5200))]

    monkeypatch.setattr(psutil, "net_connections", connections)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [])
    outcome = orders.confirm(key)
    assert outcome["state"] == "rejected"
    assert calls["count"] >= 2
    orders.bridge._api.order_send.assert_not_called()


def test_competing_core_image_blocks_even_before_listener(monkeypatch):
    import psutil
    from modules.mt5_orders import require_exclusive_demo_core
    monkeypatch.setenv("NIBLIT_API_PORT", "5202")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_PORTS", "5200")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_IMAGE", r"C:\older\niblit.exe")
    monkeypatch.setattr(psutil, "net_connections", lambda kind: [])
    monkeypatch.setattr(psutil, "process_iter",
                        lambda attrs: [Mock(info={"name": "niblit.exe", "exe": r"C:\older\niblit.exe"})])
    with pytest.raises(PermissionError, match="Previous trading Core"):
        require_exclusive_demo_core()


def test_timewait_socket_without_listener_does_not_block_demo(monkeypatch):
    import psutil
    from modules.mt5_orders import require_exclusive_demo_core
    monkeypatch.setenv("NIBLIT_API_PORT", "5202")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_PORTS", "5200")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_IMAGE", r"C:\older\niblit.exe")
    monkeypatch.setattr(psutil, "net_connections",
                        lambda kind: [Mock(status=psutil.CONN_TIME_WAIT, laddr=Mock(port=5200))])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [])
    require_exclusive_demo_core()


def test_competing_port_bad_value_rejected(orders, monkeypatch):
    from modules.mt5_orders import require_exclusive_demo_core
    monkeypatch.setenv("NIBLIT_API_PORT", "5202")
    monkeypatch.setenv("NIBLIT_MT5_COMPETING_CORE_PORTS", "5202")
    with pytest.raises(ValueError, match="Invalid competing Core"):
        require_exclusive_demo_core()
