"""Canonical KnowledgeDocument and related models for Niblit memory architecture.

This module defines the authoritative data contracts for ingested knowledge.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """Stable source type identifiers for schema stability."""
    web_page = "web_page"
    web_search_result = "web_search_result"
    github = "github"
    stack_overflow = "stack_overflow"
    pypi = "pypi"
    file = "file"
    api = "api"
    chat = "chat"
    market = "market"
    system = "system"
    research_synthesis = "research_synthesis"


class TrustLevel(str, Enum):
    """Explicit trust classification for stored content."""
    trusted_internal = "trusted_internal"
    user_supplied = "user_supplied"
    external_structured = "external_structured"
    external_untrusted = "external_untrusted"
    model_generated = "model_generated"
    derived = "derived"


class ContentFormat(str, Enum):
    """Content format identifiers."""
    text_plain = "text/plain"
    text_markdown = "text/markdown"
    application_json = "application/json"
    text_html = "text/html"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

@dataclass
class DocumentProvenance:
    """Structured provenance metadata for a knowledge document.

    Not all fields are required for every source type.
    """
    source_uri: str = ""
    canonical_uri: str = ""
    domain: str = ""

    retrieval_method: str = ""  # http, api, search, file, etc.
    search_provider: str = ""   # serpex, serpapi, duckduckgo, etc.
    fetcher: str = ""           # internet_manager, research_agent, etc.
    parser: str = ""            # html, json, markdown, etc.

    http_status: Optional[int] = None
    content_type: str = ""
    content_length: int = 0

    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    updated_at: Optional[str] = None

    author: str = ""
    title: str = ""

    source_type: str = ""  # SourceType value

    content_hash: str = ""

    parser_version: str = "1.0"
    acquisition_version: str = "1.0"

    trust_level: str = TrustLevel.external_untrusted

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "", [], {})}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentProvenance:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# KnowledgeDocument
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeDocument:
    """Canonical internal representation of ingested knowledge.

    Every piece of information that enters Niblit long-term memory
    must be representable as a KnowledgeDocument.
    """
    id: str = ""
    schema_version: str = "knowledge_document.v1"

    source_type: str = SourceType.web_search_result.value
    source_uri: str = ""
    canonical_uri: str = ""

    title: str = ""
    content: str = ""
    content_format: str = ContentFormat.text_plain.value

    author: str = ""
    language: str = ""

    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    observed_at: Optional[str] = None

    content_hash: str = ""

    metadata: Dict[str, Any] = field(default_factory=dict)

    topics: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)

    confidence: float = 0.8

    provenance: Dict[str, Any] = field(default_factory=dict)

    parser_version: str = "1.0"
    acquisition_version: str = "1.0"

    embedding_ids: List[str] = field(default_factory=list)

    created_at: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = compute_content_hash(self.content)
        if not self.id:
            self.id = self._generate_id()
        if not self.retrieved_at:
            self.retrieved_at = datetime.now(timezone.utc).isoformat()
        if not self.observed_at:
            self.observed_at = self.retrieved_at
        if not self.created_at:
            self.created_at = self.retrieved_at

    def _generate_id(self) -> str:
        if not self.source_uri and not self.content:
            from uuid import uuid4
            return "doc_" + uuid4().hex
        identity = self.source_uri + "\n" + self.content_hash
        return "doc_" + hashlib.sha256(identity.encode()).hexdigest()[:32]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Remove empty optional fields for cleaner storage
        optional_fields = [
            "canonical_uri", "author", "language", "published_at", "updated_at",
            "observed_at", "content_hash", "topics", "entities", "relationships",
            "provenance", "parser_version", "acquisition_version", "embedding_ids",
            "created_at", "schema_version",
        ]
        for f in optional_fields:
            if not data.get(f):
                data.pop(f, None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnowledgeDocument:
        # Handle provenance as dict or DocumentProvenance
        prov = data.get("provenance", {})
        if isinstance(prov, DocumentProvenance):
            prov = prov.to_dict()
        data["provenance"] = prov
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def get_trust_level(self) -> TrustLevel:
        try:
            return TrustLevel(self.provenance.get("trust_level", TrustLevel.external_untrusted.value))
        except ValueError:
            return TrustLevel.external_untrusted


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

# Common tracking parameters to strip during normalization
_TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "_ga", "ref", "source", "campaign",
    "mc_cid", "mc_eid",
}

# Domains that commonly add tracking params we want to strip
_COMMON_TRACKING_DOMAINS: set[str] = {
    "google.com", "google.co.uk", "google.ca", "google.com.au",
    "facebook.com", "youtube.com", "twitter.com", "x.com",
    "linkedin.com", "reddit.com", "amazon.com", "amazon.co.uk",
    "bing.com", "yahoo.com", "news.ycombinator.com",
}


def _normalize_url(
    url: str,
    *,
    strip_tracking: bool = True,
    remove_fragment: bool = True,
    lowercase_host: bool = True,
) -> str:
    """Normalize a URL for canonical comparison and storage.

    Handles:
      - scheme normalization (lowercase)
      - hostname casing
      - default port removal
      - fragment removal
      - common tracking parameter removal (UTM, fbclid, etc.)
      - trailing slash normalization for paths without extension

    Does NOT aggressively rewrite query strings where parameters may
    identify different content.
    """
    if not url or not isinstance(url, str):
        return url

    url = url.strip()
    if not url:
        return url

    # Add scheme if missing
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc

    # Lowercase hostname
    if lowercase_host:
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if hostname:
            # Rebuild netloc with lowercased hostname
            port = parsed.port
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("credentialed source URLs are not permitted")
            if ":" in hostname:
                hostname = f"[{hostname}]"
            if port and (scheme, port) not in {("http", 80), ("https", 443)}:
                netloc = f"{hostname}:{port}"
            else:
                netloc = hostname

    # Remove default ports
    if parsed.port == 80 and scheme == "http":
        netloc = netloc.replace(":80", "", 1)
    elif parsed.port == 443 and scheme == "https":
        netloc = netloc.replace(":443", "", 1)

    # Normalize path: remove trailing slash for non-root paths
    path = parsed.path
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Query parameter handling
    params = parse_qs(parsed.query, keep_blank_values=False)
    if strip_tracking:
        domain = parsed.hostname or ""
        if any(domain.endswith(d) for d in _COMMON_TRACKING_DOMAINS):
            params = {k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS}
        else:
            # Only strip for params that are clearly tracking
            params = {k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS}

    # Rebuild query string - preserve parameter order where possible
    if params:
        query = urlencode({k: v[0] if len(v) == 1 else v for k, v in params.items()}, doseq=True)
    else:
        query = ""

    fragment = "" if remove_fragment else parsed.fragment

    normalized = urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        query,
        fragment,
    ))

    return normalized


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def compute_content_hash(content: str, *, normalize_line_endings: bool = True) -> str:
    """Compute a deterministic SHA-256 hash for content deduplication.

    Normalization:
      - Strip leading/trailing whitespace from the document
      - Optionally normalize line endings (CRLF → LF)
      - Do NOT collapse internal whitespace (preserve structure)

    Returns hex digest.
    """
    if not content:
        return hashlib.sha256(b"").hexdigest()

    text = str(content).strip()

    if normalize_line_endings:
        text = text.replace("\r\n", "\n").replace("\r", "\n")

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SSRF / private IP protection
# ---------------------------------------------------------------------------

# Private/reserved IPv4 ranges
_PRIVATE_IPV4_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("0.0.0.0/8"),
]

# Private IPv6 ranges
_PRIVATE_IPV6_RANGES = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link-local
]

# Metadata / cloud provider IPs that should be blocked
_METADATA_IP_RANGES = [
    ipaddress.ip_network("169.254.169.254/32"),  # AWS/GCP metadata
]

_BLOCKED_SCHEMES = {"file", "ftp", "gopher", "file://", "ftp://"}


def _is_private_ip(ip_str: str) -> bool:
    """Return True if ip_str is a private/reserved IP."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for net in _PRIVATE_IPV4_RANGES + _PRIVATE_IPV6_RANGES + _METADATA_IP_RANGES:
        if addr in net:
            return True
    return False


def _validate_url_for_fetch(url: str) -> Optional[str]:
    """Validate URL for safe fetching.

    Returns None if URL is safe, or an error string if blocked.
    """
    if not url:
        return "empty_url"

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return f"invalid_url:{exc}"

    scheme = parsed.scheme.lower()
    if not scheme:
        return "missing_scheme"

    if scheme not in ("http", "https"):
        return f"blocked_scheme:{scheme}"

    hostname = parsed.hostname
    if not hostname:
        return "missing_hostname"

    # Block localhost variants
    hostname_lower = hostname.lower()
    if hostname_lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return f"blocked_host:{hostname}"

    # Resolve hostname and check all IPs
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Cannot resolve — block to be safe
        return f"unresolvable_host:{hostname}"

    for family, type_, proto, canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            return f"private_ip:{ip_str}"

    return None
