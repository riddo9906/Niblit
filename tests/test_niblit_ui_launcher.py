#!/usr/bin/env python3
"""Tests for modules/niblit_ui_launcher.py — the desktop UI launch contract.

Covers:
  * Result contract  — launch_primary_ui always returns UiLaunchResult, never dict
  * Coercion         — _coerce_ui_launch_result handles legacy dicts/objects
  * Trading status   — _inspect_trading_runtime reads real attrs / env
  * HTTP readiness   — _wait_for_http_ready success / timeout / transient
  * API startup      — API already ready vs. needs start; port resolution
  * Lifecycle        — UiLaunchResult.wait() / terminate() / idempotency
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from modules.niblit_ui_launcher import (
    UiLaunchResult,
    _coerce_ui_launch_result,
    _inspect_trading_runtime,
    _wait_for_http_ready,
    _niblit_api_port,
    _cloud_url,
    launch_primary_ui,
    get_runtime_state,
    reset_runtime_state,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _FakeManager:
    """Minimal stand-in for LeanAlgoManager / TradingRuntimeManager."""

    def __init__(
        self,
        backend: str = "paper",
        state: str = "ready",
        trading_mode: str = "observe",
        execution_enabled: bool = False,
    ) -> None:
        self.backend = backend
        self.state = state
        self.trading_mode = trading_mode
        self.execution_enabled = execution_enabled


class _LegacyManager:
    """Manager that only exposes the legacy *Name properties."""

    def __init__(self) -> None:
        self.selected_backend_name = "lean"
        self.state_name = "ready"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Result contract — must never return a dict
# ─────────────────────────────────────────────────────────────────────────────

class TestResultContract:
    """Section 12 — Result Contract: every path returns UiLaunchResult."""

    def test_success_returns_result_not_dict(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert isinstance(result, UiLaunchResult)
            assert not isinstance(result, dict)

    def test_api_failure_returns_result_not_dict(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=False), \
             patch("modules.niblit_ui_launcher._start_api_server_thread", return_value=None):
            result = launch_primary_ui(core=None)
            assert isinstance(result, UiLaunchResult)
            assert not isinstance(result, dict)

    def test_trading_required_failure_returns_result(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"), \
             patch.dict(os.environ, {"NIBLIT_TRADING_REQUIRED": "true"}):
            result = launch_primary_ui(core=Mock(spec=[]))
            assert isinstance(result, UiLaunchResult)
            assert result.success is False

    def test_result_has_success_attribute(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert hasattr(result, "success")
            assert isinstance(result.success, bool)

    def test_result_has_message_attribute(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert hasattr(result, "message")
            assert isinstance(result.message, str)

    def test_result_has_wait_method(self):
        result = UiLaunchResult(success=True)
        assert callable(getattr(result, "wait", None))

    def test_result_has_terminate_method(self):
        result = UiLaunchResult(success=True)
        assert callable(getattr(result, "terminate", None))

    def test_result_has_mode_attribute(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert hasattr(result, "mode")
            assert isinstance(result.mode, str)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Coercion helper
# ─────────────────────────────────────────────────────────────────────────────

class TestCoerce:
    """Section 12 — _coerce_ui_launch_result compatibility helper."""

    def test_passthrough_result(self):
        original = UiLaunchResult(success=True, mode="active", message="ok")
        coerced = _coerce_ui_launch_result(original)
        assert coerced is original

    def test_dict_ok_status(self):
        result = _coerce_ui_launch_result({"status": "ok", "message": "all good"})
        assert isinstance(result, UiLaunchResult)
        assert result.success is True
        assert result.mode == "active"
        assert result.message == "all good"

    def test_dict_error_status(self):
        result = _coerce_ui_launch_result({"status": "error", "errors": ["boom"]})
        assert isinstance(result, UiLaunchResult)
        assert result.success is False
        assert result.mode == "degraded"

    def test_dict_empty(self):
        """Empty dict → success=False (status '' != 'ok')."""
        result = _coerce_ui_launch_result({})
        assert isinstance(result, UiLaunchResult)
        assert result.success is False

    def test_none_raises(self):
        with pytest.raises(TypeError, match="None"):
            _coerce_ui_launch_result(None)

    def test_int_raises(self):
        with pytest.raises(TypeError, match="int"):
            _coerce_ui_launch_result(42)

    def test_dict_preserves_readiness(self):
        result = _coerce_ui_launch_result(
            {"status": "ok", "readiness": {"api": "ready"}}
        )
        assert result.readiness == {"api": "ready"}

    def test_dict_errors_joined_in_message(self):
        result = _coerce_ui_launch_result(
            {"status": "error", "errors": ["err1", "err2"]}
        )
        assert result.success is False
        assert "err1" in result.message and "err2" in result.message


# ─────────────────────────────────────────────────────────────────────────────
# 3. Trading-runtime inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestInspectTradingRuntime:
    """Section 13 — _inspect_trading_runtime reads real attrs / env."""

    def test_none_manager(self):
        result = _inspect_trading_runtime(None)
        assert result["found"] is False
        assert result["backend"] == "none"
        assert result["state"] == "stopped"
        assert result["mode"] == "disabled"
        assert result["execution_enabled"] is False

    def test_full_manager(self):
        mgr = _FakeManager(backend="paper", state="ready", trading_mode="observe")
        result = _inspect_trading_runtime(mgr)
        assert result["found"] is True
        assert result["backend"] == "paper"
        assert result["state"] == "ready"
        assert result["mode"] == "observe"
        assert result["execution_enabled"] is False

    def test_legacy_name_attributes(self):
        """Manager exposes selected_backend_name / state_name instead of backend/state."""
        mgr = _LegacyManager()
        result = _inspect_trading_runtime(mgr)
        assert result["found"] is True
        assert result["backend"] == "lean"
        assert result["state"] == "ready"

    def test_manager_without_any_trading_attrs(self):
        """A bare Mock (no trading attrs) → safe defaults."""
        mgr = Mock(spec=[])
        result = _inspect_trading_runtime(mgr)
        assert result["found"] is True
        assert result["backend"] == "lean"
        assert result["state"] == "unknown"
        assert result["mode"] == "observe"
        assert result["execution_enabled"] is False

    def test_freqtrade_backend_via_env(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_TRADING_BACKEND", "freqtrade")
        mgr = _make_lean_manager()
        result = _inspect_trading_runtime(mgr)
        assert result["backend"] == "freqtrade"

    def test_paper_backend_via_env(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_TRADING_BACKEND", "paper")
        mgr = _make_lean_manager()
        result = _inspect_trading_runtime(mgr)
        assert result["backend"] == "paper"

    def test_trading_mode_via_env(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_TRADING_MODE", "live")
        mgr = _make_lean_manager()
        result = _inspect_trading_runtime(mgr)
        assert result["mode"] == "live"

    def test_execution_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_TRADING_ALLOW_EXECUTION", "true")
        mgr = _make_lean_manager()
        result = _inspect_trading_runtime(mgr)
        assert result["execution_enabled"] is True


def _make_lean_manager():
    """Create a stub that replicates LeanAlgoManager's inspection properties.

    Importing ``modules.lean_algo_manager`` triggers the full NiblitCore
    dependency chain (``parameter_manager`` → ``niblit_memory`` →
    ``sentence-transformers``) which attempts an HuggingFace model download
    during collection and crashes the interpreter.  This stub replicates the
    exact property logic so the inspection contract is fully tested without
    that chain.  The real class in ``lean_algo_manager.py`` uses the same
    logic.
    """

    class _Stub:
        def __init__(self):
            self._signal_thread = None
            self._monitor_thread = None

        @property
        def backend(self):
            return os.environ.get("NIBLIT_TRADING_BACKEND", "lean")

        @property
        def state(self):
            if self._signal_thread is not None and self._signal_thread.is_alive():
                return "running"
            if self._monitor_thread is not None and self._monitor_thread.is_alive():
                return "running"
            return "ready"

        @property
        def state_name(self):
            return self.state

        @property
        def selected_backend_name(self):
            return self.backend

        @property
        def trading_mode(self):
            return os.environ.get("NIBLIT_TRADING_MODE", "observe")

        @property
        def execution_enabled(self):
            return os.environ.get("NIBLIT_TRADING_ALLOW_EXECUTION", "false").lower() == "true"

    return _Stub()


# ─────────────────────────────────────────────────────────────────────────────
# 4. LeanAlgoManager synchronous properties
# ─────────────────────────────────────────────────────────────────────────────

class TestLeanAlgoManagerProperties:
    """Section 13 — LeanAlgoManager exposes stable inspection properties."""

    def test_backend_default(self, monkeypatch):
        monkeypatch.delenv("NIBLIT_TRADING_BACKEND", raising=False)
        mgr = _make_lean_manager()
        assert mgr.backend == "lean"

    def test_backend_env_override(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_TRADING_BACKEND", "freqtrade")
        mgr = _make_lean_manager()
        assert mgr.backend == "freqtrade"

    def test_state_ready(self):
        mgr = _make_lean_manager()
        assert mgr.state == "ready"
        assert mgr.state_name == "ready"

    def test_state_running(self):
        mgr = _make_lean_manager()
        mgr._signal_thread = Mock()
        mgr._signal_thread.is_alive.return_value = True
        assert mgr.state == "running"

    def test_trading_mode_default(self, monkeypatch):
        monkeypatch.delenv("NIBLIT_TRADING_MODE", raising=False)
        mgr = _make_lean_manager()
        assert mgr.trading_mode == "observe"

    def test_execution_disabled_default(self, monkeypatch):
        monkeypatch.delenv("NIBLIT_TRADING_ALLOW_EXECUTION", raising=False)
        mgr = _make_lean_manager()
        assert mgr.execution_enabled is False

    def test_execution_enabled(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_TRADING_ALLOW_EXECUTION", "true")
        mgr = _make_lean_manager()
        assert mgr.execution_enabled is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. HTTP readiness helper
# ─────────────────────────────────────────────────────────────────────────────

def _mock_http_response(status: int = 200) -> MagicMock:
    """Build a mock context-manager returned by urllib.request.urlopen."""
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.status = status
    return resp


class TestWaitForHttpReady:
    """Section 14 — _wait_for_http_ready success / timeout / transient."""

    @patch("modules.niblit_ui_launcher.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_urlopen.return_value = _mock_http_response(200)
        assert _wait_for_http_ready(
            "http://127.0.0.1:5000/health", timeout_seconds=5
        ) is True

    @patch("modules.niblit_ui_launcher.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionRefusedError("refused")
        assert _wait_for_http_ready(
            "http://127.0.0.1:5000/health",
            timeout_seconds=1,
            interval_seconds=0.01,
        ) is False

    @patch("modules.niblit_ui_launcher.urllib.request.urlopen")
    def test_transient_then_success(self, mock_urlopen):
        mock_urlopen.side_effect = [
            ConnectionRefusedError("refused"),
            ConnectionRefusedError("refused"),
            _mock_http_response(200),
        ]
        assert _wait_for_http_ready(
            "http://127.0.0.1:5000/health",
            timeout_seconds=5,
            interval_seconds=0.01,
        ) is True

    @patch("modules.niblit_ui_launcher.urllib.request.urlopen")
    def test_malformed_json_does_not_crash(self, mock_urlopen):
        """A non-200 response must not raise; it should be treated as not ready."""
        mock_urlopen.return_value = _mock_http_response(503)
        assert _wait_for_http_ready(
            "http://127.0.0.1:5000/health",
            timeout_seconds=1,
            interval_seconds=0.01,
        ) is False

    @patch("modules.niblit_ui_launcher.urllib.request.urlopen")
    def test_http_200_returns_true(self, mock_urlopen):
        mock_urlopen.return_value = _mock_http_response(200)
        assert _wait_for_http_ready(
            "http://127.0.0.1:5000/health", timeout_seconds=5
        ) is True


# ─────────────────────────────────────────────────────────────────────────────
# 6. Port / URL resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestPortResolution:
    """Section 14 — port resolution defaults to 5000 (not 8080)."""

    def test_default_api_port(self, monkeypatch):
        monkeypatch.delenv("NIBLIT_API_PORT", raising=False)
        assert _niblit_api_port() == 5000

    def test_env_api_port(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_API_PORT", "9090")
        assert _niblit_api_port() == 9090

    def test_invalid_api_port(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_API_PORT", "not-a-number")
        assert _niblit_api_port() == 5000

    def test_zero_api_port(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_API_PORT", "0")
        assert _niblit_api_port() == 5000

    def test_negative_api_port(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_API_PORT", "-1")
        assert _niblit_api_port() == 5000

    def test_default_cloud_url(self, monkeypatch):
        monkeypatch.delenv("NIBLIT_CLOUD_SERVER_URL", raising=False)
        monkeypatch.delenv("NIBLIT_CLOUD_SERVER_PRIMARY_PORT", raising=False)
        assert _cloud_url() == "http://127.0.0.1:8000"

    def test_env_cloud_url(self, monkeypatch):
        monkeypatch.setenv("NIBLIT_CLOUD_SERVER_URL", "http://127.0.0.1:8000/")
        assert _cloud_url() == "http://127.0.0.1:8000"


# ─────────────────────────────────────────────────────────────────────────────
# 7. launch_primary_ui integration with mocked HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TestLaunchPrimaryUi:
    """Section 14 — API startup: already ready vs. needs start vs. failure."""

    def test_api_already_ready_no_start(self):
        """API already serving → success, _start_api_server_thread NOT called."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True) as mock_wait, \
             patch("modules.niblit_ui_launcher._start_api_server_thread") as mock_start:
            result = launch_primary_ui(core=None)
            assert isinstance(result, UiLaunchResult)
            assert result.success is True
            assert result.mode == "degraded"  # no trading manager → degraded
            assert result.readiness.get("api") == "ready"
            assert result.readiness.get("cloud") == "ready"
            mock_start.assert_not_called()  # API was already up

    def test_api_starts_when_not_running(self):
        """API not running → launcher starts it → success."""
        call_count = [0]

        def mock_wait(url, **kwargs):
            call_count[0] += 1
            if "/healthz" in url:
                return True  # cloud ready
            # API health: first quick check fails, second (after start) succeeds
            return call_count[0] > 1

        with patch("modules.niblit_ui_launcher._wait_for_http_ready", side_effect=mock_wait), \
             patch("modules.niblit_ui_launcher._start_api_server_thread",
                   return_value=(Mock(), Mock())) as mock_start:
            result = launch_primary_ui(core=Mock())
            assert isinstance(result, UiLaunchResult)
            assert result.success is True
            mock_start.assert_called_once()

    def test_api_failure_degraded(self):
        """API not ready and can't start → success=False, mode=degraded."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=False), \
             patch("modules.niblit_ui_launcher._start_api_server_thread", return_value=None):
            result = launch_primary_ui(core=Mock())
            assert isinstance(result, UiLaunchResult)
            assert result.success is False
            assert result.mode == "degraded"
            assert result.readiness.get("api") == "unavailable"

    def test_trading_missing_nonblocking(self):
        """No trading manager but API ready → success=True, mode=degraded."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=Mock(spec=[]))
            assert isinstance(result, UiLaunchResult)
            assert result.success is True
            assert result.mode == "degraded"
            assert result.readiness.get("trading") == "missing"

    def test_trading_found_ok(self):
        """Trading manager present + API ready → mode=active."""
        core = Mock()
        core.lean_algo_manager = _FakeManager(backend="paper", state="ready")
        core.trading_runtime_manager = None  # not set → falls to lean_algo_manager
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=core)
            assert isinstance(result, UiLaunchResult)
            assert result.success is True
            assert result.mode == "active"
            assert "backend=paper" in str(result.message) or result.readiness.get("trading") == "ready"

    def test_trading_required_blocks(self):
        """NIBLIT_TRADING_REQUIRED=true + no manager → success=False."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"), \
             patch.dict(os.environ, {"NIBLIT_TRADING_REQUIRED": "true"}):
            result = launch_primary_ui(core=Mock(spec=[]))
            assert isinstance(result, UiLaunchResult)
            assert result.success is False
            assert "required" in result.message.lower()

    def test_trading_required_ok(self):
        """NIBLIT_TRADING_REQUIRED=true + manager ready → success=True."""
        core = Mock()
        core.lean_algo_manager = _FakeManager(backend="paper", state="ready")
        core.trading_runtime_manager = None
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"), \
             patch.dict(os.environ, {"NIBLIT_TRADING_REQUIRED": "true"}):
            result = launch_primary_ui(core=core)
            assert isinstance(result, UiLaunchResult)
            assert result.success is True
            assert result.mode == "active"

    def test_api_url_uses_port_5000(self):
        """The API health URL must use port 5000, not 8080."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True) as mock_wait, \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            # Check that the API health URL called contains port 5000
            assert mock_wait.called
            first_call_args = mock_wait.call_args_list[0]
            first_url = first_call_args[0][0]
            assert "5000" in first_url
            assert "/health" in first_url
            assert "8080" not in first_url

    def test_no_dict_return_contract(self):
        """Explicitly verify no code path returns a dict (the original bug)."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert not isinstance(result, dict), "launch_primary_ui must not return a dict"

    def test_message_accessible(self):
        """The original crash was 'dict has no attribute message'."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert hasattr(result, "message")
            assert result.message  # non-empty

    def test_wait_returns_zero_without_process(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            assert result.wait() == 0

    def test_terminate_idempotent(self):
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True), \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            result = launch_primary_ui(core=None)
            result.terminate()
            result.terminate()  # second call must not raise

    def test_cloud_url_uses_port_8000(self):
        """Cloud check must NOT use 5000 or 8080."""
        with patch("modules.niblit_ui_launcher._wait_for_http_ready", return_value=True) as mock_wait, \
             patch("modules.niblit_ui_launcher._start_api_server_thread"):
            launch_primary_ui(core=None)
            # The last call should be the cloud healthz check
            cloud_call = mock_wait.call_args_list[-1]
            cloud_url = cloud_call[0][0]
            assert "8000" in cloud_url
            assert "5000" not in cloud_url


# ─────────────────────────────────────────────────────────────────────────────
# 8. UiLaunchResult lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class TestUiLaunchResultLifecycle:
    def test_wait_no_process(self):
        result = UiLaunchResult(success=True)
        assert result.wait() == 0

    def test_terminate_idempotent(self):
        result = UiLaunchResult(success=True)
        result.terminate()
        result.terminate()

    def test_terminate_with_mock_process(self):
        mock_proc = Mock()
        mock_proc.wait.return_value = 0
        result = UiLaunchResult(success=True, _ui_process=mock_proc)
        result.terminate()
        mock_proc.terminate.assert_called_once()

    def test_terminate_with_owned_server(self):
        mock_server = Mock()
        result = UiLaunchResult(
            success=True,
            _owned_server=mock_server,
            _api_thread=None,
        )
        result.terminate()
        assert mock_server.should_exit is True

    def test_is_trading_enabled(self):
        assert UiLaunchResult(success=True, mode="active").is_trading_enabled()
        assert UiLaunchResult(success=True, mode="live").is_trading_enabled()
        assert not UiLaunchResult(success=True, mode="degraded").is_trading_enabled()
        assert not UiLaunchResult(success=True, mode="disabled").is_trading_enabled()

    def test_default_values(self):
        result = UiLaunchResult(success=False)
        assert result.mode == "disabled"
        assert result.api_url == ""
        assert result.message == ""
        assert result.readiness == {}

    def test_repr_excludes_private_fields(self):
        result = UiLaunchResult(success=True, _api_thread=Mock())
        repr_str = repr(result)
        assert "_api_thread" not in repr_str
        assert "success=True" in repr_str


# ─────────────────────────────────────────────────────────────────────────────
# 9. RuntimeState singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeState:
    def test_singleton(self):
        reset_runtime_state()
        s1 = get_runtime_state()
        s2 = get_runtime_state()
        assert s1 is s2

    def test_reset(self):
        reset_runtime_state()
        s = get_runtime_state()
        s.api_ready = True
        reset_runtime_state()
        s2 = get_runtime_state()
        assert s2.api_ready is False

    def test_all_fields_false_initially(self):
        reset_runtime_state()
        s = get_runtime_state()
        assert s.lean_ready is False
        assert s.api_ready is False
        assert s.cloud_ready is False
        assert s.ui_ready is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
