"""
test_main.py — Unit tests for main.py shell behaviour.

Focuses on the graceful-shutdown paths added to fix the self-lock / Ctrl+C
data-loss issue (GitHub issue: "Fix self_lock issue").

Run with::

    pytest test_main.py -v

NiblitCore and NiblitIO are stubbed so no real services are started.
"""

import sys
import signal
import threading
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_core(running=True):
    core = MagicMock()
    core.running = running
    core.router = None
    core.llm_enabled = True
    core.db.recent_interactions.return_value = []
    core.handle.return_value = "ok"
    core.shutdown.return_value = None
    core.help_text.return_value = "help text"
    return core


def _make_io():
    io = MagicMock()
    io.out = MagicMock()
    io.error = MagicMock()
    return io


# ---------------------------------------------------------------------------
# run_shell — KeyboardInterrupt path
# ---------------------------------------------------------------------------

class TestRunShellKeyboardInterrupt:
    """Ctrl+C (KeyboardInterrupt) must trigger core.shutdown() and return."""

    def test_keyboard_interrupt_calls_shutdown(self):
        """Pressing Ctrl+C should call core.shutdown() before returning."""
        import main

        core = _make_core()
        io = _make_io()

        # First input() call raises KeyboardInterrupt
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            main.run_shell(core, io)

        core.shutdown.assert_called_once()

    def test_keyboard_interrupt_returns_cleanly(self):
        """run_shell should return normally after KeyboardInterrupt (no re-raise)."""
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=KeyboardInterrupt):
            # Must not raise
            main.run_shell(core, io)

    def test_keyboard_interrupt_outputs_saving_message(self):
        """User should see a message telling them data is being saved."""
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=KeyboardInterrupt):
            main.run_shell(core, io)

        # Check that at least one out() call mentioned saving/interrupted
        all_calls = " ".join(str(c) for c in io.out.call_args_list).lower()
        assert "interrupt" in all_calls or "saving" in all_calls

    def test_keyboard_interrupt_shutdown_exception_does_not_propagate(self):
        """Even if core.shutdown() raises, run_shell must not propagate the error."""
        import main

        core = _make_core()
        core.shutdown.side_effect = RuntimeError("shutdown failed")
        io = _make_io()

        with patch("builtins.input", side_effect=KeyboardInterrupt):
            main.run_shell(core, io)  # must not raise


# ---------------------------------------------------------------------------
# run_shell — EOFError path (Termux stdin close)
# ---------------------------------------------------------------------------

class TestRunShellEOFError:
    """Stdin close (EOFError from input()) must also trigger core.shutdown()."""

    def test_eoferror_calls_shutdown(self):
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=EOFError):
            main.run_shell(core, io)

        core.shutdown.assert_called_once()

    def test_eoferror_returns_cleanly(self):
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=EOFError):
            main.run_shell(core, io)

    def test_eoferror_outputs_message(self):
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=EOFError):
            main.run_shell(core, io)

        all_calls = " ".join(str(c) for c in io.out.call_args_list).lower()
        assert "eof" in all_calls or "closed" in all_calls or "saving" in all_calls


# ---------------------------------------------------------------------------
# run_shell — normal "exit" / "quit" still works
# ---------------------------------------------------------------------------

class TestRunShellNormalExit:
    def test_exit_command_calls_shutdown(self):
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=["exit"]):
            main.run_shell(core, io)

        core.shutdown.assert_called_once()

    def test_quit_command_calls_shutdown(self):
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=["quit"]):
            main.run_shell(core, io)

        core.shutdown.assert_called_once()

    def test_exit_command_returns(self):
        import main

        core = _make_core()
        io = _make_io()

        with patch("builtins.input", side_effect=["exit"]):
            main.run_shell(core, io)


# ---------------------------------------------------------------------------
# run_shell — ordinary Exception does not shut down (loop continues)
# ---------------------------------------------------------------------------

class TestRunShellOrdinaryException:
    def test_ordinary_exception_does_not_call_shutdown(self):
        """A regular exception inside the loop should be caught and loop continues."""
        import main

        core = _make_core()
        # First call raises a non-fatal error; second call raises EOFError to end the loop
        core.handle.side_effect = ValueError("oops")
        io = _make_io()

        with patch("builtins.input", side_effect=["some command", EOFError]):
            main.run_shell(core, io)

        # shutdown called once (from EOFError), not twice
        assert core.shutdown.call_count == 1


# ---------------------------------------------------------------------------
# Signal handler: _shutdown_on_signal
# ---------------------------------------------------------------------------

class TestShutdownOnSignal:
    def test_handler_calls_core_shutdown(self):
        """_shutdown_on_signal should call _active_core.shutdown() if set."""
        import main

        core = _make_core()
        main._active_core = core

        with pytest.raises(SystemExit):
            main._shutdown_on_signal(signal.SIGTERM, None)

        core.shutdown.assert_called_once()

    def test_handler_calls_sys_exit(self):
        """_shutdown_on_signal must always call sys.exit(0)."""
        import main

        main._active_core = None  # no core — should still exit

        with pytest.raises(SystemExit) as exc_info:
            main._shutdown_on_signal(signal.SIGTERM, None)

        assert exc_info.value.code == 0

    def test_handler_tolerates_shutdown_exception(self):
        """Even if core.shutdown() raises, sys.exit(0) must still be called."""
        import main

        core = _make_core()
        core.shutdown.side_effect = RuntimeError("boom")
        main._active_core = core

        with pytest.raises(SystemExit) as exc_info:
            main._shutdown_on_signal(signal.SIGTERM, None)

        assert exc_info.value.code == 0

    def test_handler_no_active_core(self):
        """Handler with no active core must still exit cleanly."""
        import main

        main._active_core = None
        with pytest.raises(SystemExit):
            main._shutdown_on_signal(signal.SIGTERM, None)


# ---------------------------------------------------------------------------
# _active_core is set by run_shell
# ---------------------------------------------------------------------------

class TestActiveCoreExposed:
    def test_active_core_set_after_run_shell_starts(self):
        """run_shell must assign _active_core so signal handlers can reach it."""
        import main

        core = _make_core()
        io = _make_io()

        main._active_core = None

        with patch("builtins.input", side_effect=["exit"]):
            main.run_shell(core, io)

        assert main._active_core is core


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
