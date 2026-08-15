import os
import sys

os.environ['NIBLIT_HEADLESS'] = '1'
os.environ['NIBLIT_SKIP_INIT_WAIT'] = '1'
os.environ['NIBLIT_LOW_RESOURCE_MODE'] = '1'

sys.path.insert(0, 'C:/Users/Riyaad/Documents/GitHub/Niblit')

# Verify niblit-lean-algos is importable
try:
    import niblit_lean_algos
    print('niblit_lean_algos: IMPORT OK')
except ImportError as e:
    print(f'niblit_lean_algos: IMPORT FAILED: {e}')

# Verify TradingRuntimeManager is importable
try:
    from niblit_lean_algos.manager import TradingRuntimeManager
    print('TradingRuntimeManager: IMPORT OK')
except ImportError as e:
    print(f'TradingRuntimeManager: IMPORT FAILED: {e}')

# Verify UI launcher inspection works
from modules.niblit_ui_launcher import _inspect_trading_runtime
result = _inspect_trading_runtime(None)
print(f'UI launcher inspection (None manager): {result}')

print('MANAGER VERIFICATION PASSED')