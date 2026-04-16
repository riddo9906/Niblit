"""modules/local_brain.py — QwenLocalBrain: Niblit's primary local LLM.

Uses Qwen/Qwen2.5-0.5B-Instruct running entirely on CPU (no GPU required),
making it suitable for Termux + proot-distro Ubuntu on Android.

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
The model is cached for the process lifetime.  All heavy transformers
imports are guarded so the module imports cleanly even without ``torch``.

Environment variables
---------------------
NIBLIT_LOCAL_MODEL   Override model name (default: ``Qwen/Qwen2.5-0.5B-Instruct``)
NIBLIT_LOCAL_MAX_NEW  Max new tokens (default: 200)
NIBLIT_LOCAL_DTYPE   torch dtype: ``float32`` (default) or ``float16``
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("Niblit.LocalBrain")

# ── Configuration ─────────────────────────────────────────────────────────────
_MODEL_NAME   = os.environ.get("NIBLIT_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
_MAX_NEW_TOKENS = int(os.environ.get("NIBLIT_LOCAL_MAX_NEW", "200"))
_DTYPE_STR    = os.environ.get("NIBLIT_LOCAL_DTYPE", "float32")


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
    repo_dir = _repo_cache_dir(model_name)
    if not repo_dir.exists():
        return []

    patterns = ("snapshots/*/model.safetensors", "snapshots/*/model.safetensors.index.json")
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(repo_dir.glob(pattern))
    if not paths:
        # Fallback if cache layout differs from expected snapshots/* layout.
        paths.extend(repo_dir.rglob("model.safetensors"))
        paths.extend(repo_dir.rglob("model.safetensors.index.json"))
    unique_sorted = sorted({p.resolve() for p in paths})
    return unique_sorted


class QwenLocalBrain:
    """CPU-friendly local LLM brain using Qwen2.5-0.5B-Instruct.

    Thread-safe.  Loads model lazily on first use.
    """

    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        max_new_tokens: int = _MAX_NEW_TOKENS,
        dtype_str: str = _DTYPE_STR,
    ) -> None:
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.dtype_str = dtype_str

        self._lock = threading.Lock()
        self._tokenizer: Optional[Any] = None
        self._model: Optional[Any] = None
        self._load_tried: bool = False
        self._load_error: Optional[str] = None

    # ── Availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True once the model has been loaded successfully."""
        return self._model is not None

    def load_error(self) -> Optional[str]:
        """Return the last load error string, or None if loaded successfully."""
        return self._load_error

    def ensure_loaded(self) -> bool:
        """Public wrapper that loads model + tokenizer lazily if needed."""
        return self._ensure_loaded()

    def cache_info(self) -> Dict[str, Any]:
        """Return HuggingFace cache inspection info for this model."""
        model_files = _model_file_candidates(self.model_name)
        repo_dir = _repo_cache_dir(self.model_name)
        return {
            "hub_cache_dir": str(_resolve_hf_hub_cache_dir()),
            "repo_cache_dir": str(repo_dir),
            "model_files": [str(p) for p in model_files],
            "installed_locally": bool(model_files),
        }

    # ── Lazy model loading ────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        """Load model + tokenizer if not yet done.  Returns True on success."""
        if self._model is not None:
            return True
        if self._load_tried:
            return False
        with self._lock:
            if self._model is not None:
                return True
            if self._load_tried:
                return False
            self._load_tried = True
            try:
                import torch
                from transformers import AutoTokenizer, AutoModelForCausalLM

                dtype = torch.float32 if self.dtype_str == "float32" else torch.float16

                log.info("[LocalBrain] Loading %s (dtype=%s, device=cpu)…",
                         self.model_name, self.dtype_str)
                tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=dtype,
                    device_map="cpu",
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

        try:
            import torch

            n_tokens = max_new_tokens or self.max_new_tokens

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
                    max_new_tokens=n_tokens,
                    do_sample=False,
                    pad_token_id=self._tokenizer.eos_token_id,
                )

            # Decode only the newly generated tokens (not the prompt)
            input_len = inputs["input_ids"].shape[1]
            new_tokens = outputs[0][input_len:]
            response = self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

            log.debug("[LocalBrain] Generated %d tokens for prompt[:60]=%r",
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
            "model_name":   self.model_name,
            "loaded":       self._model is not None,
            "load_tried":   self._load_tried,
            "load_error":   self._load_error,
            "max_new_tokens": self.max_new_tokens,
            "dtype":        self.dtype_str,
            "hub_cache_dir": cache["hub_cache_dir"],
            "repo_cache_dir": cache["repo_cache_dir"],
            "model_files": cache["model_files"],
            "installed_locally": cache["installed_locally"],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[QwenLocalBrain] = None
_inst_lock = threading.Lock()


def get_local_brain(
    model_name: str = _MODEL_NAME,
    max_new_tokens: int = _MAX_NEW_TOKENS,
) -> QwenLocalBrain:
    """Return the process-wide :class:`QwenLocalBrain` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = QwenLocalBrain(
                    model_name=model_name,
                    max_new_tokens=max_new_tokens,
                )
    return _instance


if __name__ == "__main__":
    print('Running local_brain.py')
