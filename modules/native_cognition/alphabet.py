"""Unicode-aware symbol and alphabet primitives for Niblit's native cognition.

Offsets always refer to the original input string. This module deliberately
does not pretend that every script has a Latin A-Z alphabet.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Iterator


LATIN_LETTER_NAMES = (
    "ay", "bee", "see", "dee", "ee", "eff", "gee", "aitch", "eye",
    "jay", "kay", "ell", "em", "en", "oh", "pee", "cue", "ar",
    "ess", "tee", "you", "vee", "double-u", "ex", "why", "zee",
)
LATIN_ALPHABET = tuple({
    "character": chr(65 + i),
    "lowercase": chr(97 + i),
    "position": i + 1,
    "name": LATIN_LETTER_NAMES[i],
    "script": "Latin",
} for i in range(26))

_SCRIPT_MARKERS = {
    "LATIN": "Latin", "GREEK": "Greek", "CYRILLIC": "Cyrillic",
    "ARABIC": "Arabic", "HEBREW": "Hebrew", "DEVANAGARI": "Devanagari",
    "BENGALI": "Bengali", "GURMUKHI": "Gurmukhi", "GUJARATI": "Gujarati",
    "TAMIL": "Tamil", "TELUGU": "Telugu", "KANNADA": "Kannada",
    "MALAYALAM": "Malayalam", "THAI": "Thai", "LAO": "Lao",
    "MYANMAR": "Myanmar", "GEORGIAN": "Georgian", "ARMENIAN": "Armenian",
    "HIRAGANA": "Hiragana", "KATAKANA": "Katakana", "HANGUL": "Hangul",
    "CJK": "Han", "IDEOGRAPH": "Han", "ETHIOPIC": "Ethiopic",
    "THAANA": "Thaana", "KHMER": "Khmer", "TIBETAN": "Tibetan",
}


def normalize_text(text: str) -> str:
    """Canonical NFC normalization; raw source text should remain separately stored."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return unicodedata.normalize("NFC", text)


def script_of(character: str) -> str:
    if len(character) != 1:
        raise ValueError("script_of expects one Unicode code point")
    name = unicodedata.name(character, "")
    for marker, script in _SCRIPT_MARKERS.items():
        if marker in name:
            return script
    category = unicodedata.category(character)
    return "Common" if category[0] in "PNZSC" else "Unknown"


def graphemes(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield approximate extended grapheme clusters with original offsets.

    Combining marks, variation selectors and ZWJ-linked code points stay with
    their base. Python's standard library has no full UAX #29 segmenter.
    """
    start = 0
    cluster = ""
    join_next = False
    for index, char in enumerate(text):
        code = ord(char)
        combining = bool(unicodedata.combining(char))
        variation = 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF
        if not cluster:
            start, cluster = index, char
        elif combining or variation or join_next or char == "\u200d":
            cluster += char
        else:
            yield start, index, cluster
            start, cluster = index, char
        join_next = char == "\u200d"
    if cluster:
        yield start, len(text), cluster


def classify_character(character: str) -> dict:
    if len(character) != 1:
        raise ValueError("classify_character expects one Unicode code point")
    category = unicodedata.category(character)
    if character.isspace():
        kind = "whitespace"
    elif category.startswith("L"):
        kind = "letter"
    elif category.startswith("M"):
        kind = "mark"
    elif category == "Nd":
        kind = "decimal_digit"
    elif category.startswith("N"):
        kind = "number_symbol"
    elif category.startswith("P"):
        kind = "punctuation"
    elif category.startswith("S"):
        kind = "symbol"
    elif category.startswith("C"):
        kind = "control_or_format"
    else:
        kind = "other"
    return {
        "character": character,
        "codepoint": f"U+{ord(character):04X}",
        "unicode_name": unicodedata.name(character, "UNNAMED"),
        "unicode_category": category,
        "kind": kind,
        "script": script_of(character),
        "combining_class": unicodedata.combining(character),
    }


def inspect_alphabet(text: str) -> dict:
    counts = Counter()
    scripts = Counter()
    unique = []
    seen = set()
    for start, end, cluster in graphemes(text):
        first = cluster[0]
        info = classify_character(first)
        counts[info["kind"]] += 1
        if info["kind"] == "letter":
            scripts[info["script"]] += 1
        if cluster not in seen:
            seen.add(cluster)
            unique.append({"unit": cluster, "start": start, "end": end,
                           "script": info["script"], "kind": info["kind"]})
    return {
        "normalization": "NFC",
        "grapheme_count": sum(counts.values()),
        "kind_counts": dict(counts),
        "script_counts": dict(scripts),
        "unique_graphemes": unique[:512],
        "latin_reference_alphabet": list(LATIN_ALPHABET),
    }
