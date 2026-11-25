"""Governed bridge from Niblit's local agent loop to configured MCP servers.

The bridge reuses the user's existing Claude/VS Code MCP definitions. Every
discovered capability is registered with Core's normal schema validation,
permission metadata and execution trace.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import re
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

log = logging.getLogger("Niblit.MCPAgentBridge")

_SAFE_READ_TOOLS_BY_SERVER = {
    "desktop_commander": {
        "read_file", "read_multiple_files", "list_directory", "start_search",
        "get_more_search_results", "stop_search", "list_searches", "get_file_info",
        "read_process_output", "list_sessions", "list_processes", "get_usage_stats",
    },
    "filesystem": {
        "read_text_file", "read_multiple_files", "read_media_file",
        "list_directory", "list_directory_with_sizes", "directory_tree",
        "search_files", "get_file_info", "list_allowed_directories",
    },
    "git": {"git_status", "git_log", "git_branch", "git_diff_stat", "git_diff"},
}
_EXCLUDED_TOOLS_BY_SERVER = {
    "desktop_commander": {
        "get_config", "set_config_value", "get_recent_tool_calls",
        "give_feedback_to_desktop_commander",
    },
    "filesystem": {"read_file"},
    "git": set(),
}
_SENSITIVE_PATH_PARTS = {
    ".git", ".ssh", ".aws", ".azure", ".netrc", ".npmrc", ".pypirc",
    "credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".p7b", ".keystore"}
_ALLOWED_SERVER_NAMES = {
    "desktop-commander": "desktop_commander",
    "desktop_commander": "desktop_commander",
    "filesystem": "filesystem",
    "git": "git",
}


def _is_sensitive_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normal = value.replace("\\", "/").casefold()
    if "://" in normal:
        return False
    parts = [part for part in normal.split("/") if part]
    for part in parts:
        if (part in _SENSITIVE_PATH_PARTS or ".env" in part
                or "secret" in part or "credential" in part
                or Path(part).suffix in _SENSITIVE_SUFFIXES):
            return True
    return False


def _workspace_root() -> str:
    configured = os.environ.get("NIBLIT_WORKSPACE_ROOT")
    candidate = Path(configured).expanduser() if configured else Path.home() / "Documents" / "GitHub" / "Niblit"
    if not candidate.exists():
        candidate = Path.home()
    return str(candidate)


def _server_configs() -> list[dict[str, Any]]:
    """Load only explicitly supported stdio MCP servers; never log env values."""
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    sources = [
        appdata / "Claude" / "claude_desktop_config.json",
        appdata / "Code" / "User" / "mcp.json",
    ]
    discovered: dict[str, dict[str, Any]] = {}
    for config_path in sources:
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except Exception as exc:
            log.warning("MCP config %s could not be parsed: %s", config_path.name, type(exc).__name__)
            continue
        servers = payload.get("mcpServers") or payload.get("servers") or {}
        if not isinstance(servers, dict):
            continue
        for source_name, config in servers.items():
            canonical = _ALLOWED_SERVER_NAMES.get(str(source_name).casefold())
            if not canonical or canonical in discovered or not isinstance(config, dict):
                continue
            command = str(config.get("command") or "").strip()
            args = config.get("args") or []
            if not command or not isinstance(args, list) or not all(isinstance(v, str) for v in args):
                continue
            if config.get("url"):
                continue
            if any(re.search(r"(?i)(token|secret|password|credential|api[_-]?key)", v) for v in args):
                log.warning("MCP server %s has credential-like command arguments; not started", canonical)
                continue
            if command.casefold() in {"cmd", "cmd.exe"}:
                command = "cmd.exe"
            elif command.casefold() == "npx":
                command = "cmd.exe"
                args = ["/c", "npx", "-y", *[v for v in args if v != "-y"]]
            elif command.casefold() == "node":
                command = "node.exe"
            elif command.casefold() == "docker":
                command = "docker.exe"
            discovered[canonical] = {
                "name": canonical,
                "command": command,
                "args": list(args),
                "env": config.get("env") if isinstance(config.get("env"), dict) else {},
                "cwd": str(Path(config.get("cwd") or _workspace_root()).expanduser()),
                "source": config_path.name,
            }
    return [discovered[name] for name in ("desktop_commander", "filesystem", "git") if name in discovered]


def _server_config() -> dict[str, Any] | None:
    """Compatibility helper used by focused tests and diagnostics."""
    return next((item for item in _server_configs() if item["name"] == "desktop_commander"), None)


def _redact_listing(text: str) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return "\n".join(
            line for line in text.splitlines()
            if not _is_sensitive_path(line.split(" ", 1)[-1].strip())
        )

    def clean(value):
        if isinstance(value, list):
            return [
                clean(item) for item in value
                if not (
                    isinstance(item, dict)
                    and any(_is_sensitive_path(item.get(key)) for key in ("name", "path", "relativePath"))
                )
            ]
        if isinstance(value, dict):
            return {
                key: clean(item) for key, item in value.items()
                if not (key in {"name", "path", "relativePath"} and _is_sensitive_path(item))
            }
        return value

    return json.dumps(clean(payload), ensure_ascii=False)


class _MCPServerConnection:
    """Persistent MCP stdio client hosted on its own asyncio thread."""

    def __init__(self, config: dict[str, Any]):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        self.config = config
        self._ClientSession = ClientSession
        self._stdio_client = stdio_client
        self._StdioServerParameters = StdioServerParameters
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"niblit-mcp-{config['name']}",
            daemon=True,
        )
        self._stack: AsyncExitStack | None = None
        self._session = None
        self._call_lock = threading.RLock()
        self._closed = False
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        self.tools = future.result(timeout=45)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect(self):
        self._stack = AsyncExitStack()
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in self.config.get("env", {}).items()})
        params = self._StdioServerParameters(
            command=self.config["command"],
            args=self.config.get("args", []),
            env=env,
            cwd=self.config.get("cwd"),
        )
        read_stream, write_stream = await self._stack.enter_async_context(self._stdio_client(params))
        self._session = await self._stack.enter_async_context(self._ClientSession(read_stream, write_stream))
        await self._session.initialize()
        discovered = []
        page = await self._session.list_tools()
        discovered.extend(page.tools)
        while getattr(page, "nextCursor", None):
            page = await self._session.list_tools(cursor=page.nextCursor)
            discovered.extend(page.tools)
        return discovered

    def call(self, tool_name: str, arguments: dict[str, Any]):
        if self._closed or self._session is None:
            raise RuntimeError("MCP connection is closed")

        async def invoke():
            return await self._session.call_tool(tool_name, arguments)

        with self._call_lock:
            future = asyncio.run_coroutine_threadsafe(invoke(), self._loop)
            return future.result(timeout=180)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._stack is not None:
                future = asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop)
                future.result(timeout=8)
        except Exception:
            log.debug("MCP connection shutdown was not clean", exc_info=True)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=3)


class MCPAgentBridge:
    def __init__(self):
        self._lock = threading.RLock()
        self._connections: dict[str, _MCPServerConnection] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}
        self._schemas: dict[str, dict[str, Any]] = {}
        self._status: dict[str, dict[str, Any]] = {}
        self._attempted = False

    def connect(self):
        if os.environ.get("NIBLIT_MCP_BRIDGE_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
            self._status = {"bridge": {"available": False, "reason": "disabled_by_configuration"}}
            return []
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("NIBLIT_MCP_BRIDGE_ENABLED") is None:
            return []
        with self._lock:
            if self._attempted:
                return list(self._schemas.values())
            self._attempted = True
            for config in _server_configs():
                server_name = config["name"]
                try:
                    connection = _MCPServerConnection(config)
                    self._connections[server_name] = connection
                    discovered = 0
                    for remote_tool in connection.tools:
                        remote_name = str(remote_tool.name)
                        if remote_name in _EXCLUDED_TOOLS_BY_SERVER.get(server_name, set()):
                            continue
                        public_name = "mcp_" + server_name + "_" + re.sub(r"[^a-zA-Z0-9_]", "_", remote_name)
                        input_schema = dict(getattr(remote_tool, "inputSchema", None) or {})
                        if input_schema.get("type") != "object":
                            input_schema = {"type": "object", "properties": {}, "required": []}
                        input_schema.setdefault("properties", {})
                        input_schema.setdefault("required", [])
                        input_schema.setdefault("additionalProperties", False)
                        self._tool_map[public_name] = (server_name, remote_name)
                        self._schemas[public_name] = {
                            "type": "function",
                            "function": {
                                "name": public_name,
                                "description": (
                                    f"{server_name.replace('_', ' ').title()} MCP tool. "
                                    + str(getattr(remote_tool, "description", "") or remote_name)
                                )[:1800],
                                "parameters": input_schema,
                            },
                        }
                        discovered += 1
                    self._status[server_name] = {
                        "available": True,
                        "tool_count": discovered,
                        "source": config.get("source"),
                    }
                    log.info("MCP server %s connected; %d tools discovered", server_name, discovered)
                except Exception as exc:
                    self._status[server_name] = {
                        "available": False,
                        "reason": type(exc).__name__,
                        "source": config.get("source"),
                    }
                    log.warning("MCP server %s connection failed: %s", server_name, type(exc).__name__)
            return list(self._schemas.values())

    def dispatch(self, public_name: str, arguments: dict[str, Any]):
        route = self._tool_map.get(public_name)
        if not route:
            return {"error": "mcp_tool_unavailable"}
        server_name, remote_name = route
        connection = self._connections.get(server_name)
        if connection is None:
            return {"error": "mcp_server_unavailable"}
        args = dict(arguments or {})
        schema = self._schemas.get(public_name, {}).get("function", {}).get("parameters", {})
        properties = schema.get("properties", {})
        if "origin" in properties:
            args["origin"] = "llm"

        path_keys = (
            "path", "file_path", "source", "source_path", "destination",
            "destination_path", "new_path", "directory",
        )
        if any(_is_sensitive_path(args.get(key)) for key in path_keys):
            return {"error": "blocked_by_niblit_secret_file_policy"}
        if remote_name == "read_multiple_files":
            paths = args.get("paths", [])
            if not isinstance(paths, list) or any(_is_sensitive_path(value) for value in paths):
                return {"error": "blocked_by_niblit_secret_file_policy"}
        if remote_name == "start_search":
            file_pattern = args.get("filePattern", "")
            if _is_sensitive_path(file_pattern):
                return {"error": "blocked_by_niblit_secret_file_policy"}
            if args.get("searchType") == "content":
                if not file_pattern:
                    args["filePattern"] = "*.py"
                elif file_pattern.strip() in {"*", "*.*", "**/*", "**/*.*"}:
                    return {"error": "broad_content_search_requires_safe_file_pattern"}

        try:
            result = connection.call(remote_name, args)
            chunks = []
            listing_tools = {
                "list_directory", "list_directory_with_sizes", "directory_tree", "search_files",
            }
            for item in getattr(result, "content", []) or []:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    if remote_name in listing_tools:
                        text = _redact_listing(text)
                    chunks.append(text)
                else:
                    chunks.append({"type": str(getattr(item, "type", "unknown"))})
            if getattr(result, "isError", False):
                return {"error": "\n".join(str(item) for item in chunks)[:6000] or "MCP tool reported an error"}
            structured = getattr(result, "structuredContent", None)
            return {
                "server": server_name,
                "tool": remote_name,
                "content": "\n".join(str(item) for item in chunks)[:12000],
                **({"structured_content": structured} if structured is not None else {}),
            }
        except Exception as exc:
            log.warning("MCP tool %s.%s failed: %s", server_name, remote_name, type(exc).__name__)
            return {"error": f"mcp_{server_name}_{type(exc).__name__}"}

    def status(self):
        return {
            "available": any(item.get("available") for item in self._status.values()),
            "servers": {name: dict(value) for name, value in self._status.items()},
            "tool_count": len(self._schemas),
        }

    def close(self):
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        for connection in connections:
            connection.close()


_bridge: MCPAgentBridge | None = None
_bridge_lock = threading.RLock()


def get_mcp_agent_bridge() -> MCPAgentBridge:
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = MCPAgentBridge()
            atexit.register(_bridge.close)
        return _bridge


def register_mcp_tools(loop) -> list[str]:
    """Register discovered MCP tools on the same governed Core tool loop."""
    enabled = os.environ.get("NIBLIT_MCP_BRIDGE_ENABLED")
    if enabled is not None and enabled.strip().lower() in {"0", "false", "no"}:
        return []
    if enabled is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    bridge = get_mcp_agent_bridge()
    schemas = bridge.connect()
    if not schemas:
        return []
    from modules.core_tool_runtime import COMMAND_PERMISSION_ACTIONS, GOVERNED_COMMAND_METADATA
    server_configs = {item["name"]: item for item in _server_configs()}
    registered = []
    for schema in schemas:
        name = schema["function"]["name"]
        server_name, remote_name = bridge._tool_map[name]
        safe_read = remote_name in _SAFE_READ_TOOLS_BY_SERVER.get(server_name, set())
        action = f"command.mcp.{server_name}.{remote_name}"
        server_config = server_configs.get(server_name, {})
        category = server_name.replace("_", " ").title() + " MCP"
        scope = {
            "desktop_commander": "host_filesystem",
            "filesystem": "workspace_filesystem",
            "git": "repository",
        }.get(server_name, "provider")
        allowed_roots = []
        if server_name in {"filesystem", "git"}:
            root_cwd = os.path.abspath(server_config.get("cwd") or os.getcwd())
            if server_name == "git":
                allowed_roots = [root_cwd]
            else:
                args = list(server_config.get("args") or [])
                package_index = next(
                    (index for index, value in enumerate(args)
                     if "server-filesystem" in str(value)),
                    None,
                )
                root_args = args[package_index + 1:] if package_index is not None else ["."]
                root_args = [value for value in root_args if not str(value).startswith("-")]
                allowed_roots = [
                    os.path.abspath(os.path.join(root_cwd, str(value)))
                    for value in (root_args or ["."])
                ]
        function = schema.get("function", {})
        parameter_names = list(
            (function.get("parameters") or {}).get("properties", {}).keys()
        )
        metadata = {
            "provider": server_name,
            "scope": scope,
            "allowed_roots": allowed_roots,
            "category": category,
            "keywords": [
                server_name.replace("_", " "),
                remote_name.replace("_", " "),
                *parameter_names,
            ],
            "risk_class": "low" if safe_read else "high",
            "side_effect_level": "read_only" if safe_read else "mutation",
            "requires_authorization": not safe_read,
        }
        loop.register_capability(
            name,
            lambda _name=name, **arguments: bridge.dispatch(_name, arguments),
            schema,
            metadata=metadata,
        )
        GOVERNED_COMMAND_METADATA[name] = {
            **metadata,
            "availability": lambda core, _bridge=bridge, _server=server_name: bool(
                _bridge.status().get("servers", {}).get(_server, {}).get("available")
            ),
        }
        if not safe_read:
            COMMAND_PERMISSION_ACTIONS[name] = action
        registered.append(name)
    return registered
