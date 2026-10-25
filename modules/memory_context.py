"""Pure context selection, independent of storage and inference providers."""
from typing import Dict, List, Optional


def select_recent_messages(
    messages: List[Dict[str, str]],
    *,
    max_messages: int,
    max_chars: Optional[int],
) -> List[Dict[str, str]]:
    """Return a bounded chronological suffix without an orphaned assistant.

    Preserve whole messages rather than silently truncating their content.
    If the newest message cannot fit, no older context is substituted for it.
    Character limits bound history text, not model tokens or the whole prompt.
    """
    if max_messages <= 0 or (max_chars is not None and max_chars <= 0):
        return []
    selected = []
    used = 0
    for message in reversed(messages):
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant", "system"} or not isinstance(content, str) or not content.strip():
            continue
        if len(selected) >= max_messages:
            break
        if max_chars is not None and used + len(content) > max_chars:
            break
        selected.append({"role": role, "content": content})
        used += len(content)
    selected.reverse()
    while selected and selected[0]["role"] == "assistant":
        selected.pop(0)
    return selected
