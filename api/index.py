"""
api/index.py — Vercel Python serverless entry-point for Niblit.

Vercel requires serverless functions to live inside the ``api/`` directory.
This thin shim adds the repository root to ``sys.path`` so that the full
``app.py`` Flask application (and all its Niblit modules) can be imported
without modification.

The Vercel Python runtime looks for a variable named ``app`` that is a valid
WSGI callable; we simply re-export it from the root ``app.py``.
"""

import os
import sys

# Add repository root to path so ``import app`` resolves to /app.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Re-export the Flask WSGI application.
# Vercel's Python runtime serves the object named ``app``.
from app import app  # noqa: F401, E402  (re-export)
