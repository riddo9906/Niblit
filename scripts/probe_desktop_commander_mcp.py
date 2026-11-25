import asyncio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    params = StdioServerParameters(
        command="cmd.exe",
        args=["/c", "npx", "-y", "@wonderwhy-er/desktop-commander@latest"],
        cwd=r"C:\Users\Riyaad\Documents\GitHub\Niblit",
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            print("DESKTOP_COMMANDER_MCP_CONNECTED=PASS")
            print("TOOL_COUNT", len(result.tools))
            for tool in result.tools:
                print(tool.name, "-", (tool.description or "")[:100])

if __name__ == "__main__":
    asyncio.run(main())
