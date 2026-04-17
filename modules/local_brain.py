"""modules/local_brain.py — QwenLocalBrain: Niblit's primary local LLM.

Supports two backend formats:

**GGUF (llama-cpp-python) — recommended for Termux / mobile**
  Quantized GGUF models (e.g. q4_K_M) use ~300–600 MB RAM with no PyTorch
  dependency, making them stable on Android/Termux where the full
  safetensors format crashes (~2 GB RAM spike during load).

  Set ``NIBLIT_LOCAL_MODEL_FORMAT=gguf`` and point
  ``NIBLIT_GGUF_MODEL_PATH`` to the local ``.gguf`` file, *or* let
  auto-detection pick it up when ``NIBLIT_LOCAL_MODEL`` ends in ``.gguf``.

**safetensors (transformers) — desktop / server**
  Full-precision Transformers pipeline (original behaviour).  Requires
  ``torch`` + ``transformers``.  Suitable for desktops with ≥4 GB RAM.

Auto-detection order
--------------------
1. ``NIBLIT_LOCAL_MODEL_FORMAT`` env var (``gguf`` / ``safetensors`` /
   ``auto``).
2. If the resolved model path ends in ``.gguf`` → GGUF backend.
3. Default → safetensors backend.

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
The model is cached for the process lifetime.  All heavy imports are
guarded so the module imports cleanly even without ``torch`` or
``llama_cpp``.

Environment variables
---------------------
NIBLIT_LOCAL_MODEL          HuggingFace model id **or** path to ``.gguf`` file.
                            Default: ``Qwen/Qwen2.5-0.5B-Instruct``
NIBLIT_GGUF_MODEL_PATH      Explicit path to a local ``.gguf`` file.
                            When set, ``NIBLIT_LOCAL_MODEL_FORMAT`` defaults to
                            ``gguf`` automatically.
NIBLIT_LOCAL_MODEL_FORMAT   Backend override: ``auto`` (default), ``gguf``, or
                            ``safetensors``.
NIBLIT_LOCAL_MAX_NEW        Max new tokens (default: 200)
NIBLIT_LOCAL_DTYPE          torch dtype used by safetensors backend:
                            ``float32`` (default) or ``float16``
NIBLIT_GGUF_N_CTX           llama-cpp context length (default: 2048)
NIBLIT_GGUF_N_THREADS       llama-cpp CPU threads (default: auto)
NIBLIT_GGUF_CHAT_TEMPLATE   Chat template for the GGUF backend: ``qwen``
                            (default / ChatML), ``llama2``, ``alpaca``,
                            or ``raw`` (no template).
NIBLIT_GGUF_STOP_TOKENS     Comma-separated stop tokens for GGUF generation.
                            When empty, defaults are derived from the chat
                            template (e.g. ``<|im_end|>`` for qwen/ChatML).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("Niblit.LocalBrain")

# ── Configuration ─────────────────────────────────────────────────────────────
_MODEL_NAME      = os.environ.get("NIBLIT_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
_GGUF_MODEL_PATH = os.environ.get("NIBLIT_GGUF_MODEL_PATH", "").strip()
_MAX_NEW_TOKENS  = int(os.environ.get("NIBLIT_LOCAL_MAX_NEW", "200"))
_DTYPE_STR       = os.environ.get("NIBLIT_LOCAL_DTYPE", "float32")
_GGUF_N_CTX      = int(os.environ.get("NIBLIT_GGUF_N_CTX", "2048"))
_GGUF_N_THREADS_STR = os.environ.get("NIBLIT_GGUF_N_THREADS", "").strip()
_GGUF_N_THREADS  = int(_GGUF_N_THREADS_STR) if _GGUF_N_THREADS_STR.isdigit() else None

# Model format: 'auto', 'gguf', or 'safetensors'
_MODEL_FORMAT    = os.environ.get("NIBLIT_LOCAL_MODEL_FORMAT", "auto").strip().lower()

# GGUF chat template style.  Supported values:
#   qwen   — Qwen2.5 / ChatML style (default; also used for generic ChatML models)
#   llama2 — Llama-2 [INST] format
#   alpaca — Alpaca instruction format
#   raw    — No template; prompt is sent as-is
_GGUF_CHAT_TEMPLATE = os.environ.get("NIBLIT_GGUF_CHAT_TEMPLATE", "qwen").strip().lower()

# Comma-separated stop tokens for the GGUF backend.
# When empty, sensible defaults are applied based on the chat template.
_GGUF_STOP_TOKENS_STR = os.environ.get("NIBLIT_GGUF_STOP_TOKENS", "").strip()

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


def _resolve_model_format(model_name: str, gguf_path: str, fmt: str) -> str:
    """Resolve the effective backend format (``'gguf'`` or ``'safetensors'``).

    Priority:
    1. Explicit ``fmt`` override (if not ``'auto'``).
    2. Explicit ``gguf_path`` env var → ``'gguf'``.
    3. ``model_name`` ends in ``.gguf`` → ``'gguf'``.
    4. Default → ``'safetensors'``.
    """
    if fmt not in ("auto", "gguf", "safetensors"):
        log.warning("[LocalBrain] Unknown NIBLIT_LOCAL_MODEL_FORMAT=%r; falling back to auto", fmt)
        fmt = "auto"
    if fmt != "auto":
        return fmt
    if gguf_path:
        return "gguf"
    if model_name.lower().endswith(".gguf"):
        return "gguf"
    return "safetensors"


def _resolve_hf_hub_cache_dir() -> Path:
    """Resolve HuggingFace Hub cache directory used by transformers downloads."""
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
    """Return known weight files in the HuggingFace cache for *model_name*.

    Finds both ``.safetensors`` and ``.gguf`` files.
    """
    repo_dir = _repo_cache_dir(model_name)
    if not repo_dir.exists():
        return []

    patterns = (
        "snapshots/*/model.safetensors",
        "snapshots/*/model.safetensors.index.json",
        "snapshots/*.gguf",
        "snapshots/*/*.gguf",
    )
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(repo_dir.glob(pattern))
    if not paths:
        # Fallback if cache layout differs from expected snapshots/* layout.
        paths.extend(repo_dir.rglob("model.safetensors"))
        paths.extend(repo_dir.rglob("model.safetensors.index.json"))
        paths.extend(repo_dir.rglob("*.gguf"))
    unique_sorted = sorted({p.resolve() for p in paths})
    return unique_sorted


def _find_gguf_in_cache(model_name: str) -> Optional[Path]:
    """Return the first ``.gguf`` file found in the HuggingFace cache for *model_name*, or None."""
    for p in _model_file_candidates(model_name):
        if p.suffix.lower() == ".gguf":
            return p
    return None


class QwenLocalBrain:
    """CPU-friendly local LLM brain supporting GGUF (llama-cpp) and safetensors (transformers).

    **GGUF backend** (recommended for Termux / mobile):
      - Requires ``llama-cpp-python`` (``pip install llama-cpp-python``).
      - Set ``NIBLIT_GGUF_MODEL_PATH=/path/to/model.gguf`` or point
        ``NIBLIT_LOCAL_MODEL`` at a ``.gguf`` file.
      - Uses only ~300–600 MB RAM; no PyTorch required.

    **safetensors backend** (desktop / server):
      - Requires ``torch`` + ``transformers``.
      - Default when no GGUF file is configured.
      - Uses ~2 GB+ RAM; may crash on low-memory devices.

    Thread-safe.  Loads model lazily on first ``generate()`` call.
    """

    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        max_new_tokens: int = _MAX_NEW_TOKENS,
        dtype_str: str = _DTYPE_STR,
        gguf_model_path: str = _GGUF_MODEL_PATH,
        model_format: str = _MODEL_FORMAT,
        gguf_n_ctx: int = _GGUF_N_CTX,
        gguf_n_threads: Optional[int] = _GGUF_N_THREADS,
        gguf_chat_template: str = _GGUF_CHAT_TEMPLATE,
    ) -> None:
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.dtype_str = dtype_str
        self.gguf_model_path = gguf_model_path
        self.gguf_n_ctx = gguf_n_ctx
        self.gguf_n_threads = gguf_n_threads
        self.gguf_chat_template = gguf_chat_template

        # Resolve effective format once at construction time so it's stable.
        self.model_format = _resolve_model_format(model_name, gguf_model_path, model_format)

        self._lock = threading.Lock()
        # GGUF backend
        self._llama: Optional[Any] = None
        # safetensors backend
        self._tokenizer: Optional[Any] = None
        self._model: Optional[Any] = None

        self._load_tried: bool = False
        self._load_error: Optional[str] = None

    # ── Availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True once the model has been loaded successfully."""
        if self.model_format == "gguf":
            return self._llama is not None
        return self._model is not None

    def load_error(self) -> Optional[str]:
        """Return the last load error string, or None if loaded successfully."""
        return self._load_error

    def ensure_loaded(self) -> bool:
        """Public wrapper that loads the model lazily if needed."""
        return self._ensure_loaded()

    def cache_info(self) -> Dict[str, Any]:
        """Return cache / installation info for this model."""
        if self.model_format == "gguf":
            resolved_path = self._resolved_gguf_path()
            return {
                "backend":        "gguf",
                "gguf_model_path": str(resolved_path) if resolved_path else "",
                "installed_locally": resolved_path is not None and resolved_path.is_file(),
                "hub_cache_dir":  str(_resolve_hf_hub_cache_dir()),
                "repo_cache_dir": "",
                "model_files":    [str(resolved_path)] if resolved_path and resolved_path.is_file() else [],
            }
        model_files = _model_file_candidates(self.model_name)
        repo_dir = _repo_cache_dir(self.model_name)
        return {
            "backend":        "safetensors",
            "gguf_model_path": "",
            "hub_cache_dir":  str(_resolve_hf_hub_cache_dir()),
            "repo_cache_dir": str(repo_dir),
            "model_files":    [str(p) for p in model_files],
            "installed_locally": bool(model_files),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolved_gguf_path(self) -> Optional[Path]:
        """Return the resolved path to the GGUF file, or None if not found."""
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
            if p.is_file():
                return p
            return p
        # 3. Check HuggingFace cache for any .gguf file
        cached = _find_gguf_in_cache(self.model_name)
        if cached:
            return cached
        return None

    # ── Lazy model loading ────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        """Load the model if not yet done.  Returns True on success."""
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
            if self.model_format == "gguf":
                return self._load_gguf()
            return self._load_safetensors()

    def _load_gguf(self) -> bool:
        """Load model via llama-cpp-python (GGUF backend)."""
        try:
            from llama_cpp import Llama  # type: ignore[import]
        except ImportError:
            self._load_error = (
                "llama-cpp-python is not installed. "
                "Install with: pip install llama-cpp-python"
            )
            log.warning("[LocalBrain] %s", self._load_error)
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
            "n_ctx": self.gguf_n_ctx,
            "verbose": False,
        }
        if self.gguf_n_threads is not None:
            kwargs["n_threads"] = self.gguf_n_threads

        log.info(
            "[LocalBrain] Loading GGUF model %s (n_ctx=%d)…",
            gguf_path.name, self.gguf_n_ctx,
        )
        try:
            self._llama = Llama(**kwargs)
            log.info("[LocalBrain] ✅ GGUF model ready: %s", gguf_path.name)
            return True
        except Exception as exc:
            self._load_error = str(exc)
            log.warning("[LocalBrain] Could not load GGUF model %s: %s", gguf_path, exc)
            return False

    def _load_safetensors(self) -> bool:
        """Load model via HuggingFace Transformers (safetensors backend)."""
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM

            dtype = torch.float32 if self.dtype_str == "float32" else torch.float16

            log.info(
                "[LocalBrain] Loading %s (dtype=%s, format=safetensors, device=cpu)…",
                self.model_name, self.dtype_str,
            )
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=dtype,
                device_map="cpu",
                use_safetensors=True,
            )
            model.eval()
            self._tokenizer = tokenizer
            self._model = model
            log.info("[LocalBrain] ✅ %s ready", self.model_name)
            return True
        except Exception as exc:
            self._load_error = str(exc)
            log.warning("[LocalBrain] Could not load %s: %s", self.model_name, exc)
            return False

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        max_new_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate a response for *prompt*.

        Falls back to a graceful message if the model isn't loaded.

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

        if self.model_format == "gguf":
            return self._generate_gguf(prompt, n_tokens, system_prompt)
        return self._generate_safetensors(prompt, n_tokens, system_prompt)

    def _generate_gguf(
        self,
        prompt: str,
        max_new_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate using the llama-cpp backend."""
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
            response = output["choices"][0]["text"].strip() if output and output.get("choices") else ""
            log.debug("[LocalBrain/gguf] Generated response for prompt[:60]=%r", prompt[:60])
            return response if response else "[LocalBrain: empty response]"
        except Exception as exc:
            log.debug("[LocalBrain/gguf] generate error: %s", exc)
            return f"[LocalBrain error: {exc}]"

    def _generate_safetensors(
        self,
        prompt: str,
        max_new_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate using the HuggingFace Transformers backend."""
        try:
            import torch

            # Build chat-template messages if the tokenizer supports it
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            if hasattr(self._tokenizer, "apply_chat_template"):
                text = self._tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            else:
                # Plain prompt without template
                text = (f"System: {system_prompt}\n\n" if system_prompt else "") + prompt

            inputs = self._tokenizer(text, return_tensors="pt")

            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=self._tokenizer.eos_token_id,
                )

            # Decode only the newly generated tokens (not the prompt)
            input_len = inputs["input_ids"].shape[1]
            new_tokens = outputs[0][input_len:]
            response = self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

            log.debug("[LocalBrain/safetensors] Generated %d tokens for prompt[:60]=%r",
                      len(new_tokens), prompt[:60])
            return response if response else "[LocalBrain: empty response]"

        except Exception as exc:
            log.debug("[LocalBrain] generate error: %s", exc)
            return f"[LocalBrain error: {exc}]"

    def ask(self, prompt: str, context: str = "") -> str:
        """Convenience wrapper: optionally prepend *context* to prompt."""
        full_prompt = (context.strip() + "\n\n" + prompt.strip()) if context.strip() else prompt
        return self.generate(full_prompt)

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status dict."""
        cache = self.cache_info()
        return {
            "model_name":           self.model_name,
            "model_format":         self.model_format,
            "loaded":               self.is_available(),
            "load_tried":           self._load_tried,
            "load_error":           self._load_error,
            "max_new_tokens":       self.max_new_tokens,
            "dtype":                self.dtype_str,
            "gguf_model_path":      cache.get("gguf_model_path", ""),
            "gguf_n_ctx":           self.gguf_n_ctx,
            "gguf_n_threads":       self.gguf_n_threads,
            "gguf_chat_template":   self.gguf_chat_template,
            "hub_cache_dir":        cache.get("hub_cache_dir", ""),
            "repo_cache_dir":       cache.get("repo_cache_dir", ""),
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
    model_format: str = _MODEL_FORMAT,
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
                    model_format=model_format,
                )
    return _instance


if __name__ == "__main__":
    print('Running local_brain.py')
