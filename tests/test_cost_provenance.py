from datetime import datetime,timezone
import pytest
from modules.trading_values import fee_resolution
from modules.position_intelligence import strategy_ownership

NOW=1800000000
def replay(rate=.0002,**extra):
    return dict(observed_at=datetime.fromtimestamp(NOW-1,timezone.utc).isoformat(),config_sha256='config',
        ccxt_version='installed',method_sha256='code',records=[{'symbol':'BTC/USDT:USDT',
            'purpose':'native_entry_bookkeeping','rate':rate,'market_maker':rate,'default_fees':{'maker':rate}}],**extra)
def resolve(**args):
    return fee_resolution(symbol='BTC/USDT:USDT',config_hash='config',now=NOW,**args)

def test_installed_native_maker_replay_is_not_account_fee_or_authority():
    result=resolve(replay=replay(),quote={'public_market':{'maker':.0002,'taker':.0005}})
    assert result['status']=='INSTALLED_CODE_REPLAY' and result['rate']==.0002
    assert not result['execution_fee_verified'] and not result['execution_authorized']

def test_known_override_precedence_and_conflict():
    assert resolve(private_override=.001)['rate']==.001
    assert resolve(private_override=.001,engine_override=.002)['status']=='CONFLICT'
    assert resolve(private_override=0)['status']=='EXPLICIT_CONFIGURATION'

def test_zero_fallback_is_rejected_but_explicit_zero_is_attributed():
    data=replay(0);data['records'][0].update(market_maker=None,default_fees={})
    assert resolve(replay=data)['status']=='ZERO_FALLBACK_REJECTED'
    assert resolve(engine_override=0)['rate']==0

def test_public_or_historical_rates_cannot_replace_missing_native_evidence():
    result=resolve(quote={'public_market':{'maker':.0002,'taker':.0005}})
    assert result['status']=='UNKNOWN' and result['rate'] is None
    assert result['historical_fees_eligible_for_selection'] is False

@pytest.mark.parametrize('value',[True,-.1,float('nan'),.5])
def test_invalid_fee_sources_fail_closed(value):
    assert resolve(private_override=value)['status']=='INVALID'

def test_stale_binding_and_same_role_conflicts_are_distinct():
    data=replay();data['observed_at']=datetime.fromtimestamp(NOW-901,timezone.utc).isoformat()
    assert resolve(replay=data)['status']=='STALE'
    data=replay();data['config_sha256']='other'
    assert resolve(replay=data)['status']=='BINDING_MISMATCH'
    assert resolve(replay=replay(),quote={'public_market':{'maker':.0003}})['status']=='CONFLICT'

def test_original_native_ownership_cannot_be_aliased_into_core_authority():
    position={'strategy':'NiblitLabManager','enter_tag':'niblit_lab:trend_v1:sell'}
    result=strategy_ownership(position,{'state':'matched_engine_record'},'NiblitLabManager')
    assert result['owner']=='native_niblit_lab' and result['entry_rule']=='trend_v1'
    assert result['core_entry_decision'].startswith('UNKNOWN')
    assert not result['core_may_adopt_position'] and not result['duplicate_authority_allowed']
    assert position['strategy']=='NiblitLabManager'
    assert strategy_ownership(position,{'state':'record_mismatch'},'NiblitLabManager')['owner']=='UNKNOWN'

def test_core_tag_alone_cannot_prove_an_authorized_decision():
    result=strategy_ownership({'strategy':'NiblitCoreManaged','enter_tag':'niblit_core:ticket'},
        {'state':'matched_engine_record'},'NiblitCoreManaged')
    assert result['status']=='CORE_RECEIPT_VERIFICATION_REQUIRED'
    assert result['execution_authorized'] is False
