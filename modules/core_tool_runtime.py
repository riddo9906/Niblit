"""modules/core_tool_runtime.py - Phase 5C governed tool runtime for Core.

Composition module: builds THE configured LlmToolLoop for the canonical Core
inference boundary (server.py /v1/inference/chat) and wires the EXISTING
governed capabilities onto it:

    runtime_status           NiblitToolExecutor (loop default)
    web_search / web_fetch   register_research_tools (Phase 5A/5B)
    trading_runtime_status   register_trading (read-only, real getter)
    run_research             bounded ResearchOrchestrator trigger (Phase 5C)

No new search / persistence / inference surface is created here:
- promoted knowledge persists via the TieredKnowledgeSystem singleton bound
  to ``core.db`` (the same authority AutonomousLearningEngine uses),
- lifecycle events publish via the process EventBus,
- trading stays strictly read-only via the real
  ``core.trading_runtime_manager`` (None -> truthful "unavailable").

The model never gains execution authority: every call is schema-validated by
LlmToolLoop and dispatched only to the read-only capabilities above.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, Optional

from modules.event_bus import get_event_bus
from modules.llm_tool_loop import LlmToolLoop
from modules.command_surface_audit import (
    READ_ONLY as AUDIT_READ_ONLY,
    SIDE_LOW as AUDIT_SIDE_LOW,
    SIDE_NONE as AUDIT_SIDE_NONE,
    VARIANT_SPELLINGS,
    build_original_surface as build_original_surface_audit,
    canonical_id as audit_canonical_id,
)
from modules.research_orchestrator import (
    DEFAULT_MAX_FETCHES,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_SEARCHES,
    ResearchOrchestrator,
    register_research_tools,
)
from modules.tiered_knowledge_system import get_tiered_knowledge_system
from modules.trading_read_tools import register as register_trading

log = logging.getLogger("Niblit.CoreToolRuntime")

RUN_RESEARCH_FUNCTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_research",
        "description": (
            "Run one bounded LLM-supervised research cycle on a topic: "
            "governed web search + fetch, evidence audit, deterministic "
            "promotion gate, and (on approval) tiered-knowledge persistence "
            "with a recall proof. Read-only for the runtime; persists only "
            "promoted knowledge through the canonical store."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "max_searches": {"type": "integer"},
                "max_fetches": {"type": "integer"},
                "max_rounds": {"type": "integer"},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
}

# Hard structural caps - the model can lower budgets, never raise them.
HARD_CAP_SEARCHES = 4
HARD_CAP_FETCHES = 6
HARD_CAP_ROUNDS = 3

_RESEARCH_LOCK = threading.Lock()
_loop_singleton: Optional[LlmToolLoop] = None
_loop_lock = threading.RLock()
_singleton_core_getter: Optional[Callable] = None


def _get_singleton_core() -> Any:
    """Resolve Core through the provider most recently supplied by the host."""
    getter = _singleton_core_getter
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        log.debug("Core provider failed", exc_info=True)
        return None


def _clamped_budget(value: Any, default: int, cap: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, cap))


def run_research_capability(loop: LlmToolLoop, core_getter: Callable,
                            arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Governed run_research trigger (single-flight, hard-capped)."""
    topic = str(arguments.get("topic") or "").strip()
    if not topic:
        return {"error": "missing_topic"}

    if not _RESEARCH_LOCK.acquire(blocking=False):
        return {"error": "research_run_in_progress",
                "detail": "one bounded research run at a time"}
    try:
        core = core_getter() if callable(core_getter) else None
        store = get_tiered_knowledge_system(
            knowledge_db=getattr(core, "db", None))
        orchestrator = ResearchOrchestrator(
            loop=loop,
            knowledge_store=store,
            event_bus=get_event_bus(),
            max_searches=_clamped_budget(arguments.get("max_searches"),
                                         DEFAULT_MAX_SEARCHES,
                                         HARD_CAP_SEARCHES),
            max_fetches=_clamped_budget(arguments.get("max_fetches"),
                                        DEFAULT_MAX_FETCHES,
                                        HARD_CAP_FETCHES),
            max_rounds=_clamped_budget(arguments.get("max_rounds"),
                                       DEFAULT_MAX_ROUNDS,
                                       HARD_CAP_ROUNDS),
            results_per_query=2,
        )
        result = orchestrator.run(topic)
        artifact = result.artifact()
        # Compact tool result (token-bounded); the full artifact stays in the
        # events/logs and in the store itself, never fabricated here.
        return {
            "topic": topic,
            "promotion": artifact["promotion"],
            "stored": artifact["stored"],
            "recall": artifact["recall"],
            "usage": artifact["usage"],
            "errors": artifact["errors"],
            "claims": artifact["candidate"]["learned_claims"][:5],
            "event_types": [e["type"] for e in artifact["events"]],
        }
    except Exception as exc:  # structured failure, never raise into the loop
        log.warning("[CoreToolRuntime] run_research failed: %s", exc)
        return {"error": f"research_failed: {exc}"}
    finally:
        _RESEARCH_LOCK.release()


# ---------------------------------------------------------------------------
# Phase 5D: governed workspace capabilities (list/search/read/write/edit)
# and the bounded test runner.
# ---------------------------------------------------------------------------

WORKSPACE_FUNCTION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "workspace_list": {
        "type": "function",
        "function": {
            "name": "workspace_list",
            "description": (
                "List one directory level of the authorized Niblit workspace "
                "with real file metadata (size, modified time, type). "
                "Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "directory path relative to the "
                                            "workspace root (e.g. modules)"},
                    "max_entries": {"type": "integer"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "workspace_search": {
        "type": "function",
        "function": {
            "name": "workspace_search",
            "description": (
                "Search real workspace file names AND file contents for a "
                "query (bounded grep with line numbers). Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string",
                             "description": "optional subdirectory to scope "
                                            "the search"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    "workspace_read": {
        "type": "function",
        "function": {
            "name": "workspace_read",
            "description": (
                "Read the REAL content of a workspace text/code file "
                "(e.g. .py/.md/.json) through the same renderer authority "
                "the UI file tab uses. Never a summary. Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "workspace_read_pdf": {
        "type": "function",
        "function": {
            "name": "workspace_read_pdf",
            "description": (
                "Extract bounded text with page numbers from a PDF inside "
                "the authorized workspace. Read-only; image-only PDFs "
                "require OCR and are reported as such."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "workspace_inspect_python": {
        "type": "function",
        "function": {
            "name": "workspace_inspect_python",
            "description": (
                "Parse an authorized Python file without executing it. Returns "
                "its module docstring, imports, classes, functions, methods, "
                "and source line ranges. Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "workspace_write": {
        "type": "function",
        "function": {
            "name": "workspace_write",
            "description": (
                "Create or overwrite a workspace text/code file. Automatic "
                "backup of any replaced file is kept. Bounded to the "
                "authorized workspace; forbidden for secrets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    "workspace_edit": {
        "type": "function",
        "function": {
            "name": "workspace_edit",
            "description": (
                "Patch a workspace file by replacing an exact snippet that "
                "must occur exactly once (old_text -> new_text). Automatic "
                "backup kept. Preferred over full-file writes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    "run_tests": {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run pytest on ONE test file inside the workspace with a "
                "fixed, bounded command (no arbitrary commands). Returns "
                "pass/fail plus a truncated output tail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "test_path": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["test_path"],
                "additionalProperties": False,
            },
        },
    },
}


def register_workspace_tools(loop: LlmToolLoop) -> None:
    """Register the governed workspace capabilities on the loop."""
    from modules import workspace_tools as wt

    loop.register_capability(
        "workspace_list",
        lambda **arguments: wt.list_workspace(
            sub_path=str(arguments.get("path", "") or ""),
            max_entries=arguments.get("max_entries"),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_list"],
    )
    loop.register_capability(
        "workspace_search",
        lambda **arguments: wt.search_workspace(
            query=str(arguments.get("query", "")),
            sub_path=str(arguments.get("path", "") or ""),
            max_results=arguments.get("max_results"),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_search"],
    )
    loop.register_capability(
        "workspace_read",
        lambda **arguments: wt.read_workspace(
            rel_path=str(arguments.get("path", "")),
            max_chars=arguments.get("max_chars"),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_read"],
    )
    loop.register_capability(
        "workspace_read_pdf",
        lambda **arguments: wt.read_workspace_pdf(
            rel_path=str(arguments.get("path", "")),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_read_pdf"],
    )
    loop.register_capability(
        "workspace_inspect_python",
        lambda **arguments: wt.inspect_python_workspace(
            rel_path=str(arguments.get("path", "")),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_inspect_python"],
    )
    loop.register_capability(
        "workspace_write",
        lambda **arguments: wt.write_workspace(
            rel_path=str(arguments.get("path", "")),
            content=str(arguments.get("content", "")),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_write"],
    )
    loop.register_capability(
        "workspace_edit",
        lambda **arguments: wt.edit_workspace(
            rel_path=str(arguments.get("path", "")),
            old_text=str(arguments.get("old_text", "")),
            new_text=str(arguments.get("new_text", "")),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["workspace_edit"],
    )
    loop.register_capability(
        "run_tests",
        lambda **arguments: wt.run_tests(
            test_path=str(arguments.get("test_path", "")),
            timeout=arguments.get("timeout"),
            event_bus=get_event_bus(),
        ),
        WORKSPACE_FUNCTION_SCHEMAS["run_tests"],
    )

# ---------------------------------------------------------------------------
# Phase 5F: restored ORIGINAL Niblit knowledge commands (source-traced).
# ---------------------------------------------------------------------------
# Original surface (niblit_core.py COMMANDS list + command_registry.register):
#     "memory"          -> db.recent_interactions(50)      (register @2668)
#     "recall <query>"  -> db.recall(query, limit=8)       (_cmd_recall @3340)
#     "acquired data"   -> db.get_acquired_data(cat, 20)   (_cmd_acquired_data @3373)
#     "knowledge stats" -> db.get_knowledge_summary()      (_cmd_knowledge_stats @3415)
# All four are READ-ONLY against the real KnowledgeDB bound at ``core.db``.
# They are registered on the SAME governed LlmToolLoop — no second executor.

KNOWLEDGE_FUNCTION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "recall": {
        "type": "function",
        "function": {
            "name": "recall",
            "description": (
                "Recall acquired data from KnowledgeDB matching a query. "
                "Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer",
                              "description": "max entries (default 8)"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    "acquired_data": {
        "type": "function",
        "function": {
            "name": "acquired_data",
            "description": (
                "Show acquired data stored in KnowledgeDB, optionally "
                "filtered by category (research|ideas|code|reflection). "
                "Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "limit": {"type": "integer",
                              "description": "max entries (default 20)"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "knowledge_stats": {
        "type": "function",
        "function": {
            "name": "knowledge_stats",
            "description": (
                "KnowledgeDB statistics: fact counts, top tags, ALE step "
                "breakdown"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "memory": {
        "type": "function",
        "function": {
            "name": "memory",
            "description": "Show recent interaction memory entries",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer",
                              "description": "max entries (default 50)"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
}


def _safe_db(core_getter: Callable) -> Any:
    """Return the real KnowledgeDB (``core.db``) or None — never a substitute."""
    try:
        core = core_getter() if callable(core_getter) else None
    except Exception:
        return None
    return getattr(core, "db", None)


def knowledge_recall_capability(db: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Restored original ``recall`` — db.recall(query, limit=8)."""
    if db is None:
        return {"error": "knowledge_db_unavailable"}
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"error": "missing_query"}
    try:
        raw_limit = arguments.get("limit")
        limit = max(1, min(int(raw_limit), 25)) if raw_limit else 8
        results = db.recall(query, limit=limit)
    except Exception as exc:
        return {"error": f"recall_failed: {exc}"}
    entries = []
    for r in list(results or [])[:limit]:
        if isinstance(r, dict):
            entries.append({
                "key": str(r.get("key", r.get("topic", r.get("time", ""))))[:120],
                "value": str(r.get("value", r.get("input", r.get("text", ""))))[:300],
                "tags": [str(t) for t in (r.get("tags") or [])[:3]],
            })
        else:
            entries.append({"value": str(r)[:300]})
    return {"query": query, "count": len(entries), "entries": entries}


def knowledge_acquired_data_capability(db: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Restored original ``acquired data`` — db.get_acquired_data(cat, 20)."""
    if db is None:
        return {"error": "knowledge_db_unavailable"}
    category = str(arguments.get("category") or "").strip() or None
    try:
        raw_limit = arguments.get("limit")
        limit = max(1, min(int(raw_limit), 50)) if raw_limit else 20
        data = db.get_acquired_data(category=category, limit=limit)
    except Exception as exc:
        return {"error": f"acquired_data_failed: {exc}"}
    entries = []
    for fact in list(data or [])[:limit]:
        if isinstance(fact, dict):
            entries.append({
                "key": str(fact.get("key", ""))[:80],
                "value": str(fact.get("value", ""))[:300],
                "tags": [str(t) for t in (fact.get("tags") or [])[:3]],
            })
        else:
            entries.append({"value": str(fact)[:300]})
    return {"category": category, "count": len(entries), "entries": entries}


def knowledge_stats_capability(db: Any, _arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Restored original ``knowledge stats`` — db.get_knowledge_summary()."""
    if db is None:
        return {"error": "knowledge_db_unavailable"}
    try:
        summary = db.get_knowledge_summary()
    except Exception as exc:
        return {"error": f"knowledge_stats_failed: {exc}"}
    return {"summary": str(summary)[:4000]}


def memory_recent_capability(db: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Restored original ``memory`` — db.recent_interactions(50)."""
    if db is None:
        return {"error": "knowledge_db_unavailable"}
    try:
        raw_limit = arguments.get("limit")
        limit = max(1, min(int(raw_limit), 100)) if raw_limit else 50
        entries = db.recent_interactions(limit)
    except Exception as exc:
        return {"error": f"memory_failed: {exc}"}
    items = [str(e)[:300] for e in list(entries or [])[:limit]]
    return {"count": len(items), "entries": items}


def register_knowledge_tools(loop: LlmToolLoop, core_getter: Callable) -> None:
    """Register the restored original knowledge commands on the governed loop."""
    def db_getter() -> Any:
        return _safe_db(core_getter)

    loop.register_capability(
        "recall",
        lambda **arguments: knowledge_recall_capability(db_getter(), arguments),
        KNOWLEDGE_FUNCTION_SCHEMAS["recall"],
    )
    loop.register_capability(
        "acquired_data",
        lambda **arguments: knowledge_acquired_data_capability(db_getter(), arguments),
        KNOWLEDGE_FUNCTION_SCHEMAS["acquired_data"],
    )
    loop.register_capability(
        "knowledge_stats",
        lambda **arguments: knowledge_stats_capability(db_getter(), arguments),
        KNOWLEDGE_FUNCTION_SCHEMAS["knowledge_stats"],
    )
    loop.register_capability(
        "memory",
        lambda **arguments: memory_recent_capability(db_getter(), arguments),
        KNOWLEDGE_FUNCTION_SCHEMAS["memory"],
    )


# ---------------------------------------------------------------------------
# Phase 5G: promoted ORIGINAL read-only commands (evidence-traced, §11)
# ---------------------------------------------------------------------------
# Each entry binds a governed tool name to the ORIGINAL handler that
# niblit_core.py registered. NOTHING is re-implemented: the capability calls the
# SAME handler object Core's own dispatcher calls (core.command_registry) and
# bounds its output. Evidence for every entry lives in
# modules/command_surface_audit.READ_ONLY_EVIDENCE (handler body read during
# Phase 5G-B). Promotion also requires the AST handler scan to find no mutation
# token (enforced by the Phase 5G tests).
#
# requires_attr: core attribute the handler needs (None = always available).
# side_effect_level: AUDIT_SIDE_NONE = pure read; AUDIT_SIDE_LOW = read plus the
# documented, bounded unified-runtime telemetry state write.

MAX_ORIGINAL_OUTPUT_CHARS = 4000

ORIGINAL_READONLY_PROMOTIONS: Dict[str, Dict[str, Any]] = {
    "status": {
        "canonical_id": "status", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "NiblitCore._cmd_status reads memory/loop/epoch telemetry only",
    },
    "health": {
        "canonical_id": "health", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "NiblitCore._cmd_health -> health_check() reads component state",
    },
    "metrics": {
        "canonical_id": "metrics", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "NiblitCore._cmd_metrics reads PerformanceMetrics counters",
    },
    "time": {
        "canonical_id": "time", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "NiblitCore._cmd_time returns datetime.now()",
    },
    "coherence": {
        "canonical_id": "coherence", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "_tcl",
        "evidence": "NiblitCore._cmd_coherence reads TCL status()",
    },
    "help": {
        "canonical_id": "help", "category": "Discoverability", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "NiblitCore._cmd_help returns help_text() from the live registry",
    },
    "dump": {
        "canonical_id": "dump", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "registry lambda reads _dump_loop_count/_get_memory_count",
    },
    "runtime capabilities": {
        "canonical_id": "runtime_capabilities", "category": "Runtime", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "command_registry",
        "evidence": "NiblitCore._cmd_runtime_capabilities -> registry.detailed_report()",
    },
    "sa-structure": {
        "canonical_id": "sa_structure", "category": "Structural", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "structural_awareness.component_report() inventory",
    },
    "sa-threads": {
        "canonical_id": "sa_threads", "category": "Structural", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "threading.enumerate() snapshot",
    },
    "sa-loops": {
        "canonical_id": "sa_loops", "category": "Structural", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "structural_awareness.loop_report()",
    },
    "sa-modules": {
        "canonical_id": "sa_modules", "category": "Structural", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "structural_awareness.module_report()",
    },
    "sa-dashboard": {
        "canonical_id": "sa_dashboard", "category": "Structural", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "structural_awareness.runtime_dashboard()",
    },
    "sa-resources": {
        "canonical_id": "sa_resources", "category": "Structural", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "structural_awareness.resource_report()",
    },
    "build summary": {
        "canonical_id": "build_summary", "category": "Build", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "build_scanner",
        "evidence": "build_scanner.summarize() (read-only directory scan)",
    },
    "build path": {
        "canonical_id": "build_path", "category": "Build", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": None,
        "evidence": "prints the configured build path and sync readiness",
    },
    "scan build": {
        "canonical_id": "scan_build", "category": "Build", "args": ["text"],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "build_scanner",
        "evidence": "build_scanner.scan(subdir) directory listing",
    },
    "read build file": {
        "canonical_id": "read_build_file", "category": "Build", "args": ["text"],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "build_scanner",
        "evidence": "build_scanner.read_file() bounded preview (read-only)",
    },
    "github status": {
        "canonical_id": "github_status", "category": "GitHub", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "github_sync",
        "evidence": "github_sync.status() read-only",
    },
    "github log": {
        "canonical_id": "github_log", "category": "GitHub", "args": ["text"],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "github_sync",
        "evidence": "github_sync.log(n) read-only",
    },
    "ale processes": {
        "canonical_id": "ale_processes", "category": "Autonomous", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "autonomous_engine",
        "evidence": "reads ALE get_learning_stats(), returns text",
    },
    "autonomous-learn status": {
        "canonical_id": "ale_status", "category": "Autonomous", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "autonomous_engine",
        "evidence": "reads ALE get_learning_stats()",
    },
    "autonomous-learn code-status": {
        "canonical_id": "ale_code_status", "category": "Autonomous", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "autonomous_engine",
        "evidence": "reads ALE code-literacy stats",
    },
    # ── unified-runtime read-outs: read + bounded telemetry state write ─────
    # Evidence: NiblitUnifiedRuntime.dispatch_command() renders the cognition
    # read-out and persists its own telemetry state file (single bounded JSON
    # write; no knowledge/workspace/system/trading authority is touched).
    "runtime status": {
        "canonical_id": "unified_runtime_status", "category": "Runtime",
        "args": [], "risk_class": AUDIT_READ_ONLY,
        "side_effect_level": AUDIT_SIDE_LOW,
        "side_effect_detail": ("NiblitUnifiedRuntime.dispatch_command persists its "
                               "telemetry state file (bounded)"),
        "requires_attr": None,
        "evidence": "unified runtime state/provider/deployment read-out",
    },
    "retrieval status": {
        "canonical_id": "retrieval_status", "category": "Research", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_LOW,
        "side_effect_detail": ("NiblitUnifiedRuntime.dispatch_command persists its "
                               "telemetry state file (bounded)"),
        "requires_attr": None,
        "evidence": "AdaptiveRetrievalCognition.render_command telemetry read-out",
    },
    "retrieval inspect": {
        "canonical_id": "retrieval_inspect", "category": "Research",
        "args": ["text"], "risk_class": AUDIT_READ_ONLY,
        "side_effect_level": AUDIT_SIDE_LOW,
        "side_effect_detail": ("NiblitUnifiedRuntime.dispatch_command persists its "
                               "telemetry state file (bounded)"),
        "requires_attr": None,
        "evidence": "retrieval mastery/gaps/lineage inspection read-out",
    },
    "hypothesis status": {
        "canonical_id": "hypothesis_status", "category": "Research", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_LOW,
        "side_effect_detail": ("NiblitUnifiedRuntime.dispatch_command persists its "
                               "telemetry state file (bounded)"),
        "requires_attr": None,
        "evidence": "HypothesisEngine.render_command beliefs/support read-out",
    },
    "hypothesis list": {
        "canonical_id": "hypothesis_list", "category": "Research", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_LOW,
        "side_effect_detail": ("NiblitUnifiedRuntime.dispatch_command persists its "
                               "telemetry state file (bounded)"),
        "requires_attr": None,
        "evidence": "HypothesisEngine.render_command lifecycle list",
    },
    "hypothesis show": {
        "canonical_id": "hypothesis_show", "category": "Research", "args": ["text"],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_LOW,
        "side_effect_detail": ("NiblitUnifiedRuntime.dispatch_command persists its "
                               "telemetry state file (bounded)"),
        "requires_attr": None,
        "evidence": "HypothesisEngine.render_command single-hypothesis view",
    },
    # Phase 5F knowledge commands are declared here too so the audit can map
    # their canonical identities (registered by register_knowledge_tools).
    "recall": {
        "canonical_id": "recall", "category": "Knowledge", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "db",
        "evidence": "niblit_core._cmd_recall -> db.recall(query, limit)",
    },
    "acquired data": {
        "canonical_id": "acquired_data", "category": "Knowledge", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "db",
        "evidence": "niblit_core._cmd_acquired_data -> db.get_acquired_data()",
    },
    "knowledge stats": {
        "canonical_id": "knowledge_stats", "category": "Knowledge", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "db",
        "evidence": "niblit_core._cmd_knowledge_stats -> db.get_knowledge_summary()",
    },
    "memory": {
        "canonical_id": "memory", "category": "Knowledge", "args": [],
        "risk_class": AUDIT_READ_ONLY, "side_effect_level": AUDIT_SIDE_NONE,
        "requires_attr": "db",
        "evidence": "registry lambda -> db.recent_interactions(50)",
    },
}


# Each spec carries the ORIGINAL registry name it binds to; identity recovery
# and the availability predicate both read it from here.
for _original, _spec in ORIGINAL_READONLY_PROMOTIONS.items():
    _spec.setdefault("original_name", _original)


def _original_availability(spec: Dict[str, Any]) -> Callable[[Any], bool]:
    """Availability predicate for one promoted original command.

    A promoted command is only EXECUTABLE when BOTH hold: the runtime
    dependency it reads exists AND the canonical registry the live core built
    actually holds a callable handler under the original name. Anything else is
    reported as UNAVAILABLE with a truthful reason (no silent success).
    """
    attr = spec.get("requires_attr")
    original = str(spec.get("original_name") or "")

    def available(core: Any) -> bool:
        commands = getattr(getattr(core, "command_registry", None), "commands", None)
        if not isinstance(commands, dict):
            return False
        if not callable(commands.get(original, None) and
                        getattr(commands[original], "handler", None)):
            return False
        return not attr or getattr(core, attr, None) is not None

    return available


def original_availability_reason(spec: Dict[str, Any]) -> str:
    """Truthful reason used when a promoted command's dependency is missing."""
    original = str(spec.get("original_name") or "")
    attr = spec.get("requires_attr")
    base = (f"the canonical registry has no callable handler for the original "
            f"command {original!r}")
    return (f"{base}; core.{attr} is not initialized in this runtime" if attr
            else base)


def _original_function_schema(canonical: str, description: str,
                              args: Optional[List[str]]) -> Dict[str, Any]:
    properties = {name: {"type": "string"} for name in (args or [])}
    return {
        "type": "function",
        "function": {
            "name": canonical,
            "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": [], "additionalProperties": False},
        },
    }


def original_command_capability(core_getter: Callable, original_name: str,
                                spec: Dict[str, Any]) -> Callable:
    """Bridge one promoted ORIGINAL command onto the governed capability shape.

    The bridge dispatches the SAME handler object Core's own registry holds, so
    there is no second implementation. It never turns failure into success: a
    missing handler or missing runtime dependency is reported truthfully.
    """
    canonical = str(spec.get("canonical_id"))

    def capability(**arguments: Any) -> Dict[str, Any]:
        core = core_getter() if callable(core_getter) else None
        commands = getattr(getattr(core, "command_registry", None), "commands", None)
        meta = commands.get(original_name) if isinstance(commands, dict) else None
        handler = getattr(meta, "handler", None)
        if not callable(handler):
            return {"error": "original_handler_unavailable",
                    "command": original_name, "canonical_id": canonical}
        if not _original_availability(spec)(core):
            return {"error": "dependency_unavailable", "command": original_name,
                    "detail": original_availability_reason(spec)}
        text = str(arguments.get("text") or "").strip()
        try:
            output = handler(text)
        except Exception as exc:
            return {"error": f"original_command_failed: {exc}",
                    "command": original_name, "canonical_id": canonical}
        rendered = output if isinstance(output, str) else json.dumps(output,
                                                                    default=str)
        return {
            "command": original_name,
            "canonical_id": canonical,
            "read_only": True,
            "side_effect_level": spec.get("side_effect_level", AUDIT_SIDE_NONE),
            "handler": getattr(handler, "__qualname__", None),
            "output": rendered[:MAX_ORIGINAL_OUTPUT_CHARS],
            "truncated": len(rendered) > MAX_ORIGINAL_OUTPUT_CHARS,
            "chars": len(rendered),
        }

    return capability


def register_original_readonly_tools(loop: LlmToolLoop,
                                     core_getter: Callable) -> List[str]:
    """Phase 5G-F: expose the evidence-traced ORIGINAL read-only commands.

    Commands already governed by an earlier phase (Phase 5F knowledge commands)
    are left untouched - the loop keeps ONE capability per canonical identity.
    """
    core = core_getter() if callable(core_getter) else None
    commands = getattr(getattr(core, "command_registry", None), "commands", None)
    commands = commands if isinstance(commands, dict) else {}
    existing = set(loop.allowed_tool_names())
    registered: List[str] = []
    for original, spec in ORIGINAL_READONLY_PROMOTIONS.items():
        canonical = str(spec.get("canonical_id"))
        if canonical in existing:
            continue
        description = str(getattr(commands.get(original), "description", "") or "").strip()
        if not description:
            description = (f"Original Niblit command {original!r} (the canonical "
                           "registry carries no description in this runtime)")
        loop.register_capability(
            canonical,
            original_command_capability(core_getter, original, spec),
            _original_function_schema(canonical, description, spec.get("args")),
        )
        registered.append(canonical)
    return registered


def build_governed_tool_loop(core_getter: Callable) -> LlmToolLoop:
    """Compose the governed loop: existing loop + existing capabilities."""
    from modules.niblit_tool_executor import NiblitToolExecutor

    loop = LlmToolLoop(executor=NiblitToolExecutor(core_getter=core_getter))
    register_research_tools(loop)
    register_trading(
        loop,
        lambda: getattr(
            core_getter() if callable(core_getter) else None,
            "trading_runtime_manager", None),
    )
    loop.register_capability(
        "run_research",
        lambda **arguments: run_research_capability(loop, core_getter,
                                                    arguments),
        RUN_RESEARCH_FUNCTION_SCHEMA,
    )
    # Phase 5D: governed workspace surface (list/search/read/write/edit)
    # and the bounded test runner — same file authority as the UI.
    register_workspace_tools(loop)
    # Phase 5F: restored original knowledge commands (niblit_core.py).
    register_knowledge_tools(loop, core_getter)
    # Phase 5G-F: evidence-traced ORIGINAL read-only commands. Registered on the
    # SAME loop through the SAME register_capability path - no second executor.
    register_original_readonly_tools(loop, core_getter)
    return loop


def get_governed_tool_loop(core_getter: Optional[Callable] = None) -> LlmToolLoop:
    """Process-level configured loop (Core server runtime)."""
    global _loop_singleton, _singleton_core_getter
    with _loop_lock:
        if callable(core_getter):
            _singleton_core_getter = core_getter
        if _loop_singleton is None:
            _loop_singleton = build_governed_tool_loop(_get_singleton_core)
        return _loop_singleton


def reset_governed_tool_loop() -> None:
    """Test hook: drop the process-level singleton."""
    global _loop_singleton, _singleton_core_getter
    with _loop_lock:
        _loop_singleton = None
        _singleton_core_getter = None


# ---------------------------------------------------------------------------
# Phase 5E: governed command surface (Command tab -> real capabilities).
# ---------------------------------------------------------------------------
#
# The Command tab invokes THE SAME governed capabilities the LLM uses:
#     UI -> POST /api/commands/execute
#        -> execute_governed_command (this module)
#        -> validation chain (known? schema? available? permission?)
#        -> LlmToolLoop.invoke  (identical _validate_call + _tool_map as the
#           LLM tool loop - there is NO second command executor)
#        -> registered capability / NiblitToolExecutor
#        -> real result -> EventBus -> UI
#
# Metadata reuses the field shape already established by
# trading_read_tools.TRADING_STATUS_CAPABILITY (category / risk_class /
# side_effect_level) - no duplicate metadata system is introduced.

COMMAND_PERMISSION_ACTIONS: Dict[str, str] = {
    "workspace_write": "command.workspace_write",
    "workspace_edit": "command.workspace_edit",
    "run_tests": "command.run_tests",
}

# Availability: callable(core) -> bool. A False result means a required
# runtime dependency is currently missing (state UNAVAILABLE); the command
# stays listed but is never dispatched while unavailable.
GOVERNED_COMMAND_METADATA: Dict[str, Dict[str, Any]] = {
    "runtime_status": {
        "category": "Runtime", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "web_search": {
        "category": "Research", "risk_class": "low",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "web_fetch": {
        "category": "Research", "risk_class": "low",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "run_research": {
        "category": "Research", "risk_class": "medium",
        # Persists ONLY promoted knowledge through the canonical store;
        # search/fetch budgets are hard-capped in code (UI can lower, never
        # raise them).
        "side_effect_level": "mutation", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "trading_runtime_status": {
        "category": "Trading", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: bool(
            getattr(core, "trading_runtime_manager", None)),
    },
    "workspace_list": {
        "category": "Workspace", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "workspace_search": {
        "category": "Workspace", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "workspace_read": {
        "category": "Workspace", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "workspace_read_pdf": {
        "category": "Workspace", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "workspace_inspect_python": {
        "category": "Workspace", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    },
    "workspace_write": {
        "category": "Workspace", "risk_class": "medium",
        "side_effect_level": "mutation", "requires_authorization": True,
        "availability": lambda core: True,
    },
    "workspace_edit": {
        "category": "Workspace", "risk_class": "medium",
        "side_effect_level": "mutation", "requires_authorization": True,
        "availability": lambda core: True,
    },
    "run_tests": {
        "category": "Workspace", "risk_class": "high",
        # Fixed bounded pytest command, but it does execute workspace code;
        # from the Command surface this requires an explicit operator grant.
        "side_effect_level": "execution", "requires_authorization": True,
        "availability": lambda core: True,
    },
    # ── Phase 5F: restored ORIGINAL Niblit knowledge commands ─────────────
    # Sources: niblit_core.py _cmd_recall/_cmd_acquired_data/
    # _cmd_knowledge_stats + register("memory", ...) — all read-only
    # against the real KnowledgeDB bound at core.db.
    "recall": {
        "category": "Knowledge", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: bool(getattr(core, "db", None)),
    },
    "acquired_data": {
        "category": "Knowledge", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: bool(getattr(core, "db", None)),
    },
    "knowledge_stats": {
        "category": "Knowledge", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: bool(getattr(core, "db", None)),
    },
    "memory": {
        "category": "Knowledge", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: bool(getattr(core, "db", None)),
    },
}

# ---------------------------------------------------------------------------
# Phase 5G: availability reasons (truthful UNAVAILABLE reporting, §10/§19)
# ---------------------------------------------------------------------------
# Only used to EXPLAIN an unavailable state; the availability predicate above
# still decides whether a command may dispatch at all.
AVAILABILITY_REASONS: Dict[str, str] = {
    "trading_runtime_status": "TradingRuntimeManager is not initialized in this runtime",
    "recall": "core.db (KnowledgeDB) is not initialized in this runtime",
    "acquired_data": "core.db (KnowledgeDB) is not initialized in this runtime",
    "knowledge_stats": "core.db (KnowledgeDB) is not initialized in this runtime",
    "memory": "core.db (KnowledgeDB) is not initialized in this runtime",
}

# ---------------------------------------------------------------------------
# Phase 5G: extend the governed metadata (NOT a second metadata structure).
# ---------------------------------------------------------------------------
# The promoted ORIGINAL commands get their entry derived from
# ORIGINAL_READONLY_PROMOTIONS. Existing Phase 5E/5F entries are never
# overwritten (setdefault): earlier phases stay authoritative for their own
# commands, and no part of the 244-command inventory becomes hardcoded here.
for _original, _spec in ORIGINAL_READONLY_PROMOTIONS.items():
    _canonical = str(_spec["canonical_id"])
    _risk = str(_spec["risk_class"])
    _side = str(_spec["side_effect_level"])
    _derived = {
        # 5E/5F field vocabulary (preserved for the existing UI/tests)
        "category": _spec.get("category", "Original"),
        "risk_class": "none" if _risk == AUDIT_READ_ONLY else "low",
        "side_effect_level": ("read_only" if _side == AUDIT_SIDE_NONE else "low"),
        "requires_authorization": bool(_spec.get("requires_authorization", False)),
        "availability": _original_availability(_spec),
        # Phase 5G audit metadata
        "original_source": "niblit_core.py",
        "original_name": _original,
        "source_symbol": "niblit_core.py:NiblitCore._register_commands",
        "handler_symbol": _spec.get("evidence", ""),
        "phase5g_risk_class": _risk,
        "phase5g_side_effect_level": _side,
        "llm_safe": True,
        "governed_status": "GOVERNED_EXECUTABLE",
        "unavailable_reason": original_availability_reason(_spec),
        "side_effect_detail": _spec.get("side_effect_detail", ""),
        "aliases": [_original],
    }
    # Merge, never clobber: a Phase 5E/5F entry stays authoritative for the
    # fields it already declares, while every promoted command still carries the
    # full Phase 5G governance record.
    _existing = GOVERNED_COMMAND_METADATA.setdefault(_canonical, {})
    for _key, _value in _derived.items():
        _existing.setdefault(_key, _value)

# ---------------------------------------------------------------------------
# Phase 5F: original-command identity recovery.
#
# Source-derived mapping (niblit_core.py command_registry registrations and
# the ORIGINAL SURFACE comment block) — nothing here is invented:
#   "recall"          -> recall           (niblit_core._cmd_recall)
#   "acquired data"   -> acquired_data    (niblit_core._cmd_acquired_data)
#   "knowledge stats" -> knowledge_stats  (niblit_core._cmd_knowledge_stats)
#   "memory"          -> memory           (niblit_core register("memory", ...))
# The original verbal names are preserved as aliases; the governed
# snake_case tool names stay canonical because the LLM tool loop requires
# identifier-safe tool names.
ORIGINAL_COMMAND_ALIASES: Dict[str, Dict[str, Any]] = {
    "recall": {"original_name": "recall", "aliases": []},
    "acquired_data": {"original_name": "acquired data", "aliases": ["acquired data"]},
    "knowledge_stats": {"original_name": "knowledge stats", "aliases": ["knowledge stats"]},
    "memory": {"original_name": "memory", "aliases": []},
}

# Phase 5G: every promoted ORIGINAL command also keeps its original verbal name
# as a resolvable alias (e.g. "sa-dashboard" -> "sa_dashboard",
# "runtime capabilities" -> "runtime_capabilities"). setdefault keeps the
# Phase 5F knowledge entries above authoritative for their own commands.
for _original, _spec in ORIGINAL_READONLY_PROMOTIONS.items():
    _entry = ORIGINAL_COMMAND_ALIASES.setdefault(
        str(_spec["canonical_id"]), {"original_name": _original, "aliases": []})
    _entry.setdefault("original_name", _original)
    if _original != _entry.get("original_name") and _original not in _entry["aliases"]:
        _entry["aliases"] = [*_entry.get("aliases", []), _original]

# Reverse index: original verbal name -> canonical governed tool name.
_ORIGINAL_TO_CANONICAL: Dict[str, str] = {
    alias: canonical
    for canonical, _meta in ORIGINAL_COMMAND_ALIASES.items()
    for alias in [_meta.get("original_name", canonical),
                  *_meta.get("aliases", [])]
}


def resolve_command_alias(name: str) -> str:
    """Map an original Niblit command name to its canonical governed name.

    Identity recovery only — the returned name is then dispatched through
    the normal governed validation chain (schema -> availability ->
    permission -> LlmToolLoop.invoke). Unknown names pass through unchanged
    and are rejected downstream as unknown_command, as before.
    """
    return _ORIGINAL_TO_CANONICAL.get(name, name)


def _emit_command_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Publish one command.* event; event failures never abort execution."""
    from modules.event_bus import NiblitEvent

    try:
        get_event_bus().publish(NiblitEvent(
            type=event_type, source="core_tool_runtime", payload=payload))
    except Exception as exc:  # pragma: no cover - observability only
        log.warning("[CoreToolRuntime] command event failed (%s): %s",
                    event_type, exc)


def _permission_manager():
    """Existing PermissionManager authority (file-backed check/ask store)."""
    from modules.permission_manager import PermissionManager

    return PermissionManager()


def _command_state(name: str, meta: Dict[str, Any], core: Any) -> str:
    """Truthful runtime state: EXECUTABLE | REQUIRES_AUTHORIZATION |
    UNAVAILABLE. Everything listed here is REGISTERED by construction (the
    registry is derived from the governed loop's own schema registry)."""
    try:
        if not meta["availability"](core):
            return "UNAVAILABLE"
    except Exception:
        return "UNAVAILABLE"
    if meta["requires_authorization"]:
        action = COMMAND_PERMISSION_ACTIONS.get(name, f"command.{name}")
        try:
            granted = bool(_permission_manager().check(action))
        except Exception:
            granted = False
        if not granted:
            return "REQUIRES_AUTHORIZATION"
    return "EXECUTABLE"


def list_governed_commands(core_getter: Optional[Callable] = None) -> Dict[str, Any]:
    """Registry for the Command tab, derived from the governed loop itself.

    A command is never labelled EXECUTABLE merely because a schema exists:
    availability (runtime dependency) and permission (authorization store)
    are evaluated per call against the live core.
    """
    core = core_getter() if callable(core_getter) else None
    loop = get_governed_tool_loop(core_getter or (lambda: None))
    commands = []
    for name in loop.allowed_tool_names():
        schema = loop._schemas.get(name)
        if schema is None and name == "runtime_status":
            from modules.llm_tool_loop import make_runtime_status_tool
            schema = make_runtime_status_tool()
        function = (schema or {}).get("function", {})
        meta = GOVERNED_COMMAND_METADATA.get(name, {
            "category": "Uncategorized", "risk_class": "unknown",
            "side_effect_level": "unknown", "requires_authorization": False,
            "availability": lambda _core: False,
        })
        state = _command_state(name, meta, core)
        identity = ORIGINAL_COMMAND_ALIASES.get(name, {})
        commands.append({
            "name": name,
            "original_name": identity.get("original_name", name),
            "aliases": identity.get("aliases", []),
            "description": function.get("description", ""),
            "category": meta["category"],
            "input_schema": function.get("parameters", {}),
            "state": state,
            "risk_class": meta["risk_class"],
            "side_effect_level": meta["side_effect_level"],
            "requires_authorization": bool(meta["requires_authorization"]),
            "authorization_action": COMMAND_PERMISSION_ACTIONS.get(name),
            # execution_enabled is true ONLY for commands that will actually
            # dispatch right now (the §17 critical success condition).
            "execution_enabled": state == "EXECUTABLE",
            # ── Phase 5G governance detail (additive; §4 says the existing
            # fields and their meanings stay exactly as they were) ──────────
            "governed_status": meta.get("governed_status", "GOVERNED_EXECUTABLE"),
            "audit_risk_class": meta.get("phase5g_risk_class", ""),
            "audit_side_effect_level": meta.get("phase5g_side_effect_level", ""),
            "side_effect_detail": meta.get("side_effect_detail", ""),
            "original_source": meta.get("original_source", ""),
            "source_symbol": meta.get("source_symbol", ""),
            "evidence": meta.get("handler_symbol", ""),
            "unavailable_reason": (
                meta.get("unavailable_reason", "")
                or AVAILABILITY_REASONS.get(name, "")
            ) if state == "UNAVAILABLE" else "",
        })
    return {
        "source": "core_tool_runtime.governed_registry",
        "capability_path": ("UI -> /api/commands/execute -> "
                            "core_tool_runtime -> LlmToolLoop.invoke -> "
                            "registered capability / NiblitToolExecutor"),
        "original_command_count": len(ORIGINAL_READONLY_PROMOTIONS),
        "research_budgets": {
            "max_searches": HARD_CAP_SEARCHES,
            "max_fetches": HARD_CAP_FETCHES,
            "max_rounds": HARD_CAP_ROUNDS,
            "ui_can_raise": False,
        },
        "commands": commands,
        "count": len(commands),
    }


# ---------------------------------------------------------------------------
# Phase 5G: original-surface reconciliation (read-only audit, live inputs).
# ---------------------------------------------------------------------------
def promoted_audit_map() -> Dict[str, Dict[str, Any]]:
    """The Phase 5G promotion table in the shape the audit layer consumes.

    The audit NEVER decides promotion and this module NEVER classifies: the
    table is the single promotion authority and the audit reads it.
    """
    return {
        original: {
            "canonical_id": spec["canonical_id"],
            "risk_class": spec["risk_class"],
            "side_effect_level": spec["side_effect_level"],
            "requires_authorization": bool(spec.get("requires_authorization", False)),
            "evidence": spec.get("evidence", ""),
            "side_effect_detail": spec.get("side_effect_detail", ""),
            "schema": _original_function_schema(
                spec["canonical_id"], "", spec.get("args")),
        }
        for original, spec in ORIGINAL_READONLY_PROMOTIONS.items()
    }


def list_original_command_surface(core_getter: Optional[Callable] = None,
                                  project_root: Optional[str] = None) -> Dict[str, Any]:
    """Reconcile the ORIGINAL command surface with the governed one.

    Composes the read-only audit layer (modules/command_surface_audit.py) with
    the LIVE governed registry. Nothing is registered, dispatched or cached
    here: the audit reads the core registry the core already built, and this
    function only supplies the promotion table and the current governed states.
    """
    core = core_getter() if callable(core_getter) else None
    registry = list_governed_commands(core_getter or (lambda: None))
    states = {c["name"]: c["state"] for c in registry["commands"]}
    reasons = {c["name"]: c.get("unavailable_reason", "")
               for c in registry["commands"] if c.get("unavailable_reason")}
    alias_map: Dict[str, str] = {}
    for canonical, identity in ORIGINAL_COMMAND_ALIASES.items():
        for alias in (identity.get("original_name", canonical),
                      *identity.get("aliases", [])):
            alias_map[alias] = canonical
    # verified spelling variants: the audit keeps ONE canonical identity
    for variant, canonical_name in VARIANT_SPELLINGS.items():
        alias_map.setdefault(
            variant,
            alias_map.get(canonical_name, audit_canonical_id(canonical_name)),
        )
    return build_original_surface_audit(
        core,
        promoted=promoted_audit_map(),
        governed_states=states,
        governed_unavailable_reasons=reasons,
        governed_commands=registry["commands"],
        alias_map=alias_map,
        project_root=project_root,
    )


def execute_governed_command(core_getter: Optional[Callable] = None,
                             name: str = "",
                             arguments: Optional[Dict[str, Any]] = None,
                             request_id: str = "") -> Dict[str, Any]:
    """Validation chain -> governed dispatch -> real result -> EventBus.

    Never turns failure into success and never silently substitutes another
    command: unknown / malformed / unauthorized / unavailable are all
    returned as distinct truthful statuses.
    """
    core = core_getter() if callable(core_getter) else None
    loop = get_governed_tool_loop(core_getter or (lambda: None))
    requested_name = str(name or "").strip()
    # Phase 5F: original Niblit command names are accepted as aliases and
    # dispatched to the canonical governed capability. The result reports
    # the requested name truthfully (with alias_of) — execution itself is
    # unchanged: same validation chain, same LlmToolLoop.invoke.
    command_name = resolve_command_alias(requested_name)
    base = {"command": requested_name, "request_id": request_id or ""}
    if command_name != requested_name:
        base["alias_of"] = command_name

    # 1) known command?
    if command_name not in loop.allowed_tool_names():
        _emit_command_event("command.execution.rejected", {
            **base, "reason": "unknown_command",
            "registered": loop.allowed_tool_names(),
        })
        return {**base, "status": "rejected", "result": None,
                "error": f"unknown_command: {command_name!r}"}

    # 2) schema + argument validation (§6 order: schema BEFORE permission)
    pre_error = loop.prevalidate(command_name, arguments or {})
    if pre_error is not None:
        _emit_command_event("command.execution.rejected", {
            **base, "reason": "schema_validation", "error": pre_error,
        })
        return {**base, "status": "rejected", "result": None,
                "error": pre_error}

    meta = GOVERNED_COMMAND_METADATA.get(command_name, {})
    # 3) runtime dependency available?
    try:
        available = bool(meta.get("availability", lambda _c: False)(core))
    except Exception:
        available = False
    if not available:
        _emit_command_event("command.execution.rejected", {
            **base, "reason": "unavailable",
            "detail": "required runtime dependency is not available",
        })
        return {**base, "status": "unavailable", "result": None,
                "error": "capability dependency not available"}

    # 4) permission / authorization?
    action = COMMAND_PERMISSION_ACTIONS.get(command_name)
    if meta.get("requires_authorization"):
        try:
            granted = bool(_permission_manager().check(action))
        except Exception:
            granted = False
        if not granted:
            _emit_command_event("command.authorization.requested", {
                **base, "action": action,
                "reason": "mutation capability requires explicit grant",
            })
            return {**base, "status": "authorization_required",
                    "result": None,
                    "error": (f"authorization required for {action!r}; "
                              "grant it in the operator permission store"),
                    "authorization_action": action}

    # 4) governed dispatch (same path as the LLM: schema validation +
    #    _tool_map dispatch inside LlmToolLoop.invoke).
    _emit_command_event("command.execution.started", {**base})
    outcome = loop.invoke(command_name, arguments or {})
    status = outcome.get("status", "error")
    _emit_command_event("command.execution.completed", {
        **base, "status": status,
        "duration_ms": outcome.get("duration_ms"),
        **({"error": outcome.get("error")} if outcome.get("error") else {}),
    })
    if status == "rejected":
        _emit_command_event("command.execution.rejected", {
            **base, "reason": "schema_validation",
            "error": outcome.get("error"),
        })
    # JSON-safe result: capability results may embed live objects (e.g. a
    # market-data provider). The LLM loop already tolerates these via
    # json.dumps(default=str); the command boundary must too, so the endpoint
    # never 500s on serialization.
    result = outcome.get("result")
    if result is not None:
        try:
            json.dumps(result)
        except TypeError:
            result = json.loads(json.dumps(result, default=str))
    return {
        **base,
        "status": status,
        "result": result,
        "error": outcome.get("error"),
        "duration_ms": outcome.get("duration_ms"),
        "governance": {
            "schema_validated": True,
            "permission_action": action,
            "executor": "core_tool_runtime.LlmToolLoop.invoke",
            "dispatch_path": "identical to the LLM tool loop",
        },
    }
