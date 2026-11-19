"""Compatibility tests: legacy research flags do not create execution authority."""
from modules.tft_forecast import _configured_value
from modules.core_trading_sessions import configured_demo_profile


def test_empty_mt5_alias_falls_back_to_exness_demo_profile(monkeypatch):
    monkeypatch.setenv('NIBLIT_MT5_DEMO_PROFILE', '')
    monkeypatch.setenv('NIBLIT_EXNESS_DEMO_PROFILE', r'C:\fixture\exness-demo-profile.json')
    assert configured_demo_profile() == r'C:\fixture\exness-demo-profile.json'


def test_explicit_mt5_demo_profile_takes_precedence(monkeypatch):
    monkeypatch.setenv('NIBLIT_MT5_DEMO_PROFILE', '  mt5-demo-profile.json  ')
    monkeypatch.setenv('NIBLIT_EXNESS_DEMO_PROFILE', 'exness-demo-profile.json')
    assert configured_demo_profile() == 'mt5-demo-profile.json'


def test_old_tft_flag_is_honored_when_new_flag_is_absent(monkeypatch):
    monkeypatch.delenv("NIBLIT_TFT_ENABLED", raising=False)
    monkeypatch.setenv("TRADING_TFT_ENABLED", "0")
    assert _configured_value("NIBLIT_TFT_ENABLED", "TRADING_TFT_ENABLED", "1") == "0"


def test_new_tft_flag_takes_precedence(monkeypatch):
    monkeypatch.setenv("NIBLIT_TFT_ENABLED", "1")
    monkeypatch.setenv("TRADING_TFT_ENABLED", "0")
    assert _configured_value("NIBLIT_TFT_ENABLED", "TRADING_TFT_ENABLED", "1") == "1"


def test_legacy_horizon_fallback(monkeypatch):
    monkeypatch.delenv("NIBLIT_TFT_FORECAST_HORIZON", raising=False)
    monkeypatch.setenv("TRADING_TFT_HORIZON", "10")
    assert _configured_value("NIBLIT_TFT_FORECAST_HORIZON", "TRADING_TFT_HORIZON", "3") == "10"


def test_research_switches_do_not_grant_demo_or_funded_authority(monkeypatch):
    from modules.trading_session_api import demo_control_policy
    monkeypatch.setenv("TRADING_TFT_ENABLED", "1")
    monkeypatch.setenv("TRADING_KELLY_ENABLED", "1")
    monkeypatch.setenv("NIBLIT_RL_ENABLED", "1")
    monkeypatch.setenv("NIBLIT_DESKTOP_OBSERVATION_ONLY", "1")
    policy = demo_control_policy({"emergency_stopped": True, "remote_demo": {"configured": False}})
    assert policy["activation_available"] is False
    assert policy["delivery_authorized"] is False
    assert policy["funded_execution_available"] is False
    assert policy["delivery_blocker"] == "Installed desktop is observation-only"


def test_missing_demo_profile_is_reported_as_configuration_blocker(monkeypatch):
    from modules.trading_session_api import demo_control_policy
    monkeypatch.setenv("NIBLIT_DESKTOP_OBSERVATION_ONLY", "0")
    monkeypatch.delenv("NIBLIT_MT5_DEMO_DELIVERY_ENABLED", raising=False)
    monkeypatch.delenv("NIBLIT_FREQTRADE_DEMO_DELIVERY_ENABLED", raising=False)
    policy = demo_control_policy({"remote_demo": {"configured": False}})
    assert policy["activation_available"] is True
    assert policy["delivery_authorized"] is False
    assert "No verified demo delivery transport" in policy["delivery_blocker"]


def test_latched_stop_and_uncertain_order_are_visible_without_rearming(monkeypatch):
    from modules.trading_session_api import demo_control_policy
    monkeypatch.setenv("NIBLIT_DESKTOP_OBSERVATION_ONLY", "0")
    monkeypatch.delenv("NIBLIT_MT5_DEMO_DELIVERY_ENABLED", raising=False)
    monkeypatch.delenv("NIBLIT_FREQTRADE_DEMO_DELIVERY_ENABLED", raising=False)
    policy = demo_control_policy({"emergency_stopped": True,
        "orders": [{"adapter": "mt5", "state": "unknown"},
                   {"adapter": "mt5", "state": "closed"}],
        "remote_demo": {"configured": False}})
    assert policy["recovery"] == {
        "stop_latched": True, "requires_reviewed_scope": True,
        "unresolved_orders_visible": 1, "broker_reconciliation_required": True,
        "transport_configured": False, "automatic_rearm_allowed": False,
        "activation_ready": False,
        "activation_blockers": ["No verified demo delivery transport",
                                "Unresolved broker delivery requires reconciliation",
                                "Emergency stop requires explicit reviewed demo rearm"]}
    assert policy["delivery_authorized"] is False
    assert policy["funded_execution_available"] is False


def test_remote_demo_activation_projection_requires_verified_transport_and_no_unresolved_claims(monkeypatch):
    from modules.trading_session_api import demo_control_policy
    monkeypatch.setenv('NIBLIT_DESKTOP_OBSERVATION_ONLY', '0')
    monkeypatch.delenv('NIBLIT_MT5_DEMO_DELIVERY_ENABLED', raising=False)
    monkeypatch.delenv('NIBLIT_FREQTRADE_DEMO_DELIVERY_ENABLED', raising=False)
    status={'remote_demo': {'configured': True, 'verified': True},
            'orders': [], 'emergency_stopped': False}
    policy=demo_control_policy(status)
    assert policy['platform_delivery_enabled']['exness_demo'] is True
    assert policy['recovery']['activation_ready'] is True
    assert policy['recovery']['activation_blockers'] == []
    status['emergency_stopped']=True
    policy=demo_control_policy(status)
    assert policy['activation_available'] is True  # reviewed rearm is possible
    assert policy['recovery']['activation_ready'] is False
    assert 'Emergency stop requires explicit reviewed demo rearm' in policy['recovery']['activation_blockers']
    assert policy['funded_execution_available'] is False
