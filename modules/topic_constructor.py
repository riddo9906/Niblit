#!/usr/bin/env python3
"""
TOPIC CONSTRUCTOR
Builds safe, search-API-friendly research topic queries that avoid:

  • HTTP 403  — server rejects oversized or malformed query strings
  • HTTP 443  — SSL/TLS connection timeout caused by query strings that are
                too long for the HTTPS handshake buffer or contain characters
                that confuse URL-parsing middleware
  • Timeouts  — search backends (Serpex, DuckDuckGo, GitHub, Searchcode) have
                implicit query-size limits; exceeding them causes silent hangs

Strategy
--------
1. Strip every character that is illegal or awkward in a URL query string.
2. Remove non-ASCII bytes that bloat percent-encoded URLs.
3. Aggressively strip stop-words from long phrases.
4. Keep only the highest-signal keywords (shortest words that carry meaning
   tend to be the most search-able).
5. Hard-cap at MAX_WORDS (5) and MAX_LENGTH (60 chars) — both well inside
   every major search API's documented safe limits.
6. Validate that urllib.parse.urlencode would not expand the query beyond
   MAX_ENCODED_LENGTH (128 chars) and trim further if needed.

Usage
-----
    from modules.topic_constructor import TopicConstructor
    tc = TopicConstructor()

    # Single topic
    safe = tc.build("some very long topic with lots of extra words and filler")
    # → e.g. "long topic extra words"

    # Batch
    queries = tc.build_batch(raw_topic_list, max_topics=20)

    # Cycle-aware (ALE helper)
    query = tc.select_for_cycle(topics, index=5)
"""

import re
import logging
import unicodedata
from typing import List, Optional
from urllib.parse import quote

log = logging.getLogger("TopicConstructor")

# ── Hard limits ───────────────────────────────────────────────────────────────

# Maximum *raw* characters in the cleaned query string.
# 60 chars fits comfortably in any search API's query parameter and avoids
# HTTPS middleware issues that manifest as error 443 timeouts.
_MAX_QUERY_LENGTH: int = 60

# Maximum number of words — keeps the URL short and the query focused.
_MAX_QUERY_WORDS: int = 5

# Maximum percent-encoded length (after urllib.parse.quote).
# A 60-char ASCII string encodes to ≤60 chars; this cap guards against
# topics that are short in raw chars but expand when encoded (rare but real).
_MAX_ENCODED_LENGTH: int = 128

# ── Unsafe character patterns ─────────────────────────────────────────────────

# Characters that are either illegal in URL query strings, trigger 403/443
# on some proxies, or cause silent request failures on search backends.
# Includes: angle brackets, braces, pipes, backslash, caret, brackets,
# backtick, semicolon, dollar, ampersand, plus, comma, slash, question,
# at-sign, equals, hash, percent, colon, apostrophe, quote, exclamation,
# tilde, asterisk, parentheses, period (trailing only — handled separately).
_UNSAFE_RE = re.compile(r'[<>"\{\}\|\\\^\[\]`;\$&\+,/\?@=#%:\'!()*~]')

# A run of whitespace (including tabs, newlines) → single space
_WHITESPACE_RE = re.compile(r'\s+')

# Any character that is not a plain ASCII letter, digit, hyphen, or space
_NON_ASCII_WORD_RE = re.compile(r'[^\x20\x2D\x30-\x39\x41-\x5A\x61-\x7A]')

# Trailing/leading punctuation on individual words
_WORD_BOUNDARY_RE = re.compile(r'^[\-\.]|[\-\.]$')

# ── Stop-words ────────────────────────────────────────────────────────────────

# Comprehensive list of words that add URL length without search signal.
# Kept sorted for readability; looked-up as a frozenset for O(1) performance.
_STOP_WORDS: frozenset = frozenset({
    # articles & determiners
    "a", "an", "the", "this", "that", "these", "those", "some", "any",
    "all", "every", "each", "both", "either", "neither", "no",
    # conjunctions
    "and", "or", "but", "nor", "so", "yet", "for",
    # prepositions
    "in", "on", "at", "to", "of", "with", "by", "from", "into", "onto",
    "upon", "over", "under", "above", "below", "between", "among", "through",
    "during", "before", "after", "since", "until", "about", "around",
    "against", "along", "across", "behind", "beyond", "near", "off", "out",
    "past", "per", "toward", "towards", "via", "within", "without",
    # pronouns
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
    # auxiliary & modal verbs
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "can",
    "shall", "need", "dare", "ought",
    # common adverbs / filler
    "also", "as", "if", "then", "than", "like", "just", "only", "very",
    "more", "most", "much", "many", "few", "such", "own",
    "how", "what", "which", "when", "where", "who", "why", "whether",
    "here", "there", "now", "up", "down",
    # connective phrases (appear as individual tokens after splitting)
    "using", "use", "used", "uses",
    "based", "given", "like", "well", "way", "make", "makes",
    "new", "good", "best", "right", "different", "same",
})

# ── Fallback query ────────────────────────────────────────────────────────────
_FALLBACK_QUERY: str = "machine learning"


class TopicConstructor:
    """Constructs safe, concise, search-API-friendly topic query strings.

    All public methods guarantee:
      * Output ≤ MAX_QUERY_LENGTH raw characters
      * Output ≤ MAX_QUERY_WORDS words
      * Output contains only printable ASCII (a-z A-Z 0-9 space hyphen)
      * URL-encoded form ≤ MAX_ENCODED_LENGTH characters
      * No characters that trigger HTTP 403 or 443 on common search APIs

    Methods
    -------
    build(raw_topic)
        Return a single cleaned, cut-down query string.
    build_batch(topics, max_topics)
        Return a de-duplicated list of safe queries.
    is_safe(query)
        Return True if the query can be used as-is without modification.
    validate(query)
        Return (is_valid, reason) explaining any safety failure.
    select_for_cycle(topics, index)
        Pick topic at index mod len and return it cleaned (ALE helper).
    """

    def __init__(
        self,
        max_length: int = _MAX_QUERY_LENGTH,
        max_words: int = _MAX_QUERY_WORDS,
        max_encoded_length: int = _MAX_ENCODED_LENGTH,
    ):
        self.max_length = max_length
        self.max_words = max_words
        self.max_encoded_length = max_encoded_length

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def is_safe(self, query: str) -> bool:
        """Return True if *query* passes all safety checks without modification."""
        ok, _ = self.validate(query)
        return ok

    def validate(self, query: str) -> tuple:
        """Return *(is_valid: bool, reason: str)* for the given query string.

        When *is_valid* is False, *reason* explains the first violation found.
        Callers can use this for logging or debugging without needing to
        re-run :meth:`build`.
        """
        if not query or not isinstance(query, str):
            return False, "empty or non-string"
        if len(query) > self.max_length:
            return False, f"too long: {len(query)} > {self.max_length} chars"
        if len(query.split()) > self.max_words:
            return False, f"too many words: {len(query.split())} > {self.max_words}"
        if _UNSAFE_RE.search(query):
            return False, "contains unsafe characters"
        try:
            encoded = quote(query, safe=" ")
            if len(encoded) > self.max_encoded_length:
                return False, f"URL-encoded too long: {len(encoded)} > {self.max_encoded_length}"
        except Exception:
            return False, "URL encoding failed"
        return True, "ok"

    def build(self, raw_topic: str) -> str:
        """Return a cleaned, cut-down query string from *raw_topic*.

        Pipeline
        --------
        1.  Coerce to string and strip whitespace.
        2.  Normalise Unicode → ASCII transliteration (NFD + strip combining).
        3.  Remove all characters that trigger 403 / 443 or URL issues.
        4.  Collapse whitespace runs to a single space.
        5.  Remove non-ASCII characters that survived step 2-3.
        6.  Split into words; strip leading/trailing punctuation per word.
        7.  Remove duplicate words (order-preserving).
        8.  Aggressively strip stop-words when phrase has ≥ 3 words.
        9.  Trim individual words that are too long (> 30 chars — URL safe).
        10. Truncate to *max_words* words.
        11. Hard-truncate to *max_length* characters at a word boundary.
        12. Validate URL-encoded length; trim further one word at a time.
        13. Lowercase the final result for consistent API cache hits.
        14. Fallback to _FALLBACK_QUERY if result is empty.
        """
        if not isinstance(raw_topic, str):
            raw_topic = str(raw_topic) if raw_topic else ""
        if not raw_topic.strip():
            return _FALLBACK_QUERY

        # 1. Strip
        text = raw_topic.strip()

        # 2. Unicode → ASCII (transliterate accented chars, drop combining marks)
        try:
            text = unicodedata.normalize("NFD", text)
            text = "".join(c for c in text if unicodedata.category(c) != "Mn")
            text = text.encode("ascii", errors="ignore").decode("ascii")
        except Exception:
            text = text.encode("ascii", errors="ignore").decode("ascii")

        # 3. Remove unsafe URL / 403 / 443 characters
        text = _UNSAFE_RE.sub(" ", text)

        # 4. Collapse whitespace
        text = _WHITESPACE_RE.sub(" ", text).strip()

        # 5. Strip any remaining non-ASCII word characters
        text = _NON_ASCII_WORD_RE.sub("", text)
        text = _WHITESPACE_RE.sub(" ", text).strip()

        if not text:
            return _FALLBACK_QUERY

        # 6. Per-word cleanup: strip leading/trailing hyphens/periods
        raw_words = text.split()
        clean_words: List[str] = []
        for w in raw_words:
            w = _WORD_BOUNDARY_RE.sub("", w).strip()
            if w:
                clean_words.append(w)

        if not clean_words:
            return _FALLBACK_QUERY

        # 7. Remove duplicate words (case-insensitive, order-preserving)
        seen_lower: set = set()
        deduped: List[str] = []
        for w in clean_words:
            lw = w.lower()
            if lw not in seen_lower:
                seen_lower.add(lw)
                deduped.append(w)
        clean_words = deduped

        # 8. Strip stop-words when there are enough keywords to survive pruning
        if len(clean_words) >= 3:
            filtered = [w for w in clean_words if w.lower() not in _STOP_WORDS]
            # Only apply if at least 2 meaningful words survive
            if len(filtered) >= 2:
                clean_words = filtered

        # 9. Trim individual words > 30 chars (very long tokens bloat URLs)
        clean_words = [w[:30] for w in clean_words]

        # 10. Truncate to max_words
        clean_words = clean_words[: self.max_words]

        # 11. Hard-truncate to max_length at a word boundary
        text = " ".join(clean_words)
        if len(text) > self.max_length:
            text = text[: self.max_length].rsplit(" ", 1)[0].strip()

        # 12. Validate URL-encoded length; drop trailing words until it fits
        words_now = text.split()
        while words_now:
            candidate = " ".join(words_now)
            try:
                encoded_len = len(quote(candidate, safe=" "))
            except Exception:
                encoded_len = len(candidate) * 3  # worst-case percent-encoding
            if encoded_len <= self.max_encoded_length:
                text = candidate
                break
            words_now.pop()
        else:
            text = ""

        # 13. Lowercase for consistent cache hits across search backends
        text = text.lower().strip()

        # 14. Fallback
        return text or _FALLBACK_QUERY

    # ─────────────────────────────────────────────────────────────────────────

    def build_batch(
        self,
        topics: List[str],
        max_topics: Optional[int] = None,
    ) -> List[str]:
        """Return a de-duplicated list of safe queries built from *topics*.

        Parameters
        ----------
        topics:
            Raw topic strings (may be long, contain stop-words, etc.).
        max_topics:
            Cap the returned list at this many entries.  ``None`` = no cap.
        """
        seen: set = set()
        result: List[str] = []
        for t in topics:
            safe = self.build(t)
            if safe and safe not in seen:
                seen.add(safe)
                result.append(safe)
                if max_topics and len(result) >= max_topics:
                    break
        return result

    # ─────────────────────────────────────────────────────────────────────────

    def select_for_cycle(self, topics: List[str], index: int) -> str:
        """Pick the topic at *index* (mod len) and return it cleaned.

        Convenience wrapper used by ALE's ``_select_next_topic()`` so the
        topic fed into every research step is always search-API safe.
        """
        if not topics:
            return _FALLBACK_QUERY
        raw = topics[index % len(topics)]
        return self.build(raw)
