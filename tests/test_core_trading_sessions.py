import json
import sqlite3
import threading
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.trading_session_selftest import fixture,freq_fixture,activate,exercise,exercise_freq
from modules.core_trading_sessions import CoreTradingSessions
from modules.trading_session_api import register_trading_routes


@pytest.fixture
def f(tmp_path):return fixture(tmp_path)


def test_full_mt5_pipeline_and_canonical_outbox(tmp_path):assert exercise(tmp_path)['passed']
def test_full_freqtrade_pipeline_and_canonical_outbox(tmp_path):assert exercise_freq(tmp_path)['passed']


def test_observation_and_proposal_never_authorize(f):
    f.service.propose('mt5','EURUSD',60);f.bot.step()
    assert not f.api.sent
    assert len(f.bot.manager['candidates'])==6


def test_scope_tamper_and_replayed_activation(f):
    p=f.service.propose('mt5','EURUSD',60)
    with pytest.raises(PermissionError):f.service.activate(p['id'],'0'*64,threaded=False)
    f.service.activate(p['id'],p['spec_hash'],threaded=False)
    with pytest.raises(PermissionError):f.service.activate(p['id'],p['spec_hash'],threaded=False)


@pytest.mark.parametrize('field,value',[('max_entries',1.5),('risk_cash',26),('risk_fraction',float('nan')),('max_positions',True)])
def test_scope_limits_are_bounded_and_finite(f,field,value):
    with pytest.raises(ValueError):f.service.propose('mt5','EURUSD',60,{field:value})
    assert not f.api.sent


def test_expiry_keeps_observer_but_no_order(f):
    p=activate(f)
    with f.gateway.db() as db:db.execute('UPDATE trading_sessions SET expires=0 WHERE id=?',(p['id'],))
    f.bot.step();assert not f.api.sent
    assert f.service.session(p['id'])['state']=='expired'
    assert f.bot.manager['assessment_complete']


def test_restart_interrupts_scope_and_keeps_emergency_stop(f):
    p=activate(f);f.service.stop(emergency=True)
    other=CoreTradingSessions(f.runtime,f.service.adapters,journal=f.service.journal,notify=lambda _:None)
    q=other.propose('mt5','EURUSD',60)
    with pytest.raises(PermissionError,match='Emergency'):other.activate(q['id'],q['spec_hash'],threaded=False)
    other.activate(q['id'],q['spec_hash'],clear_stop=True,threaded=False)
    with pytest.raises(PermissionError):f.service.pm.check_trading(f.gateway,q['id'],f.service.runtime_id,'forged','open')
    assert f.service.session(p['id'])['state']=='stopped'


def test_active_session_does_not_rearm_after_restart(f):
    p=activate(f)
    other=CoreTradingSessions(f.runtime,f.service.adapters,journal=f.service.journal,notify=lambda _:None)
    bot=other.observe('mt5','EURUSD',threaded=False);bot.session['id']=p['id']
    bot.step();assert not f.api.sent
    assert other.session(p['id'])['state']=='interrupted'


@pytest.mark.parametrize('case',['live','changed_account','stale_quote','invalid_equity','session_loss','peak_drawdown','daily_loss'])
def test_core_rejects_unsafe_account_and_market_state(f,monkeypatch,case):
    p=activate(f)
    if case=='live':f.api.account.trade_mode=2
    elif case=='changed_account':f.api.account.login=99
    elif case=='stale_quote':
        original=f.bridge.tick
        monkeypatch.setattr(f.bridge,'tick',lambda *a:original(*a)|{'fresh':False})
    elif case=='invalid_equity':f.api.account.equity=float('nan')
    elif case=='session_loss':f.api.account.equity*=.97
    elif case=='peak_drawdown':
        with f.gateway.db() as db:db.execute('UPDATE trading_sessions SET peak_equity=? WHERE id=?',(1100000.,p['id']))
    elif case=='daily_loss':
        from types import SimpleNamespace
        f.api.deals.append(SimpleNamespace(type=0,profit=-40000.,commission=0.,swap=0.,fee=0.))
    f.bot.step();assert not f.api.sent


@pytest.mark.parametrize('operation',['disagreement','failure'])
def test_six_strategy_consensus_fails_closed(f,monkeypatch,operation):
    import modules.strategy_manager as strategies
    original=strategies.evaluate
    def evaluate(rows,name):
        result=original(rows,name)
        if name=='rsi_reversion_v1':
            if operation=='failure':raise ValueError('Fixture strategy error')
            return result|{'side':'sell'}
        return result
    monkeypatch.setattr(strategies,'evaluate',evaluate)
    activate(f);f.bot.step();assert not f.api.sent
    assert len(f.bot.manager['candidates'])==6


@pytest.mark.parametrize('behavior',['timeout','partial','reject'])
def test_uncertain_partial_rejected_delivery_is_not_retried(f,behavior):
    activate(f);f.api.behavior=behavior
    for _ in range(3):f.bot.step()
    assert len(f.api.sent)==1
    if behavior!='reject':assert f.service.admission.status('broker')['state']=='quarantined'


def test_core_owned_mt5_ticket_cannot_use_manual_confirmation(f):
    s=f.service.adapters['mt5'].snapshot('EURUSD')
    prepared=f.service.adapters['mt5'].prepare(s,'buy',__import__('modules.core_trading_sessions',fromlist=['configured_limits']).configured_limits())
    with pytest.raises(PermissionError,match='Core-owned'):f.orders.confirm(prepared['ticket'])
    assert not f.api.sent


def test_core_owned_freqtrade_ticket_cannot_use_manual_confirmation(tmp_path):
    f=freq_fixture(tmp_path);adapter=f.service.adapters['freqtrade'];s=adapter.snapshot('BTC/USDT:USDT')
    prepared=adapter.prepare(s,'buy',__import__('modules.core_trading_sessions',fromlist=['configured_limits']).configured_limits())
    with pytest.raises(PermissionError,match='Core-owned'):f.desk.confirm(prepared['ticket'])
    assert not f.api.sent


def test_revocation_between_preview_and_send_is_final(f):
    p=activate(f);adapter=f.service.adapters['mt5'];prepare=adapter.prepare
    def revoke(*a,**k):
        result=prepare(*a,**k)
        f.service.pm.stop_trading(f.gateway,p['id'])
        return result
    adapter.prepare=revoke;f.bot.step();assert not f.api.sent


def test_revalidate_risk_after_preview(f):
    activate(f);adapter=f.service.adapters['mt5'];prepare=adapter.prepare
    def change(*a,**k):
        result=prepare(*a,**k);f.api.account.equity*=.9;return result
    adapter.prepare=change;f.bot.step();assert not f.api.sent


def test_memory_denial_prevents_submission(f):
    activate(f);f.gateway.denied=True;f.bot.step();assert not f.api.sent


def test_inference_reservation_does_not_block_deterministic_broker_cycle(f):
    activate(f)
    token = f.service.admission.acquire('core_inference')['token']
    f.bot.step()
    assert len(f.api.sent) == 1
    assert f.service.admission.status()['owner'] == 'core_inference'
    f.service.admission.finish(token)


def test_competing_broker_cycle_blocks_and_audits_trade(f):
    proposal = activate(f)
    token = f.service.admission.acquire('trading_cycle', session_id='other')['token']
    f.bot.step()
    assert not f.api.sent and f.bot.manager['assessment_complete']
    with f.gateway.db() as db:
        denial = db.execute("SELECT reason FROM trading_admission_audit WHERE session_id=? AND decision='denied'",
                            (proposal['id'],)).fetchone()
    assert denial['reason'] == 'Another Core broker cycle owns admission'
    f.service.admission.finish(token)


def test_dead_broker_owner_recovers_only_after_uncertain_delivery_resolves(f, monkeypatch):
    from modules.task_admission import AdmissionBusy
    proposal = activate(f)
    f.service.admission.acquire('trading_cycle', session_id=proposal['id'])
    monkeypatch.setattr(f.service.admission, '_owner_gone', lambda *_: True)
    with f.gateway.db() as db:
        db.execute("INSERT INTO trading_orders VALUES('uncertain',?,'mt5','account','EURUSD','EURUSD','open','unknown','{}',NULL,0)",
                   (proposal['id'],))
    with pytest.raises(AdmissionBusy):
        f.service.admission.acquire('trading_cycle')
    with f.gateway.db() as db:
        db.execute("UPDATE trading_orders SET state='rejected' WHERE id='uncertain'")
    token = f.service.admission.acquire('trading_cycle')['token']
    with f.gateway.db() as db:
        assert db.execute("SELECT 1 FROM trading_admission_audit WHERE decision='recovered'").fetchone()
    f.service.admission.finish(token)


def test_closed_broker_position_does_not_cause_duplicate_entry_same_bar(f):
    activate(f);f.bot.step();f.bot.step();f.api.price+=.01;f.bot.step();f.bot.step();f.bot.step()
    assert len(f.api.sent)==2


def test_manual_position_never_adopted_or_closed(f):
    activate(f);f.bot.step();f.bot.step()
    # Proven entry record is removed from fixture scope to represent unowned exposure.
    with f.gateway.db() as db:db.execute("UPDATE trading_orders SET state='closed'")
    f.api.price+=.01;f.bot.step();assert len(f.api.sent)==1


def test_api_needs_exact_origin_nonce_and_ack(f):
    app=FastAPI();register_trading_routes(app,lambda:f.service)
    client=TestClient(app)
    body={'adapter':'mt5','symbol':'EURUSD','seconds':60}
    assert client.post('/api/trading/sessions/propose',json=body).status_code==403
    assert client.get('/api/trading/sessions',headers={'origin':'https://example.com'}).status_code==403
    nonce=client.get('/api/trading/sessions').json()['operator_nonce']
    headers={'origin':'http://127.0.0.1:5000','x-niblit-trading-nonce':nonce}
    p=client.post('/api/trading/sessions/propose',json=body,headers=headers).json()
    assert client.post('/api/trading/sessions/activate',json={'id':p['id'],'spec_hash':p['spec_hash']},headers=headers).status_code==422
    assert not f.api.sent


def test_alerts_are_durable_and_never_execute(f):
    f.bot.step();status=f.service.status();alerts=[e for e in status['events'] if e['alert']]
    assert alerts and not any(e['delivered'] for e in alerts)
    f.service.acknowledge_alert(alerts[0]['id'])
    assert not f.api.sent


def test_learning_approval_does_not_grant_trading(f):
    p=f.service.propose('mt5','EURUSD',60)
    with f.gateway.db() as db:
        f.service.pm._learning_schema(db)
        db.execute("INSERT INTO task_authorizations(id,spec,spec_hash,state,created,expires) VALUES('learning','{}','x','approved',0,9999999999)")
    f.bot.session['id']=p['id'];f.bot.step();assert not f.api.sent


def test_freqtrade_native_protection_change_blocks_final_send(tmp_path):
    f=freq_fixture(tmp_path);p=f.service.propose('freqtrade','BTC/USDT:USDT',60)
    f.service.activate(p['id'],p['spec_hash'],threaded=False)
    adapter=f.service.adapters['freqtrade'];prepare=adapter.prepare
    def change(*args,**kwargs):
        result=prepare(*args,**kwargs);f.api.config['stoploss']=-.2;return result
    adapter.prepare=change;f.bot.step();assert not f.api.sent


def test_freqtrade_sells_use_existing_short_adapter(tmp_path):
    f=freq_fixture(tmp_path)
    for i,r in enumerate(f.api.candles):r.update(open=200.-i,high=201.-i,low=199.-i,close=199.5-i)
    p=f.service.propose('freqtrade','BTC/USDT:USDT',60);f.service.activate(p['id'],p['spec_hash'],threaded=False)
    f.bot.step();assert len(f.api.sent)==1,f.bot.error
    assert f.api.sent[0][1]['side']=='short'


def test_atomic_instrument_claim_blocks_other_broker(f,tmp_path):
    other=fixture(tmp_path/'other');other.api.account.login=2;other.bridge.snapshot('EURUSD');other.bridge.snapshot('EURUSD')
    f.service.adapters['other']=other.service.adapters['mt5']
    activate(f);p=f.service.propose('other','EURUSD',60)
    f.service.activate(p['id'],p['spec_hash'],threaded=False)
    f.bot.step();f.service.bots[('other','EURUSD')].step()
    assert len(f.api.sent)==1 and not other.api.sent


def test_http_review_activation_to_core_worker_and_hosted_desk(f,monkeypatch,tmp_path):
    from modules.trading_session_api import register_market_desk
    from modules.trading_desk import create_app,Desk
    app=FastAPI();register_trading_routes(app,lambda:f.service)
    hosted=register_market_desk(app,lambda:create_app(Desk(tmp_path/'desk'),mt5=f.bridge,core_hosted=True))
    original=f.service.activate
    monkeypatch.setattr(f.service,'activate',lambda ident,fingerprint,clear_stop=False:original(ident,fingerprint,clear_stop=clear_stop,threaded=False))
    client=TestClient(app)
    page=client.get('/market-desk/')
    assert page.status_code==200
    assert 'content="/market-desk"' in page.text
    assert 'src="/market-desk/sessions.js"' in page.text
    assert client.get('/market-desk/sessions.js').status_code==200
    nonce=client.get('/api/trading/sessions').json()['operator_nonce']
    headers={'origin':'http://127.0.0.1:5000','x-niblit-trading-nonce':nonce}
    p=client.post('/api/trading/sessions/propose',json={'adapter':'mt5','symbol':'EURUSD','seconds':60},headers=headers).json()
    result=client.post('/api/trading/sessions/activate',json={'id':p['id'],'spec_hash':p['spec_hash'],'acknowledgement':'ACTIVATE_BOUNDED_DEMO_SESSION'},headers=headers)
    assert result.status_code==200,result.text
    f.bot.step();assert len(f.api.sent)==1
    assert client.post('/api/trading/sessions/stop',json={'emergency':True},headers=headers).status_code==200
    f.bot.step();assert len(f.api.sent)==1
    hosted.shutdown()


def test_emergency_stop_persists_when_memory_permission_is_revoked(f):
    activate(f);f.gateway.denied=True
    response=f.service.stop(emergency=True)
    assert response['state']=='stopped' and response['telemetry_pending']
    assert f.service.status()['emergency_stopped']
    f.bot.step();assert not f.api.sent


def test_risk_exits_owned_position_when_exposure_limit_breached(f):
    activate(f);f.bot.step();f.bot.step()
    f.api.account.equity=200000.
    f.bot.step();assert len(f.api.sent)==2
    assert f.api.sent[-1].get('position')


def test_missing_broker_stop_causes_authorized_exit_not_new_entry(f):
    activate(f);f.bot.step();f.bot.step()
    f.api.positions[0].sl=0.
    f.bot.step();assert len(f.api.sent)==2
    assert f.api.sent[-1].get('position')


def test_broker_currency_valuation_is_used(f):
    from modules.trading_session_adapters import account_exposure
    f.api.info.currency_profit='JPY'
    value=account_exposure(f.api,f.api.info,'EURUSD',.01,160.,'USD')
    assert value>160000. and value<162000.
    f.api.order_calc_profit=lambda *a:None
    with pytest.raises(ValueError):account_exposure(f.api,f.api.info,'EURUSD',.01,160.,'USD')


def test_permission_manager_refuses_funded_scope_itself(f):
    with pytest.raises(PermissionError):
        f.service.pm.propose_trading(f.gateway,{'environment':'live','live_money':True},f.service.runtime_id,1000.)


def test_restart_cancels_only_provably_unsent_ticket(f):
    from modules.core_trading_sessions import digest
    p=activate(f);s=f.service.adapters['mt5'].snapshot('EURUSD')
    prepared=f.service.adapters['mt5'].prepare(s,'buy',p['spec']['limits'])
    with f.gateway.db() as db:
        db.execute('INSERT INTO trading_orders VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('unsent',p['id'],'mt5',s['account'],s['instrument'],'EURUSD','open','prepared',json.dumps({'prepared':prepared,'context':{}}),None,0))
    other=CoreTradingSessions(f.runtime,f.service.adapters,journal=f.service.journal,notify=lambda _:None)
    with f.gateway.db() as db:assert db.execute("SELECT state FROM trading_orders WHERE id='unsent'").fetchone()[0]=='rejected'
    with f.orders.db() as db:assert db.execute('SELECT state FROM mt5_tickets WHERE id=?',(prepared['ticket'],)).fetchone()[0]=='rejected'
    assert not f.api.sent


def test_background_worker_stops_cleanly_without_activating(f):
    bot=f.service.observe('mt5','EURUSD',threaded=True)
    f.service.shutdown()
    assert not bot.worker.is_alive() and not f.api.sent


@pytest.mark.parametrize('field,value',[('stoploss',None),('minimal_roi',{}),('fee',None)])
def test_freqtrade_missing_native_protection_or_fee_blocks_entry(tmp_path,field,value):
    f=freq_fixture(tmp_path);f.api.config[field]=value
    p=f.service.propose('freqtrade','BTC/USDT:USDT',60);f.service.activate(p['id'],p['spec_hash'],threaded=False)
    f.bot.step();assert not f.api.sent


def test_freqtrade_engine_is_never_started_by_observation_or_activation(tmp_path):
    f=freq_fixture(tmp_path);f.api.config['state']='stopped'
    p=f.service.propose('freqtrade','BTC/USDT:USDT',60);f.service.activate(p['id'],p['spec_hash'],threaded=False)
    f.bot.step();assert not f.api.sent



def test_reconciliation_and_realized_outcomes_continue_with_stale_market(f,monkeypatch):
    activate(f);f.bot.step();f.bot.step()
    request=dict(f.api.sent[0]);request.update(position=f.api.positions[0].ticket,type=1)
    f.api.order_send(request)  # offline broker double simulates a protective exit
    original=f.bridge.tick
    monkeypatch.setattr(f.bridge,'tick',lambda *a:original(*a)|{'fresh':False})
    f.bot.step()
    assert len(f.api.sent)==2
    receipts=[json.loads(o['result'] or '{}') for o in f.service.status()['orders']]
    assert any(abs(r.get('realized_net',0)-4.8)<1e-8 for r in receipts)
    assert f.bot.error and 'Stale' in f.bot.error


def test_telemetry_checks_actual_runtime_namespace(f):
    original=f.gateway.require
    f.runtime.scope={'namespace':'other','principal':'desktop_operator'}
    def require(action,*args,**kwargs):
        if kwargs.get('namespace')=='other':raise PermissionError('Other namespace is not granted')
        return original(action,*args,**kwargs)
    f.gateway.require=require
    with pytest.raises(PermissionError):f.service.emit('fixture',{'environment':'simulation'})
    assert not f.api.sent


def test_native_receipt_is_one_time_and_cannot_mint_a_session(tmp_path):
    f=freq_fixture(tmp_path);captured=[]
    original=f.api.verify_core
    def verify(body):
        captured.append(dict(body));return original(body)
    f.api.verify_core=verify
    p=f.service.propose('freqtrade','BTC/USDT:USDT',60,{'max_entries':1})
    f.service.activate(p['id'],p['spec_hash'],threaded=False);f.bot.step()
    assert len(f.api.trades)==1,f.bot.error
    assert captured
    with pytest.raises(PermissionError):f.service.native_entry_receipt(captured[0])
    with pytest.raises(PermissionError):f.service.native_entry_receipt(captured[0]|{'ticket':'x'*32})
    assert f.service.session(p['id'])['entries']==1


def test_native_strategy_callback_denies_expired_or_changed_claim(tmp_path):
    f=freq_fixture(tmp_path)
    p=f.service.propose('freqtrade','BTC/USDT:USDT',60)
    f.service.activate(p['id'],p['spec_hash'],threaded=False)
    def verify(body):
        with f.gateway.db() as db:db.execute('UPDATE trading_sessions SET expires=0 WHERE id=?',(p['id'],))
        return f.service.native_entry_receipt(body)
    f.api.verify_core=verify;f.bot.step()
    assert not f.api.trades


def test_non_core_native_catalog_cannot_execute_core_session(tmp_path):
    f=freq_fixture(tmp_path);f.api.config['strategy']='NiblitLabManager'
    p=f.service.propose('freqtrade','BTC/USDT:USDT',60)
    f.service.activate(p['id'],p['spec_hash'],threaded=False);f.bot.step()
    assert not f.api.sent


@pytest.mark.parametrize('change',[{'dry_run':False},{'strategy':'Other'},{'db_url':None}])
def test_native_callback_fails_closed_without_original_scope(change):
    from modules.freqtrade_core_claim import confirm_core_entry
    config={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':{'name':'binance'},'stake_currency':'USDT','trading_mode':'futures','db_url':'sqlite:///fixture'}|change
    verify=Mock(return_value={'allowed':True})
    assert not confirm_core_entry(config,-.01,{'0':.02},pair='BTC/USDT:USDT',side='long',amount=.001,rate=100.,entry_tag='niblit_core:'+'a'*32,verify=verify)


def test_native_callback_transport_error_never_uses_freqtrade_fail_open_default():
    from modules.freqtrade_core_claim import confirm_core_entry
    config={'dry_run':True,'strategy':'NiblitCoreManaged','exchange':{'name':'binance'},'stake_currency':'USDT','trading_mode':'futures','db_url':'sqlite:///fixture'}
    verify=Mock(side_effect=TimeoutError('offline'))
    assert confirm_core_entry(config,-.01,{'0':.02},pair='BTC/USDT:USDT',side='long',amount=.001,rate=100.,entry_tag='niblit_core:'+'a'*32,verify=verify) is False


def test_session_signal_and_expiry_audit_survive_broker_outage(f, monkeypatch):
    proposal = activate(f)
    f.bot.step()
    status = f.service.status()
    assert any(event['kind'] == 'signal' and event['payload']['session'] == proposal['id']
               for event in status['events'])
    with f.gateway.db() as db:
        db.execute('UPDATE trading_sessions SET expires=0 WHERE id=?', (proposal['id'],))
    monkeypatch.setattr(f.bot.bridge, 'reconciliation_identity', Mock(side_effect=ConnectionError))
    submissions = len(f.api.sent)
    f.bot.step()
    assert len(f.api.sent) == submissions
    assert f.service.session(proposal['id'])['state'] == 'expired'
    assert any(event['kind'] == 'session_expired' and event['alert']
               and event['payload']['session'] == proposal['id']
               for event in f.service.status()['events'])


def test_expired_owned_position_is_watched_without_close_authority(f):
    proposal = activate(f)
    f.bot.step()
    f.bot.step()
    with f.gateway.db() as db:
        db.execute('UPDATE trading_sessions SET expires=0 WHERE id=?', (proposal['id'],))
    f.api.price += .01
    f.bot.step()
    assert len(f.api.sent) == 1
    status = f.service.status()
    assert f.service.session(proposal['id'])['state'] == 'expired'
    assert any(event['kind'] == 'position_watch' and event['payload']['session'] == proposal['id']
               and event['payload']['position']['stop_loss'] > 0 for event in status['events'])


def test_mt5_reconciles_changed_position_ticket_and_broker_protective_exit(f):
    proposal = activate(f)
    f.bot.step()
    position = f.api.positions[0]
    position.identifier = position.ticket
    position.ticket += 1000
    f.bot.step()
    entry = next(order for order in f.service.status()['orders'] if order['action'] == 'open')
    receipt = json.loads(entry['result'])
    assert entry['state'] == 'open'
    assert receipt['position_identifier'] == str(position.identifier)
    assert receipt['position_id'] == str(position.ticket)
    assert receipt['stop_loss'] and receipt['take_profit']

    # A broker-side protective exit need not carry the opening order's magic.
    from types import SimpleNamespace
    f.api.positions.clear()
    f.api.deals.append(SimpleNamespace(ticket=9999, order=9998, position_id=position.identifier,
        symbol='EURUSD', magic=0, comment='[tp]', entry=1, profit=5., commission=-.2, swap=-.1, fee=-.1))
    f.bot.step()
    entry = next(order for order in f.service.status()['orders'] if order['id'] == entry['id'])
    receipt = json.loads(entry['result'])
    assert entry['state'] == 'closed'
    assert receipt['realized_net'] == pytest.approx(4.5)
    assert receipt['exit_deals'] == ['9999']
    assert len(f.api.sent) == 1
    assert any(event['kind'] == 'reconciliation' and event['payload']['session'] == proposal['id']
               and event['payload']['evidence'].get('realized_net') == pytest.approx(4.5)
               and event['memory_receipt'] for event in f.service.status()['events'])


def test_mt5_refuses_to_manage_position_with_mixed_opening_orders(f):
    activate(f)
    f.bot.step()
    from types import SimpleNamespace
    opening = f.api.deals[0]
    f.api.deals.append(SimpleNamespace(**{**vars(opening), 'ticket': 9999, 'order': 9998, 'magic': 0}))
    f.api.price += .01
    f.bot.step()
    order = f.service.status()['orders'][0]
    assert order['state'] == 'unknown'
    assert 'mixed' in json.loads(order['result'])['reason']
    assert len(f.api.sent) == 1


def test_close_only_scope_resumes_owned_position_without_new_exposure(f):
    original = activate(f)
    f.bot.step()
    f.bot.step()
    entry = next(row for row in f.service.status()['orders'] if row['action'] == 'open')
    with pytest.raises(PermissionError, match='Original session'):
        f.service.propose('mt5', 'EURUSD', 60, close_order_id=entry['id'])
    f.service.stop(original['id'])
    proposal = f.service.propose('mt5', 'EURUSD', 60, close_order_id=entry['id'])
    assert proposal['spec']['position_actions'] == ['close']
    assert proposal['spec']['limits']['max_entries'] == 0
    f.api.price += .01
    f.bot.step()
    assert len(f.api.sent) == 1
    f.service.activate(proposal['id'], proposal['spec_hash'], threaded=False)
    lease = f.service.admission.acquire('trading_cycle')['token']
    try:
        with pytest.raises(PermissionError, match='Action outside approved'):
            f.service.pm.check_trading(f.gateway, proposal['id'], f.service.runtime_id, lease, 'open')
    finally:
        f.service.admission.finish(lease)
    for _ in range(4):
        f.bot.step()
    assert len(f.api.sent) == 2
    assert 'position' in f.api.sent[-1]
    orders = f.service.status()['orders']
    close = next(row for row in orders if row['action'] == 'close')
    assert close['session_id'] == proposal['id'] and close['state'] == 'closed'
    assert json.loads(close['payload'])['originating_order'] == entry['id']
    assert json.loads(close['payload'])['exit_reason']
    assert json.loads(close['result'])['realized_net'] == pytest.approx(4.8)
    assert f.service.session(proposal['id'])['entries'] == 0
    outcomes = [event for event in f.service.status()['events'] if event['kind'] == 'trading_outcome']
    assert len(outcomes) == 1
    assert outcomes[0]['payload']['order'] == entry['id']
    assert outcomes[0]['memory_receipt']


def test_close_only_scope_refuses_unknown_order(f):
    with pytest.raises(PermissionError, match='matching Core-owned'):
        f.service.propose('mt5','EURUSD',60,close_order_id='0'*64)
    assert not f.api.sent


def switch_to_xm(f):
    from types import SimpleNamespace
    f.api.ACCOUNT_TRADE_MODE_REAL = 2
    f.api.account = SimpleNamespace(**{**vars(f.api.account), 'login':100000001,
        'server':'XMZA-MT5 12', 'company':'XM', 'trade_mode':2})


def test_mt5_switch_suspends_grant_and_never_rearms(f):
    proposal = activate(f)
    demo = f.api.account
    switch_to_xm(f)
    f.bot.step()
    status = f.service.status()
    assert status['mt5_accounts']['active']['environment'] == 'live'
    assert status['mt5_accounts']['active']['login'] == '100000001'
    assert f.service.session(proposal['id'])['state'] == 'interrupted'
    assert not f.api.sent
    f.api.account = demo
    f.bot.step()
    status = f.service.status()
    assert status['mt5_accounts']['active']['environment'] == 'demo'
    assert len(status['mt5_accounts']['known']) == 2
    assert f.service.session(proposal['id'])['state'] == 'interrupted'
    assert not f.api.sent
    assert any(e['kind'] == 'mt5_connection_changed' for e in status['events'])


def test_mt5_switch_after_delivery_guard_does_not_send(f, monkeypatch):
    proposal = activate(f)
    original = f.service.pm.check_trading

    def switched(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get('consume'):
            switch_to_xm(f)
        return result

    monkeypatch.setattr(f.service.pm, 'check_trading', switched)
    f.bot.step()
    assert not f.api.sent
    status = f.service.status()
    assert f.service.session(proposal['id'])['state'] == 'interrupted'
    assert status['orders'][0]['state'] == 'rejected'


def test_mt5_switch_preserves_original_position_ownership(f):
    proposal = activate(f)
    f.bot.step()
    f.bot.step()
    opened = next(o for o in f.service.status()['orders'] if o['action']=='open')
    switch_to_xm(f)
    f.bot.step()
    status = f.service.status()
    assert f.service.session(proposal['id'])['state'] == 'interrupted'
    assert status['orders'][0]['id'] == opened['id']
    assert status['orders'][0]['account'] != status['mt5_accounts']['active']['identity']
    assert len(f.api.sent) == 1


def test_mt5_unknown_and_disconnected_are_distinct(f, monkeypatch):
    f.api.account.trade_mode = 99
    assert f.service.status()['mt5_accounts']['active']['environment'] == 'unknown'
    monkeypatch.setattr(f.api, 'terminal_info', lambda: None)
    registry = f.service.status()['mt5_accounts']
    assert not registry['connected'] and registry['active'] is None
    assert registry['known'][0]['last_verified'] is not None
    assert not f.api.sent


def test_mt5_unavailable_selected_symbol_is_not_a_disconnect(f):
    result = f.bot.bridge.bridge.snapshot('unavailable', allow_symbol_fallback=True)
    assert result['connected'] and result['unavailable_symbol'] == 'unavailable'
    assert result['symbol'] is None and result['account']['environment'] == 'demo'


@pytest.mark.parametrize('broker,server',[('XM Global Limited','XMGlobal-MT5 12'),('MetaQuotes Ltd.','MetaQuotes-Demo')])
def test_local_demo_volume_editor_for_xm_and_mt5(f,monkeypatch,broker,server):
    monkeypatch.delenv('NIBLIT_AUTO_MAX_LOTS',raising=False)
    f.api.account.company=broker;f.api.account.server=server
    f.bridge.snapshot('EURUSD');f.bridge.snapshot('EURUSD')
    f.orders.autonomous_max_volume=.10
    p=f.service.propose('mt5','EURUSD',60,{'max_volume':.03,'max_positions':1})
    assert p['spec']['limits']['max_volume']==.03
    f.service.activate(p['id'],p['spec_hash'],threaded=False);f.bot.step()
    assert len(f.api.sent)==1,f.bot.error
    assert f.api.sent[0]['volume']==.03
    f.api.account.trade_mode=2
    with pytest.raises(PermissionError):f.service.propose('mt5','EURUSD',60,{'max_volume':.03})
    assert len(f.api.sent)==1


def test_volume_policy_drop_invalidates_existing_review(f,monkeypatch):
    monkeypatch.delenv('NIBLIT_AUTO_MAX_LOTS',raising=False)
    f.orders.autonomous_max_volume=.10
    p=f.service.propose('mt5','EURUSD',60,{'max_volume':.03})
    f.orders.autonomous_max_volume=.01
    with pytest.raises(PermissionError):f.service.activate(p['id'],p['spec_hash'],threaded=False)
    assert not f.api.sent
