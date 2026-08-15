#!/usr/bin/env python3
"""Add instrumentation around ui_result.wait() to identify hang location."""
content = open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8').read()

# Add instrumentation before ui_result.wait()
old = 'exit_code = ui_result.wait()'
new = '''io.out(f"{timestamp()} [INSTRUMENT] About to call ui_result.wait()", flush=True)
                    import sys; sys.stdout.flush()
                    exit_code = ui_result.wait()
                    io.out(f"{timestamp()} [INSTRUMENT] ui_result.wait() returned: {exit_code}", flush=True)
                    import sys; sys.stdout.flush()'''

if old in content:
    content = content.replace(old, new)
    with open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Instrumentation added around ui_result.wait()")
else:
    print("ui_result.wait() not found - may already have instrumentation or different format")

# Verify
lines = [l for l in content.splitlines() if 'INSTRUMENT' in l and 'ui_result.wait' in l]
print(f"INSTRUMENT lines related to ui_result.wait: {len(lines)}")
for line in lines:
    print(f"  {line}")