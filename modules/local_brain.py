"""modules/local_brain.py — QwenLocalBrain: Niblit's primary local LLM.

Supports two execution backends for GGUF quantized models:

* **python** — ``llama-cpp-python`` (``pip install llama-cpp-python``).
  Preferred on desktop/server.  Requires ~2–4 GB RAM to *compile* on first
  install, which can OOM-kill Android/Termux processes.

* **subprocess** — calls the pre-built ``llama.cpp`` CLI binary
  (``llama-cli`` / ``main``) via ``subprocess.run()``.  Zero Python
  compilation; ideal for Termux and other low-RAM environments.
  Build with: ``pkg install git cmake clang make && git clone
  https://github.com/ggerganov/llama.cpp && cd llama.cpp && make -j1``

In ``auto`` mode (default) the python backend is tried first; if
``llama-cpp-python`` is not installed the subprocess backend is used
automatically.

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
                            files.  Default: ``Qwen/Qwen2.5-0.5B-Instruct``
NIBLIT_GGUF_MODEL_PATH      Explicit path to a local ``.gguf`` file
                            (takes priority over NIBLIT_LOCAL_MODEL).
NIBLIT_LOCAL_MAX_NEW        Max new tokens (default: 200)
NIBLIT_GGUF_N_CTX           Context length (default: 2048)
NIBLIT_GGUF_N_THREADS       CPU threads (default: auto)
NIBLIT_GGUF_CHAT_TEMPLATE   Chat template: ``qwen`` (default / ChatML),
                            ``llama2``, ``alpaca``, or ``raw``.
NIBLIT_GGUF_STOP_TOKENS     Comma-separated stop tokens.  When empty,
                            defaults are derived from the chat template.
NIBLIT_GGUF_BACKEND         Backend: ``auto`` (default), ``python``
                            (llama-cpp-python only), or ``subprocess``
                            (llama.cpp binary, no Python compilation needed).
NIBLIT_LLAMA_BINARY         Path to the llama.cpp CLI binary
                            (``llama-cli`` or ``main``).  When unset,
                            common PATH entries and build locations are tried.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
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

# Backend selector: 'auto' | 'python' | 'subprocess'
_GGUF_BACKEND = os.environ.get("NIBLIT_GGUF_BACKEND", "auto").strip().lower()

# Path to the llama.cpp CLI binary (llama-cli / main).
# When empty, common locations are searched automatically.
_LLAMA_BINARY = os.environ.get("NIBLIT_LLAMA_BINARY", "").strip()

# GGUF chat template style.  Supported values:
#   qwen   — Qwen2.5 / ChatML style (default; also used for generic ChatML models)
#   llama2 — Llama-2 [INST] format
#   alpaca — Alpaca instruction format
#   raw    — No template; prompt is sent as-is
_GGUF_CHAT_TEMPLATE = os.environ.get("NIBLIT_GGUF_CHAT_TEMPLATE", "qwen").strip().lower()

# Comma-separated stop tokens for the GGUF backend.
# When empty, sensible defaults are applied based on the chat template.
_GGUF_STOP_TOKENS_STR = os.environ.get("NIBLIT_GGUF_STOP_TOKENS", "").strip()

# Candidate binary names / paths for the subprocess backend (searched in order).
_LLAMA_BINARY_CANDIDATES = [
    "llama-cli",                          # in PATH (new name, llama.cpp >= 3.x)
    "llama",                              # in PATH (some distributions)
    "main",                               # in PATH (old name)
    "~/llama.cpp/llama-cli",
    "~/llama.cpp/main",
    "~/llama.cpp/build/bin/llama-cli",
    "~/llama.cpp/build/bin/main",
]

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
        self.model_format = "gguf"

        self._lock = threading.Lock()

        # python backend state
        self._llama: Optional[Any] = None

        # subprocess backend state
        self._subprocess_bin: Optional[Path] = None

        # which backend is active: 'python' | 'subprocess' | ''
        self._backend_in_use: str = ""

        self._load_tried: bool = False
        self._load_error: Optional[str] = None

    # ── Availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True once a backend has been loaded successfully."""
        return self._llama is not None or self._subprocess_bin is not None

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

        ``auto``: tries python first, falls back to subprocess.
        ``python``: python only.
        ``subprocess``: subprocess only.
        """
        backend = self.gguf_backend
        if backend in ("python", "auto"):
            if self._load_python_backend():
                return True
            if backend == "python":
                return False
            # auto: fall through to subprocess

        if backend in ("subprocess", "auto"):
            return self._load_subprocess_backend()

        # Unknown backend value — treat as auto
        log.warning(
            "[LocalBrain] Unknown NIBLIT_GGUF_BACKEND=%r; falling back to auto.", backend
        )
        return self._load_python_backend() or self._load_subprocess_backend()

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
                "  cd ~/llama.cpp && make -j1\n"
                "Then set: export NIBLIT_LLAMA_BINARY=~/llama.cpp/llama-cli"
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
            if self.gguf_n_threads is not None:
                cmd += ["-t", str(self.gguf_n_threads)]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            output = result.stdout

            # Strip the echoed prompt (llama-cli echoes the prompt before generating).
            if output.startswith(full_prompt):
                output = output[len(full_prompt):]
            elif full_prompt in output:
                output = output[output.index(full_prompt) + len(full_prompt):]

            # Truncate at the first stop token.
            for stop in stop_tokens:
                if stop in output:
                    output = output[: output.index(stop)]

            log.debug(
                "[LocalBrain] subprocess generated response for prompt[:60]=%r", prompt[:60]
            )
            return output.strip() or "[LocalBrain: empty response]"

        except subprocess.TimeoutExpired:
            log.debug("[LocalBrain] subprocess timed out")
            return "[LocalBrain subprocess: timeout after 120 s]"
        except Exception as exc:
            log.debug("[LocalBrain] subprocess generate error: %s", exc)
            return f"[LocalBrain subprocess error: {exc}]"
        finally:
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass

    def ask(self, prompt: str, context: str = "") -> str:
        """Convenience wrapper: optionally prepend *context* to prompt."""
        full_prompt = (context.strip() + "\n\n" + prompt.strip()) if context.strip() else prompt
        return self.generate(full_prompt)

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
