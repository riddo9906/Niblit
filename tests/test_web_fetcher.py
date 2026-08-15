"""Unit tests for SafeWebFetcher."""

import pytest

from niblit_memory.web_fetcher import SafeWebFetcher, DEFAULT_MAX_REDIRECTS, DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT, DEFAULT_MAX_RESPONSE_BYTES


class TestSafeWebFetcher:
    def setup_method(self):
        self.fetcher = SafeWebFetcher()

    def test_blocked_localhost(self):
        response = self.fetcher.fetch("http://localhost:8080")
        assert response.success is False
        assert "blocked_host" in response.error

    def test_blocked_127(self):
        response = self.fetcher.fetch("http://127.0.0.1:8080")
        assert response.success is False
        assert "blocked_host" in response.error

    def test_blocked_private_10(self):
        response = self.fetcher.fetch("http://10.0.0.1/test")
        assert response.success is False
        assert "private_ip" in response.error

    def test_blocked_metadata_ip(self):
        response = self.fetcher.fetch("http://169.254.169.254/latest/meta-data/")
        assert response.success is False

    def test_blocked_file_scheme(self):
        response = self.fetcher.fetch("file:///etc/passwd")
        assert response.success is False
        assert "blocked_scheme" in response.error

    def test_blocked_ftp_scheme(self):
        response = self.fetcher.fetch("ftp://example.com")
        assert response.success is False
        assert "blocked_scheme" in response.error

    def test_empty_url(self):
        response = self.fetcher.fetch("")
        assert response.success is False
        assert response.error == "url_validation_failed:empty_url"

    def test_missing_scheme(self):
        response = self.fetcher.fetch("example.com")
        assert response.success is False
        assert "missing_scheme" in response.error

    def test_timeout_handling(self):
        # Use a very short timeout to trigger timeout error
        fetcher = SafeWebFetcher(connect_timeout=1, read_timeout=1)
        # This IP should timeout quickly (non-routable)
        response = fetcher.fetch("http://198.51.100.1/")
        assert response.success is False
        assert "timeout" in response.error or "request_failed" in response.error

    def test_content_type_validation(self):
        # This should pass URL validation but may fail on actual fetch
        # We're just checking the fetcher doesn't crash on valid URLs
        response = self.fetcher.fetch("http://example.com")
        # Should either succeed or fail with a network error, not a validation error
        if not response.success:
            assert "url_validation_failed" not in response.error

    def test_response_truncation_tracking(self):
        # Verify truncation property exists and defaults to False for small responses
        response = self.fetcher.fetch("http://example.com")
        if response.success:
            assert response.truncated is False

    def test_defaults(self):
        assert DEFAULT_MAX_REDIRECTS == 5
        assert DEFAULT_CONNECT_TIMEOUT == 10
        assert DEFAULT_READ_TIMEOUT == 20
        assert DEFAULT_MAX_RESPONSE_BYTES == 5_000_000