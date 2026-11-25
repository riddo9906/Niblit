"""Small, inspectable language primitives; offsets refer to original text."""
from __future__ import annotations

import re
import unicodedata


_TOKEN_RE = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)

LEXICAL_CLASSES = {
    "determiner": set("a an the this that these those each every some any no".split()),
    "pronoun": set("i me my mine we us our you your he him his she her it its they them their who whom what which".split()),
    "auxiliary": set("am is are was were be been being do does did have has had".split()),
    "modal": set("can could may might must shall should will would".split()),
    "negation": set("not never neither nor n't".split()),
    "conjunction": set("and or but yet so although because while if unless".split()),
    "preposition": set("in on at by for from to with without about above below under over between through during before after into onto of as".split()),
    "question": set("who whom whose what which when where why how".split()),
    "quantifier": set("all both each every few many much more most less least several enough".split()),
    "temporal": set("now today yesterday tomorrow earlier later soon always never often sometimes".split()),
    "causal": set("because therefore thus hence consequently causes caused leads led result results due".split()),
    "comparison": set("more less most least greater smaller larger higher lower equal than versus compared".split()),
    "definition": set("means defined refers represents called known".split()),
}
_STOP_WORDS = set().union(*LEXICAL_CLASSES.values()) | {
    "of", "to", "in", "on", "for", "with", "a", "an", "the", "is", "are",
    "was", "were", "be", "been", "being", "it", "this", "that",
}
_IRREGULAR = {
    "is": ("be", "verb"), "are": ("be", "verb"), "was": ("be", "verb"),
    "were": ("be", "verb"), "has": ("have", "verb"), "had": ("have", "verb"),
    "does": ("do", "verb"), "did": ("do", "verb"), "went": ("go", "verb"),
    "gone": ("go", "verb"), "better": ("good", "adjective"),
    "best": ("good", "adjective"), "worse": ("bad", "adjective"),
    "worst": ("bad", "adjective"),
}


def normalize_word(word: str) -> str:
    return unicodedata.normalize("NFKC", word).casefold().replace("’", "'")


def classify_word(word: str) -> dict:
    normalized = normalize_word(word)
    classes = [name for name, words in LEXICAL_CLASSES.items() if normalized in words]
    if normalized.endswith("n't") and "negation" not in classes:
        classes.append("negation")
    lemma, pos = _IRREGULAR.get(normalized, (normalized, "unknown"))
    if pos == "unknown":
        if normalized.endswith("ly") and len(normalized) > 3:
            pos = "adverb"
        elif normalized.endswith(("ing", "ed")) and len(normalized) > 4:
            pos = "verb_form"
        elif normalized.endswith(("ous", "ful", "able", "ive", "al")) and len(normalized) > 4:
            pos = "adjective"
        elif normalized.isalpha():
            pos = "content_word"
        else:
            pos = "symbol"
    if not lemma or lemma == normalized:
        lemma = normalized
    return {
        "normalized": normalized,
        "lemma_hint": lemma,
        "part_of_speech_hint": pos,
        "lexical_classes": classes,
        "is_stop_word": normalized in _STOP_WORDS,
    }


def tokenize(text: str) -> list[dict]:
    tokens = []
    for match in _TOKEN_RE.finditer(text):
        raw = match.group(0)
        info = classify_word(raw) if any(ch.isalpha() for ch in raw) else {
            "normalized": raw, "lemma_hint": raw, "part_of_speech_hint": "punctuation",
            "lexical_classes": [], "is_stop_word": False,
        }
        tokens.append({
            "text": raw, "start": match.start(), "end": match.end(),
            **info,
        })
    return tokens


def split_sentences(text: str) -> list[dict]:
    """Split on terminal punctuation while retaining exact source spans."""
    result = []
    start = 0
    for match in re.finditer(r"[.!?؟。！？]+(?:[\"'’”)\]]*)", text):
        end = match.end()
        left = start
        while left < end and text[left].isspace():
            left += 1
        if text[left:end].strip():
            result.append({"text": text[left:end].strip(), "start": left, "end": end})
        start = end
    if text[start:].strip():
        left = start
        while left < len(text) and text[left].isspace():
            left += 1
        result.append({"text": text[left:].strip(), "start": left, "end": len(text)})
    return result


def sentence_signals(sentence: str) -> dict:
    words = [normalize_word(w) for w in re.findall(r"\w+(?:['’]\w+)*", sentence)]
    return {
        "negated": any(w in LEXICAL_CLASSES["negation"] or w.endswith("n't") for w in words),
        "conditional": any(w in {"if", "unless"} for w in words),
        "causal": any(w in LEXICAL_CLASSES["causal"] for w in words),
        "question": sentence.rstrip().endswith(("?", "؟")),
        "modal": any(w in LEXICAL_CLASSES["modal"] for w in words),
        "temporal": any(w in LEXICAL_CLASSES["temporal"] for w in words),
        "comparative": any(w in LEXICAL_CLASSES["comparison"] for w in words),
        "definition": any(w in LEXICAL_CLASSES["definition"] for w in words),
    }
