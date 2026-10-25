"""modules/command_surface_audit.py - Phase 5G read-only command-surface audit.

This module is an AUDIT and CLASSIFICATION layer for the ORIGINAL Niblit command
surface. It is deliberately NOT any of the following:

    * not a command executor   (nothing here dispatches a command)
    * not a command registry   (nothing here registers a command)
    * not a router             (nothing here routes text)
    * not a permission layer   (authorization stays in PermissionManager)

It only READS:

    1. the LIVE registry that NiblitCore actually built
       (``core.command_registry.commands`` - the canonical registry),
    2. the CLI vocabulary that main.py actually declares (AST, section 15 of the
       Phase 5G brief: legacy vocabulary stays usable, it is only catalogued),
    3. the handler objects registered in (1), which give a REAL implementation
       trace (module / qualname / file / line) - no filename inference.

Every discovered name therefore gets exactly one explicit classification with a
machine-readable reason, so the Command surface can never report an
"unexplained MISSING" command.

Promotion decisions (which original commands may become LLM tools) are NOT made
here: the governed tool metadata lives in ``modules/core_tool_runtime.py`` (the
Phase 5E/5F authority) and the audit reconciles against it.
"""
from __future__ import annotations

import ast
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("Niblit.CommandSurfaceAudit")

# ---------------------------------------------------------------------------
# vocabularies
# ---------------------------------------------------------------------------

#: Where a discovered command comes from.
SOURCE_CORE_REGISTRY = "CORE_REGISTRY"
SOURCE_CLI = "CLI"
SOURCE_ROUTER_PREFIX = "ROUTER_PREFIX"
SOURCE_GOVERNED_TOOL = "GOVERNED_TOOL"
SOURCES = (SOURCE_CORE_REGISTRY, SOURCE_CLI, SOURCE_ROUTER_PREFIX,
           SOURCE_GOVERNED_TOOL)

#: Phase 5E/5F state model, extended with the Phase 5G classes. Exactly one of
#: these is assigned to every discovered command (completeness contract).
GOVERNED_EXECUTABLE = "GOVERNED_EXECUTABLE"
GOVERNED_AUTH_REQUIRED = "GOVERNED_AUTH_REQUIRED"
GOVERNED_UNAVAILABLE = "GOVERNED_UNAVAILABLE"
OPERATOR_ONLY = "OPERATOR_ONLY"
INTERNAL = "INTERNAL"
DEPRECATED = "DEPRECATED"
SURFACE_STATUSES = (GOVERNED_EXECUTABLE, GOVERNED_AUTH_REQUIRED,
                    GOVERNED_UNAVAILABLE, OPERATOR_ONLY, INTERNAL, DEPRECATED)

#: Risk classes (§7 of the Phase 5G brief).
READ_ONLY = "READ_ONLY"
RESEARCH = "RESEARCH"
KNOWLEDGE_WRITE = "KNOWLEDGE_WRITE"
WORKSPACE_WRITE = "WORKSPACE_WRITE"
CODE_EXECUTION = "CODE_EXECUTION"
SYSTEM_MUTATION = "SYSTEM_MUTATION"
GITHUB_MUTATION = "GITHUB_MUTATION"
DEPLOYMENT = "DEPLOYMENT"
TRADING = "TRADING"
SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
INTERNAL_RISK = "INTERNAL"
RISK_CLASSES = (READ_ONLY, RESEARCH, KNOWLEDGE_WRITE, WORKSPACE_WRITE,
                CODE_EXECUTION, SYSTEM_MUTATION, GITHUB_MUTATION, DEPLOYMENT,
                TRADING, SECURITY_SENSITIVE, INTERNAL_RISK)

#: Side-effect levels (§7).
SIDE_NONE = "NONE"
SIDE_LOW = "LOW"
SIDE_MEDIUM = "MEDIUM"
SIDE_HIGH = "HIGH"
SIDE_CRITICAL = "CRITICAL"


#: Verified spelling variants of ORIGINAL commands (audit finding, §5/§14).
#: Key = variant name that is ALSO registered (as a router prefix) but only
#: re-spells an existing canonical command; value = the canonical ORIGINAL name.
#: Evidence: niblit_router.py COMMAND_PREFIXES contains both spellings while
#: the registry executes a single handler family — see _p5g_surface.json
#: "alias_of" entries produced by this module. Only the FIRST-listed spelling
#: per pair is the variant; the second is the owner the variant resolves to.
VARIANT_SPELLINGS: Dict[str, str] = {
    "acquired-data": "acquired data",
    "knowledge-stats": "knowledge stats",
    "ale-processes": "ale processes",
    "fix code": "fix-code",
    "github deep": "github-deep",
    "graph_rag": "graph-rag",
    "kb stats": "kb-stats",
    "refresh topics": "refresh-topics",
    "reload_params": "reload-params",
    "run_selfheal": "run-selfheal",
    "self enhance": "self-enhance",
}

#: Phase 5G classes are recorded per command; the 5E/5F governed metadata keeps
#: its own vocabulary (risk_class none/low/medium/high, side_effect_level
#: read_only/low/mutation/execution) for backwards compatibility.
RISK_TO_GOVERNED: Dict[str, str] = {
    READ_ONLY: "none",
    RESEARCH: "low",
    KNOWLEDGE_WRITE: "medium",
    WORKSPACE_WRITE: "medium",
    CODE_EXECUTION: "high",
    SYSTEM_MUTATION: "high",
    GITHUB_MUTATION: "high",
    DEPLOYMENT: "high",
    TRADING: "high",
    SECURITY_SENSITIVE: "high",
    INTERNAL_RISK: "none",
}


def canonical_id(name: str) -> str:
    """Deterministic canonical identity for one original command name.

    ``"knowledge stats"`` -> ``"knowledge_stats"``, ``"sa-commands"`` ->
    ``"sa_commands"``. Purely spelling normalisation - the ORIGINAL name is
    always preserved next to it, never replaced.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


#: Inverse of RISK_TO_GOVERNED: the Phase 5E/5F vocabulary -> Phase 5G classes.
#: Used when reconciling an already-governed capability (which reports the 5E
#: vocabulary) so the audit never records a class outside RISK_CLASSES.
GOVERNED_TO_RISK: Dict[str, str] = {
    "none": READ_ONLY,
    "read_only": READ_ONLY,
    "low": RESEARCH,
    "medium": WORKSPACE_WRITE,
    "high": SECURITY_SENSITIVE,
    "execution": CODE_EXECUTION,
    "mutation": SYSTEM_MUTATION,
}

#: Phase 5E/5F side-effect vocabulary -> Phase 5G levels.
GOVERNED_TO_SIDE: Dict[str, str] = {
    "read_only": SIDE_NONE,
    "none": SIDE_NONE,
    "low": SIDE_LOW,
    "medium": SIDE_MEDIUM,
    "high": SIDE_HIGH,
    "mutation": SIDE_HIGH,
    "execution": SIDE_CRITICAL,
    "critical": SIDE_CRITICAL,
}


def governed_to_risk(value: str) -> str:
    """Translate a 5E/5F risk value into a valid Phase 5G class."""
    text = str(value or "").strip().lower()
    if text in RISK_CLASSES:
        return text
    return GOVERNED_TO_RISK.get(text, INTERNAL_RISK)


def governed_to_side(value: str) -> str:
    """Translate a 5E/5F side-effect value into a valid Phase 5G level."""
    text = str(value or "").strip().lower()
    if text in (SIDE_NONE, SIDE_LOW, SIDE_MEDIUM, SIDE_HIGH, SIDE_CRITICAL):
        return text.upper()
    return GOVERNED_TO_SIDE.get(text, SIDE_LOW)


# ---------------------------------------------------------------------------
# curated READ-ONLY evidence (handler bodies read during Phase 5G-B)
# ---------------------------------------------------------------------------
# Every entry below was verified by reading the handler body in niblit_core.py
# (or the module the handler delegates to). Only handlers that read state and
# return text appear here: no KnowledgeDB write, no workspace write, no
# subprocess execution, no trading/broker access, no system mutation.
# ``promoted`` marks the commands Phase 5G also exposes on the governed loop.

READ_ONLY_EVIDENCE: Dict[str, Dict[str, Any]] = {
    "status": {"handler": "NiblitCore._cmd_status", "promoted": True,
               "evidence": "reads memory count + loop/epoch telemetry, returns text"},
    "health": {"handler": "NiblitCore._cmd_health", "promoted": True,
               "evidence": "health_check() reads component state only"},
    "metrics": {"handler": "NiblitCore._cmd_metrics", "promoted": True,
                "evidence": "reads PerformanceMetrics counters"},
    "time": {"handler": "NiblitCore._cmd_time", "promoted": True,
             "evidence": "datetime.now().strftime, pure read"},
    "coherence": {"handler": "NiblitCore._cmd_coherence", "promoted": True,
                  "evidence": "reads Temporal Coherence Layer status()"},
    "help": {"handler": "NiblitCore._cmd_help", "promoted": True,
             "evidence": "returns help_text() built from the live registry"},
    "dump": {"handler": "NiblitCore._register_commands.<lambda@2681>",
             "promoted": True,
             "evidence": "f-string over _dump_loop_count/_get_memory_count"},
    "runtime capabilities": {"handler": "NiblitCore._cmd_runtime_capabilities",
                             "promoted": True,
                             "evidence": "registry.detailed_report() snapshot"},
    "unified runtime status": {
        "handler": "NiblitCore._register_commands.<lambda@2688>",
        "promoted": True,
        "evidence": ("unified_runtime.dispatch_command read-out; bounded "
                     "telemetry state write (LOW)")},
    "retrieval status": {"handler": "NiblitCore._register_commands.<lambda@2734>",
                         "promoted": True,
                         "evidence": ("adaptive_retrieval.render_command(); bounded "
                                      "telemetry state write (LOW)")},
    "retrieval inspect": {"handler": "NiblitCore._register_commands.<lambda@2745>",
                          "promoted": True,
                          "evidence": ("adaptive_retrieval.render_command(); bounded "
                                       "telemetry state write (LOW)")},
    "hypothesis status": {"handler": "NiblitCore._register_commands.<lambda@2803>",
                          "promoted": True,
                          "evidence": ("hypothesis_engine.render_command(); bounded "
                                       "telemetry state write (LOW)")},
    "hypothesis list": {"handler": "NiblitCore._register_commands.<lambda@2803>",
                        "promoted": True,
                        "evidence": ("hypothesis_engine.render_command(); bounded "
                                     "telemetry state write (LOW)")},
    "hypothesis show": {"handler": "NiblitCore._register_commands.<lambda@2824>",
                        "promoted": True,
                        "evidence": ("hypothesis_engine.render_command(); bounded "
                                     "telemetry state write (LOW)")},
    "ale processes": {"handler": "NiblitCore._cmd_ale_process_awareness",
                      "promoted": True,
                      "evidence": "reads ALE learning stats, returns text"},
    "autonomous-learn status": {"handler": "NiblitCore._cmd_autonomous_status",
                                "promoted": True,
                                "evidence": "reads ALE get_learning_stats()"},
    "autonomous-learn code-status": {
        "handler": "NiblitCore._cmd_autonomous_code_status",
        "promoted": True,
        "evidence": "reads ALE code-literacy stats"},
    "build summary": {"handler": "NiblitCore._cmd_build_summary", "promoted": True,
                      "evidence": "build_scanner.summarize() (read-only scan)"},
    "build path": {"handler": "NiblitCore._cmd_build_path", "promoted": True,
                   "evidence": "prints configured build path + sync readiness"},
    "scan build": {"handler": "NiblitCore._cmd_scan_build", "promoted": True,
                   "evidence": "build_scanner.scan() directory listing"},
    "read build file": {"handler": "NiblitCore._cmd_read_build_file",
                        "promoted": True,
                        "evidence": "build_scanner.read_file() (bounded preview)"},
    "github status": {"handler": "NiblitCore._cmd_github_status", "promoted": True,
                      "evidence": "github_sync.status() read-only"},
    "github log": {"handler": "NiblitCore._cmd_github_log", "promoted": True,
                   "evidence": "github_sync.log(n) read-only"},
    "sa-structure": {"handler": "NiblitCore._cmd_sa_structure", "promoted": True,
                     "evidence": "structural_awareness.component_report()"},
    "sa-threads": {"handler": "NiblitCore._cmd_sa_threads", "promoted": True,
                   "evidence": "threading.enumerate() snapshot"},
    "sa-loops": {"handler": "NiblitCore._cmd_sa_loops", "promoted": True,
                 "evidence": "structural_awareness.loop_report()"},
    "sa-modules": {"handler": "NiblitCore._cmd_sa_modules", "promoted": True,
                   "evidence": "structural_awareness.module_report()"},
    "sa-dashboard": {"handler": "NiblitCore._cmd_sa_dashboard", "promoted": True,
                     "evidence": "structural_awareness.runtime_dashboard()"},
    "sa-resources": {"handler": "NiblitCore._cmd_sa_resources", "promoted": True,
                     "evidence": "structural_awareness.resource_report()"},
    # read-only, but intentionally NOT exposed to the LLM (see reason)
    "sa-commands": {"handler": "NiblitCore._cmd_sa_commands", "promoted": False,
                    "not_promoted_reason": "duplicate view of 'runtime capabilities'"},
    "sa-flow": {"handler": "NiblitCore._cmd_sa_flow", "promoted": False,
                "not_promoted_reason": "narrative architecture description"},
    "sa-awareness": {"handler": "NiblitCore._cmd_sa_awareness", "promoted": False,
                     "not_promoted_reason": "aggregate of other sa-* reports"},
    "sa-scripts": {"handler": "NiblitCore._cmd_sa_scripts", "promoted": False,
                   "not_promoted_reason": "repo script inventory, operator view"},
    "tree scan": {"handler": "NiblitCore._cmd_tree_scan", "promoted": False,
                  "not_promoted_reason": ("unbounded path scan; governed "
                                          "workspace_list/workspace_search "
                                          "already provide scoped reads")},
    "tree read": {"handler": "NiblitCore._cmd_tree_read", "promoted": False,
                  "not_promoted_reason": ("unbounded path read; governed "
                                          "workspace_read already provides "
                                          "scoped reads")},
    "slsa-status": {"handler": "NiblitCore._cmd_slsa_status", "promoted": False,
                    "evidence": ("_get_slsa_status() reads engine attrs only; the "
                                 "SLSA LIFECYCLE commands stay outside the LLM "
                                 "surface"),
                    "not_promoted_reason": ("SLSA lifecycle family stays outside "
                                            "the LLM surface")},
}

# ---------------------------------------------------------------------------
# risk rules for every OTHER command (ordered; first match wins)
# ---------------------------------------------------------------------------
# Tuple: (tokens, risk_class, side_effect_level, requires_authorization, note).
# A token matches when the command name IS the token or STARTS WITH token + " ".
# These rules never promote anything: they only classify risk/authorisation so
# the surface stays truthful. Order = severity, so families that contain
# read-only members are listed after their mutating members.

RISK_RULES: Tuple[Tuple[Tuple[str, ...], str, str, bool, str], ...] = (
    (("memory-reset", "memory reset"), SYSTEM_MUTATION, SIDE_CRITICAL, True,
     "flushes memory, caches and state files"),
    (("cmd exec",), CODE_EXECUTION, SIDE_CRITICAL, True,
     "sandboxed command execution surface"),
    (("ctrl",), SECURITY_SENSITIVE, SIDE_HIGH, True,
     "device control (sandbox exec + serial/G-code)"),
    (("run-live-test",), CODE_EXECUTION, SIDE_HIGH, True,
     "executes the interactive live command tester"),
    (("run-diagnostics",), CODE_EXECUTION, SIDE_HIGH, True,
     "executes the diagnostic suite"),
    (("autonomous-learn command-exec",), CODE_EXECUTION, SIDE_HIGH, True,
     "ALE step 14 executes diagnostic commands"),
    (("dev-agent execute", "dev-agent approve", "dev-agent rollback"),
     DEPLOYMENT, SIDE_CRITICAL, True, "dev-agent lifecycle authority"),
    (("dev-agent analyze",), CODE_EXECUTION, SIDE_HIGH, True,
     "dev-agent analysis pipeline"),
    (("dev-agent",), CODE_EXECUTION, SIDE_MEDIUM, True, "dev-agent family"),
    (("github push", "github pull", "github deep", "github-deep"),
     GITHUB_MUTATION, SIDE_HIGH, True, "github repository mutation"),
    (("orchestrate audit",), WORKSPACE_WRITE, SIDE_MEDIUM, True,
     "runs the repo auditor, which writes its JSON report"),
    (("autonomous-learn",), SYSTEM_MUTATION, SIDE_HIGH, True,
     "mutates ALE loop / topic / queue state"),
    (("self-implement", "idea-implement", "self-idea", "generate code"),
     CODE_EXECUTION, SIDE_HIGH, True, "generates and implements code"),
    (("self-heal", "heal", "fix code", "fix-code"), CODE_EXECUTION, SIDE_HIGH,
     True, "self-repair / code mutation"),
    (("deploy improvements", "import improvements", "hot reload improvements",
      "orchestrate pipeline"), DEPLOYMENT, SIDE_HIGH, True,
     "deployment / hot-reload of workspace code"),
    (("lean", "trading", "trading study", "trading swing", "stream"),
     TRADING, SIDE_HIGH, True, "trading family - outside LLM authority"),
    (("market intelligence",), TRADING, SIDE_LOW, True,
     "market cognition telemetry (trading family, not promoted)"),
    (("tree write", "tree edit"), WORKSPACE_WRITE, SIDE_HIGH, True,
     "writes / edits files in the tree"),
    (("file",), WORKSPACE_WRITE, SIDE_MEDIUM, True, "universal file manager"),
    (("deploy-bridge", "deployment-bridge"), SYSTEM_MUTATION, SIDE_MEDIUM, True,
     "cross-deployment checkpoint write"),
    (("pdf.",), KNOWLEDGE_WRITE, SIDE_MEDIUM, True, "PDF ingest writes knowledge"),
    (("document-cognition",), KNOWLEDGE_WRITE, SIDE_MEDIUM, True,
     "PDF ingest + governed memory persistence"),
    (("reflect", "self-teach", "learn about", "remember", "ideas"),
     KNOWLEDGE_WRITE, SIDE_MEDIUM, True, "writes knowledge / memory entries"),
    (("self-research",), RESEARCH, SIDE_MEDIUM, True,
     "web research that stores results in the KB"),
    (("self-enhance", "self enhance", "self-monitor", "evolve", "evolution",
      "evo"), CODE_EXECUTION, SIDE_HIGH, True, "self-evolution / enhancement"),
    (("kb prune", "kb consolidate", "kb contradict", "kb think"),
     KNOWLEDGE_WRITE, SIDE_MEDIUM, True, "knowledge-base mutation"),
    (("start_slsa", "stop_slsa", "restart_slsa", "slsa"), SYSTEM_MUTATION,
     SIDE_HIGH, True, "SLSA lifecycle mutation"),
    (("runtime provider", "runtime model switch", "backend", "local-model",
      "toggle-llm", "llm-provider", "llm-train", "qwen", "llama3", "brain"),
     SYSTEM_MUTATION, SIDE_MEDIUM, True, "switches runtime provider/model state"),
    (("runtime infer", "runtime"), RESEARCH, SIDE_LOW, True,
     "provider-routed inference"),
    (("security", "sec-membrane", "cyber", "cyber-membrane", "cybermembrane",
      "membrane", "mesh", "autonomous-network"), SECURITY_SENSITIVE, SIDE_HIGH,
     True, "defensive security / network membrane"),
    (("bios", "krnl", "kernel", "os", "platform", "hardware", "net"),
     SYSTEM_MUTATION, SIDE_HIGH, True, "platform / kernel / device integration"),
    (("env-state", "envstate", "env-adapter", "envadapter", "niblit-runtime",
      "nrt"), SYSTEM_MUTATION, SIDE_MEDIUM, True, "runtime environment state"),
    (("module-autonomy", "autonomy"), SYSTEM_MUTATION, SIDE_MEDIUM, True,
     "module autonomy framework"),
    (("civilization", "civ"), SYSTEM_MUTATION, SIDE_MEDIUM, True,
     "multi-agent civilization framework"),
    (("curriculum", "study", "learn", "chat", "chat-memory"),
     KNOWLEDGE_WRITE, SIDE_MEDIUM, True, "learning / conversation memory write"),
    (("reload_params", "reload-params"), SYSTEM_MUTATION, SIDE_LOW, True,
     "reloads runtime parameters"),
    (("run_selfheal", "run-selfheal"), CODE_EXECUTION, SIDE_HIGH, True,
     "explicit self-heal trigger"),
    (("refresh-topics", "refresh topics"), SYSTEM_MUTATION, SIDE_LOW, True,
     "refreshes the research topic rotation"),
    (("hybrid-search",), RESEARCH, SIDE_LOW, False, "vector search (read)"),
    (("retrieval",), RESEARCH, SIDE_LOW, False,
     "adaptive-retrieval cognition telemetry (read-out)"),
    (("search", "summary", "think about", "knowledge", "builds", "trainer"),
     RESEARCH, SIDE_LOW, False, "internet research surface"),
    (("graph-rag", "graph_rag"), RESEARCH, SIDE_LOW, False, "Graph-RAG read"),
    (("exit", "quit", "shutdown"), SYSTEM_MUTATION, SIDE_LOW, True,
     "terminates the running runtime"),
    (("dump on", "dump off", "dump visible", "dump invisible", "dump"),
     SYSTEM_MUTATION, SIDE_LOW, True, "toggles dump visibility"),
    (("my", "sa-", "struct", "dashboard", "loops", "loop", "routing",
      "confidence", "tools", "commands", "version", "new commands",
      "show new commands", "what's new", "whats new", "new features",
      "recent commands", "added commands", "notifications"), READ_ONLY,
     SIDE_NONE, False, "read-only inventory / discoverability vocabulary"),
    (("game", "kb health", "ale", "read build", "improvement-status",
      "show improvements", "auto-research", "agentic", "enterprise",
      "multimodal", "collab", "reasoning", "docs"), READ_ONLY, SIDE_NONE,
     False, "read-only reporting vocabulary"),
    (("kb stats", "kb-stats", "status_slsa", "my", "sa-"), READ_ONLY, SIDE_NONE,
     False, "read-only knowledge / structural inventory"),
    (("market", "market data"), TRADING, SIDE_LOW, True,
     "market data / cognition family"),
    (("hf-status",), READ_ONLY, SIDE_NONE, False, "HuggingFace bridge status"),
    (("hf-enable", "hf-disable", "hf-ask", "toggle-llm", "llm-provider",
      "chat-memory", "llm-train", "memory dump"), SYSTEM_MUTATION, SIDE_MEDIUM,
     True, "provider / memory state mutation"),
    (("github",), GITHUB_MUTATION, SIDE_MEDIUM, True,
     "github router family (status/log are classified read-only separately)"),
)


#: Trading EXECUTION phrases. The prefix rules above only match when the name
#: STARTS with a family token ("trading ...", "lean ..."), so a verb-first
#: spelling such as "place order" or "close position" would slip past. These
#: phrases are matched on WORD boundaries anywhere in the name, which is why
#: they are listed separately and checked first. They mirror the execution
#: surface the trading authority already forbids
#: (modules/trading_read_tools.FORBIDDEN_EXECUTION_NAMES) and are classified
#: before any read-only rule, so a trading command can never be LLM-exposed.
TRADING_EXECUTION_PHRASES: Tuple[str, ...] = (
    "place order", "cancel order", "close position", "open position",
    "execute strategy", "change leverage", "allocate capital",
    "start live trading", "modify live strategy", "bypass risk",
    "disable risk", "send freqtrade", "lean backtest execution",
    "buy", "sell", "trade now", "execute trade", "submit order",
)


def match_trading_phrase(name: str) -> Optional[Dict[str, Any]]:
    """Classify a trading EXECUTION phrase found anywhere in ``name``.

    Word-boundary matching keeps unrelated names out (e.g. "market data" is a
    read, "place order" is not), and the result is a TRADING rule identical to
    the prefix rule's contract.
    """
    lowered = f" {str(name or '').strip().lower()} "
    for phrase in TRADING_EXECUTION_PHRASES:
        if f" {phrase} " in lowered or lowered.strip() == phrase:
            return {"risk_class": TRADING, "side_effect_level": SIDE_HIGH,
                    "requires_authorization": True,
                    "reason": (f"trading-execution phrase[{phrase}]: trading "
                               "execution authority stays with "
                               "TradingRuntimeManager, never the LLM")}
    return None


def match_risk_rule(name: str) -> Optional[Dict[str, Any]]:
    """Return the first matching risk rule for ``name`` (or None).

    A token matches when the name IS the token, STARTS WITH ``token + " "`` or,
    for dotted tokens such as ``"pdf."``, when the name starts with the token
    itself. Matching is textual and deterministic - never inferred.
    """
    lowered = str(name or "").strip().lower()
    phrase = match_trading_phrase(lowered)
    if phrase is not None:
        return phrase
    for tokens, risk, side, auth, note in RISK_RULES:
        for token in tokens:
            if (lowered == token or lowered.startswith(token + " ")
                    or (token.endswith(".") and lowered.startswith(token))):
                return {"risk_class": risk, "side_effect_level": side,
                        "requires_authorization": auth,
                        "reason": f"rule[{token}]: {note}"}
    return None


# ---------------------------------------------------------------------------
# handler side-effect scan (AST evidence, bounded to the handler itself)
# ---------------------------------------------------------------------------

#: Tokens that indicate a REAL mutation when they appear in a called symbol.
MUTATION_TOKENS: Tuple[str, ...] = (
    "write", "unlink", "remove", "rmtree", "mkdir", "makedirs", "rename",
    "truncate", "push", "commit", "deploy", "reload", "execute", "popen",
    "subprocess", "system", "eval", "save", "store", "insert", "delete",
    "drop", "reset", "restart", "train", "ingest", "prune", "consolidate",
    "upload", "download", "install", "kill", "send_order", "place_order",
    "toggle", "start_", "stop_", "_stop", "_start", "_save",
)

#: ``open`` is only a mutation in a WRITE mode. A plain ``open(path).read()`` is
#: a read, so the mode argument decides - checked structurally, not by name.
WRITE_MODES: Tuple[str, ...] = ("w", "a", "x", "r+", "w+", "a+", "x+")


def _write_mode_open(node) -> bool:
    """True when a Call is ``open(..., mode)`` with a writing mode."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return False
    if node.func.id != "open":
        return False
    for argument in list(node.args) + [kw.value for kw in node.keywords
                                      if kw.arg == "mode"]:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            if argument.value.strip().lower() in WRITE_MODES:
                return True
    return False


#: Documented FALSE POSITIVES of MUTATION_TOKENS: the token only appears inside
#: a symbol that READS state. Every entry was verified by reading the handler
#: body; the scan still reports the RAW hit, so nothing is silently ignored.
#: Key = command name, value = tokens that are reads, not mutations.
ALLOWLISTED_MUTATION_TOKENS: Dict[str, Tuple[str, ...]] = {
    # _cmd_build_path only formats paths; get_deploy_path() is a getter.
    "build path": ("deploy",),
}

#: Commands whose curated evidence documents a bounded telemetry state write.
LOW_SIDE_EFFECT_COMMANDS: Dict[str, str] = {
    "unified runtime status": ("NiblitUnifiedRuntime.dispatch_command persists the "
                               "unified-runtime telemetry state file (bounded)"),
    "retrieval status": ("NiblitUnifiedRuntime.dispatch_command persists the "
                         "unified-runtime telemetry state file (bounded)"),
    "retrieval inspect": ("NiblitUnifiedRuntime.dispatch_command persists the "
                          "unified-runtime telemetry state file (bounded)"),
    "hypothesis status": ("NiblitUnifiedRuntime.dispatch_command persists the "
                          "unified-runtime telemetry state file (bounded)"),
    "hypothesis list": ("NiblitUnifiedRuntime.dispatch_command persists the "
                        "unified-runtime telemetry state file (bounded)"),
    "hypothesis show": ("NiblitUnifiedRuntime.dispatch_command persists the "
                        "unified-runtime telemetry state file (bounded)"),
}

_AST_CACHE: Dict[str, Any] = {}


def _file_ast(path: str):
    if path not in _AST_CACHE:
        try:
            with open(path, encoding="utf-8") as fh:
                _AST_CACHE[path] = ast.parse(fh.read())
        except Exception as exc:  # source unavailable -> no scan evidence
            _AST_CACHE[path] = exc
    return _AST_CACHE[path]


def _call_tokens(node) -> List[str]:
    """Render every called symbol inside ``node`` as a dotted token list."""
    tokens: List[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        parts: List[str] = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        if parts:
            tokens.append(".".join(reversed(parts)))
    return tokens


def scan_handler(handler: Any, *, rel_root: Optional[str] = None,
                 follow_depth: int = 1,
                 allowlist: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """Read-only AST scan of a registered handler's own body.

    Returns the called symbols, any mutation tokens found, and a boolean
    ``read_only_by_scan``. This is evidence for the audit - it never executes
    the handler and never decides promotion on its own.
    """
    code = getattr(handler, "__code__", None)
    if code is None:
        return {"scanned": False, "reason": "handler has no python code object"}
    path = getattr(code, "co_filename", "") or ""
    line = getattr(code, "co_firstlineno", None)
    tree = _file_ast(path) if path else None
    if tree is None or isinstance(tree, Exception) or line is None:
        return {"scanned": False, "reason": "source not parseable"}

    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            node_line = getattr(node, "lineno", None)
            if node_line is not None and abs(node_line - line) <= 1:
                if target is None or getattr(node, "lineno", 0) >= getattr(
                        target, "lineno", 0):
                    target = node
    if target is None:
        return {"scanned": False, "reason": "handler body not found by line"}

    tokens = _call_tokens(target)
    delegates: List[str] = []
    if follow_depth > 0 and isinstance(target, ast.Lambda):
        # A lambda forwarder (e.g. self._dispatch_unified_runtime_command) is
        # followed one level so the audit records the real delegate name.
        for token in tokens:
            delegates.append(token)
    lowered = " ".join(tokens).lower()
    hits = sorted({t for t in MUTATION_TOKENS if t in lowered})
    if any(_write_mode_open(sub) for sub in ast.walk(target)):
        hits.append("open_write")
        hits = sorted(set(hits))
    allowlist = tuple(allowlist or ())
    unresolved = [t for t in hits if t not in allowlist]
    return {
        "scanned": True,
        "file": (os.path.relpath(path, rel_root).replace("\\", "/")
                 if rel_root else path),
        "line": line,
        "calls": tokens[:40],
        "delegates": delegates,
        # raw hits: every mutation-shaped token the body contains
        "mutation_tokens": hits,
        # allowlisted hits: verified read-only symbols (never hidden)
        "allowlisted_mutation_tokens": [t for t in hits if t in allowlist],
        # the only tokens that actually block promotion
        "unresolved_mutation_tokens": unresolved,
        "read_only_by_scan": not unresolved,
    }


# ---------------------------------------------------------------------------
# main.py CLI vocabulary (AST; canonical identities stay consistent, §15)
# ---------------------------------------------------------------------------

_CLI_CACHE: Dict[str, Any] = {}


def _cli_symbol(node) -> Optional[str]:
    if isinstance(node, ast.Attribute):
        return f"{_cli_symbol(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Lambda):
        return f"<lambda@{getattr(node, 'lineno', '?')}>"
    return None


def read_cli_vocabulary(project_root: str) -> Dict[str, Any]:
    """Read the CLI vocabulary main.py actually declares (cached per process)."""
    if project_root in _CLI_CACHE:
        return _CLI_CACHE[project_root]
    path = os.path.join(project_root, "main.py")
    result: Dict[str, Any] = {"source_file": "main.py",
                              "legacy_commands": [], "direct_commands": {},
                              "cli_registry_sync": [], "parse_error": ""}
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except Exception as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"
        _CLI_CACHE[project_root] = result
        return result

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and target.id == "LEGACY_COMMANDS"
                        and isinstance(node.value, ast.List)):
                    result["legacy_commands"] = [
                        elt.value for elt in node.value.elts
                        if isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)]
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "run_shell":
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Name)
                                and target.id == "DIRECT_COMMANDS"
                                and isinstance(node.value, ast.Dict)):
                            for key, value in zip(node.value.keys, node.value.values):
                                if (isinstance(key, ast.Constant)
                                        and isinstance(key.value, str)):
                                    result["direct_commands"][key.value] = {
                                        "handler_symbol": _cli_symbol(value),
                                        "source_symbol": (f"main.py:{node.lineno}:"
                                                          "run_shell.DIRECT_COMMANDS")}
        if (isinstance(fn, ast.FunctionDef)
                and fn.name == "_sync_cli_capability_registry"):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "register"):
                    args = [a for a in node.args]
                    name = (args[0].value if args and isinstance(args[0], ast.Constant)
                            else None)
                    if not isinstance(name, str):
                        continue
                    kw = {k.arg: k.value for k in node.keywords if k.arg}
                    aliases = []
                    if isinstance(kw.get("aliases"), ast.Tuple):
                        aliases = [e.value for e in kw["aliases"].elts
                                   if isinstance(e, ast.Constant)
                                   and isinstance(e.value, str)]
                    result["cli_registry_sync"].append({
                        "name": name,
                        "handler_symbol": (_cli_symbol(args[1])
                                           if len(args) > 1 else None),
                        "description": (args[2].value
                                        if len(args) > 2
                                        and isinstance(args[2], ast.Constant) else ""),
                        "aliases": aliases,
                        "source_symbol": ("main.py:_sync_cli_capability_registry:"
                                          f"register({name!r})"),
                    })
    _CLI_CACHE[project_root] = result
    return result


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def classify_command(
    name: str,
    *,
    source: str,
    executable: bool,
    category: str = "uncategorized",
    description: str = "",
    aliases: Tuple[str, ...] = (),
    deprecated: bool = False,
    deprecation_message: str = "",
    handler_trace: Optional[Dict[str, Any]] = None,
    source_symbol: str = "",
    dispatch_path: str = "",
    governed_state: str = "",
    promoted: Optional[Dict[str, Any]] = None,
    unavailable_reason: str = "",
    scan: Optional[Dict[str, Any]] = None,
    arguments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Assign exactly one Phase 5G status + risk class to one command.

    Returns a self-describing record: every field is derived from the live
    registry, from the curated evidence tables above, or from the AST scan -
    nothing is invented and nothing is left unexplained.
    """
    risk = INTERNAL_RISK
    side = SIDE_NONE
    requires_auth = False
    status = OPERATOR_ONLY
    reason = ""

    # ── 1) risk / side-effect / authorization (independent of exposure) ─────
    if promoted is not None:
        risk = promoted.get("risk_class", READ_ONLY)
        side = promoted.get("side_effect_level", SIDE_NONE)
        requires_auth = bool(promoted.get("requires_authorization", False))
    elif name in READ_ONLY_EVIDENCE:
        risk = READ_ONLY
        if name in LOW_SIDE_EFFECT_COMMANDS:
            side = SIDE_LOW
    else:
        rule = match_risk_rule(name)
        if rule is None:
            rule = {"risk_class": INTERNAL_RISK, "side_effect_level": SIDE_NONE,
                    "requires_authorization": False,
                    "reason": ("no explicit rule matched: operator review required "
                               "before any LLM exposure (Phase 5G default)")}
        risk = rule["risk_class"]
        side = rule["side_effect_level"]
        requires_auth = bool(rule["requires_authorization"])
        reason = f"not exposed to the LLM: {rule['reason']}"

    # ── 2) status (exposure) ────────────────────────────────────────────────
    if deprecated:
        status = DEPRECATED
        reason = (f"the canonical registry marks this command deprecated: "
                  f"{deprecation_message or 'no message'}")
    elif promoted is not None:
        if not executable:
            status = GOVERNED_UNAVAILABLE
            unavailable_reason = (unavailable_reason
                                 or "registered handler is not callable")
            reason = unavailable_reason
        elif governed_state == "EXECUTABLE":
            status = GOVERNED_EXECUTABLE
            reason = promoted.get("evidence", "")
        elif governed_state == "REQUIRES_AUTHORIZATION":
            status = GOVERNED_AUTH_REQUIRED
            reason = "governed capability requires an explicit operator grant"
        elif governed_state == "UNAVAILABLE":
            status = GOVERNED_UNAVAILABLE
            reason = unavailable_reason or "required runtime dependency not available"
        else:
            status = GOVERNED_UNAVAILABLE
            reason = "governed state could not be evaluated for this command"
    elif not executable and source == SOURCE_ROUTER_PREFIX:
        status = OPERATOR_ONLY
        reason = (f"router prefix family dispatched by NiblitRouter.handle_command; "
                  f"not a governed LLM capability (risk_class={risk})")
    elif not executable and source == SOURCE_CLI:
        status = INTERNAL
        reason = ("CLI shell vocabulary owned by main.run_shell; not a runtime "
                  "capability registry entry")
    elif not executable:
        status = GOVERNED_UNAVAILABLE
        reason = "registered without a callable handler"
        unavailable_reason = unavailable_reason or reason
    elif name in READ_ONLY_EVIDENCE:
        status = OPERATOR_ONLY
        reason = ("verified read-only original command, NOT promoted: "
                  + str(READ_ONLY_EVIDENCE[name].get("not_promoted_reason")
                        or "operator surface retained"))
    else:
        status = OPERATOR_ONLY
        if not reason:
            reason = ("not exposed to the LLM: no explicit rule matched: operator "
                      "review required before any LLM exposure")

    return {
        "source": source,
        "source_symbol": source_symbol,
        "canonical_id": (promoted or {}).get("canonical_id") or canonical_id(name),
        "original_name": name,
        "aliases": list(aliases),
        "description": description,
        "category": category,
        "handler": (handler_trace or {}).get("qualname"),
        "handler_module": (handler_trace or {}).get("module"),
        "handler_symbol": (handler_trace or {}).get("entry_point"),
        "arguments": list(arguments if arguments is not None
                          else (["text"] if executable else [])),
        "schema_if_known": (promoted or {}).get("schema"),
        "side_effect_level": side,
        "side_effect_detail": (LOW_SIDE_EFFECT_COMMANDS.get(name, "")
                              or (promoted or {}).get("side_effect_detail", "")),
        "risk_class": risk,
        "requires_authorization": requires_auth,
        "llm_safe": status == GOVERNED_EXECUTABLE,
        "governed_status": status,
        "implementation_exists": bool(executable),
        "actual_dispatch_path": dispatch_path,
        "classification_reason": reason,
        "unavailable_reason": unavailable_reason,
        "scan": scan or {},
    }


# ---------------------------------------------------------------------------
# original-surface aggregation
# ---------------------------------------------------------------------------

def _trace(handler: Any, project_root: str) -> Dict[str, Any]:
    code = getattr(handler, "__code__", None)
    path = getattr(code, "co_filename", "") or ""
    rel = ""
    if path:
        try:
            rel = os.path.relpath(path, project_root).replace("\\", "/")
        except ValueError:
            rel = path
    return {
        "callable": callable(handler),
        "module": getattr(handler, "__module__", None),
        "qualname": getattr(handler, "__qualname__", None),
        "file": rel,
        "line": getattr(code, "co_firstlineno", None),
        "entry_point": (f"{rel}:{getattr(code, 'co_firstlineno', '?')}"
                        if rel else None),
    }


def build_original_surface(
    core: Any,
    *,
    promoted: Optional[Dict[str, Dict[str, Any]]] = None,
    governed_states: Optional[Dict[str, str]] = None,
    governed_unavailable_reasons: Optional[Dict[str, str]] = None,
    governed_commands: Optional[List[Dict[str, Any]]] = None,
    alias_map: Optional[Dict[str, str]] = None,
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconcile the COMPLETE original command surface with the governed one.

    ``core`` is the live NiblitCore (or None). Everything is read from the
    registry the core actually built - no command is invented, and every
    discovered name gets an explicit classification (see ``classify_command``).
    """
    promoted = promoted or {}
    governed_states = governed_states or {}
    governed_unavailable_reasons = governed_unavailable_reasons or {}
    alias_map = alias_map or {}
    project_root = project_root or os.getcwd()
    registry = getattr(core, "command_registry", None)
    registered = dict(getattr(registry, "commands", {}) or {})

    entries: List[Dict[str, Any]] = []
    seen: set = set()
    conflicts: List[Dict[str, str]] = []
    canonical_owner: Dict[str, List[str]] = {}

    for name in sorted(registered):
        meta = registered[name]
        seen.add(name)
        handler = getattr(meta, "handler", None)
        executable = callable(handler)
        authority = str(getattr(meta, "source_authority", "") or "")
        source = (SOURCE_ROUTER_PREFIX if "niblit_router" in authority.lower()
                  else SOURCE_CORE_REGISTRY)
        trace = _trace(handler, project_root) if executable else None
        scan = (scan_handler(handler, rel_root=project_root,
                             allowlist=ALLOWLISTED_MUTATION_TOKENS.get(name, ()))
                if executable else {})
        rule = promoted.get(name)
        governed_state = ""
        if rule is not None:
            governed_state = str(governed_states.get(rule["canonical_id"], ""))
        entry = classify_command(
            name,
            source=source,
            executable=executable,
            category=str(getattr(meta, "category", "") or "uncategorized"),
            description=str(getattr(meta, "description", "") or ""),
            aliases=tuple(getattr(meta, "aliases", ()) or ()),
            deprecated=bool(getattr(meta, "deprecated", False)),
            deprecation_message=str(getattr(meta, "deprecation_message", "") or ""),
            handler_trace=trace,
            source_symbol=str(getattr(meta, "source_authority", "") or ""),
            dispatch_path=("NiblitCore.handle -> CanonicalRuntimeCapabilityRegistry.execute"
                           " -> registered handler"
                           if executable else
                           "NiblitCore.handle -> NiblitRouter.process/handle_command"
                           " (prefix routing vocabulary)"),
            governed_state=governed_state,
            promoted=rule,
            unavailable_reason=governed_unavailable_reasons.get(
                rule["canonical_id"], "") if rule else "",
            scan=scan,
            arguments=([k for k in (rule or {}).get("schema", {})
                        .get("function", {}).get("parameters", {})
                        .get("properties", {})] if rule else None),
        )
        entry["promoted"] = rule is not None
        entry["governed_tool"] = (rule or {}).get("canonical_id")
        entry["evidence"] = (rule or {}).get("evidence", "")
        entries.append(entry)
        canonical_owner.setdefault(entry["canonical_id"], []).append(name)

    # ── CLI vocabulary (main.py, §15: canonical identities stay consistent) ──
    cli = read_cli_vocabulary(project_root)
    cli_names: List[str] = list(cli.get("legacy_commands", []))
    cli_names += sorted(cli.get("direct_commands", {}))
    cli_names += [c["name"] for c in cli.get("cli_registry_sync", [])]
    cli_symbols: Dict[str, str] = {c["name"]: c.get("source_symbol", "")
                                   for c in cli.get("cli_registry_sync", [])}
    for key, value in cli.get("direct_commands", {}).items():
        cli_symbols[key] = value.get("source_symbol", "")
    for name in sorted({n for n in cli_names if n}):
        if name in seen:
            continue
        seen.add(name)
        entries.append(classify_command(
            name,
            source=SOURCE_CLI,
            executable=False,
            category="cli",
            description="CLI shell vocabulary declared by main.py",
            source_symbol=cli_symbols.get(name, "main.py"),
            dispatch_path="main.run_shell (CLI surface only)",
            aliases=tuple(a for c in cli.get("cli_registry_sync", [])
                          if c["name"] == name for a in c.get("aliases", [])),
        ))

    by_canonical: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        canonical_owner.setdefault(entry["canonical_id"], []).append(
            entry["original_name"])
        by_canonical.setdefault(entry["canonical_id"], entry)

    # ── variant spellings (§5/§14: verified re-spellings, not duplicates) ────
    # VARIANT_SPELLINGS is the audited table: the FIRST-listed spelling of each
    # pair is a pure alias of its owner (both appear in the router vocabulary,
    # one handler family executes them). Marking the variant keeps the surface
    # complete (every discovered name still listed) while the canonical-id
    # collision check below skips the resolved variant — a RESOLVED variant is
    # evidence of reconciliation, not a conflict.
    for entry in entries:
        owner_name = VARIANT_SPELLINGS.get(entry["original_name"])
        if owner_name is None:
            continue
        owner = next((candidate for candidate in entries
                      if candidate["original_name"] == owner_name), None)
        if owner is None:
            continue
        entry["alias_of"] = owner["original_name"]
        entry["governed_tool"] = owner.get("governed_tool") or owner["canonical_id"]
        entry["classification_reason"] = (
            f"router prefix spelling variant of the canonical command "
            f"{owner['original_name']!r}; resolved through the canonical identity "
            f"(no duplicate command is created)")
        if owner.get("promoted"):
            alias_map.setdefault(entry["original_name"], owner["governed_tool"])
    for entry in entries:
        if entry["source"] != SOURCE_ROUTER_PREFIX or entry["implementation_exists"]:
            continue
        owner = by_canonical.get(entry["canonical_id"])
        if owner is None or owner["original_name"] == entry["original_name"]:
            continue
        if not owner["implementation_exists"]:
            continue
        entry["alias_of"] = owner["original_name"]
        entry["governed_tool"] = owner.get("governed_tool") or owner["canonical_id"]
        entry["classification_reason"] = (
            f"router prefix spelling variant of the canonical command "
            f"{owner['original_name']!r}; resolved through the canonical identity "
            f"(no duplicate command is created)")
        if owner.get("promoted"):
            alias_map.setdefault(entry["original_name"], owner["governed_tool"])

    # ── declared aliases from the canonical registry ────────────────────────
    for entry in entries:
        for alias in list(entry["aliases"]):
            target = alias_map.get(alias)
            if target and target != (entry.get("governed_tool")
                                     or entry["canonical_id"]):
                conflicts.append({
                    "type": "alias_conflict",
                    "alias": alias,
                    "claimed_by": target,
                    "also_declared_by": entry["original_name"],
                    "resolution": ("first verified canonical identity wins; the "
                                   "conflicting declaration is NOT auto-resolved"),
                })
            elif alias in registered and alias != entry["original_name"]:
                conflicts.append({
                    "type": "alias_shadows_registration",
                    "alias": alias,
                    "declared_by": entry["original_name"],
                    "resolution": ("both names stay registered; alias resolution is "
                                   "not applied to registered names"),
                })

    # ── canonical identity collisions ───────────────────────────────────────
    # A promoted original and the governed tool that implements it are the SAME
    # command seen at two layers, not a collision. A RESOLVED spelling variant
    # (alias_of set above) is likewise reconciliation evidence, not a
    # collision. A real collision is two DISTINCT, UNRESOLVED commands (neither
    # one governing the other) that normalise to the same canonical id.
    for canonical, names in sorted(canonical_owner.items()):
        distinct = sorted(set(names))
        if len(distinct) < 2:
            continue
        owners = [e for e in entries if e["original_name"] in distinct]
        governing = {e["governed_tool"] for e in owners
                     if e.get("governed_tool")
                     and e["governed_tool"] in distinct}
        non_alias = [e["original_name"] for e in owners
                     if not e.get("alias_of")
                     and e["original_name"] not in governing
                     and not (e["source"] == SOURCE_GOVERNED_TOOL
                              and e["original_name"] == e["canonical_id"]
                              and any(o["governed_tool"] == e["original_name"]
                                      for o in owners))]
        if len(non_alias) > 1:
            conflicts.append({
                "type": "canonical_id_collision",
                "canonical_id": canonical,
                "commands": non_alias,
                "resolution": ("kept as distinct registered commands; no governed "
                               "identity is merged automatically"),
            })

    # ── curated promotion targets vs the live runtime ───────────────────────
    for name in sorted(promoted):
        if name in registered:
            handler = getattr(registered[name], "handler", None)
            code = getattr(handler, "__code__", None)
            expected = str(promoted[name].get("handler_symbol", ""))
            if (not expected or code is None or expected.endswith(
                    f":{getattr(code, 'co_firstlineno', '?')}")):
                continue
            conflicts.append({
                "type": "handler_trace_advisory",
                "command": name,
                "curated": expected,
                "live_line": getattr(code, "co_firstlineno", None),
                "resolution": ("the LIVE trace is authoritative; the curated note "
                               "is documentation only"),
            })
        else:
            conflicts.append({
                "type": "promotion_target_not_registered",
                "command": name,
                "resolution": "reported as GOVERNED_UNAVAILABLE in this runtime",
            })

    # ── governed-only capabilities (not part of the original vocabulary) ────
    for command in (governed_commands or []):
        name = command.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        state = str(command.get("state", ""))
        entries.append(classify_command(
            name,
            source=SOURCE_GOVERNED_TOOL,
            executable=bool(command.get("execution_enabled")
                            or state in ("EXECUTABLE", "REQUIRES_AUTHORIZATION")),
            category=str(command.get("category", "governed")),
            description=str(command.get("description", "")),
            aliases=tuple(command.get("aliases", ()) or ()),
            governed_state=state,
            promoted={
                "canonical_id": name,
                # The governed registry speaks the Phase 5E/5F vocabulary
                # (none/low/medium/high); translate it into a Phase 5G class
                # instead of leaking an invalid one into the audit.
                "risk_class": governed_to_risk(
                    str(command.get("audit_risk_class")
                        or command.get("risk_class", ""))),
                "side_effect_level": governed_to_side(
                    str(command.get("audit_side_effect_level")
                        or command.get("side_effect_level", ""))),
                "requires_authorization": bool(command.get("requires_authorization")),
                "evidence": (command.get("evidence")
                             or "governed Phase 5E/5F/5G capability registered on "
                                "the governed tool loop"),
                "side_effect_detail": str(command.get("side_effect_detail", "")),
                "schema": {"type": "function",
                           "function": {"name": name,
                                        "description": command.get("description", ""),
                                        "parameters": command.get("input_schema", {})}},
            },
            unavailable_reason=("required runtime dependency not available"
                                if state == "UNAVAILABLE" else ""),
            dispatch_path=("UI/LLM -> core_tool_runtime.execute_governed_command -> "
                           "LlmToolLoop.invoke -> registered capability"),
        ))

    # ── summary + completeness contract (§19) ───────────────────────────────
    status_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    risk_counts: Dict[str, int] = {}
    unexplained: List[str] = []
    for entry in entries:
        status_counts[entry["governed_status"]] = (
            status_counts.get(entry["governed_status"], 0) + 1)
        source_counts[entry["source"]] = source_counts.get(entry["source"], 0) + 1
        risk_counts[entry["risk_class"]] = risk_counts.get(entry["risk_class"], 0) + 1
        if (entry["governed_status"] not in SURFACE_STATUSES
                or not entry["classification_reason"]):
            unexplained.append(entry["original_name"])
    return {
        "source": "modules/command_surface_audit.py",
        "basis": ("live core.command_registry + main.py AST vocabulary + "
                  "source-verified read-only evidence + AST handler scan"),
        "commands": entries,
        "aliases": alias_map,
        "conflicts": conflicts,
        "summary": {
            "total": len(entries),
            "registered_in_core": len(registered),
            "by_status": dict(sorted(status_counts.items())),
            "by_source": dict(sorted(source_counts.items())),
            "by_risk_class": dict(sorted(risk_counts.items())),
            "governed_exposed": sorted(
                e["original_name"] for e in entries if e.get("promoted")),
            "unexplained": unexplained,
            "complete": not unexplained,
        },
        "cli_vocabulary": {
            "legacy_commands": cli.get("legacy_commands", []),
            "direct_commands": sorted(cli.get("direct_commands", {})),
            "cli_registry_sync": [c["name"] for c in cli.get("cli_registry_sync", [])],
            "parse_error": cli.get("parse_error", ""),
        },
    }
