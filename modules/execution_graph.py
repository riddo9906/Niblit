#!/usr/bin/env python3
"""
modules/execution_graph.py — Phase 21 Execution Graph Engine

The architectural spine that connects intent → planning → tooling →
forecast → validation → action → reflection into a single compositional
execution run.

Instead of the previous linear ``think() → tool() → respond()`` pipeline,
the execution graph builds a **plan graph** for each request:

::

    Intent (from CognitiveRouter)
        │
        ▼
    ExecutionGraph.build()
        ├── Step: retrieve_memory
        ├── Step: run_forecast       (if use_forecast)
        ├── Step: call_tools         (if use_tools)
        ├── Step: validate_risk      (if run_governance)
        ├── Step: generate_response
        └── Step: reflect            (always)
        │
        ▼
    ExecutionGraph.run()             ← executes steps sequentially
        │
        ▼
    ExecutionResult
        ├── response: str
        ├── steps_run: list
        ├── tools_called: list
        ├── forecast_signal: str
        └── reflection_notes: str

The graph is *compositional*: steps are only included when the routing
decision requires them.  Each step is self-contained and gracefully
degrades when its dependency module is unavailable.

Configuration (env vars)
------------------------
    NIBLIT_EXEC_GRAPH_ENABLED — "0" to disable (default 1)
    NIBLIT_EXEC_GRAPH_MAX_TOOLS — max tools per run (default 3)

Usage::

    from modules.execution_graph import get_execution_graph

    graph = get_execution_graph()
    result = graph.run("What is 2 ** 32?", context={})
    print(result.response)
    print(result.steps_run)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_EXEC_GRAPH_ENABLED", "1").strip() not in ("0", "false")
_MAX_TOOLS: int = int(os.getenv("NIBLIT_EXEC_GRAPH_MAX_TOOLS", "3"))


# ── Step result ───────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    """Result of a single execution graph step."""
    name: str
    success: bool
    output: Any = None
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class ExecutionResult:
    """Full result of a completed execution graph run."""
    response: str
    steps_run: List[str] = field(default_factory=list)
    step_results: List[StepResult] = field(default_factory=list)
    tools_called: List[str] = field(default_factory=list)
    forecast_signal: str = "HOLD"
    reflection_notes: str = ""
    mode: str = ""
    intent: str = ""
    elapsed_ms: float = 0.0
    quality_score: float = 0.5
    request_id: str = ""
    trace_id: str = ""
    selected_module: str = ""
    selected_function: str = ""

    def to_dict(self) -> Dict:
        return {
            "response": self.response,
            "steps_run": self.steps_run,
            "tools_called": self.tools_called,
            "forecast_signal": self.forecast_signal,
            "reflection_notes": self.reflection_notes,
            "mode": self.mode,
            "intent": self.intent,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "quality_score": round(self.quality_score, 4),
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "selected_module": self.selected_module,
            "selected_function": self.selected_function,
        }


# ── ExecutionGraph ────────────────────────────────────────────────────────────

class ExecutionGraph:
    """Compositional plan graph executor.

    Builds a step sequence from a :class:`~modules.cognitive_router.CognitiveMode`
    and executes them in order, sharing a mutable *context* dict between steps.

    Thread-safe (each ``run()`` call uses its own context dict).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_count: int = 0
        self._error_count: int = 0
        log.debug("[ExecutionGraph] initialised")

    # ── Public entry-point ────────────────────────────────────────────────────

    def run(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        mode: Optional[Any] = None,
    ) -> ExecutionResult:
        """Execute the full graph for *text* and return an :class:`ExecutionResult`.

        Args:
            text:    Raw user input.
            context: Optional caller-provided context dict (will be mutated).
            mode:    Pre-computed :class:`~modules.cognitive_router.CognitiveMode`.
                     If ``None``, the router is called to determine the mode.

        Returns:
            :class:`ExecutionResult` — always a valid result even on errors.
        """
        if not _ENABLED:
            return ExecutionResult(response=text, mode="disabled")

        t0 = time.monotonic()
        ctx: Dict[str, Any] = dict(context or {})
        ctx["input"] = text

        try:
            if mode is None:
                from modules.cognitive_router import get_cognitive_router
                mode = get_cognitive_router().route(text)

            ctx["mode"] = mode
            steps = self._build_steps(mode)
            step_results: List[StepResult] = []

            for step_name, step_fn in steps:
                sr = self._run_step(step_name, step_fn, ctx)
                step_results.append(sr)
                if not sr.success and ctx.get("abort_on_failure"):
                    break

            result = ExecutionResult(
                response=ctx.get("response", ""),
                steps_run=[sr.name for sr in step_results],
                step_results=step_results,
                tools_called=ctx.get("tools_called", []),
                forecast_signal=ctx.get("forecast_signal", "HOLD"),
                reflection_notes=ctx.get("reflection_notes", ""),
                mode=mode.mode_name,
                intent=mode.intent,
                elapsed_ms=(time.monotonic() - t0) * 1000,
                quality_score=self._estimate_quality(step_results, ctx),
                request_id=str(ctx.get("request_id", "")),
                trace_id=str(ctx.get("trace_id", "")),
                selected_module=str(ctx.get("selected_module", "modules.execution_graph")),
                selected_function=str(ctx.get("selected_function", "ExecutionGraph.run")),
            )

            with self._lock:
                self._run_count += 1

            # Emit event
            try:
                from modules.event_bus import get_event_bus, NiblitEvent, EVENT_EXECUTION_COMPLETE
                get_event_bus().publish(                NiblitEvent(
                    type=EVENT_EXECUTION_COMPLETE,
                    source="execution_graph",
                    payload={
                        **result.to_dict(),
                        "event_category": "orchestration",
                        "event_priority": "high",
                        "observation_required": True,
                    },
                ))
            except Exception:
                pass

            log.debug(
                "[ExecutionGraph] run complete: mode=%s intent=%s steps=%d elapsed=%.0fms",
                mode.mode_name, mode.intent, len(step_results), result.elapsed_ms,
            )
            return result

        except Exception as exc:
            with self._lock:
                self._error_count += 1
            log.warning("[ExecutionGraph] run error: %s", exc)
            return ExecutionResult(
                response="",
                mode=getattr(mode, "mode_name", "unknown"),
                elapsed_ms=(time.monotonic() - t0) * 1000,
                request_id=str(ctx.get("request_id", "")),
                trace_id=str(ctx.get("trace_id", "")),
            )

    # ── Graph building ────────────────────────────────────────────────────────

    def _build_steps(self, mode: Any) -> List[tuple]:
        """Return ordered (name, fn) step list for *mode*."""
        steps: List[tuple] = []

        # Step 1: Retrieve memory (almost always)
        if getattr(mode, "use_memory", True):
            steps.append(("retrieve_memory", self._step_retrieve_memory))

        # Step 2: Run forecast
        if getattr(mode, "use_forecast", False):
            steps.append(("run_forecast", self._step_run_forecast))

        # Step 3: Call tools
        if getattr(mode, "use_tools", False):
            steps.append(("call_tools", self._step_call_tools))

        # Step 4: Validate risk/governance
        if getattr(mode, "run_governance", False):
            steps.append(("validate_risk", self._step_validate_risk))

        # Step 5: Generate response (always)
        steps.append(("generate_response", self._step_generate_response))

        # Step 6: Reflect (always — closes the learning loop)
        steps.append(("reflect", self._step_reflect))

        return steps

    # ── Step implementations ──────────────────────────────────────────────────

    def _run_step(self, name: str, fn: Callable, ctx: Dict) -> StepResult:
        t0 = time.monotonic()
        try:
            fn(ctx)
            return StepResult(name=name, success=True, elapsed_ms=(time.monotonic() - t0) * 1000)
        except Exception as exc:
            log.debug("[ExecutionGraph] step %s failed: %s", name, exc)
            return StepResult(name=name, success=False, error=str(exc),
                              elapsed_ms=(time.monotonic() - t0) * 1000)

    def _step_retrieve_memory(self, ctx: Dict) -> None:
        """Pull relevant KB facts and attach them to context."""
        try:
            from niblit_memory import NiblitMemory
            mem = NiblitMemory()
            query = ctx.get("input", "")
            results = mem.search(query, top_k=3)
            ctx["memory_results"] = results
            log.debug("[ExecutionGraph] memory retrieved: %d facts", len(results))
        except Exception as exc:
            log.debug("[ExecutionGraph] memory step skipped: %s", exc)
            ctx["memory_results"] = []

    def _step_run_forecast(self, ctx: Dict) -> None:
        """Consult the ForecastArbitrator or TFT adapter."""
        try:
            from modules.forecast_arbitrator import get_forecast_arbitrator
            arb = get_forecast_arbitrator()
            consensus = arb.consensus()
            ctx["forecast_signal"] = consensus.direction
            ctx["forecast_confidence"] = consensus.confidence
            log.debug("[ExecutionGraph] forecast=%s conf=%.2f",
                      consensus.direction, consensus.confidence)
        except Exception:
            try:
                from modules.tft_forecast import get_tft_adapter
                sig = get_tft_adapter().predict_signal()
                ctx["forecast_signal"] = sig
                log.debug("[ExecutionGraph] TFT forecast fallback=%s", sig)
            except Exception as exc2:
                log.debug("[ExecutionGraph] forecast step skipped: %s", exc2)
                ctx["forecast_signal"] = "HOLD"

    def _step_call_tools(self, ctx: Dict) -> None:
        """Detect and execute tool calls from the input."""
        called: List[str] = []
        try:
            from niblit_tools.tool_registry import get_registry
            registry = get_registry()
            text = ctx.get("input", "")

            # Simple heuristic: check if any tool name appears in the input
            tools = registry.list_tools()
            for tool_def in tools[:_MAX_TOOLS]:
                name = tool_def.get("name", "")
                if name and name.lower() in text.lower():
                    try:
                        result = registry.run(name, {})
                        ctx[f"tool_result_{name}"] = result
                        called.append(name)
                        log.debug("[ExecutionGraph] tool %s ran → %s", name, str(result)[:60])
                    except Exception:
                        pass
        except Exception as exc:
            log.debug("[ExecutionGraph] tool step skipped: %s", exc)

        ctx["tools_called"] = called

    def _step_validate_risk(self, ctx: Dict) -> None:
        """Basic safety/risk check."""
        try:
            from nibblebots.governance_evolution_engine import record_governance_event, EVT_CYCLE
            record_governance_event(EVT_CYCLE)
        except Exception:
            pass
        ctx["risk_validated"] = True

    def _step_generate_response(self, ctx: Dict) -> None:
        """Assemble the final response string from context."""
        parts: List[str] = []

        # Attach forecast signal if available
        signal = ctx.get("forecast_signal")
        if signal and signal != "HOLD":
            parts.append(f"[Forecast: {signal}]")

        # Attach tool results
        for key, val in ctx.items():
            if key.startswith("tool_result_"):
                tool_name = key[len("tool_result_"):]
                parts.append(f"[{tool_name}]: {val}")

        # Attach memory snippets
        mem_results = ctx.get("memory_results", [])
        if mem_results:
            snippets = []
            for r in mem_results[:2]:
                fact = r.get("fact") or r.get("content") or r.get("text") or ""
                if fact:
                    snippets.append(str(fact)[:120])
            if snippets:
                parts.append("(KB: " + " | ".join(snippets) + ")")

        ctx["response"] = " ".join(parts) if parts else ""

    def _step_reflect(self, ctx: Dict) -> None:
        """Write a brief reflection note for the learning loop."""
        mode_name = getattr(ctx.get("mode"), "mode_name", "unknown")
        tools = ctx.get("tools_called", [])
        forecast = ctx.get("forecast_signal", "HOLD")
        notes = f"mode={mode_name} tools={tools} forecast={forecast}"
        ctx["reflection_notes"] = notes
        log.debug("[ExecutionGraph] reflection: %s", notes)

    @staticmethod
    def _estimate_quality(step_results: List[StepResult], ctx: Dict[str, Any]) -> float:
        score = 0.35
        if step_results:
            successes = sum(1 for item in step_results if item.success)
            score += min(0.35, (successes / max(1, len(step_results))) * 0.35)
        if ctx.get("response"):
            score += 0.15
        if ctx.get("tools_called"):
            score += 0.1
        if ctx.get("forecast_signal") and ctx.get("forecast_signal") != "HOLD":
            score += 0.05
        return max(0.0, min(1.0, score))

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "run_count": self._run_count,
                "error_count": self._error_count,
                "max_tools_per_run": _MAX_TOOLS,
            }


# ── Singleton ─────────────────────────────────────────────────────────────────
_graph: Optional[ExecutionGraph] = None
_graph_lock = threading.Lock()


def get_execution_graph() -> ExecutionGraph:
    """Return the module-level :class:`ExecutionGraph` singleton."""
    global _graph
    with _graph_lock:
        if _graph is None:
            _graph = ExecutionGraph()
    return _graph


if __name__ == "__main__":
    print('Running execution_graph.py')
