from modules.position_exit_policy import assess_exit


def position(side=0):return {'type':side,'price_open':100.}
def quote(price,stamp=1000):return {'bid':price,'ask':price+.01,'fresh':True,'timestamp':stamp}
def context(strategy='breakout_v1'):return {'strategy':strategy,'initial_stop':99.,'breakout_level':100.2}
def bars(prices):return [{'timestamp':300*(i+1),'close':v} for i,v in enumerate(prices)]


def test_profit_giveback_requires_distinct_confirmations_and_cost_buffer():
    c=context()
    assert assess_exit(position(),[],quote(101.),c)['action']=='hold'
    assert assess_exit(position(),[],quote(100.6,1015),c)['action']=='hold'
    assert assess_exit(position(),[],quote(100.6,1015),c)['action']=='hold'
    result=assess_exit(position(),[],quote(100.6,1030),c)
    assert result['action']=='close' and 'Profit protection' in result['reason']
    assert result['prediction_use'].startswith('Advisory')


def test_failed_breakout_needs_two_closes_inside_saved_boundary():
    c=context()
    assert assess_exit(position(),bars([100.3]*50+[100.1]),quote(100.1),c)['action']=='hold'
    report=assess_exit(position(),bars([100.3]*49+[100.1,100.1]),quote(100.1),c)
    assert report['action']=='close' and 'failed breakout' in report['reason']


def test_unknown_old_position_stale_quote_and_invalid_stop_hold():
    assert assess_exit(position(),[],quote(100),None)['action']=='hold'
    q=quote(100);q['fresh']=False
    assert assess_exit(position(),[],q,context())['action']=='hold'
    c=context();c['initial_stop']=101
    assert assess_exit(position(),[],quote(100),c)['action']=='hold'


def test_short_profit_protection_is_symmetric():
    c=context();c['initial_stop']=101
    assess_exit(position(1),[],quote(98.99),c)
    assert assess_exit(position(1),[],quote(99.39,1015),c)['action']=='hold'
    assert assess_exit(position(1),[],quote(99.39,1030),c)['action']=='close'
