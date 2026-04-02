"""
api/index.py — Vercel Python serverless entry-point for Niblit.

Vercel requires serverless functions to live inside the ``api/`` directory.
This module is the **canonical** Vercel handler: it defines a lightweight
Flask application at module level (so Vercel's runtime detects it immediately)
and lazily boots the full NiblitCore on the first real request.

The Vercel Python runtime looks for a variable named ``app`` that is a valid
WSGI callable.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

# ── path bootstrap ──────────────────────────────────────────────────────────
# Add the repository root so that ``app``, ``niblit_core``, etc. are importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Flask bootstrap ─────────────────────────────────────────────────────────
try:
    from flask import Flask, request, jsonify, Response
    from flask_cors import CORS
    _flask_ok = True
except ImportError:
    _flask_ok = False

if not _flask_ok:
    raise RuntimeError(
        "Flask is required. Add 'flask' and 'flask-cors' to requirements.txt."
    )

app = Flask(__name__)
CORS(app)

log = logging.getLogger("NiblitVercel")

# ── Lazy NiblitCore ─────────────────────────────────────────────────────────
_core = None
_core_error: str | None = None
_core_loaded = False


def _get_core():
    """Return the singleton NiblitCore, loading it once on first call."""
    global _core, _core_error, _core_loaded
    if _core_loaded:
        return _core
    _core_loaded = True
    try:
        from niblit_core import NiblitCore  # type: ignore[import]
        _core = NiblitCore()
    except Exception as exc:
        _core_error = str(exc)
        log.warning("NiblitCore unavailable: %s", exc)
    return _core


# ── Try to mount the full app.py routes ────────────────────────────────────
# If app.py can be imported cleanly its routes are preferred.  If not, we
# fall back to the minimal routes defined below.
_full_app_mounted = False
try:
    from app import app as _full_app  # type: ignore[import]
    # Replace this module's 'app' with the full application so all routes
    # (/, /chat, /api/*, /mcp, …) are available.
    app = _full_app
    _full_app_mounted = True
except Exception as _import_err:
    log.info(
        "Full app.py not mountable (%s); falling back to minimal handler.",
        _import_err,
    )

# ── Minimal fallback routes (only active when full app.py is unavailable) ──
if not _full_app_mounted:

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "niblit", "mode": "minimal"})

    @app.route("/", methods=["GET"])
    def index():
        return jsonify({
            "service": "Niblit AI",
            "status": "running",
            "note": "full UI unavailable — check build logs",
        })

    @app.route("/ping", methods=["GET"])
    def ping():
        return jsonify({"pong": True, "ts": int(time.time())})

    @app.route("/chat", methods=["POST"])
    def chat():
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or data.get("message") or "").strip()
        if not text:
            return jsonify({"error": "no text provided"}), 400
        core = _get_core()
        if core is None:
            return jsonify({
                "reply": f"[error] NiblitCore unavailable: {_core_error}",
                "ts": int(time.time()),
            })
        try:
            reply = core.process(text)
        except Exception as exc:
            reply = f"[error] {exc}"
        return jsonify({"reply": reply, "ts": int(time.time())})

    @app.route("/api/status", methods=["GET"])
    def api_status():
        core = _get_core()
        return jsonify({
            "core_loaded": core is not None,
            "core_error": _core_error,
            "ts": int(time.time()),
        })
