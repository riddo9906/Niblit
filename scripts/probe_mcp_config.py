import json
from pathlib import Path
import re
path = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "mcp.json"
data = json.loads(path.read_text(encoding="utf-8"))
servers = data.get("mcpServers") or data.get("servers") or {}
for name in ("docker", "MCP_DOCKER", "netdata"):
    item = servers.get(name)
    if not item:
        continue
    args = []
    for value in item.get("args", []):
        args.append("[REDACTED]" if re.search(r"(?i)(token|secret|password|credential|api[_-]?key)", value) else value)
    print("SERVER", name)
    print("COMMAND", item.get("command"))
    print("ARGS", args)
    print("URL", item.get("url"))
    print("ENV_KEYS", sorted((item.get("env") or {}).keys()))
