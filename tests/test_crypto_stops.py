"""Deterministic protection tests, no MT5 process or broker commands."""
import copy,math
import pytest
from modules.crypto_stops import levels,fixed_levels,policy,RULES


def inputs():
    end=1800000000
    rows=[dict(time=end-(63-i)*300,open=75000.,high=75010.,low=74990.,close=75000.) for i in range(64)]
    spec=dict(point=.01,trade_tick_size=.25,trade_stops_level=0,trade_freeze_level=0,digits=2,
              currency_base='BTC',currency_profit='USD',trade_mode=4)
    quote=dict(bid=75000.,ask=75006.4,timestamp=end+310)
    return rows,spec,quote


@pytest.mark.parametrize('strategy',list(RULES))
@pytest.mark.parametrize('side',['buy','sell'])
def test_stops_are_outside_spread_and_volatility_with_grid_and_two_r(side,strategy):
    rows,spec,q=inputs();p=levels(rows,spec,q,side,strategy)
    assert p['atr']==20 and p['stop_modifications_enabled'] is False
    assert p['stop_distance']>=p['atr_multiple']*20
    if side=='buy':assert p['stop_loss']<q['bid']-3*(q['ask']-q['bid']) and p['take_profit']>q['ask']
    else:assert p['stop_loss']>q['ask']+3*(q['ask']-q['bid']) and p['take_profit']<q['bid']
    assert p['gross_reward_multiple']>=2
    assert abs(p['stop_loss']/.25-round(p['stop_loss']/.25))<1e-7


def test_structure_not_just_atr_defines_invalidation():
    rows,spec,q=inputs();rows[-3]['low']=74850.
    p=levels(rows,spec,q,'buy','trend_v1')
    assert p['stop_loss']<74850 and p['structure_anchor']==74850


def test_broker_stop_and_freeze_constraints_are_respected():
    rows,spec,q=inputs();spec.update(trade_stops_level=10000,trade_freeze_level=15000)
    assert q['bid']-levels(rows,spec,q,'buy')['stop_loss']>=150
    assert levels(rows,spec,q,'sell')['stop_loss']-q['ask']>=150


@pytest.mark.parametrize('case',['missing','forming','future','stale','gap','bad_ohlc','nan','unknown_tick','disabled'])
def test_unverified_history_or_contract_never_falls_back_to_fixed_points(case):
    rows,spec,q=inputs()
    if case=='missing':rows=None
    elif case=='forming':q['timestamp']=rows[-1]['time']+100
    elif case=='future':rows[-1]['time']+=600
    elif case=='stale':q['timestamp']+=1000
    elif case=='gap':rows[-5]['time']-=300
    elif case=='bad_ohlc':rows[-1]['low']=75020
    elif case=='nan':rows[-1]['high']=float('nan')
    elif case=='unknown_tick':spec['trade_tick_size']=None
    elif case=='disabled':spec['trade_mode']=0
    with pytest.raises((ValueError,TypeError)):levels(rows,spec,q,'buy')


def test_confirmation_keeps_reviewed_sl_and_tp_unchanged():
    rows,spec,q=inputs();p=levels(rows,spec,q,'buy')
    current=q|{'bid':75000.25,'ask':75006.65}
    confirmed=fixed_levels(p,spec,current,'buy')
    assert confirmed['stop_loss']==p['stop_loss'] and confirmed['take_profit']==p['take_profit']


def test_crossed_reviewed_stop_or_widening_spread_requires_new_review():
    rows,spec,q=inputs();p=levels(rows,spec,q,'buy')
    with pytest.raises(ValueError):fixed_levels(p,spec,q|{'bid':p['stop_loss']-1,'ask':p['stop_loss']+5},'buy')
    with pytest.raises(ValueError):fixed_levels(p,spec,q|{'ask':75100},'buy')


def test_huge_structural_stop_is_rejected_not_clamped():
    rows,spec,q=inputs()
    for r in rows:r.update(high=79000.,low=71000.)
    with pytest.raises(ValueError,match='no tighter fallback'):levels(rows,spec,q,'buy')
