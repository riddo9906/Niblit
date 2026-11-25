import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.trading_session_selftest import fixture,freq_fixture
from modules.trading_session_api import register_trading_routes,demo_readiness
from modules.core_trading_sessions import configured_limits

def client_for(monkeypatch,f):
 monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY','1');monkeypatch.setenv('NIBLIT_API_PORT','5200')
 monkeypatch.delenv('NIBLIT_FREQTRADE_EXECUTION_CONFIG',raising=False);monkeypatch.delenv('NIBLIT_NATIVE_CALLBACK_TOKEN_FILE',raising=False)
 app=FastAPI();register_trading_routes(app,lambda:f.service)
 return TestClient(app,base_url='http://127.0.0.1:5200')

def test_readiness_and_review_do_not_grant_or_clear_stop(tmp_path,monkeypatch):
 f=fixture(tmp_path);f.service.stop()
 with client_for(monkeypatch,f) as client:
  h={'origin':'http://tauri.localhost','x-niblit-trading-nonce':f.service.nonce}
  assert client.post('/api/trading/sessions/readiness',json={'adapter':'mt5','symbol':'EURUSD'}).status_code==403
  result=client.post('/api/trading/sessions/readiness',json={'adapter':'mt5','symbol':'EURUSD'},headers=h)
  assert result.status_code==200,result.text
  r=result.json();assert r['review_only'] and not r['execution_authorized'] and not r['order_ticket_created']
  assert {'deployment_lock','no_scoped_authority'}<={x['code'] for x in r['blockers']}
  p=client.post('/api/trading/sessions/propose',json={'adapter':'mt5','symbol':'EURUSD'},headers=h)
  assert p.status_code==200,p.text
  proposal=p.json();assert proposal['state']=='pending'
  denied=client.post('/api/trading/sessions/activate',json={'id':proposal['id'],'spec_hash':proposal['spec_hash'],'acknowledgement':'ACTIVATE_BOUNDED_DEMO_SESSION'},headers=h)
  assert denied.status_code==403
  assert f.service.session(proposal['id'])['state']=='pending'
 assert f.api.sent==[]
 f.service.shutdown()

def test_mt5_draft_uses_inspect_without_ticket(tmp_path,monkeypatch):
 f=fixture(tmp_path);a=f.service.adapters['mt5'];s=a.snapshot('EURUSD')
 monkeypatch.setattr(a.orders,'preview',lambda *args,**kwargs:pytest.fail('Draft created native ticket'))
 p=a.draft_entry(s,'buy',configured_limits());assert p['ticket'] is None and p['risk']>0
 assert f.api.sent==[];f.service.shutdown()

def test_operator_activation_contract_only_in_isolated_fixture(tmp_path,monkeypatch):
 f=fixture(tmp_path)
 with client_for(monkeypatch,f) as client:
  monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY','0') # Test process only, not installed configuration.
  original=f.service.activate
  monkeypatch.setattr(f.service,'activate',lambda ident,fingerprint:original(ident,fingerprint,threaded=False))
  h={'origin':'http://tauri.localhost','x-niblit-trading-nonce':f.service.nonce}
  p=client.post('/api/trading/sessions/propose',json={'adapter':'mt5','symbol':'EURUSD'},headers=h).json()
  body={'id':p['id'],'spec_hash':p['spec_hash'],'acknowledgement':'ACTIVATE_BOUNDED_DEMO_SESSION'}
  assert client.post('/api/trading/sessions/activate',json=body).status_code==403
  r=client.post('/api/trading/sessions/activate',json=body,headers=h)
  assert r.status_code==200 and f.service.session(p['id'])['state']=='active'
  assert not any(x.get('running') for x in f.service.status()['observers'])
 assert f.api.sent==[];f.service.shutdown()

def test_readonly_risk_preview_does_not_halt_or_rewrite_a_scope(tmp_path):
 f=fixture(tmp_path);row=f.service.propose('mt5','EURUSD');before=f.service.session(row['id'])
 s=f.service.adapters['mt5'].snapshot('EURUSD');s['margin']=s['equity']
 with f.service.gateway.db() as db:events=db.execute('select count(*) from trading_events').fetchone()[0]
 with pytest.raises(PermissionError,match='loss/drawdown'):
  f.service.risk(row,s,record=False)
 assert f.service.session(row['id'])==before
 with f.service.gateway.db() as db:assert db.execute('select count(*) from trading_events').fetchone()[0]==events
 assert f.api.sent==[];f.service.shutdown()

def test_freqtrade_blockers_and_platform_scope(tmp_path,monkeypatch):
 f=freq_fixture(tmp_path);monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY','1')
 original=f.service.adapters['freqtrade'].snapshot
 def stopped(symbol):
  s=original(symbol);s['configuration']['state']='stopped';s['configuration']['max_open_trades']=0;return s
 monkeypatch.setattr(f.service.adapters['freqtrade'],'snapshot',stopped)
 r=demo_readiness(f.service,'freqtrade','BTC/USDT:USDT')
 assert not r['activation_eligible']
 assert {'engine_stopped','position_capacity','missing_cost_bounds'}<={x['code'] for x in r['blockers']}
 assert r['controller']['strategy']=='NiblitCoreManaged' and f.api.sent==[]
 f.service.shutdown()

@pytest.mark.parametrize('kind',['wrong_environment','stale','missing'])
def test_unknown_identity_or_market_fails_closed(tmp_path,monkeypatch,kind):
 f=fixture(tmp_path);a=f.service.adapters['mt5'];original=a.snapshot
 def changed(symbol):
  s=original(symbol)
  if kind=='wrong_environment':s['environment']='live'
  elif kind=='stale':s['quote']['fresh']=False
  else:raise ConnectionError('fixture unavailable')
  return s
 monkeypatch.setattr(a,'snapshot',changed)
 r=demo_readiness(f.service,'mt5','EURUSD')
 assert not r['activation_eligible'] and not r['execution_authorized'] and f.api.sent==[]
 f.service.shutdown()

@pytest.mark.parametrize('packaged,success,expected',[(True,False,True),(True,True,False),(False,False,False)])
def test_failed_packaged_desktop_cleans_owned_runtime(monkeypatch,packaged,success,expected):
 from unittest.mock import Mock
 from modules.niblit_ui_launcher import finish_failed_packaged_ui
 if packaged:monkeypatch.setenv('NIBLIT_INSTALLATION_MANIFEST','fixture-only')
 else:monkeypatch.delenv('NIBLIT_INSTALLATION_MANIFEST',raising=False)
 result=Mock();result.success=success;core=Mock()
 assert finish_failed_packaged_ui(result,core) is expected
 assert result.terminate.called is expected and core.shutdown.called is expected

def test_packaged_cleanup_failure_still_attempts_core_shutdown(monkeypatch):
 from unittest.mock import Mock
 from modules.niblit_ui_launcher import finish_failed_packaged_ui
 monkeypatch.setenv('NIBLIT_INSTALLATION_MANIFEST','fixture-only')
 result=Mock();result.success=False;result.terminate.side_effect=RuntimeError('fixture cleanup error');core=Mock()
 assert finish_failed_packaged_ui(result,core)
 core.shutdown.assert_called_once()
