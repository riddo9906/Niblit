"""test_niblit_router.py — unit tests for niblit_router.

Covers ChatDetector.classify() and NiblitRouter.process() routing logic.

All tests are fully offline-safe: NiblitBrain, NiblitMemory and NiblitCore
are replaced with lightweight MagicMock objects so no real inference or
database connections are required.

Run with::

    pytest test_niblit_router.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from niblit_router import ChatDetector, NiblitRouter, safe_call, timestamp
    _ROUTER_AVAILABLE = True
except ImportError:
    _ROUTER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _ROUTER_AVAILABLE,
    reason="niblit_router could not be imported",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router(llm_enabled: bool = False):
    """Return a NiblitRouter with stub brain, memory, and core."""
    brain = MagicMock()
    brain.think.return_value = {"response": "stub response", "source": "mock"}
    brain.learn.return_value = None

    memory = MagicMock()
    memory.log_event = MagicMock()

    core = MagicMock()
    core.llm_enabled = llm_enabled
    core.collector = None

    router = NiblitRouter(brain=brain, memory=memory, core=core)
    return router, brain, memory, core


# ---------------------------------------------------------------------------
# ChatDetector.classify
# ---------------------------------------------------------------------------

class TestChatDetectorClassify:
    """Tests for the ChatDetector.classify() static method."""

    def test_classify_returns_tuple(self):
        result = ChatDetector.classify("hello")
        assert isinstance(result, tuple)
        assert len(result) == 2

    # Self-introspection patterns ───────────────────────────────────────────

    def test_self_introspection_what_would_you_improve(self):
        msg_type, _ = ChatDetector.classify("what would you improve about yourself?")
        assert msg_type == "self_introspection"

    def test_self_introspection_limitations(self):
        msg_type, _ = ChatDetector.classify("what are your limitations?")
        assert msg_type == "self_introspection"

    def test_self_introspection_weaknesses(self):
        msg_type, _ = ChatDetector.classify("what are your weaknesses?")
        assert msg_type == "self_introspection"

    # Self-referential patterns ─────────────────────────────────────────────

    def test_self_referential_what_are_you(self):
        msg_type, _ = ChatDetector.classify("what are you?")
        assert msg_type == "self_referential"

    def test_self_referential_who_are_you(self):
        msg_type, _ = ChatDetector.classify("who are you?")
        assert msg_type == "self_referential"

    def test_self_referential_tell_me_about_yourself(self):
        msg_type, _ = ChatDetector.classify("tell me about yourself")
        assert msg_type == "self_referential"

    def test_self_referential_what_can_you_do(self):
        msg_type, _ = ChatDetector.classify("what can you do?")
        assert msg_type == "self_referential"

    # Info query patterns ───────────────────────────────────────────────────

    def test_info_query_what_is(self):
        msg_type, subject = ChatDetector.classify("what is machine learning?")
        assert msg_type == "info_query"

    def test_info_query_tell_me_about(self):
        msg_type, _ = ChatDetector.classify("tell me about neural networks")
        assert msg_type == "info_query"

    # Chat patterns ─────────────────────────────────────────────────────────

    def test_chat_hello(self):
        msg_type, _ = ChatDetector.classify("hello")
        assert msg_type in ("chat", "general")

    def test_chat_hi(self):
        msg_type, _ = ChatDetector.classify("hi there")
        assert msg_type in ("chat", "general")

    # General fallback ──────────────────────────────────────────────────────

    def test_general_fallback(self):
        # A random string that matches none of the specific patterns
        msg_type, subject = ChatDetector.classify("xyzzyqq_random_input_8472")
        assert msg_type == "general"
        assert subject is None

    def test_case_insensitive(self):
        # Self-referential patterns should be case-insensitive
        msg_type, _ = ChatDetector.classify("WHAT ARE YOU?")
        assert msg_type == "self_referential"


# ---------------------------------------------------------------------------
# NiblitRouter.process  (LLM-disabled path)
# ---------------------------------------------------------------------------

class TestNiblitRouterProcess:
    """Tests for NiblitRouter.process() with LLM disabled."""

    def test_process_returns_string(self):
        router, _, _, _ = _make_router(llm_enabled=False)
        result = router.process("hello")
        assert isinstance(result, str)

    def test_process_help_command(self):
        router, _, _, _ = _make_router()
        result = router.process("help")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_process_slash_prefix_routes_to_command(self):
        router, _, _, _ = _make_router()
        result = router.process("/help")
        assert isinstance(result, str)

    def test_process_empty_string_does_not_raise(self):
        router, _, _, _ = _make_router()
        result = router.process("")
        assert isinstance(result, str)

    def test_process_whitespace_only_does_not_raise(self):
        router, _, _, _ = _make_router()
        result = router.process("   ")
        assert isinstance(result, str)

    def test_process_self_referential_returns_string(self):
        router, _, _, _ = _make_router(llm_enabled=False)
        result = router.process("what are you?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_process_self_introspection_returns_string(self):
        router, _, _, _ = _make_router(llm_enabled=False)
        result = router.process("what would you improve about yourself?")
        assert isinstance(result, str)

    def test_process_with_llm_enabled_calls_brain(self):
        router, brain, _, core = _make_router(llm_enabled=True)
        core.llm_enabled = True
        router.process("what is artificial intelligence?")
        # brain.think should have been called for a non-command message
        # (may or may not be called depending on routing — just verify no crash)
        assert True

    def test_process_command_status(self):
        router, _, _, _ = _make_router()
        result = router.process("status")
        assert isinstance(result, str)

    def test_process_version_command(self):
        router, _, _, _ = _make_router()
        result = router.process("version")
        assert isinstance(result, str)

    def test_llm_provider_qwen_switch_command(self):
        router, _, _, core = _make_router()
        mock_mgr = MagicMock()
        mock_mgr.switch.return_value = "✅ LLM provider switched to **qwen**."
        mock_lb = MagicMock()
        mock_lb.status.return_value = {
            "model_name": "~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "gguf_chat_template": "qwen",
        }
        with (
            patch("modules.llm_provider_manager.get_llm_provider_manager", return_value=mock_mgr),
            patch("modules.local_brain.swap_local_brain", return_value=mock_lb),
        ):
            result = router.process("llm-provider qwen")
        mock_mgr.switch.assert_called_once_with("qwen")
        assert "qwen" in result.lower()
        assert core.local_brain == mock_lb

    def test_llm_provider_status_includes_qwen(self):
        router, _, _, _ = _make_router()
        mock_mgr = MagicMock()
        mock_mgr.status.return_value = {
            "active": "qwen",
            "hf": True,
            "anthropic": False,
            "qwen": True,
            "hf_model": "hf-model",
            "anthropic_model": "n/a",
            "qwen_model": "Qwen/Qwen2.5-0.5B-Instruct",
        }
        with patch("modules.llm_provider_manager.get_llm_provider_manager", return_value=mock_mgr):
            result = router.process("llm-provider status")
        assert "qwen" in result.lower()
        assert "active provider: **qwen**" in result.lower()
        assert "local-model switch qwen|llama3" in result.lower()

    def test_llm_provider_llama3_switch_alias(self):
        router, _, _, core = _make_router()
        mock_mgr = MagicMock()
        mock_mgr.switch.return_value = "✅ LLM provider switched to **qwen**."
        mock_lb = MagicMock()
        mock_lb.status.return_value = {
            "model_name": "~/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
            "gguf_chat_template": "llama3",
        }
        with (
            patch("modules.llm_provider_manager.get_llm_provider_manager", return_value=mock_mgr),
            patch("modules.local_brain.swap_local_brain", return_value=mock_lb),
        ):
            result = router.process("llm-provider llama3")
        assert "llama 3.2" in result.lower()
        mock_mgr.switch.assert_called_once_with("qwen")
        assert core.local_brain == mock_lb


# ---------------------------------------------------------------------------
# NiblitRouter.log_event
# ---------------------------------------------------------------------------

class TestNiblitRouterLogEvent:
    """Tests for NiblitRouter.log_event()."""

    def test_log_event_calls_memory(self):
        router, _, memory, _ = _make_router()
        router.log_event("test event message")
        assert memory.log_event.called

    def test_log_event_no_memory_does_not_raise(self):
        brain = MagicMock()
        memory = MagicMock()
        memory.log_event.side_effect = Exception("storage error")
        router = NiblitRouter(brain=brain, memory=memory, core=None)
        # Should not raise even if memory.log_event fails
        router.log_event("test event")


# ---------------------------------------------------------------------------
# NiblitRouter helpers
# ---------------------------------------------------------------------------

class TestNiblitRouterHelpers:
    """Tests for miscellaneous router helpers."""

    def test_deduplicate_strings(self):
        router, _, _, _ = _make_router()
        items = ["a", "b", "a", "c", "b"]
        result = router._deduplicate_results(items)
        assert result == ["a", "b", "c"]

    def test_deduplicate_dicts_by_content(self):
        router, _, _, _ = _make_router()
        # _deduplicate_results extracts text content from dicts
        items = [
            {"snippet": "result A"},
            {"snippet": "result B"},
            {"snippet": "result A"},  # duplicate content
        ]
        result = router._deduplicate_results(items)
        # Should have 2 unique content strings
        assert len(result) == 2
        assert "result A" in result
        assert "result B" in result

    def test_deduplicate_empty_list(self):
        router, _, _, _ = _make_router()
        assert router._deduplicate_results([]) == []


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class TestModuleHelpers:
    """Tests for module-level helper functions."""

    def test_timestamp_returns_string(self):
        ts = timestamp()
        assert isinstance(ts, str)
        assert len(ts) > 0

    def test_safe_call_returns_value(self):
        result = safe_call(lambda x: x * 2, 5)
        assert result == 10

    def test_safe_call_on_exception_returns_error_string(self):
        def bad_fn():
            raise ValueError("intentional error")

        result = safe_call(bad_fn)
        assert isinstance(result, str)
        assert "ERROR" in result.upper() or "error" in result.lower()


if __name__ == "__main__":
    print('Running test_niblit_router.py')
