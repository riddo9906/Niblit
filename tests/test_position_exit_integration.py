"""Real exit-policy integration with controlled quotes; no broker order calls."""
import copy,json,time,sqlite3
from types import SimpleNamespace
import pytest
from modules.position_intelligence import assess_entry_thesis,PositionIntelligence
from test_position_intelligence import setup_position
from test_core_market_pipeline import pipeline


def quote(now=None):
    now=time.time() if now is None else now
    return dict(symbol='BTC/USDT:USDT',venue='fixture',source='ccxt_public_order_book',
                timestamp=now,received_at=now,bid=101.,ask=101.01,fresh=True)


def thesis(s,context=None,quote_value=None,previous=None,complete=True):
    context=context or dict(strategy='trend_v1',initial_stop=95.)
    return assess_entry_thesis(s.position,s.market,dict(s.observation,venue='fixture'),{'assessment_complete':complete},
        {'state':'matched_engine_record','recorded_entry_context':context},quote_value or quote(),previous)


def test_original_evaluator_invoked_and_engine_context_unchanged(setup_position):
    s=setup_position;context=dict(strategy='trend_v1',initial_stop=95.)
    s.position['enter_tag']='niblit_lab:trend_v1:buy'
    before=copy.deepcopy(context);result=thesis(s,context)
    assert result['state']=='evaluated' and result['policy']=='position_exit_policy.assess_exit'
    assert result['recommendation']=='HOLD' and not result['execution_authorized']
    assert result['evidence']['strategy']=='trend_v1' and context==before
    assert 'execution_eligible' not in result


@pytest.mark.parametrize('change',['missing','stale','future','mismatch','venue','crossed','nan','boolean','source'])
def test_bad_quote_never_authorizes_exit(setup_position,change):
    s=setup_position;q=quote()
    if change=='missing':q.pop('timestamp')
    if change=='stale':q['timestamp']-=16
    if change=='future':q['timestamp']+=6
    if change=='mismatch':q['symbol']='ETH/USDT:USDT'
    if change=='venue':q['venue']='other'
    if change=='crossed':q['bid']=102
    if change=='nan':q['ask']=float('nan')
    if change=='boolean':q['bid']=True
    if change=='source':q['source']='candle_close'
    result=thesis(s,quote_value=q)
    assert result['state']=='unavailable' and result['recommendation']=='ABSTAIN'
    assert not result['execution_authorized']


def test_no_context_no_adoption_and_partial_failure_abstains(setup_position):
    s=setup_position
    r=assess_entry_thesis(s.position,s.market,s.observation,{'assessment_complete':True},
                         {'state':'matched_engine_record'},quote())
    assert r['state']=='not_eligible' and 'recorded' in r['reason']
    assert thesis(s,complete=False)['state']=='unavailable'
    s.position['enter_tag']='niblit_lab:breakout_v1:buy'
    assert thesis(s)['state']=='not_eligible'


def test_giveback_continuity_restart_and_distinct_quote_timestamps(setup_position,monkeypatch):
    s=setup_position;s.position['enter_tag']='niblit_lab:breakout_v1:buy'
    clock=[time.time()];monkeypatch.setattr(time,'time',lambda:clock[0])
    # Recorded boundary is below all fixture candles: no failed-breakout condition.
    context=dict(strategy='breakout_v1',initial_stop=99.,breakout_level=99.)
    a=thesis(s,context,dict(quote(),bid=101.,ask=101.01))
    assert a['recommendation']=='HOLD'
    clock[0]+=15
    b=thesis(s,context,dict(quote(),bid=100.6,ask=100.61),a)
    assert b['monitor_context']['giveback_checks']==1
    again=thesis(s,context,dict(quote(),bid=100.6,ask=100.61),b)
    assert again['monitor_context']['giveback_checks']==1
    clock[0]+=15
    c=thesis(s,context,dict(quote(),bid=100.6,ask=100.61),json.loads(json.dumps(again)))
    assert c['recommendation']=='EXIT-CANDIDATE' and not c['execution_authorized']
    assert context.get('giveback_checks') is None
    old=quote(clock[0]-10)
    assert thesis(s,context,old,c)['recommendation']=='ABSTAIN'


def attach_context(s):
    s.position['enter_tag']='niblit_lab:trend_v1:buy'
    context={'strategy':'trend_v1','initial_stop':95.}
    with sqlite3.connect(s.ledger) as db:
        db.execute('CREATE TABLE trade_custom_data(ft_trade_id,cd_key,cd_value)')
        db.execute('INSERT INTO trade_custom_data VALUES(?,?,?)',(1,'niblit_exit_context',json.dumps(context)))
    s.desk.quote=lambda pair,config:quote()
    return context


def test_full_scan_memory_restart_core_denial_and_no_order_routes(setup_position):
    s=setup_position;context=attach_context(s)
    a=s.monitor.scan()['positions'][0]
    assert a['entry_thesis']['state']=='evaluated' and a['core']['memory']['queued']
    restarted=PositionIntelligence(s.desk,s.core,s.pipeline.gateway)
    # Exact same quote evidence survives cache re-open without a new episode.
    saved_quote=quote(a['entry_thesis']['quote']['timestamp']);s.desk.quote=lambda pair,config:saved_quote
    b=restarted.scan()['positions'][0]
    assert b['core']['memory']['id']==a['core']['memory']['id']
    assert b['entry_thesis']['context_identity']==a['entry_thesis']['context_identity']
    with sqlite3.connect(s.ledger) as db:
        assert json.loads(db.execute('SELECT cd_value FROM trade_custom_data').fetchone()[0])==context
    restarted.core_analysis=lambda obs:{'authorization':{'allowed':False}}
    assert restarted.scan()['positions'][0]['entry_thesis']['recommendation']=='ABSTAIN'


def test_quote_failure_retains_candle_observation(setup_position):
    s=setup_position;attach_context(s)
    def unavailable(pair,config):raise ConnectionError('fixture quote outage')
    s.desk.quote=unavailable
    report=s.monitor.scan()['positions'][0]
    assert report['entry_thesis']['state']=='unavailable'
    assert report['strategies']['assessment_complete'] and report['core']['memory']['queued']


@pytest.mark.parametrize('change',['valid','missing_timestamp','stale','mismatch','crossed','empty','wrong_contract'])
def test_public_quote_provider_exact_contract_and_timestamp(monkeypatch,change):
    from modules import market_data_providers as m
    stamp=time.time()
    instrument={'symbol':'BTC/USDT:USDT','active':True,'contract':True,'linear':True,'settle':'USDT'}
    book={'symbol':instrument['symbol'],'timestamp':stamp*1000,'bids':[[100.,1]],'asks':[[100.01,2]]}
    if change=='missing_timestamp':book['timestamp']=None
    if change=='stale':book['timestamp']-=20000
    if change=='mismatch':book['symbol']='BTC/USDT'
    if change=='crossed':book['asks']=[[99.,2]]
    if change=='empty':book['bids']=[]
    if change=='wrong_contract':instrument['linear']=False
    class Exchange:
        def __init__(self,config):
            assert config=={'enableRateLimit':True,'timeout':5000}
        def load_markets(self):return {instrument['symbol']:instrument}
        def market(self,pair):return instrument
        def fetch_order_book(self,pair,limit):
            assert pair=='BTC/USDT:USDT' and limit==5
            return book
    monkeypatch.setattr(m,'_CCXT_OK',True);monkeypatch.setattr(m,'_ccxt',SimpleNamespace(binanceusdm=Exchange))
    result=m.MarketDataProviders().ccxt_quote('BTC/USDT:USDT','binanceusdm')
    assert result['fresh'] is (change=='valid')
    assert result['source']=='ccxt_public_order_book'


def test_desk_quote_selects_original_futures_provider(monkeypatch):
    from modules.trading_desk import Desk
    from modules.market_data_providers import MarketDataProviders
    calls=[]
    def fetch(self,pair,exchange):calls.append((pair,exchange));return {'fresh':False}
    monkeypatch.setattr(MarketDataProviders,'ccxt_quote',fetch)
    d=Desk.__new__(Desk)
    assert d.quote('BTC/USDT:USDT',{'exchange':'binance','trading_mode':'futures'})['venue']=='binance'
    assert calls==[('BTC/USDT:USDT','binanceusdm')]
    assert not d.quote('BTC/USDT:USDT',{'exchange':'binance','trading_mode':'spot'})['fresh']
