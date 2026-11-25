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


def test_order_reversal_evaluator_exits_profitable_short_after_distinct_bars():
    from modules.position_exit_policy import assess_reversal
    closes=[120-i*.48 for i in range(48)]+[96,96.5,97.3,98.4,99.2]
    rows=[{'timestamp':(i+1)*300,'close':close} for i,close in enumerate(closes)]
    info={'strategy':'trend_v1','initial_stop':110.,'peak_price_gain':15.}
    short={'type':1,'price_open':105.}
    q={'bid':99.,'ask':99.1,'fresh':True,'timestamp':16000}
    first=assess_reversal(short,rows[:-1],q,info,observed_profit=3.)
    assert first['action']=='hold'
    assert first['evidence']['score']>=2
    assert first['evidence']['confirmed_bars']==1
    duplicate=assess_reversal(short,rows[:-1],q,info,observed_profit=3.)
    assert duplicate['action']=='hold'
    assert duplicate['evidence']['confirmed_bars']==1
    next_bar=assess_reversal(short,rows,q,info,observed_profit=3.)
    assert next_bar['action']=='close'
    assert next_bar['execution_eligible'] is True
    assert next_bar['evidence']['current_r']>0
    assert next_bar['evidence']['confirmed_bars']==2
    assert info['reversal_last_bar']==15900


def test_reversal_evaluator_keeps_trade_when_not_profitable_or_no_retracement():
    from modules.position_exit_policy import assess_reversal
    closes=[120-i*.48 for i in range(48)]+[96,96.5,97.3,98.4,99.2]
    rows=[{'timestamp':(i+1)*300,'close':close} for i,close in enumerate(closes)]
    q={'bid':99.,'ask':99.1,'fresh':True,'timestamp':16000}
    short={'type':1,'price_open':105.}
    def context(peak):return {'strategy':'trend_v1','initial_stop':110.,'peak_price_gain':peak}
    assert assess_reversal(short,rows,q,context(15),observed_profit=-1)['action']=='hold'
    assert assess_reversal(short,rows,q,context(6),observed_profit=3)['action']=='hold'
    assert assess_reversal(short,rows,{**q,'fresh':False},context(15),observed_profit=3)['action']=='hold'
    assert assess_reversal(short,rows[:-1]+[rows[-1]],q,None,observed_profit=3)['action']=='hold'


def test_reversal_evaluator_cannot_count_old_candles_as_confirmations():
    from modules.position_exit_policy import assess_reversal
    closes=[120-i*.48 for i in range(48)]+[96,96.5,97.3,98.4,99.2]
    rows=[{'timestamp':(i+1)*300,'close':close} for i,close in enumerate(closes)]
    c={'strategy':'trend_v1','initial_stop':110.,'peak_price_gain':15.}
    q={'bid':99.,'ask':99.1,'fresh':True,'timestamp':16000}
    short={'type':1,'price_open':105.}
    assert assess_reversal(short,rows,q,c,observed_profit=3)['action']=='hold'
    assert assess_reversal(short,rows[:-1],q,c,observed_profit=3)['action']=='hold'
    assert c['reversal_consecutive_bars']==1


def test_reversal_does_not_confirm_on_stale_or_future_candles():
    from modules.position_exit_policy import assess_reversal
    closes=[120-i*.48 for i in range(48)]+[96,96.5,97.3,98.4,99.2]
    rows=bars(closes)
    position_short={'type':1,'price_open':105.}
    def state():return {'strategy':'trend_v1','initial_stop':110.,'peak_price_gain':15.}
    for stamp in (rows[-1]['timestamp']-1,rows[-1]['timestamp']+600,0,float('nan')):
        c=state()
        response=assess_reversal(position_short,rows,{'bid':99.,'ask':99.1,'fresh':True,'timestamp':stamp},c,observed_profit=3.)
        assert response['action']=='hold'
        assert c.get('reversal_consecutive_bars',0)==0


def test_reversal_skipped_bar_cannot_advance_confirmation():
    from modules.position_exit_policy import assess_reversal
    closes=[120-i*.48 for i in range(48)]+[96,96.5,97.3,98.4,99.2]
    rows=bars(closes)
    short={'type':1,'price_open':105.}
    c={'strategy':'trend_v1','initial_stop':110.,'peak_price_gain':15.}
    first=assess_reversal(short,rows[:-1],{'bid':99.,'ask':99.1,'fresh':True,'timestamp':15650},c,observed_profit=3.)
    assert first['evidence']['confirmed_bars']==1
    # Next observed completed bar is two bars later; do not treat it as consecutive.
    next_rows=bars(closes+[100.5,100.8])
    second=assess_reversal(short,next_rows,{'bid':99.,'ask':99.1,'fresh':True,'timestamp':16550},c,observed_profit=3.)
    assert second['action']=='hold'
    assert second['evidence']['confirmed_bars']==1


def test_reversal_requires_measured_positive_broker_profit():
    from modules.position_exit_policy import assess_reversal
    rows=bars([120-i*.48 for i in range(48)]+[96,96.5,97.3,98.4,99.2])
    short={'type':1,'price_open':105.}
    q={'bid':99.,'ask':99.1,'fresh':True,'timestamp':16000}
    for profit in (None,0,-1,True,float('nan'),float('inf'),'4'):
        c={'strategy':'trend_v1','initial_stop':110.,'peak_price_gain':15.}
        report=assess_reversal(short,rows,q,c,observed_profit=profit)
        assert report['action']=='hold'
        assert report['execution_eligible'] is False
        assert c.get('reversal_consecutive_bars',0)==0
