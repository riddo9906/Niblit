"""Unit tests for DocumentNormalizer."""

import pytest

from niblit_memory.document_normalizer import (
    DocumentNormalizer,
    _clean_html_to_text,
    _extract_domain,
    _extract_title_from_html,
    _extract_title_from_text,
    _infer_language,
    _normalize_timestamp,
)
from niblit_memory.knowledge_document import (
    ContentFormat,
    KnowledgeDocument,
    SourceType,
    TrustLevel,
)


class TestCleanHtmlToText:
    def test_removes_scripts(self):
        html = '<html><script>alert("xss")</script><p>Hello</p></html>'
        text = _clean_html_to_text(html)
        assert "alert" not in text
        assert "Hello" in text

    def test_removes_styles(self):
        html = '<html><style>.foo { color: red; }</style><p>World</p></html>'
        text = _clean_html_to_text(html)
        assert "color" not in text
        assert "World" in text

    def test_decodes_entities(self):
        html = "<p>& < > &nbsp;</p>"
        text = _clean_html_to_text(html)
        assert "&" in text
        assert "<" in text
        assert ">" in text

    def test_collapses_whitespace(self):
        html = "<p>   Hello    World   </p>"
        text = _clean_html_to_text(html)
        assert text == "Hello World"

    def test_empty_input(self):
        assert _clean_html_to_text("") == ""


class TestExtractTitleFromHtml:
    def test_basic_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        assert _extract_title_from_html(html) == "My Page"

    def test_no_title(self):
        assert _extract_title_from_html("<html><body>No title</body></html>") == ""

    def test_empty_input(self):
        assert _extract_title_from_html("") == ""


class TestInferLanguage:
    def test_english(self):
        assert _infer_language("Hello world") == "en"

    def test_chinese(self):
        assert _infer_language("你好世界") == "zh"

    def test_japanese(self):
        assert _infer_language("こんにちは") == "ja"

    def test_korean(self):
        assert _infer_language("안녕하세요") == "ko"

    def test_arabic(self):
        assert _infer_language("مرحبا") == "ar"

    def test_empty(self):
        assert _infer_language("") == ""


class TestExtractDomain:
    def test_basic_domain(self):
        assert _extract_domain("https://example.com/path") == "example.com"

    def test_with_port(self):
        assert _extract_domain("https://example.com:8443/path") == "example.com"

    def test_empty(self):
        assert _extract_domain("") == ""


class TestNormalizeTimestamp:
    def test_none(self):
        assert _normalize_timestamp(None) is None

    def test_iso_string(self):
        result = _normalize_timestamp("2024-01-15T10:30:00Z")
        assert "2024-01-15" in result

    def test_unix_timestamp(self):
        result = _normalize_timestamp(1705327200)
        assert "2024-01-15" in result


class TestDocumentNormalizer:
    def setup_method(self):
        self.normalizer = DocumentNormalizer()

    def test_normalize_dict_text(self):
        doc = self.normalizer.normalize(
            raw={"text": "Hello world", "url": "https://example.com"},
            source_type=SourceType.web_page,
        )
        assert doc.content == "Hello world"
        assert doc.source_uri == "https://example.com"

    def test_normalize_string(self):
        doc = self.normalizer.normalize(
            raw="Plain text content",
            source_type=SourceType.file,
        )
        assert doc.content == "Plain text content"

    def test_default_trust_is_external_untrusted(self):
        doc = self.normalizer.normalize(
            raw={"text": "test"},
            source_type=SourceType.web_page,
        )
        assert doc.get_trust_level() == TrustLevel.external_untrusted

    def test_custom_trust(self):
        doc = self.normalizer.normalize(
            raw={"text": "test"},
            source_type=SourceType.web_page,
            trust_level=TrustLevel.user_supplied,
        )
        assert doc.get_trust_level() == TrustLevel.user_supplied

    def test_content_hash_computed(self):
        doc = self.normalizer.normalize(
            raw={"text": "hello world"},
            source_type=SourceType.web_page,
        )
        assert doc.content_hash
        assert len(doc.content_hash) == 64

    def test_id_generated(self):
        doc = self.normalizer.normalize(
            raw={"text": "test"},
            source_type=SourceType.web_page,
        )
        assert doc.id
        assert doc.id.startswith("doc_")

    def test_metadata_populated(self):
        doc = self.normalizer.normalize(
            raw={"text": "test"},
            source_type=SourceType.web_page,
        )
        assert "source_type" in doc.metadata
        assert "trust_level" in doc.metadata

    def test_html_extraction(self):
        doc = self.normalizer.normalize(
            raw={
                "html": "<html><body><p>Article text here</p></body></html>",
                "url": "https://example.com",
            },
            source_type=SourceType.web_page,
        )
        assert "Article text here" in doc.content
        assert doc.content_format == ContentFormat.text_html.value

    def test_search_result_normalization(self):
        doc = self.normalizer.normalize_search_result(
            {"text": "Search snippet", "url": "https://example.com"},
            query="test query",
            search_provider="serpex",
        )
        assert doc.source_type == SourceType.web_search_result.value
        assert doc.confidence == 0.7

    def test_github_result_normalization(self):
        doc = self.normalizer.normalize_github_result(
            {"text": "code snippet", "url": "https://github.com/owner/repo"},
            repository="owner/repo",
            path="src/main.py",
        )
        assert doc.source_type == SourceType.github.value
        assert doc.confidence == 0.75
        assert doc.metadata.get("repository") == "owner/repo"

    def test_chat_message_normalization(self):
        doc = self.normalizer.normalize_chat_message(
            role="user",
            content="Hello assistant",
            source="cli",
        )
        assert doc.source_type == SourceType.chat.value
        assert doc.metadata.get("role") == "user"