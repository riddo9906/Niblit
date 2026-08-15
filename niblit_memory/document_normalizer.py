"""DocumentNormalizer — converts raw sources into canonical KnowledgeDocuments.

This module provides deterministic normalization for:
  - Web search results
  - Fetched web pages
  - GitHub search results
  - File contents
  - API responses
  - Chat messages
  - Market data
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from niblit_memory.knowledge_document import (
    ContentFormat,
    KnowledgeDocument,
    SourceType,
    TrustLevel,
    compute_content_hash,
    _normalize_url,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_title_from_html(html_text: str) -> str:
    """Extract <title> from HTML if present."""
    if not html_text:
        return ""
    match = re.search(r'<title[^>]*>(.*?)</title>', html_text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_canonical_url_from_html(html_text: str) -> str:
    """Extract canonical URL from <link rel="canonical"> if present."""
    if not html_text:
        return ""
    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _infer_language(text: str) -> str:
    """Rudimentary language detection based on character ranges."""
    if not text:
        return ""
    # Check for CJK
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_chars / max(len(text), 1) > 0.1:
        return "zh"
    # Check for Japanese
    jp_chars = sum(1 for c in text if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff')
    if jp_chars > 10:
        return "ja"
    # Check for Korean
    ko_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
    if ko_chars > 10:
        return "ko"
    # Check for Arabic
    ar_chars = sum(1 for c in text if '\u0600' <= c <= '\u06ff')
    if ar_chars > 10:
        return "ar"
    # Default to English/Latin
    return "en"


def _clean_html_to_text(html_text: str) -> str:
    """Basic HTML-to-text conversion.

    Removes scripts, styles, and tags while preserving whitespace structure.
    This is a lightweight alternative to full readability extraction.
    """
    if not html_text:
        return ""

    # Remove scripts and styles
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.IGNORECASE | re.DOTALL)

    # Remove all tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # Decode HTML entities
    text = text.replace('&nbsp;', ' ').replace('<', '<').replace('>', '>').replace('&', '&')

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _normalize_timestamp(ts: Any) -> Optional[str]:
    """Normalize various timestamp formats to ISO format."""
    if ts is None:
        return None
    if isinstance(ts, str):
        # Already a string — try to parse and re-format
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.isoformat()
        except ValueError:
            return ts
    if isinstance(ts, (int, float)):
        # Unix timestamp
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            return None
    return None


# ---------------------------------------------------------------------------
# DocumentNormalizer
# ---------------------------------------------------------------------------

class DocumentNormalizer:
    """Converts raw inputs into canonical KnowledgeDocuments.

    Usage:
        normalizer = DocumentNormalizer()
        doc = normalizer.normalize(
            raw={"text": "...", "url": "..."},
            source_type=SourceType.web_page,
            trust_level=TrustLevel.external_untrusted,
        )
    """

    def __init__(self, *, default_trust: TrustLevel = TrustLevel.external_untrusted):
        self.default_trust = default_trust

    def normalize(
        self,
        raw: Any,
        *,
        source_type: SourceType,
        trust_level: Optional[TrustLevel] = None,
        provenance: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocument:
        """Normalize raw input into a KnowledgeDocument.

        Args:
            raw: Raw input (dict or str).
            source_type: The type of source.
            trust_level: Trust classification. Defaults to external_untrusted for web.
            provenance: Optional pre-built provenance dict.
            metadata: Optional extra metadata.

        Returns:
            KnowledgeDocument with populated fields.
        """
        trust = trust_level or self.default_trust
        prov_data = dict(provenance or {})
        meta = dict(metadata or {})

        # Extract common fields from raw dict
        text = ""
        source_uri = ""
        title = ""
        author = ""
        published_at = None
        updated_at = None
        content_format = ContentFormat.text_plain
        raw_html = ""

        if isinstance(raw, dict):
            text = raw.get("text") or raw.get("content") or raw.get("snippet") or raw.get("description") or ""
            source_uri = raw.get("url") or raw.get("link") or raw.get("source_uri") or ""
            title = raw.get("title") or ""
            author = raw.get("author") or ""
            published_at = _normalize_timestamp(raw.get("published_at") or raw.get("published") or raw.get("created_at"))
            updated_at = _normalize_timestamp(raw.get("updated_at") or raw.get("modified_at"))
            raw_html = raw.get("html") or raw.get("raw_html") or ""

            # Detect content format
            content_type = raw.get("content_type", "")
            if content_type:
                if "html" in content_type:
                    content_format = ContentFormat.text_html
                elif "json" in content_type:
                    content_format = ContentFormat.application_json
                elif "markdown" in content_type or "md" in content_type:
                    content_format = ContentFormat.text_markdown

            # If we have HTML but no text, extract text from it
            if raw_html and not text:
                text = _clean_html_to_text(raw_html)
                title = title or _extract_title_from_html(raw_html)
                canonical = _extract_canonical_url_from_html(raw_html)
                if canonical:
                    source_uri = source_uri or canonical
                content_format = ContentFormat.text_html

            # If still no text, skip
            if not text and not raw_html:
                logger.debug("[DocumentNormalizer] Empty text for source_type=%s uri=%s", source_type.value, source_uri)

        elif isinstance(raw, str):
            text = raw
            content_format = ContentFormat.text_plain

        # Normalize content
        text = str(text).strip()

        # Compute content hash
        content_hash = compute_content_hash(text)

        # Normalize URI
        canonical_uri = _normalize_url(source_uri) if source_uri else ""
        if canonical_uri:
            source_uri = canonical_uri

        # Infer language
        language = _infer_language(text)

        # Build provenance
        prov_data.setdefault("source_uri", source_uri)
        prov_data.setdefault("canonical_uri", canonical_uri)
        prov_data.setdefault("domain", _extract_domain(source_uri))
        prov_data.setdefault("source_type", source_type.value)
        prov_data.setdefault("trust_level", (trust or self.default_trust).value)
        prov_data.setdefault("content_hash", content_hash)
        prov_data.setdefault("retrieved_at", datetime.now(timezone.utc).isoformat())
        if published_at:
            prov_data["published_at"] = published_at
        if updated_at:
            prov_data["updated_at"] = updated_at
        if author:
            prov_data["author"] = author
        if title:
            prov_data["title"] = title

        # Build metadata
        meta.setdefault("source_type", source_type.value)
        meta.setdefault("trust_level", (trust or self.default_trust).value)
        if raw_html:
            meta["raw_html_length"] = len(raw_html)

        doc = KnowledgeDocument(
            source_type=source_type.value,
            source_uri=source_uri,
            canonical_uri=canonical_uri,
            title=title or _extract_title_from_text(text),
            content=text,
            content_format=content_format.value,
            author=author,
            language=language,
            published_at=published_at,
            updated_at=updated_at,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            observed_at=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
            metadata=meta,
            provenance=prov_data,
            confidence=_default_confidence_for_trust(trust or self.default_trust),
        )

        return doc

    def normalize_search_result(
        self,
        result: Dict[str, Any],
        *,
        query: str = "",
        search_provider: str = "",
    ) -> KnowledgeDocument:
        """Normalize a search result snippet into a KnowledgeDocument.

        Search results are NOT full pages — they are marked as web_search_result
        and stored with lower confidence than fetched pages.
        """
        prov = {
            "search_provider": search_provider or result.get("source", ""),
            "retrieval_method": "search",
            "query": query,
        }
        meta = {
            "query": query,
            "search_provider": search_provider or result.get("source", ""),
        }

        doc = self.normalize(
            raw=result,
            source_type=SourceType.web_search_result,
            trust_level=TrustLevel.external_untrusted,
            provenance=prov,
            metadata=meta,
        )
        # Lower confidence for search snippets
        doc.confidence = 0.7
        return doc

    def normalize_github_result(
        self,
        result: Dict[str, Any],
        *,
        repository: str = "",
        path: str = "",
        commit: str = "",
    ) -> KnowledgeDocument:
        """Normalize a GitHub search result into a KnowledgeDocument."""
        source_uri = result.get("url") or result.get("html_url") or ""
        prov = {
            "source_uri": source_uri,
            "canonical_uri": _normalize_url(source_uri),
            "domain": "github.com",
            "retrieval_method": "api",
            "search_provider": "github",
            "fetcher": "research_agent",
            "source_type": SourceType.github.value,
            "trust_level": TrustLevel.external_structured.value,
            "repository": repository,
            "path": path,
            "commit": commit,
        }
        meta = {
            "repository": repository,
            "path": path,
            "commit": commit,
            "source_type": SourceType.github.value,
        }

        doc = self.normalize(
            raw=result,
            source_type=SourceType.github,
            trust_level=TrustLevel.external_structured,
            provenance=prov,
            metadata=meta,
        )
        doc.confidence = 0.75
        return doc

    def normalize_chat_message(
        self,
        role: str,
        content: str,
        *,
        source: str = "chat",
    ) -> KnowledgeDocument:
        """Normalize a chat message into a KnowledgeDocument."""
        prov = {
            "source_uri": f"chat:{source}:{role}",
            "retrieval_method": "chat",
            "source_type": SourceType.chat.value,
            "trust_level": TrustLevel.model_generated.value if role == "assistant" else TrustLevel.user_supplied.value,
        }
        meta = {
            "role": role,
            "source": source,
        }

        doc = self.normalize(
            raw={"text": content, "role": role},
            source_type=SourceType.chat,
            trust_level=TrustLevel.model_generated if role == "assistant" else TrustLevel.user_supplied,
            provenance=prov,
            metadata=meta,
        )
        doc.confidence = 0.5 if role == "assistant" else 0.9
        return doc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        return hostname.lower() if hostname else ""
    except Exception:
        return ""


def _extract_title_from_text(text: str, max_len: int = 120) -> str:
    """Extract a title from the first line or sentence of text."""
    if not text:
        return ""
    # Take first line
    first_line = text.split("\n")[0].strip()
    # Or first sentence
    sentences = re.split(r'(?<=[.!?])\s+', first_line)
    title = sentences[0] if sentences else first_line
    # Truncate
    if len(title) > max_len:
        title = title[:max_len - 3] + "..."
    return title


def _default_confidence_for_trust(trust: TrustLevel) -> float:
    """Return default confidence based on trust level."""
    mapping = {
        TrustLevel.trusted_internal: 1.0,
        TrustLevel.user_supplied: 0.9,
        TrustLevel.external_structured: 0.8,
        TrustLevel.external_untrusted: 0.7,
        TrustLevel.model_generated: 0.5,
        TrustLevel.derived: 0.6,
    }
    return mapping.get(trust, 0.7)