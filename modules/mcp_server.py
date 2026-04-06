#!/usr/bin/env python3
"""
modules/mcp_server.py — Model Context Protocol (MCP) server for Niblit.

Implements the MCP specification (https://modelcontextprotocol.io) so that
any MCP-compatible client (Claude Desktop, VS Code Copilot, Cursor, etc.)
can connect to Niblit and use its capabilities as tools, resources, and
prompts.

Transports supported
--------------------
* **HTTP + SSE** — POST ``/mcp`` for JSON-RPC requests; GET ``/mcp/sse`` for
  the Server-Sent Events notification stream.  Used when Niblit is deployed
  as a web service (Vercel, Render, etc.).
* **stdio** — Run ``python -m modules.mcp_server`` for a subprocess-style
  MCP server that Claude Desktop and similar clients can spawn directly.

Tools exposed
-------------
* ``niblit_chat``          — Send a message to Niblit and receive a reply.
* ``niblit_search``        — Search Niblit's knowledge base / the web.
* ``niblit_status``        — Retrieve Niblit's system status.
* ``niblit_learn``         — Trigger an autonomous learning cycle.
* ``niblit_remember``      — Store a fact in Niblit's knowledge base.
* ``niblit_recall``        — Recall facts from the knowledge base.
* ``niblit_generate_code`` — Generate code using Niblit's code generator.
* ``niblit_serpex_search`` — Perform a Serpex-backed web search.

Resources exposed
-----------------
* ``niblit://status``        — Live system-status JSON.
* ``niblit://knowledge``     — Recent knowledge base entries.

Prompts exposed
---------------
* ``niblit_assistant``       — Prime the AI assistant with Niblit context.

Configuration (env vars)
------------------------
``MCP_SECRET``    — Bearer token required for HTTP transport (leave blank = no auth).
``MCP_HOST``      — Bind host for standalone HTTP mode (default: ``0.0.0.0``).
``MCP_PORT``      — Bind port for standalone HTTP mode (default: ``8765``).
``MCP_ENABLED``   — Set to ``false`` to disable MCP even when imported (default: ``true``).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from queue import Queue, Empty
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("NiblitMCP")

# ─── optional flask import ─────────────────────────────────────────────────
try:
    from flask import Flask as _Flask, request as _request, Response as _Response, jsonify as _jsonify  # noqa: F401
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False

# ─── MCP SDK (optional — falls back to built-in JSON-RPC handler) ──────────
try:
    import mcp  # type: ignore[import]  # noqa: F401
    _MCP_SDK_AVAILABLE = True
except ImportError:
    _MCP_SDK_AVAILABLE = False

# ─── config ────────────────────────────────────────────────────────────────
MCP_SECRET: str = os.getenv("MCP_SECRET", "")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8765"))
MCP_ENABLED: bool = os.getenv("MCP_ENABLED", "true").lower() in ("1", "true", "yes")

# Protocol version this implementation targets
_MCP_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "niblit"
_SERVER_VERSION = "1.0.0"

# ───────────────────────────────────────────────────────────────────────────
# Tool / Resource / Prompt definitions
# ───────────────────────────────────────────────────────────────────────────

_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "niblit_chat",
        "description": "Send a message to Niblit and receive an AI-generated reply. "
                       "Niblit can answer questions, execute commands, and reason about topics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message or command to send to Niblit.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "niblit_search",
        "description": "Search Niblit's knowledge base and/or the internet for information.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "niblit_status",
        "description": "Retrieve Niblit's current system status including module health, "
                       "autonomous learning statistics, and uptime.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "niblit_learn",
        "description": "Trigger one autonomous learning cycle immediately. "
                       "Niblit will research topics, generate code, and improve itself.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Optional topic to seed into the research queue.",
                }
            },
        },
    },
    {
        "name": "niblit_remember",
        "description": "Store a fact or piece of information in Niblit's knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Unique key for the fact."},
                "value": {"type": "string", "description": "The fact or information to store."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization.",
                },
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "niblit_recall",
        "description": "Recall facts from Niblit's knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for knowledge recall.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum facts to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "niblit_generate_code",
        "description": "Generate functional code using Niblit's code generator.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Programming language (e.g. python, javascript, bash).",
                },
                "purpose": {
                    "type": "string",
                    "description": "Description of what the code should do.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context for code generation.",
                },
            },
            "required": ["language", "purpose"],
        },
    },
    {
        "name": "niblit_serpex_search",
        "description": "Perform a Serpex-backed web search with relevance filtering. "
                       "Returns validated, semantically relevant web snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Web search query."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "niblit_searchcode",
        "description": "Search open-source code on searchcode.com. "
                       "Covers GitHub, Bitbucket, GitLab, Google Code and more. "
                       "Uses the searchcode MCP endpoint (https://api.searchcode.com/v1/mcp) "
                       "when reachable, otherwise the public REST API. "
                       "Returns real code snippets for a given query and optional language filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Code search query (e.g. 'async context manager python').",
                },
                "language": {
                    "type": "string",
                    "description": "Optional language filter (e.g. 'python', 'javascript', 'go').",
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of code snippets to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
]

_RESOURCE_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "uri": "niblit://status",
        "name": "Niblit System Status",
        "description": "Live JSON snapshot of Niblit's module health and learning statistics.",
        "mimeType": "application/json",
    },
    {
        "uri": "niblit://knowledge",
        "name": "Niblit Knowledge Base",
        "description": "Recent entries from Niblit's persistent knowledge base.",
        "mimeType": "application/json",
    },
]

_PROMPT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "niblit_assistant",
        "description": "Prime the AI assistant with Niblit context and capabilities.",
        "arguments": [
            {
                "name": "task",
                "description": "The specific task you want Niblit to help with.",
                "required": False,
            }
        ],
    },
]


# ───────────────────────────────────────────────────────────────────────────
# Core handler
# ───────────────────────────────────────────────────────────────────────────

class NiblitMCPHandler:
    """
    Handles MCP JSON-RPC messages (transport-agnostic).

    Wire a :class:`~niblit_core.NiblitCore` instance via :meth:`set_core`
    after construction.
    """

    def __init__(self) -> None:
        self._core: Optional[Any] = None
        # SSE subscriber queues: session_id → Queue
        self._sse_queues: Dict[str, Queue] = {}
        self._lock = threading.Lock()

    def set_core(self, core: Any) -> None:
        """Attach a live NiblitCore instance."""
        self._core = core
        log.info("[MCP] NiblitCore attached to MCP handler")

    # ── auth helper ──────────────────────────────────────────────────────────

    def _check_auth(self, meta: Optional[Dict[str, Any]]) -> bool:
        """Return True if auth passes or no secret is configured."""
        if not MCP_SECRET:
            return True
        bearer = (meta or {}).get("authorization", "")
        if bearer.startswith("Bearer "):
            bearer = bearer[7:]
        return bearer == MCP_SECRET

    # ── MCP method dispatcher ────────────────────────────────────────────────

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process one MCP JSON-RPC message.

        Returns a response dict or ``None`` for notifications (no id).
        """
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        # Notifications (no id) — fire and forget
        if msg_id is None and method != "initialize":
            self._dispatch_notification(method, params)
            return None

        try:
            result = self._dispatch(method, params)
            return self._ok(msg_id, result)
        except _MCPError as exc:
            return self._err(msg_id, exc.code, exc.message)
        except Exception as exc:
            log.error("[MCP] unhandled error in %s: %s", method, exc)
            return self._err(msg_id, -32603, "Internal error")

    def _dispatch(self, method: str, params: Dict[str, Any]) -> Any:
        handlers: Dict[str, Callable] = {
            "initialize":         self._handle_initialize,
            "ping":               self._handle_ping,
            "tools/list":         self._handle_tools_list,
            "tools/call":         self._handle_tools_call,
            "resources/list":     self._handle_resources_list,
            "resources/read":     self._handle_resources_read,
            "prompts/list":       self._handle_prompts_list,
            "prompts/get":        self._handle_prompts_get,
            "completion/complete": self._handle_completion,
        }
        handler = handlers.get(method)
        if handler is None:
            raise _MCPError(-32601, f"Method not found: {method}")
        return handler(params)

    def _dispatch_notification(self, method: str, params: Dict[str, Any]) -> None:
        if method == "notifications/initialized":
            log.info("[MCP] Client initialized")
        elif method == "notifications/cancelled":
            log.debug("[MCP] Request cancelled: %s", params.get("requestId"))

    # ── MCP method handlers ──────────────────────────────────────────────────

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "protocolVersion": _MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
        }

    def _handle_ping(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def _handle_tools_list(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"tools": _TOOL_DEFINITIONS}

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        dispatchers: Dict[str, Callable] = {
            "niblit_chat":          self._tool_chat,
            "niblit_search":        self._tool_search,
            "niblit_status":        self._tool_status,
            "niblit_learn":         self._tool_learn,
            "niblit_remember":      self._tool_remember,
            "niblit_recall":        self._tool_recall,
            "niblit_generate_code": self._tool_generate_code,
            "niblit_serpex_search": self._tool_serpex_search,
            "niblit_searchcode":     self._tool_searchcode,
        }
        fn = dispatchers.get(name)
        if fn is None:
            raise _MCPError(-32602, f"Unknown tool: {name}")
        text = fn(args)
        return {"content": [{"type": "text", "text": str(text)}]}

    def _handle_resources_list(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"resources": _RESOURCE_DEFINITIONS}

    def _handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        uri = params.get("uri", "")
        if uri == "niblit://status":
            content = self._resource_status()
        elif uri == "niblit://knowledge":
            content = self._resource_knowledge()
        else:
            raise _MCPError(-32602, f"Unknown resource URI: {uri}")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(content, default=str),
                }
            ]
        }

    def _handle_prompts_list(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"prompts": _PROMPT_DEFINITIONS}

    def _handle_prompts_get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        if name == "niblit_assistant":
            task = args.get("task", "general assistance")
            system_text = (
                "You are connected to Niblit, an autonomous self-improving AI system. "
                "Niblit can search the web, generate code, learn autonomously, "
                "and maintain a persistent knowledge base. "
                f"The user needs help with: {task}. "
                "Use the available Niblit tools to fulfill the request."
            )
            return {
                "description": "Niblit assistant system prompt",
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": system_text}}
                ],
            }
        raise _MCPError(-32602, f"Unknown prompt: {name}")

    def _handle_completion(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"completion": {"values": [], "total": 0, "hasMore": False}}

    # ── tool implementations ─────────────────────────────────────────────────

    def _tool_chat(self, args: Dict[str, Any]) -> str:
        message = args.get("message", "")
        if not message:
            return "[Error: empty message]"
        if self._core is None:
            return "[Niblit core not available — start Niblit first]"
        try:
            if hasattr(self._core, "handle"):
                return str(self._core.handle(message))
            if hasattr(self._core, "process"):
                return str(self._core.process(message))
            if hasattr(self._core, "respond"):
                return str(self._core.respond(message))
            return "[Niblit: no response handler found]"
        except Exception as exc:
            return f"[Niblit chat error: {exc}]"

    def _tool_search(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "")
        max_results = int(args.get("max_results", 5))
        if not query:
            return "[Error: empty query]"
        # Try internet search first, then KB recall
        if self._core:
            internet = getattr(self._core, "internet", None)
            if internet:
                try:
                    results = internet.search(query, max_results=max_results)
                    snippets = []
                    for r in (results or []):
                        text = r.get("text", str(r)) if isinstance(r, dict) else str(r)
                        if text:
                            snippets.append(text[:300])
                    if snippets:
                        return "\n\n".join(snippets[:max_results])
                except Exception as exc:
                    log.debug("[MCP] internet search failed: %s", exc)
            # Fallback to KB recall
            db = getattr(self._core, "db", None)
            if db and hasattr(db, "recall"):
                try:
                    results = db.recall(query, limit=max_results)
                    if results:
                        return "\n\n".join(str(r)[:300] for r in results[:max_results])
                except Exception as exc:
                    log.debug("[MCP] KB recall failed: %s", exc)
        return "[No search results found]"

    def _tool_status(self, _args: Dict[str, Any]) -> str:
        if self._core is None:
            return json.dumps({"status": "offline", "message": "Niblit core not available"})
        try:
            if hasattr(self._core, "get_status"):
                return json.dumps(self._core.get_status(), default=str)
            # Build a basic status from known attributes
            status: Dict[str, Any] = {
                "status": "online",
                "modules": {},
                "autonomous_learning": {},
            }
            for mod in ("internet", "llm", "brain", "researcher", "code_generator",
                        "code_compiler", "evolve_engine", "autonomous_engine"):
                status["modules"][mod] = bool(getattr(self._core, mod, None))
            ae = getattr(self._core, "autonomous_engine", None)
            if ae and hasattr(ae, "get_learning_stats"):
                stats = ae.get_learning_stats()
                status["autonomous_learning"] = {
                    "running": stats.get("running", False),
                    "cycle_count": stats.get("cycle_count", 0),
                    "uptime_seconds": stats.get("uptime_seconds", 0),
                }
            return json.dumps(status, default=str)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    def _tool_learn(self, args: Dict[str, Any]) -> str:
        topic = args.get("topic", "")
        if self._core is None:
            return "[Niblit core not available]"
        ae = getattr(self._core, "autonomous_engine", None)
        if not ae:
            return "[Autonomous learning engine not available]"
        if topic and hasattr(ae, "add_research_topic"):
            ae.add_research_topic(topic)
        try:
            if hasattr(ae, "_autonomous_research"):
                result = ae._autonomous_research()
                return f"Learning cycle completed: {result}"
            return "[Learning triggered but no method found]"
        except Exception as exc:
            return f"[Learning error: {exc}]"

    def _tool_remember(self, args: Dict[str, Any]) -> str:
        key = args.get("key", "")
        value = args.get("value", "")
        tags = args.get("tags", [])
        if not key or not value:
            return "[Error: key and value are required]"
        db = getattr(self._core, "db", None) if self._core else None
        if db is None:
            return "[Knowledge base not available]"
        try:
            if hasattr(db, "add_fact"):
                db.add_fact(f"mcp:{key}", value, tags=["mcp"] + (tags or []))
            elif hasattr(db, "store_learning"):
                db.store_learning({"key": key, "value": value})
            return f"✅ Stored: {key}"
        except Exception as exc:
            return f"[Remember error: {exc}]"

    def _tool_recall(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "")
        limit = int(args.get("limit", 10))
        if not query:
            return "[Error: query is required]"
        db = getattr(self._core, "db", None) if self._core else None
        if db is None:
            return "[Knowledge base not available]"
        try:
            if hasattr(db, "recall"):
                results = db.recall(query, limit=limit)
            elif hasattr(db, "search_facts"):
                results = db.search_facts(query, limit=limit)
            else:
                return "[Recall method not available]"
            if not results:
                return "[No matching facts found]"
            lines = []
            for r in results[:limit]:
                if isinstance(r, dict):
                    lines.append(f"{r.get('key', '')}: {str(r.get('value', r))[:200]}")
                else:
                    lines.append(str(r)[:200])
            return "\n".join(lines)
        except Exception as exc:
            return f"[Recall error: {exc}]"

    def _tool_generate_code(self, args: Dict[str, Any]) -> str:
        language = args.get("language", "python")
        purpose = args.get("purpose", "")
        context = args.get("context", "")
        if not purpose:
            return "[Error: purpose is required]"
        # Try LLM-based generation first
        llm = getattr(self._core, "llm", None) if self._core else None
        if llm and hasattr(llm, "generate_code"):
            try:
                code = llm.generate_code(language, purpose, context)
                if code and len(code) > 20:
                    return f"```{language}\n{code}\n```"
            except Exception as exc:
                log.debug("[MCP] LLM code gen failed: %s", exc)
        # Fallback to CodeGenerator
        cg = getattr(self._core, "code_generator", None) if self._core else None
        if cg and hasattr(cg, "generate"):
            try:
                result = cg.generate(language, "module", name=purpose[:40])
                if isinstance(result, dict) and result.get("code"):
                    return f"```{language}\n{result['code']}\n```"
            except Exception as exc:
                log.debug("[MCP] CodeGenerator failed: %s", exc)
        return f"[Code generation unavailable for {language}]"

    def _tool_serpex_search(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "")
        if not query:
            return "[Error: query is required]"
        agent = getattr(self._core, "serpex_research_agent", None) if self._core else None
        if not agent:
            # Try lazy construction
            try:
                from niblit_agents.research_agent import ResearchAgent
                agent = ResearchAgent()
            except Exception:
                return "[Serpex search unavailable — set SERPEX_API_KEY]"
        try:
            results = agent.search_web(query)
            valid = [r for r in (results or []) if isinstance(r, dict) and "error" not in r]
            if not valid:
                return f"[No relevant Serpex results for: {query}]"
            lines = [
                f"[{i+1}] {r.get('title', '')} — {r.get('snippet', '')[:200]}"
                for i, r in enumerate(valid[:5])
            ]
            return "\n".join(lines)
        except Exception as exc:
            return f"[Serpex search error: {exc}]"

    def _tool_searchcode(self, args: Dict[str, Any]) -> str:
        """Search open-source code via searchcode.com (MCP → REST fallback)."""
        query = args.get("query", "")
        language = args.get("language", "")
        max_results = int(args.get("max_results", 5))
        if not query:
            return "[Error: query is required]"

        # Try to get SearchcodeSearch from core first
        sc = getattr(self._core, "searchcode_search", None) if self._core else None
        if sc is None:
            try:
                from modules.searchcode_search import SearchcodeSearch
                sc = SearchcodeSearch()
            except Exception as exc:
                return f"[Searchcode unavailable: {exc}]"

        try:
            results = sc.search_code(query, language=language, max_results=max_results)
            if not results:
                return f"[No searchcode results for: {query}]"
            lines = []
            for i, r in enumerate(results[:max_results]):
                filename = r.get("filename", "")
                lang = r.get("language", language)
                text = r.get("text", "")[:200]
                url = r.get("url", "")
                header = f"[{i+1}] {filename}" + (f" ({lang})" if lang else "")
                if url:
                    header += f" — {url}"
                lines.append(header)
                if text:
                    lines.append(f"  {text}")
            return "\n".join(lines)
        except Exception as exc:
            return f"[Searchcode error: {exc}]"

    # ── resource implementations ─────────────────────────────────────────────

    def _resource_status(self) -> Dict[str, Any]:
        status = json.loads(self._tool_status({}))
        status["timestamp"] = time.time()
        return status

    def _resource_knowledge(self) -> Dict[str, Any]:
        db = getattr(self._core, "db", None) if self._core else None
        if db is None:
            return {"error": "Knowledge base not available", "entries": []}
        try:
            if hasattr(db, "get_recent_facts"):
                facts = db.get_recent_facts(limit=20)
            elif hasattr(db, "recall"):
                facts = db.recall("", limit=20)
            else:
                facts = []
            return {"entries": [str(f)[:300] for f in (facts or [])[:20]]}
        except Exception as exc:
            return {"error": str(exc), "entries": []}

    # ── SSE notification broadcast ───────────────────────────────────────────

    def subscribe_sse(self, session_id: str) -> Queue:
        """Register an SSE subscriber and return its queue."""
        q: Queue = Queue(maxsize=100)
        with self._lock:
            self._sse_queues[session_id] = q
        return q

    def unsubscribe_sse(self, session_id: str) -> None:
        with self._lock:
            self._sse_queues.pop(session_id, None)

    def broadcast(self, event: Dict[str, Any]) -> None:
        """Broadcast a notification to all SSE subscribers."""
        data = json.dumps(event)
        with self._lock:
            queues = list(self._sse_queues.values())
        for q in queues:
            try:
                q.put_nowait(data)
            except Exception:
                pass

    # ── JSON-RPC helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _ok(msg_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _err(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }


class _MCPError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ───────────────────────────────────────────────────────────────────────────
# Singleton handler (shared across Flask routes and stdio)
# ───────────────────────────────────────────────────────────────────────────

_handler: Optional[NiblitMCPHandler] = None


def get_handler() -> NiblitMCPHandler:
    """Return the singleton MCP handler, creating it if necessary."""
    global _handler  # pylint: disable=global-statement
    if _handler is None:
        _handler = NiblitMCPHandler()
    return _handler


def attach_core(core: Any) -> None:
    """Attach a NiblitCore instance to the global MCP handler."""
    get_handler().set_core(core)


# ───────────────────────────────────────────────────────────────────────────
# Flask route registrar (called from app.py / server.py)
# ───────────────────────────────────────────────────────────────────────────

def register_flask_routes(app: Any) -> None:
    """
    Register ``/mcp`` (JSON-RPC POST) and ``/mcp/sse`` (SSE GET) routes on a
    Flask *app* object.

    Call this from your Flask application factory after creating the app::

        from modules.mcp_server import register_flask_routes
        register_flask_routes(app)
    """
    if not _FLASK_AVAILABLE:
        log.warning("[MCP] Flask not available — HTTP routes not registered")
        return
    if not MCP_ENABLED:
        log.info("[MCP] MCP_ENABLED=false — HTTP routes skipped")
        return

    handler = get_handler()

    @app.route("/mcp", methods=["POST", "OPTIONS"])
    def mcp_endpoint():
        """MCP JSON-RPC endpoint (HTTP transport)."""
        # CORS pre-flight
        if _request.method == "OPTIONS":
            resp = _Response("", 204)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return resp

        # Bearer-token auth
        if MCP_SECRET:
            auth = _request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else auth
            if token != MCP_SECRET:
                return _jsonify({"error": "Unauthorized"}), 401

        try:
            body = _request.get_json(force=True, silent=True) or {}
        except Exception:
            body = {}

        if not body:
            return _jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), 400

        response = handler.handle(body)
        if response is None:
            # Notification — no body, 204
            return _Response("", 204)
        return _jsonify(response)

    @app.route("/mcp/sse", methods=["GET"])
    def mcp_sse():
        """MCP Server-Sent Events endpoint for push notifications."""
        if MCP_SECRET:
            auth = _request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else auth
            if token != MCP_SECRET:
                return _jsonify({"error": "Unauthorized"}), 401

        session_id = str(uuid.uuid4())
        q = handler.subscribe_sse(session_id)

        def generate():
            # Send initial endpoint event (MCP HTTP+SSE spec)
            yield f"event: endpoint\ndata: /mcp\n\n"
            try:
                while True:
                    try:
                        data = q.get(timeout=30)
                        yield f"data: {data}\n\n"
                    except Empty:
                        # Heartbeat keep-alive
                        yield ": heartbeat\n\n"
            finally:
                handler.unsubscribe_sse(session_id)

        return _Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    log.info("[MCP] Flask routes registered: POST /mcp  GET /mcp/sse")


# ───────────────────────────────────────────────────────────────────────────
# FastAPI route registrar (called from app.py)
# ───────────────────────────────────────────────────────────────────────────

def register_fastapi_routes(app: Any) -> None:
    """
    Register ``/mcp`` (JSON-RPC POST) and ``/mcp/sse`` (SSE GET) routes on a
    FastAPI *app* object.

    Call this from your FastAPI application factory after creating the app::

        from modules.mcp_server import register_fastapi_routes
        register_fastapi_routes(app)
    """
    if not MCP_ENABLED:
        log.info("[MCP] MCP_ENABLED=false — HTTP routes skipped")
        return

    try:
        from fastapi import Request as _FARequest
        from fastapi.responses import (
            Response as _FAResponse,
            JSONResponse as _FAJsonResponse,
            StreamingResponse as _FAStreamingResponse,
        )
    except ImportError:
        log.warning("[MCP] FastAPI not available — HTTP routes not registered")
        return

    handler = get_handler()

    @app.post("/mcp")
    async def mcp_endpoint(request: _FARequest):
        """MCP JSON-RPC endpoint (HTTP transport)."""
        if MCP_SECRET:
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else auth
            if token != MCP_SECRET:
                return _FAJsonResponse({"error": "Unauthorized"}, status_code=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        if not body:
            return _FAJsonResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )

        response = handler.handle(body)
        if response is None:
            return _FAResponse(status_code=204)
        return _FAJsonResponse(response)

    @app.get("/mcp/sse")
    async def mcp_sse(request: _FARequest):
        """MCP Server-Sent Events endpoint for push notifications."""
        if MCP_SECRET:
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else auth
            if token != MCP_SECRET:
                return _FAJsonResponse({"error": "Unauthorized"}, status_code=401)

        session_id = str(uuid.uuid4())
        q = handler.subscribe_sse(session_id)

        async def generate():
            yield "event: endpoint\ndata: /mcp\n\n"
            try:
                while True:
                    try:
                        data = q.get(timeout=30)
                        yield f"data: {data}\n\n"
                    except Empty:
                        yield ": heartbeat\n\n"
            finally:
                handler.unsubscribe_sse(session_id)

        return _FAStreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    log.info("[MCP] FastAPI routes registered: POST /mcp  GET /mcp/sse")


# ───────────────────────────────────────────────────────────────────────────
# Stdio transport (subprocess mode — for Claude Desktop, etc.)
# ───────────────────────────────────────────────────────────────────────────

def run_stdio() -> None:
    """
    Run Niblit as a stdio MCP server.

    Reads line-delimited JSON from stdin and writes JSON-RPC responses to
    stdout.  This is the transport used by Claude Desktop when configured
    with a ``command`` entry in ``claude_desktop_config.json``::

        {
          "mcpServers": {
            "niblit": {
              "command": "python",
              "args": ["-m", "modules.mcp_server"],
              "env": {"HF_TOKEN": "...", "SERPEX_API_KEY": "..."}
            }
          }
        }
    """
    handler = get_handler()

    # Lazily import and attach NiblitCore
    try:
        from niblit_core import NiblitCore  # type: ignore[import]
        core = NiblitCore()
        handler.set_core(core)
        log.info("[MCP/stdio] NiblitCore started")
    except Exception as exc:
        log.warning("[MCP/stdio] NiblitCore unavailable: %s", exc)

    log.info("[MCP/stdio] Ready — reading from stdin")
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = handler.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


# ───────────────────────────────────────────────────────────────────────────
# Standalone HTTP server (optional, for non-Flask deployments)
# ───────────────────────────────────────────────────────────────────────────

def run_http_server(host: str = MCP_HOST, port: int = MCP_PORT) -> None:
    """
    Run Niblit as a standalone HTTP MCP server using FastAPI + uvicorn.

    Prefer this only for development; use Gunicorn with uvicorn workers in production.
    """
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        import uvicorn
    except ImportError:
        log.error("[MCP] FastAPI and uvicorn are required for HTTP server mode")
        return

    standalone_app = FastAPI(title="niblit_mcp_standalone", docs_url=None, redoc_url=None)
    standalone_app.add_middleware(CORSMiddleware, allow_origins=["*"],
                                  allow_methods=["*"], allow_headers=["*"])
    register_fastapi_routes(standalone_app)

    handler = get_handler()
    try:
        from niblit_core import NiblitCore  # type: ignore[import]
        core = NiblitCore()
        handler.set_core(core)
    except Exception as exc:
        log.warning("[MCP/http] NiblitCore unavailable: %s", exc)

    log.info("[MCP] Starting HTTP server on %s:%d", host, port)
    uvicorn.run(standalone_app, host=host, port=port)


# ───────────────────────────────────────────────────────────────────────────
# Entry point
# ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    # Default: stdio transport
    run_stdio()
