"""
test_builtin_tools.py — Unit tests for niblit_tools/builtin_tools.py

Covers calculator, get_datetime, word_count, kb_query, list_commands,
summarise_text, and the register_all() integration with ToolRegistry.

Run with::

    pytest test_builtin_tools.py -v
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    from niblit_tools.builtin_tools import (
        calculator,
        get_datetime,
        word_count,
        kb_query,
        list_commands,
        summarise_text,
        register_all,
        _safe_eval,
    )
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="builtin_tools module not available")


# ---------------------------------------------------------------------------
# calculator
# ---------------------------------------------------------------------------

class TestCalculator:
    def test_simple_addition(self):
        assert calculator("1 + 1") == "2"

    def test_subtraction(self):
        assert calculator("10 - 3") == "7"

    def test_multiplication(self):
        assert calculator("6 * 7") == "42"

    def test_division(self):
        result = calculator("10 / 4")
        assert result == "2.5"

    def test_power(self):
        assert calculator("2 ** 10") == "1024"

    def test_floor_division(self):
        assert calculator("17 // 5") == "3"

    def test_modulo(self):
        assert calculator("17 % 5") == "2"

    def test_sqrt_via_math(self):
        assert calculator("sqrt(16)") == "4"

    def test_pi(self):
        result = float(calculator("pi"))
        assert abs(result - 3.14159) < 0.001

    def test_nested_expression(self):
        assert calculator("(3 + 4) * 2") == "14"

    def test_negative_number(self):
        assert calculator("-5 + 10") == "5"

    def test_invalid_expression_returns_error(self):
        result = calculator("import os")
        assert "error" in result.lower()

    def test_invalid_syntax_returns_error(self):
        result = calculator("1 +* 2")
        assert "error" in result.lower()

    def test_unsafe_name_returns_error(self):
        result = calculator("__import__('os')")
        assert "error" in result.lower()

    def test_returns_string(self):
        assert isinstance(calculator("2 + 2"), str)


# ---------------------------------------------------------------------------
# get_datetime
# ---------------------------------------------------------------------------

class TestGetDatetime:
    def test_returns_string(self):
        assert isinstance(get_datetime(), str)

    def test_format_both(self):
        result = get_datetime("both")
        assert "UTC" in result
        # Should contain both date and time components
        assert "-" in result and ":" in result

    def test_format_date(self):
        result = get_datetime("date")
        assert "UTC" in result
        assert "-" in result
        assert ":" not in result

    def test_format_time(self):
        result = get_datetime("time")
        assert "UTC" in result
        assert ":" in result

    def test_default_format(self):
        result = get_datetime()
        assert "UTC" in result

    def test_unknown_format_falls_through_to_both(self):
        result = get_datetime("unknown")
        assert "UTC" in result


# ---------------------------------------------------------------------------
# word_count
# ---------------------------------------------------------------------------

class TestWordCount:
    def test_basic_count(self):
        result = word_count("hello world")
        assert "Words: 2" in result
        assert "Characters: 11" in result
        assert "Lines: 1" in result

    def test_multiline(self):
        result = word_count("line one\nline two")
        assert "Lines: 2" in result

    def test_empty_string(self):
        result = word_count("")
        assert "Words: 0" in result
        assert "Lines: 0" in result

    def test_returns_string(self):
        assert isinstance(word_count("test"), str)

    def test_single_word(self):
        result = word_count("hi")
        assert "Words: 1" in result


# ---------------------------------------------------------------------------
# kb_query
# ---------------------------------------------------------------------------

class TestKbQuery:
    def test_kb_unavailable_returns_error_message(self):
        with patch.dict("sys.modules", {"niblit_memory": None}):
            result = kb_query("test query")
            assert isinstance(result, str)

    def test_returns_string(self):
        result = kb_query("test")
        assert isinstance(result, str)

    def test_no_results_message(self):
        mem_mock = MagicMock()
        mem_mock.return_value.search.return_value = []
        with patch("niblit_tools.builtin_tools.NiblitMemory", mem_mock, create=True):
            try:
                from niblit_tools import builtin_tools
                original = getattr(builtin_tools, "NiblitMemory", None)
                builtin_tools.NiblitMemory = mem_mock  # type: ignore[attr-defined]
            except Exception:
                pass
        # Falls back gracefully regardless
        result = kb_query("nonexistent query with no results")
        assert isinstance(result, str)

    def test_max_results_respected(self):
        """Passing max_results=1 should not crash."""
        result = kb_query("test", max_results=1)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# list_commands
# ---------------------------------------------------------------------------

class TestListCommands:
    def test_returns_string(self):
        result = list_commands()
        assert isinstance(result, str)

    def test_contains_commands_or_fallback(self):
        result = list_commands()
        # Should either list commands or give a helpful fallback message
        assert len(result) > 0

    def test_with_mocked_commands(self):
        with patch("niblit_tools.builtin_tools.COMMANDS", ["help", "status", "memory"],
                   create=True):
            # The import inside list_commands may succeed or fail — either way it
            # should return a non-empty string
            result = list_commands()
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# summarise_text
# ---------------------------------------------------------------------------

class TestSummariseText:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert summarise_text(text, max_words=50) == text

    def test_long_text_truncated(self):
        words = " ".join(f"word{i}" for i in range(20))
        result = summarise_text(words, max_words=5)
        assert result.endswith(" …")
        assert len(result.split()) == 6  # 5 words + "…"

    def test_empty_string(self):
        assert summarise_text("") == ""

    def test_exact_max_words_not_truncated(self):
        text = "one two three four five"
        result = summarise_text(text, max_words=5)
        assert "…" not in result

    def test_returns_string(self):
        assert isinstance(summarise_text("test text"), str)

    def test_max_words_1(self):
        text = "first second third"
        result = summarise_text(text, max_words=1)
        assert result == "first …"


# ---------------------------------------------------------------------------
# register_all — integration with ToolRegistry
# ---------------------------------------------------------------------------

class TestRegisterAll:
    def test_register_all_adds_tools(self):
        from niblit_tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        register_all(reg)
        tool_names = {t["name"] for t in reg.list_tools()}
        assert "calculator" in tool_names
        assert "get_datetime" in tool_names
        assert "word_count" in tool_names
        assert "kb_query" in tool_names
        assert "list_commands" in tool_names
        assert "summarise_text" in tool_names

    def test_registered_tools_are_callable(self):
        from niblit_tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        register_all(reg)
        result = reg.run("calculator", {"expression": "6 * 7"})
        assert result == "42"

    def test_registered_tools_count(self):
        from niblit_tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        register_all(reg)
        assert len(reg.list_tools()) >= 6
