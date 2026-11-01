"""Read-only build inputs audit. Does not import specs or boot any service."""
import ast
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(root=ROOT):
    root = Path(root)
    ui = Path(os.getenv('NIBLIT_UI_PATH') or os.getenv('NIBLIT_UI_ROOT') or root.parent / 'niblit-ui')
    cloud = Path(os.getenv('NIBLIT_CLOUD_SERVER_PATH') or root.parent / 'Niblit-cloud-server')
    lean = Path(os.getenv('NIBLIT_LEAN_ALGOS_ROOT') or os.getenv('NIBLIT_LEAN_ALGOS') or root.parent / 'niblit-lean-algos')
    freq = Path(os.getenv('NIBLIT_FREQTRADE_ROOT') or root.parent / 'freqtrade')
    checks = []
    def require(path, label):
        checks.append({'input': label, 'ok': path.is_file()})
    for directory, name in ((root, 'niblit.spec'), (cloud, 'niblit-cloud-server.spec'),
                            (lean, 'niblit-lean-algos.spec'), (lean, 'freqtrade_worker.spec')):
        path = directory / name
        require(path, name)
        if path.is_file():
            try:
                ast.parse(path.read_text(encoding='utf-8-sig'))
                checks.append({'input': name + ' syntax', 'ok': True})
            except (SyntaxError, UnicodeError):
                checks.append({'input': name + ' syntax', 'ok': False})
    for directory, relative in ((ui, 'package.json'), (ui, 'src-tauri/Cargo.toml'),
            (ui, 'src-tauri/tauri.conf.json'), (cloud, 'app/main.py'),
            (lean, 'main.py'), (lean, 'freqtrade_strategy_worker.py'),
            (freq, 'freqtrade/strategy/interface.py')):
        require(directory / relative, directory.name + '/' + relative)
    for symbol in ('BTC', 'ETH'):
        require(freq / f'user_data/data/binance/futures/{symbol}_USDT_USDT-1h-futures.feather',
                symbol + ' recorded worker data (not live data)')
    for desk in ('trading-desk', 'memory-desk', 'client-portal'):
        require(root / 'assets' / desk / 'index.html', desk + ' web entry')
    return {'inputs_ready': all(item['ok'] for item in checks), 'checks': checks,
            'scope': 'Source inputs and spec syntax only; compilation and boot acceptance remain required',
            'services_started': False}


if __name__ == '__main__':
    report = audit()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['inputs_ready'] else 1)
