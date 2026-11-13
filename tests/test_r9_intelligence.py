from types import SimpleNamespace

from modules.mt5_bridge import summarize_completed
from modules.strategy_manager import assess_with_context
from modules.trading_session_adapters import mt5_trade_costs


def bars():
    return [
        {'time': 300 * (i+1), 'open': 100+i, 'high': 101+i,
         'low': 99+i, 'close': 100+i}
        for i in range(21)
    ]


def test_context_excludes_forming_and_future_bars():
    data = bars()
    data[-1].update(open=999, high=1000, low=998, close=999)
    result = summarize_completed(data, 'M5', 21*300)
    assert result['status'] == 'ready'
    assert result['trend'] == 'up'
    assert result['resistance'] == 120


def test_context_surfaces_gap_and_staleness():
    data = bars()
    assert summarize_completed(data[:5], 'M5', 21*300)['status'] == 'insufficient_closed_history'
    assert summarize_completed(data, 'M5', 30*300)['status'] == 'stale'
    data.pop(6)
    assert summarize_completed(data, 'M5', 22*300)['status'] == 'session_gap'


def test_context_does_not_create_votes_or_replace_consensus():
    baseline = assess_with_context([])
    enriched = assess_with_context([], {'H4': {'status':'ready','trend':'down'}})
    assert [(c['strategy'], c['side']) for c in enriched['candidates']] == [
        (c['strategy'], c['side']) for c in baseline['candidates']]
    assert enriched['side'] == baseline['side']
    assert enriched['candidates'][0]['context']['H4']['trend'] == 'down'


def test_broker_cost_evidence_preserves_unknowns_and_does_not_subtract_spread_twice():
    api = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
                          order_calc_profit=lambda order, symbol, lot, start, end: (end-start)*lot)
    costs = mt5_trade_costs(api, SimpleNamespace(currency='USD'), 'EURUSD', 'buy', 1,
                           {'price':102,'stop_loss':98,'take_profit':108}, {'bid':101,'ask':102})
    assert costs['spread_cost_estimate'] == 1
    assert costs['gross_at_target'] == 6
    assert costs['gross_at_stop'] == -4
    assert costs['net_at_target'] is None and costs['commission'] is None
    assert not costs['costs_complete'] and not costs['funded_eligible']
