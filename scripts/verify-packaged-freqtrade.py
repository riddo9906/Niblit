"""Verify packaged live market data using dry-run only; never accept real keys."""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, ProxyHandler, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = bundle / 'freqtrade/niblit-freqtrade-worker.exe'
    config_path = output / 'dry-run.json'
    if config_path.exists():
        raise RuntimeError('Use a fresh verification output folder')
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('FREQTRADE__', 'NIBLIT_', 'BINANCE_'))}
    env['PYTHON_DOTENV_DISABLED'] = '1'
    subprocess.run([str(executable), '--engine', '--version'], env=env, check=True)
    subprocess.run([str(executable), '--prepare-profile', '--mode', 'dry-run',
                    '--output', str(config_path)], env=env, check=True)
    config = json.loads(config_path.read_text())
    assert config['dry_run'] is True and not config['exchange']['key'] and not config['exchange']['secret']
    config['initial_state'] = 'running'
    config['api_server']['listen_port'] = 18180
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    for port in (18180, 28110):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    env.update(NIBLIT_TRADING_BACKEND='freqtrade', NIBLIT_TRADING_MODE='observe',
               NIBLIT_FREQTRADE_ALLOW_EXECUTION='false', NIBLIT_FREQTRADE_DRY_RUN='true',
               NIBLIT_FREQTRADE_BASE_URL='http://127.0.0.1:18180',
               NIBLIT_FREQTRADE_USERNAME=config['api_server']['username'],
               NIBLIT_FREQTRADE_PASSWORD=config['api_server']['password'],
               NIBLIT_TRADING_API_PORT='28110', NIBLIT_MARKET_DATA_PROVIDER='ccxt',
               NIBLIT_MARKET_DATA_EXCHANGE='binance', NIBLIT_MARKET_DATA_MARKET_TYPE='spot',
               NIBLIT_MARKET_DATA_TIMEFRAME='1h', NIBLIT_EXECUTION_DB=str(output / 'executions.sqlite'),
               NIBLIT_SIGNAL_FILE=str(output / 'signal.json'), NIBLIT_TRACE_FILE=str(output / 'trace.jsonl'),
               NIBLIT_RESULTS_FILE=str(output / 'results.json'), NIBLIT_REFLECTION_FILE=str(output / 'reflection.jsonl'),
               NIBLIT_EPISODES_FILE=str(output / 'episodes.jsonl'))
    auth = base64.b64encode((config['api_server']['username'] + ':' + config['api_server']['password']).encode()).decode()
    opener = build_opener(ProxyHandler({}))

    def get(url, authenticated=False):
        request = Request(url, headers={'Authorization': 'Basic ' + auth} if authenticated else {})
        with opener.open(request, timeout=8) as response:
            return json.load(response)

    report = {'ready': False, 'dry_run': True, 'checks': {}}
    processes, streams = [], []
    try:
        for name, command in (
            ('engine', [str(executable), '--engine', 'trade', '--dry-run', '--config', str(config_path)]),
            ('adapter', [str(bundle / 'lean-algos/niblit-lean-algos.exe')]),
        ):
            stream = (output / (name + '.log')).open('w', encoding='utf-8')
            streams.append(stream)
            processes.append(subprocess.Popen(command, cwd=output, env=env, stdout=stream,
                             stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
        deadline = time.monotonic() + 180
        last_error = ''
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('Packaged service exited; see engine.log and adapter.log')
            try:
                remote = get('http://127.0.0.1:18180/api/v1/show_config', True)
                assert remote.get('dry_run') is True
                candles = get('http://127.0.0.1:18180/api/v1/pair_candles?pair=BTC%2FUSDT&timeframe=1h&limit=2', True)
                adapter = get('http://127.0.0.1:28110/health')
                if (remote.get('state') == 'running' and candles.get('length', 0) > 0
                        and adapter.get('backend') == 'freqtrade' and adapter.get('healthy') is True
                        and adapter.get('market_data', {}).get('healthy') is True):
                    report.update(ready=True, checks={'native_engine_running': True, 'dry_run_verified': True,
                                  'live_candles_available': True, 'adapter_healthy': True},
                                  strategy=remote.get('strategy'), candle_count=candles['length'])
                    break
            except Exception as exc:
                last_error = type(exc).__name__ + ': ' + str(exc)
            time.sleep(2)
        if not report['ready']:
            raise RuntimeError('Packaged live-data readiness timed out: ' + last_error)
        # Exercise the same human command handler against this authenticated
        # simulated engine. Never send a start to a real-money instance.
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from modules.freqtrade_operator import handle_freqtrade_command, LIVE_ACK
        with patch.dict(os.environ, {**env, 'NIBLIT_FREQTRADE_ALLOW_CONTROL': 'true'}):
            checks = report['checks']
            checks['operator_status'] = handle_freqtrade_command('freqtrade status')['status'] == 'success'
            checks['live_request_rejected_against_dry_run'] = handle_freqtrade_command('freqtrade start live ' + LIVE_ACK)['status'] == 'rejected'
            checks['operator_stop'] = handle_freqtrade_command('freqtrade stop')['status'] == 'success'
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if get('http://127.0.0.1:18180/api/v1/show_config', True).get('state') == 'stopped':
                    break
                time.sleep(1)
            checks['operator_stopped_state'] = get('http://127.0.0.1:18180/api/v1/show_config', True).get('state') == 'stopped'
            checks['operator_start_dry_run'] = handle_freqtrade_command('freqtrade start dry-run')['status'] == 'success'
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if get('http://127.0.0.1:18180/api/v1/show_config', True).get('state') == 'running':
                    break
                time.sleep(1)
            checks['operator_restarted_state'] = get('http://127.0.0.1:18180/api/v1/show_config', True).get('state') == 'running'
            report['ready'] = all(checks.values())
    except Exception as exc:
        report.update(ready=False, error=str(exc))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for stream in streams:
            stream.close()
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
