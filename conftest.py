"""
conftest.py — pytest configuration for the Niblit project.

The project root contains an __init__.py (marking it as a Python package).
Without this file pytest's default import mode inserts the *parent* directory
into sys.path, making top-level modules like niblit_sqlite_db unreachable.
Inserting the project root here ensures all local modules are importable
regardless of how pytest resolves the package hierarchy.
"""

import os
import sys


# Ensure the project root is always on sys.path so that bare imports such as
#   from niblit_sqlite_db import NiblitSQLiteDB
# work correctly even when the directory is treated as a package by pytest.
_project_root = os.path.abspath(os.path.dirname(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# Store the exitstatus from pytest_sessionfinish so we can use it in
# pytest_unconfigure (which fires after all terminal output is flushed).
_exit_status: int = 0


def pytest_sessionfinish(session, exitstatus):
    """Capture the exit status for use in pytest_unconfigure."""
    global _exit_status
    _exit_status = int(exitstatus)


def pytest_unconfigure(config):
    """Force a clean OS-level exit to prevent SIGABRT crashes.

    Heavy native extensions (torch, faiss-cpu, CUDA libraries) can trigger
    ``terminate called without an active exception`` (exit code 134) during
    normal Python GC when their C++ destructors run after the interpreter
    shuts down.  Calling ``os._exit()`` bypasses the GC/atexit chain while
    still propagating the correct pytest exit code (0 = all passed, non-zero
    = failures).

    This hook fires *after* the terminal reporter has written the full test
    summary (including failure details), so no output is lost.
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(_exit_status)


if __name__ == "__main__":
    print('Running conftest.py')
