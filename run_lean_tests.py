import subprocess
import sys
import os

os.chdir('C:/Users/Riyaad/Documents/GitHub/niblit-lean-algos')
result = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/', '-v'],
    capture_output=True,
    text=True,
)
print(result.stdout)
print(result.stderr)
sys.exit(result.returncode)