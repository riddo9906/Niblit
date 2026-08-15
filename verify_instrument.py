#!/usr/bin/env python3
content = open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8').read()
lines = [l for l in content.splitlines() if 'INSTRUMENT' in l]
print(f"Found {len(lines)} INSTRUMENT lines:")
for line in lines:
    print(f"  {line}")
print()
# Check for wait() call
wait_lines = [l for l in content.splitlines() if 'wait()' in l]
print(f"Found {len(wait_lines)} wait() lines:")
for line in wait_lines:
    print(f"  {line}")