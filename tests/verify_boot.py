"""Quick boot simulation — verifies the launcher produces the expected output."""
import sys
from unittest.mock import patch, Mock

from modules.niblit_ui_launcher import launch_primary_ui, UiLaunchResult, _coerce_ui_launch_result

# Simulate a core with a paper trading manager (ready state)
core = Mock()
core.trading_runtime_manager = None
core.lean_algo_manager = Mock(
    backend="paper", state="ready", trading_mode="observe", execution_enabled=False
)

captured = []
class FakeIO:
    def out(self, msg, **kw):
        captured.append(msg)

with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
     patch("modules.niblit_ui_launcher._start_api_server_thread"):
    result = launch_primary_ui(core=core, io=FakeIO())

print("=== BOOT OUTPUT ===")
for line in captured:
    print(line)

print("\n=== RESULT ===")
print(f"Type:      {type(result).__name__} (not dict: {not isinstance(result, dict)})")
print(f"Success:   {result.success}")
print(f"Mode:      {result.mode}")
print(f"API URL:   {result.api_url}")
print(f"Cloud URL: {result.cloud_url}")
print(f"Message:   {result.message}")
print(f"Readiness: {result.readiness}")
print(f"Wait():    {result.wait()}")
result.terminate()

print("\n=== CALLER COMPAT (main.py) ===")
for attr in ("success", "message", "mode", "api_url", "cloud_url", "readiness"):
    print(f"  hasattr({attr}): {hasattr(result, attr)}")
for meth in ("wait", "terminate"):
    print(f"  callable({meth}): {callable(getattr(result, meth, None))}")

# Legacy dict coercion
legacy = {"status": "ok", "errors": [], "runtime_state": {}}
coerced = _coerce_ui_launch_result(legacy)
print(f"\nLegacy dict → {type(coerced).__name__}(success={coerced.success}, mode={coerced.mode})")

ok = (
    isinstance(result, UiLaunchResult)
    and result.success
    and "5000" in result.api_url
    and "8000" in result.cloud_url
    and callable(result.wait)
    and callable(result.terminate)
    and isinstance(legacy, dict)  # ensure we don't regress
    and isinstance(coerced, UiLaunchResult)
)
print(f"\nALL CHECKS PASSED: {ok}")
sys.exit(0 if ok else 1)
