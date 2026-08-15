#!/usr/bin/env python3
"""Fix indentation in main.py instrumentation."""
import re

content = open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8').read()

# Fix lines 1415-1421 - the try block around ui_result.wait
old_block = '''                    _BOOT_STATUS.sidecar_status = getattr(_BOOT_STATUS, "sidecar_status", "active")
                    try:
                        io.out(f"{timestamp()} [INSTRUMENT] About to call ui_result.wait()", flush=True)
                    sys.stdout.flush()
                    exit_code = ui_result.wait()
                    io.out(f"{timestamp()} [INSTRUMENT] ui_result.wait() returned: {exit_code}", flush=True)
                    sys.stdout.flush()
                    finally:'''

new_block = '''                    _BOOT_STATUS.sidecar_status = getattr(_BOOT_STATUS, "sidecar_status", "active")
                    try:
                        io.out(f"{timestamp()} [INSTRUMENT] About to call ui_result.wait()", flush=True)
                        sys.stdout.flush()
                        exit_code = ui_result.wait()
                        io.out(f"{timestamp()} [INSTRUMENT] ui_result.wait() returned: {exit_code}", flush=True)
                        sys.stdout.flush()
                    finally:'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed indentation for ui_result.wait() instrumentation")
else:
    print("Block not found - checking current state")
    # Find and print the relevant section
    lines = content.splitlines()
    for i, line in enumerate(lines[1410:1425], start=1411):
        print(f"{i}: {repr(line)}")