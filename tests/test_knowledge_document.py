"""Unit tests for KnowledgeDocument, SourceType, Provenance, and utilities."""

import pytest

from niblit_memory.knowledge_document import (
    ContentFormat,
    DocumentProvenance,
    KnowledgeDocument,
    SourceType,
    TrustLevel,
    compute_content_hash,
    _normalize_url,
    _validate_url_for_fetch,
)


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------

class TestComputeContentHash:
    def test_empty_content(self):
        h = compute_content_hash("")
        assert len(h) == 64  # SHA-256 hex length

    def test_same_content_same_hash(self):
        text = "The quick brown fox jumps over the lazy dog"
        assert compute_content_hash(text) == compute_content_hash(text)

    def test_different_content_different_hash(self):
        assert compute_content_hash("hello") != compute_content_hash("world")

    def test_whitespace_stripped(self):
        assert compute_content_hash("  hello  ") == compute_content_hash("hello")

    def test_line_ending_normalization(self):
        assert compute_content_hash("hello\r\nworld") == compute_content_hash("hello\nworld")

    def test_internal_whitespace_preserved(self):
        # Internal spaces should NOT be collapsed
        assert compute_content_hash("hello   world") != compute_content_hash("hello world")


# ---------------------------------------------------------------------------
# _normalize_url
# ---------------------------------------------------------------------------

class TestNormalizeUrl:
    def test_simple_url(self):
        assert _normalize_url("https://example.com") == "https://example.com"

    def test_scheme_lowercase(self):
        assert _normalize_url("HTTPS://Example.COM") == "https://example.com"

    def test_trailing_slash_removed(self):
        assert _normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_trailing_slash_kept_for_root(self):
        assert _normalize_url("https://example.com/") == "https://example.com/"

    def test_default_port_removed(self):
        assert _normalize_url("https://example.com:443/path") == "https://example.com/path"
        assert _normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_non_default_port_kept(self):
        assert _normalize_url("https://example.com:8443/path") == "https://example.com:8443/path"

    def test_fragment_removed(self):
        result = _normalize_url("https://example.com/path#section")
        assert "#" not in result

    def test_utm_params_stripped(self):
        url = "https://example.com/path?utm_source=google&utm_medium=cpc&keep=this"
        result = _normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "keep=this" in result

    def test_adds_scheme_if_missing(self):
        assert _normalize_url("example.com/path") == "https://example.com/path"

    def test_empty_url(self):
        assert _normalize_url("") == ""

    def test_none_url(self):
        assert _normalize_url(None) is None


# ---------------------------------------------------------------------------
# _validate_url_for_fetch
# ---------------------------------------------------------------------------

class TestValidateUrlForFetch:
    def test_localhost_blocked(self):
        assert _validate_url_for_fetch("http://localhost:8080") is not None
        assert "blocked_host" in _validate_url_for_fetch("http://localhost:8080")

    def test_127_0_0_1_blocked(self):
        assert _validate_url_for_fetch("http://127.0.0.1:8080") is not None

    def test_private_10_x_blocked(self):
        assert _validate_url_for_fetch("http://10.0.0.1/test") is not None

    def test_private_192_168_x_blocked(self):
        assert _validate_url_for_fetch("http://192.168.1.1/test") is not None

    def test_metadata_ip_blocked(self):
        assert _validate_url_for_fetch("http://169.254.169.254/latest/meta-data/") is not None

    def test_https_allowed(self):
        assert _validate_url_for_fetch("https://example.com") is None

    def test_http_allowed(self):
        assert _validate_url_for_fetch("http://example.com") is None

    def test_file_scheme_blocked(self):
        assert _validate_url_for_fetch("file:///etc/passwd") is not None

    def test_ftp_scheme_blocked(self):
        assert _validate_url_for_fetch("ftp://example.com") is not None

    def test_empty_url_blocked(self):
        assert _validate_url_for_fetch("") == "empty_url"

    def test_missing_scheme_blocked(self):
        assert _validate_url_for_fetch("example.com") == "missing_scheme"


# ---------------------------------------------------------------------------
# KnowledgeDocument
# ---------------------------------------------------------------------------

class TestKnowledgeDocument:
    def test_create_with_defaults(self):
        doc = KnowledgeDocument()
        assert doc.id
        assert doc.schema_version == "knowledge_document.v1"
        assert doc.source_type == SourceType.web_search_result.value
        assert doc.retrieved_at
        assert doc.observed_at
        assert doc.created_at

    def test_id_generation(self):
        doc1 = KnowledgeDocument()
        doc2 = KnowledgeDocument()
        assert doc1.id != doc2.id

    def test_to_dict_removes_empty_optional(self):
        doc = KnowledgeDocument(content="test")
        data = doc.to_dict()
        assert "content" in data
        assert "canonical_uri" not in data  # empty, should be removed

    def test_to_dict_keeps_non_empty(self):
        doc = KnowledgeDocument(content="test", canonical_uri="https://example.com")
        data = doc.to_dict()
        assert data["canonical_uri"] == "https://example.com"

    def test_from_dict_roundtrip(self):
        doc = KnowledgeDocument(
            content="hello world",
            source_uri="https://example.com",
            title="Test",
        )
        data = doc.to_dict()
        restored = KnowledgeDocument.from_dict(data)
        assert restored.content == "hello world"
        assert restored.source_uri == "https://example.com"
        assert restored.title == "Test"

    def test_get_trust_level(self):
        doc = KnowledgeDocument()
        assert doc.get_trust_level() == TrustLevel.external_untrusted

    def test_custom_trust_level(self):
        doc = KnowledgeDocument(
            content="test",
            provenance={"trust_level": TrustLevel.user_supplied.value},
        )
        assert doc.get_trust_level() == TrustLevel.user_supplied


# ---------------------------------------------------------------------------
# DocumentProvenance
# ---------------------------------------------------------------------------

class TestDocumentProvenance:
    def test_defaults(self):
        prov = DocumentProvenance()
        assert prov.trust_level == TrustLevel.external_untrusted.value
        assert prov.parser_version == "1.0"

    def test_to_dict_filters_empty(self):
        prov = DocumentProvenance(source_uri="https://example.com")
        data = prov.to_dict()
        assert "source_uri" in data
        assert "canonical_uri" not in data

    def test_from_dict(self):
        prov = DocumentProvenance.from_dict({
            "source_uri": "https://example.com",
            "trust_level": TrustLevel.user_supplied.value,
        })
        assert prov.source_uri == "https://example.com"
        assert prov.trust_level == TrustLevel.user_supplied.value


# ---------------------------------------------------------------------------
# SourceType enum
# ---------------------------------------------------------------------------

class TestSourceType:
    def test_values(self):
        assert SourceType.web_page.value == "web_page"
        assert SourceType.web_search_result.value == "web_search_result"
        assert SourceType.github.value == "github"
        assert SourceType.chat.value == "chat"

    def test_all_values_stable(self):
        # Ensure no accidental renames
        expected = {
            "web_page", "web_search_result", "github", "stack_overflow",
            "pypi", "file", "api", "chat", "market", "system", "research_synthesis",
        }
        assert set(st.value for st in SourceType) == expected


# ---------------------------------------------------------------------------
# TrustLevel enum
# ---------------------------------------------------------------------------

class TestTrustLevel:
    def test_values(self):
        assert TrustLevel.external_untrusted.value == "external_untrusted"
        assert TrustLevel.user_supplied.value == "user_supplied"
        assert TrustLevel.model_generated.value == "model_generated"