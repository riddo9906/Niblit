import pytest

from modules import strategy_manager


@pytest.mark.parametrize(('votes', 'expected', 'complete'), [
    (['sell', 'sell', 'wait', 'wait', 'wait', 'wait'], 'sell', True),
    (['wait', 'sell', 'wait', 'wait', 'wait', 'wait'], 'sell', True),
    (['buy', 'sell', 'wait', 'wait', 'wait', 'wait'], 'wait', True),
    (['wait'] * 6, 'wait', True),
    (['buy', 'invalid', 'wait', 'wait', 'wait', 'wait'], 'wait', False),
])
def test_established_policy(monkeypatch, votes, expected, complete):
    by_strategy = dict(zip(strategy_manager.STRATEGIES, votes))
    monkeypatch.setattr(strategy_manager, 'evaluate', lambda candles, strategy: {
        'strategy': strategy, 'side': by_strategy[strategy],
    })
    result = strategy_manager.assess([{'timestamp': 0}])
    assert result['side'] == expected
    assert result['assessment_complete'] == complete
    assert len(result['candidates']) == 6
