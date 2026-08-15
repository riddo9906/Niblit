"""Safe web fetcher with SSRF protection for Niblit.

This module provides a hardened HTTP fetcher for retrieving web pages
with security controls:
  - SSRF protection (blocks private IPs, localhost, metadata endpoints)
  - Response size limits
  - Redirect limits
  - Content type validation
  - Timeout controls
"""

from __future__ import annotations

import logging
import os
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from niblit_memory.knowledge_document import _validate_url_for_fetch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Maximum number of redirects to follow
DEFAULT_MAX_REDIRECTS: int = 5

#: Default connect timeout in seconds
DEFAULT_CONNECT_TIMEOUT: int = 10

#: Default read timeout in seconds
DEFAULT_READ_TIMEOUT: int = 20

#: Maximum response size in bytes (5 MB)
DEFAULT_MAX_RESPONSE_BYTES: int = 5_000_000

#: Allowed content types for HTML extraction
_ALLOWED_HTML_CONTENT_TYPES: set[str] = {
    "text/html",
    "text/plain",
    "text/xml",
    "application/xhtml+xml",
}

# Environment variable overrides
_ENV_CONNECT_TIMEOUT = os.getenv("NIBLIT_WEB_CONNECT_TIMEOUT_SECONDS")
_ENV_READ_TIMEOUT = os.getenv("NIBLIT_WEB_READ_TIMEOUT_SECONDS")
_ENV_MAX_REDIRECTS = os.getenv("NIBLIT_WEB_MAX_REDIRECTS")
_ENV_MAX_RESPONSE_BYTES = os.getenv("NIBLIT_WEB_MAX_RESPONSE_BYTES")


# ---------------------------------------------------------------------------
# Fetcher response
# ---------------------------------------------------------------------------

@dataclass
class FetchResponse:
    """Normalized response from a safe web fetch."""
    url: str
    status_code: int
    content: str
    content_type: str
    content_length: int
    headers: Dict[str, str]
    final_url: str
    from_cache: bool = False
    error: str = ""

    @property
    def success(self) -> bool:
        return self.status_code >= 200 and self.status_code < 300 and not self.error

    @property
    def truncated(self) -> bool:
        return self.content_length >= DEFAULT_MAX_RESPONSE_BYTES


# ---------------------------------------------------------------------------
# Safe web fetcher
# ---------------------------------------------------------------------------

class SafeWebFetcher:
    """HTTP fetcher with SSRF protection and content validation.

    Usage:
        fetcher = SafeWebFetcher()
        response = fetcher.fetch("https://example.com")
        if response.success:
            print(response.content)
    """

    def __init__(
        self,
        *,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        user_agent: str = "Niblit/1.0 (+https://github.com/riyoad/Niblit)",
    ):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def fetch(self, url: str) -> FetchResponse:
        """Fetch a single URL with safety controls.

        Returns:
            FetchResponse with status, content, and diagnostics.
        """
        # --- Pre-fetch URL validation ---
        url_error = _validate_url_for_fetch(url)
        if url_error:
            return FetchResponse(
                url=url,
                status_code=0,
                content="",
                content_type="",
                content_length=0,
                headers={},
                final_url=url,
                error=f"url_validation_failed:{url_error}",
            )

        try:
            response = self.session.get(
                url,
                timeout=(self.connect_timeout, self.read_timeout),
                allow_redirects=True,
                stream=True,
                max_redirects=self.max_redirects,
            )
        except requests.exceptions.Timeout:
            return FetchResponse(
                url=url,
                status_code=0,
                content="",
                content_type="",
                content_length=0,
                headers={},
                final_url=url,
                error="timeout",
            )
        except requests.exceptions.SSLError as exc:
            return FetchResponse(
                url=url,
                status_code=0,
                content="",
                content_type="",
                content_length=0,
                headers={},
                final_url=url,
                error=f"ssl_error:{exc}",
            )
        except requests.exceptions.RequestException as exc:
            return FetchResponse(
                url=url,
                status_code=0,
                content="",
                content_type="",
                content_length=0,
                headers={},
                final_url=url,
                error=f"request_failed:{exc}",
            )

        # --- Check final URL after redirects ---
        final_url = response.url
        final_error = _validate_url_for_fetch(final_url)
        if final_error:
            response.close()
            return FetchResponse(
                url=url,
                status_code=response.status_code,
                content="",
                content_type="",
                content_length=0,
                headers={},
                final_url=final_url,
                error=f"redirect_blocked:{final_error}",
            )

        # --- Content type validation ---
        content_type = response.headers.get("Content-Type", "")
        if not self._is_allowed_content_type(content_type):
            response.close()
            return FetchResponse(
                url=url,
                status_code=response.status_code,
                content="",
                content_type=content_type,
                content_length=0,
                headers=dict(response.headers),
                final_url=final_url,
                error=f"unsupported_content_type:{content_type}",
            )

        # --- Read response with size limit ---
        content_bytes = self._read_with_limit(response)
        response.close()

        content = content_bytes.decode("utf-8", errors="replace")
        content_length = len(content_bytes)

        return FetchResponse(
            url=url,
            status_code=response.status_code,
            content=content,
            content_type=content_type,
            content_length=content_length,
            headers=dict(response.headers),
            final_url=final_url,
            error="",
        )

    def _is_allowed_content_type(self, content_type: str) -> bool:
        """Check if content type is allowed for extraction."""
        if not content_type:
            return True  # Allow missing content type
        ct_lower = content_type.lower()
        return any(ct_lower.startswith(allowed) for allowed in _ALLOWED_HTML_CONTENT_TYPES)

    def _read_with_limit(self, response: requests.Response) -> bytes:
        """Read response body with size limit."""
        chunks = []
        total_bytes = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                total_bytes += len(chunk)
                if total_bytes > self.max_response_bytes:
                    logger.warning("[SafeWebFetcher] Response exceeded %d bytes, truncating", self.max_response_bytes)
                    break
                chunks.append(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        """Close the underlying session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()