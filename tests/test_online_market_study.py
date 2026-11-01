import json
import math
import sqlite3

import pytest
from modules.online_market_study import OnlineMarketStudy,choose,GATE


def bars(n):
    return [{'timestamp':300*(i+1),'close':100+i*.03+math.sin(i)*.001} for i in range(n)]


def test_forecast_precedes_label_and_is_immutable(tmp_path):
    engine=OnlineMarketStudy(tmp_path/'study.sqlite')
    data=bars(30)
    first=engine.observe('demo:EURUSD',data,market_time=data[-1]['timestamp']+301,fresh=True)
    assert first['settled']==0 and not first['execution_eligible']
    revised=[dict(r) for r in data];revised[-1]['close']+=2
    second=engine.observe('demo:EURUSD',revised,market_time=data[-1]['timestamp']+302,fresh=True)
    assert second['forecast']==first['forecast']
    updated=bars(31)
    third=engine.observe('demo:EURUSD',updated,market_time=updated[-1]['timestamp']+301,fresh=True)
    assert third['settled']==1
    with sqlite3.connect(engine.path) as db:
        outcome=json.loads(db.execute('SELECT payload FROM online_results').fetchone()[0])
    assert outcome['reference_close']==first['forecast']['reference_close']
    assert outcome['expected_return']==first['forecast']['expected_return']
    assert outcome['target_bar']>outcome['bar']
    assert engine.observe('live:EURUSD',updated,market_time=updated[-1]['timestamp']+301,fresh=True)['settled']==0


def test_sequential_adaptation_is_research_only(tmp_path):
    engine=OnlineMarketStudy(tmp_path/'study.sqlite')
    for n in range(25,71):
        data=bars(n);report=engine.observe('demo',data,market_time=data[-1]['timestamp']+301,fresh=True)
    assert report['settled']==45
    assert report['manager']['selected'] in {'momentum_5','momentum_20'}
    assert report['manager']['later_check_samples']>=12
    assert not report['forecast']['execution_eligible']
    assert report['decision_support']['action']=='observe_or_abstain'


def test_holdout_cannot_select_a_different_winner():
    rows=[{'predictions':{'zero':0,'momentum_5':.1,'momentum_20':.2,'reversion_5':-.1},'realized':.1} for _ in range(40)]
    assert choose(rows)['candidate']=='momentum_5'
    changed=[{**r,'realized':.2 if i>=28 else .1} for i,r in enumerate(rows)]
    assert choose(changed)['candidate']=='momentum_5'
    assert choose(rows[:39])['selected']=='zero'


def test_gap_staleness_nonfinite_and_no_queue(tmp_path):
    engine=OnlineMarketStudy(tmp_path/'study.sqlite');data=bars(30);clock=data[-1]['timestamp']+301
    assert engine.observe('demo',data,market_time=clock,fresh=False)['state']=='stale_or_unfinished'
    assert engine.observe('demo',data,market_time=clock+300,fresh=True)['state']=='stale_or_unfinished'
    broken=bars(30);broken[-1]['timestamp']+=300
    assert engine.observe('demo',broken,market_time=clock,fresh=True)['state']=='history_gap'
    data[-1]['close']=float('nan')
    with pytest.raises(ValueError):engine.observe('demo',data,market_time=clock,fresh=True)
    GATE.acquire()
    try:assert engine.observe('demo',bars(30),market_time=clock,fresh=True)=={'state':'busy','queued':False,'execution_eligible':False}
    finally:GATE.release()
