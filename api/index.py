"""
api/index.py — Vercel Python serverless entry-point for Niblit.

Vercel requires serverless functions to live inside the ``api/`` directory.
This module is the **canonical** Vercel handler: it defines a lightweight
FastAPI application at module level (so Vercel's ASGI runtime detects it
immediately) and lazily boots the full NiblitCore on the first real request.

The Vercel Python runtime looks for a variable named ``app`` that is a valid
ASGI callable.  FastAPI satisfies this requirement natively.

This file is intentionally self-contained so that it never fails to import
due to missing heavy/agentic dependencies.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ── FastAPI application ──────────────────────────────────────────────────────
app = FastAPI(title="Niblit AI", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

log = logging.getLogger("NiblitVercel")

# ── Lazy NiblitCore ─────────────────────────────────────────────────────────
# NiblitCore and its heavy dependencies are only loaded on the first real
# request.  If they are not available (e.g. Lambda storage limits) the API
# still boots and returns a structured error instead of a 500.
_core = None
_core_error: str | None = None
_core_loaded = False


def _get_core():
    """Return the singleton NiblitCore, loading it once on first call."""
    global _core, _core_error, _core_loaded
    if _core_loaded:
        return _core
    _core_loaded = True
    # Add repo root to sys.path so niblit_core is importable when present.
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from niblit_core import NiblitCore  # type: ignore[import]
        _core = NiblitCore()
    except Exception as exc:
        _core_error = str(exc)
        log.warning("NiblitCore unavailable: %s", exc)
    return _core


# ── Request models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str = ""
    message: str = ""


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "niblit", "mode": "minimal"}


@app.get("/")
def index():
    return {
        "status": "ok",
        "service": "Niblit AI",
        "message": "Niblit minimal API is alive!",
    }


@app.get("/ping")
def ping():
    return {"pong": True, "ts": int(time.time())}


@app.post("/chat")
def chat(body: ChatRequest):
    text = (body.text or body.message).strip()
    if not text:
        return JSONResponse(content={"error": "no text provided"}, status_code=400)
    core = _get_core()
    if core is None:
        log.warning("NiblitCore unavailable for chat request")
        return {"reply": "[error] NiblitCore unavailable — see server logs",
                "ts": int(time.time())}
    try:
        reply = core.handle(text)
    except Exception as exc:
        log.error("core.handle error: %s", exc)
        reply = "[error] request failed — see server logs"
    return {"reply": reply, "ts": int(time.time())}


@app.get("/api/status")
def api_status():
    core = _get_core()
    return {
        "core_loaded": core is not None,
        "core_error": _core_error is not None,
        "ts": int(time.time()),
    }
