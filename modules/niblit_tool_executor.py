"""modules/niblit_tool_executor.py — Full Niblit tool suite for function-calling LLMs.

Provides :class:`NiblitToolExecutor` which extends :class:`KBToolExecutor` with
tools for every major Niblit command family: system, brain, memory/KB, learning,
code execution, ALE/healing, model management, and structural awareness.

The executor routes most tools through ``core.process(command)`` (the same path
used by the interactive shell), ensuring that all existing router/core logic is
reused without duplication.

Usage::

    from modules.niblit_tool_executor import NiblitToolExecutor
    from modules.local_brain import NIBLIT_ALL_TOOLS, _TOOL_CALL_SYSTEM_PROMPT

    executor = NiblitToolExecutor(core=core_instance)
    text, tool_calls = lb.generate_with_tools(
        prompt,
        system_prompt=_TOOL_CALL_SYSTEM_PROMPT,
        tools=NIBLIT_ALL_TOOLS,
    )
    results = executor.execute_tool_calls(tool_calls, confirm_fn=None)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from modules.kb_tool_executor import KBToolExecutor

log = logging.getLogger("Niblit.NiblitToolExecutor")

# Maximum characters to return from niblit_exec output (prevent context overflow).
_EXEC_MAX_CHARS = int(__import__("os").environ.get("NIBLIT_TOOL_EXEC_MAX_CHARS", "800"))


class NiblitToolExecutor(KBToolExecutor):
    """Execute all Niblit tool calls produced by a function-calling LLM.

    Inherits all KB tools from :class:`KBToolExecutor` and adds:
    - Core system tools (niblit_status, niblit_exec, niblit_list_commands)
    - Brain routing tools (set_brain_mode, toggle_llm)
    - Local model management (switch_local_model, local_model_status)
    - Extended memory tools (search_memory, store_kb_fact)
    - Learning tools (self_research, self_teach, reflect)
    - Code tools (run_code, fix_code)
    - ALE tools (ale_status, autonomous_learn)
    - Self-healing (run_selfheal)
    - Structural awareness (niblit_structure)

    Parameters
    ----------
    core:
        A :class:`~niblit_core.NiblitCore` instance.  When ``None`` the
        executor falls back to the process singleton or router singleton.
    knowledge_db:
        Optional :class:`~niblit_memory.KnowledgeDB` override (passed to parent).
    local_brain:
        Optional :class:`~modules.local_brain.QwenLocalBrain` override (parent).
    """

    def __init__(
        self,
        core: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        local_brain: Optional[Any] = None,
    ) -> None:
        super().__init__(knowledge_db=knowledge_db, local_brain=local_brain)
        self._core = core

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_core(self) -> Optional[Any]:
        if self._core is not None:
            return self._core
        # Try to reach the process-wide singleton if available
        try:
            import niblit_core as _nc
            return getattr(_nc, "_active_core", None)
        except Exception:
            return None

    def _get_router(self) -> Optional[Any]:
        core = self._get_core()
        if core:
            return getattr(core, "router", None)
        try:
            from niblit_router import NiblitRouter
            return getattr(NiblitRouter, "_instance", None)
        except Exception:
            return None

    def _exec(self, command: str) -> str:
        """Route *command* through NiblitCore.process() or the router fallback."""
        core = self._get_core()
        if core is not None and hasattr(core, "process"):
            try:
                result = core.process(command)
                return str(result or "")[:_EXEC_MAX_CHARS]
            except Exception as exc:
                return f"[niblit_exec error: {exc}]"

        router = self._get_router()
        if router is not None and hasattr(router, "process"):
            try:
                result = router.process(command)
                return str(result or "")[:_EXEC_MAX_CHARS]
            except Exception as exc:
                return f"[router_exec error: {exc}]"

        return "[niblit_exec: core not available — start Niblit first]"

    # ── System tools ──────────────────────────────────────────────────────────

    def niblit_status(self) -> Dict[str, Any]:
        """Return a compact runtime status snapshot."""
        output = self._exec("status")
        return {"status": output}

    def niblit_exec(self, command: str) -> Dict[str, Any]:
        """Execute any Niblit command string and return its output."""
        output = self._exec(command)
        return {"command": command, "output": output}

    def niblit_list_commands(self) -> Dict[str, Any]:
        """Return all available commands grouped by category."""
        output = self._exec("commands")
        return {"commands": output}

    # ── Brain / LLM routing tools ─────────────────────────────────────────────

    def set_brain_mode(self, mode: str) -> Dict[str, Any]:
        """Change BrainRouter mode (local|balanced|power|offline)."""
        valid = {"local", "balanced", "power", "offline"}
        if mode not in valid:
            return {"error": f"Invalid mode {mode!r}. Use: {sorted(valid)}"}
        output = self._exec(f"brain mode {mode}")
        return {"mode": mode, "result": output}

    def toggle_llm(self, action: str) -> Dict[str, Any]:
        """Toggle cloud LLM on/off/status."""
        valid = {"on", "off", "status"}
        if action not in valid:
            return {"error": f"Invalid action {action!r}. Use: on | off | status"}
        output = self._exec(f"toggle-llm {action}")
        return {"action": action, "result": output}

    # ── Local model management ────────────────────────────────────────────────

    def switch_local_model(self, preset: str) -> Dict[str, Any]:
        """Hot-swap local model to a named preset (qwen|llama3)."""
        output = self._exec(f"local-model switch {preset}")
        return {"preset": preset, "result": output}

    def local_model_status(self) -> Dict[str, Any]:
        """Return active local model status."""
        output = self._exec("local-model status")
        return {"result": output}

    # ── Extended memory tools ─────────────────────────────────────────────────

    def search_memory(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search the knowledge base for facts matching *query*."""
        try:
            db = self._get_db()
            results = db.search(query, limit=limit)
            rows = []
            for r in results:
                if isinstance(r, dict):
                    value = str(r.get("value", ""))
                    rows.append({
                        "key": r.get("key", ""),
                        "snippet": (value[:120] + "…") if len(value) > 120 else value,
                        "tags": r.get("tags", []),
                    })
                else:
                    rows.append({"entry": str(r)[:120]})
            return {"query": query, "count": len(rows), "results": rows}
        except Exception as exc:
            return {"error": str(exc)}

    def store_kb_fact(self, key: str, value: str, tags: str = "") -> Dict[str, Any]:
        """Store a new fact in the knowledge base."""
        try:
            db = self._get_db()
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            db.add_fact(key=key, value=value, tags=tag_list)
            return {"stored": True, "key": key, "tags": tag_list}
        except Exception as exc:
            return {"stored": False, "error": str(exc)}

    # ── Learning tools ────────────────────────────────────────────────────────

    def self_research(self, topic: str) -> Dict[str, Any]:
        """Research *topic* via multi-backend engine and store in KB."""
        output = self._exec(f"self-research {topic}")
        return {"topic": topic, "result": output[:600]}

    def self_teach(self, topic: str) -> Dict[str, Any]:
        """Research + ingest *topic* as structured KB entries."""
        output = self._exec(f"self-teach {topic}")
        return {"topic": topic, "result": output[:600]}

    def reflect(self, topic: str) -> Dict[str, Any]:
        """Reflect on *topic*: summarise KB facts and store insight."""
        output = self._exec(f"reflect {topic}")
        return {"topic": topic, "result": output[:600]}

    # ── Code tools ────────────────────────────────────────────────────────────

    def run_code(self, language: str, code: str) -> Dict[str, Any]:
        """Run a code snippet through Niblit's CodeCompiler."""
        output = self._exec(f"run code {language} {code}")
        return {"language": language, "output": output[:800]}

    def fix_code(self, language: str, code: str) -> Dict[str, Any]:
        """Fix a broken code snippet via CodeErrorFixer (up to 3 retries)."""
        output = self._exec(f"fix code {language} {code}")
        return {"language": language, "output": output[:800]}

    # ── ALE tools ─────────────────────────────────────────────────────────────

    def ale_status(self) -> Dict[str, Any]:
        """Return ALE (Autonomous Learning Engine) status."""
        output = self._exec("ale status")
        return {"ale_status": output}

    def autonomous_learn(self, action: str) -> Dict[str, Any]:
        """Start/stop/status the ALE background loop."""
        valid = {"start", "stop", "status"}
        if action not in valid:
            return {"error": f"Invalid action {action!r}. Use: start | stop | status"}
        output = self._exec(f"autonomous-learn {action}")
        return {"action": action, "result": output}

    # ── Self-healing ──────────────────────────────────────────────────────────

    def run_selfheal(self) -> Dict[str, Any]:
        """Trigger SelfHealer to scan and patch Niblit's own source."""
        output = self._exec("run-selfheal")
        return {"selfheal_result": output}

    # ── Structural awareness ──────────────────────────────────────────────────

    def niblit_structure(self, section: str = "") -> Dict[str, Any]:
        """Return live structural snapshot of Niblit."""
        cmd_map = {
            "modules":    "my modules",
            "threads":    "my threads",
            "loops":      "ale processes",
            "commands":   "my commands",
            "resources":  "sa-resources",
            "dashboard":  "dashboard",
            "flow":       "sa-flow",
        }
        if section and section.lower() in cmd_map:
            output = self._exec(cmd_map[section.lower()])
        else:
            # Full snapshot: combine the most useful sections
            parts = []
            for cmd in ("status", "brain status", "ale status", "my modules"):
                out = self._exec(cmd)
                if out and not out.startswith("[niblit_exec"):
                    parts.append(f"--- {cmd} ---\n{out[:400]}")
            output = "\n\n".join(parts)
        return {"section": section or "full", "result": output[:1000]}

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Dispatch all tool calls and return results.

        Extends the parent KB dispatcher with all Niblit-level tools.
        Unknown tool names fall back to ``niblit_exec(name + ' ' + args)``
        so the model can still reach any command even if no specific tool exists.
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
                result = self._dispatch(name, args, confirm_fn=confirm_fn)
                results.append({"tool": name, "result": result})
            except Exception as exc:
                log.debug("[NiblitToolExecutor] %s error: %s", name, exc)
                results.append({"tool": name, "error": str(exc)})

        return results

    def _dispatch(
        self,
        name: str,
        args: Dict[str, Any],
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ) -> Any:
        """Route a single tool name + args to the correct implementation."""
        # ── KB tools (parent) ─────────────────────────────────────────────────
        if name == "list_kb_facts":
            return self.list_kb_facts(
                limit=int(args.get("limit", 20)),
                tag=args.get("tag"),
            )
        if name == "read_kb_fact":
            return self.read_kb_fact(key=args["key"])
        if name == "delete_kb_fact":
            return self.delete_kb_fact(key=args["key"], confirm_fn=confirm_fn)
        if name == "complete_slsa_artifact":
            return self.complete_slsa_artifact(key=args["key"])

        # ── System ────────────────────────────────────────────────────────────
        if name == "niblit_status":
            return self.niblit_status()
        if name == "niblit_exec":
            return self.niblit_exec(command=args["command"])
        if name == "niblit_list_commands":
            return self.niblit_list_commands()

        # ── Brain / LLM ───────────────────────────────────────────────────────
        if name == "set_brain_mode":
            return self.set_brain_mode(mode=args["mode"])
        if name == "toggle_llm":
            return self.toggle_llm(action=args["action"])

        # ── Local model ───────────────────────────────────────────────────────
        if name == "switch_local_model":
            return self.switch_local_model(preset=args["preset"])
        if name == "local_model_status":
            return self.local_model_status()

        # ── Extended memory ───────────────────────────────────────────────────
        if name == "search_memory":
            return self.search_memory(
                query=args["query"],
                limit=int(args.get("limit", 10)),
            )
        if name == "store_kb_fact":
            return self.store_kb_fact(
                key=args["key"],
                value=args["value"],
                tags=args.get("tags", ""),
            )

        # ── Learning ──────────────────────────────────────────────────────────
        if name == "self_research":
            return self.self_research(topic=args["topic"])
        if name == "self_teach":
            return self.self_teach(topic=args["topic"])
        if name == "reflect":
            return self.reflect(topic=args["topic"])

        # ── Code ──────────────────────────────────────────────────────────────
        if name == "run_code":
            return self.run_code(language=args["language"], code=args["code"])
        if name == "fix_code":
            return self.fix_code(language=args["language"], code=args["code"])

        # ── ALE ───────────────────────────────────────────────────────────────
        if name == "ale_status":
            return self.ale_status()
        if name == "autonomous_learn":
            return self.autonomous_learn(action=args["action"])

        # ── Self-healing ──────────────────────────────────────────────────────
        if name == "run_selfheal":
            return self.run_selfheal()

        # ── Structural ────────────────────────────────────────────────────────
        if name == "niblit_structure":
            return self.niblit_structure(section=args.get("section", ""))

        # ── Generic fallback: route through niblit_exec ───────────────────────
        log.debug(
            "[NiblitToolExecutor] Unknown tool %r — falling back to niblit_exec", name
        )
        # Build a best-effort command string from name + args
        arg_str = " ".join(str(v) for v in args.values())
        fallback_cmd = f"{name.replace('_', '-')} {arg_str}".strip()
        return self.niblit_exec(command=fallback_cmd)
