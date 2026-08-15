import py_compile
import sys

try:
    py_compile.compile('C:/Users/Riyaad/Documents/GitHub/Niblit/main.py', doraise=True)
    print('main.py: COMPILE OK')
except py_compile.PyCompileError as e:
    print(f'main.py: COMPILE FAILED: {e}')
    sys.exit(1)

try:
    py_compile.compile('C:/Users/Riyaad/Documents/GitHub/Niblit/modules/niblit_ui_launcher.py', doraise=True)
    print('niblit_ui_launcher.py: COMPILE OK')
except py_compile.PyCompileError as e:
    print(f'niblit_ui_launcher.py: COMPILE FAILED: {e}')
    sys.exit(1)

try:
    py_compile.compile('C:/Users/Riyaad/Documents/GitHub/Niblit/niblit_core.py', doraise=True)
    print('niblit_core.py: COMPILE OK')
except py_compile.PyCompileError as e:
    print(f'niblit_core.py: COMPILE FAILED: {e}')
    sys.exit(1)

print('ALL COMPILE CHECKS PASSED')