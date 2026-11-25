"""Versioned, inspectable keyword ontology and source-span matcher.

This is a cognitive cue layer, not a complete dictionary or a truth classifier.
Every hit points back to the original source text and remains a candidate cue.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

LEXICON_VERSION = "0.2.0"

KEYWORD_GROUPS = {
    "logic": (
        "and", "or", "but", "either", "neither", "both", "not", "never",
        "unless", "if", "then", "otherwise", "only if", "even if",
        "therefore", "thus", "hence", "as a result",
    ),
    "epistemic": (
        "know", "knows", "known", "believe", "believes", "understand",
        "assume", "assumption", "infer", "inference", "deduce", "deduction",
        "conclude", "conclusion", "estimate", "predict", "suspect",
        "hypothesis", "theory", "uncertain", "uncertainty", "possible",
        "impossible", "probable", "unlikely", "likely",
    ),
    "evidence": (
        "evidence", "source", "citation", "reference", "record", "measurement",
        "observation", "observed", "measured", "documented", "verified",
        "confirmed", "corroborated", "reported", "test result", "data",
        "sample", "experiment", "proof", "proven", "unverified",
    ),
    "reasoning": (
        "because", "reason", "reasoning", "explain", "explanation", "implies",
        "indicates", "suggests", "demonstrates", "shows", "means", "derive",
        "derived", "consequence", "implication", "interpret", "interpretation",
        "analyze", "analyse", "compare", "evaluate", "assess",
    ),
    "causality": (
        "cause", "causes", "caused", "causing", "effect", "effects",
        "result", "results", "resulted", "leads to", "led to", "due to",
        "because of", "contributes to", "influences", "affects", "depends on",
        "correlates with",
    ),
    "temporal": (
        "before", "after", "during", "while", "since", "until", "when",
        "previous", "previously", "currently", "now", "later", "earlier", "eventually",
        "at the same time", "first", "next", "then", "finally", "recently",
        "historical", "future", "past", "present", "deadline", "duration",
    ),
    "sequence": (
        "step", "steps", "stage", "phase", "sequence", "process", "workflow",
        "procedure", "first", "second", "third", "next", "finally",
        "start", "begin", "continue", "finish", "complete",
    ),
    "comparison": (
        "compare", "compared", "comparison", "versus", "vs", "than",
        "greater", "less", "equal", "equivalent", "similar", "different",
        "difference", "same", "higher", "lower", "increase", "decrease",
        "more", "fewer", "largest", "smallest", "best", "worst",
    ),
    "quantity": (
        "number", "amount", "quantity", "total", "sum", "average", "mean",
        "median", "ratio", "fraction", "percentage", "percent", "rate",
        "range", "minimum", "maximum", "at least", "at most", "approximately",
        "roughly", "exactly", "unit", "units", "per", "each",
    ),
    "spatial": (
        "inside", "outside", "above", "below", "under", "over", "between",
        "beside", "near", "far", "left", "right", "north", "south", "east",
        "west", "within", "around", "across", "location", "position",
        "direction", "distance", "route", "path",
    ),
    "definition": (
        "means", "meaning", "defined as", "definition", "refers to",
        "represents", "called", "known as", "is a type of", "is an example of",
        "concept", "term", "category", "class", "kind",
    ),
    "classification": (
        "type", "types", "kind", "category", "class", "group", "belongs to",
        "classified as", "instance of", "member of", "subtype", "subcategory",
        "family", "domain", "attribute", "property", "feature",
    ),
    "change": (
        "change", "changes", "changed", "increase", "increased", "decrease",
        "decreased", "grow", "grew", "shrink", "shrunk", "transform",
        "transformed", "convert", "converted", "replace", "replaced",
        "update", "updated", "improve", "improved", "degrade", "degraded",
    ),
    "agency": (
        "person", "people", "user", "operator", "system", "service", "agent",
        "model", "organization", "company", "customer", "owner", "author",
        "creator", "developer", "sender", "receiver", "client", "server",
    ),
    "communication": (
        "say", "said", "tell", "told", "ask", "asked", "reply", "respond",
        "report", "reported", "announce", "announced", "claim", "claimed",
        "state", "stated", "write", "written", "message", "conversation",
        "request", "instruction", "command",
    ),
    "computation": (
        "calculate", "calculation", "compute", "computed", "formula",
        "equation", "expression", "variable", "constant", "operator",
        "addition", "subtraction", "multiplication", "division", "power",
        "square", "root", "remainder", "rearrange", "solve",
    ),
    "programming": (
        "code", "function", "method", "class", "module", "package", "library",
        "variable", "parameter", "argument", "return", "loop", "condition",
        "exception", "error", "bug", "test", "compile", "build", "deploy",
        "api", "database", "file", "directory", "process", "thread",
    ),
    "memory": (
        "remember", "recall", "forget", "memorize", "memorise", "memory",
        "retrieve", "retrieval", "store", "stored", "learn", "learned",
        "practice", "review", "repeat", "reinforce", "mastery", "retain",
        "retention", "association", "recognize", "recognise",
    ),
    "safety": (
        "risk", "danger", "unsafe", "safe", "permission", "authorized",
        "authorised", "consent", "privacy", "secret", "credential",
        "sensitive", "harm", "threat", "attack", "vulnerability",
        "constraint", "boundary", "prohibited", "restricted",
    ),
    "negation": (
        "not", "no", "never", "neither", "nor", "cannot", "can't",
        "does not", "do not", "did not", "without", "lack", "lacks",
        "failed to", "unable to",
    ),
    "modality": (
        "can", "could", "may", "might", "must", "should", "shall",
        "will", "would", "possibly", "probably", "certainly", "required",
        "optional", "mandatory", "permitted", "forbidden",
    ),
    "question": (
        "who", "what", "when", "where", "why", "how", "which", "whose",
        "whether", "what if", "how many", "how much", "how long",
    ),
}

MORPHEME_HINTS = {
    "prefixes": {
        "un-": "negation_or_reversal", "re-": "again_or_back",
        "pre-": "before", "post-": "after", "anti-": "against",
        "inter-": "between", "intra-": "within", "sub-": "below_or_subordinate",
        "super-": "above_or_excess", "trans-": "across_or_change",
        "mis-": "incorrect_or_badly", "non-": "absence_or_negation",
        "over-": "excess_or_above", "under-": "insufficient_or_below",
    },
    "suffixes": {
        "-tion": "process_or_result_noun", "-ment": "process_or_result_noun",
        "-ness": "state_or_quality_noun", "-ity": "state_or_quality_noun",
        "-able": "capability_or_suitability", "-ible": "capability_or_suitability",
        "-less": "absence", "-ful": "having_or_full_of",
        "-ize": "make_or_become", "-ise": "make_or_become",
        "-ology": "field_of_study", "-ist": "person_or_specialist",
        "-er": "agent_or_comparator", "-ly": "adverb_or_manner_hint",
    },
}

def normalize_keyword(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().replace("’", "'").strip()

_COMPILED = []
for group, phrases in KEYWORD_GROUPS.items():
    for phrase in sorted(set(phrases), key=lambda value: (-len(value), value)):
        normalized = normalize_keyword(phrase)
        pattern = re.compile(r"(?<!\w)" + re.escape(normalized).replace(r"\ ", r"\s+") + r"(?!\w)", re.IGNORECASE)
        _COMPILED.append((group, normalized, pattern))

_NUMERIC_CUE = re.compile(
    r"(?<!\w)[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|/\d+)?(?!\w)"
)

def extract_keyword_signals(text: str, *, max_hits: int = 512) -> list[dict]:
    """Find lexical and numeric cues with exact offsets; cues do not assert facts."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if max_hits < 1:
        return []
    hits = []
    for match in _NUMERIC_CUE.finditer(text):
        hits.append({
            "keyword": match.group(0), "normalized": match.group(0),
            "group": "quantity", "start": match.start(), "end": match.end(),
            "status": "numeric_cue_only", "confidence": 0.5,
        })
    for group, keyword, pattern in _COMPILED:
        for match in pattern.finditer(text):
            hits.append({
                "keyword": match.group(0),
                "normalized": keyword,
                "group": group,
                "start": match.start(),
                "end": match.end(),
                "status": "lexical_cue_only",
                "confidence": 0.35,
            })
    hits.sort(key=lambda item: (item["start"], -(item["end"] - item["start"]), item["group"]))
    deduped = []
    seen = set()
    for hit in hits:
        key = (hit["group"], hit["normalized"], hit["start"], hit["end"])
        if key not in seen:
            seen.add(key)
            deduped.append(hit)
        if len(deduped) >= max_hits:
            break
    return deduped

def summarize_keyword_signals(hits: list[dict]) -> dict:
    counts = Counter(item["group"] for item in hits)
    return {
        "lexicon_version": LEXICON_VERSION,
        "hit_count": len(hits),
        "group_counts": dict(sorted(counts.items())),
        "groups_present": sorted(counts),
    }

def morphology_hints(word: str) -> list[dict]:
    """Return cautious affix cues; never rewrite the source token or claim a lemma."""
    normalized = normalize_keyword(word)
    hints = []
    for affix, meaning in MORPHEME_HINTS["prefixes"].items():
        if normalized.startswith(affix[:-1]) and len(normalized) > len(affix):
            hints.append({"affix": affix, "hint": meaning, "status": "heuristic"})
    for affix, meaning in MORPHEME_HINTS["suffixes"].items():
        if normalized.endswith(affix[1:]) and len(normalized) > len(affix):
            hints.append({"affix": affix, "hint": meaning, "status": "heuristic"})
    return hints
