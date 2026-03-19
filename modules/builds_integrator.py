#!/usr/bin/env python3
"""
modules/builds_integrator.py — Unified integration layer for Niblit's builds/python scripts.

Discovers, imports, and exposes the scripts that the Autonomous Learning Engine
has compiled into ``builds/python/`` so every subsystem that can benefit from
them (NLP preprocessing, data-structure handling, binary inspection, conversation
management) has a single, stable import point.

Integrated builds scripts
--------------------------
* NLP processor  — tokenisation, keyword extraction, n-gram analysis
  (ale_python_natural_language_processi.py)
* JSONL / fused-data structures  — JSONL load/save + FusedMemory integration
  (ale_python_data_structures_1773756657.py)
* Binary file parser  — magic-byte format detection, hexdump, struct parsing
  (ale_python_binary_file_parsing_with_struct_17737559.py)
* Chat-completion client  — conversation-history manager for LLM sessions
  (ale_python_chat_completion_API_clien.py)
* Data processor  — general-purpose null-filtering pipeline
  (ale_python_autonomous_improvement.py)

All imports are lazy and fully fault-tolerant: if a builds script is missing
or raises on import, the corresponding feature degrades gracefully.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("BuildsIntegrator")

# ---------------------------------------------------------------------------
# Path to builds/python — resolved relative to this file's package root
# ---------------------------------------------------------------------------
_BUILDS_PYTHON_DIR: Path = Path(__file__).resolve().parent.parent / "builds" / "python"

# ---------------------------------------------------------------------------
# Lazy-loaded class references (populated once by _ensure_loaded)
# ---------------------------------------------------------------------------
_NLP_CLASS: Optional[Any] = None
_DATA_STRUCT_CLASS: Optional[Any] = None
_BINARY_CLASS: Optional[Any] = None
_CHAT_CLASS: Optional[Any] = None
_DATA_PROC_CLASS: Optional[Any] = None
_LOADED: bool = False


def _load_module_from_path(name: str, path: Path) -> Optional[Any]:
    """Dynamically load a Python file from *path* under the module name *name*."""
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception as exc:
        log.debug("[BuildsIntegrator] Failed to load %s from %s: %s", name, path, exc)
        return None


def _ensure_loaded() -> None:
    """Import all builds/python scripts on first call (idempotent)."""
    global _NLP_CLASS, _DATA_STRUCT_CLASS, _BINARY_CLASS, _CHAT_CLASS, _DATA_PROC_CLASS, _LOADED
    if _LOADED:
        return
    _LOADED = True

    # ── NLP processor ──────────────────────────────────────────────────────
    nlp_path = _BUILDS_PYTHON_DIR / "ale_python_natural_language_processi.py"
    if nlp_path.exists():
        mod = _load_module_from_path("builds_nlp_processor", nlp_path)
        if mod:
            _NLP_CLASS = getattr(mod, "AlePythonNaturalLanguageProcessingWithNltkAn", None)
            if _NLP_CLASS:
                log.info("[BuildsIntegrator] NLP processor loaded ✅")

    # ── JSONL / data structures ────────────────────────────────────────────
    ds_path = _BUILDS_PYTHON_DIR / "ale_python_data_structures_1773756657.py"
    if ds_path.exists():
        mod = _load_module_from_path("builds_data_structures", ds_path)
        if mod:
            _DATA_STRUCT_CLASS = getattr(mod, "AlePythonDataStructures1773756657", None)
            if _DATA_STRUCT_CLASS:
                log.info("[BuildsIntegrator] Data-structures module loaded ✅")

    # ── Binary file parser ─────────────────────────────────────────────────
    bin_path = _BUILDS_PYTHON_DIR / "ale_python_binary_file_parsing_with_struct_17737559.py"
    if bin_path.exists():
        mod = _load_module_from_path("builds_binary_parser", bin_path)
        if mod:
            _BINARY_CLASS = getattr(mod, "AlePythonBinaryFileParsingWithStruct17737559", None)
            if _BINARY_CLASS:
                log.info("[BuildsIntegrator] Binary file parser loaded ✅")

    # ── Chat-completion client ─────────────────────────────────────────────
    chat_path = _BUILDS_PYTHON_DIR / "ale_python_chat_completion_API_clien.py"
    if chat_path.exists():
        mod = _load_module_from_path("builds_chat_client", chat_path)
        if mod:
            _CHAT_CLASS = getattr(mod, "AlePythonChatCompletionApiClientImplementatio", None)
            if _CHAT_CLASS:
                log.info("[BuildsIntegrator] Chat-completion client loaded ✅")

    # ── Data processor (autonomous improvement) ────────────────────────────
    dp_path = _BUILDS_PYTHON_DIR / "ale_python_autonomous_improvement.py"
    if dp_path.exists():
        mod = _load_module_from_path("builds_data_processor", dp_path)
        if mod:
            _DATA_PROC_CLASS = getattr(mod, "DataProcessor", None)
            if _DATA_PROC_CLASS:
                log.info("[BuildsIntegrator] DataProcessor loaded ✅")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class BuildsIntegrator:
    """Unified wrapper around all builds/python scripts.

    Provides high-level methods that the ALE steps and CLI router can call
    without knowing which underlying builds script is being used.

    Parameters
    ----------
    data_dir:
        Directory used by the JSONL data-structures module as its working
        folder.  Defaults to the ``builds/python`` directory.
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        _ensure_loaded()

        self._data_dir = data_dir or str(_BUILDS_PYTHON_DIR)

        # Instantiate each component lazily on first use via properties
        self._nlp: Optional[Any] = None
        self._data_struct: Optional[Any] = None
        self._binary: Optional[Any] = None
        self._chat: Optional[Any] = None
        self._data_proc: Optional[Any] = None

        # Runtime counters
        self._nlp_calls: int = 0
        self._binary_calls: int = 0
        self._jsonl_loads: int = 0
        self._chat_sessions: int = 0
        self._proc_calls: int = 0

        log.info("[BuildsIntegrator] Ready (nlp=%s, data_struct=%s, binary=%s, chat=%s, proc=%s)",
                 _NLP_CLASS is not None, _DATA_STRUCT_CLASS is not None,
                 _BINARY_CLASS is not None, _CHAT_CLASS is not None,
                 _DATA_PROC_CLASS is not None)

    # ── component properties ────────────────────────────────────────────────

    @property
    def nlp(self) -> Optional[Any]:
        """NLP processor singleton."""
        if self._nlp is None and _NLP_CLASS is not None:
            try:
                self._nlp = _NLP_CLASS()
            except Exception as exc:
                log.debug("[BuildsIntegrator] NLP init failed: %s", exc)
        return self._nlp

    @property
    def binary(self) -> Optional[Any]:
        """Binary file parser singleton."""
        if self._binary is None and _BINARY_CLASS is not None:
            try:
                self._binary = _BINARY_CLASS()
            except Exception as exc:
                log.debug("[BuildsIntegrator] Binary parser init failed: %s", exc)
        return self._binary

    @property
    def data_struct(self) -> Optional[Any]:
        """JSONL / fused data-structures instance."""
        if self._data_struct is None and _DATA_STRUCT_CLASS is not None:
            try:
                self._data_struct = _DATA_STRUCT_CLASS(data_dir=self._data_dir)
            except Exception as exc:
                log.debug("[BuildsIntegrator] DataStructures init failed: %s", exc)
        return self._data_struct

    @property
    def data_proc(self) -> Optional[Any]:
        """General-purpose data-processor singleton."""
        if self._data_proc is None and _DATA_PROC_CLASS is not None:
            try:
                self._data_proc = _DATA_PROC_CLASS()
            except Exception as exc:
                log.debug("[BuildsIntegrator] DataProcessor init failed: %s", exc)
        return self._data_proc

    # ── NLP ─────────────────────────────────────────────────────────────────

    def nlp_process(self, text: str) -> Dict[str, Any]:
        """Tokenise *text*, extract keywords, and compute bigrams.

        Returns a dict with keys ``tokens``, ``keywords``, ``bigrams``,
        ``token_count``.  Returns an empty dict when the NLP module is
        unavailable.
        """
        if not text or not text.strip():
            return {}
        proc = self.nlp
        if proc is None:
            return {}
        try:
            self._nlp_calls += 1
            return proc.process(text) or {}
        except Exception as exc:
            log.debug("[BuildsIntegrator] nlp_process failed: %s", exc)
            return {}

    def extract_keywords(self, text: str, top_n: int = 10) -> List[str]:
        """Convenience wrapper — return just the keyword list."""
        result = self.nlp_process(text)
        return result.get("keywords", [])[:top_n]

    # ── Binary ───────────────────────────────────────────────────────────────

    def inspect_binary(self, path: str) -> Dict[str, Any]:
        """Inspect a binary file at *path*: detect format, size, hexdump.

        Returns a dict with keys ``path``, ``format``, ``size``,
        ``hexdump``.  Returns an error dict if inspection fails.
        """
        parser = self.binary
        if parser is None:
            return {"error": "binary parser not available"}
        try:
            self._binary_calls += 1
            return parser.inspect(path) or {}
        except Exception as exc:
            log.debug("[BuildsIntegrator] inspect_binary(%s) failed: %s", path, exc)
            return {"error": str(exc), "path": path}

    # ── JSONL / data structures ───────────────────────────────────────────────

    def load_jsonl(self, path: str) -> int:
        """Load a JSONL file via the data-structures module (writes to FusedMemory).

        Returns the number of records loaded, or 0 on failure.
        """
        ds = self.data_struct
        if ds is None:
            return 0
        try:
            self._jsonl_loads += 1
            return ds.load(path) or 0
        except Exception as exc:
            log.debug("[BuildsIntegrator] load_jsonl(%s) failed: %s", path, exc)
            return 0

    def filter_data(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Filter loaded records via the data-structures module."""
        ds = self.data_struct
        if ds is None:
            return []
        try:
            return ds.filter(**kwargs) or []
        except Exception as exc:
            log.debug("[BuildsIntegrator] filter_data failed: %s", exc)
            return []

    # ── Chat-completion client ────────────────────────────────────────────────

    def create_chat_session(self, system_prompt: str = "You are a helpful assistant.") -> Optional[Any]:
        """Create and return a new chat-completion conversation session.

        The returned object has `.send(user_input)` and `.receive(reply)` methods
        compatible with the builds/python chat-completion client API.
        """
        if _CHAT_CLASS is None:
            return None
        try:
            self._chat_sessions += 1
            return _CHAT_CLASS(system_prompt=system_prompt)
        except Exception as exc:
            log.debug("[BuildsIntegrator] create_chat_session failed: %s", exc)
            return None

    # ── Data processor ────────────────────────────────────────────────────────

    def process_data(self, data: List[Any]) -> List[Any]:
        """Filter nulls from *data* using the DataProcessor pipeline."""
        proc = self.data_proc
        if proc is None:
            return [x for x in data if x is not None]
        try:
            self._proc_calls += 1
            return proc.process(data) or []
        except Exception as exc:
            log.debug("[BuildsIntegrator] process_data failed: %s", exc)
            return [x for x in data if x is not None]

    # ── Enrich KB content ─────────────────────────────────────────────────────

    def enrich_content(self, text: str, topic: str = "") -> Dict[str, Any]:
        """Return NLP-enriched metadata about *text* suitable for KB storage.

        Extracts keywords, bigrams, and token counts.  When the NLP processor
        is unavailable a lightweight fallback is used (word-frequency only).
        """
        if not text or not text.strip():
            return {}

        result = self.nlp_process(text)
        if result:
            return {
                "topic": topic,
                "keywords": result.get("keywords", []),
                "bigrams": result.get("bigrams", []),
                "token_count": result.get("token_count", 0),
                "source": "nlp_builds_integrator",
            }

        # Lightweight fallback when NLP module unavailable
        words = [w.lower() for w in text.split() if len(w) > 3]
        from collections import Counter
        top = [w for w, _ in Counter(words).most_common(10)]
        return {
            "topic": topic,
            "keywords": top,
            "bigrams": [],
            "token_count": len(words),
            "source": "fallback_counter",
        }

    # ── Run all builds (status report) ───────────────────────────────────────

    def run_all(self) -> Dict[str, Any]:
        """Call `.run()` on every available builds component and return results."""
        out: Dict[str, Any] = {}

        if self.nlp is not None:
            try:
                out["nlp"] = self.nlp.run()
            except Exception as exc:
                out["nlp"] = {"error": str(exc)}

        if self.binary is not None:
            try:
                out["binary"] = self.binary.run()
            except Exception as exc:
                out["binary"] = {"error": str(exc)}

        if self.data_struct is not None:
            try:
                out["data_struct"] = self.data_struct.run()
            except Exception as exc:
                out["data_struct"] = {"error": str(exc)}

        # DataProcessor only has .process(); report results count as status
        if self.data_proc is not None:
            out["data_proc"] = {
                "results_buffered": len(getattr(self.data_proc, "results", [])),
            }

        return out

    def status(self) -> Dict[str, Any]:
        """Return availability and usage counters for all builds components."""
        _ensure_loaded()
        return {
            "nlp_available": _NLP_CLASS is not None,
            "data_struct_available": _DATA_STRUCT_CLASS is not None,
            "binary_available": _BINARY_CLASS is not None,
            "chat_available": _CHAT_CLASS is not None,
            "data_proc_available": _DATA_PROC_CLASS is not None,
            "nlp_calls": self._nlp_calls,
            "binary_calls": self._binary_calls,
            "jsonl_loads": self._jsonl_loads,
            "chat_sessions": self._chat_sessions,
            "proc_calls": self._proc_calls,
            "builds_dir": str(_BUILDS_PYTHON_DIR),
            "builds_dir_exists": _BUILDS_PYTHON_DIR.exists(),
        }

    def list_builds(self) -> List[Dict[str, str]]:
        """Return a list of all .py files under builds/python/ with descriptions."""
        _ensure_loaded()
        scripts: List[Dict[str, str]] = []
        if not _BUILDS_PYTHON_DIR.exists():
            return scripts
        for fpath in sorted(_BUILDS_PYTHON_DIR.glob("*.py")):
            desc = ""
            try:
                first_lines = fpath.read_text(encoding="utf-8", errors="replace")[:300]
                for line in first_lines.splitlines():
                    line = line.strip()
                    if line.startswith('"""') or line.startswith("'''"):
                        desc = line.strip('"\' ')
                        if not desc:
                            continue
                        break
                    if line and not line.startswith("#") and not line.startswith("import"):
                        break
            except OSError:
                pass
            scripts.append({"name": fpath.name, "description": desc})
        return scripts
