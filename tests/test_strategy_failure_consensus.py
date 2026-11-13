
from unittest.mock import patch

import pytest
from modules.strategy_manager import assess


def signal(name, side):
    return {'strategy':name,'side':side,'reason':'fixture','bar':300,'evidence':{}}


@pytest.mark.parametrize('selection',['auto','trend_v1'])
def test_failed_rule_cannot_silently_allow_a_direction(selection):
    rules={'trend_v1':'trend','breakout_v1':'breakout','ema_pullback_v1':'pullback'}
    with patch('modules.strategy_manager.STRATEGIES',rules), patch(
            'modules.strategy_manager.evaluate',
            side_effect=[signal('trend_v1','buy'),RuntimeError('private failure details'),signal('ema_pullback_v1','buy')]) as evaluate:
        result=assess([],requested=selection)
    assert evaluate.call_count==3
    assert result['side']=='wait'
    assert result['assessment_complete'] is False
    assert result['strategy_failures']==[{'strategy':'breakout_v1','error_type':'RuntimeError'}]
    assert result['candidates'][1]['status']=='failed'
    assert 'private failure details' not in str(result)


@pytest.mark.parametrize('malformed',[None,{'strategy':'trend_v1','side':'buy'},
    {'strategy':'breakout_v1','side':'BUY'}])
def test_malformed_strategy_result_is_an_explicit_comparison_failure(malformed):
    with patch('modules.strategy_manager.STRATEGIES',{'trend_v1':'','breakout_v1':''}), patch(
            'modules.strategy_manager.evaluate',side_effect=[signal('trend_v1','buy'),malformed]):
        result=assess([])
    assert result['side']=='wait'
    assert result['strategy_failures'][0]['error_type']=='ValueError'


def test_missing_position_owner_does_not_transfer_to_an_eligible_strategy():
    with patch('modules.strategy_manager.STRATEGIES',{'trend_v1':''}), patch(
            'modules.strategy_manager.evaluate',return_value=signal('trend_v1','buy')):
        result=assess([],held_strategy='retired_rule')
    assert result['side']=='wait'
    assert result['assessment_complete'] is False
    assert 'ownership' in result['selection_reason']


def test_real_rules_report_successful_comparison_without_claiming_profit():
    rows=[{'timestamp':(i+1)*300,'open':100+i,'close':100+i,
           'high':100+i+.1,'low':100+i-.1} for i in range(60)]
    result=assess(rows)
    assert result['assessment_complete'] is True
    assert result['strategy_failures']==[]
    assert result['side']=='buy'
    assert len(result['candidates'])==6
    assert 'profit' in result['selection_limit']


def test_failed_comparison_keeps_demo_observer_alive_and_never_submits(tmp_path):
    import time
    from types import SimpleNamespace
    from unittest.mock import Mock
    from modules.demo_autotrader import DemoAutotrader
    from modules.demo_strategy import evaluate as real_evaluate
    rows=[{'timestamp':(i+1)*300,'open':100+i,'close':100+i,
           'high':100+i+.1,'low':100+i-.1} for i in range(60)]
    bridge=Mock()
    bridge.snapshot.return_value={
        'account':{'mode':'demo','identity':'fixture','equity':1000,'currency':'USD'},
        'positions':[],'pending_order_count':0,'candles':rows,
        'quote':{'fresh':True,'timestamp':18305,'bid':159.9999,'ask':160}}
    api=Mock()
    api.history_deals_get.return_value=[]
    bridge.connect.return_value=(api,SimpleNamespace(),None)
    bridge.identity.return_value='fixture'
    orders=Mock()
    bot=DemoAutotrader(bridge,orders,tmp_path/'demo.sqlite3')
    bot.session=dict(id='fixture',symbol='EURUSD',strategy='auto',account='fixture',
        initial_equity=1000,peak_equity=1000,until=time.time()+60,max_entries=1,
        entries=0,last_bar=None,state='running')
    def partly_unavailable(candles,name):
        if name=='breakout_v1':
            raise RuntimeError('fixture failure')
        return real_evaluate(candles,name)
    with patch('modules.strategy_manager.evaluate',side_effect=partly_unavailable):
        bot.step()
        bot.step()
    assert bot.manager['side']=='wait'
    assert bot.manager['assessment_complete'] is False
    assert bot.session['state']=='running'
    orders.preview.assert_not_called()
    orders.confirm.assert_not_called()
    with bot.db() as db:
        rows=db.execute('SELECT payload FROM decisions').fetchall()
    assert any('strategy_failures' in row[0] for row in rows)


