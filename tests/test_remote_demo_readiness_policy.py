"""Remote demo readiness is not governed by local MT5 transport flags."""
from modules.trading_session_api import demo_control_policy, demo_readiness
from modules.trading_session_selftest import fixture


def test_verified_remote_demo_is_separate_from_local_flags(monkeypatch):
    monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY', '0')
    monkeypatch.delenv('NIBLIT_MT5_DEMO_DELIVERY_ENABLED', raising=False)
    monkeypatch.delenv('NIBLIT_FREQTRADE_DEMO_DELIVERY_ENABLED', raising=False)
    status = {'remote_demo': {'configured': True, 'verified': True},
              'emergency_stopped': True}
    policy = demo_control_policy(status)
    assert policy['platform_delivery_enabled'] == {
        'mt5': False, 'freqtrade': False, 'exness_demo': True}
    assert policy['emergency_stopped'] is True
    assert policy['activation_available'] is True

    status['remote_demo']['verified'] = False
    assert demo_control_policy(status)['platform_delivery_enabled']['exness_demo'] is False
    monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY', '1')
    assert demo_control_policy({'remote_demo': {'configured': True, 'verified': True}})['activation_available'] is False


def test_remote_readiness_does_not_create_preflight_ticket_or_reset_stop(tmp_path, monkeypatch):
    monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY', '0')
    f = fixture(tmp_path)
    original = f.service.adapters['mt5']
    class Remote:
        def status(self):
            return {'configured': True, 'verified': True}
        def snapshot(self, symbol):
            return original.snapshot(symbol)
        def reconcile(self, order):
            raise AssertionError('Readiness must not reconcile an order')
        def prepare(self, *args, **kwargs):
            raise AssertionError('Readiness must not create a remote ticket')
    f.service.adapters['exness_demo'] = Remote()
    try:
        f.service.stop(emergency=True)
        result = demo_readiness(f.service, 'exness_demo', 'EURUSD')
        assert result['review_only'] and result['execution_authorized'] is False
        assert result['remote_order_preflight'] == 'PENDING_AT_EXECUTION'
        assert result['risk_approval'] == 'NOT_GRANTED_REMOTE_PREFLIGHT_PENDING'
        assert result['external_send_count'] == 0
        assert not {'platform_delivery_disabled', 'missing_cost_bounds',
                    'dependency_unavailable'} & {x['code'] for x in result['blockers']}
        assert f.service.status()['emergency_stopped'] is True
        assert f.api.sent == []
    finally:
        f.service.shutdown()
