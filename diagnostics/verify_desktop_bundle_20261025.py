"""Bounded smoke checks for the assembled desktop services; no trading orders."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist" / "niblit"
REPORT = {}
for relative in ("niblit.exe", "niblit-ui.exe", "cloud/niblit-cloud.exe", "lean-algos/niblit-lean-algos.exe"):
    artifact = BUNDLE / relative
    assert artifact.is_file(), f"Missing {artifact}"
    REPORT[relative] = {"bytes": artifact.stat().st_size}

for service, relative, port, overrides in (
    ("cloud", "cloud/niblit-cloud.exe", 18080, {"NIBLIT_PORT": "18080", "NIBLIT_CLOUD_BIND_HOST": "127.0.0.1"}),
    ("lean", "lean-algos/niblit-lean-algos.exe", 18100, {"NIBLIT_TRADING_API_PORT": "18100", "NIBLIT_TRADING_MODE": "observe", "NIBLIT_TRADING_BACKEND": "paper"}),
):
    exe = BUNDLE / relative
    env = {**os.environ, **overrides}
    log_path = ROOT / "diagnostics" / f"desktop-smoke-{service}-20261025.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env, stdout=log, stderr=subprocess.STDOUT)
        result = {"health_http_200": False}
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and proc.poll() is None:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        if response.status == 200:
                            result["health_http_200"] = True
                            break
                except Exception:
                    time.sleep(0.3)
            result["exit_before_cleanup"] = proc.poll()
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        REPORT[service] = result

output = ROOT / "diagnostics" / "desktop-bundle-verification-20261025.json"
output.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
print(json.dumps(REPORT, indent=2))
raise SystemExit(0 if all(REPORT[name]["health_http_200"] for name in ("cloud", "lean")) else 1)
