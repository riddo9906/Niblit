"""NIBLIT PHASE 5B — TASKS 16–19: READ-ONLY TRADING RUNTIME CAPABILITY SURFACE.

Exposes the AUTHORITATIVE trading runtime (niblit-lean-algos
TradingRuntimeManager) to the local LLM as READ-ONLY governed capabilities.

Hard rules enforced structurally in this module:
- Only read-only state access. No order/execution/cancel/leverage surface
  exists here and none may be added.
- All values come from the live runtime object. Missing/unavailable state is
  reported as "unavailable" — NEVER fabricated.
- LeanAlgoManager / Cloud lean probe remain compatibility surfaces; they are
  NOT touched or elevated here.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Capability names deliberately absent from this module and from any schema
# derived from it. Guarded by regression tests (Task 18).
FORBIDDEN_EXECUTION_NAMES = (
    "place_order", "cancel_order", "close_position", "open_position",
    "execute_strategy", "change_leverage", "allocate_capital",
    "start_live_trading", "modify_live_strategy", "bypass_risk",
    "disable_risk", "send_freqtrade_command", "run_lean_backtest_execution",
)

TRADING_STATUS_SCHEMA = {
    "type": "object",
    "name": "trading_runtime_status",
    "description": (
        "Read-only inspection of the authoritative Niblit trading runtime "
        "(TradingRuntimeManager): state, backend, execution mode, market data "
        "provider, and execution-enabled governance flag."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

TRADING_STATUS_CAPABILITY = {
    "name": "trading_runtime_status",
    "category": "Trading",
    "description": TRADING_STATUS_SCHEMA["description"],
    "risk_class": "none",
    "side_effect_level": "read_only",
    "read_only": True,
    "requires_network": False,
    "requires_confirmation": False,
}

# OpenAI function-tool shape required by LlmToolLoop's validator
# (loop reads schema["function"]["parameters"]).
TRADING_STATUS_FUNCTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "trading_runtime_status",
        "description": TRADING_STATUS_SCHEMA["description"],
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


def _state_attr(runtime: Any, names: tuple) -> Any:
    """Read the first present attribute; return 'unavailable' when absent."""
    for name in names:
        value = getattr(runtime, name, None)
        if value is not None:
            if callable(value):
                continue  # read-only surface: properties/data only, no calls
            return value
    return "unavailable"


def read_runtime_status(runtime: Any) -> Dict[str, Any]:
    """Build a structured READ-ONLY snapshot from the authoritative runtime."""
    if runtime is None:
        return {
            "available": False,
            "reason": "trading_runtime_not_initialized",
            "execution_tools_exposed": False,
        }

    status: Dict[str, Any] = {
        "available": True,
        "authority": "TradingRuntimeManager",
        "read_only": True,
        "state": _state_attr(runtime, ("state", "runtime_state")),
        "backend": _state_attr(runtime, ("backend", "backend_name")),
        "execution_mode": _state_attr(runtime, ("execution_mode", "mode")),
        "market_data_provider": _state_attr(
            runtime, ("market_data_provider", "data_provider")),
        "execution_enabled": getattr(runtime, "execution_enabled", "unavailable"),
    }
    return status


def execute_trading_runtime_status(arguments: Dict[str, Any], runtime: Optional[Any]) -> Dict[str, Any]:
    """Dispatch entry used by the governed tool loop. Never executes anything."""
    if arguments:
        raise ValueError("unexpected_arguments_for_read_only_capability")
    return read_runtime_status(runtime)


def register(loop: Any, runtime_getter: Any) -> str:
    """Register the read-only trading capability with the governed tool loop.

    Uses the loop's actual signature ``register_capability(name, fn, schema)``
    with the schema in OpenAI function-tool shape
    ``{"type": "function", "function": {"name", "description", "parameters"}}``
    so the loop's validator accepts it unchanged.
    """
    if not hasattr(loop, "register_capability"):
        raise RuntimeError("supplied loop lacks register_capability")

    def handler(**kwargs: Any) -> Dict[str, Any]:
        # The governed loop invokes handlers as fn(**arguments). The validator
        # already rejects unknown keys, so kwargs is always {} here.
        return execute_trading_runtime_status(kwargs, runtime_getter())

    loop.register_capability(
        TRADING_STATUS_CAPABILITY["name"],
        handler,
        TRADING_STATUS_FUNCTION_SCHEMA,
    )
    return TRADING_STATUS_CAPABILITY["name"]
