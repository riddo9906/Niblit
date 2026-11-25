from pathlib import Path
import re

path = Path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\modules\mcp_agent_bridge.py")
source = path.read_text(encoding="utf-8")
pattern = re.compile(r"    def dispatch\(self, public_name: str, arguments: dict\[str, Any\]\):\n.*?\n    def status\(self\):", re.S)
replacement = r'''    def dispatch(self, public_name: str, arguments: dict[str, Any]):
        remote_name = self._tool_map.get(public_name)
        if not remote_name or self._connection is None:
            return {"error": "mcp_tool_unavailable"}
        args = dict(arguments or {})
        schema = self._schemas.get(public_name, {}).get("function", {}).get("parameters", {})
        properties = schema.get("properties", {})
        if "origin" in properties:
            args["origin"] = "llm"
        if remote_name in {"read_file", "get_file_info", "list_directory"}:
            if _is_sensitive_path(args.get("path", "")):
                return {"error": "blocked_by_niblit_secret_file_policy"}
        if remote_name == "read_multiple_files":
            paths = args.get("paths", [])
            if not isinstance(paths, list) or any(_is_sensitive_path(value) for value in paths):
                return {"error": "blocked_by_niblit_secret_file_policy"}
        if remote_name in {"write_file", "write_pdf", "edit_block", "move_file"}:
            for key in ("path", "destination", "destination_path", "new_path"):
                if _is_sensitive_path(args.get(key)):
                    return {"error": "blocked_by_niblit_secret_file_policy"}
        if remote_name == "start_search":
            if _is_sensitive_path(args.get("path", "")) or _is_sensitive_path(args.get("filePattern", "")):
                return {"error": "blocked_by_niblit_secret_file_policy"}
            if args.get("searchType") == "content" and not args.get("filePattern"):
                args["filePattern"] = "*.py"
        try:
            result = self._connection.call(remote_name, args)
            chunks = []
            for item in getattr(result, "content", []) or []:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    if remote_name == "list_directory":
                        text = "\n".join(
                            line for line in text.splitlines()
                            if not _is_sensitive_path(line.split(" ", 1)[-1].strip())
                        )
                    chunks.append(text)
                else:
                    chunks.append({"type": str(getattr(item, "type", "unknown"))})
            if getattr(result, "isError", False):
                return {"error": "\n".join(chunks)[:6000] or "MCP tool reported an error"}
            structured = getattr(result, "structuredContent", None)
            return {
                "server": "desktop_commander",
                "tool": remote_name,
                "content": "\n".join(chunks)[:12000],
                **({"structured_content": structured} if structured is not None else {}),
            }
        except Exception as exc:
            log.warning("Desktop Commander tool %s failed: %s", remote_name, type(exc).__name__)
            return {"error": f"desktop_commander_{type(exc).__name__}"}

    def status(self):'''
if not pattern.search(source):
    raise SystemExit("dispatch method pattern not found")
source = pattern.sub(replacement, source, count=1)
path.write_text(source, encoding="utf-8", newline="\n")
print("MCP_DISPATCH_SECRET_GUARDS=APPLIED")
