#!/usr/bin/env python3
"""Apply instrumentation to main.py to identify hang location."""
import re

# Read the file
with open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the instrumentation to add after print_boot_status_report
after_report_marker = '# ── Primary UI: managed via orchestrator, legacy Tk desktop, or niblit-ui ─\n    if _should_launch_desktop(_args):'

instrumentation_before = '''# ── Primary UI: managed via orchestrator, legacy Tk desktop, or niblit-ui ─
    io.out(f"{timestamp()} [INSTRUMENT] Checking _should_launch_desktop()", flush=True)
    import sys; sys.stdout.flush()
    _should_launch = _should_launch_desktop(_args)
    io.out(f"{timestamp()} [INSTRUMENT] _should_launch_desktop() returned: {_should_launch}", flush=True)
    import sys; sys.stdout.flush()
    if _should_launch:'''

# Replace
if after_report_marker in content:
    content = content.replace(after_report_marker, instrumentation_before)

# Add instrumentation before the UI launch calls
legacy_launch_marker = 'try:\n                from modules.desktop_runtime_shell import launch_desktop_shell\n\n                launched = launch_desktop_shell'

instrumentation_legacy = '''try:
                io.out(f"{timestamp()} [INSTRUMENT] Calling launch_desktop_shell()", flush=True)
                import sys; sys.stdout.flush()
                from modules.desktop_runtime_shell import launch_desktop_shell

                launched = launch_desktop_shell'''

if legacy_launch_marker in content:
    content = content.replace(legacy_launch_marker, instrumentation_legacy)

# Add instrumentation for niblit-ui path
niblit_ui_marker = '_log_managed_ui_diagnostics(io)\n            try:\n                from modules.niblit_ui_launcher import launch_primary_ui\n\n                ui_result = launch_primary_ui('

instrumentation_niblit_ui = '''_log_managed_ui_diagnostics(io)
            io.out(f"{timestamp()} [INSTRUMENT] Calling launch_primary_ui()", flush=True)
            import sys; sys.stdout.flush()
            try:
                from modules.niblit_ui_launcher import launch_primary_ui

                ui_result = launch_primary_ui('''

if niblit_ui_marker in content:
    content = content.replace(niblit_ui_marker, instrumentation_niblit_ui)

# Add instrumentation before run_shell
shell_marker = '    # ── Interactive shell (CLI fallback) ─────────────────────────────────────\n    io.out(f"{timestamp()} ✅ Niblit Runtime Fully Operational")\n    try:\n        run_shell(core, io)'

instrumentation_shell = '''    # ── Interactive shell (CLI fallback) ─────────────────────────────────────
    io.out(f"{timestamp()} [INSTRUMENT] About to call run_shell()", flush=True)
    import sys; sys.stdout.flush()
    try:
        run_shell(core, io)'''

if shell_marker in content:
    content = content.replace(shell_marker, instrumentation_shell)

# Write back
with open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Instrumentation applied successfully!")
print("Checking for INSTRUMENT lines:")
instrument_lines = [l for l in content.splitlines() if 'INSTRUMENT' in l]
for line in instrument_lines[:20]:
    print(line)