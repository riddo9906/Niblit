"""
test_llama_server_manager.py — Unit tests for modules/llama_server_manager.py

Tests cover:
- ModelInfo serialisation
- _parse_quantization helper
- Model discovery with temp directories
- Explicit model registration
- adopt_external_server (with a mock HTTP probe)
- health_check without a running server
- switch_model guard (unknown model)
- status() shape
- LlamaServerManager singleton accessor
- RuntimeManager integration (service registered, accessor works)
"""
from __future__ import annotations

import os
import pathlib
import threading
import unittest
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_fake_gguf(directory: pathlib.Path, filename: str, size_bytes: int = 1024) -> pathlib.Path:
    """Create a zero-content placeholder with a .gguf extension."""
    p = directory / filename
    p.write_bytes(b"\x00" * min(size_bytes, 64))  # write a small stub only
    return p


# ── ModelInfo tests ──────────────────────────────────────────────────────────

class TestModelInfo(unittest.TestCase):
    def test_to_dict_fields(self):
        from modules.llama_server_manager import ModelInfo

        info = ModelInfo(name="mymodel", path="/tmp/mymodel.gguf", size_mb=1024.5, quantization="Q4_K_M")
        d = info.to_dict()
        self.assertEqual(d["name"], "mymodel")
        self.assertEqual(d["path"], "/tmp/mymodel.gguf")
        self.assertAlmostEqual(d["size_mb"], 1024.5, places=1)
        self.assertEqual(d["quantization"], "Q4_K_M")
        self.assertFalse(d["is_active"])

    def test_to_dict_active_flag(self):
        from modules.llama_server_manager import ModelInfo

        info = ModelInfo(name="active", path="/tmp/active.gguf", size_mb=0.0, is_active=True)
        self.assertTrue(info.to_dict()["is_active"])


# ── _parse_quantization tests ─────────────────────────────────────────────────

class TestParseQuantization(unittest.TestCase):
    def test_q4_k_m(self):
        from modules.llama_server_manager import _parse_quantization

        self.assertEqual(_parse_quantization("qwen2.5-coder-3b-instruct-q4_k_m.gguf"), "Q4_K_M")

    def test_q8_0(self):
        from modules.llama_server_manager import _parse_quantization

        self.assertEqual(_parse_quantization("llama-3.2-1B-Q8_0.gguf"), "Q8_0")

    def test_no_tag(self):
        from modules.llama_server_manager import _parse_quantization

        self.assertEqual(_parse_quantization("model-without-quant.gguf"), "")

    def test_f16(self):
        from modules.llama_server_manager import _parse_quantization

        self.assertEqual(_parse_quantization("model-f16.gguf"), "F16")


# ── _make_model_info helper ───────────────────────────────────────────────────

class TestMakeModelInfo(unittest.TestCase):
    def test_basic(self):
        from modules.llama_server_manager import _make_model_info

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir) / "qwen2.5-0.5b-Q4_K_M.gguf"
            p.write_bytes(b"x" * 1024)
            info = _make_model_info(p)
            self.assertEqual(info.name, "qwen2.5-0.5b-Q4_K_M")
            self.assertGreater(info.size_mb, 0)
            self.assertEqual(info.quantization, "Q4_K_M")

    def test_override_name(self):
        from modules.llama_server_manager import _make_model_info

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir) / "some-model.gguf"
            p.write_bytes(b"")
            info = _make_model_info(p, override_name="custom-name")
            self.assertEqual(info.name, "custom-name")


# ── LlamaServerManager unit tests ────────────────────────────────────────────

class TestLlamaServerManagerInit(unittest.TestCase):
    def test_init_does_not_raise(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        self.assertIsNotNone(mgr)
        self.assertEqual(mgr.registered_models, {})
        self.assertFalse(mgr._server_ready)

    def test_server_url_default(self):
        from modules.llama_server_manager import LlamaServerManager

        with patch.dict(os.environ, {
            "NIBLIT_LLAMA_SERVER_URL": "",
            "NIBLIT_LLAMA_HOST": "",
            "NIBLIT_LLAMA_SERVER_HOST": "",
            "NIBLIT_LLAMA_PORT": "8080",
        }, clear=False):
            mgr = LlamaServerManager()
            self.assertIn("8080", mgr._server_url)

    def test_custom_server_url(self):
        from modules.llama_server_manager import LlamaServerManager

        with patch.dict(os.environ, {"NIBLIT_LLAMA_SERVER_URL": "http://192.168.1.5:9090"}, clear=False):
            mgr = LlamaServerManager()
            self.assertEqual(mgr._server_url, "http://192.168.1.5:9090")


class TestModelDiscovery(unittest.TestCase):
    def test_discover_empty_directory(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = LlamaServerManager()
            found = mgr.discover_models(extra_dirs=[tmpdir])
            self.assertEqual(found, [])
            self.assertEqual(mgr.registered_models, {})

    def test_discover_finds_gguf_files(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir)
            _make_fake_gguf(p, "qwen-0.5b-Q4_K_M.gguf")
            _make_fake_gguf(p, "llama-1B-Q8_0.gguf")

            mgr = LlamaServerManager()
            found = mgr.discover_models(extra_dirs=[tmpdir])
            names = [m.name for m in found]
            self.assertIn("qwen-0.5b-Q4_K_M", names)
            self.assertIn("llama-1B-Q8_0", names)
            self.assertEqual(len(mgr.registered_models), 2)

    def test_discover_does_not_duplicate(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir)
            _make_fake_gguf(p, "model.gguf")

            mgr = LlamaServerManager()
            mgr.discover_models(extra_dirs=[tmpdir])
            mgr.discover_models(extra_dirs=[tmpdir])  # second pass
            self.assertEqual(len(mgr.registered_models), 1)

    def test_discover_nested_subdirectory(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = pathlib.Path(tmpdir) / "sub" / "deep"
            subdir.mkdir(parents=True)
            _make_fake_gguf(subdir, "nested.gguf")

            mgr = LlamaServerManager()
            found = mgr.discover_models(extra_dirs=[tmpdir])
            self.assertEqual(len(found), 1)
            self.assertIn("nested", mgr.registered_models)


class TestRegisterModel(unittest.TestCase):
    def test_register_explicit_path(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir) / "mymodel-Q4_K_S.gguf"
            p.write_bytes(b"stub")

            mgr = LlamaServerManager()
            info = mgr.register_model(str(p))
            self.assertEqual(info.name, "mymodel-Q4_K_S")
            self.assertEqual(info.quantization, "Q4_K_S")
            self.assertIn("mymodel-Q4_K_S", mgr.registered_models)

    def test_register_with_custom_name(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir) / "somemodel.gguf"
            p.write_bytes(b"stub")

            mgr = LlamaServerManager()
            info = mgr.register_model(str(p), name="preferred-name")
            self.assertEqual(info.name, "preferred-name")
            self.assertIn("preferred-name", mgr.registered_models)


class TestGetRegisteredModels(unittest.TestCase):
    def test_sorted_by_name(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir)
            _make_fake_gguf(p, "zebra.gguf")
            _make_fake_gguf(p, "alpha.gguf")
            _make_fake_gguf(p, "mid.gguf")

            mgr = LlamaServerManager()
            mgr.discover_models(extra_dirs=[tmpdir])
            names = [m.name for m in mgr.get_registered_models()]
            self.assertEqual(names, sorted(names))


class TestAdoptExternalServer(unittest.TestCase):
    def test_adopt_when_server_reachable(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        with patch.object(mgr, "_probe_http", return_value=True):
            result = mgr.adopt_external_server()
        self.assertTrue(result)
        self.assertTrue(mgr._external_server)
        self.assertTrue(mgr._server_ready)

    def test_adopt_when_server_unreachable(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        with patch.object(mgr, "_probe_http", return_value=False):
            result = mgr.adopt_external_server()
        self.assertFalse(result)
        self.assertFalse(mgr._external_server)


class TestHealthCheck(unittest.TestCase):
    def test_stopped_server(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        # No process, no external server → stopped
        snap = mgr.health_check()
        self.assertEqual(snap["status"], "stopped")
        self.assertIsNone(snap["server_pid"])
        self.assertFalse(snap["server_ready"])

    def test_external_server_healthy(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        mgr._external_server = True
        with patch.object(mgr, "_probe_http", return_value=True):
            snap = mgr.health_check()
        self.assertEqual(snap["status"], "healthy")
        self.assertTrue(snap["external"])


class TestSwitchModel(unittest.TestCase):
    def test_switch_to_unknown_model_returns_false(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        result = mgr.switch_model("nonexistent-model")
        self.assertFalse(result)

    def test_switch_to_active_model_is_noop(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        mgr._active_model_name = "current-model"
        # No stop/start should happen
        with patch.object(mgr, "stop") as mock_stop, \
             patch.object(mgr, "start") as mock_start:
            result = mgr.switch_model("current-model")
        self.assertTrue(result)
        mock_stop.assert_not_called()
        mock_start.assert_not_called()


class TestStartNoModelOrBinary(unittest.TestCase):
    def test_start_without_models_returns_false(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        mgr._binary = "/fake/llama-server"
        # No models registered, no env vars
        with patch.object(mgr, "_probe_http", return_value=False), \
             patch.dict(os.environ, {"NIBLIT_GGUF_MODEL_PATH": "", "NIBLIT_LOCAL_MODEL": ""}, clear=False):
            result = mgr.start()
        self.assertFalse(result)

    def test_start_without_binary_returns_false(self):
        import tempfile
        from modules.llama_server_manager import LlamaServerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            p = pathlib.Path(tmpdir) / "model.gguf"
            p.write_bytes(b"stub")

            mgr = LlamaServerManager()
            mgr._binary = None
            mgr.register_model(str(p))
            with patch.object(mgr, "_probe_http", return_value=False):
                result = mgr.start()
            self.assertFalse(result)

    def test_start_adopts_running_server(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        # Simulate an already-running external server
        with patch.object(mgr, "_probe_http", return_value=True):
            result = mgr.start()
        self.assertTrue(result)
        self.assertTrue(mgr._external_server)


class TestStatus(unittest.TestCase):
    def test_status_shape(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        s = mgr.status()
        self.assertIn("status", s)
        self.assertIn("server_url", s)
        self.assertIn("active_model", s)
        self.assertIn("binary", s)
        self.assertIn("autostart", s)
        self.assertIn("models", s)
        self.assertIsInstance(s["models"], list)


class TestHealthMonitor(unittest.TestCase):
    def test_start_stop_health_monitor(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        mgr.start_health_monitor(interval_seconds=1000)  # long interval so it never fires
        self.assertIsNotNone(mgr._health_thread)
        thread_ref = mgr._health_thread
        self.assertTrue(thread_ref.is_alive())
        mgr.stop_health_monitor()
        # After stop, _health_thread is None and the thread is no longer alive
        self.assertIsNone(mgr._health_thread)
        self.assertFalse(thread_ref.is_alive())

    def test_start_monitor_is_idempotent(self):
        from modules.llama_server_manager import LlamaServerManager

        mgr = LlamaServerManager()
        mgr.start_health_monitor(interval_seconds=1000)
        t1 = mgr._health_thread
        mgr.start_health_monitor(interval_seconds=1000)
        t2 = mgr._health_thread
        self.assertIs(t1, t2)
        mgr.stop_health_monitor()


class TestSingleton(unittest.TestCase):
    def test_singleton_returns_same_instance(self):
        # Reset singleton for this test
        import modules.llama_server_manager as mod
        original = mod._manager
        mod._manager = None
        try:
            from modules.llama_server_manager import get_llama_server_manager

            a = get_llama_server_manager()
            b = get_llama_server_manager()
            self.assertIs(a, b)
        finally:
            mod._manager = original


# ── RuntimeManager integration ────────────────────────────────────────────────

class TestRuntimeManagerIntegration(unittest.TestCase):
    """Verify that RuntimeManager registers and exposes llama_server_manager."""

    def test_llama_server_manager_in_diagnostics(self):
        from core.runtime_manager import RuntimeManager

        rm = RuntimeManager()
        diag = rm.get_diagnostics()
        services = diag.get("services", {})
        self.assertIn("llama_server_manager", services)

    def test_get_llama_server_manager_returns_value_or_none(self):
        from core.runtime_manager import RuntimeManager

        rm = RuntimeManager()
        mgr = rm.get_llama_server_manager()
        # Either a LlamaServerManager instance or None (if binary unavailable)
        if mgr is not None:
            self.assertTrue(hasattr(mgr, "discover_models"))
            self.assertTrue(hasattr(mgr, "switch_model"))

    def test_timeline_uses_deque(self):
        import collections
        from core.runtime_manager import RuntimeManager

        rm = RuntimeManager()
        self.assertIsInstance(rm._runtime_timeline, collections.deque)
        self.assertEqual(rm._runtime_timeline.maxlen, 1000)

    def test_lifecycle_invalid_transition_ignored(self):
        from core.runtime_manager import RuntimeManager

        rm = RuntimeManager()
        # Attempt an invalid transition
        initial = rm._lifecycle_state
        rm._transition_lifecycle("stopped", "created")  # invalid path
        # State must not have changed
        self.assertEqual(rm._lifecycle_state, initial)

    def test_lifecycle_valid_transition_applied(self):
        from core.runtime_manager import RuntimeManager

        rm = RuntimeManager()
        # Force a known valid transition path
        rm._lifecycle_state = "loaded"
        rm._transition_lifecycle("loaded", "ready")
        self.assertEqual(rm._lifecycle_state, "ready")


if __name__ == "__main__":
    unittest.main()
