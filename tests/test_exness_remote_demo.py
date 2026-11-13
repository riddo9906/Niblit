"""Broker doubles only: shared real Core/session/ticket code, no real orders."""
import copy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace as Obj
import pytest

GATEWAY=Path(__file__).resolve().parents[1]/'deploy/vps-gateway'
sys.path.insert(0,str(GATEWAY))
import demo_execution as demo
from modules.mt5_bridge import MT5Bridge
from modules.mt5_orders import MAGIC
from modules.core_trading_sessions import configured_limits,CoreTradingSessions
from modules.remote_demo_adapter import RemoteDemoAdapter
from modules.trading_session_selftest import FixtureMT5,FixtureGateway
from modules.memory_laboratory.runtime import MemoryRuntime


@pytest.fixture
def service(tmp_path,monkeypatch):
    api=FixtureMT5();api.account.company='Exness fixture';api.account.server='Exness-MT5Trial10'
    api.account.login=123;api.info.name='BTCUSDm';api.info.currency_base='BTC'
    api.price=75000.;api.info.trade_contract_size=1.;api.info.point=.01;api.info.digits=2
    api.info.trade_tick_size=.01;api.info.trade_freeze_level=0
    api.rates=[dict(time=api.bar-(59-i)*300,open=74970.+i*.5,high=74971.+i*.5,
                    low=74969.+i*.5,close=74970.5+i*.5,tick_volume=10) for i in range(60)]
    api.order_calc_profit=lambda side,symbol,volume,entry,exit:(exit-entry)*volume*(1 if side==0 else -1)
    terminal=Obj(connected=True,trade_allowed=True,tradeapi_disabled=False,build=1,
                 path=str(tmp_path),data_path=str(tmp_path/'data'))
    api.terminal_info=lambda:terminal
    api.symbol_info=lambda s:api.info if s=='BTCUSDm' else None
    exe=tmp_path/'terminal64.exe';exe.write_text('fixture')
    cfg={'terminal':str(exe),'account':MT5Bridge().account_record(api,api.account,terminal),'symbols':['BTCUSDm']}
    monkeypatch.setattr(demo,'existing_terminal',lambda _:100)
    s=demo.DemoService(cfg,tmp_path/'state',api)
    s.bridge.snapshot('BTCUSDm');s.bridge.snapshot('BTCUSDm')
    return s,api,terminal


def prepare(s):return s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy','limits':configured_limits(),'position':None})


@pytest.mark.parametrize('field,value',[('trade_mode',2),('trade_mode',1),('login',999),('server','Exness-MT5Trial11'),('company','other')])
def test_changed_account_rejected_at_final_sdk_boundary(service,field,value):
    s,api,t=service;p=prepare(s)
    setattr(api.account,field,value)
    with pytest.raises(PermissionError):s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    assert not api.sent


@pytest.mark.parametrize('field,value',[('connected',False),('trade_allowed',False),('tradeapi_disabled',True),('data_path','different')])
def test_terminal_change_or_permissions_never_sends(service,field,value):
    s,api,t=service;p=prepare(s);setattr(t,field,value)
    try:s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    except (PermissionError,ValueError):pass
    assert not api.sent


def test_idempotent_demo_delivery_and_no_new_authority_on_restart(service):
    s,api,t=service;p=prepare(s)
    first=s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    again=s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    assert first['state']==again['state']=='submitted' and len(api.sent)==1
    other=demo.DemoService(s.cfg,s.state,api)
    assert other.dispatch('status',{})['execution_at_startup'] is False


def test_ambiguous_delivery_is_durable_and_never_retried(service):
    s,api,t=service;p=prepare(s);api.behavior='timeout'
    assert s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})['state']=='unknown'
    assert s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})['state']=='unknown'
    assert len(api.sent)==1
    with pytest.raises(ValueError):prepare(s)


def test_gateway_restart_rejects_old_preview(service):
    s,api,t=service;p=prepare(s);other=demo.DemoService(s.cfg,s.state,api)
    assert other.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})['state']=='rejected'
    assert not api.sent


def test_persistent_emergency_stop(service):
    s,api,t=service;p=prepare(s);s.dispatch('emergency-stop',{})
    other=demo.DemoService(s.cfg,s.state,api)
    assert other.dispatch('status',{})['emergency_stopped']
    with pytest.raises(PermissionError):other.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    assert not api.sent


@pytest.mark.parametrize('expires',[0,float('nan'),float('inf'),True])
def test_expired_or_invalid_scope(service,expires):
    s,api,t=service;p=prepare(s)
    with pytest.raises(PermissionError):s.dispatch('submit',{'ticket':p['ticket'],'expires':expires})
    assert not api.sent


def test_symbol_and_risk_ceiling(service):
    s,api,t=service
    with pytest.raises(PermissionError):s.dispatch('market',{'symbol':'EURUSD'})
    bad=configured_limits()|{'max_volume':.1}
    with pytest.raises(PermissionError):s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy','limits':bad})
    assert not api.sent


@pytest.mark.parametrize('change',[{'action':6},{'volume':.1},{'magic':0},{'symbol':'EURUSD'},{'sl':0}])
def test_final_boundary_rejects_unsupported_mutation(service,change):
    s,api,t=service
    request={'action':1,'volume':.01,'magic':MAGIC,'type':0,'symbol':'BTCUSDm','sl':159,'tp':162}|change
    with pytest.raises(PermissionError):s.bridge._api.order_send(request)
    assert not api.sent


def test_existing_six_strategy_core_to_remote_ticket_pipeline(service,tmp_path,monkeypatch):
    s,api,t=service
    # In-process transport double only; real Core/permission/admission/ticket logic.
    adapter=object.__new__(RemoteDemoAdapter);adapter.profile={'account':s.cfg['account']}
    adapter.last_status=None;adapter.call=lambda action,body=None:s.dispatch(action,body or {})
    runtime=MemoryRuntime(FixtureGateway(tmp_path/'canonical.sqlite'))
    monkeypatch.delenv('NIBLIT_VPS_GATEWAY_PROFILE',raising=False)
    core=CoreTradingSessions(runtime,{'exness_demo':adapter},journal=tmp_path/'decisions.sqlite',notify=lambda _:None)
    bot=core.observe('exness_demo','BTCUSDm',threaded=False)
    bot.step();assert not api.sent and len(bot.manager['candidates'])==6
    p=core.propose('exness_demo','BTCUSDm',60,{'max_entries':1,'max_positions':1})
    assert p['spec']['account_binding']==s.cfg['account']
    core.activate(p['id'],p['spec_hash'],threaded=False);bot.step()
    assert len(api.sent)==1,bot.error
    assert api.sent[0]['volume']==.01 and api.sent[0]['sl'] and api.sent[0]['tp']
    bot.step();assert len(api.sent)==1
    core.stop(emergency=True);assert s.dispatch('status',{})['emergency_stopped']


def test_remote_client_requires_core_scope_before_network():
    adapter=object.__new__(RemoteDemoAdapter);called=[];adapter.call=lambda *a:called.append(a)
    with pytest.raises(PermissionError):adapter.submit({'ticket':'x'},lambda:None)
    with pytest.raises(PermissionError):adapter.submit({'ticket':'x'},lambda:{'environment':'live','expires':time.time()+60})
    assert called==[]


def test_demo_scope_cannot_be_replaced_by_read_only_gateway_credential(service):
    import http.client,threading
    from gateway import GatewayServer,Handler
    s,api,t=service
    with GatewayServer(('127.0.0.1',0),Handler) as server:
        server.authorization=b'Bearer '+b'a'*64
        server.demo_authorization=b'Bearer '+b'b'*64;server.demo=s
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            c=http.client.HTTPConnection('127.0.0.1',server.server_port)
            c.request('GET','/demo/status',headers={'Authorization':'Bearer '+'a'*64})
            r=c.getresponse();r.read();assert r.status==401;c.close()
            c=http.client.HTTPConnection('127.0.0.1',server.server_port)
            c.request('GET','/demo/status',headers={'Authorization':'Bearer '+'b'*64})
            r=c.getresponse();payload=json.loads(r.read());assert r.status==200
            assert payload['result']['account']['environment']=='demo'
            c.close()
        finally:server.shutdown();thread.join()
    assert not api.sent


def test_partial_fill_blocks_new_preparation(service):
    s,api,t=service;p=prepare(s);api.behavior='partial'
    assert s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})['state']=='partial'
    with pytest.raises(PermissionError):prepare(s)
    assert len(api.sent)==1


def test_price_review_rejection_is_proven_unsent_and_durable(service):
    s,api,t=service
    for row in api.rates:row.update(high=75050.,low=74950.)
    p=prepare(s);api.price+=10
    result=s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    assert result['state']=='rejected'
    assert result['broker']=={'reason_code':'price_moved_outside_review','delivery_began':False}
    with s.orders.db() as db:
        assert db.execute('SELECT state FROM mt5_tickets WHERE id=?',(p['ticket'],)).fetchone()[0]=='rejected'
    assert not api.sent


def test_account_changes_between_last_boundary_checks_never_sends(service):
    s,api,t=service
    first=copy.copy(api.account);second=copy.copy(api.account);second.trade_mode=2
    answers=iter((first,second));api.account_info=lambda:next(answers)
    with pytest.raises(PermissionError):
        s.bridge._api.order_send({'action':1,'volume':.01,'magic':MAGIC,'type':0,'symbol':'BTCUSDm','sl':159,'tp':162})
    assert not api.sent


def test_crypto_drift_is_capped_and_preserves_original_point(service):
    s,api,t=service
    api.price=75000.;api.info.trade_contract_size=1.
    api.order_calc_profit=lambda side,symbol,volume,entry,exit:(exit-entry)*volume*(1 if side==0 else -1)
    p=prepare(s)
    with s.orders.db() as db:
        review=json.loads(db.execute('SELECT body FROM mt5_tickets WHERE id=?',(p['ticket'],)).fetchone()[0])['review']
    assert review['point']==.01
    assert review['max_review_price_drift']==pytest.approx(7.5,abs=.001)
    api.price+=.25
    assert s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})['state']=='submitted'
    assert len(api.sent)==1 and api.sent[0]['volume']==.01


@pytest.mark.parametrize('fraction',[.001,float('nan'),True,-.001])
def test_review_drift_cannot_exceed_hard_ceiling(service,tmp_path,fraction):
    from modules.mt5_orders import DemoOrders
    s,api,t=service
    with pytest.raises(ValueError):DemoOrders(s.bridge,tmp_path/'bad.sqlite',price_drift_fraction=fraction)
    assert not api.sent


def test_unaffordable_structural_stop_is_rejected_not_squeezed(service):
    s,api,t=service
    with pytest.raises(ValueError,match='minimum volume exceeds risk budget'):
        s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy',
                   'limits':configured_limits()|{'risk_cash':.001},'position':None})
    assert not api.sent


def test_delivery_preserves_reviewed_protection_even_if_later_bars_change(service):
    s,api,t=service;p=prepare(s)
    sl,tp=p['stop_loss'],p['take_profit']
    for row in api.rates:row.update(high=76000.,low=74000.)
    result=s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    assert result['state']=='submitted'
    assert api.sent[0]['sl']==sl and api.sent[0]['tp']==tp


def test_core_scope_rejects_changed_protection_policy(service,tmp_path,monkeypatch):
    s,api,t=service;changed=False
    adapter=object.__new__(RemoteDemoAdapter);adapter.profile={'account':s.cfg['account']};adapter.last_status=None
    def call(action,body=None):
        result=s.dispatch(action,body or {})
        if changed and action=='snapshot':result['protection_policy']['version']='unapproved-policy/2'
        return result
    adapter.call=call
    monkeypatch.delenv('NIBLIT_VPS_GATEWAY_PROFILE',raising=False)
    core=CoreTradingSessions(MemoryRuntime(FixtureGateway(tmp_path/'policy.sqlite')),{'exness_demo':adapter},
                             journal=tmp_path/'policy-decisions.sqlite',notify=lambda _:None)
    p=core.propose('exness_demo','BTCUSDm',60)
    assert p['spec']['protection_policy']['version']=='crypto-atr-structure/1'
    core.activate(p['id'],p['spec_hash'],threaded=False);changed=True
    bot=core.bots[('exness_demo','BTCUSDm')];bot.step()
    assert not api.sent and 'protection policy changed' in bot.error


def test_market_protection_preview_is_read_only_and_broker_valued(service):
    s,api,t=service
    market=s.dispatch('market',{'symbol':'BTCUSDm'})
    assert market['protection_preview']['status']=='available'
    for side in ('buy','sell'):
        p=market['protection_preview'][side]
        assert p['estimated_stop_loss_at_minimum_volume']>0
        assert p['account_currency']=='USD' and p['broker_minimum_volume']==.01
        assert p['stop_distance']>3*market['quote']['spread']
    with s.orders.db() as db:assert db.execute('SELECT COUNT(*) FROM mt5_tickets').fetchone()[0]==0
    assert not api.sent


def test_unknown_broker_valuation_is_not_zero_in_protection_preview(service):
    s,api,t=service;api.order_calc_profit=lambda *a:None
    market=s.dispatch('market',{'symbol':'BTCUSDm'})
    assert market['protection_preview']['buy']['estimated_stop_loss_at_minimum_volume'] is None
    assert not api.sent


def test_three_sequential_demo_entries_and_fourth_denied(service,tmp_path,monkeypatch):
    s,api,t=service
    adapter=object.__new__(RemoteDemoAdapter);adapter.profile={'account':s.cfg['account']}
    adapter.last_status=None;adapter.call=lambda action,body=None:s.dispatch(action,body or {})
    runtime=MemoryRuntime(FixtureGateway(tmp_path/'multi-canonical.sqlite'))
    monkeypatch.delenv('NIBLIT_VPS_GATEWAY_PROFILE',raising=False)
    core=CoreTradingSessions(runtime,{'exness_demo':adapter},journal=tmp_path/'multi.sqlite',notify=lambda _:None)
    bot=core.observe('exness_demo','BTCUSDm',threaded=False)
    with pytest.raises(ValueError):core.propose('exness_demo','BTCUSDm',60,{'max_entries':4,'max_positions':1})
    p=core.propose('exness_demo','BTCUSDm',60,{'max_entries':3,'max_positions':1})
    core.activate(p['id'],p['spec_hash'],threaded=False)
    for number in range(1,4):
        bot.step()
        assert len(api.sent)==number,bot.error
        assert core.session(p['id'])['entries']==number
        assert len(api.positions)==1
        assert api.sent[-1]['volume']==.01 and api.sent[-1]['sl'] and api.sent[-1]['tp']
        bot.step();assert len(api.sent)==number  # Existing position cannot be duplicated.
        # Broker-double stop exit: keep confirmed deal identifiers, no real broker calls.
        position=api.positions.pop()
        api.deals.append(Obj(ticket=9000+number,order=8000+number,position_id=position.ticket,
            symbol='BTCUSDm',type=1,magic=MAGIC,comment='broker stop fixture',entry=1,
            profit=-1.,commission=0.,swap=0.,fee=0.))
        bot.step();assert len(api.sent)==number  # Same closed bar cannot re-enter.
        api.bar+=300
        for row in api.rates:row['time']+=300
    bot.step();assert len(api.sent)==3
    assert core.session(p['id'])['entries']==3


@pytest.mark.parametrize('lots',[.02,.05,.10])
def test_reviewed_larger_demo_volume_uses_existing_core_pipeline(service,tmp_path,monkeypatch,lots):
    original,api,t=service
    s=demo.DemoService(original.cfg,tmp_path/'larger-state',api,max_volume=.10)
    s.bridge.snapshot('BTCUSDm');s.bridge.snapshot('BTCUSDm')
    adapter=object.__new__(RemoteDemoAdapter);adapter.profile={'account':s.cfg['account']}
    adapter.last_status=None;adapter.call=lambda action,body=None:s.dispatch(action,body or {})
    monkeypatch.delenv('NIBLIT_VPS_GATEWAY_PROFILE',raising=False)
    monkeypatch.delenv('NIBLIT_AUTO_MAX_LOTS',raising=False)
    core=CoreTradingSessions(MemoryRuntime(FixtureGateway(tmp_path/'larger-canonical.sqlite')),
        {'exness_demo':adapter},journal=tmp_path/'larger-decisions.sqlite',notify=lambda _:None)
    p=core.propose('exness_demo','BTCUSDm',60,{'max_volume':lots,'max_entries':1,'max_positions':1})
    assert p['spec']['limits']['max_volume']==lots
    core.activate(p['id'],p['spec_hash'],threaded=False)
    bot=core.observe('exness_demo','BTCUSDm',threaded=False);bot.step()
    assert len(api.sent)==1,bot.error
    assert api.sent[0]['volume']==lots and api.sent[0]['sl'] and api.sent[0]['tp']
    assert s.dispatch('status',{})['funded_execution_enabled'] is False


@pytest.mark.parametrize('lots',[0,-.01,.11,float('nan'),float('inf'),True])
def test_invalid_or_excessive_autonomous_volume_ceiling_rejected(service,tmp_path,lots):
    s,api,t=service
    with pytest.raises(ValueError):demo.DemoService(s.cfg,tmp_path/'bad-volume',api,max_volume=lots)
    assert not api.sent


def test_larger_demo_still_blocks_live_and_default_and_missing_guard(service,tmp_path):
    original,api,t=service
    s=demo.DemoService(original.cfg,tmp_path/'scoped-volume',api,max_volume=.10)
    s.bridge.snapshot('BTCUSDm');s.bridge.snapshot('BTCUSDm')
    limits=configured_limits()|{'max_volume':.05}
    p=s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy','limits':limits})
    with pytest.raises(PermissionError):s.orders.confirm(p['ticket'])
    body=p['intent']
    with pytest.raises(ValueError):s.orders.preview(body)  # Manual tickets remain 0.01.
    api.account.trade_mode=2
    with pytest.raises(PermissionError):s.dispatch('submit',{'ticket':p['ticket'],'expires':time.time()+60})
    assert not api.sent


def test_broker_step_rounds_down_under_reviewed_maximum(service,tmp_path):
    old,api,t=service
    s=demo.DemoService(old.cfg,tmp_path/'step-volume',api,max_volume=.10)
    s.bridge.snapshot('BTCUSDm');s.bridge.snapshot('BTCUSDm')
    p=s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy','limits':configured_limits()|{'max_volume':.055}})
    assert p['intent']['volume']==.05


@pytest.mark.parametrize('broker,server',[('XM Global Limited','XMGlobal-MT5 12'),('MetaQuotes Ltd.','MetaQuotes-Demo')])
def test_other_pinned_demo_profiles_keep_final_demo_gate(service,tmp_path,broker,server):
    old,api,t=service;api.account.company=broker;api.account.server=server
    cfg={**old.cfg,'account':MT5Bridge().account_record(api,api.account,t)}
    path=tmp_path/'profile.json';path.write_text(json.dumps(cfg),encoding='utf-8')
    assert demo.load_demo_config(path)==cfg
    s=demo.DemoService(cfg,tmp_path/'generic-demo',api,max_volume=.10)
    assert s.dispatch('status',{})['account']['environment']=='demo'
    api.account.trade_mode=2
    with pytest.raises(PermissionError):s.dispatch('status',{})
    assert not api.sent



def test_broker_minimum_above_old_cap_is_supported_only_after_review(service,tmp_path):
    old,api,t=service
    api.info.volume_min=.10;api.info.volume_step=.10
    s=demo.DemoService(old.cfg,tmp_path/'minimum-volume',api,max_volume=.10)
    s.bridge.snapshot('BTCUSDm');s.bridge.snapshot('BTCUSDm')
    with pytest.raises(ValueError):
        s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy','limits':configured_limits()})
    p=s.dispatch('prepare',{'symbol':'BTCUSDm','side':'buy','limits':configured_limits()|{'max_volume':.10}})
    assert p['intent']['volume']==.10
    assert not api.sent



def test_new_demo_discovery_is_read_only_and_detects_live_transition(service,monkeypatch):
    import discover_demo
    s,api,t=service
    monkeypatch.setattr(discover_demo,'existing_terminal',lambda _:100)
    candidate=discover_demo.discover(api,Path(s.cfg['terminal']),['BTCUSDm'])
    assert candidate==s.cfg and not api.sent
    api.account.trade_mode=2
    with pytest.raises(PermissionError):discover_demo.discover(api,Path(s.cfg['terminal']),['BTCUSDm'])
    assert not api.sent
