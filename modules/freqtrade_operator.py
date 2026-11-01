"""Explicit human Freqtrade commands; never registered as assistant tools."""
from __future__ import annotations

import base64
import json
import os
from urllib.request import Request, ProxyHandler, build_opener

LIVE_ACK = 'I_UNDERSTAND_LIVE_TRADING_RISK'


def _request(method, path):
    base = os.getenv('NIBLIT_FREQTRADE_BASE_URL', 'http://127.0.0.1:18080').rstrip('/')
    if base.endswith('/api/v1'):
        base = base[:-7]
    user = os.getenv('NIBLIT_FREQTRADE_USERNAME', '')
    password = os.getenv('NIBLIT_FREQTRADE_PASSWORD', '')
    if not user or not password:
        raise RuntimeError('Start Niblit using the Freqtrade profile launcher to load private API credentials')
    token = base64.b64encode(f'{user}:{password}'.encode()).decode()
    req = Request(base + '/api/v1/' + path, method=method,
                  headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'},
                  data=b'{}' if method == 'POST' else None)
    with build_opener(ProxyHandler({})).open(req, timeout=10) as response:
        return json.load(response)


def handle_freqtrade_command(text):
    parts = text.strip().split()
    action = parts[1].lower() if len(parts) > 1 else 'status'
    try:
        if action in {'status', 'health', 'balance', 'trades'}:
            if len(parts) > 2:
                return {'status': 'rejected', 'error': 'This read-only command takes no arguments'}
            path = {'status': 'show_config', 'health': 'ping', 'balance': 'balance', 'trades': 'trades?limit=20'}[action]
            data = _request('GET', path)
            if action == 'status':
                # Project selected public fields; never echo a provider config.
                data = {key: data.get(key) for key in ('state', 'dry_run', 'strategy', 'exchange', 'timeframe', 'max_open_trades')}
            return {'status': 'success', 'result': data}
        if action not in {'start', 'stop'}:
            return {'status': 'rejected', 'error': 'Use freqtrade status, health, balance, trades, start dry-run, start live <acknowledgement>, or stop'}
        if os.getenv('NIBLIT_FREQTRADE_ALLOW_CONTROL') != 'true':
            return {'status': 'rejected', 'error': 'Freqtrade human controls require the Freqtrade profile launcher'}
        if action == 'stop':
            if len(parts) != 2:
                return {'status': 'rejected', 'error': 'Usage: freqtrade stop'}
            return {'status': 'success', 'result': _request('POST', 'stop')}
        requested = parts[2].lower() if len(parts) >= 3 else ''
        if requested not in {'dry-run', 'live'}:
            return {'status': 'rejected', 'error': 'Specify start dry-run or start live with the live acknowledgement'}
        if requested == 'live' and (len(parts) != 4 or parts[3] != LIVE_ACK):
            return {'status': 'rejected', 'error': 'Live start requires the explicit acknowledgement: ' + LIVE_ACK}
        if requested == 'dry-run' and len(parts) != 3:
            return {'status': 'rejected', 'error': 'Usage: freqtrade start dry-run'}
        actual = _request('GET', 'show_config').get('dry_run')
        if type(actual) is not bool or actual != (requested == 'dry-run'):
            return {'status': 'rejected', 'error': 'Requested mode does not match the authenticated Freqtrade engine'}
        return {'status': 'success', 'result': _request('POST', 'start')}
    except Exception as exc:
        # No exception body/provider payload or credentials are returned.
        return {'status': 'unavailable', 'error': 'Freqtrade command unavailable: ' + type(exc).__name__}
