from unittest.mock import patch
from modules.strategy_manager import assess

def result(name,side):
    return {'strategy':name,'side':side,'reason':'test','bar':300,'evidence':{}}

def test_switches_to_only_eligible_rule():
    with patch('modules.strategy_manager.STRATEGIES',{'trend_v1':'','breakout_v1':''}), patch('modules.strategy_manager.evaluate',side_effect=[result('trend_v1','wait'),result('breakout_v1','buy')]):
        assert assess([])['strategy']=='breakout_v1'

def test_conflicting_rules_abstain():
    with patch('modules.strategy_manager.STRATEGIES',{'trend_v1':'','breakout_v1':''}), patch('modules.strategy_manager.evaluate',side_effect=[result('trend_v1','sell'),result('breakout_v1','buy')]):
        assert assess([])['side']=='wait'

def test_pinned_rule_does_not_chase_alternative():
    with patch('modules.strategy_manager.STRATEGIES',{'trend_v1':'','breakout_v1':''}), patch('modules.strategy_manager.evaluate',side_effect=[result('trend_v1','wait'),result('breakout_v1','buy')]):
        assert assess([],requested='trend_v1')['side']=='wait'


def test_agreeing_non_breakout_rules_are_not_called_a_breakout():
    rules={'trend_v1':'','ema_pullback_v1':''}
    with patch('modules.strategy_manager.STRATEGIES',rules), patch('modules.strategy_manager.evaluate',side_effect=[result('trend_v1','buy'),result('ema_pullback_v1','buy')]):
        d=assess([])
        assert d['strategy']=='trend_v1'
        assert 'breakout' not in d['selection_reason']
        assert 'ema_pullback_v1' in d['selection_reason']
