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


def pytest_sessionfinish(session, exitstatus):
    """Force a clean OS-level exit to prevent SIGABRT crashes.

    Heavy native extensions (torch, faiss-cpu, CUDA libraries) can trigger
    ``terminate called without an active exception`` (exit code 134) during
    normal Python GC when their C++ destructors run after the interpreter
    shuts down.  Calling ``os._exit()`` bypasses the GC/atexit chain while
    still propagating the correct pytest exit code (0 = all passed, non-zero
    = failures).
    """
    os._exit(int(exitstatus))
