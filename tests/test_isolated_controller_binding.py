import pytest
from modules.trading_desk import Desk
from modules.trading_session_selftest import freq_fixture

@pytest.mark.parametrize('base',['http://evil:18080/api/v1/','https://127.0.0.1:18080/api/v1/',
 'http://user:secret@127.0.0.1:18080/api/v1/','http://127.0.0.1:18080/api/v1/?x=1'])
def test_explicit_binding_does_not_redirect_credentials(tmp_path,base):
    with pytest.raises(ValueError):Desk(tmp_path,config_path=tmp_path/'config.json',api_base=base)

def test_stopped_engine_can_only_produce_non_deliverable_draft(tmp_path):
    f=freq_fixture(tmp_path);f.api.config['state']='stopped'
    adapter=f.service.adapters['freqtrade'];s=adapter.snapshot('BTC/USDT:USDT')
    from modules.core_trading_sessions import configured_limits
    with f.desk.db() as db:before=db.execute('select count(*) from tickets').fetchone()[0]
    draft=adapter.draft_entry(s,'buy',configured_limits())
    assert draft['quantity']>0 and 'ticket' not in draft
    with f.desk.db() as db:assert db.execute('select count(*) from tickets').fetchone()[0]==before
    with pytest.raises(PermissionError,match='Stopped'):adapter.prepare(s,'buy',configured_limits())
    assert f.api.sent==[]

@pytest.mark.parametrize('field,value',[('environment','live'),('fresh',False),('side','wait')])
def test_draft_preserves_market_and_mode_boundaries(tmp_path,field,value):
    f=freq_fixture(tmp_path);adapter=f.service.adapters['freqtrade'];s=adapter.snapshot('BTC/USDT:USDT')
    side='buy'
    if field=='fresh':s['quote']['fresh']=value
    elif field=='side':side=value
    else:s[field]=value
    from modules.core_trading_sessions import configured_limits
    with pytest.raises((ValueError,PermissionError)):adapter.draft_entry(s,side,configured_limits())
    assert f.api.sent==[]

def test_trading_scope_is_in_immutable_proposal_and_cannot_cross_namespaces(tmp_path):
    from modules.permission_manager import PermissionManager
    f=freq_fixture(tmp_path)
    f.service.pm=PermissionManager(trading_scope={'namespace':'candidate_test','principal':'candidate_operator'})
    proposal=f.service.propose('freqtrade','BTC/USDT:USDT',60)
    assert proposal['spec']['memory_scope']==f.service.pm.trading_scope
    other=PermissionManager()
    with pytest.raises(PermissionError,match='scope changed'):
        other.activate_trading(f.gateway,proposal['id'],proposal['spec_hash'],f.service.runtime_id)
    assert f.api.sent==[]

@pytest.mark.parametrize('scope',[{'namespace':'x'},{'namespace':True,'principal':'x'},{'namespace':'','principal':'x'}])
def test_invalid_memory_scope_denied(scope):
    from modules.permission_manager import PermissionManager
    with pytest.raises(ValueError):PermissionManager(trading_scope=scope)
