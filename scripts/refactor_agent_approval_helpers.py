from pathlib import Path
import re
p = Path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\server.py")
s = p.read_text(encoding="utf-8")
pattern = re.compile(r"def _agent_operator_origin_allowed\(request: Request\) -> bool:\n.*?\n\ndef _is_registered_chat_command", re.S)
replacement = '''def _agent_operator_origin_allowed(request: Request) -> bool:
    from modules.agent_tool_approval import operator_origin_allowed
    return operator_origin_allowed(request)


def _register_agent_tool_approvals(request_id: str, trace: list[dict]) -> None:
    from modules.agent_tool_approval import register_pending_approvals
    from modules.core_tool_runtime import COMMAND_PERMISSION_ACTIONS, GOVERNED_COMMAND_METADATA
    register_pending_approvals(
        request_id, trace, _AGENT_TOOL_APPROVALS, _AGENT_TOOL_APPROVALS_LOCK,
        GOVERNED_COMMAND_METADATA, COMMAND_PERMISSION_ACTIONS,
        ttl_seconds=_AGENT_TOOL_APPROVAL_TTL_SECONDS,
    )


def _is_registered_chat_command'''
if not pattern.search(s):
    raise SystemExit("server approval helper block not found")
s = pattern.sub(replacement, s, count=1)
p.write_text(s, encoding="utf-8", newline="\n")
print("SERVER_APPROVAL_HELPERS_DELEGATED=PASS")
