import sys
import os
from modules.trading_runtime_client import TradingRuntimeClient

def test_direct_packaged_launch_uses_recorded_feed_and_external_account(tmp_path, monkeypatch):
    bundle = tmp_path / 'bundle'
    worker = bundle / 'freqtrade/niblit-freqtrade-worker.exe'
    worker.parent.mkdir(parents=True)
    worker.touch()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(bundle / 'niblit.exe'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    for key in ('NIBLIT_TRADING_BACKEND', 'NIBLIT_MARKET_DATA_PROVIDER', 'NIBLIT_MARKET_DATA_TIMEFRAME',
                'NIBLIT_PAPER_STATE_FILE', 'NIBLIT_EXECUTION_DB', 'NIBLIT_TRADING_CONTROL_FILE',
                'NIBLIT_REPLAY_STATE_FILE', 'NIBLIT_REPLAY_DATA_DIR'):
        monkeypatch.setenv(key, os.environ.get(key, ''))
        monkeypatch.delenv(key, raising=False)
    TradingRuntimeClient()
    assert os.environ['NIBLIT_MARKET_DATA_PROVIDER'] == 'replay'
    assert os.environ['NIBLIT_REPLAY_DATA_DIR'] == str(bundle / 'freqtrade/data')
    assert os.environ['NIBLIT_PAPER_STATE_FILE'] == str(tmp_path / 'local/Niblit/paper/account.json')
    monkeypatch.setenv('NIBLIT_MARKET_DATA_PROVIDER', 'ccxt')
    TradingRuntimeClient()
    assert os.environ['NIBLIT_MARKET_DATA_PROVIDER'] == 'ccxt'
