import json
from pathlib import Path
from tempfile import TemporaryDirectory

from modules import mcp_agent_bridge as bridge_module


def _write_claude_config(payload):
    temporary = TemporaryDirectory(prefix=".mcp-bridge-test-", dir=str(Path(__file__).resolve().parents[1]))
    root = Path(temporary.name)
    config_dir = root / "Claude"
    config_dir.mkdir()
    (config_dir / "claude_desktop_config.json").write_text(json.dumps(payload), encoding="utf-8")
    return temporary, root


def test_server_config_reads_only_desktop_commander_stdio_definition(monkeypatch):
    temporary, root = _write_claude_config({
        "mcpServers": {
            "desktop-commander": {
                "command": "cmd",
                "args": ["/c", "npx", "-y", "@wonderwhy-er/desktop-commander@latest"],
                "env": {"LOCAL_TEST_SETTING": "present"},
            },
            "unrelated": {"command": "should-not-start", "args": []},
        }
    })
    try:
        monkeypatch.setenv("APPDATA", str(root))
        result = bridge_module._server_config()
        assert result["name"] == "desktop_commander"
        assert result["command"] == "cmd.exe"
        assert result["args"][-1] == "@wonderwhy-er/desktop-commander@latest"
        assert result["env"]["LOCAL_TEST_SETTING"] == "present"
    finally:
        temporary.cleanup()


def test_server_config_rejects_credential_like_command_arguments(monkeypatch):
    temporary, root = _write_claude_config({
        "mcpServers": {
            "desktop-commander": {
                "command": "cmd",
                "args": ["/c", "npx", "--api-key=do-not-use"],
            }
        }
    })
    try:
        monkeypatch.setenv("APPDATA", str(root))
        assert bridge_module._server_config() is None
    finally:
        temporary.cleanup()


def test_register_mcp_tools_uses_same_core_governed_registry(monkeypatch):
    from modules import core_tool_runtime

    read_schema = {
        "type": "function",
        "function": {
            "name": "mcp_desktop_commander_read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    }
    write_schema = {
        "type": "function",
        "function": {
            "name": "mcp_desktop_commander_write_file",
            "description": "Write a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        },
    }

    class FakeBridge:
        _tool_map = {
            "mcp_desktop_commander_read_file": ("desktop_commander", "read_file"),
            "mcp_desktop_commander_write_file": ("desktop_commander", "write_file"),
        }

        def connect(self):
            return [read_schema, write_schema]

        def dispatch(self, name, arguments):
            return {"tool": name, "arguments": arguments}

        def status(self):
            return {"servers": {"desktop_commander": {"available": True}}}

    class FakeLoop:
        def __init__(self):
            self.registered = {}

        def register_capability(self, name, function, schema, metadata=None):
            self.registered[name] = (function, schema, dict(metadata or {}))

    monkeypatch.setenv("NIBLIT_MCP_BRIDGE_ENABLED", "1")
    monkeypatch.setattr(bridge_module, "get_mcp_agent_bridge", lambda: FakeBridge())
    loop = FakeLoop()
    old_metadata = dict(core_tool_runtime.GOVERNED_COMMAND_METADATA)
    old_actions = dict(core_tool_runtime.COMMAND_PERMISSION_ACTIONS)
    try:
        registered = bridge_module.register_mcp_tools(loop)
        assert set(registered) == set(FakeBridge._tool_map)
        assert "mcp_desktop_commander_read_file" in loop.registered
        assert core_tool_runtime.GOVERNED_COMMAND_METADATA["mcp_desktop_commander_read_file"]["requires_authorization"] is False
        assert core_tool_runtime.GOVERNED_COMMAND_METADATA["mcp_desktop_commander_write_file"]["requires_authorization"] is True
        assert core_tool_runtime.COMMAND_PERMISSION_ACTIONS["mcp_desktop_commander_write_file"] == "command.mcp.desktop_commander.write_file"
    finally:
        core_tool_runtime.GOVERNED_COMMAND_METADATA.clear()
        core_tool_runtime.GOVERNED_COMMAND_METADATA.update(old_metadata)
        core_tool_runtime.COMMAND_PERMISSION_ACTIONS.clear()
        core_tool_runtime.COMMAND_PERMISSION_ACTIONS.update(old_actions)

def test_secret_file_policy_blocks_sensitive_paths():
    for path in (
        r"C:\Users\Riyaad\Documents\GitHub\Niblit\.env",
        r"C:\Users\Riyaad\Documents\GitHub\Niblit\.env.local",
        r"C:\Users\Riyaad\Documents\GitHub\Niblit\.git\config",
        r"C:\Users\Riyaad\.ssh\id_ed25519",
        r"C:\Users\Riyaad\secrets\provider.json",
        r"C:\Users\Riyaad\certs\client.pem",
    ):
        assert bridge_module._is_sensitive_path(path)
    assert not bridge_module._is_sensitive_path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\modules\server.py")


def test_dispatch_forces_llm_origin_and_filters_sensitive_directory_entries():
    class FakeConnection:
        def __init__(self):
            self.calls = []

        def call(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            class Result:
                isError = False
                structuredContent = None
                content = [type("Text", (), {"text": "[FILE] .env\n[DIR] .git\n[FILE] server.py"})()]
            return Result()

    bridge = bridge_module.MCPAgentBridge()
    bridge._connections = {"desktop_commander": FakeConnection()}
    bridge._tool_map = {"mcp_desktop_commander_list_directory": ("desktop_commander", "list_directory")}
    bridge._schemas = {"mcp_desktop_commander_list_directory": {
        "function": {"parameters": {"properties": {"path": {}, "origin": {}}}}
    }}
    result = bridge.dispatch("mcp_desktop_commander_list_directory", {"path": ".", "origin": "ui"})
    assert bridge._connections["desktop_commander"].calls[0][1]["origin"] == "llm"
    assert result["content"] == "[FILE] server.py"
