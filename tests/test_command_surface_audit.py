"""Phase 5G tests: original command-surface audit and governance.

Covers the four contracts the phase depends on:

1. COMPLETENESS - every discovered ORIGINAL command (canonical registry, CLI
   vocabulary, router prefixes, governed tools) gets exactly one risk class and
   one governed status with a machine-readable reason.
2. TRADING BOUNDARY - no TRADING command is ever exposed to the LLM, and the
   TradingRuntimeManager stays the only trading authority.
3. CANONICAL IDENTITY - variant spellings resolve to one canonical id; a real
   collision is REPORTED, never silently merged or duplicated.
4. NO DUPLICATE EXECUTOR/REGISTRY - the audit layer registers and executes
   nothing, and a promoted original command dispatches the SAME handler object
   the canonical registry holds.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

import modules.command_surface_audit as audit
import modules.core_tool_runtime as ctr
from modules.command_registry import CanonicalRuntimeCapabilityRegistry
from modules.command_surface_audit import (
    GOVERNED_EXECUTABLE,
    OPERATOR_ONLY,
    READ_ONLY,
    RISK_CLASSES,
    SIDE_LOW,
    SIDE_NONE,
    SURFACE_STATUSES,
    TRADING,
    VARIANT_SPELLINGS,
    build_original_surface,
    canonical_id,
    classify_command,
    match_risk_rule,
    scan_handler,
)
from modules.core_tool_runtime import (
    ORIGINAL_READONLY_PROMOTIONS,
    execute_governed_command,
    list_governed_commands,
    list_original_command_surface,
    reset_governed_tool_loop,
    resolve_command_alias,
)
from modules.trading_read_tools import FORBIDDEN_EXECUTION_NAMES

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# helpers: a core whose registry is a REAL CanonicalRuntimeCapabilityRegistry
# ---------------------------------------------------------------------------
def make_core(*registrations, **attrs):
    """Build a core stand-in around the real registry type.

    ``registrations`` are ``(name, handler, kwargs)`` triples; a handler of
    ``None`` models a router prefix (registered vocabulary the router
    dispatches, not a callable capability).
    """
    registry = CanonicalRuntimeCapabilityRegistry()
    for name, handler, kwargs in registrations:
        registry.register(name, handler,
                          category=kwargs.pop("category", "test"), **kwargs)
    core = SimpleNamespace(command_registry=registry, db=None,
                           trading_runtime_manager=None, _tcl=None,
                           build_scanner=None, github_sync=None,
                           autonomous_engine=None)
    for key, value in attrs.items():
        setattr(core, key, value)
    return core


def _read_only(argument=""):
    return f"read-only output for {argument!r}"


def _mutating(argument=""):
    with open(os.devnull, "w"):  # a real write, to prove the scanner sees it
        pass
    return "wrote something"


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_governed_tool_loop()
    yield
    reset_governed_tool_loop()



# ---------------------------------------------------------------------------
# 1) completeness: every command is classified with a reason
# ---------------------------------------------------------------------------
def test_every_discovered_command_gets_exactly_one_classification():
    core = make_core(
        ("status", _read_only, {"category": "runtime"}),
        ("acquired data", _read_only, {"category": "knowledge"}),
        ("acquired-data", None, {"category": "router",
                                 "source_authority": "niblit_router.COMMAND_PREFIXES"}),
        ("slsa build", _mutating, {"category": "build"}),
    )
    surface = build_original_surface(core, promoted=ctr.promoted_audit_map(),
                                     project_root=PROJECT_ROOT)
    entries = surface["commands"]
    assert entries, "the audit must report at least the registered commands"
    for entry in entries:
        assert entry["governed_status"] in SURFACE_STATUSES, entry
        assert entry["risk_class"] in RISK_CLASSES, entry
        assert entry["classification_reason"], entry
        assert entry["canonical_id"] == canonical_id(entry["original_name"]), entry
    assert surface["summary"]["complete"] is True
    assert surface["summary"]["unexplained"] == []


def test_unmatched_command_defaults_to_operator_only_with_a_reason():
    entry = classify_command("a command nobody has ever seen",
                             source="CORE_REGISTRY", executable=True)
    assert entry["governed_status"] == OPERATOR_ONLY
    assert entry["llm_safe"] is False
    assert "operator review required" in entry["classification_reason"]


def test_unmatched_risk_rule_is_reported_not_defaulted_to_read_only():
    assert match_risk_rule("a command nobody has ever seen") is None
    entry = classify_command("a command nobody has ever seen",
                             source="CORE_REGISTRY", executable=True)
    assert entry["risk_class"] != READ_ONLY
    assert entry["side_effect_level"] == SIDE_NONE


# ---------------------------------------------------------------------------
# 2) trading boundary
# ---------------------------------------------------------------------------
def test_no_trading_command_is_classified_as_llm_safe():
    core = make_core(
        ("trading status", _read_only, {"category": "trading"}),
        ("trading execute", _mutating, {"category": "trading"}),
        ("place order", _mutating, {"category": "trading"}),
    )
    surface = build_original_surface(core, promoted=ctr.promoted_audit_map(),
                                     project_root=PROJECT_ROOT)
    trading = [e for e in surface["commands"] if e["risk_class"] == TRADING]
    assert len(trading) == 3, [e["original_name"] for e in surface["commands"]]
    for entry in trading:
        assert entry["llm_safe"] is False, entry
        assert entry["governed_status"] == OPERATOR_ONLY, entry
        assert entry["requires_authorization"] is True, entry


def test_no_forbidden_execution_name_is_registered_on_the_governed_loop():
    loop = ctr.build_governed_tool_loop(lambda: make_core())
    registered = set(loop.allowed_tool_names())
    for name in FORBIDDEN_EXECUTION_NAMES:
        assert name not in registered, name
    # the read-only trading read-out stays the single trading surface
    assert "trading_runtime_status" in registered
    assert {"buy", "sell", "place_order", "trading_execute"} & registered == set()


def test_promotion_table_contains_no_trading_or_mutation_command():
    forbidden = ("trade", "order", "buy", "sell", "deploy",
                 "reset", "install", "commit", "push")
    for original, spec in ORIGINAL_READONLY_PROMOTIONS.items():
        assert spec["risk_class"] == READ_ONLY, (original, spec["risk_class"])
        assert spec["side_effect_level"] in (SIDE_NONE, SIDE_LOW), original
        assert spec.get("requires_authorization", False) is False, original
        assert not any(token in original.lower()
                       for token in forbidden), original


# ---------------------------------------------------------------------------
# 3) canonical identity: variants resolve, collisions are reported
# ---------------------------------------------------------------------------
def test_variant_spellings_resolve_to_one_canonical_command():
    core = make_core(
        ("acquired data", _read_only, {"category": "knowledge"}),
        ("acquired-data", None, {"category": "router",
                                 "source_authority": "niblit_router.COMMAND_PREFIXES"}),
        ("knowledge stats", _read_only, {"category": "knowledge"}),
        ("knowledge-stats", None, {"category": "router",
                                   "source_authority": "niblit_router.COMMAND_PREFIXES"}),
    )
    surface = build_original_surface(core, promoted=ctr.promoted_audit_map(),
                                     alias_map={"acquired-data": "acquired data",
                                                "knowledge-stats": "knowledge stats"},
                                     project_root=PROJECT_ROOT)
    by_name = {e["original_name"]: e for e in surface["commands"]}
    resolved = 0
    for variant, owner_name in VARIANT_SPELLINGS.items():
        if variant not in by_name or owner_name not in by_name:
            continue
        variant_entry, owner_entry = by_name[variant], by_name[owner_name]
        assert variant_entry["canonical_id"] == owner_entry["canonical_id"]
        assert variant_entry["alias_of"] == owner_name, variant_entry
        assert variant_entry["llm_safe"] is False
        assert "no duplicate command is created" in variant_entry["classification_reason"]
        resolved += 1
    assert resolved >= 2, "the synthetic registry must exercise variant resolution"


def test_canonical_collision_is_reported_and_never_silently_merged():
    core = make_core(
        ("test one", _read_only, {"category": "test"}),
        ("test-one", _read_only, {"category": "test"}),  # same canonical_id
    )
    surface = build_original_surface(core, promoted=ctr.promoted_audit_map(),
                                     project_root=PROJECT_ROOT)
    collisions = [c for c in surface["conflicts"]
                  if c["type"] == "canonical_id_collision"]
    assert collisions and sorted(collisions[0]["commands"]) == sorted(
        ["test-one", "test one"])
    assert "merged automatically" in collisions[0]["resolution"]
    # both commands survive as distinct registered commands
    names = {e["original_name"] for e in surface["commands"]}
    assert {"test one", "test-one"} <= names


def test_every_promoted_command_has_a_unique_canonical_id():
    canonical_ids = [spec["canonical_id"]
                     for spec in ORIGINAL_READONLY_PROMOTIONS.values()]
    assert len(canonical_ids) == len(set(canonical_ids)), "duplicate canonical id"


def test_original_verbal_names_resolve_to_canonical_governed_names():
    for original, spec in ORIGINAL_READONLY_PROMOTIONS.items():
        assert resolve_command_alias(original) == spec["canonical_id"], original
    assert resolve_command_alias("sa-dashboard") == "sa_dashboard"
    assert resolve_command_alias("runtime capabilities") == "runtime_capabilities"
    assert resolve_command_alias("knowledge stats") == "knowledge_stats"
    assert resolve_command_alias("definitely not a command") == (
        "definitely not a command")



# ---------------------------------------------------------------------------
# 4) no duplicate executor / registry
# ---------------------------------------------------------------------------
def test_audit_module_registers_and_executes_nothing():
    """The audit layer has no registry, no executor and no network/subprocess
    access - it only reads source and the live core registry."""
    import ast

    with open(audit.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "ast", "logging", "os", "re", "typing"}, imported
    for forbidden in ("subprocess", "socket", "urllib", "requests"):
        assert forbidden not in imported, forbidden
    # the audit only READS the registry the core already built
    core = make_core(("status", _read_only, {"category": "runtime"}))
    before = dict(core.command_registry.commands)
    build_original_surface(core, promoted=ctr.promoted_audit_map(),
                           project_root=PROJECT_ROOT)
    assert dict(core.command_registry.commands) == before
    assert len(core.command_registry.commands) == len(before)


def test_promoted_command_dispatches_the_same_handler_object():
    calls = []

    def spy(argument=""):
        calls.append(argument)
        return "spied read output"

    core = make_core(("status", spy, {"category": "runtime",
                                      "description": "runtime status"}))
    out = execute_governed_command(lambda: core, "status", {}, "p5g-same-handler")
    assert out["status"] == "success", out
    assert calls == [""], calls
    assert out["result"]["handler"] == spy.__qualname__
    assert out["result"]["command"] == "status"
    assert out["result"]["canonical_id"] == "status"
    assert out["result"]["read_only"] is True


def test_promoted_command_is_registered_exactly_once_on_the_loop():
    core = make_core(("status", _read_only, {"category": "runtime"}))
    loop = ctr.build_governed_tool_loop(lambda: core)
    names = loop.allowed_tool_names()
    assert len(names) == len(set(names))
    assert names.count("status") == 1
    # rebuilding must not duplicate the capability either
    reset_governed_tool_loop()
    rebuilt = ctr.build_governed_tool_loop(lambda: core)
    assert rebuilt.allowed_tool_names().count("status") == 1
    assert set(rebuilt.allowed_tool_names()) == set(names)


def test_phase5f_knowledge_commands_keep_their_single_implementation():
    """Phase 5G must not shadow the Phase 5F knowledge capabilities."""
    core = make_core(
        ("status", _read_only, {"category": "runtime"}),
        ("recall", _read_only, {"category": "knowledge"}),
    )
    loop = ctr.build_governed_tool_loop(lambda: core)
    assert loop.allowed_tool_names().count("recall") == 1
    assert "acquired_data" in loop.allowed_tool_names()



# ---------------------------------------------------------------------------
# promotion evidence: read-only handlers proven by AST, not by assertion
# ---------------------------------------------------------------------------
def _niblit_core_module():
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    import niblit_core

    return niblit_core


def _resolve_real_handler(niblit_core, original):
    """Map an original command spelling onto its real niblit_core method.

    The ORIGINAL name is a human verb phrase ("sa-dashboard"); the real method
    is the handler symbol the curated evidence recorded ("NiblitCore._cmd_...").
    Both are resolved through real source, never guessed.
    """
    evidence = audit.READ_ONLY_EVIDENCE.get(original, {})
    symbol = evidence.get("handler", "")
    method = symbol.split("NiblitCore.")[-1].split(".")[0] if symbol else ""
    # ``_register_commands`` is the whole registration block, not the handler:
    # a lambda command must be verified against the LIVE registry instead.
    if method and method != "_register_commands":
        handler = getattr(niblit_core.NiblitCore, method, None)
        if handler is not None:
            return handler
    for candidate in (original, original.replace("-", "_").replace(" ", "_")):
        handler = getattr(niblit_core.NiblitCore, candidate, None)
        if handler is not None:
            return handler
    return None


def test_promoted_handlers_are_proven_read_only_by_ast_scan():
    """Every promoted ORIGINAL command that maps to a real niblit_core method is
    AST-verified: no unresolved mutation token in its own body."""
    niblit_core = _niblit_core_module()
    checked = []
    for original in ORIGINAL_READONLY_PROMOTIONS:
        handler = _resolve_real_handler(niblit_core, original)
        if handler is None:
            continue  # registry lambda: covered by the live-core test
        scan = scan_handler(handler, rel_root=PROJECT_ROOT,
                            allowlist=audit.ALLOWLISTED_MUTATION_TOKENS.get(
                                original, ()))
        assert scan.get("scanned"), (original, scan)
        assert scan["unresolved_mutation_tokens"] == [], (original, scan)
        assert scan["read_only_by_scan"] is True, original
        checked.append(original)
    assert len(checked) >= 20, f"only {len(checked)} promoted handlers verified"


def test_curated_evidence_never_claims_a_mutation_handler():
    """The curated evidence table must not list a handler that writes."""
    niblit_core = _niblit_core_module()
    for name, evidence in audit.READ_ONLY_EVIDENCE.items():
        symbol = evidence.get("handler", "")
        method = symbol.split("NiblitCore.")[-1].split(".")[0] if symbol else ""
        if not method or method == "_register_commands":
            continue  # registry lambda: verified against the live core
        handler = getattr(niblit_core.NiblitCore, method, None)
        assert handler is not None, (name, symbol)
        scan = scan_handler(handler, rel_root=PROJECT_ROOT,
                            allowlist=audit.ALLOWLISTED_MUTATION_TOKENS.get(name, ()))
        assert scan["unresolved_mutation_tokens"] == [], (name, symbol, scan)


def test_mutation_handler_is_detected_by_the_scanner():
    scan = scan_handler(_mutating, rel_root=PROJECT_ROOT)
    assert scan["mutation_tokens"], scan
    assert scan["read_only_by_scan"] is False


def test_documented_false_positive_is_reported_but_allowlisted():
    """A verified read-only symbol may be allowlisted, never hidden."""
    scanned = scan_handler(_mutating, rel_root=PROJECT_ROOT)
    allowed = scan_handler(_mutating, rel_root=PROJECT_ROOT,
                           allowlist=tuple(scanned["mutation_tokens"]))
    assert scanned["mutation_tokens"], scanned
    assert allowed["mutation_tokens"] == scanned["mutation_tokens"]
    assert allowed["allowlisted_mutation_tokens"] == scanned["mutation_tokens"]
    assert allowed["unresolved_mutation_tokens"] == []



# ---------------------------------------------------------------------------
# truthful runtime behaviour of the promoted surface
# ---------------------------------------------------------------------------
def test_promoted_command_is_unavailable_when_the_core_has_no_handler():
    """No silent success: without the canonical handler the command is
    UNAVAILABLE and is never dispatched."""
    core = make_core()  # empty registry
    registry = list_governed_commands(lambda: core)
    status = {c["name"]: c for c in registry["commands"]}["status"]
    assert status["state"] == "UNAVAILABLE"
    assert status["execution_enabled"] is False
    assert status["unavailable_reason"], status
    assert status["audit_risk_class"] == READ_ONLY
    out = execute_governed_command(lambda: core, "status", {}, "p5g-unavailable")
    assert out["status"] == "unavailable"
    assert out["result"] is None


def test_promoted_command_is_executable_when_the_core_registered_it():
    core = make_core(("status", _read_only, {"category": "runtime"}))
    registry = list_governed_commands(lambda: core)
    entry = {c["name"]: c for c in registry["commands"]}["status"]
    assert entry["state"] == "EXECUTABLE"
    assert entry["execution_enabled"] is True
    assert entry["original_name"] == "status"
    assert entry["original_source"] == "niblit_core.py"
    assert entry["source_symbol"].startswith("niblit_core.py:")


def test_promoted_command_output_is_bounded():
    core = make_core(("status", lambda argument="": "x" * 50_000,
                      {"category": "runtime"}))
    out = execute_governed_command(lambda: core, "status", {}, "p5g-bounded")
    assert out["status"] == "success"
    assert out["result"]["truncated"] is True
    assert len(out["result"]["output"]) == ctr.MAX_ORIGINAL_OUTPUT_CHARS
    assert out["result"]["chars"] == 50_000


def test_promoted_command_reports_handler_failure_truthfully():
    def boom(argument=""):
        raise RuntimeError("core exploded")

    core = make_core(("status", boom, {"category": "runtime"}))
    out = execute_governed_command(lambda: core, "status", {}, "p5g-fail")
    assert out["status"] == "success", "dispatch happened, result carries the error"
    assert "core exploded" in out["result"]["error"]
    assert out["result"]["error"].startswith("original_command_failed")


def test_promoted_command_rejects_unknown_arguments():
    core = make_core(("status", _read_only, {"category": "runtime"}))
    out = execute_governed_command(lambda: core, "status", {"evil": "x"},
                                   "p5g-args")
    assert out["status"] == "rejected"
    assert out["result"] is None


def test_governed_metadata_is_complete_for_every_promoted_command():
    for original, spec in ORIGINAL_READONLY_PROMOTIONS.items():
        meta = ctr.GOVERNED_COMMAND_METADATA[spec["canonical_id"]]
        assert meta["governed_status"] == GOVERNED_EXECUTABLE, original
        assert meta["llm_safe"] is True, original
        assert meta["phase5g_risk_class"] == READ_ONLY, original
        assert meta["requires_authorization"] is False, original
        assert meta["original_source"] == "niblit_core.py", original
        assert meta["original_name"] == original, original
        assert meta["unavailable_reason"], original


def test_low_side_effect_commands_document_their_write():
    for original, spec in ORIGINAL_READONLY_PROMOTIONS.items():
        if spec["side_effect_level"] != SIDE_LOW:
            continue
        assert spec.get("side_effect_detail"), original
        assert ctr.GOVERNED_COMMAND_METADATA[spec["canonical_id"]][
            "side_effect_detail"] == spec["side_effect_detail"]



# ---------------------------------------------------------------------------
# the reconciliation payload
# ---------------------------------------------------------------------------
def test_surface_payload_is_complete_and_serialisable():
    import json

    core = make_core(("status", _read_only, {"category": "runtime"}))
    surface = list_original_command_surface(lambda: core, project_root=PROJECT_ROOT)
    json.dumps(surface)  # the endpoint must never 500 on serialization
    assert surface["summary"]["complete"] is True
    assert surface["summary"]["unexplained"] == []
    assert surface["summary"]["total"] >= len(core.command_registry.commands)
    # every promoted command is reconciled against its governed state
    promoted_names = {e["original_name"] for e in surface["commands"]
                      if e.get("promoted")}
    assert promoted_names == set(ORIGINAL_READONLY_PROMOTIONS) & promoted_names
    for entry in surface["commands"]:
        assert entry["risk_class"] in RISK_CLASSES
        assert entry["governed_status"] in SURFACE_STATUSES
        assert entry["classification_reason"]


@pytest.mark.skipif(os.environ.get("NIBLIT_P5G_LIVE") != "1",
                    reason="set NIBLIT_P5G_LIVE=1 to bootstrap the real NiblitCore")
def test_live_core_surface_is_complete():
    from niblit_core import NiblitCore

    core = NiblitCore()
    try:
        surface = list_original_command_surface(lambda: core,
                                                project_root=PROJECT_ROOT)
        assert surface["summary"]["complete"] is True
        assert surface["summary"]["unexplained"] == []
        for entry in surface["commands"]:
            if entry.get("promoted"):
                assert entry["risk_class"] == READ_ONLY, entry
                assert entry["scan"]["unresolved_mutation_tokens"] == [], entry
            if entry["risk_class"] == TRADING:
                assert entry["llm_safe"] is False, entry
    finally:
        try:
            core.shutdown()
        except Exception:
            pass

