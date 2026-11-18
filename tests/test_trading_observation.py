import json
from types import SimpleNamespace
import pytest
from modules.trading_observation import ReadOnlyMT5,profile
from modules.cognitive_chat import admission


def test_observer_cannot_reach_mutating_mt5_methods():
    calls=[]
    native=SimpleNamespace(account_info=lambda: 'read',order_send=lambda *a:calls.append(a),
                           login=lambda *a:calls.append(a),initialize=lambda *a:calls.append(a))
    observer=ReadOnlyMT5(native)
    assert observer.account_info()=='read'
    for name in ('order_send','login','initialize','shutdown','symbol_select','order_check'):
        with pytest.raises(PermissionError):getattr(observer,name)
    assert calls==[]


def test_profile_requires_execution_denial(tmp_path,monkeypatch):
    path=tmp_path/'profile.json';path.write_text(json.dumps({'execution_state':'ENABLED'}))
    monkeypatch.setenv('NIBLIT_OBSERVATION_PROFILE',str(path))
    with pytest.raises(PermissionError):profile()


def test_chat_admits_only_bounded_observation_not_trade_instructions():
    assert admission('Observe trading now')[1]==[('observe_trading',{})]
    assert admission('Compare trading observations')[1]==[('recall_trading_observations',{})]
    assert not any(n=='observe_trading' for n,_ in admission('Observe trading now and close all positions')[1])


def test_observer_has_no_execution_authority_from_market_payload(monkeypatch):
    from modules import trading_observation as m
    monkeypatch.setenv('NIBLIT_OBSERVATION_PROFILE','relative.json')
    with pytest.raises(PermissionError):m.profile()


def test_exit_estimate_uses_executable_side_and_never_calls_it_complete():
    from modules.trading_values import linear_exit_estimate
    value=linear_exit_estimate(entry=110,bid=100,ask=101,quantity=2,short=True,
        entry_fee=.2,closing_rate=.001,funding=.5,stop=120)
    assert value['gross_if_closed_at_book']==18
    assert value['spread_cost_at_quantity']==2
    assert value['net_excluding_unknown_costs']==pytest.approx(18.098)
    assert value['gross_loss_from_entry_at_exact_stop']==20
    assert value['complete_net_outcome']=='UNKNOWN'
    assert value['execution_authorized'] is False


def test_missing_fee_and_crossed_stop_are_not_silently_favorable():
    from modules.trading_values import linear_exit_estimate
    value=linear_exit_estimate(entry=110,bid=120,ask=121,quantity=2,short=True,
        entry_fee=.2,closing_rate=None,funding=None,stop=120)
    assert value['net_excluding_unknown_costs'] is None
    assert value['stop_crossed'] is True
    with pytest.raises(ValueError):
        linear_exit_estimate(entry=110,bid=122,ask=121,quantity=2,short=True,
            entry_fee=.2,closing_rate=.001,funding=0,stop=120)


def test_cost_review_intents_do_not_admit_mutations():
    assert admission('Review MT5 execution conditions.')[1]==[('observe_trading',{'review':True,'platform':'mt5'})]
    assert admission('Review Freqtrade execution conditions.')[1]==[('observe_trading',{'review':True,'platform':'freqtrade'})]
    assert admission('Explain why execution remains denied.')[1]==[('recall_trading_observations',{'review':True})]
    assert admission('Review MT5 execution conditions and send an order')[1]==[]


def test_mt5_cost_review_preserves_unknown_commission_without_order_calls(monkeypatch):
    import time
    from modules.trading_observation import mt5_execution_review,ReadOnlyMT5
    import modules.crypto_stops as stops
    monkeypatch.setattr(stops,'from_mt5',lambda api,symbol,info,q,side,strategy:
        {'stop_loss':100 if side=='buy' else 300,'take_profit':400 if side=='buy' else 50})
    account=SimpleNamespace(equity=10000,currency='USD',margin=0,margin_free=10000,trade_allowed=True)
    terminal=SimpleNamespace(trade_allowed=True,tradeapi_disabled=False)
    info=SimpleNamespace(volume_min=.01,volume_step=.01,trade_mode=4,point=.01,trade_stops_level=0,trade_freeze_level=0,
        currency_profit='USD',trade_contract_size=1)
    native=SimpleNamespace(ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,symbol_info=lambda s:info,
        order_calc_margin=lambda *a:100,order_calc_profit=lambda k,s,v,a,b:(b-a)*v*(1 if k==0 else -1),
        order_send=lambda *a:pytest.fail('No order may be submitted'))
    result={'symbol':'BTCUSDm','quote':{'ask':201,'bid':200,'timestamp':time.time(),'spread':1},
        'fresh':True,'positions':[],'strategy_comparison':{'signal':'HOLD','candidates':[]}}
    review=mt5_execution_review(SimpleNamespace(connect=lambda:(None,account,terminal)),ReadOnlyMT5(native),result)
    assert review['eligibility']=='BLOCKED'
    assert review['commission']=='UNKNOWN'
    assert all(s['net_cost_review']['costs_complete'] is False for s in review['scenarios'])
    assert any('consensus' in reason for reason in review['blockers'])
