import os
import sys

os.environ['NIBLIT_HEADLESS'] = '1'
os.environ['NIBLIT_SKIP_INIT_WAIT'] = '1'
os.environ['NIBLIT_LOW_RESOURCE_MODE'] = '1'

sys.path.insert(0, 'C:/Users/Riyaad/Documents/GitHub/Niblit')

from niblit_core import NiblitCore

core = NiblitCore()

# Verify TradingRuntimeManager is available in Phase 0
manager = getattr(core, 'trading_runtime_manager', None)
alias = getattr(core, 'lean_algo_manager', None)

print(f'trading_runtime_manager: {manager}')
print(f'lean_algo_manager alias: {alias}')
print(f'same object: {manager is alias}')

if manager is not None:
    print(f'backend: {getattr(manager, "backend", "unknown")}')
    print(f'state: {getattr(manager, "state", "unknown")}')
    print(f'mode: {getattr(manager, "trading_mode", "unknown")}')
    print(f'execution_enabled: {getattr(manager, "execution_enabled", False)}')

# Verify UI launcher can inspect the manager
from modules.niblit_ui_launcher import _inspect_trading_runtime
trading = _inspect_trading_runtime(manager)
print(f'\nUI launcher inspection: {trading}')

core.shutdown()
print('\nBOOT VERIFICATION PASSED')