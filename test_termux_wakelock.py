"""
test_termux_wakelock.py — Unit tests for modules/termux_wakelock.py

All subprocess calls are mocked so these tests run on any platform (Linux CI,
macOS, Windows) without requiring a real Termux environment.

Run with::

    pytest test_termux_wakelock.py -v
"""

import shutil
import subprocess
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from modules.termux_wakelock import TermuxWakeLock, _is_termux, _run, get_wakelock


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _termux_wl(enable_notification=False):
    """Return a TermuxWakeLock whose _check_available() always returns True."""
    wl = TermuxWakeLock(enable_notification=enable_notification)
    wl._available = True  # bypass Termux detection
    return wl


# ──────────────────────────────────────────────────────────────────────────────
# _is_termux helper
# ──────────────────────────────────────────────────────────────────────────────

class TestIsTermux:
    def test_returns_true_when_which_finds_command(self):
        with patch("shutil.which", return_value="/usr/bin/termux-wake-lock"):
            assert _is_termux() is True

    def test_returns_false_when_no_indicators(self):
        with (
            patch("shutil.which", return_value=None),
            patch("os.path.isdir", return_value=False),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert _is_termux() is False

    def test_returns_true_from_env_variable(self):
        with (
            patch("shutil.which", return_value=None),
            patch("os.path.isdir", return_value=False),
            patch.dict("os.environ", {"TERMUX_VERSION": "0.118"}, clear=False),
        ):
            assert _is_termux() is True

    def test_returns_true_from_com_termux_dir(self):
        with (
            patch("shutil.which", return_value=None),
            patch("os.path.isdir", return_value=True),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert _is_termux() is True


# ──────────────────────────────────────────────────────────────────────────────
# _run helper
# ──────────────────────────────────────────────────────────────────────────────

class TestRun:
    def test_returns_true_on_zero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert _run(["termux-wake-lock"]) is True

    def test_returns_false_on_nonzero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert _run(["termux-wake-lock"]) is False

    def test_returns_false_on_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _run(["termux-wake-lock"]) is False

    def test_returns_false_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
            assert _run(["termux-wake-lock"]) is False

    def test_returns_false_on_os_error(self):
        with patch("subprocess.run", side_effect=OSError("nope")):
            assert _run(["termux-wake-lock"]) is False


# ──────────────────────────────────────────────────────────────────────────────
# TermuxWakeLock.acquire()
# ──────────────────────────────────────────────────────────────────────────────

class TestAcquire:
    def test_acquire_runs_wake_lock_command(self):
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True) as mock_run:
            ok = wl.acquire()
        assert ok is True
        mock_run.assert_any_call(["termux-wake-lock"])

    def test_acquire_sets_is_acquired(self):
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True):
            wl.acquire()
        assert wl.is_acquired is True

    def test_acquire_idempotent(self):
        """Second acquire() must return False and not re-run the command."""
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True) as mock_run:
            wl.acquire()
            result = wl.acquire()
        assert result is False
        # termux-wake-lock called exactly once
        assert sum(1 for c in mock_run.call_args_list if c == call(["termux-wake-lock"])) == 1

    def test_acquire_returns_false_when_not_available(self):
        wl = TermuxWakeLock()
        wl._available = False
        result = wl.acquire()
        assert result is False
        assert wl.is_acquired is False

    def test_acquire_returns_false_when_command_fails(self):
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=False):
            ok = wl.acquire()
        assert ok is False
        assert wl.is_acquired is False

    def test_acquire_posts_notification_when_enabled(self):
        wl = _termux_wl(enable_notification=True)
        with (
            patch("modules.termux_wakelock._run", return_value=True),
            patch("shutil.which", return_value="/usr/bin/termux-notification"),
        ):
            wl.acquire()
        # Notification command should have been attempted

    def test_acquire_skips_notification_when_disabled(self):
        wl = _termux_wl(enable_notification=False)
        with patch("modules.termux_wakelock._run", return_value=True) as mock_run:
            wl.acquire()
        # Only wake-lock command, not notification
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert not any("termux-notification" in str(c) for c in cmds)


# ──────────────────────────────────────────────────────────────────────────────
# TermuxWakeLock.release()
# ──────────────────────────────────────────────────────────────────────────────

class TestRelease:
    def test_release_runs_wake_unlock_command(self):
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True) as mock_run:
            wl.acquire()
            wl.release()
        mock_run.assert_any_call(["termux-wake-unlock"])

    def test_release_clears_is_acquired(self):
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True):
            wl.acquire()
            wl.release()
        assert wl.is_acquired is False

    def test_release_idempotent(self):
        """release() when not acquired must return False."""
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True) as mock_run:
            result = wl.release()
        assert result is False

    def test_release_clears_acquired_even_if_command_fails(self):
        """Even if termux-wake-unlock exits non-zero, is_acquired must be False."""
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", side_effect=[True, False]):
            wl.acquire()
            wl.release()
        assert wl.is_acquired is False

    def test_acquire_then_release_then_acquire_again(self):
        """Wake lock should be re-acquirable after a full cycle."""
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True):
            wl.acquire()
            wl.release()
            ok = wl.acquire()
        assert ok is True
        assert wl.is_acquired is True


# ──────────────────────────────────────────────────────────────────────────────
# status() and available property
# ──────────────────────────────────────────────────────────────────────────────

class TestStatus:
    def test_status_not_available(self):
        wl = TermuxWakeLock()
        wl._available = False
        assert "not available" in wl.status().lower()

    def test_status_available_not_acquired(self):
        wl = _termux_wl()
        assert "inactive" in wl.status().lower()

    def test_status_acquired(self):
        wl = _termux_wl()
        with patch("modules.termux_wakelock._run", return_value=True):
            wl.acquire()
        assert "active" in wl.status().lower()

    def test_available_property_true_on_termux(self):
        wl = TermuxWakeLock()
        with (
            patch("modules.termux_wakelock._is_termux", return_value=True),
            patch("shutil.which", return_value="/bin/termux-wake-lock"),
        ):
            wl._available = None  # reset cache
            assert wl.available is True

    def test_available_property_false_off_termux(self):
        wl = TermuxWakeLock()
        with (
            patch("modules.termux_wakelock._is_termux", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            wl._available = None
            assert wl.available is False


# ──────────────────────────────────────────────────────────────────────────────
# Thread safety
# ──────────────────────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_acquires_only_one_succeeds(self):
        """Only one acquire() should win; others should return False."""
        wl = _termux_wl()
        results = []

        def try_acquire():
            with patch("modules.termux_wakelock._run", return_value=True):
                results.append(wl.acquire())

        threads = [threading.Thread(target=try_acquire) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 9


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────────────────────────────────────

class TestGetWakelock:
    def test_returns_same_instance(self):
        import modules.termux_wakelock as m
        m._global_wakelock = None  # reset between tests
        a = get_wakelock()
        b = get_wakelock()
        assert a is b

    def test_returns_termux_wakelock_instance(self):
        import modules.termux_wakelock as m
        m._global_wakelock = None
        assert isinstance(get_wakelock(), TermuxWakeLock)


# ──────────────────────────────────────────────────────────────────────────────
# Integration: niblit_core wires the wake-lock correctly
# ──────────────────────────────────────────────────────────────────────────────

class TestNiblitCoreWiring:
    """Smoke-test that NiblitCore creates and uses the wakelock attribute."""

    def _make_core_with_mock_wakelock(self):
        """Import niblit_core and patch TermuxWakeLock before NiblitCore runs."""
        mock_wl = MagicMock()
        mock_wl.acquire.return_value = True
        mock_wl.release.return_value = True
        mock_wl.status.return_value = "🟢 Wake-lock: ACTIVE"
        mock_wl.is_acquired = True

        mock_wl_cls = MagicMock(return_value=mock_wl)

        import niblit_core
        original = niblit_core.TermuxWakeLock
        niblit_core.TermuxWakeLock = mock_wl_cls
        try:
            from niblit_core import NiblitCore
            core = NiblitCore()
        finally:
            niblit_core.TermuxWakeLock = original

        return core, mock_wl

    def test_core_has_wakelock_attribute(self):
        core, _ = self._make_core_with_mock_wakelock()
        assert hasattr(core, "wakelock")

    def test_wakelock_acquire_called_on_startup(self):
        core, mock_wl = self._make_core_with_mock_wakelock()
        mock_wl.acquire.assert_called()

    def test_wakelock_release_called_on_shutdown(self):
        core, mock_wl = self._make_core_with_mock_wakelock()
        core.shutdown()
        mock_wl.release.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
