"""modules/llm_tool_loop.py - governed Core-side LLM tool execution loop.

Phase 4C: connect the local LLM (via Cloud :8000) to Niblit's existing
governed capability layer (NiblitToolExecutor) so the model REQUESTS actions
and Core AUTHORIZES and EXECUTES them, then returns observations back to the
SAME logical reasoning interaction.

Model never owns execution authority: every tool call is validated (schema),
bounded, and routed through NiblitToolExecutor.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from modules.niblit_tool_executor import MAX_TOOL_CALLS_PER_TURN, NiblitToolExecutor

log = logging.getLogger("Niblit.LlmToolLoop")

_NIBLIT_CLOUD_PORT = int(os.environ.get("NIBLIT_CLOUD_SERVER_PRIMARY_PORT", "8000"))
_CLOUD_ROOT = f"http://127.0.0.1:{_NIBLIT_CLOUD_PORT}"
_CHAT_PATH = "/v1/chat/completions"

# Repetition guard: the same tool requested with identical arguments more
# than this many times means the model is stuck in a loop; the guard then
# removes the tool surface so the model MUST answer from the observations
# it already has (bounded, truthful, never fabricated).
MAX_IDENTICAL_TOOL_CALLS = 2
_NIBLIT_CLOUD_PORT = int(os.environ.get("NIBLIT_CLOUD_SERVER_PRIMARY_PORT", "8000"))
_CLOUD_ROOT = f"http://127.0.0.1:{_NIBLIT_CLOUD_PORT}"
_CHAT_PATH = "/v1/chat/completions"


def make_runtime_status_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "runtime_status",
            "description": (
                "Fetch the current Niblit runtime status shell output. "
                "Read-only; no side effects. Useful for answering questions "
                "about Niblit's runtime state or status."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


class ToolCallError(Exception):
    """A tool call was invalid or not permitted."""


class ToolAuthorizationError(ToolCallError):
    """A capability is registered but requires an operator permission grant."""


class LlmToolLoop:

    def __init__(self, executor=None, cloud_root=None, max_loop_calls=15, timeout=300.0,
                 memory_gateway=None, memory_scope=None):
        self.cloud_root = cloud_root or _CLOUD_ROOT
        self.executor = executor or NiblitToolExecutor()
        self.max_loop_calls = max_loop_calls
        self.timeout = timeout
        self.memory_gateway = memory_gateway
        self.memory_scope = memory_scope
        self._tool_map = {"runtime_status": self.executor.niblit_status}

    def allowed_tool_names(self):
        return list(self._tool_map.keys())

    def register_capability(self, name, fn, schema):
        """Governed capability registration (Phase 5A): expose one additional
        read-only Niblit capability as an LLM tool with its OpenAI schema."""
        self._tool_map[name] = fn
        self._schemas = getattr(self, "_schemas", {})
        self._schemas[name] = schema

    def prevalidate(self, name, arguments=None):
        """Phase 5E: schema-validate a call WITHOUT dispatching it.

        Returns an error string for rejection, or None when the call would
        pass validation. Uses the exact same _validate_call rules as both the
        LLM tool loop and Command invoke - one validator, three entry points.
        """
        if not isinstance(arguments, dict):
            return "arguments must be an object"
        allowed = dict(getattr(self, "_schemas", {}))
        allowed.setdefault("runtime_status", make_runtime_status_tool())
        call = {"function": {"name": str(name or ""),
                             "arguments": json.dumps(arguments or {})}}
        try:
            self._validate_call(call, allowed)
            return None
        except ToolCallError as exc:
            return str(exc)

    def invoke(self, name, arguments=None):
        """Phase 5E: direct governed invocation of one registered capability.

        Used by the Command surface (server.py /api/commands/execute). This is
        deliberately the SAME governance path the LLM uses: identical schema
        validation (``_validate_call``) and the identical dispatch table
        (``_tool_map``). There is no second command executor.

        Returns a truthful envelope - never a fabricated success:
            {"status": "success"|"rejected"|"error",
             "result": <real tool result or None>,
             "error": <str or None>, "duration_ms": <float>}
        """
        if not isinstance(arguments, dict):
            return {"status": "rejected", "result": None,
                    "error": "arguments must be an object", "duration_ms": 0.0}
        allowed = dict(getattr(self, "_schemas", {}))
        # runtime_status is registered in _tool_map by __init__ but its schema
        # arrives via the tools argument in the LLM path; the direct path
        # needs it explicitly.
        allowed.setdefault("runtime_status", make_runtime_status_tool())
        call = {"function": {"name": str(name or ""),
                             "arguments": json.dumps(arguments or {})}}
        t0 = time.perf_counter()
        try:
            validated_name, args = self._validate_call(call, allowed)
            self._require_authorization(validated_name)
            result = self._tool_map[validated_name](**args)
            duration = round((time.perf_counter() - t0) * 1000, 1)
            return {"status": "success", "result": result,
                    "error": None, "duration_ms": duration}
        except ToolCallError as exc:
            duration = round((time.perf_counter() - t0) * 1000, 1)
            status = ("authorization_required"
                      if isinstance(exc, ToolAuthorizationError) else "rejected")
            return {"status": status, "result": None,
                    "error": str(exc), "duration_ms": duration}
        except Exception as exc:  # real failures surface as errors, never swallowed
            duration = round((time.perf_counter() - t0) * 1000, 1)
            return {"status": "error", "result": None,
                    "error": str(exc), "duration_ms": duration}

    def _validate_call(self, call, allowed_schemas):
        function = call.get("function", {})
        name = str(function.get("name", ""))
        if name not in allowed_schemas:
            raise ToolCallError(f"unknown tool: {name!r}")
        args_raw = function.get("arguments", "") or ""
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError as exc:
            raise ToolCallError(f"malformed arguments JSON for {name}: {exc}") from exc
        schema = allowed_schemas[name].get("function", {}).get("parameters", {})
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not isinstance(args, dict):
            raise ToolCallError(f"invalid arguments for {name}: must be an object")
        unknown = set(args) - set(props)
        if unknown:
            raise ToolCallError(f"invalid arguments for {name}: unknown keys {sorted(unknown)}")
        missing = required - set(args)
        if missing:
            raise ToolCallError(f"invalid arguments for {name}: missing {sorted(missing)}")
        return name, args

    @staticmethod
    def _require_authorization(name: str) -> None:
        """Apply command-surface permission metadata to direct LLM tool calls."""
        try:
            from modules.core_tool_runtime import (
                COMMAND_PERMISSION_ACTIONS,
                GOVERNED_COMMAND_METADATA,
                _permission_manager,
            )
        except Exception as exc:
            raise ToolAuthorizationError(
                "authorization policy is unavailable") from exc
        metadata = GOVERNED_COMMAND_METADATA.get(name, {})
        if not metadata.get("requires_authorization"):
            return
        action = COMMAND_PERMISSION_ACTIONS.get(name, f"command.{name}")
        if action and not _permission_manager().check(action):
            raise ToolAuthorizationError(
                f"authorization required for {action!r}")

    def _cloud_chat(self, messages, model, tools=None, tool_choice=None, max_tokens=512):
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        req = urllib.request.Request(
            self.cloud_root + _CHAT_PATH,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise ToolCallError(f"cloud HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise ToolCallError(f"cloud unreachable: {exc}") from exc

    def chat(self, messages, tools=None, model="qwen2.5-coder-3b",
             tool_choice=None):
        schemas = dict(getattr(self, "_schemas", {}))
        schemas.setdefault("runtime_status", make_runtime_status_tool())
        if tools is None:
            # Registered capabilities are the default tool surface.
            tools = list(schemas.values())
            allowed = schemas
        else:
            # An explicit tool list is a capability boundary, not merely a
            # display hint. Only registered tools in that list are exposed
            # to validation and execution for this conversation.
            requested_names = [
                str(tool.get("function", {}).get("name", ""))
                for tool in tools if isinstance(tool, dict)
            ]
            requested = set(requested_names)
            unknown = requested - set(schemas)
            if unknown:
                raise ToolCallError(
                    f"unregistered tools requested: {sorted(unknown)}")
            allowed = {name: schemas[name] for name in requested}
            tools = [allowed[name] for name in requested_names]
        from modules.memory_laboratory.context import augment_messages
        working, memory_retrieval = augment_messages(
            messages, gateway=self.memory_gateway, scope=self.memory_scope)
        trace: List[Dict[str, Any]] = []
        final = ""
        last_niblit_model = None
        stopped = "loop_budget_exhausted"
        repeat_counts: Dict[str, int] = {}
        tools_disabled = False
        guard_triggered = False
        initial_tool_choice = tool_choice

        for _ in range(self.max_loop_calls):
            active_tools = None if tools_disabled else (tools or None)
            body = self._cloud_chat(
                working,
                model=model,
                tools=active_tools,
                tool_choice=None if tools_disabled else initial_tool_choice,
            )
            # A required tool choice applies only to the initial assistant
            # turn. After its observation, the model can answer normally.
            initial_tool_choice = None
            last_niblit_model = body.get("niblit_model") or last_niblit_model
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                final = message.get("content") or ""
                stopped = "repetition_guard" if guard_triggered else "final_answer"
                break
            if len(tool_calls) > MAX_TOOL_CALLS_PER_TURN:
                raise ToolCallError(
                    f"tool_calls {len(tool_calls)} exceeds MAX_TOOL_CALLS_PER_TURN ({MAX_TOOL_CALLS_PER_TURN})"
                )
            working.append({
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            })
            t0 = time.perf_counter()
            repeat_detected = False
            for call in tool_calls:
                tc_id = call.get("id") or f"call_{len(trace)}"
                try:
                    active_allowed = {} if tools_disabled else allowed
                    name, args = self._validate_call(call, active_allowed)
                    self._require_authorization(name)
                    signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                    repeat_counts[signature] = repeat_counts.get(signature, 0) + 1
                    if (repeat_counts[signature] > MAX_IDENTICAL_TOOL_CALLS
                            and not tools_disabled):
                        repeat_detected = True
                    result = self._tool_map[name](**args)
                    if isinstance(result, dict) and result.get("error"):
                        status = "error"
                        call_error = str(result["error"])
                    else:
                        status = "success"
                        call_error = None
                except ToolAuthorizationError as exc:
                    name, args = "?", {}
                    result = {"error": str(exc)}
                    status = "authorization_required"
                    call_error = str(exc)
                except ToolCallError as exc:
                    name, args = "?", {}
                    result = {"error": str(exc)}
                    status = "rejected"
                    call_error = str(exc)
                except Exception as exc:
                    name, args = "?", {}
                    result = {"error": str(exc)}
                    status = "error"
                    call_error = str(exc)
                duration_ms = (time.perf_counter() - t0) * 1000
                trace.append({
                    "tool_call_id": tc_id,
                    "tool": name,
                    "arguments": args,
                    "status": status,
                    "duration_ms": round(duration_ms, 1),
                    **({"error": call_error} if call_error else {}),
                })
                working.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": name,
                    "content": json.dumps(result, default=str),
                })

            if repeat_detected:
                # Repetition guard: an identical call was re-requested more
                # than MAX_IDENTICAL_TOOL_CALLS times. The model is stuck in a
                # loop, so remove the tool surface — the next turn MUST be a
                # text answer built from the observations already collected.
                tools_disabled = True
                guard_triggered = True
                note = ("Tool repetition detected. Do not call tools again; "
                        "answer now using the observations already collected.")
                working.append({"role": "system", "content": note})
                trace.append({
                    "tool_call_id": "loop_guard",
                    "tool": "(loop_guard)",
                    "arguments": {},
                    "status": "guard",
                    "duration_ms": 0.0,
                    "note": note,
                })

        if not final and not tools_disabled and trace:
            # Budget exhausted while still tool-calling: one forced no-tools
            # turn so the interaction ends in an answer, not silence.
            working.append({
                "role": "system",
                "content": ("Tool-call budget exhausted. Answer now from the "
                            "observations already collected; no tools available."),
            })
            try:
                body = self._cloud_chat(working, model=model, tools=None)
                last_niblit_model = body.get("niblit_model") or last_niblit_model
                choice = (body.get("choices") or [{}])[0]
                final = choice.get("message", {}).get("content") or ""
                if final:
                    stopped = "forced_final_answer"
            except ToolCallError:
                pass  # surfaced as empty text + truthful stopped, never silent

        # Source links are emitted by Core from retrieval provenance, so a small
        # model omitting citations cannot silently remove the evidence trail.
        citations = memory_retrieval.get("citations", [])
        if final and citations:
            final += "\n\nRetrieved sources:\n" + "\n".join(
                "- " + citation for citation in citations)
        return {"text": final, "trace": trace,
                "memory_retrieval": memory_retrieval,
                "niblit_model": last_niblit_model, "stopped": stopped}
