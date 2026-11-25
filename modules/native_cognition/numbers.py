"""Deterministic numeric parsing for native cognition; no model or eval needed."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction


_NUMERIC_RE = re.compile(
    r"(?<![\w])(?P<currency>R\s*)?(?P<sign>[+-]?)"
    r"(?P<number>\d+/\d+|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<percent>\s*%)?(?![\w])", re.IGNORECASE
)
_SMALL = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALE = {"hundred": 100, "thousand": 1000, "million": 1_000_000,
          "billion": 1_000_000_000}


def parse_numeric_literal(raw: str) -> dict | None:
    text = raw.strip()
    currency = "ZAR" if re.match(r"^R\s*", text, re.IGNORECASE) else None
    text = re.sub(r"^R\s*", "", text, flags=re.IGNORECASE).replace(",", "")
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        if "/" in text:
            value = Fraction(text)
            decimal = Decimal(value.numerator) / Decimal(value.denominator)
            kind = "fraction"
        else:
            value = Decimal(text)
            decimal = value
            kind = "decimal" if "." in text else "integer"
    except (ValueError, ZeroDivisionError, InvalidOperation):
        return None
    sign = -1 if decimal < 0 else 1
    if percent:
        decimal /= Decimal(100)
        kind = "percentage"
    return {
        "raw": raw,
        "currency": currency,
        "kind": kind,
        "value": format(decimal, "f"),
        "sign": sign,
        "is_integer": decimal == decimal.to_integral_value(),
    }


def parse_english_number_words(text: str) -> dict | None:
    """Parse a bounded English cardinal/decimal phrase (up to billions)."""
    words = re.findall(r"[a-z]+", text.casefold().replace("-", " "))
    if not words:
        return None
    negative = False
    if words and words[0] in {"minus", "negative"}:
        negative = True
        words = words[1:]
    elif words and words[0] == "plus":
        words = words[1:]
    if not words:
        return None
    if "point" in words:
        point = words.index("point")
        whole = _parse_integer_words(words[:point])
        fraction_words = words[point + 1:]
        if whole is None or not fraction_words or any(w not in _SMALL or _SMALL[w] > 9 for w in fraction_words):
            return None
        fractional = "".join(str(_SMALL[w]) for w in fraction_words)
        value = Decimal(whole) + Decimal("0." + fractional)
        if negative:
            value = -value
        return {"raw": text, "kind": "word_decimal", "value": format(value, "f"),
                "sign": -1 if negative else 1, "is_integer": False}
    whole = _parse_integer_words(words)
    if whole is None:
        return None
    value = -whole if negative else whole
    return {"raw": text, "kind": "word_integer", "value": str(value),
            "sign": -1 if negative else 1, "is_integer": True}


def _parse_integer_words(words: list[str]) -> int | None:
    if not words or any(w not in _SMALL and w not in _TENS and w not in _SCALE and w != "and" for w in words):
        return None
    total = current = 0
    consumed = False
    for word in words:
        if word == "and":
            continue
        consumed = True
        if word in _SMALL:
            current += _SMALL[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = max(1, current) * 100
        else:
            scale = _SCALE[word]
            if scale == 100:
                current = max(1, current) * scale
            else:
                total += max(1, current) * scale
                current = 0
    return total + current if consumed else None


def extract_numeric_literals(text: str) -> list[dict]:
    found = []
    for match in _NUMERIC_RE.finditer(text):
        parsed = parse_numeric_literal(match.group(0))
        if parsed:
            parsed.update(start=match.start(), end=match.end())
            found.append(parsed)
    return found


def extract_number_word_phrases(text: str) -> list[dict]:
    """Find bounded English number phrases inside ordinary sentences."""
    allowed = set(_SMALL) | set(_TENS) | set(_SCALE) | {
        "and", "point", "minus", "negative", "plus",
    }
    tokens = list(re.finditer(r"[A-Za-z]+(?:-[A-Za-z]+)*", text))
    found = []
    index = 0
    while index < len(tokens):
        parts = tokens[index].group(0).casefold().split("-")
        if not all(part in allowed for part in parts):
            index += 1
            continue
        start_index = index
        end_index = index + 1
        while end_index < len(tokens):
            gap = text[tokens[end_index - 1].end():tokens[end_index].start()]
            next_parts = tokens[end_index].group(0).casefold().split("-")
            if (len(gap) > 3 or any(not char.isspace() and char != "-" for char in gap)
                    or not all(part in allowed for part in next_parts)):
                break
            end_index += 1
        start = tokens[start_index].start()
        end = tokens[end_index - 1].end()
        phrase = text[start:end]
        parsed = parse_english_number_words(phrase)
        if parsed:
            parsed.update(start=start, end=end)
            found.append(parsed)
        index = max(start_index + 1, end_index)
    return found
