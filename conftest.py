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
