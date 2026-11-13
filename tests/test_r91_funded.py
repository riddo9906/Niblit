import pytest

from modules.core_trading_sessions import CoreTradingSessions
from modules.funded_risk import BREACHES, MAXIMUMS, MINIMUMS, evaluate, net_costs
from modules.strategy_manager import replay_context
from modules.trading_session_selftest import fixture


def case():
    account = dict(broker='XM',terminal_id='terminal',login='fixture',server='XM test',
                   environment='live',currency='USD')
    policy = dict(account=account.copy(),version='test-v1',authorization_id='fixture',
                  starts=100,expires=200,revoked=False,symbols=['EURUSD'],strategies=['trend_v1'],
                  limits={**dict.fromkeys(MAXIMUMS.values(), 10),**dict.fromkeys(MINIMUMS.values(), 1)})
    evidence = dict(account=account,identity_verified=True,symbol='EURUSD',strategy='trend_v1',
                    action='open',connected=True,quote_fresh=True,contract_verified=True,
                    protective_stop=True,consensus_complete=True,context_eligible=True,costs_complete=True)
    evidence.update(dict.fromkeys(BREACHES,False))
    evidence.update(dict.fromkeys(MAXIMUMS,1))
    evidence.update(dict.fromkeys(MINIMUMS,1))
    return policy,evidence


@pytest.mark.parametrize('field', list(MAXIMUMS))
def test_each_maximum_fails_closed(field):
    policy,evidence=case()
    evidence[field]='10.00001'
    decision=evaluate(policy,evidence,now=150)
    assert decision['decision']=='REJECT'
    assert MAXIMUMS[field]+'_breach' in decision['reasons']


@pytest.mark.parametrize('field', list(MINIMUMS))
def test_each_minimum_fails_closed(field):
    policy,evidence=case()
    evidence[field]='0.999'
    assert MINIMUMS[field]+'_breach' in evaluate(policy,evidence,now=150)['reasons']


def test_pass_is_not_authority_and_wrong_server_or_expiry_fail():
    policy,evidence=case()
    decision=evaluate(policy,evidence,now=150)
    assert decision['decision']=='PASS' and not decision['execution_enabled']
    evidence['account']['server']='wrong'
    reasons=evaluate(policy,evidence,now=200)['reasons']
    assert 'account_binding_mismatch' in reasons and 'outside_authorization_window' in reasons


def test_material_costs_are_never_inferred_zero():
    values=dict(volume='.01',currency='USD',now=150)
    schedule=dict(currency='USD',source='fixture',verified_at=100,expires=200,
                  minimum_commission='.2',round_trip_per_lot='10',
                  financing_upper_bound='.3',slippage_upper_bound='.5')
    out=net_costs('4','-2',schedule=schedule,**values)
    assert out['status']=='ESTIMATED' and out['net_target']=='3.0' and out['net_stop']=='-3.0'
    assert net_costs('4','-2',schedule=schedule|{'expires':150},**values)['status']=='STALE'
    del schedule['financing_upper_bound']
    assert not net_costs('4','-2',schedule=schedule,**values)['costs_complete']


def test_critical_breaker_survives_core_reconstruction(tmp_path):
    f=fixture(tmp_path)
    policy,evidence=case()
    evidence['uncertain_delivery']=True
    first=f.service.funded_preflight(policy,evidence)
    assert first['breaker_state']=='RECONCILIATION_REQUIRED'
    restarted=CoreTradingSessions(f.runtime,f.service.adapters,journal=f.service.journal,notify=lambda _:None)
    evidence['uncertain_delivery']=False
    after=restarted.funded_preflight(policy,evidence)
    assert 'breaker_reconciliation_required' in after['reasons']
    assert not f.api.sent
    with f.gateway.db() as db:
        assert db.execute('SELECT COUNT(*) FROM funded_risk_evaluations').fetchone()[0]==2


def test_replay_never_sees_future_price_or_adds_strategy_votes():
    rows=[dict(time=300*(i+1),open=100+i,high=101+i,low=99+i,close=100+i) for i in range(65)]
    as_of=300*61
    baseline=list(replay_context({'M5':rows},[as_of]))
    rows[-1]['close']=10000
    assert list(replay_context({'M5':rows},[as_of]))==baseline
    assert len(baseline[0]['assessment']['candidates'])==6
    assert max(baseline[0]['input_m5_timestamps'])+300 <= as_of


def test_live_demo_proposal_route_persists_rejection_without_broker_command(tmp_path):
    from types import SimpleNamespace
    f = fixture(tmp_path)
    demo = f.api.account
    f.api.ACCOUNT_TRADE_MODE_REAL = 2
    f.api.account = SimpleNamespace(**{**vars(demo), 'login': 100000001,
                                    'server': 'XMZA-MT5 12', 'company': 'XM', 'trade_mode': 2})
    with pytest.raises(PermissionError, match='Real-money execution disabled'):
        f.service.propose('mt5', 'EURUSD', 60)
    assert f.service.status()['funded_preflight']['reasons'] == ['policy_missing']
    assert not f.api.sent
    f.api.account = demo
    assert f.service.status()['funded_preflight'] is None
