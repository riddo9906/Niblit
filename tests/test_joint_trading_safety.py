"""Existing Core + platform ticket paths. All providers are offline doubles."""
from types import SimpleNamespace
import pytest
from modules.trading_session_selftest import fixture, freq_fixture, activate
from modules.mt5_orders import DemoOrders
from modules.trading_values import freqtrade_actuals


def body(f,**extra):
    return dict(action='open',symbol='EURUSD',side='buy',volume=.01,
        account_identity=f.bridge.identity(f.api.account_info()),**extra)


def test_native_mt5_delivery_is_denied_without_consuming_ticket(tmp_path):
    f=fixture(tmp_path)
    native=DemoOrders(f.bridge,tmp_path/'native-denied.sqlite')
    ticket=native.preview(body(f),core_owned=True)['ticket']
    assert native.confirm(ticket,guard=lambda:None)['state']=='execution_denied'
    assert not f.api.sent
    with native.db() as db:assert db.execute('select state from mt5_tickets').fetchone()[0]=='preview'


def test_demo_label_alone_cannot_bind_a_transport(tmp_path):
    f=fixture(tmp_path)
    with pytest.raises(ValueError,match='Exact verified demo identity'):
        DemoOrders(f.bridge,tmp_path/'invalid.sqlite',expected_binding={'environment':'demo'},execution_transport=f.api.order_send)


def test_native_freqtrade_delivery_is_denied_before_http_or_ticket_consumption(tmp_path):
    f=freq_fixture(tmp_path);adapter=f.service.adapters['freqtrade']
    snapshot=adapter.snapshot('BTC/USDT:USDT')
    from modules.core_trading_sessions import configured_limits
    prepared=adapter.prepare(snapshot,'buy',configured_limits())
    f.desk.transport=None
    f.desk.connection=lambda:(_ for _ in ()).throw(AssertionError('No HTTP/config read needed to deny'))
    assert adapter.submit(prepared,lambda:None)['state']=='execution_denied'
    assert not f.api.sent
    with pytest.raises(PermissionError,match='EXECUTION_DENIED'):f.desk.api('forceenter',{'pair':'BTC/USDT:USDT'})


@pytest.mark.parametrize('change,match',[
    ('funded','demo'),('wrong_account','changed'),('broker','binding'),
    ('disconnected','connected'),('symbol','permit'),('margin','margin'),('expert','permission')])
def test_mt5_broker_or_binding_denial_never_calls_intercepted_send(tmp_path,change,match):
    f=fixture(tmp_path);request=body(f)
    if change=='funded':f.api.account.trade_mode=2
    elif change=='wrong_account':f.api.account.login=2
    elif change=='broker':f.api.account.company='Changed broker'
    elif change=='disconnected':f.api.terminal_info=lambda:SimpleNamespace(connected=False)
    elif change=='symbol':f.api.info.trade_mode=0
    elif change=='margin':f.api.account.margin_free=0
    else:f.api.account.trade_expert=False
    with pytest.raises((ValueError,PermissionError,RuntimeError),match=match):f.orders.preview(request,core_owned=True)
    assert not f.api.sent


@pytest.mark.parametrize('volume',[0,-.01,.015,float('inf'),True])
def test_invalid_mt5_volume(tmp_path,volume):
    f=fixture(tmp_path);request=body(f);request['volume']=volume
    with pytest.raises(ValueError):f.orders.preview(request,core_owned=True)
    assert not f.api.sent


def test_account_change_after_preflight_blocks_core_delivery(tmp_path):
    f=fixture(tmp_path);activate(f)
    adapter=f.service.adapters['mt5'];old=adapter.prepare
    def changed(*args,**kwargs):
        prepared=old(*args,**kwargs);f.api.account.login=2;return prepared
    adapter.prepare=changed;f.bot.step()
    assert not f.api.sent


def test_mt5_risk_limit_and_missing_authority(tmp_path):
    f=fixture(tmp_path);f.bot.step();assert not f.api.sent
    activate(f);f.api.order_calc_profit=lambda *args:-100.;f.bot.step();assert not f.api.sent


def test_platform_activation_does_not_authorize_other_platform(tmp_path):
    a=fixture(tmp_path/'mt5');b=freq_fixture(tmp_path/'freqtrade')
    activate(a);a.bot.step();b.bot.step()
    assert len(a.api.sent)==1 and not b.api.sent


def test_freqtrade_native_strategy_can_be_observed_but_not_adopted_for_core_entry(tmp_path):
    f=freq_fixture(tmp_path);f.api.config['strategy']='NiblitLabManager'
    s=f.service.adapters['freqtrade'].snapshot('BTC/USDT:USDT')
    from modules.core_trading_sessions import configured_limits
    with pytest.raises(PermissionError,match='Core-managed'):f.service.adapters['freqtrade'].prepare(s,'buy',configured_limits())
    assert not f.api.sent


def test_historical_fees_do_not_substitute_for_new_entry_fee(tmp_path):
    f=freq_fixture(tmp_path);f.api.config.pop('fee')
    s=f.service.adapters['freqtrade'].snapshot('BTC/USDT:USDT')
    from modules.core_trading_sessions import configured_limits
    with pytest.raises(ValueError,match='historical position fees'):f.service.adapters['freqtrade'].prepare(s,'buy',configured_limits())
    assert not f.api.sent


def test_actuals_do_not_double_count_equity_or_assign_mixed_strategy_profit():
    p=dict(trade_id=1,pair='TEST/USDT',strategy='NiblitLabManager',is_short=True,
        open_rate=100.,current_rate=90.,amount=1.,fee_open_cost=.1,fee_close=.001,
        fee_close_cost=None,funding_fees=.2,profit_abs=10.01,realized_profit=0.)
    balance={'stake':'USDT','total':1010.02,'starting_capital':990.,
        'currencies':[{'currency':'USDT','balance':1000.,'used':100.,'free':900.}]}
    profit={'profit_closed_coin':0.}
    closed=[{'is_open':False,'strategy':'Other','close_profit_abs':5.},
            {'is_open':False,'strategy':'NiblitLabManager','close_profit_abs':-5.}]
    r=freqtrade_actuals([p],balance,profit,closed,observed_at=1,mode='dry-run')
    assert r['positions'][0]['calculation_verified']
    assert r['capital']['equity_at_status_marks']==pytest.approx(1010.01)
    assert r['capital']['marked_equity_reported']==1010.02
    assert r['realized_by_strategy']=={'Other':5.,'NiblitLabManager':-5.}
    assert r['positions'][0]['closing_fee_paid'] is None
    assert r['price_as_of']=='UNKNOWN' and not r['execution_authorized']


def test_negative_floating_profit_is_not_subtracted_from_marked_equity_twice(tmp_path):
    f=freq_fixture(tmp_path);p=f.service.propose('freqtrade','BTC/USDT:USDT',60)
    f.service.activate(p['id'],p['spec_hash'],threaded=False);f.bot.step()
    f.api.trades[0]['profit_abs']=-5.
    snapshot=f.service.adapters['freqtrade'].snapshot('BTC/USDT:USDT')
    assert snapshot['equity']==10000. and snapshot['unrealized']==-5.


def test_readiness_recall_is_platform_and_principal_scoped(tmp_path,monkeypatch):
    from test_memory_laboratory_gateway import Backend,gateway
    from modules.memory_laboratory import context
    from modules.trading_read_tools import read_trading_readiness
    g=gateway(tmp_path,Backend());monkeypatch.setattr(context,'runtime_gateway',lambda:g)
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_NAMESPACE','test');monkeypatch.setenv('NIBLIT_MEMORY_LAB_PRINCIPAL','operator')
    with g.db() as db:
        for platform in ('mt5','freqtrade'):
            g.audit(db,'trading.preflight','fixture.'+platform,namespace='test',principal='operator',
                platform=platform,observation={'summary':'recorded only','observed_at':'fixture'})
    result=read_trading_readiness('mt5')
    assert len(result['reports'])==1 and result['reports'][0]['platform']=='mt5'
    assert result['execution_state']=='DENIED'
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_PRINCIPAL','other')
    assert read_trading_readiness()['status']=='UNKNOWN'
    with pytest.raises(ValueError):read_trading_readiness('../broker')
