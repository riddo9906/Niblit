#!/usr/bin/env python3
"""
nibblebot-aios-architecture  —  Nibblebot that introspects the Niblit codebase,
maps every module to an AI-OS layer, and opens a GitHub Issue with a complete
architecture proposal for "Niblit AI OS Complete".

The bot **never** commits or pushes code.  It **only** creates / updates GitHub
Issues with its architecture proposals, labelled ``nibblebot-aios``.

Phases:
    1. Introspect  — scan the local checkout for modules, languages, tests, CI.
    2. Map         — assign each module to an AIOS layer (Kernel, HAL, Memory,
                     Intelligence, Learning, Network, Application, Security).
    3. Propose     — generate architecture doc with ASCII diagram, mapping
                     table, gap analysis, hardware matrix, growth pipeline.
    4. Publish     — create (or update) a GitHub Issue with the proposal.

Usage (local testing)::

    GITHUB_TOKEN=ghp_... python nibblebots/aios_architecture_bot.py

Environment variables:
    GITHUB_TOKEN        GitHub token with ``repo`` + ``issues`` scope.
    GITHUB_REPOSITORY   owner/repo  (auto-set in GitHub Actions).
    AIOS_DRY_RUN        Set to ``"true"`` to print the issue body instead
                        of creating it on GitHub.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-AIOS-Arch/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
DRY_RUN = os.environ.get("AIOS_DRY_RUN", "").lower() == "true"
ISSUE_LABEL = "nibblebot-aios"
ISSUE_TITLE_PREFIX = "\U0001f3d7\ufe0f Nibblebot AIOS Architecture Proposal"

# Directories to skip during introspection
SKIP_DIRS = {
    "__pycache__", ".git", ".github", "node_modules", ".build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "venv", ".venv",
}

# ---------------------------------------------------------------------------
# AIOS layer definitions — order matters for the diagram
# ---------------------------------------------------------------------------
LAYER_DEFS: List[Tuple[str, str, str]] = [
    ("Application",   "APP", "User-facing interfaces, commands, routing"),
    ("Intelligence",  "INT", "AI reasoning, LLMs, research, brain"),
    ("Learning",      "LRN", "Continuous improvement, curriculum, ALE"),
    ("Memory",        "MEM", "Persistent memory, vector store, knowledge DB"),
    ("Network",       "NET", "Distributed mesh, inter-device comms"),
    ("Security",      "SEC", "Auth, SLSA, encryption, permissions"),
    ("Kernel",        "KRN", "Core runtime, process mgmt, resources"),
    ("HAL",           "HAL", "Hardware abstraction — Swift, TS, Rust nodes"),
]

# Keyword → layer mapping used by the classifier
_LAYER_KEYWORDS: Dict[str, List[str]] = {
    "Kernel": [
        "runtime", "kernel", "bootloader", "bios", "firmware",
        "orchestrator", "task_queue", "event_bus", "lifecycle",
        "module_loader", "workspace_init", "platform_bootstrap",
        "circuit_breaker", "resilience", "dependency_injection",
        "safe_loader", "runtime_manager",
    ],
    "HAL": [
        "device_control", "device_manager", "device_mesh",
        "hardware_scanner", "termux", "env_adapter", "os_integration",
        "terminal_tools", "binary_tools",
    ],
    "Memory": [
        "memory", "vector_store", "knowledge_db", "knowledge_engine",
        "fused_memory", "sqlite", "storage", "db", "cache",
        "llm_chat_memory", "knowledge_digest", "knowledge_filter",
        "knowledge_synthesizer", "ingestion",
    ],
    "Intelligence": [
        "brain", "hf_brain", "llm", "openai", "anthropic",
        "reasoning", "prediction", "intent_parser", "reflect",
        "metacognition", "multimodal", "researcher", "idea_generator",
        "code_generator", "code_compiler", "code_error_fixer",
        "hf_adapter", "llm_adapter", "llm_controller", "llm_module",
        "software_studier", "trading_brain",
    ],
    "Learning": [
        "learning", "ale", "curriculum", "self_researcher",
        "self_teacher", "self_improvement", "self_implementer",
        "self_idea", "evolve", "adaptive", "collaborative_learner",
        "parallel_learner", "parallel_learning", "graded_curriculum",
        "autonomous_learning", "llm_training",
    ],
    "Network": [
        "network", "distributed", "mesh", "net", "api_gateway",
        "connection_pool", "realtime_stream", "internet_manager",
        "autonomous_network",
    ],
    "Security": [
        "security", "membrane", "guard", "slsa", "permission",
        "antifraud", "auth", "encryption", "slice_guard",
    ],
    "Application": [
        "router", "command", "dashboard", "control_panel", "voice",
        "game_engine", "niblit_personality", "notification",
        "kivy", "server", "app", "api",
    ],
}


# ---------------------------------------------------------------------------
# GitHub API helpers  (same pattern as improvement_bot.py)
# ---------------------------------------------------------------------------

def gh_get(path: str) -> Any:
    """GET from GitHub REST API v3."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  \u26a0 API error: {path} \u2192 {exc}", file=sys.stderr)
        return None


def gh_post(path: str, body: Dict[str, Any]) -> Any:
    """POST to GitHub REST API v3."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    data = json.dumps(body).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  \u26a0 API POST error: {path} \u2192 {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 1. Introspect the Niblit codebase
# ---------------------------------------------------------------------------

def _read_first_docstring(filepath: Path) -> str:
    """Return the module-level docstring (first triple-quoted string) or
    the first comment line, truncated to 120 chars."""
    try:
        text = filepath.read_text(errors="replace")[:4096]
    except OSError:
        return ""
    # Try triple-quoted docstring
    match = re.search(r'"""(.*?)"""', text, re.DOTALL)
    if not match:
        match = re.search(r"'''(.*?)'''", text, re.DOTALL)
    if match:
        doc = match.group(1).strip().split("\n")[0]
        return doc[:120]
    # Fallback: first comment
    for line in text.splitlines()[:5]:
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            return stripped.lstrip("# ")[:120]
    return ""


def introspect_codebase() -> Dict[str, Any]:
    """Scan the local Niblit checkout and collect structural information.

    Returns a dict with keys:
        py_modules   — list of dicts {path, name, docstring}
        directories  — list of top-level directories
        languages    — dict mapping language → file count
        test_files   — list of test file paths
        ci_workflows — list of workflow file names
        deploy_nodes — list of sub-dirs under nodes/
        config_files — list of config/infra file paths
        total_py_lines — total Python LOC
    """
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    if not root.is_dir():
        root = Path(".").resolve()

    py_modules: List[Dict[str, str]] = []
    test_files: List[str] = []
    config_files: List[str] = []
    languages: Dict[str, int] = {}
    total_py_lines = 0

    lang_map = {
        ".py": "Python", ".swift": "Swift", ".ts": "TypeScript",
        ".js": "JavaScript", ".rs": "Rust", ".go": "Go",
        ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML",
        ".json": "JSON", ".md": "Markdown",
    }

    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))

        # Track language
        lang = lang_map.get(p.suffix)
        if lang:
            languages[lang] = languages.get(lang, 0) + 1

        # Python specifics
        if p.suffix == ".py":
            try:
                total_py_lines += sum(1 for _ in p.open(errors="replace"))
            except OSError:
                pass
            doc = _read_first_docstring(p)
            py_modules.append({"path": rel, "name": p.stem, "docstring": doc})
            if p.name.startswith("test_"):
                test_files.append(rel)

        # Config files
        if p.name in (
            "Dockerfile", "fly.toml", "vercel.json", "render.yaml",
            "requirements.txt", "requirements-dev.txt", "requirements-pipeline.txt",
            "Cargo.toml", "Package.swift", "package.json", "tsconfig.json",
            "pyproject.toml", "setup.py", "buildozer.spec", "Procfile",
            "runtime.txt",
        ):
            config_files.append(rel)

    # Top-level directories
    directories = sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and d.name not in SKIP_DIRS
    )

    # CI workflows
    ci_dir = root / ".github" / "workflows"
    ci_workflows: List[str] = []
    if ci_dir.is_dir():
        ci_workflows = sorted(f.name for f in ci_dir.iterdir() if f.is_file())

    # Deployment nodes
    nodes_dir = root / "nodes"
    deploy_nodes: List[str] = []
    if nodes_dir.is_dir():
        deploy_nodes = sorted(
            d.name for d in nodes_dir.iterdir() if d.is_dir()
        )

    return {
        "py_modules": py_modules,
        "directories": directories,
        "languages": languages,
        "test_files": test_files,
        "ci_workflows": ci_workflows,
        "deploy_nodes": deploy_nodes,
        "config_files": config_files,
        "total_py_lines": total_py_lines,
    }


# ---------------------------------------------------------------------------
# 2. Map modules → AIOS layers
# ---------------------------------------------------------------------------

def classify_module(name: str, path: str, docstring: str) -> str:
    """Classify a single module into an AIOS layer.

    Uses keyword matching against the module name, path, and docstring.
    Returns the layer name (e.g. "Kernel", "Memory").
    """
    combined = f"{name} {path} {docstring}".lower()
    scores: Dict[str, int] = {layer: 0 for layer, _, _ in LAYER_DEFS}

    for layer, keywords in _LAYER_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                scores[layer] += 1

    best_layer = max(scores, key=lambda k: scores[k])
    if scores[best_layer] == 0:
        return "Application"  # default bucket
    return best_layer


def map_modules_to_layers(
    modules: List[Dict[str, str]],
) -> Dict[str, List[Dict[str, str]]]:
    """Assign every Python module to an AIOS layer.

    Returns a dict  layer_name → list of module dicts (path, name, docstring).
    """
    mapping: Dict[str, List[Dict[str, str]]] = {
        layer: [] for layer, _, _ in LAYER_DEFS
    }
    for mod in modules:
        layer = classify_module(mod["name"], mod["path"], mod["docstring"])
        mapping[layer].append(mod)
    return mapping


# ---------------------------------------------------------------------------
# 3. Generate architecture proposal
# ---------------------------------------------------------------------------

def _ascii_diagram() -> str:
    """Return an ASCII art system diagram of the AIOS layers."""
    width = 64
    border = "+" + "-" * (width - 2) + "+"
    lines: List[str] = []
    lines.append("```")
    lines.append(f"{'NIBLIT AI OS COMPLETE':^{width}}")
    lines.append(f"{'Architecture Overview':^{width}}")
    lines.append("")
    lines.append(border)
    lines.append(f"|{'APPLICATION LAYER (APP)':^{width - 2}}|")
    lines.append(f"|{'Router · Commands · Dashboard · Voice · API':^{width - 2}}|")
    lines.append(border)
    lines.append(f"|{'INTELLIGENCE LAYER (INT)':^{width - 2}}|")
    lines.append(f"|{'Brain · LLM Adapters · Reasoning · Research':^{width - 2}}|")
    lines.append(border)
    lines.append(f"|{'LEARNING ENGINE (LRN)':^{width - 2}}|")
    lines.append(f"|{'ALE · Curriculum · Self-Researcher · Evolve':^{width - 2}}|")
    lines.append(border)
    lines.append(f"|{'  MEMORY SUBSYSTEM (MEM)  |  NETWORK LAYER (NET)  ':^{width - 2}}|")
    lines.append(f"|{'  VectorStore · KnowledgeDB |  DistributedMesh · P2P ':^{width - 2}}|")
    lines.append(border)
    lines.append(f"|{'SECURITY LAYER (SEC)':^{width - 2}}|")
    lines.append(f"|{'SLSA · Membrane · Permissions · Guard':^{width - 2}}|")
    lines.append(border)
    lines.append(f"|{'KERNEL LAYER (KRN)':^{width - 2}}|")
    lines.append(f"|{'Runtime · EventBus · TaskQueue · Lifecycle':^{width - 2}}|")
    lines.append(border)
    lines.append(f"|{'HARDWARE ABSTRACTION LAYER (HAL)':^{width - 2}}|")
    lines.append(f"|{'Swift/iOS  ·  TypeScript/Web  ·  Rust/Embedded':^{width - 2}}|")
    lines.append(border)
    lines.append("```")
    return "\n".join(lines)


def _mapping_table(
    layer_map: Dict[str, List[Dict[str, str]]],
) -> str:
    """Render a Markdown table mapping modules to layers."""
    lines: List[str] = []
    lines.append("| Layer | Code | Module | Purpose |")
    lines.append("|-------|------|--------|---------|")

    for layer_name, code, _ in LAYER_DEFS:
        modules = layer_map.get(layer_name, [])
        if not modules:
            lines.append(f"| {layer_name} | {code} | *(none found)* | — |")
            continue
        for i, mod in enumerate(sorted(modules, key=lambda m: m["name"])):
            display_layer = layer_name if i == 0 else ""
            display_code = code if i == 0 else ""
            doc = mod["docstring"][:60] or "—"
            lines.append(
                f"| {display_layer} | {display_code} "
                f"| `{mod['path']}` | {doc} |"
            )
    return "\n".join(lines)


def _gap_analysis(
    layer_map: Dict[str, List[Dict[str, str]]],
    deploy_nodes: List[str],
) -> str:
    """Identify missing components needed for a complete AIOS."""
    gaps: List[Dict[str, str]] = []

    # Kernel gaps
    kernel_names = {m["name"] for m in layer_map.get("Kernel", [])}
    if "niblit_runtime" not in kernel_names and "runtime_manager" not in kernel_names:
        gaps.append({
            "layer": "Kernel",
            "component": "Unified Runtime Manager",
            "description": (
                "A central process/coroutine scheduler that manages all AIOS "
                "subsystems, handles graceful startup/shutdown, and exposes "
                "a health-check API."
            ),
        })
    if not any("process" in m["name"] for m in layer_map.get("Kernel", [])):
        gaps.append({
            "layer": "Kernel",
            "component": "Process Isolation / Sandboxing",
            "description": (
                "Each AIOS service should run in an isolated context with "
                "resource limits to prevent a runaway agent from consuming "
                "all memory or CPU."
            ),
        })

    # HAL gaps
    expected_nodes = {"swift", "typescript", "rust"}
    present_nodes = {n.lower() for n in deploy_nodes}
    missing_nodes = expected_nodes - present_nodes
    if missing_nodes:
        gaps.append({
            "layer": "HAL",
            "component": f"Node stubs: {', '.join(sorted(missing_nodes))}",
            "description": (
                "Missing hardware-node implementations. Each node should "
                "expose a common FFI/API so the kernel can dispatch tasks "
                "to the appropriate device."
            ),
        })
    if not any("driver" in m["name"] for m in layer_map.get("HAL", [])):
        gaps.append({
            "layer": "HAL",
            "component": "Driver Registry",
            "description": (
                "A pluggable driver registry that auto-discovers available "
                "hardware (GPU, NPU, microcontroller) and loads the right "
                "adapter at boot time."
            ),
        })

    # Memory gaps
    mem_names = {m["name"] for m in layer_map.get("Memory", [])}
    if "fused_memory" not in mem_names and "fused_memory_primary" not in mem_names:
        gaps.append({
            "layer": "Memory",
            "component": "Unified Memory Fabric",
            "description": (
                "A single API that transparently routes reads/writes across "
                "SQLite, vector store, and knowledge DB backends."
            ),
        })

    # Network gaps
    net_names = {m["name"] for m in layer_map.get("Network", [])}
    if not any("sync" in n or "replicat" in n for n in net_names):
        gaps.append({
            "layer": "Network",
            "component": "State Replication / CRDT Sync",
            "description": (
                "For multi-device AIOS, memory and config changes must "
                "replicate across nodes via CRDTs or an event-sourced log."
            ),
        })

    # Security gaps
    sec_names = {m["name"] for m in layer_map.get("Security", [])}
    if not any("encrypt" in n for n in sec_names):
        gaps.append({
            "layer": "Security",
            "component": "At-rest & In-transit Encryption",
            "description": (
                "All inter-node communication and local knowledge stores "
                "should be encrypted (TLS for transit, AES/ChaCha for rest)."
            ),
        })

    # Learning gaps
    lrn_names = {m["name"] for m in layer_map.get("Learning", [])}
    if not any("benchmark" in n or "eval" in n for n in lrn_names):
        gaps.append({
            "layer": "Learning",
            "component": "Automated Benchmark Suite",
            "description": (
                "A self-evaluation harness that measures reasoning quality, "
                "latency, and resource usage after each learning cycle."
            ),
        })

    # Format
    if not gaps:
        return "*No critical gaps detected — impressive!*"

    lines: List[str] = []
    lines.append("| # | Layer | Missing Component | Description |")
    lines.append("|---|-------|-------------------|-------------|")
    for i, g in enumerate(gaps, 1):
        desc = g["description"][:100]
        lines.append(
            f"| {i} | {g['layer']} | **{g['component']}** | {desc} |"
        )
    return "\n".join(lines)


def _hardware_matrix(deploy_nodes: List[str]) -> str:
    """Generate a hardware compatibility matrix."""
    platforms = [
        ("Linux / x86_64", "Python", "Full", "Primary dev & CI target"),
        ("macOS / arm64", "Python + Swift", "Full", "Desktop + iOS bridge"),
        ("iOS / arm64", "Swift node", "Partial", "Mobile via Swift Package"),
        ("Web / WASM", "TypeScript node", "Partial", "Browser-based UI"),
        ("Embedded / ARM", "Rust node", "Minimal", "Edge / IoT devices"),
        ("Android / ARM", "Python (Kivy)", "Partial", "Via Buildozer"),
        ("Fly.io / Cloud", "Docker", "Full", "Production deployment"),
        ("Render / Cloud", "Docker", "Full", "Alternative cloud host"),
    ]
    present = {n.lower() for n in deploy_nodes}

    lines: List[str] = []
    lines.append("| Platform | Runtime | Coverage | Status | Notes |")
    lines.append("|----------|---------|----------|--------|-------|")
    for plat, runtime, coverage, notes in platforms:
        key = runtime.split()[0].lower()
        if key in present or key == "python" or key == "docker":
            status = "\u2705 Available"
        else:
            status = "\u26a0\ufe0f Planned"
        lines.append(
            f"| {plat} | {runtime} | {coverage} | {status} | {notes} |"
        )
    return "\n".join(lines)


def _growth_pipeline() -> str:
    """Describe the autonomous growth / improvement pipeline."""
    return """```
\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
\u2502  AUTONOMOUS GROWTH PIPELINE                               \u2502
\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2524
\u2502                                                           \u2502
\u2502  1. OBSERVE   \u2500\u2500  Self-monitor + metrics collection        \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u25bc                                                    \u2502
\u2502  2. ANALYSE   \u2500\u2500  Gap analyzer + metacognition              \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u25bc                                                    \u2502
\u2502  3. RESEARCH  \u2500\u2500  GitHub deep research + software studier  \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u25bc                                                    \u2502
\u2502  4. PLAN      \u2500\u2500  Idea generator + self-improvement orch.  \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u25bc                                                    \u2502
\u2502  5. IMPLEMENT \u2500\u2500  Self-implementer + code generator        \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u25bc                                                    \u2502
\u2502  6. TEST      \u2500\u2500  Automated tests + CI pipeline            \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u25bc                                                    \u2502
\u2502  7. DEPLOY    \u2500\u2500  HAL dispatches to target nodes           \u2502
\u2502       \u2502                                                    \u2502
\u2502       \u2514\u2500\u2500\u2500\u2500\u2500\u2500 (loop back to OBSERVE) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
\u2502                                                           \u2502
\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
```"""


def _interlayer_comms() -> str:
    """Describe the inter-layer communication design."""
    return (
        "All layers communicate through the **Kernel Event Bus** — a "
        "publish/subscribe system already prototyped in `core/event_bus.py`.\n\n"
        "```\n"
        "  APP \u2500\u2500\u2510                 \u250c\u2500\u2500 INT\n"
        "       \u2502   \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510   \u2502\n"
        "  LRN \u2500\u2500\u2524   \u2502 EVENT BUS \u2502   \u251c\u2500\u2500 MEM\n"
        "       \u2502   \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518   \u2502\n"
        "  NET \u2500\u2500\u2524       \u2502 \u2502       \u251c\u2500\u2500 SEC\n"
        "       \u2502       \u2502 \u2502       \u2502\n"
        "  HAL \u2500\u2500\u2518       KRN       \u2514\u2500\u2500 (external)\n"
        "```\n\n"
        "**Message format (proposed):**\n\n"
        "```json\n"
        "{\n"
        '  "source_layer": "LRN",\n'
        '  "target_layer": "MEM",\n'
        '  "event_type":   "knowledge.store",\n'
        '  "payload":      { "key": "...", "value": "..." },\n'
        '  "timestamp":    "2025-01-01T00:00:00Z",\n'
        '  "trace_id":     "uuid-v4"\n'
        "}\n"
        "```\n\n"
        "**Key design decisions:**\n"
        "- Async-first: all cross-layer calls are non-blocking.\n"
        "- Each layer registers handlers with the Event Bus at boot time.\n"
        "- The Kernel guarantees at-least-once delivery within a node.\n"
        "- Cross-node delivery is handled by the Network layer (mesh protocol)."
    )


def generate_proposal(
    codebase: Dict[str, Any],
    layer_map: Dict[str, List[Dict[str, str]]],
) -> str:
    """Assemble the full architecture proposal as a Markdown document."""
    date_str = datetime.date.today().isoformat()
    total_modules = sum(len(v) for v in layer_map.values())
    layer_counts = {
        layer: len(mods) for layer, mods in layer_map.items()
    }

    lines: List[str] = []

    # Header
    lines.append("## \U0001f3d7\ufe0f Niblit AI OS Complete — Architecture Proposal\n")
    lines.append(
        "This proposal was **automatically generated** by "
        "[nibblebot-aios-architecture]"
        "(https://github.com/riddo9906/Niblit/blob/main/nibblebots/"
        "aios_architecture_bot.py) "
        f"on **{date_str}** by introspecting the live Niblit codebase.\n"
    )

    # Quick stats
    lines.append("### \U0001f4ca Codebase Snapshot\n")
    lines.append(f"- **Python modules:** {len(codebase['py_modules'])}")
    lines.append(f"- **Total Python LOC:** {codebase['total_py_lines']:,}")
    lines.append(
        f"- **Languages:** "
        f"{', '.join(f'{k} ({v})' for k, v in sorted(codebase['languages'].items(), key=lambda x: -x[1]))}"
    )
    lines.append(f"- **Test files:** {len(codebase['test_files'])}")
    lines.append(f"- **CI workflows:** {len(codebase['ci_workflows'])}")
    lines.append(
        f"- **Deployment nodes:** {', '.join(codebase['deploy_nodes']) or 'none'}"
    )
    lines.append(
        f"- **Top-level dirs:** {', '.join(codebase['directories'][:15])}"
    )
    lines.append("")

    # ASCII diagram
    lines.append("---\n### \U0001f5fa\ufe0f System Architecture Diagram\n")
    lines.append(_ascii_diagram())
    lines.append("")

    # Module mapping table
    lines.append("---\n### \U0001f4cb Module-to-Layer Mapping\n")
    lines.append(
        f"*{total_modules} modules classified across "
        f"{len([l for l, c in layer_counts.items() if c > 0])} layers.*\n"
    )
    for layer_name, code, desc in LAYER_DEFS:
        count = layer_counts.get(layer_name, 0)
        lines.append(f"- **{layer_name}** ({code}): {count} modules — {desc}")
    lines.append("")
    lines.append(
        "<details>\n<summary>\U0001f50d Click to expand full mapping table</summary>\n"
    )
    lines.append(_mapping_table(layer_map))
    lines.append("\n</details>\n")

    # Gap analysis
    lines.append("---\n### \U0001f6a7 Gap Analysis — Missing Components\n")
    lines.append(_gap_analysis(layer_map, codebase["deploy_nodes"]))
    lines.append("")

    # Hardware matrix
    lines.append("---\n### \U0001f4bb Hardware Compatibility Matrix\n")
    lines.append(_hardware_matrix(codebase["deploy_nodes"]))
    lines.append("")

    # Growth pipeline
    lines.append("---\n### \U0001f331 Autonomous Growth Pipeline\n")
    lines.append(
        "The AIOS continuously improves itself through a seven-stage loop:\n"
    )
    lines.append(_growth_pipeline())
    lines.append("")

    # Inter-layer comms
    lines.append("---\n### \U0001f4e1 Inter-Layer Communication Design\n")
    lines.append(_interlayer_comms())
    lines.append("")

    # Next steps
    lines.append("---\n### \u27a1\ufe0f Recommended Next Steps\n")
    lines.append("1. **Stabilise the Kernel** — ensure `core/runtime_manager.py` "
                 "and `core/event_bus.py` can boot all layers in order.")
    lines.append("2. **Unify Memory** — wire `fused_memory.py` to serve as "
                 "the single Memory-layer API for all other layers.")
    lines.append("3. **HAL Node Contracts** — define a shared protobuf / JSON "
                 "schema so Swift, TypeScript, and Rust nodes speak the same "
                 "protocol.")
    lines.append("4. **Security Audit** — add TLS between nodes and at-rest "
                 "encryption for knowledge stores.")
    lines.append("5. **Benchmark Harness** — create an automated eval suite "
                 "that runs after every learning cycle to measure improvement.")
    lines.append("6. **CI Gate** — add a GitHub Actions job that runs the full "
                 "AIOS boot sequence and layer health-checks on every PR.")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(
        "<sub>\U0001f916 Generated by "
        "[nibblebot-aios-architecture]"
        "(https://github.com/riddo9906/Niblit/tree/main/nibblebots/"
        "aios_architecture_bot.py). "
        "This bot never commits code — it only proposes architecture via "
        "GitHub Issues.</sub>"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Create / update GitHub Issue
# ---------------------------------------------------------------------------

def ensure_label_exists() -> None:
    """Create the ``nibblebot-aios`` label if it does not already exist."""
    existing = gh_get(f"/repos/{REPO}/labels/{ISSUE_LABEL}")
    if existing and "name" in existing:
        return
    gh_post(f"/repos/{REPO}/labels", {
        "name": ISSUE_LABEL,
        "color": "1d76db",
        "description": "Nibblebot AIOS architecture proposals",
    })


def find_open_issue() -> Optional[int]:
    """Return the issue number of an existing open architecture proposal."""
    data = gh_get(
        f"/repos/{REPO}/issues?labels={ISSUE_LABEL}&state=open&per_page=10"
    )
    if not data or not isinstance(data, list):
        return None
    for issue in data:
        title = issue.get("title", "")
        if "Architecture Proposal" in title:
            return issue["number"]
    return None


def create_or_update_issue(body: str) -> None:
    """Publish the architecture proposal as a GitHub Issue.

    If an open issue with the same label and title pattern exists, it is
    updated (PATCH) instead of creating a duplicate.
    """
    ensure_label_exists()
    existing = find_open_issue()

    date_str = datetime.date.today().isoformat()
    title = f"{ISSUE_TITLE_PREFIX} \u2014 {date_str}"

    if existing:
        print(f"  \U0001f4dd Updating existing issue #{existing}")
        url = f"{GITHUB_API}/repos/{REPO}/issues/{existing}"
        data = json.dumps({"body": body, "title": title}).encode()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
            "Content-Type": "application/json",
        }
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        req = Request(url, data=data, headers=headers, method="PATCH")
        try:
            with urlopen(req, timeout=30) as resp:  # noqa: S310
                result = json.loads(resp.read().decode())
                print(f"  \u2705 Updated issue #{existing}: {result.get('html_url', '')}")
        except (URLError, OSError) as exc:
            print(f"  \u26a0 Failed to update issue: {exc}", file=sys.stderr)
    else:
        print("  \U0001f4dd Creating new issue")
        result = gh_post(f"/repos/{REPO}/issues", {
            "title": title,
            "body": body,
            "labels": [ISSUE_LABEL],
        })
        if result and "html_url" in result:
            print(f"  \u2705 Created issue: {result['html_url']}")
        else:
            print("  \u26a0 Failed to create issue", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point — introspect, map, propose, publish."""
    print("\U0001f3d7\ufe0f  Nibblebot AIOS Architecture Bot starting...")
    print(f"   Repository: {REPO}")
    print(f"   Dry run:    {DRY_RUN}")
    print()

    if not TOKEN and not DRY_RUN:
        print(
            "\u26a0 GITHUB_TOKEN not set — cannot create issues.",
            file=sys.stderr,
        )

    # 1. Introspect
    print("\U0001f50d Phase 1: Introspecting codebase...")
    codebase = introspect_codebase()
    print(f"  \u2022 {len(codebase['py_modules'])} Python modules")
    print(f"  \u2022 {codebase['total_py_lines']:,} total Python LOC")
    print(f"  \u2022 Languages: {', '.join(codebase['languages'].keys())}")
    print(f"  \u2022 Deployment nodes: {codebase['deploy_nodes']}")
    print()

    # 2. Map
    print("\U0001f5fa\ufe0f  Phase 2: Mapping modules to AIOS layers...")
    layer_map = map_modules_to_layers(codebase["py_modules"])
    for layer_name, _, _ in LAYER_DEFS:
        count = len(layer_map[layer_name])
        print(f"  \u2022 {layer_name:15s} \u2192 {count} modules")
    print()

    # 3. Propose
    print("\U0001f4d0 Phase 3: Generating architecture proposal...")
    proposal_body = generate_proposal(codebase, layer_map)
    print(f"  \u2022 Proposal length: {len(proposal_body):,} chars")
    print()

    # 4. Publish
    if DRY_RUN:
        print("=" * 70)
        print("DRY RUN \u2014 Issue body:")
        print("=" * 70)
        print(proposal_body)
        return

    print("\U0001f4e4 Phase 4: Publishing to GitHub...")
    create_or_update_issue(proposal_body)
    print("\n\u2705 AIOS Architecture Bot complete!")


if __name__ == "__main__":
    main()
