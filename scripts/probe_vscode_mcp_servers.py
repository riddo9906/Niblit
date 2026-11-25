import asyncio
import os
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = r"C:\Users\Riyaad\Documents\GitHub\Niblit"

async def probe(name, command, args, cwd=ROOT, env=None):
    try:
        params = StdioServerParameters(command=command, args=args, cwd=cwd, env={**os.environ, **(env or {})})
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                print("SERVER", name, "CONNECTED", len(result.tools))
                for tool in result.tools:
                    print("TOOL", name, tool.name, (tool.description or "").splitlines()[0][:140])
    except Exception as exc:
        print("SERVER", name, "UNAVAILABLE", type(exc).__name__, str(exc)[:180])

async def main():
    await probe("filesystem", "cmd.exe", ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", ROOT])
    await probe("git", "node.exe", [r"C:\Users\Riyaad\mcp\git-mcp.js"])

if __name__ == "__main__":
    asyncio.run(main())
