#!/usr/bin/env python3
"""modules/knowledge_digest.py — KnowledgeDigest

Processes raw research text into a first-person, internalized understanding
before it is persisted to the knowledge base.  This keeps stored facts clean
and human-readable rather than being dumps of raw source material or internal
metadata keys.

Usage (additive — can be dropped in anywhere):

    from modules.knowledge_digest import KnowledgeDigest

    digest = KnowledgeDigest(llm=core.llm)
    stored_value = digest.digest(topic="neural networks", raw_content=raw)
"""

import logging
import re

log = logging.getLogger("KnowledgeDigest")

# Maximum characters of raw content sent to the LLM for rephrasing
_MAX_LLM_INPUT_LENGTH = 900

# Maximum characters returned when no LLM is available (fallback path)
_MAX_FALLBACK_LENGTH = 600

# Patterns for internal metadata that should never appear in stored facts
_INTERNAL_KEY_PATTERNS = re.compile(
    r"\b(?:gap_learned|self_teach_summary|quiz|ale_reflection|ale_learned"
    r"|ale_code_reflection|ale_trading_reflection|research):[^\s,;\"']{3,}\b",
    re.IGNORECASE,
)

# Strip standalone large integers (≥10 digits) — these are raw timestamps
_LARGE_INT_PATTERN = re.compile(r"\b\d{10,}\b")

# The prompt used when an LLM is available
_DIGEST_PROMPT = (
    "You are Niblit, a self-improving AI assistant.  You just researched the topic "
    "'{topic}'.  Below is the raw information you found.  Write a concise explanation "
    "(2–4 sentences) in your own words, as if you now genuinely understand this topic.  "
    "Do NOT copy the source text verbatim.  Do NOT include source URLs, timestamps, "
    "or technical key names.  Focus on meaning and insight.\n\n"
    "Raw research:\n{content}"
)


def _clean_metadata_noise(text: str) -> str:
    """Remove internal key names and raw timestamps from *text*."""
    text = _INTERNAL_KEY_PATTERNS.sub("", text)
    text = _LARGE_INT_PATTERN.sub("", text)
    # Collapse multiple spaces / newlines left behind
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class KnowledgeDigest:
    """Rewrites raw research into Niblit's own internalized understanding.

    Parameters
    ----------
    llm:
        Any object with a ``query_llm(messages, max_tokens=...)`` method
        (e.g. ``LLMAdapter``, ``HFLLMAdapter``).  When *None*, the digest
        falls back to cleaning the raw text without LLM rephrasing.
    """

    def __init__(self, llm=None):
        self.llm = llm

    # ── public API ────────────────────────────────────────────────────────────

    def digest(self, topic: str, raw_content: str, llm=None) -> str:
        """Return *raw_content* reformulated in Niblit's own words.

        Parameters
        ----------
        topic:
            The subject being stored (e.g. ``"neural networks"``).
        raw_content:
            Raw research text, a dict converted to string, or any value
            that can be coerced with ``str()``.
        llm:
            Optional LLM override for this single call; falls back to
            ``self.llm`` when not provided.

        Returns
        -------
        str
            A cleaned, internalized version of the content.  Never raises —
            always returns *something* useful.
        """
        active_llm = llm or self.llm
        cleaned = _clean_metadata_noise(str(raw_content))

        if not cleaned or len(cleaned) < 10:
            # Nothing meaningful left after cleaning — return the original
            return str(raw_content).strip()

        if active_llm and hasattr(active_llm, "query_llm"):
            try:
                prompt = _DIGEST_PROMPT.format(
                    topic=topic,
                    content=cleaned[:_MAX_LLM_INPUT_LENGTH],
                )
                messages = [{"role": "user", "content": prompt}]
                result = active_llm.query_llm(messages, max_tokens=280)
                if result:
                    result_str = str(result).strip()
                    if len(result_str) > 20:
                        log.debug(
                            "[KnowledgeDigest] LLM digest ok for topic '%s' (%d chars)",
                            topic,
                            len(result_str),
                        )
                        return result_str
            except Exception as exc:
                log.debug("[KnowledgeDigest] LLM digest failed for '%s': %s", topic, exc)

        # Fallback: cleaned text, trimmed to a readable length
        return cleaned[:_MAX_FALLBACK_LENGTH]
