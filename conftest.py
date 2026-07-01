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
from pathlib import Path

# Ensure the repository root itself is importable before any local imports.
_CONFTST_REPO_ROOT = Path(__file__).resolve().parent
if str(_CONFTST_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONFTST_REPO_ROOT))

# Install the shared package import hook FIRST, before any other imports.
# This must happen before pytest's collection phase processes any test module.
import importlib.abc
import importlib.machinery
import importlib.util

class _RepoSharedFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'shared':
            candidate = _CONFTST_REPO_ROOT / 'shared' / '__init__.py'
            if not candidate.exists():
                return None
            return importlib.util.spec_from_file_location(
                fullname,
                candidate,
                submodule_search_locations=[str(candidate.parent)],
            )
        if fullname.startswith('shared.'):
            module_name = fullname.split('.', 1)[1]
            candidate = _CONFTST_REPO_ROOT / 'shared' / f'{module_name}.py'
            package_candidate = _CONFTST_REPO_ROOT / 'shared' / module_name / '__init__.py'
            if candidate.exists():
                return importlib.util.spec_from_file_location(fullname, candidate)
            if package_candidate.exists():
                return importlib.util.spec_from_file_location(
                    fullname,
                    package_candidate,
                    submodule_search_locations=[str(package_candidate.parent)],
                )
        return None

if not any(isinstance(finder, _RepoSharedFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _RepoSharedFinder())

from modules.runtime_bootstrap import bootstrap_runtime_environment


# Ensure the project root is always on sys.path so that bare imports such as
#   from niblit_sqlite_db import NiblitSQLiteDB
# work correctly even when the directory is treated as a package by pytest.
repo_root = bootstrap_runtime_environment(__file__)
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


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
