from pathlib import Path
p = Path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\modules\mcp_agent_bridge.py")
s = p.read_text(encoding="utf-8")
s = s.replace('text = "\n".join(', 'text = "\\n".join(')
s = s.replace('return {"error": "\n".join(', 'return {"error": "\\n".join(')
s = s.replace('"content": "\n".join(', '"content": "\\n".join(')
p.write_text(s, encoding="utf-8", newline="\n")
print("MCP_DISPATCH_STRING_LITERALS_FIXED")
