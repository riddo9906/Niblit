from modules.mcp_agent_bridge import get_mcp_agent_bridge

bridge = get_mcp_agent_bridge()
schemas = bridge.connect()
print("DESKTOP_COMMANDER_BRIDGE_CONNECTED", bridge.status())
for schema in schemas:
    fn = schema["function"]
    if fn["name"] in {
        "mcp_desktop_commander_list_directory",
        "mcp_desktop_commander_read_file",
        "mcp_desktop_commander_start_process",
        "mcp_desktop_commander_write_file",
    }:
        params = fn["parameters"]
        print("TOOL", fn["name"], "required=", params.get("required"), "properties=", list(params.get("properties", {})))
result = bridge.dispatch(
    "mcp_desktop_commander_list_directory",
    {"path": r"C:\Users\Riyaad\Documents\GitHub\Niblit"},
)
print("LIVE_LIST_DIRECTORY_RESULT", str(result)[:1800])
bridge.close()
