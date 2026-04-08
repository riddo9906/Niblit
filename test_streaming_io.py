"""
test_streaming_io.py — Unit tests for NiblitIO streaming output (niblit_io.py)
and the Ollama-inspired CLI argument parser (main.py).

Run with::

    pytest test_streaming_io.py -v
"""

import sys
import io as _io
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# NiblitIO.stream_out
# ---------------------------------------------------------------------------

class TestNiblitIOStreamOut:
    def setup_method(self):
        from niblit_io import NiblitIO
        NiblitIO._quiet = False  # reset before each test

    def test_stream_out_returns_full_text(self):
        from niblit_io import NiblitIO
        with patch("sys.stdout", new_callable=_io.StringIO):
            result = NiblitIO.stream_out(["Hello", ", ", "world", "!"])
        assert result == "Hello, world!"

    def test_stream_out_prints_tokens(self):
        from niblit_io import NiblitIO
        buf = _io.StringIO()
        with patch("sys.stdout", buf):
            NiblitIO.stream_out(["foo", "bar"])
        output = buf.getvalue()
        assert "foo" in output
        assert "bar" in output

    def test_stream_out_quiet_mode_skips_print(self):
        from niblit_io import NiblitIO
        NiblitIO._quiet = True
        buf = _io.StringIO()
        with patch("sys.stdout", buf):
            result = NiblitIO.stream_out(["a", "b", "c"])
        assert buf.getvalue() == ""
        assert result == "abc"

    def test_stream_out_accepts_generator(self):
        from niblit_io import NiblitIO

        def _gen():
            for ch in "xyz":
                yield ch

        with patch("sys.stdout", new_callable=_io.StringIO):
            result = NiblitIO.stream_out(_gen())
        assert result == "xyz"

    def test_stream_out_custom_end(self):
        from niblit_io import NiblitIO
        buf = _io.StringIO()
        with patch("sys.stdout", buf):
            NiblitIO.stream_out(["hi"], end="")
        output = buf.getvalue()
        assert output == "hi"

    def test_stream_out_empty_tokens(self):
        from niblit_io import NiblitIO
        with patch("sys.stdout", new_callable=_io.StringIO):
            result = NiblitIO.stream_out([])
        assert result == ""

    def test_stream_out_no_delay_by_default(self):
        """stream_out with delay=0 must not call time.sleep."""
        from niblit_io import NiblitIO
        with patch("time.sleep") as mock_sleep:
            with patch("sys.stdout", new_callable=_io.StringIO):
                NiblitIO.stream_out(["a", "b"])
        mock_sleep.assert_not_called()

    def test_stream_out_delay_calls_sleep(self):
        from niblit_io import NiblitIO
        with patch("time.sleep") as mock_sleep:
            with patch("sys.stdout", new_callable=_io.StringIO):
                NiblitIO.stream_out(["a", "b"], delay=0.1)
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# NiblitIO.stream_lines
# ---------------------------------------------------------------------------

class TestNiblitIOStreamLines:
    def setup_method(self):
        from niblit_io import NiblitIO
        NiblitIO._quiet = False

    def test_stream_lines_yields_all_lines(self):
        from niblit_io import NiblitIO
        with patch("sys.stdout", new_callable=_io.StringIO):
            lines = list(NiblitIO.stream_lines("line1\nline2\nline3"))
        assert lines == ["line1", "line2", "line3"]

    def test_stream_lines_single_line(self):
        from niblit_io import NiblitIO
        with patch("sys.stdout", new_callable=_io.StringIO):
            lines = list(NiblitIO.stream_lines("only one"))
        assert lines == ["only one"]

    def test_stream_lines_quiet_mode_no_output(self):
        from niblit_io import NiblitIO
        NiblitIO._quiet = True
        buf = _io.StringIO()
        with patch("sys.stdout", buf):
            lines = list(NiblitIO.stream_lines("a\nb"))
        assert buf.getvalue() == ""
        assert lines == ["a", "b"]

    def test_stream_lines_is_generator(self):
        """stream_lines must be a generator (lazy evaluation)."""
        import inspect
        from niblit_io import NiblitIO
        gen = NiblitIO.stream_lines("hello\nworld")
        assert inspect.isgenerator(gen)

    def test_stream_lines_empty_string(self):
        from niblit_io import NiblitIO
        with patch("sys.stdout", new_callable=_io.StringIO):
            lines = list(NiblitIO.stream_lines(""))
        # "".splitlines() returns [] in Python — no lines to yield
        assert lines == []


# ---------------------------------------------------------------------------
# parse_args — CLI argument parser (main.py)
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_default_args_no_one_shot(self):
        import main
        args = main.parse_args([])
        assert args.one_shot is None

    def test_default_quiet_false(self):
        import main
        args = main.parse_args([])
        assert args.quiet is False

    def test_default_debug_false(self):
        import main
        args = main.parse_args([])
        assert args.debug is False

    def test_one_shot_short_flag(self):
        import main
        args = main.parse_args(["-c", "status"])
        assert args.one_shot == "status"

    def test_one_shot_long_flag(self):
        import main
        args = main.parse_args(["--one-shot", "help"])
        assert args.one_shot == "help"

    def test_quiet_short_flag(self):
        import main
        args = main.parse_args(["-q"])
        assert args.quiet is True

    def test_quiet_long_flag(self):
        import main
        args = main.parse_args(["--quiet"])
        assert args.quiet is True

    def test_debug_flag(self):
        import main
        args = main.parse_args(["--debug"])
        assert args.debug is True

    def test_version_flag_raises_system_exit(self):
        import main
        with pytest.raises(SystemExit) as exc_info:
            main.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_combined_flags(self):
        import main
        args = main.parse_args(["-q", "--debug", "-c", "memory"])
        assert args.quiet is True
        assert args.debug is True
        assert args.one_shot == "memory"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
