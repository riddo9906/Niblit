import json
import time
from types import SimpleNamespace as Obj
from unittest.mock import Mock

import pytest
from modules.demo_strategy import evaluate, position_volume, risk_budget
from modules.demo_autotrader import DemoAutotrader


def candles(up=True):
    return [dict(timestamp=300*(i+1),open=100+i if up else 200-i,
                 high=101+i if up else 201-i, low=99+i if up else 199-i,
                 close=100.5+i if up else 199.5-i) for i in range(60)]


@pytest.mark.parametrize('strategy',['trend_v1','breakout_v1'])
def test_both_directions_and_insufficient_history(strategy):
    assert evaluate(candles(),strategy)['side']=='buy'
    assert evaluate(candles(False),strategy)['side']=='sell'
    assert evaluate([],strategy)['side']=='wait'
    bad=candles();bad[-1]['timestamp']+=300
    assert evaluate(bad,strategy)['side']=='wait'


def test_risk_scales_down_and_never_rounds_up():
    assert risk_budget(100)==.25
    assert risk_budget(100000)==25
    assert position_volume(100,2,.01,.01) is None
    assert position_volume(1000,10,.001,.001)==.002
    assert position_volume(100000,2,.001,.001)==.01
    with pytest.raises(ValueError): risk_budget(float('nan'))


@pytest.fixture
def bot(tmp_path):
    s=dict(account=dict(mode='demo',identity='a',equity=1000,currency='USD'),
           capabilities={'order_submission':True},positions=[],pending_order_count=0,
           candles=candles(),quote={'fresh':True,'timestamp':18305,'bid':159.9999,'ask':160})
    api=Mock()
    api.account_info.return_value=Obj()
    api.history_deals_get.return_value=[]
    api.symbol_info.return_value=Obj(point=.00001,trade_stops_level=10,digits=5,volume_min=.01,volume_step=.01)
    api.order_calc_profit.return_value=-2
    bridge=Mock()
    bridge.snapshot.return_value=s
    bridge.connect.return_value=(api,Obj(),Obj())
    bridge.identity.return_value='a'
    orders=Mock()
    orders.preview.return_value={'ticket':'t','review':{'estimated_stop_risk':2}}
    orders.confirm.return_value={'state':'filled','result':{'order':44}}
    orders.inspect.return_value={'estimated_stop_risk':2}
    b=DemoAutotrader(bridge,orders,tmp_path/'demo.sqlite3')
    b.session=dict(id='s',symbol='EURUSD',strategy='trend_v1',account='a',initial_equity=1000,
                   peak_equity=1000,until=time.time()+600,max_entries=3,entries=0,last_bar=None,state='running')
    return b


def test_one_delivery_per_bar_and_durable_reason(bot):
    bot.step();bot.step()
    bot.orders.confirm.assert_called_once_with('t')
    assert bot.session['entries']==1
    decisions=bot.status()['decisions']
    assert any(d.get('evidence',{}).get('mean20') for d in decisions)
    assert any(d.get('ticket')=='t' for d in decisions)


@pytest.mark.parametrize('condition',['live','changed','stale','loss','limit','risk','expiry'])
def test_fail_closed(bot,condition):
    s=bot.bridge.snapshot.return_value
    if condition=='live': s['account']['mode']='live_read_only'
    if condition=='changed': s['account']['identity']='b'
    if condition=='stale': s['quote']['fresh']=False
    if condition=='loss': s['account']['equity']=979
    if condition=='limit': bot.session['entries']=3
    if condition=='risk': bot.bridge.connect.return_value[0].order_calc_profit.return_value=-200
    if condition=='expiry': bot.session['until']=0
    try: bot.step()
    except ValueError: pass
    bot.orders.confirm.assert_not_called()


def test_unknown_delivery_is_not_retried(bot):
    bot.orders.confirm.return_value={'state':'unknown','result':{}}
    with pytest.raises(ValueError,match='Unresolved'): bot.step()
    bot.step()
    bot.orders.confirm.assert_called_once()


def test_opposite_signal_closes_owned_position_only(bot):
    bot.bridge.snapshot.return_value['positions']=[dict(ticket=99,magic=29102026,symbol='EURUSD',type=1,volume=.01)]
    bot.orders.preview.return_value['review']['estimated_stop_risk']=None
    bot.step()
    assert bot.orders.preview.call_args.args[0]['action']=='close'
    assert bot.orders.preview.call_args.args[0]['position_ticket']==99


def test_outcome_is_linked_net_of_all_costs_and_idempotent(bot):
    bot.step()
    api=bot.bridge.connect.return_value[0]
    api.history_deals_get.return_value=[
        Obj(magic=29102026,position_id=44,order=44,entry=0,profit=0,commission=-1,swap=0,fee=0),
        Obj(magic=29102026,position_id=44,order=45,entry=1,profit=10,commission=-1,swap=-.5,fee=-.2)]
    bot.outcomes(bot.bridge.snapshot.return_value)
    bot.outcomes(bot.bridge.snapshot.return_value)
    assert len(bot.status()['outcomes'])==1
    assert bot.status()['outcomes'][0]['net']==pytest.approx(7.3)
    assert bot.status()['outcomes'][0]['strategy']=='trend_v1'


def test_restart_does_not_rearm(bot):
    replacement=DemoAutotrader(bot.bridge,bot.orders,bot.path)
    assert replacement.status()['running'] is False
    assert replacement.session is None


def test_prediction_is_saved_then_scored_only_when_next_bar_completes(bot):
    import math
    rows=[dict(timestamp=(i+1)*300,open=100+math.sin(i)*.01,close=100+math.sin(i)*.01,
               high=101,low=99) for i in range(160)]
    s=bot.bridge.snapshot.return_value
    s['candles']=rows;s['quote']['timestamp']=rows[-1]['timestamp']+305
    bot.session['until']=0
    bot.step()
    assert bot.status()['forecast_outcomes']==[]
    rows.append(dict(timestamp=48300,open=100,close=100.01,high=101,low=99))
    s['quote']['timestamp']=48605
    bot.step();bot.step()
    outcomes=bot.status()['forecast_outcomes']
    assert len(outcomes)==1
    assert outcomes[0]['target_bar']==48300
    bot.orders.confirm.assert_not_called()


def test_expiry_observes_all_rules_and_never_sends(bot):
    bot.session['until']=0
    bot.session['strategy']='auto'
    bot.step()
    assert bot.session['state']=='observing'
    from modules.demo_strategy import STRATEGIES
    assert len(bot.manager['candidates'])==len(STRATEGIES)
    bot.orders.confirm.assert_not_called()
    with bot.db() as db:
        assert db.execute('SELECT count(*) FROM opportunities').fetchone()[0]==1
    bot.step()
    with bot.db() as db:
        assert db.execute('SELECT count(*) FROM opportunities').fetchone()[0]==1


def test_alert_requires_broker_preflight_and_fresh_data(bot):
    bot.session['until']=0
    bot.orders.inspect.side_effect=ValueError('Insufficient margin')
    bot.step()
    assert 'Insufficient margin' in bot.manager['risk_checks']['broker_size_margin_stop']
    with bot.db() as db: assert db.execute('SELECT count(*) FROM opportunities').fetchone()[0]==0
    bot.orders.confirm.assert_not_called()


def test_auto_selector_pins_entry_rule_for_exit(bot):
    bot.session['strategy']='auto'
    bot.step()
    assert bot.session['held_strategy']=='breakout_v1'
    bot.bridge.snapshot.return_value['positions']=[dict(ticket=44,magic=29102026,symbol='EURUSD',type=0,volume=.01)]
    bot.session['last_bar']=None
    bot.step()
    assert bot.manager['strategy']=='breakout_v1'
    assert 'retains' in bot.manager['selection_reason']


def test_start_rejects_live_account_and_existing_exposure(bot):
    bot.bridge.snapshot.return_value['account']['mode']='live_read_only'
    with pytest.raises(ValueError,match='demo'): bot.start('EURUSD','trend_v1')
    bot.bridge.snapshot.return_value['account']['mode']='demo'
    bot.bridge.snapshot.return_value['positions']=[{'ticket':1}]
    with pytest.raises(ValueError,match='no positions'): bot.start('EURUSD','trend_v1')
    bot.orders.confirm.assert_not_called()


def test_stop_before_delivery_and_excess_spread(bot):
    bot.stop()
    bot.step()
    bot.orders.confirm.assert_not_called()
    bot.stop_event.clear();bot.session['last_bar']=None
    bot.bridge.snapshot.return_value['quote']['bid']=159
    bot.step()
    bot.orders.confirm.assert_not_called()


def test_demo_routes_need_same_origin_token(bot, tmp_path):
    from fastapi.testclient import TestClient
    from modules.trading_desk import create_app, Desk
    app=create_app(Desk(tmp_path,transport=Mock()),mt5=bot.bridge)
    with TestClient(app) as client:
        assert client.get('/api/demo/status').json()['running'] is False
        assert client.post('/api/demo/start',json={}).status_code==403
        assert client.post('/api/demo/stop',json={}).status_code==403
        import re
        token=re.search(r'name="desk-token" content="([^"]+)"',client.get('/').text)[1]
        headers={'origin':'http://127.0.0.1:8767','x-desk-token':token}
        assert client.post('/api/demo/stop',json={},headers=headers).status_code==200
        body=dict(symbol='EURUSD',strategy='trend_v1',minutes=1,max_entries=1,
                  acknowledgement='START_BOUNDED_MT5_DEMO')
        bot.bridge.snapshot.return_value['account']['mode']='live_read_only'
        assert client.post('/api/demo/start',json=body,headers=headers).status_code==409


def test_observation_can_resume_with_existing_exposure_without_order_authority(bot,monkeypatch):
    monkeypatch.setattr('modules.demo_autotrader.threading.Thread.start',lambda self:None)
    snapshot=bot.bridge.snapshot.return_value
    snapshot['positions']=[dict(ticket=99,magic=29102026,symbol='EURUSD',type=0,volume=.01)]
    snapshot['capabilities']['order_submission']=False
    bot.start('EURUSD','auto',observe_only=True)
    bot.step()
    assert bot.session['state']=='observing'
    bot.orders.preview.assert_not_called()
    bot.orders.confirm.assert_not_called()
    with pytest.raises(ValueError):bot.start('EURUSD','auto',observe_only=False)


def test_adaptive_profit_exit_runs_between_bars_once_and_observation_never_closes(bot):
    snapshot=bot.bridge.snapshot.return_value
    snapshot['positions']=[dict(ticket=99,magic=29102026,symbol='EURUSD',type=0,volume=.01,price_open=160.)]
    bot.session['held_strategy']='trend_v1'
    bot.session['exit_context']={'strategy':'trend_v1','initial_stop':159.,'peak_price_gain':1.,'giveback_checks':0}
    bot.session['last_bar']=snapshot['candles'][-1]['timestamp']
    snapshot['quote'].update(bid=160.6,ask=160.61,timestamp=18305)
    bot.step()
    bot.orders.confirm.assert_not_called()
    snapshot['quote']['timestamp']=18320
    bot.step()
    assert bot.orders.preview.call_args.args[0]['action']=='close'
    assert bot.orders.preview.call_args.args[0]['position_ticket']==99
    assert bot.orders.confirm.call_count==1
    snapshot['quote']['timestamp']=18335
    bot.step()
    assert bot.orders.confirm.call_count==1
    bot.session['exit_sent']=None;bot.session['state']='observing'
    snapshot['quote']['timestamp']=18350
    bot.step()
    assert bot.orders.confirm.call_count==1
