from unittest.mock import Mock

import pytest

import modules.freqtrade_operator as ft


@pytest.fixture
def api_request(monkeypatch):
    stub = Mock()
    monkeypatch.setattr(ft, '_request', stub)
    monkeypatch.setenv('NIBLIT_FREQTRADE_ALLOW_CONTROL', 'true')
    return stub


@pytest.mark.parametrize('actual,invocation', [(False, 'freqtrade start dry-run'), (True, 'freqtrade start live ' + ft.LIVE_ACK), (None, 'freqtrade start dry-run')])
def test_mode_mismatch_never_posts(api_request, actual, invocation):
    api_request.return_value = {'dry_run': actual}
    assert ft.handle_freqtrade_command(invocation)['status'] == 'rejected'
    assert api_request.call_args_list == [(('GET', 'show_config'),)]


def test_live_start_needs_explicit_ack_before_any_request(api_request):
    assert ft.handle_freqtrade_command('freqtrade start live')['status'] == 'rejected'
    api_request.assert_not_called()


def test_no_control_grant_never_posts(api_request, monkeypatch):
    monkeypatch.delenv('NIBLIT_FREQTRADE_ALLOW_CONTROL')
    assert ft.handle_freqtrade_command('freqtrade stop')['status'] == 'rejected'
    api_request.assert_not_called()


def test_dry_start_checks_identity_then_posts(api_request):
    api_request.side_effect = [{'dry_run': True}, {'status': 'starting'}]
    assert ft.handle_freqtrade_command('freqtrade start dry-run')['status'] == 'success'
    assert api_request.call_args_list == [(('GET', 'show_config'),), (('POST', 'start'),)]


def test_live_route_is_verified_with_a_mock_only(api_request):
    api_request.side_effect = [{'dry_run': False}, {'status': 'starting'}]
    assert ft.handle_freqtrade_command('freqtrade start live ' + ft.LIVE_ACK)['status'] == 'success'
    assert api_request.call_args_list == [(('GET', 'show_config'),), (('POST', 'start'),)]


def test_status_does_not_return_private_configuration(api_request):
    api_request.return_value = {'state': 'stopped', 'dry_run': True, 'password': 'private', 'exchange': 'binance'}
    result = ft.handle_freqtrade_command('freqtrade status')
    assert 'password' not in result['result']
    api_request.assert_called_once_with('GET', 'show_config')


def test_errors_do_not_echo_credentials(api_request):
    api_request.side_effect = RuntimeError('private password')
    result = ft.handle_freqtrade_command('freqtrade balance')
    assert result['status'] == 'unavailable'
    assert 'private' not in result['error']


def test_operator_subcommand_is_classified_as_trading():
    from modules.operator_commands import _risk
    assert _risk('freqtrade status') == 'READ_ONLY'
    assert _risk('freqtrade start live ' + ft.LIVE_ACK) == 'TRADING'
