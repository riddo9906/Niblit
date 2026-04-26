"""
modules/utils.py — Shared utility functions used across Niblit.

Centralises helpers that were previously duplicated in niblit_core.py,
niblit_router.py and app.py.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Callable, Optional

log = logging.getLogger("Niblit.Utils")


def safe_call(fn: Callable, *a: Any, **kw: Any) -> Optional[Any]:
    """Call fn(*a, **kw) safely, logging and returning None on failure."""
    try:
        return fn(*a, **kw)
    except Exception as exc:
        name = getattr(fn, "__name__", repr(fn))
        log.debug("safe_call suppressed exception for %s: %s", name, exc)
        return None


def timestamp() -> str:
    """Return a human-readable UTC timestamp string: [YYYY-MM-DD HH:MM:SS]."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("[%Y-%m-%d %H:%M:%S]")
