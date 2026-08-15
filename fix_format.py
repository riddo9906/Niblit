#!/usr/bin/env python3
"""Fix formatting issues in main.py instrumentation."""
content = open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8').read()

# Fix the import sys; sys.stdout.flush() formatting - put import at top and use proper flush
# Replace all instances of the inline import with proper sys.stdout.flush() calls

# The instrumentation was added but the import statements are inline
# Let's fix this by using the module-level sys import that's already there

# Replace "import sys; sys.stdout.flush()" with just "sys.stdout.flush()"
content = content.replace('import sys; sys.stdout.flush()', 'sys.stdout.flush()')

with open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed formatting - removed inline import statements")