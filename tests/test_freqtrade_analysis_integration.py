
"""Real strategy/research integration with isolated data and no broker writes."""
import json
import sqlite3
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from modules.demo_strategy import STRATEGIES
from modules.freqtrade_research import FreqtradeResearch
from modules.trading_desk import create_app


@pytest.fixture
def research_desk(tmp_path):
    desk=Mock()
    desk.path=tmp_path/'orders.sqlite3'
    desk.configuration.return_value={'strategy':'NiblitLabManager','dry_run':True,
        'exchange':'fixture-exchange','state':'stopped'}
    desk.api.return_value={'whitelist':['BTC/USDT','ETH/USDT']}
    # Rising completed M5 bars activate real trend and breakout rules.
    rows=[]
    for i in range(160):
        price=100+i*.1
        rows.append(dict(timestamp=(i+1)*300,open=price,close=price,high=price+.01,low=price-.01))
    desk.market.return_value={'fresh':True,'candles':rows}
    return desk


@pytest.mark.parametrize('freshness',[False,None,'true'])
def test_stale_or_unverified_data_abstains_despite_real_direction(research_desk,freshness):
    lab=FreqtradeResearch(research_desk)
    fresh=lab.snapshot('BTC/USDT')
    assert fresh['manager']['side']=='buy'
    assert {c['strategy'] for c in fresh['manager']['candidates']}==set(STRATEGIES)
    # Same bar/config has a cached research report. It must not mask staleness.
    research_desk.market.return_value['fresh']=freshness
    stale=lab.snapshot('BTC/USDT')
    assert stale['manager']['side']=='wait'
    assert stale['manager']['abstain_reason']=='stale_market'
    assert any(c['side']=='buy' for c in stale['manager']['candidates'])
    assert stale['research']['state']=='stale_market'
    assert stale['research']['execution_eligible'] is False
    assert stale['execution_active'] is False
    assert fresh['analysis_memory']['id']!=stale['analysis_memory']['id']
    research_desk.market.return_value['fresh']=True
    assert lab.snapshot('BTC/USDT')['manager']['side']=='buy'


def test_missing_freshness_is_not_an_actionable_signal(research_desk):
    del research_desk.market.return_value['fresh']
    report=FreqtradeResearch(research_desk).snapshot('BTC/USDT')
    assert report['manager']['side']=='wait'


def test_decision_is_durable_idempotent_and_recalled_after_restart(research_desk):
    lab=FreqtradeResearch(research_desk)
    report=lab.snapshot('BTC/USDT')
    identity=report['analysis_memory']['id']
    assert lab.snapshot('BTC/USDT')['analysis_memory']['id']==identity
    restarted=FreqtradeResearch(research_desk)
    assert restarted.recall_analysis(identity)==report['manager']
    assert restarted.recall_analysis('absent') is None
    with sqlite3.connect(lab.path) as db:
        assert db.execute('SELECT count(*) FROM analysis_decisions').fetchone()[0]==1
    research_desk.market.return_value['fresh']=False
    stale=restarted.snapshot('BTC/USDT')
    assert FreqtradeResearch(research_desk).recall_analysis(stale['analysis_memory']['id'])['side']=='wait'
    assert all(c.args==('whitelist',) for c in research_desk.api.call_args_list)


def test_outcomes_do_not_cross_pair_venue_or_execution_mode(research_desk):
    lab=FreqtradeResearch(research_desk)
    namespace={'symbol':'BTC/USDT','venue':'fixture-exchange','mode':'dry-run-research'}
    payloads=[dict(namespace,tag='match'),
              dict(namespace,symbol='ETH/USDT',tag='other-pair'),
              dict(namespace,venue='other-exchange',tag='other-venue'),
              dict(namespace,mode='live-read-only-research',tag='other-mode'),
              {'symbol':'BTC/USDT','mode':'dry-run-research','tag':'legacy-no-venue'}]
    with sqlite3.connect(lab.path) as db:
        for i,payload in enumerate(payloads):
            db.execute('INSERT INTO forecast_outcomes VALUES(?,?)',(str(i),json.dumps(payload)))
    assert [r['tag'] for r in lab.snapshot('BTC/USDT')['forecast_outcomes']]==['match']
    assert [r['tag'] for r in lab.snapshot('ETH/USDT')['forecast_outcomes']]==['other-pair']
    research_desk.configuration.return_value['exchange']='other-exchange'
    assert [r['tag'] for r in lab.snapshot('BTC/USDT')['forecast_outcomes']]==['other-venue']
    research_desk.configuration.return_value.update(exchange='fixture-exchange',dry_run=False)
    assert [r['tag'] for r in lab.snapshot('BTC/USDT')['forecast_outcomes']]==['other-mode']


def test_actual_http_route_returns_stale_abstention_and_durable_receipt(research_desk):
    research_desk.market.return_value['fresh']=False
    with TestClient(create_app(research_desk)) as client:
        response=client.get('/api/freqtrade/research',params={'pair':'BTC/USDT'})
    assert response.status_code==200
    body=response.json()
    assert body['manager']['side']=='wait'
    assert len(body['manager']['candidates'])==6
    assert body['analysis_memory']['saved'] is True
    assert FreqtradeResearch(research_desk).recall_analysis(body['analysis_memory']['id'])==body['manager']
    assert all(c.args==('whitelist',) for c in research_desk.api.call_args_list)


def test_http_write_failure_is_unavailable_not_false_memory_success(research_desk):
    app=create_app(research_desk)
    with TestClient(app) as client, patch('modules.freqtrade_research.sqlite3.connect',
            side_effect=sqlite3.OperationalError('fixture disk unavailable')):
        response=client.get('/api/freqtrade/research',params={'pair':'BTC/USDT'})
    assert response.status_code==503
    assert 'no order was sent' in response.json()['detail']
    assert all(c.args==('whitelist',) for c in research_desk.api.call_args_list)

