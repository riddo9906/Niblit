"""modules/local_brain.py — QwenLocalBrain: Niblit's primary local LLM.

Supports three execution backends for GGUF quantized models:

* **http** — calls a running ``llama-server`` instance via its OpenAI-
  compatible HTTP API (``POST /v1/chat/completions``).  **Recommended for
  the two-session Termux/proot setup**: run ``llama-server`` natively in
  one Termux session and Niblit (in proot) in another; they communicate
  over localhost HTTP, which crosses the proot boundary cleanly.
  Start the server with::

      ~/llama.cpp/build/bin/llama-server \\
          -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \\
          --port 8080 --host 127.0.0.1 -c 2048 -t 4

  Then set ``NIBLIT_GGUF_BACKEND=http`` (or ``auto``).

* **subprocess** — calls the pre-built ``llama-cli`` binary via
  ``subprocess.run()``.  Zero Python compilation; ideal when Niblit and
  llama.cpp run in the **same** Termux session.

* **python** — ``llama-cpp-python`` (``pip install llama-cpp-python``).
  Preferred on desktop/server where RAM for compilation is available.

In ``auto`` mode (default) the order is: **http → subprocess → python**.
This ensures the crash-safe cross-session bridge is preferred on Termux.

Role in the Hybrid Brain Architecture
--------------------------------------
* **Local Brain** (always-on, zero API cost):
  - Simple reasoning, quick answers, internal thinking loops.
  - Active whenever ``toggle-llm off`` or ``NIBLIT_BRAIN_MODE=local``.
  - Serves as the primary fallback when cloud/HF is unavailable.

* **Cloud Brain** (HF / Anthropic — power mode):
  - Complex reasoning, long outputs, research synthesis.
  - Activated by ``NIBLIT_BRAIN_MODE=power`` or explicit cloud escalation.

Model loading is lazy (on first ``generate()`` call) and thread-safe.
The model is cached for the process lifetime.

Environment variables
---------------------
NIBLIT_LOCAL_MODEL          Path to a ``.gguf`` file **or** a HuggingFace
                            model id whose cache is scanned for ``.gguf``
                            files.  Default: ``~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf``
NIBLIT_GGUF_MODEL_PATH      Explicit path to a local ``.gguf`` file
                            (takes priority over NIBLIT_LOCAL_MODEL).
NIBLIT_LOCAL_MAX_NEW        Max new tokens (default: 200)
NIBLIT_GGUF_N_CTX           Context length (default: 2048)
NIBLIT_GGUF_N_THREADS       CPU threads (default: auto)
NIBLIT_GGUF_CHAT_TEMPLATE   Chat template: ``qwen`` (default / ChatML),
                            ``llama2``, ``alpaca``, or ``raw``.
NIBLIT_GGUF_STOP_TOKENS     Comma-separated stop tokens.  When empty,
                            defaults are derived from the chat template.
NIBLIT_GGUF_BACKEND         Backend: ``auto`` (default), ``http``
                            (llama-server HTTP bridge), ``subprocess``
                            (llama.cpp binary), or ``python``
                            (llama-cpp-python).
NIBLIT_LLAMA_BINARY         Path to the llama.cpp CLI binary
                            (``llama-cli`` or ``main``).  When unset,
                            common PATH entries and build locations are tried.
NIBLIT_LLAMA_SERVER_URL     Base URL of a running llama-server instance.
                            Default: ``http://127.0.0.1:8080``
NIBLIT_LLAMA_SERVER_TIMEOUT HTTP timeout in seconds for llama-server calls.
                            Default: 120
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("Niblit.LocalBrain")

# ── Configuration ─────────────────────────────────────────────────────────────
_MODEL_NAME      = os.environ.get("NIBLIT_LOCAL_MODEL", "~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf")
_GGUF_MODEL_PATH = os.environ.get("NIBLIT_GGUF_MODEL_PATH", "").strip()
_MAX_NEW_TOKENS  = int(os.environ.get("NIBLIT_LOCAL_MAX_NEW", "200"))
_GGUF_N_CTX      = int(os.environ.get("NIBLIT_GGUF_N_CTX", "2048"))
_GGUF_N_THREADS_STR = os.environ.get("NIBLIT_GGUF_N_THREADS", "").strip()
_GGUF_N_THREADS  = int(_GGUF_N_THREADS_STR) if _GGUF_N_THREADS_STR.isdigit() else None

# Backend selector: 'auto' | 'http' | 'subprocess' | 'python'
# Default is 'http': llama-server loads the model once and keeps it in RAM;
# each Niblit call is a lightweight HTTP request.  The subprocess backend
# reloads the model from disk on every call (CPU/RAM heavy) and should only
# be used when llama-server is not running.
_GGUF_BACKEND = os.environ.get("NIBLIT_GGUF_BACKEND", "http").strip().lower()

# Path to the llama.cpp CLI binary (llama-cli / main).
# When empty, common locations are searched automatically.
_LLAMA_BINARY = os.environ.get("NIBLIT_LLAMA_BINARY", "").strip()

# llama-server HTTP bridge configuration.
# NIBLIT_LLAMA_SERVER_URL — base URL of a running llama-server instance.
# NIBLIT_LLAMA_SERVER_TIMEOUT — per-request timeout in seconds.
_LLAMA_SERVER_URL = os.environ.get("NIBLIT_LLAMA_SERVER_URL", "http://127.0.0.1:8080").rstrip("/")
_LLAMA_SERVER_TIMEOUT = int(os.environ.get("NIBLIT_LLAMA_SERVER_TIMEOUT", "600"))

# GGUF chat template style.  Supported values:
#   qwen   — Qwen2.5 / ChatML style (default; also used for generic ChatML models)
#   llama2 — Llama-2 [INST] format
#   alpaca — Alpaca instruction format
#   raw    — No template; prompt is sent as-is
_GGUF_CHAT_TEMPLATE = os.environ.get("NIBLIT_GGUF_CHAT_TEMPLATE", "qwen").strip().lower()

# Comma-separated stop tokens for the GGUF backend.
# When empty, sensible defaults are applied based on the chat template.
_GGUF_STOP_TOKENS_STR = os.environ.get("NIBLIT_GGUF_STOP_TOKENS", "").strip()

# Compact inline reference of Niblit's architecture injected into every ask().
# Kept deliberately terse so it fits within a 0.5B model's context window.
_NIBLIT_STRUCTURAL_CONTEXT = """
=== NIBLIT ARCHITECTURE (your structural awareness) ===

ENTRY POINTS:
  main.py           — Interactive CLI (NIBLIT_INIT_WAIT_MAX_SECONDS=300)
  app.py / server.py — FastAPI endpoints (local + Vercel)

CORE ORCHESTRATION:
  niblit_core.py    — NiblitCore: wires every subsystem; owns db, brain, router, autonomous_engine
  niblit_router.py  — NiblitRouter: routes text → handlers; 100+ command families
  niblit_brain.py   — NiblitBrain: think(), learn(), BrainRouter orchestration
  niblit_memory/    — FusedMemory + KnowledgeDB + LocalDB + ingestion helpers

MEMORY LAYERS (bottom-up):
  LocalDB           — JSON facts/interactions/learning_log (niblit.db)
  KnowledgeDB       — richer JSON facts+queue+acquired_data (niblit_memory.json)
  FusedMemory       — SQLite events + Qdrant vector search
  NiblitMemory      — top-level hub: circuit-breaker, cache, rate-limit, telemetry

BRAIN / LLM STACK:
  QwenLocalBrain    — local GGUF model (you); backends: http|subprocess|python
  BrainRouter       — mode: local|balanced|power|offline; routes to local/cloud
  HFBrain           — cloud HF InferenceClient (moonshotai/Kimi-K2 or similar)
  LLMProviderManager — runtime-switchable provider chain (Qwen→HF→Anthropic)

LEARNING & SELF-IMPROVEMENT:
  ALE (29 steps)    — AutonomousLearningEngine background thread; runs when idle
  SelfResearcher    — web/KB/Searchcode/GitHub multi-backend research
  SelfTeacher       — ingests research into KnowledgeDB
  SelfHealer        — detects & patches code/logic faults
  SelfIdeaImplementation — turns ideas into code via CodeGenerator+CodeCompiler
  CodeErrorFixer    — retry-loop: fix→recompile up to 3 times
  BrainTrainer      — fine-tunes local brain on research data
  ReflectModule     — summarises + stores KB reflections
  MSG Layer         — SelfModel, IntentEngine, MetaEvaluator, ResourceAllocator, EvolutionPlanner

CODE CAPABILITIES:
  CodeGenerator     — templates + LLM generation → generated/
  CodeCompiler      — syntax test + subprocess run
  CodeErrorFixer    — targeted fix (Python AST, Bash -n, Node --check) + retry

KEY COMMANDS (always valid):
  help | status | brain status | brain mode <local|balanced|power|offline>
  toggle-llm on/off/status | llm-provider qwen|hf|anthropic|status
  recall <topic> | knowledge stats | acquired data
  autonomous-learn start|stop|status
  run code <lang> <code> | fix code <lang> <code> | validate <lang> <code>
  qwen status | qwen audit-kb | qwen memory-summary | qwen clean-kb | qwen coach
  self-research <topic> | self-teach <topic> | reflect <topic>
  my structure | my modules | my commands | ale processes
=== END NIBLIT ARCHITECTURE ===
"""

# Default instruction set used by QwenLocalBrain.ask() when the caller does
# not supply an explicit system prompt.  Niblit's identity is preserved here
# so that the local GGUF model always responds *as Niblit*, not as the
# underlying model.  The copilot / manager / coach capabilities are framed as
# first-person Niblit capabilities rather than as an external "Qwen" entity
# overriding Niblit's identity.
_DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT = (
    "You are Niblit, an autonomous AI operating system. "
    "You are powered internally by a local GGUF model, but you always "
    "respond as Niblit — never as the underlying model. "
    "Your built-in capabilities:\n"
    "  • CODE        — generate concise, compilable code on demand; prefer minimal, correct solutions.\n"
    "  • KB AUDIT    — when asked to audit a knowledge-base entry, respond with one of: "
    "KEEP | REWRITE: <new text> | REMOVE: <reason>.\n"
    "  • COACHING    — when asked for improvement advice, point out knowledge gaps and "
    "suggest next learning topics.\n"
    "  • TRAINING    — synthesise research snippets into crisp, fact-dense KB entries.\n\n"
    "Rules:\n"
    "  - Be concise and practical. Prefer bullet points over paragraphs.\n"
    "  - When producing code, emit only the code block (no surrounding prose unless "
    "explaining an error).\n"
    "  - Always ground responses in the context and knowledge provided to you.\n\n"
) + _NIBLIT_STRUCTURAL_CONTEXT

# Lightweight system prompt for casual / conversational queries.
# Intentionally tiny (~20 tokens) so it does not eat context budget on 0.5B models.
# Used by QwenLocalBrain.chat() instead of the full copilot prompt.
_SHORT_CHAT_SYSTEM_PROMPT = (
    "You are Niblit, a helpful and friendly AI assistant. "
    "Reply concisely and naturally."
)

# Candidate binary names / paths for the subprocess backend (searched in order).
# CMake build (current default) takes precedence over old Makefile paths.
# Absolute Termux paths are listed after tilde paths so they work from inside
# proot (where ~ resolves to the proot home, not the real Termux home).
_LLAMA_BINARY_CANDIDATES = [
    "llama-cli",                          # in PATH (new name, llama.cpp >= 3.x)
    "llama",                              # in PATH (some distributions)
    "main",                               # in PATH (old name)
    "~/llama.cpp/build/bin/llama-cli",    # CMake build (Termux / Linux default)
    "~/llama.cpp/build/bin/main",         # CMake build (old binary name)
    "~/llama.cpp/llama-cli",              # legacy Makefile build
    "~/llama.cpp/main",                   # legacy Makefile build (old name)
    # Absolute Termux paths — used when Niblit runs inside proot where ~
    # resolves to the proot home, not /data/data/com.termux/files/home.
    "/data/data/com.termux/files/home/llama.cpp/build/bin/llama-cli",
    "/data/data/com.termux/files/home/llama.cpp/build/bin/main",
    "/data/data/com.termux/files/home/llama.cpp/llama-cli",
    "/data/data/com.termux/files/home/llama.cpp/main",
]

_LLAMA_CLI_FLAG_SUPPORT_CACHE: Dict[str, set[str]] = {}


def _llama_cli_supported_flags(binary: Optional[Path]) -> set[str]:
    """Return cached set of supported llama-cli flags for *binary*."""
    if binary is None:
        return set()
    key = str(binary)
    cached = _LLAMA_CLI_FLAG_SUPPORT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        probe = subprocess.run(
            [key, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        help_text = f"{probe.stdout}\n{probe.stderr}"
    except Exception:
        _LLAMA_CLI_FLAG_SUPPORT_CACHE[key] = set()
        return set()
    supported = {
        flag for flag in ("--simple-io", "--no-display-prompt", "--silent-prompt")
        if flag in help_text
    }
    _LLAMA_CLI_FLAG_SUPPORT_CACHE[key] = supported
    return supported


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from *text*."""
    text = text.strip()
    match = re.search(r"```(?:[a-zA-Z0-9_+-]+)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    text = re.sub(r"```\s*[a-zA-Z0-9_+-]*\s*", "", text)
    return text.strip()


def _strip_llama_startup_noise(text: str) -> str:
    """Strip llama-cli startup/banner noise from subprocess output."""
    if not text:
        return ""
    lines = text.splitlines()
    cleaned: list[str] = []
    skipping_commands = False
    for line in lines:
        s = line.strip()
        low = s.lower()

        # Common Termux/proot startup noise (both forms of getprop error)
        if "getprop" in low and "operation not permitted" in low:
            continue

        # llama-cli startup metadata / banner
        if (
            low == "loading model..."
            or re.match(r"^(build|model|modalities)\s*:", low)
        ):
            continue
        if s in {"▄▄ ▄▄", "██ ██"}:
            continue
        if "available commands:" in low:
            skipping_commands = True
            continue
        if skipping_commands:
            # Skip slash-command listing block after "available commands:"
            if s.startswith("/") or s.startswith("Ctrl+") or s.startswith("or Ctrl+"):
                continue
            if not s:
                skipping_commands = False
                continue

        # Skip decorative banner lines.
        if set(s) <= {"▄", "▀", "█", " "} and s:
            continue

        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _clean_subprocess_output(output: str, full_prompt: str) -> str:
    """Normalize llama-cli output into just assistant text."""
    text = output or ""
    if text.startswith(full_prompt):
        text = text[len(full_prompt):]
    elif full_prompt in text:
        text = text[text.index(full_prompt) + len(full_prompt):]
    text = _strip_llama_startup_noise(text)
    return _strip_code_fences(text)

# ── GGUF chat-template helpers ────────────────────────────────────────────────

_GGUF_TEMPLATES: Dict[str, Dict[str, Any]] = {
    # Qwen2.5 / ChatML
    "qwen": {
        "system_start": "<|im_start|>system\n",
        "system_end":   "<|im_end|>\n",
        "user_start":   "<|im_start|>user\n",
        "user_end":     "<|im_end|>\n",
        "assistant_start": "<|im_start|>assistant\n",
        "stop": ["<|im_end|>", "<|im_start|>"],
    },
    # Llama-2 instruct
    "llama2": {
        "system_start": "<<SYS>>\n",
        "system_end":   "\n<</SYS>>\n\n",
        "user_start":   "[INST] ",
        "user_end":     " [/INST]",
        "assistant_start": "",
        "stop": ["[INST]", "</s>"],
    },
    # Alpaca
    "alpaca": {
        "system_start": "",
        "system_end":   "\n\n",
        "user_start":   "### Instruction:\n",
        "user_end":     "\n\n",
        "assistant_start": "### Response:\n",
        "stop": ["### Instruction:", "### Input:"],
    },
    # Raw — no wrapping
    "raw": {
        "system_start": "",
        "system_end":   "\n",
        "user_start":   "",
        "user_end":     "",
        "assistant_start": "",
        "stop": ["</s>"],
    },
}


def _build_gguf_prompt(
    prompt: str,
    system_prompt: Optional[str],
    template_name: str,
) -> tuple[str, list[str]]:
    """Return ``(formatted_prompt, stop_tokens)`` for *template_name*.

    If *template_name* is unknown, falls back to ``'qwen'``.
    """
    tmpl = _GGUF_TEMPLATES.get(template_name) or _GGUF_TEMPLATES["qwen"]

    parts: list[str] = []
    if system_prompt:
        parts.append(tmpl["system_start"] + system_prompt + tmpl["system_end"])
    parts.append(tmpl["user_start"] + prompt + tmpl["user_end"])
    parts.append(tmpl["assistant_start"])

    # Override stop tokens from env if provided
    if _GGUF_STOP_TOKENS_STR:
        stop = [t.strip() for t in _GGUF_STOP_TOKENS_STR.split(",") if t.strip()]
    else:
        stop = list(tmpl["stop"])

    return "".join(parts), stop


def _resolve_hf_hub_cache_dir() -> Path:
    """Resolve HuggingFace Hub cache directory."""
    explicit_hub = os.environ.get("HUGGINGFACE_HUB_CACHE", "").strip()
    if explicit_hub:
        return Path(explicit_hub).expanduser()

    hf_home = os.environ.get("HF_HOME", "").strip()
    if hf_home:
        return Path(hf_home).expanduser() / "hub"

    try:
        from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE  # type: ignore[import]
        return Path(HUGGINGFACE_HUB_CACHE).expanduser()
    except Exception:
        return Path.home() / ".cache" / "huggingface" / "hub"


def _repo_cache_dir(model_name: str) -> Path:
    safe_repo = model_name.replace("/", "--")
    return _resolve_hf_hub_cache_dir() / f"models--{safe_repo}"


def _model_file_candidates(model_name: str) -> list[Path]:
    """Return ``.gguf`` files in the HuggingFace cache for *model_name*."""
    repo_dir = _repo_cache_dir(model_name)
    if not repo_dir.exists():
        return []

    patterns = (
        "snapshots/*.gguf",
        "snapshots/*/*.gguf",
    )
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(repo_dir.glob(pattern))
    if not paths:
        paths.extend(repo_dir.rglob("*.gguf"))
    return sorted({p.resolve() for p in paths})


def _find_gguf_in_cache(model_name: str) -> Optional[Path]:
    """Return the first ``.gguf`` file found in the HuggingFace cache for *model_name*, or None."""
    for p in _model_file_candidates(model_name):
        if p.suffix.lower() == ".gguf":
            return p
    return None


# Kept for backward-compatibility with any caller that imports this name;
# always returns 'gguf' since safetensors support was removed.
def _resolve_model_format(model_name: str, gguf_path: str, fmt: str) -> str:  # noqa: ARG001
    return "gguf"


def _find_llama_binary(explicit_path: str = "") -> Optional[Path]:
    """Locate the llama.cpp CLI binary.

    Search order:
    1. *explicit_path* (from ``NIBLIT_LLAMA_BINARY`` / constructor param).
    2. ``_LLAMA_BINARY_CANDIDATES`` — PATH entries tried via ``shutil.which``,
       then absolute / home-relative paths checked directly.

    Returns the first usable executable found, or ``None``.
    """
    import shutil

    def _usable(p: Path) -> bool:
        return p.is_file() and os.access(p, os.X_OK)

    if explicit_path:
        p = Path(explicit_path).expanduser()
        if _usable(p):
            return p
        found = shutil.which(explicit_path)
        if found:
            return Path(found)
        # Return even if missing so callers can show an actionable message.
        return p

    for candidate in _LLAMA_BINARY_CANDIDATES:
        if "/" in candidate or "~" in candidate:
            p = Path(candidate).expanduser()
            if _usable(p):
                return p
        else:
            found = shutil.which(candidate)
            if found:
                return Path(found)
    return None


class QwenLocalBrain:
    """CPU-friendly local LLM brain using GGUF quantized models.

    Two backends are supported (selected by ``NIBLIT_GGUF_BACKEND``):

    * **python** — ``llama-cpp-python`` (Llama object).  Preferred on
      desktop/server where RAM is available for compilation.
    * **subprocess** — pre-built ``llama.cpp`` CLI binary called via
      ``subprocess.run()``.  No Python compilation needed; ideal for
      Termux / low-RAM Android devices.
    * **auto** (default) — tries *python* first; falls back to *subprocess*
      automatically if ``llama-cpp-python`` is not installed.

    Thread-safe.  Loads model lazily on first ``generate()`` call.
    """

    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        max_new_tokens: int = _MAX_NEW_TOKENS,
        gguf_model_path: str = _GGUF_MODEL_PATH,
        gguf_n_ctx: int = _GGUF_N_CTX,
        gguf_n_threads: Optional[int] = _GGUF_N_THREADS,
        gguf_chat_template: str = _GGUF_CHAT_TEMPLATE,
        gguf_backend: str = _GGUF_BACKEND,
        llama_binary: str = _LLAMA_BINARY,
        llama_server_url: str = _LLAMA_SERVER_URL,
        llama_server_timeout: int = _LLAMA_SERVER_TIMEOUT,
        # Accepted for backward-compatibility; ignored (always GGUF).
        model_format: str = "gguf",
        dtype_str: str = "float32",
    ) -> None:
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.gguf_model_path = gguf_model_path
        self.gguf_n_ctx = gguf_n_ctx
        self.gguf_n_threads = gguf_n_threads
        self.gguf_chat_template = gguf_chat_template
        self.gguf_backend = gguf_backend
        self.llama_binary = llama_binary
        self.llama_server_url = llama_server_url.rstrip("/")
        self.llama_server_timeout = llama_server_timeout
        self.model_format = "gguf"

        self._lock = threading.Lock()

        # python backend state
        self._llama: Optional[Any] = None

        # subprocess backend state
        self._subprocess_bin: Optional[Path] = None

        # http backend state
        self._server_url: Optional[str] = None  # set when server is reachable

        # which backend is active: 'python' | 'subprocess' | 'http' | ''
        self._backend_in_use: str = ""

        self._load_tried: bool = False
        self._load_error: Optional[str] = None

    # ── Availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True once a backend has been loaded successfully."""
        return (
            self._llama is not None
            or self._subprocess_bin is not None
            or self._server_url is not None
        )

    def load_error(self) -> Optional[str]:
        """Return the last load error string, or None if loaded successfully."""
        return self._load_error

    def ensure_loaded(self) -> bool:
        """Public wrapper that loads the model lazily if needed."""
        return self._ensure_loaded()

    def cache_info(self) -> Dict[str, Any]:
        """Return cache / installation info for this model."""
        resolved_path = self._resolved_gguf_path()
        return {
            "backend":           "gguf",
            "gguf_model_path":   str(resolved_path) if resolved_path else "",
            "installed_locally": resolved_path is not None and resolved_path.is_file(),
            "hub_cache_dir":     str(_resolve_hf_hub_cache_dir()),
            "model_files":       [str(resolved_path)] if resolved_path and resolved_path.is_file() else [],
        }

    def _log_copilot_commands(self) -> None:
        """Log key Niblit commands when the local copilot backend becomes ready."""
        log.info(
            "[LocalBrain] Copilot commands: help | status | my commands | my structure | "
            "run code <language> <code> | fix code <language> <code> | autonomous-learn status | brain status"
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolved_gguf_path(self) -> Optional[Path]:
        """Return the resolved path to the GGUF file, or None if not found.

        Resolution order:
        1. Explicit ``NIBLIT_GGUF_MODEL_PATH`` / ``gguf_model_path`` param.
        2. ``NIBLIT_LOCAL_MODEL`` / ``model_name`` ends in ``.gguf``.
        3. Default location: ``~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf``.
        4. HuggingFace cache scan for any ``.gguf`` file.
        """
        # 1. Explicit env-var path
        if self.gguf_model_path:
            p = Path(self.gguf_model_path).expanduser()
            if p.is_file():
                return p
            # Path given but file doesn't exist yet → still return it so callers
            # can show an actionable message.
            return p
        # 2. model_name is itself a file path ending in .gguf
        if self.model_name.lower().endswith(".gguf"):
            p = Path(self.model_name).expanduser()
            return p
        # 3. Default install location used by tools/install_local_qwen_model.py
        default_path = Path.home() / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        if default_path.is_file():
            return default_path
        # 4. Check HuggingFace cache for any .gguf file
        cached = _find_gguf_in_cache(self.model_name)
        if cached:
            return cached
        # Return the default path even if absent so the error message is actionable.
        return default_path

    # ── Lazy model loading ────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        """Load the model backend if not yet done.  Returns True on success."""
        if self.is_available():
            return True
        if self._load_tried:
            return False
        with self._lock:
            if self.is_available():
                return True
            if self._load_tried:
                return False
            self._load_tried = True
            return self._load_gguf()

    def _load_gguf(self) -> bool:
        """Dispatch to the configured backend(s).

        ``auto``: tries http first (cross-session bridge), then subprocess,
                  then python.
        ``http``: HTTP bridge only (requires llama-server running separately).
        ``subprocess``: subprocess only.
        ``python``: python only.
        """
        backend = self.gguf_backend

        if backend == "http":
            return self._load_http_backend()

        if backend == "auto":
            # Preferred order on Termux: http (separate session, no proot
            # boundary issues) → subprocess (same session) → python (compiled).
            if self._load_http_backend():
                return True
            if self._load_subprocess_backend():
                return True
            return self._load_python_backend()

        if backend in ("subprocess", "auto"):
            return self._load_subprocess_backend()

        if backend == "python":
            return self._load_python_backend()

        # Unknown backend value — treat as auto
        log.warning(
            "[LocalBrain] Unknown NIBLIT_GGUF_BACKEND=%r; falling back to auto.", backend
        )
        return (
            self._load_http_backend()
            or self._load_subprocess_backend()
            or self._load_python_backend()
        )

    def _check_server_url(self, url: str) -> bool:
        """Return True if a llama-server endpoint responds at *url*."""
        probe_urls = (
            url + "/health",     # newer llama-server builds
            url + "/v1/models",  # OpenAI-compatible endpoint
            url + "/props",      # older llama-server builds
        )
        for probe_url in probe_urls:
            try:
                req = urllib.request.Request(probe_url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if 200 <= resp.status < 400:
                        return True
            except urllib.error.HTTPError as exc:
                # These probe-safe codes mean "this endpoint variant is not
                # usable here" but do not prove the server is down:
                # 404=missing route, 405=method mismatch, 501=not implemented.
                # 400/401/403 still prove a live HTTP server is responding, but
                # this probe URL/method/payload is rejected on that build.
                if exc.code in {400, 401, 403, 404, 405, 501}:
                    continue
                return False
            except Exception:
                continue
        return False

    def _load_http_backend(self) -> bool:
        """Check that llama-server is reachable at NIBLIT_LLAMA_SERVER_URL."""
        url = self.llama_server_url
        if not url:
            self._load_error = "NIBLIT_LLAMA_SERVER_URL is not set."
            return False

        if self._check_server_url(url):
            self._server_url = url
            self._backend_in_use = "http"
            self._load_error = None
            log.info("[LocalBrain] ✅ http backend ready: %s", url)
            self._log_copilot_commands()
            return True

        self._load_error = (
            f"llama-server not reachable at {url}. "
            "Start it in a separate Termux session with:\n"
            "  ~/llama.cpp/build/bin/llama-server \\\n"
            "      -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \\\n"
            "      --port 8080 --host 127.0.0.1 -c 2048 -t 4\n"
            "Then set: export NIBLIT_GGUF_BACKEND=http"
        )
        log.info("[LocalBrain] http backend unavailable: %s", self._load_error)
        return False

    def _generate_http(
        self,
        prompt: str,
        max_new_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate by calling the llama-server OpenAI-compatible API.

        Uses ``POST /v1/chat/completions`` with the ChatML messages format.
        Falls back to ``POST /completion`` (legacy llama-server endpoint) if
        the chat endpoint is unavailable.
        """
        url = self._server_url
        if url is None:
            return "[LocalBrain http: server URL not set]"

        # Re-check connectivity; server may have gone down between calls.
        if not self._check_server_url(url):
            log.warning("[LocalBrain] llama-server at %s is no longer reachable.", url)
            self._server_url = None
            self._backend_in_use = ""
            return "[LocalBrain http: server unreachable — restart llama-server]"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "local",
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": 0.7,
            "stop": list(_GGUF_TEMPLATES.get(self.gguf_chat_template, {}).get("stop", [])),
        }

        body = json.dumps(payload).encode("utf-8")
        chat_url = url + "/v1/chat/completions"
        req = urllib.request.Request(
            chat_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.llama_server_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text: str = data["choices"][0]["message"]["content"]
            log.debug(
                "[LocalBrain] http generated response for prompt[:60]=%r", prompt[:60]
            )
            return text.strip() or "[LocalBrain: empty response]"
        except urllib.error.HTTPError as exc:
            # Fall back to legacy /completion endpoint if chat endpoint not supported.
            if exc.code == 404:
                return self._generate_http_legacy(prompt, max_new_tokens, system_prompt)
            log.debug("[LocalBrain] http generate HTTPError: %s", exc)
            return f"[LocalBrain http error: {exc}]"
        except Exception as exc:
            log.debug("[LocalBrain] http generate error: %s", exc)
            return f"[LocalBrain http error: {exc}]"

    def _generate_http_legacy(
        self,
        prompt: str,
        max_new_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate via the legacy ``POST /completion`` llama-server endpoint."""
        url = self._server_url
        if url is None:
            return "[LocalBrain http: server URL not set]"

        full_prompt, _ = _build_gguf_prompt(prompt, system_prompt, self.gguf_chat_template)
        payload = {
            "prompt": full_prompt,
            "n_predict": max_new_tokens,
            "temperature": 0.7,
            "stop": list(_GGUF_TEMPLATES.get(self.gguf_chat_template, {}).get("stop", [])),
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url + "/completion",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.llama_server_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data.get("content", "")
            return text.strip() or "[LocalBrain: empty response]"
        except Exception as exc:
            log.debug("[LocalBrain] http legacy generate error: %s", exc)
            return f"[LocalBrain http legacy error: {exc}]"

    def _load_python_backend(self) -> bool:
        """Load model via llama-cpp-python."""
        try:
            from llama_cpp import Llama  # type: ignore[import]
        except ImportError:
            msg = (
                "llama-cpp-python is not installed. "
                "On Termux use the subprocess backend instead: "
                "set NIBLIT_GGUF_BACKEND=subprocess and build llama.cpp with "
                "'pkg install git cmake clang make && git clone "
                "https://github.com/ggerganov/llama.cpp && cd llama.cpp && make -j1'"
            )
            log.info("[LocalBrain] python backend unavailable: %s", msg)
            self._load_error = msg
            return False

        gguf_path = self._resolved_gguf_path()
        if gguf_path is None or not gguf_path.is_file():
            self._load_error = (
                f"GGUF model file not found. "
                f"Set NIBLIT_GGUF_MODEL_PATH=/path/to/model.gguf "
                f"(tried: {gguf_path}). "
                f"Download: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
            )
            log.warning("[LocalBrain] %s", self._load_error)
            return False

        kwargs: Dict[str, Any] = {
            "model_path": str(gguf_path),
            "n_ctx":      self.gguf_n_ctx,
            "verbose":    False,
        }
        if self.gguf_n_threads is not None:
            kwargs["n_threads"] = self.gguf_n_threads

        log.info(
            "[LocalBrain] Loading GGUF model %s via llama-cpp-python (n_ctx=%d)…",
            gguf_path.name, self.gguf_n_ctx,
        )
        try:
            self._llama = Llama(**kwargs)
            self._backend_in_use = "python"
            self._load_error = None
            log.info("[LocalBrain] ✅ python backend ready: %s", gguf_path.name)
            self._log_copilot_commands()
            return True
        except Exception as exc:
            self._load_error = str(exc)
            log.warning("[LocalBrain] Could not load GGUF model %s: %s", gguf_path, exc)
            return False

    def _load_subprocess_backend(self) -> bool:
        """Validate that the llama.cpp binary and model file are available."""
        binary = _find_llama_binary(self.llama_binary)

        if binary is None or not binary.is_file():
            searched = self.llama_binary or ", ".join(_LLAMA_BINARY_CANDIDATES[:4]) + " …"
            self._load_error = (
                "llama.cpp binary not found "
                f"(searched: {searched}). "
                "Build it on Termux with:\n"
                "  pkg install git cmake clang make\n"
                "  git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp\n"
                "  cd ~/llama.cpp && mkdir -p build && cd build\n"
                "  cmake .. -DLLAMA_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF\n"
                "  cmake --build . -j1\n"
                "Then set: export NIBLIT_LLAMA_BINARY=~/llama.cpp/build/bin/llama-cli"
            )
            log.warning("[LocalBrain] %s", self._load_error)
            return False

        gguf_path = self._resolved_gguf_path()
        if gguf_path is None or not gguf_path.is_file():
            self._load_error = (
                f"GGUF model file not found (tried: {gguf_path}). "
                f"Run: python tools/install_local_qwen_model.py"
            )
            log.warning("[LocalBrain] %s", self._load_error)
            return False

        self._subprocess_bin = binary
        self._backend_in_use = "subprocess"
        self._load_error = None
        log.info(
            "[LocalBrain] ✅ subprocess backend ready: %s + %s",
            binary.name, gguf_path.name,
        )
        self._log_copilot_commands()
        return True

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        max_new_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate a response for *prompt*.

        Falls back to a graceful message if no backend is loaded.

        Parameters
        ----------
        prompt:
            The user / system prompt text.
        max_new_tokens:
            Override the default token budget for this call.
        system_prompt:
            Optional system instruction prepended to the chat template.
        """
        if not self._ensure_loaded():
            return (
                f"[LocalBrain unavailable — {self._load_error or 'model not loaded'}]\n"
                f"Input: {prompt[:120]}"
            )

        n_tokens = max_new_tokens or self.max_new_tokens

        if self._backend_in_use == "http":
            return self._generate_http(prompt, n_tokens, system_prompt)
        if self._backend_in_use == "subprocess":
            return self._generate_subprocess(prompt, n_tokens, system_prompt)
        return self._generate_python(prompt, n_tokens, system_prompt)

    def _generate_python(
        self,
        prompt: str,
        max_new_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate via the llama-cpp-python Llama object."""
        try:
            full_prompt, stop_tokens = _build_gguf_prompt(
                prompt, system_prompt, self.gguf_chat_template
            )
            output = self._llama(
                full_prompt,
                max_tokens=max_new_tokens,
                stop=stop_tokens,
                echo=False,
            )
            response = (
                output["choices"][0]["text"].strip()
                if output and output.get("choices")
                else ""
            )
            log.debug("[LocalBrain] Generated response for prompt[:60]=%r", prompt[:60])
            return response if response else "[LocalBrain: empty response]"
        except Exception as exc:
            log.debug("[LocalBrain] generate error: %s", exc)
            return f"[LocalBrain error: {exc}]"

    def _generate_subprocess(
        self,
        prompt: str,
        max_new_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate by invoking the llama.cpp CLI binary via subprocess."""
        full_prompt, stop_tokens = _build_gguf_prompt(
            prompt, system_prompt, self.gguf_chat_template
        )
        gguf_path = self._resolved_gguf_path()
        binary = self._subprocess_bin

        # When running inside proot the model path may also need the absolute
        # Termux prefix.  Expand ~ against the real Termux home if the resolved
        # path doesn't exist but the absolute Termux path does.
        if gguf_path is not None and not gguf_path.is_file():
            termux_home = Path("/data/data/com.termux/files/home")
            try:
                rel = gguf_path.relative_to(Path.home())
                candidate = termux_home / rel
                if candidate.is_file():
                    gguf_path = candidate
            except ValueError:
                pass

        prompt_file: Optional[str] = None
        try:
            # Write the formatted prompt to a temp file to avoid shell-escaping issues.
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(full_prompt)
                prompt_file = f.name

            cmd = [
                str(binary),
                "-m", str(gguf_path),
                "-f", prompt_file,
                "-n", str(max_new_tokens),
                "-c", str(self.gguf_n_ctx),
                "--log-disable",   # suppress verbose log (llama.cpp >= b1.x)
            ]
            supported_flags = _llama_cli_supported_flags(binary)
            for flag in ("--simple-io", "--no-display-prompt", "--silent-prompt"):
                if flag in supported_flags:
                    cmd.append(flag)
            if self.gguf_n_threads is not None:
                cmd += ["-t", str(self.gguf_n_threads)]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.llama_server_timeout,
                stdin=subprocess.DEVNULL,
            )

            output = _clean_subprocess_output(result.stdout, full_prompt)

            # Truncate at the first stop token.
            for stop in stop_tokens:
                if stop in output:
                    output = output[: output.index(stop)]

            log.debug(
                "[LocalBrain] subprocess generated response for prompt[:60]=%r", prompt[:60]
            )
            return output.strip() or "[LocalBrain: empty response]"

        except subprocess.TimeoutExpired:
            log.debug("[LocalBrain] subprocess timed out after %d s", self.llama_server_timeout)
            return f"[LocalBrain subprocess: timeout after {self.llama_server_timeout} s]"
        except Exception as exc:
            log.debug("[LocalBrain] subprocess generate error: %s", exc)
            return f"[LocalBrain subprocess error: {exc}]"
        finally:
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass

    def ask(self, prompt: str, context: str = "", system_prompt: Optional[str] = None) -> str:
        """Convenience wrapper: prepend context and apply local copilot system prompt."""
        full_prompt = (context.strip() + "\n\n" + prompt.strip()) if context.strip() else prompt
        sys_prompt = system_prompt or _DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT
        return self.generate(full_prompt, system_prompt=sys_prompt)

    def chat(self, prompt: str) -> str:
        """Lightweight chat wrapper using the short system prompt.

        Intended for casual / conversational messages where the full copilot
        system prompt (≈900 tokens) would dominate the 0.5B model's context
        window.  Uses ``_SHORT_CHAT_SYSTEM_PROMPT`` (≈20 tokens) instead,
        leaving far more room for the model's actual reply.
        """
        return self.generate(prompt.strip(), system_prompt=_SHORT_CHAT_SYSTEM_PROMPT)

    def memory_adapter(self, knowledge_db: Optional[Any] = None) -> Any:
        """Return (and lazily create) the QwenMemoryAdapter for this brain.

        This exposes Qwen's manager/coach role: auditing KB facts, rewriting
        low-quality entries, and coaching Niblit on knowledge gaps.
        """
        try:
            from modules.qwen_memory_adapter import get_qwen_memory_adapter
            return get_qwen_memory_adapter(
                local_brain=self,
                knowledge_db=knowledge_db,
            )
        except Exception as exc:
            log.debug("[LocalBrain] memory_adapter unavailable: %s", exc)
            return None

    def audit_memory(
        self,
        knowledge_db: Optional[Any] = None,
        max_facts: int = 30,
        apply_changes: bool = True,
    ) -> str:
        """Convenience shortcut — run a full KB audit via QwenMemoryAdapter."""
        adapter = self.memory_adapter(knowledge_db)
        if adapter is None:
            return "[LocalBrain] QwenMemoryAdapter not available."
        return adapter.run_memory_audit(max_facts=max_facts, apply_changes=apply_changes)

    def coach(self, knowledge_db: Optional[Any] = None) -> str:
        """Convenience shortcut — produce a coaching / improvement report for Niblit."""
        adapter = self.memory_adapter(knowledge_db)
        if adapter is None:
            return "[LocalBrain] QwenMemoryAdapter not available."
        return adapter.coach_niblit()

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status dict."""
        cache = self.cache_info()
        return {
            "model_name":           self.model_name,
            "model_format":         "gguf",
            "backend_in_use":       self._backend_in_use or "none",
            "gguf_backend":         self.gguf_backend,
            "loaded":               self.is_available(),
            "load_tried":           self._load_tried,
            "load_error":           self._load_error,
            "max_new_tokens":       self.max_new_tokens,
            "gguf_model_path":      cache.get("gguf_model_path", ""),
            "gguf_n_ctx":           self.gguf_n_ctx,
            "gguf_n_threads":       self.gguf_n_threads,
            "gguf_chat_template":   self.gguf_chat_template,
            "llama_binary":         str(self._subprocess_bin) if self._subprocess_bin else self.llama_binary,
            "llama_server_url":     self._server_url or self.llama_server_url,
            "hub_cache_dir":        cache.get("hub_cache_dir", ""),
            "model_files":          cache.get("model_files", []),
            "installed_locally":    cache.get("installed_locally", False),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[QwenLocalBrain] = None
_inst_lock = threading.Lock()


def get_local_brain(
    model_name: str = _MODEL_NAME,
    max_new_tokens: int = _MAX_NEW_TOKENS,
    gguf_model_path: str = _GGUF_MODEL_PATH,
    # model_format accepted for backward-compatibility; ignored (always GGUF).
    model_format: str = "gguf",
) -> QwenLocalBrain:
    """Return the process-wide :class:`QwenLocalBrain` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = QwenLocalBrain(
                    model_name=model_name,
                    max_new_tokens=max_new_tokens,
                    gguf_model_path=gguf_model_path,
                )
    return _instance


if __name__ == "__main__":
    print('Running local_brain.py')
