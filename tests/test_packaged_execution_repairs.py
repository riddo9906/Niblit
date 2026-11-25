import time
import pytest
from modules.trading_session_adapters import bound_cost_schedule
from modules.trading_session_selftest import fixture
from modules.core_trading_sessions import configured_limits


def schedule_for(s):
    return dict(binding={k:s[k] for k in ('account','environment','symbol')},
        account_binding={k:s['account_binding'][k] for k in ('broker','server','terminal_id')},
        currency=s['currency'],sides=['buy','sell'],provenance='operator_approved_bound',version='fixture-v1',
        source='INTERCEPTED_FIXTURE_NOT_BROKER_COSTS',verified_at=time.time()-1,
        expires=time.time()+60,max_volume=.01,minimum_commission=.1,
        round_trip_per_lot=10,financing_upper_bound=.05,slippage_upper_bound=.05)


def test_real_adapter_propagates_bound_costs_without_delivery(tmp_path):
    f=fixture(tmp_path);a=f.service.adapters['mt5'];a.cost_model=None
    s=a.snapshot('EURUSD');a.cost_schedule=schedule_for(s)
    p=a.prepare(s,'buy',configured_limits()|{'max_volume':.01})
    assert p['costs']['costs_complete'] is True
    assert p['costs']['modeled_loss']>=p['risk']
    assert p['costs']['binding']=={k:s[k] for k in ('account','environment','symbol')}
    assert p['costs']['execution_authorized'] is False
    assert f.api.sent==[]
    f.service.shutdown()


@pytest.mark.parametrize('field,value',[
 ('binding',{'account':'wrong','environment':'demo','symbol':'EURUSD'}),
 ('sides',['sell']),('sides',None),('account_binding',None),('currency','OTHER'),('provenance','historical_observation'),('expires',1),
 ('max_volume',.001),('account_binding',{'broker':'wrong'}),('version','')])
def test_wrong_stale_or_unapproved_schedule_is_not_cost_evidence(tmp_path,field,value):
    f=fixture(tmp_path);a=f.service.adapters['mt5'];s=a.snapshot('EURUSD')
    assert bound_cost_schedule(s,.01,schedule_for(s)|{field:value},side='buy',now=time.time()) is None
    assert f.api.sent==[]
    f.service.shutdown()


def test_missing_cost_schedule_still_fails_closed(tmp_path):
    f=fixture(tmp_path);a=f.service.adapters['mt5'];a.cost_model=None
    s=a.snapshot('EURUSD');p=a.prepare(s,'buy',configured_limits()|{'max_volume':.01})
    assert p['costs']['costs_complete'] is False
    assert p['costs']['commission'] is None
    assert f.api.sent==[]
    f.service.shutdown()


def test_observation_profile_still_allows_authenticated_ordinary_stop(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    from modules.trading_session_api import register_trading_routes
    monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY','1')
    monkeypatch.setenv('NIBLIT_API_PORT','5200')
    control=Mock();control.nonce='fixture-stop-token';control.stop.return_value={'stopped':True}
    app=FastAPI();register_trading_routes(app,lambda:control)
    with TestClient(app,base_url='http://127.0.0.1:5200') as client:
        assert client.post('/api/trading/sessions/stop',json={},headers={'origin':'http://tauri.localhost'}).status_code==403
        response=client.post('/api/trading/sessions/stop',json={},headers={'origin':'http://tauri.localhost','x-niblit-trading-nonce':control.nonce})
        assert response.status_code==200 and response.json()['stopped']
    control.stop.assert_called_once_with(None)


def test_native_callback_authentication_does_not_mint_a_claim(tmp_path,monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    from modules.trading_session_api import register_trading_routes
    from modules.freqtrade_core_claim import account_binding
    cfg={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':{'name':'binance'},'stake_currency':'USDT','trading_mode':'futures','db_url':'sqlite:///isolated.sqlite'}
    path=tmp_path/'config.json';path.write_text(json.dumps(cfg));token=tmp_path/'token';token.write_text('x'*48)
    monkeypatch.setenv('NIBLIT_API_PORT','5200');monkeypatch.setenv('NIBLIT_FREQTRADE_EXECUTION_CONFIG',str(path));monkeypatch.setenv('NIBLIT_NATIVE_CALLBACK_TOKEN_FILE',str(token))
    control=Mock();control.native_entry_receipt.side_effect=PermissionError('No unique sending Core claim')
    app=FastAPI();register_trading_routes(app,lambda:control)
    body={'ticket':'x'*32,'symbol':'BTC/USDT:USDT','side':'long','amount':.001,'rate':100.,'stoploss':-.01,'minimal_roi':{'0':.02},'fee':.0002,'account_binding':account_binding(cfg)}
    with TestClient(app,base_url='http://host.docker.internal:5200') as client:
        assert client.post('/api/trading/native-entry-receipt',json=body,headers={'x-niblit-native-token':'wrong'}).status_code==403
        assert not control.native_entry_receipt.called
        response=client.post('/api/trading/native-entry-receipt',json=body,headers={'x-niblit-native-token':'x'*48})
        assert response.status_code==403 and 'No unique sending' in response.text
    control.native_entry_receipt.assert_called_once()


def ft_cost_case(tmp_path):
    from modules.trading_session_selftest import freq_fixture
    f=freq_fixture(tmp_path);a=f.service.adapters['freqtrade'];a.cost_model=None
    s=a.snapshot('BTC/USDT:USDT')
    schedule=dict(binding={k:s[k] for k in ('account','environment','symbol')},currency=s['currency'],
        provenance='simulation_assumption',source='FIXTURE_NOT_ACCOUNT_FEE',version='test-v1',
        verified_at=time.time()-1,expires=time.time()+60,sides=['buy'],max_notional=1000,
        fee=s['protections']['fee'],funding_upper_bound=0.,slippage_upper_bound=.1)
    return f,a,s,schedule


def test_freqtrade_cost_hook_keeps_fee_and_explicit_bounds_separate(tmp_path):
    f,a,s,schedule=ft_cost_case(tmp_path)
    a.cost_schedule=schedule
    p=a.draft_entry(s,'buy',configured_limits())
    assert p['costs']['costs_complete']
    assert p['costs']['modeled_loss']>p['risk']
    assert p['costs']['provenance']=='simulation_assumption'
    assert f.api.sent==[]
    f.service.shutdown()


@pytest.mark.parametrize('field,value',[('fee',.009),('funding_upper_bound',None),('slippage_upper_bound',-1),('expires',1),('binding',{})])
def test_freqtrade_missing_conflicting_or_stale_cost_bounds_are_not_complete(tmp_path,field,value):
    f,a,s,schedule=ft_cost_case(tmp_path);a.cost_schedule=schedule|{field:value}
    assert not a.draft_entry(s,'buy',configured_limits())['costs']['costs_complete']
    assert f.api.sent==[]
    f.service.shutdown()


def test_native_fee_uses_exact_paper_profile_only():
    from modules.trading_session_adapters import native_dry_run_fee
    private={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':{'name':'binance'},
             'trading_mode':'futures','fee':.0002}
    engine={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':'binance','trading_mode':'futures'}
    assert native_dry_run_fee(engine,private)==(.0002,'private_dry_run_simulation_assumption')
    assert native_dry_run_fee(engine|{'strategy':'OtherStrategy'},private)[0] is None
    assert native_dry_run_fee(engine|{'dry_run':False},private)[0] is None
    assert native_dry_run_fee(engine,private|{'fee':float('nan')})[0] is None


def test_freqtrade_symbol_cost_profiles_are_bound_to_the_selected_pair(tmp_path):
    f,a,s,schedule=ft_cost_case(tmp_path)
    a.cost_schedule={'schema_version':'niblit-paper-costs/1',
                     'by_symbol':{s['symbol']:schedule}}
    assert a.draft_entry(s,'buy',configured_limits())['costs']['costs_complete']
    a.cost_schedule={'by_symbol':{'another/symbol':schedule}}
    assert not a.draft_entry(s,'buy',configured_limits())['costs']['costs_complete']
    assert f.api.sent==[]
    f.service.shutdown()


def test_paper_cost_schedule_is_bound_to_verified_mt5_demo_identity(tmp_path):
    f=fixture(tmp_path);a=f.service.adapters['mt5'];a.cost_model=None
    s=a.snapshot('EURUSD')
    schedule=schedule_for(s)|{'provenance':'simulation_assumption','scope':'local_demo_only',
                                'source':'FIXTURE_PAPER_ONLY_NOT_BROKER_CERTIFIED'}
    assert bound_cost_schedule(s,.01,schedule,side='buy',now=time.time()) is not None
    a.cost_schedule=schedule
    draft=a.draft_entry(s,'buy',configured_limits()|{'max_volume':.01})
    assert draft['costs']['costs_complete'] is True
    assert draft['costs']['provenance']=='simulation_assumption'
    assert f.api.sent==[]
    assert bound_cost_schedule(s|{'environment':'live'},.01,schedule,side='buy',now=time.time()) is None
    assert bound_cost_schedule(s,.01,schedule|{'scope':'live'},side='buy',now=time.time()) is None
    assert bound_cost_schedule(s,.01,schedule|{'account_binding':{'broker':'other','server':'other','terminal_id':'other'}},side='buy',now=time.time()) is None
    assert bound_cost_schedule(s,.01,schedule|{'binding':{'account':'other','environment':'demo','symbol':'EURUSD'}},side='buy',now=time.time()) is None
    assert bound_cost_schedule(s,.01,schedule|{'expires':1},side='buy',now=time.time()) is None
    f.service.shutdown()


def test_freqtrade_submit_passes_exact_core_receipt_to_native_guard():
    """A valid scoped Core receipt must survive the protection wrapper."""
    from types import SimpleNamespace
    from modules.trading_session_adapters import FreqtradeSessionAdapter
    calls=[]
    receipt={'environment':'dry-run','adapter':'freqtrade','ticket':'fixture-ticket',
             'account':'fixture-account','symbol':'ETH/USDT:USDT','action':'open','expires':time.time()+60}
    def confirm(ticket,expected=None,guard=None):
        assert ticket=='fixture-ticket'
        result=guard()
        calls.append(result)
        return {'state':'submitted','receipt':result}
    desk=SimpleNamespace(confirm=confirm)
    prepared={'ticket':'fixture-ticket','expected':{'core_owned':True}}
    def core_guard():
        calls.append('core_guard_invoked')
        return receipt
    result=FreqtradeSessionAdapter(desk).submit(prepared,core_guard)
    assert calls==['core_guard_invoked',receipt]
    assert result['receipt'] is receipt


def test_freqtrade_submit_preserves_receipt_after_native_protection_check():
    """The production protection-check path must not discard the receipt."""
    from types import SimpleNamespace
    from modules.trading_session_adapters import FreqtradeSessionAdapter
    receipt={'adapter':'freqtrade','environment':'dry-run','action':'open','ticket':'paper-ticket',
             'account':'demo-id','symbol':'ETH/USDT:USDT','expires':time.time()+90}
    private={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':{'name':'binance'},
             'trading_mode':'futures','stake_currency':'USDT','db_url':'sqlite:///paper.sqlite','fee':0.0002}
    public={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':'binance',
            'trading_mode':'futures','stake_currency':'USDT','stoploss':-0.005,'minimal_roi':{'0':0.01}}
    checks=[]
    def api(path):
        assert path=='show_config'
        checks.append('native_protection_rechecked')
        return public
    def confirm(ticket,expected=None,guard=None):
        assert ticket=='paper-ticket'
        result=guard()
        checks.append('receipt_forwarded')
        assert result is receipt
        return {'state':'submitted'}
    desk=SimpleNamespace(api=api,connection=lambda:(private,None),confirm=confirm)
    from modules.trading_session_adapters import native_dry_run_fee
    fee,_=native_dry_run_fee(public,private)
    prepared={'ticket':'paper-ticket','expected':{},'native_stoploss':-0.005,
              'native_roi':{'0':0.01},'native_fee':fee}
    assert FreqtradeSessionAdapter(desk).submit(prepared,lambda:receipt)=={'state':'submitted'}
    assert checks==['native_protection_rechecked','receipt_forwarded']
