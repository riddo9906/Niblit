import asyncio
import json
import os
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    config_path = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "mcp.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers") or payload.get("servers") or {}
    config = servers["MCP_DOCKER"]
    env = dict(os.environ)
    env.update({str(k): str(v) for k, v in (config.get("env") or {}).items()})
    params = StdioServerParameters(
        command="docker.exe",
        args=list(config["args"]),
        cwd=r"C:\Users\Riyaad\Documents\GitHub\Niblit",
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            print("DOCKER_MCP_CONNECTED", len(result.tools))
            for tool in result.tools:
                print("TOOL", tool.name, (tool.description or "").splitlines()[0][:150])
if __name__ == "__main__":
    asyncio.run(main())
