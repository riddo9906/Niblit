import json
import subprocess
import sys
from types import SimpleNamespace
import pytest
from modules.market_prediction import PredictionLedger, forecast, metrics, walk_forward
from modules.runtime_lifecycle import event
from test_phase6_cognitive_observation import memory


def observation(now=2110,terminal='desktop'):
    bars=[{'timestamp':i*300,'close':100+i} for i in range(7)]
    return {'fresh':True,'utc_clock_verified':True,'received_at':now,'symbol':'BTCUSDm',
            'account':{'identity':'demo','terminal_id':terminal,'server':'trial','environment':'demo'},
            'evidence':{'M5':{'source':{'adapter':terminal},'snapshot_id':'snapshot-'+terminal,'data_quality':{}}},
            'prediction_inputs':{'candles':bars},'quote':{'spread':.1},'strategy_comparison':{'side':'wait'}}


def test_forecast_identity_horizons_no_fabricated_probability():
    r=observation();p=forecast(r,900,2110)
    assert p['expires_at']==3000 and p['direction']=='up' and p['probability'] is None
    assert not p['execution_authorized'] and 'UNCALIBRATED' in p['calibration_status']
    assert p['id']==forecast(r,900,2120)['id']
    assert p['id']!=forecast(observation(terminal='vps'),900,2110)['id']


@pytest.mark.parametrize('change',[{'fresh':False},{'utc_clock_verified':False}])
def test_data_quality_blocks_prediction(change):
    assert forecast({**observation(),**change},300,2110) is None


def test_future_and_expired_anchor_rejected():
    assert forecast(observation(),300,2099) is None
    assert forecast(observation(),300,2200) is None
    with pytest.raises(ValueError):forecast(observation(),60,2110)


def test_canonical_restart_outcome_idempotence_and_unknown_costs(tmp_path):
    m=memory(tmp_path);ledger=PredictionLedger(m);job=SimpleNamespace(source='desktop',account='demo',terminal='desktop',symbol='BTCUSDm')
    ledger.observe(job,observation());ledger.observe(job,observation(2120))
    assert len(ledger.status(2120)['recent'])==3
    later=observation(2410);later['prediction_inputs']['candles'].append({'timestamp':2100,'close':110})
    later['evidence']['M5']['snapshot_id']='next-snapshot'
    PredictionLedger(m).observe(job,later);PredictionLedger(m).observe(job,later)
    with m.gateway.db() as db:
        rows=db.execute('SELECT outcome,outcome_episode FROM market_predictions_v1 WHERE outcome IS NOT NULL').fetchall()
    assert len(rows)==1 and rows[0][1]
    value=json.loads(rows[0][0]);assert value['correct'] and value['net_outcome'] is None
    assert value['outcome_kind']=='hypothetical_not_executed'


def test_missing_target_history_not_invented(tmp_path):
    m=memory(tmp_path);ledger=PredictionLedger(m);job=SimpleNamespace(source='desktop',account='demo',terminal='desktop',symbol='BTCUSDm')
    ledger.observe(job,observation());ledger.observe(job,observation(4000))
    assert all(p['evaluation'] is None for p in ledger.status(4000)['recent'])


def test_metrics_sample_intervals_and_probability_validation():
    assert metrics([])['directional_accuracy'] is None
    assert metrics([{'correct':True,'probability':None}])['brier_score'] is None
    score=metrics([{'correct':True,'probability':.8,'actual_up':1}])
    assert score['brier_score']==pytest.approx(.04)
    assert score['accuracy_95pct_interval'][0]<1
    with pytest.raises(ValueError):metrics([{'correct':True,'probability':1,'actual_up':1}])


def test_walk_forward_purge_reproducible_future_mutation():
    bars=[{'timestamp':i*300,'close':100+i%9} for i in range(100)]
    report=walk_forward(bars)
    assert report==walk_forward(bars)
    assert all(f['train_last_target']<f['test_first_prediction'] for f in report['folds'])
    changed=[dict(b) for b in bars];changed[-1]['close']=10000
    assert report['folds'][0]==walk_forward(changed)['folds'][0]
    assert report['net_profit'] is None and report['cost_status']=='UNKNOWN'
    assert not report['promotion_authorized']


def test_replay_rejects_gaps():
    with pytest.raises(ValueError):walk_forward([{'timestamp':0,'close':100},{'timestamp':900,'close':101}])


def test_lifecycle_records_owner_without_sensitive_fields(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_RUNTIME_LOG_FILE',str(tmp_path/'runtime.jsonl'))
    event('test',child_pid=123,reason='normal',password='never-record')
    value=json.loads((tmp_path/'process-lifecycle.jsonl').read_text())
    assert value['pid']>0 and value['child_pid']==123 and 'password' not in value


@pytest.mark.parametrize('exit_code',[0,7])
def test_real_child_exit_diagnostics(exit_code,tmp_path,monkeypatch):
    from modules.niblit_ui_launcher import UiLaunchResult
    monkeypatch.setenv('NIBLIT_RUNTIME_LOG_FILE',str(tmp_path/'runtime.jsonl'))
    child=subprocess.Popen([sys.executable,'-c',f'raise SystemExit({exit_code})'])
    result=UiLaunchResult(success=True,_ui_process=child)
    assert result.wait()==exit_code
    entries=[json.loads(line) for line in (tmp_path/'process-lifecycle.jsonl').read_text().splitlines()]
    assert any(e['event']=='ui_process_exited' and e['exit_code']==exit_code for e in entries)


def test_attached_child_wait_observes_core_shutdown_without_child_exit(tmp_path,monkeypatch):
    import threading
    from modules.niblit_ui_launcher import UiLaunchResult
    monkeypatch.setenv('NIBLIT_RUNTIME_LOG_FILE',str(tmp_path/'runtime.jsonl'))
    stop=threading.Event()
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    result=UiLaunchResult(success=True,_ui_process=child,_shutdown_event=stop)
    returned=[];thread=threading.Thread(target=lambda:returned.append(result.wait()))
    thread.start();stop.set();thread.join(timeout=4)
    try:
        assert not thread.is_alive() and returned==[0] and child.poll() is not None
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)

