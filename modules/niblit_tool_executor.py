"""modules/niblit_tool_executor.py — Full Niblit tool suite for function-calling LLMs.

Provides :class:`NiblitToolExecutor` which extends :class:`KBToolExecutor` with
tools for every major Niblit command family: system, brain, memory/KB, learning,
code execution, ALE/healing, model management, and structural awareness.

The executor routes most tools through ``core.process(command)`` (the same path
used by the interactive shell), ensuring that all existing router/core logic is
reused without duplication.

**Slim 2-tool API (Llama 3.2 1B, 2048-token context)**::

    from modules.niblit_tool_executor import NiblitToolExecutor
    from modules.local_brain import NIBLIT_SLIM_TOOLS, _SLIM_SYSTEM_PROMPT

    executor = NiblitToolExecutor(core=core_instance)
    text, tool_calls = lb.generate_with_tools(
        prompt,
        system_prompt=_SLIM_SYSTEM_PROMPT,
        tools=NIBLIT_SLIM_TOOLS,
    )
    results = executor.execute_slim_tool_calls(tool_calls)

**Full 21-tool API (Llama-3.1-8B or larger)**::

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
import os
from typing import Any, Callable, Dict, List, Optional

from modules.kb_tool_executor import KBToolExecutor

log = logging.getLogger("Niblit.NiblitToolExecutor")

# Maximum characters to return from niblit_exec output (prevent context overflow).
_EXEC_MAX_CHARS = int(os.environ.get("NIBLIT_TOOL_EXEC_MAX_CHARS", "800"))

# Maximum tool calls allowed per turn for slim-mode (prevents infinite loops).
_MAX_TOOL_CALLS_PER_TURN = int(os.environ.get("NIBLIT_MAX_TOOL_CALLS", "5"))

# Commands the slim executor will refuse unless confirm_mode is True.
_DESTRUCTIVE_COMMANDS = frozenset({"shutdown", "exit", "quit"})


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
        confirm_mode: bool = False,
    ) -> None:
        super().__init__(knowledge_db=knowledge_db, local_brain=local_brain)
        self._core = core
        # When True, destructive commands (shutdown/exit/quit) are permitted.
        self.confirm_mode = confirm_mode

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

    # ── Slim tool implementations (Llama 3.2 1B) ─────────────────────────────

    def get_structural_info(self, section: str = "all") -> Dict[str, Any]:
        """Build a compact structural snapshot for the ``niblit_structural_info`` tool.

        Returns only the requested *section* to keep token count under 400.

        Sections
        --------
        all      Full snapshot (commands + modules + state).
        commands COMMAND_PREFIXES list only.
        memory   KB + FusedMemory stats.
        brain    LLM stack + routing mode.
        ale      ALE step/status.
        kernel   Cognitive Graph Kernel info.
        """
        section = (section or "all").strip().lower()

        # ── Live state helpers ─────────────────────────────────────────────────
        def _kb_health() -> str:
            try:
                db = self._get_db()
                facts = db.list_facts(limit=5000)
                total = len(facts)
                empty = sum(1 for f in facts if not str(f.get("value", "")).strip())
                pct = round(100 * (1 - empty / max(total, 1)), 1)
                return f"{pct}% ({total} facts, {empty} empty)"
            except Exception:
                return "unavailable"

        def _ale_info() -> Dict[str, Any]:
            core = self._get_core()
            ae = getattr(core, "autonomous_engine", None) if core else None
            if ae is None:
                return {"running": False, "step": "unknown"}
            return {
                "running": getattr(ae, "_running", False),
                "step": str(getattr(ae, "_current_step", "?")),
            }

        def _brain_info() -> Dict[str, Any]:
            core = self._get_core()
            lb = getattr(core, "local_brain", None) if core else None
            backend = getattr(lb, "_backend_in_use", "none") if lb else "not loaded"
            model = getattr(lb, "model_name", "?") if lb else "?"
            try:
                from modules.brain_router import get_brain_router
                mode = get_brain_router().mode
            except Exception:
                mode = "unknown"
            return {"mode": mode, "local_backend": backend, "local_model": model}

        # ── Commands snapshot ──────────────────────────────────────────────────
        def _commands_snapshot() -> List[str]:
            try:
                from niblit_router import NiblitRouter
                prefixes = getattr(NiblitRouter, "COMMAND_PREFIXES", None)
                if prefixes:
                    return list(prefixes)
            except Exception:
                pass
            # Fallback: read the constant from the router instance
            router = self._get_router()
            prefixes = getattr(router, "COMMAND_PREFIXES", None)
            if prefixes:
                return list(prefixes)
            return ["status", "help", "brain", "qwen", "ale", "heal", "tools", "..."]

        # ── Build section ─────────────────────────────────────────────────────
        if section == "commands":
            cmds = _commands_snapshot()
            return {
                "section": "commands",
                "commands": cmds,
                "tip": "Use niblit_run_command with any of these prefixes.",
            }

        if section == "memory":
            kb_health = _kb_health()
            return {
                "section": "memory",
                "layers": {
                    "LocalDB": "niblit.db — JSON facts/interactions/learning_log",
                    "KnowledgeDB": "niblit_memory.json — facts + queue + acquired_data",
                    "FusedMemory": "SQLite events + Qdrant vector search",
                    "NiblitMemory": "top-level hub with circuit-breaker + caching",
                },
                "kb_health": kb_health,
            }

        if section == "brain":
            return {"section": "brain", **_brain_info()}

        if section == "ale":
            ale = _ale_info()
            return {
                "section": "ale",
                "ale_running": ale["running"],
                "current_step": ale["step"],
                "description": "29-step cycle: research→learn→reflect→ideate→implement→heal",
                "tip": "niblit_run_command('autonomous-learn start') to resume",
            }

        if section == "kernel":
            out = self._exec("kernel status")
            return {"section": "kernel", "kernel_status": out[:400]}

        # ── Full snapshot (section == "all" or unknown) ────────────────────────
        return {
            "section": "all",
            "modules": {
                "core":        "niblit_core.py — orchestrator, owns db/brain/router/ae",
                "brain":       "niblit_brain.py — HFBrain + RAG + BrainRouter",
                "router":      "niblit_router.py — routes COMMAND_PREFIXES to handlers",
                "memory":      "LocalDB, KnowledgeDB, FusedMemory, NiblitMemory",
                "ale":         "29-step cycle: research→learn→reflect→ideate→implement→heal",
                "self_healer": "modules/self_healer.py — prunes corrupt KB entries",
                "kernel":      "Cognitive Graph Kernel v1.0 — event bus",
                "qwen":        "QwenLocalBrain — local GGUF; backends: http|subprocess|python",
            },
            "state": {
                "kb_health":    _kb_health(),
                "ale":          _ale_info(),
                "brain":        _brain_info(),
            },
            "commands_tip": "Call niblit_structural_info(section='commands') for full list.",
        }

    def execute_niblit_run_command(
        self, command: str, reason: str
    ) -> Dict[str, Any]:
        """Execute *command* through the router with safety guards.

        Parameters
        ----------
        command:
            Full command string as typed in the shell.
        reason:
            Why the local brain is running this command (audit log).

        Returns
        -------
        dict with ``output`` key (truncated to 600 chars) or ``error`` key.
        """
        if not command or not command.strip():
            return {"error": "command must be a non-empty string"}

        cmd_lower = command.strip().lower().split()[0]

        # Block destructive commands unless confirm_mode is set
        if cmd_lower in _DESTRUCTIVE_COMMANDS and not self.confirm_mode:
            log.warning(
                "[NiblitToolExecutor] Destructive command blocked: %r | reason: %s",
                command, reason,
            )
            return {
                "error": (
                    f"Destructive command {cmd_lower!r} blocked. "
                    "Ask the user to confirm before running shutdown/exit/quit commands."
                )
            }

        log.info(
            "[NiblitToolExecutor] niblit_run_command: %r | reason: %s",
            command, reason,
        )
        output = self._exec(command.strip())
        return {"command": command, "reason": reason, "output": output[:600]}

    def execute_slim_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Execute ``NIBLIT_SLIM_TOOLS`` calls with a per-turn call-count guard.

        Handles exactly two tool names:
        - ``niblit_structural_info`` → :meth:`get_structural_info`
        - ``niblit_run_command``      → :meth:`execute_niblit_run_command`

        Unknown tool names are forwarded to :meth:`_exec` as plain commands.

        The method enforces ``NIBLIT_MAX_TOOL_CALLS`` (default 5) per call to
        prevent infinite loops.  When the limit is reached, remaining calls are
        appended as ``{"tool": name, "error": "max_tool_calls limit reached"}``.

        Parameters
        ----------
        tool_calls:
            Normalised tool call list from :meth:`QwenLocalBrain.generate_with_tools`.

        Returns
        -------
        List of result dicts, one per call, in the same order.
        """
        results: List[Dict[str, Any]] = []
        calls_made = 0

        for call in tool_calls:
            fn = call.get("function", {})
            name: str = fn.get("name", "")
            args_str: str = fn.get("arguments", "{}")

            if calls_made >= _MAX_TOOL_CALLS_PER_TURN:
                log.warning(
                    "[NiblitToolExecutor] max_tool_calls=%d reached, skipping %r",
                    _MAX_TOOL_CALLS_PER_TURN, name,
                )
                results.append({
                    "tool": name,
                    "error": (
                        f"max_tool_calls limit ({_MAX_TOOL_CALLS_PER_TURN}) reached. "
                        "Stop and report results to the user."
                    ),
                })
                continue

            try:
                args: Dict[str, Any] = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError as exc:
                results.append({"tool": name, "error": f"invalid arguments JSON: {exc}"})
                continue

            try:
                if name == "niblit_structural_info":
                    result = self.get_structural_info(section=args.get("section", "all"))
                elif name == "niblit_run_command":
                    result = self.execute_niblit_run_command(
                        command=args.get("command", ""),
                        reason=args.get("reason", ""),
                    )
                else:
                    log.debug(
                        "[NiblitToolExecutor] Slim: unknown tool %r — proxying via _exec",
                        name,
                    )
                    result = {"output": self._exec(name.replace("_", "-"))[:600]}
                results.append({"tool": name, "result": result})
                calls_made += 1
            except Exception as exc:
                log.debug("[NiblitToolExecutor] slim %s error: %s", name, exc)
                results.append({"tool": name, "error": str(exc)})
                calls_made += 1

        return results
