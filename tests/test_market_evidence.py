from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.market_evidence import recognize,closed_rows
from modules.desktop_market_intelligence import DesktopMarketIntelligence,component_inventory
from modules.strategy_manager import assess_observation

def bars(n=60):
    return [{'timestamp':300*(i+1),'open':100+i*.1,'high':102+i*.1,'low':99+i*.1,'close':101+i*.1,'volume':20} for i in range(n)]

def evidence(rows=None,clock=18300):
    return recognize(rows or bars(),'EURUSD','M5',300,clock,{'account_identity':'demo-a'})

def test_forming_future_candles_never_affect_snapshot():
    rows=bars();baseline=evidence(rows)
    future={'timestamp':18300,'open':0,'high':0,'low':0,'close':float('nan')}
    assert evidence(rows+[future])==baseline
    assert baseline['last_closed_at']==18300

def test_engulfing_rules_and_source_contract():
    rows=bars();rows[-2].update(open=110,close=108,low=107,high=111)
    rows[-1].update(open=107,close=112,low=106,high=113)
    pattern=next(p for p in evidence(rows)['patterns'] if p['name']=='bullish_engulfing')
    assert pattern['confirmation']=='closed_candle_rule' and pattern['available_at']==18300
    assert pattern['confidence'] is None and pattern['source_data']==rows[-2:]

@pytest.mark.parametrize('key,value',[('open',float('nan')),('low',999),('close',-1)])
def test_invalid_closed_candle_rejected(key,value):
    rows=bars();rows[-1][key]=value
    with pytest.raises(ValueError):evidence(rows)

def test_indicator_determinism_and_swings_available_only_after_right_bars():
    result=evidence();assert result==evidence()
    assert result['indicators']['atr14_sma']>0
    for swing in result['structure']['swings']:
        assert swing['available_at']>=swing['timestamp']+900
        assert swing['available_at']<=18300

def test_shared_evidence_does_not_change_votes():
    observation={'symbol':'EURUSD','venue':'example','timeframe':'5m','mode':'replay',
        'account_scope':'demo-a','source':'fixture','candles':bars(),'received_at':18300,'as_of':18300,'fresh':True}
    before=assess_observation(observation,now=18300)
    after=assess_observation({**observation,'market_evidence':{'M5':evidence()},'market_context':{'H4':{'trend':'down'}}},now=18300)
    assert len(after['candidates'])==6
    assert [(c['strategy'],c['side']) for c in before['candidates']]==[(c['strategy'],c['side']) for c in after['candidates']]
    assert before['side']==after['side'] and after['execution_authorized'] is False
    assert all(c['snapshot_id']==evidence()['snapshot_id'] for c in after['candidates'])

def test_inventory_never_executes_or_claims_compiled_source(tmp_path):
    directory=tmp_path/'MQL5/Experts';directory.mkdir(parents=True)
    (directory/'unsafe.ex5').write_bytes(b'compiled')
    (directory/'source.mq5').write_text('void OnTick(){OrderSend();}')
    result=component_inventory(tmp_path)
    assert len(result['components'])==2
    assert all(not c['execution_enabled'] and not c['approved_for_observation'] for c in result['components'])
    assert not next(c for c in result['components'] if c['file_type']=='.ex5')['source_available']

def test_desktop_binding_rejects_account_change_before_data():
    bridge=Mock();bridge.connect.return_value=(None,None,None)
    bridge.account_record.return_value={'identity':'wrong','terminal_id':'desktop'}
    service=DesktopMarketIntelligence(bridge,Mock())
    with pytest.raises(ValueError):service.observe('BTCUSD','expected','desktop')
    bridge.snapshot.assert_not_called()

def test_desktop_cache_revalidates_binding_without_vps():
    identity={'identity':'demo','terminal_id':'desktop','server':'example','environment':'demo'}
    api=SimpleNamespace(TIMEFRAME_H1=60,TIMEFRAME_H4=240,copy_rates_from_pos=lambda *a:[])
    bridge=Mock();bridge.connect.return_value=(api,None,None);bridge.account_record.return_value=identity
    bridge.snapshot.return_value={'candles':bars(),'quote':{'timestamp':18300,'fresh':True},'market_context':{}}
    core=Mock(return_value={'state':'analyzed_by_core','analysis':{'candidates':[]}})
    service=DesktopMarketIntelligence(bridge,core)
    first=service.observe('EURUSD','demo','desktop');second=service.observe('EURUSD','demo','desktop')
    assert second['cache_hit'] and not first['vps_dependency'] and not first['execution_authorized']
    assert not first['utc_clock_verified'] and core.call_count==1
    bridge.account_record.return_value={**identity,'identity':'live'}
    with pytest.raises(ValueError):service.observe('EURUSD','demo','desktop')

def test_remote_profile_blocks_mutations_but_not_explicit_desktop_analysis(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from modules.trading_desk import create_app,Desk
    monkeypatch.setenv('NIBLIT_VPS_GATEWAY_PROFILE','preserved-profile')
    bridge=Mock();bridge.connection_record.return_value={'identity':'demo','terminal_id':'desktop'}
    client=TestClient(create_app(Desk(tmp_path),mt5=bridge,core_hosted=True))
    assert client.get('/api/mt5/snapshot').status_code==403
    assert client.get('/api/intelligence/desktop-binding').json()['identity']=='demo'
    bridge.check_order.assert_not_called()
    page=client.get('/').text
    assert '/intelligence.js' in page and 'Desktop market intelligence' in page
