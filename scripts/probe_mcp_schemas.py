import json
from modules.mcp_agent_bridge import get_mcp_agent_bridge

bridge = get_mcp_agent_bridge()
schemas = bridge.connect()
for schema in schemas:
    name = schema["function"]["name"]
    if name in {
        "mcp_desktop_commander_read_file",
        "mcp_desktop_commander_read_multiple_files",
        "mcp_desktop_commander_list_directory",
        "mcp_desktop_commander_start_search",
        "mcp_desktop_commander_get_file_info",
    }:
        print(name, json.dumps(schema["function"]["parameters"], ensure_ascii=False))
bridge.close()
