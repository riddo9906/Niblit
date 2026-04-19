"""modules/kb_tool_executor.py — KB tool execution for local LLM tool-calling.

This module provides :class:`KBToolExecutor`, which implements the four KB
tools exposed to function-calling capable local models (e.g. Llama 3.2 1B):

* ``list_kb_facts``      — survey the KnowledgeDB
* ``read_kb_fact``       — read a specific fact by key
* ``delete_kb_fact``     — delete a corrupt/empty fact (destructive; confirm required)
* ``complete_slsa_artifact`` — synthesise a complete SLSA fact for a partial entry

Usage::

    from modules.kb_tool_executor import KBToolExecutor

    executor = KBToolExecutor()
    text, tool_calls = lb.generate_with_tools("heal kb", tools=NIBLIT_KB_TOOLS)
    result = executor.execute_tool_calls(tool_calls, confirm_fn=None)

For the ``delete_kb_fact`` tool a ``confirm_fn(key: str) -> bool`` can be
supplied.  When ``confirm_fn`` returns ``False`` the deletion is skipped.
If ``confirm_fn`` is ``None``, deletions are **skipped** (safe default for
non-interactive / automated contexts).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("Niblit.KBToolExecutor")


class KBToolExecutor:
    """Execute KB tool calls produced by a local function-calling LLM.

    Parameters
    ----------
    knowledge_db:
        A :class:`~niblit_memory.KnowledgeDB` instance.  When ``None`` the
        executor attempts to import the process-wide singleton lazily.
    local_brain:
        A :class:`~modules.local_brain.QwenLocalBrain` instance used for the
        ``complete_slsa_artifact`` tool.  When ``None`` the tool returns a
        placeholder message.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        local_brain: Optional[Any] = None,
    ) -> None:
        self._db = knowledge_db
        self._lb = local_brain

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_db(self) -> Any:
        if self._db is not None:
            return self._db
        try:
            from niblit_memory import KnowledgeDB
            return KnowledgeDB()
        except Exception as exc:
            raise RuntimeError(f"KnowledgeDB unavailable: {exc}") from exc

    def _get_lb(self) -> Optional[Any]:
        if self._lb is not None:
            return self._lb
        try:
            from modules.local_brain import get_local_brain
            return get_local_brain()
        except Exception:
            return None

    # ── Tool implementations ──────────────────────────────────────────────────

    def list_kb_facts(self, limit: int = 20, tag: Optional[str] = None) -> Dict[str, Any]:
        """Return a compact list of KB fact summaries."""
        db = self._get_db()
        facts: List[Dict[str, Any]] = db.list_facts(limit=limit * 3)  # over-fetch then filter
        if tag:
            facts = [f for f in facts if tag in (f.get("tags") or [])]
        facts = facts[:limit]
        rows = []
        for f in facts:
            value = str(f.get("value", ""))
            snippet = (value[:80] + "…") if len(value) > 80 else value
            rows.append({
                "key": f.get("key", ""),
                "snippet": snippet,
                "tags": f.get("tags", []),
            })
        return {"count": len(rows), "facts": rows}

    def read_kb_fact(self, key: str) -> Dict[str, Any]:
        """Return the full stored value for *key*."""
        db = self._get_db()
        facts: List[Dict[str, Any]] = db.list_facts(limit=10000)
        for fact in facts:
            if isinstance(fact, dict) and fact.get("key") == key:
                return {"found": True, "key": key, "value": fact.get("value"), "tags": fact.get("tags", [])}
        return {"found": False, "key": key}

    def delete_kb_fact(
        self,
        key: str,
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ) -> Dict[str, Any]:
        """Delete the KB fact with *key*, subject to confirmation.

        Parameters
        ----------
        key:
            Key of the fact to delete.
        confirm_fn:
            Callable that receives *key* and must return ``True`` to proceed.
            When ``None`` the deletion is **skipped** (safe default).
        """
        if confirm_fn is None:
            log.info("[KBToolExecutor] delete_kb_fact(%r) skipped — no confirm_fn", key)
            return {"deleted": False, "key": key, "reason": "deletion requires confirmation"}

        if not confirm_fn(key):
            return {"deleted": False, "key": key, "reason": "user declined"}

        db = self._get_db()
        removed = db.delete_fact(key)
        if removed:
            log.info("[KBToolExecutor] Deleted KB fact key=%r", key)
            return {"deleted": True, "key": key}
        return {"deleted": False, "key": key, "reason": "key not found"}

    def complete_slsa_artifact(self, key: str) -> Dict[str, Any]:
        """Synthesise a complete SLSA fact for a partial entry.

        Reads the existing value for *key* (if any), asks the local LLM to
        produce a complete, fact-dense SLSA record, and stores the result back.
        """
        # Read existing value
        existing = self.read_kb_fact(key)
        current_value = str(existing.get("value", "")) if existing.get("found") else ""

        lb = self._get_lb()
        if lb is None:
            return {"completed": False, "key": key, "reason": "local brain unavailable"}

        system = (
            "You are Niblit's KB curator. Given a KB key and any partial content, "
            "produce a concise, fact-dense SLSA (Structured Live Sense Artifact) entry "
            "covering: definition, structure, function, origin, evolution, context. "
            "Output only the completed entry text, no preamble."
        )
        user_prompt = (
            f"KB key: {key}\n"
            f"Current partial value:\n{current_value or '(empty)'}\n\n"
            "Complete the SLSA entry:"
        )
        completed = lb.ask(user_prompt, system_prompt=system)
        if completed.startswith("[LocalBrain"):
            return {"completed": False, "key": key, "reason": completed}

        # Store the completed value
        db = self._get_db()
        db.store_research(
            key=key,
            text=completed,
            tags=["slsa", "completed"],
            source="kb_tool_executor",
        )
        log.info("[KBToolExecutor] Completed SLSA artifact for key=%r", key)
        return {"completed": True, "key": key, "value": completed[:200]}

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a list of tool call dicts returned by :meth:`generate_with_tools`.

        Each element must have ``{"function": {"name": ..., "arguments": <str>}}``.
        Results are returned in the same order as *tool_calls*.

        Parameters
        ----------
        tool_calls:
            Normalised tool call list from :meth:`QwenLocalBrain.generate_with_tools`.
        confirm_fn:
            Passed through to :meth:`delete_kb_fact`.  When ``None`` deletions
            are logged but skipped.

        Returns
        -------
        List of result dicts, one per call.
        """
        results: List[Dict[str, Any]] = []
        for call in tool_calls:
            fn = call.get("function", {})
            name: str = fn.get("name", "")
            args_str: str = fn.get("arguments", "{}")
            try:
                args: Dict[str, Any] = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError as exc:
                results.append({"tool": name, "error": f"invalid arguments JSON: {exc}"})
                continue

            try:
                if name == "list_kb_facts":
                    result = self.list_kb_facts(
                        limit=int(args.get("limit", 20)),
                        tag=args.get("tag"),
                    )
                elif name == "read_kb_fact":
                    result = self.read_kb_fact(key=args["key"])
                elif name == "delete_kb_fact":
                    result = self.delete_kb_fact(
                        key=args["key"],
                        confirm_fn=confirm_fn,
                    )
                elif name == "complete_slsa_artifact":
                    result = self.complete_slsa_artifact(key=args["key"])
                else:
                    result = {"error": f"unknown tool: {name!r}"}
                results.append({"tool": name, "result": result})
            except Exception as exc:
                log.debug("[KBToolExecutor] %s error: %s", name, exc)
                results.append({"tool": name, "error": str(exc)})

        return results
