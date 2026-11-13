"""Offline release inspection: no environment loading, imports or processes."""
from pathlib import Path
import json
import importlib.util
import sys

REQUIRED_FILES = (
    'niblit.exe', 'niblit-ui.exe', 'cloud/niblit-cloud.exe',
    'lean-algos/niblit-lean-algos.exe', 'freqtrade/niblit-freqtrade-worker.exe',
    'niblit_core.py', 'main.py', 'assets/trading-desk/index.html',
    'assets/trading-desk/chart.js', 'assets/trading-desk/sessions.js', 'assets/memory-desk/index.html',
    'assets/client-portal/index.html',
    'freqtrade/data/BTC_USDT_USDT-1h-futures.feather',
    'freqtrade/data/ETH_USDT_USDT-1h-futures.feather',
)

REQUIRED_MODULES = (
    'modules.chart_annotations', 'modules.chart_views',
    'modules.native_evidence_learning', 'modules.permission_manager',
    'modules.hybrid_qdrant_manager', 'modules.strategy_manager',
    'MetaTrader5', 'modules.core_trading_sessions', 'modules.trading_session_adapters', 'modules.trading_session_api',
    'modules.freqtrade_core_claim', 'modules.trading_session_probe', 'modules.trading_session_selftest', 'modules.position_intelligence', 'modules.command_registry',
    'modules.demo_autotrader', 'modules.mt5_orders', 'modules.trading_runtime_client',
)

def inspect_bundle(root):
    root = Path(root).resolve()
    checks = []
    for relative in REQUIRED_FILES:
        path = root / relative
        try:
            ok = path.is_file() and path.stat().st_size > 0
        except OSError:
            ok = False
        checks.append({'file': relative, 'ok': ok})
    return {'bundle_files_ready': all(c['ok'] for c in checks), 'checks': checks,
            'services_started': False, 'orders_submitted': False,
            'scope': 'Offline file presence only. Service health, lifecycle, inference, memory and trading acceptance remain unverified.'}

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print('Usage: --release-preflight [bundle-directory]', file=sys.stderr)
        return 2
    root = Path(args[0]) if args else Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    report = inspect_bundle(root)
    if getattr(sys, 'frozen', False):
        # Resolve archive entries without importing learning or memory engines.
        modules = []
        for name in REQUIRED_MODULES:
            try:
                ok = importlib.util.find_spec(name) is not None
            except (ImportError, ValueError):
                ok = False
            modules.append({'module': name, 'ok': ok})
        report['module_checks'] = modules
        report['bundle_files_ready'] = report['bundle_files_ready'] and all(c['ok'] for c in modules)
    print(json.dumps(report, indent=2))
    return 0 if report['bundle_files_ready'] else 1
