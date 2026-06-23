#!/usr/bin/env python3
# modules/llm_module.py
"""
Hugging Face LLM adapter using InferenceClient (modern API).
Provides:
 - HFLLMAdapter.is_online()
 - HFLLMAdapter.query_llm(messages, model=None, max_tokens=300)
 - HFLLMAdapter.generate_code(language, purpose, context, max_tokens=800)
 - HFLLMAdapter.qdrant_client  — compatibility attribute (always None)
 - HFLLMAdapter.vector_store   — VectorStore instance for semantic context enrichment
"""
import logging
import os
import re

from modules.config.qdrant_config import QdrantConfig

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on os.environ

log = logging.getLogger("HFLLMAdapter")

HF_TOKEN = os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_TOKEN", "") or os.environ.get("HF_API_KEY", "")

try:
    from huggingface_hub import InferenceClient
    HF_CLIENT_AVAILABLE = True
except Exception:
    InferenceClient = None
    HF_CLIENT_AVAILABLE = False

DEFAULT_MODEL = os.getenv("NIBLIT_LLM_MODEL") or "moonshotai/Kimi-K2-Instruct-0905"
# Maximum characters of research context forwarded to the LLM in generate_code().
_MAX_CONTEXT_LENGTH: int = 600
# Maximum characters of vector-store context injected automatically.
_MAX_VS_CONTEXT_LENGTH: int = 400
# Number of vector-store hits to retrieve for context enrichment.
_VS_CONTEXT_TOP_K: int = 3


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```...```) wrapping generated code."""
    text = text.strip()
    # Remove opening fence: ```python, ```bash, ``` etc.
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text, flags=re.MULTILINE)
    # Remove closing fence
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


class HFLLMAdapter:
    """
    Hugging Face LLM adapter with optional Qdrant-backed context enrichment.

    When ``QDRANT_URL`` is set, :class:`modules.vector_store.VectorStore`
    routes semantic memory operations through
    :class:`modules.hybrid_qdrant_manager.HybridQdrantManager`.

    ``generate_code()`` automatically queries the vector store to pull
    semantically relevant snippets and injects them as extra context for the
    LLM — unless the caller already supplies a ``context`` string.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        self.model = model
        self.api_key = HF_TOKEN

        # ── HuggingFace InferenceClient ───────────────────────────────────────
        self.client = None
        if HF_CLIENT_AVAILABLE and self.api_key:
            try:
                self.client = InferenceClient(api_key=self.api_key)
            except Exception:
                self.client = None

        # ── Qdrant routing handled centrally by HybridQdrantManager ──────────
        qdrant_config = QdrantConfig.load()
        _url = qdrant_url or qdrant_config.url
        _key = qdrant_api_key or (qdrant_config.api_key or "")
        self.qdrant_client = None
        if _url:
            log.info("HFLLMAdapter: Qdrant routing delegated to HybridQdrantManager (%s)", _url)

        # ── VectorStore (uses same Qdrant backend when available) ─────────────
        self.vector_store = None
        try:
            from modules.vector_store import VectorStore
            self.vector_store = VectorStore(
                qdrant_url=_url,
                qdrant_api_key=_key,
            )
        except Exception as exc:
            log.debug("HFLLMAdapter: VectorStore unavailable: %s", exc)

    def is_online(self) -> bool:
        # Simple check: client present and api_key present
        return bool(self.client and self.api_key)

    def query_llm(self, messages, model: str = None, max_tokens: int = 300):
        """
        messages: list[{"role": "...", "content": "..."}]
        Returns the assistant reply as a string or an error string.
        """
        if model is None:
            model = self.model
        if not self.client:
            return "[HF ERROR] InferenceClient unavailable or HF_TOKEN not set."
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            # Try extract human-friendly text
            try:
                # resp.choices[0].message may be a dict or object
                choice = resp.choices[0]
                msg = getattr(choice, "message", None) or (choice.get("message") if isinstance(choice, dict) else None)
                # msg could be object with .content or dict with "content"
                if isinstance(msg, dict):
                    content = msg.get("content") or msg.get("content_text") or str(msg)
                else:
                    content = getattr(msg, "content", None) or str(msg)
            except Exception:
                # fallback to stringifying resp
                content = str(resp)
            return content
        except Exception as e:
            return f"[HF ERROR] {e}"

    def _fetch_vector_context(self, query: str) -> str:
        """Return a short context string pulled from the vector store."""
        if self.vector_store is None:
            return ""
        try:
            hits = self.vector_store.search(query, top_k=_VS_CONTEXT_TOP_K)
            snippets = [h.get("text", "")[:200] for h in hits if h.get("text")]
            combined = " | ".join(snippets)
            return combined[:_MAX_VS_CONTEXT_LENGTH]
        except Exception:
            return ""

    def generate_code(self, language: str, purpose: str, context: str = "", max_tokens: int = 800) -> str:
        """Generate real, executable code using the LLM.

        When ``context`` is empty and a vector store is available, semantically
        relevant snippets are retrieved from the vector store and injected as
        context automatically.

        Args:
            language:   Target programming language (e.g. "python", "bash").
            purpose:    Short description of what the code should do.
            context:    Optional research context to inform the implementation.
                        When blank, the vector store is queried automatically.
            max_tokens: Maximum tokens for the LLM response.

        Returns:
            Generated source code as a string, or empty string on failure.
        """
        # Auto-enrich context from vector store when not provided by caller
        if not context:
            context = self._fetch_vector_context(f"{language} {purpose}")

        system_prompt = (
            f"You are an expert {language} programmer. "
            f"Write real, executable {language} code. "
            "Return ONLY the code itself — no explanations, no markdown fences, "
            "no preamble. The code must be complete and runnable."
        )
        user_prompt = f"Write {language} code that: {purpose}"
        if context:
            user_prompt += (
                f"\n\nUse the following research context to inform the implementation:\n"
                f"{context[:_MAX_CONTEXT_LENGTH]}"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw = self.query_llm(messages, max_tokens=max_tokens)
        if not raw or raw.startswith("[HF ERROR]"):
            return ""
        return _strip_code_fences(raw).strip()

if __name__ == "__main__":
    print('Running llm_module.py')
