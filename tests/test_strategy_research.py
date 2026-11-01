import math

import pytest
from modules.demo_strategy import STRATEGIES,evaluate
from modules.strategy_research import study


def bars(prices):
    return [{'timestamp':300*(i+1),'open':v,'close':v,'high':v+.01,'low':v-.01} for i,v in enumerate(prices)]


@pytest.mark.parametrize('strategy',list(STRATEGIES))
def test_catalog_rules_are_explained_and_wait_for_history(strategy):
    report=evaluate(bars([100]*60),strategy)
    assert report['side']=='wait'
    assert report['references'] and report['hypothesis'] and report['validation']
    assert evaluate([],strategy)['side']=='wait'


@pytest.mark.parametrize('strategy',['rsi_reversion_v1','bollinger_reversion_v1'])
def test_reversion_requires_recovery_after_extreme(strategy):
    assert evaluate(bars([100]*58+[99,100]),strategy)['side']=='buy'
    assert evaluate(bars([100]*58+[101,100]),strategy)['side']=='sell'


def test_squeeze_requires_breakout_after_contraction():
    prices=[100+math.sin(i)*.5 for i in range(40)]+[100]*19+[102]
    assert evaluate(bars(prices),'squeeze_breakout_v1')['side']=='buy'
    prices[-1]=100
    assert evaluate(bars(prices),'squeeze_breakout_v1')['side']=='wait'


def test_predictor_has_validation_baseline_and_cannot_execute():
    rows=bars([100+i*.001+math.sin(i)*.03 for i in range(160)])
    report=study(rows)
    assert report['execution_eligible'] is False
    assert report['forecast']['walk_forward_samples']>20
    assert report['forecast']['zero_return_baseline_mae']>=0
    assert len(report['proposals'])==8
    assert all(p['execution_eligible'] is False for p in report['proposals'])
    assert all(t['max_training_label_index']<t['target_index'] for t in report['validation_trace'])


def test_future_prices_cannot_change_earlier_predictions_or_training_selection():
    rows=bars([100+i*.001+math.sin(i)*.03 for i in range(160)])
    old=study(rows)
    changed=bars([r['close'] if i<120 else r['close']+5 for i,r in enumerate(rows)])
    new=study(changed)
    earlier={t['feature_index']:t['predicted_return'] for t in old['validation_trace'] if t['feature_index']<120}
    newer={t['feature_index']:t['predicted_return'] for t in new['validation_trace'] if t['feature_index']<120}
    assert earlier==newer
    # Split is index 112; all modifications begin strictly in the holdout.
    assert [p['id'] for p in old['proposals']]==[p['id'] for p in new['proposals']]
    assert [p['training'] for p in old['proposals']]==[p['training'] for p in new['proposals']]


def test_data_quality_and_no_proposals_when_not_waiting():
    assert study(bars([100]*60))['state']=='insufficient_history'
    rows=bars([100+math.sin(i)*.01 for i in range(160)])
    assert not study(rows,generate=False)['proposals']
    rows[-1]['timestamp']+=300
    assert study(rows)['state']=='history_gap'
    with pytest.raises(ValueError): study(bars([100]*160),spread_fraction=float('nan'))
