import os
from modules.core_tool_runtime import build_governed_tool_loop
from modules.mcp_agent_bridge import get_mcp_agent_bridge

os.environ["NIBLIT_MCP_BRIDGE_ENABLED"] = "1"
loop = build_governed_tool_loop(lambda: None)
names = loop.allowed_tool_names()
mcp_names = [name for name in names if name.startswith("mcp_")]
print("CORE_GOVERNED_MCP_TOOLS_REGISTERED", len(mcp_names))
print("MCP_TOOL_GROUPS", sorted({name.split("_")[1] for name in mcp_names}))
for name in ("mcp_desktop_commander_list_directory", "mcp_filesystem_list_allowed_directories", "mcp_git_git_status", "docker_list_containers"):
    print("REGISTERED", name, name in names)

read_result = loop.invoke(
    "mcp_desktop_commander_list_directory",
    {"path": r"C:\Users\Riyaad\Documents\GitHub\Niblit"},
)
print("DESKTOP_COMMANDER_READ_STATUS", read_result["status"])
print("DESKTOP_COMMANDER_READ_HAS_OUTPUT", bool(read_result.get("result", {}).get("content")))

filesystem_result = loop.invoke("mcp_filesystem_list_allowed_directories", {})
print("FILESYSTEM_READ_STATUS", filesystem_result["status"])

git_result = loop.invoke("mcp_git_git_status", {})
print("GIT_STATUS", git_result["status"])
print("GIT_OUTPUT_PRESENT", bool(git_result.get("result", {}).get("content")))

docker_result = loop.invoke("docker_list_containers", {})
print("DOCKER_LIST_STATUS", docker_result["status"])
print("DOCKER_LIST_OUTPUT_PRESENT", bool(docker_result.get("result", {}).get("output")))

docker_mutation = loop.invoke("docker_start_container", {"container": "niblit-test"})
print("DOCKER_MUTATION_GATED", docker_mutation["status"])

blocked = loop.invoke(
    "mcp_desktop_commander_read_file",
    {"path": r"C:\Users\Riyaad\Documents\GitHub\Niblit\.env"},
)
print("SECRET_READ_BLOCKED", blocked["status"], blocked.get("error"))

mutation = loop.invoke(
    "mcp_desktop_commander_write_file",
    {"path": "agent-test.txt", "content": "must not run without approval"},
)
print("MUTATION_GATED", mutation["status"], mutation.get("error"))

get_mcp_agent_bridge().close()
