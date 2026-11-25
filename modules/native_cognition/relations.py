"""Typed semantic relation vocabulary and source-span cue extraction."""
from __future__ import annotations

import re


RELATION_TYPES = {
    "is_a": {"inverse": "has_type", "family": "taxonomy"},
    "instance_of": {"inverse": "has_instance", "family": "taxonomy"},
    "part_of": {"inverse": "has_part", "family": "structure"},
    "contains": {"inverse": "contained_in", "family": "structure"},
    "causes": {"inverse": "caused_by", "family": "causality"},
    "caused_by": {"inverse": "causes", "family": "causality"},
    "supports": {"inverse": "supported_by", "family": "evidence"},
    "supported_by": {"inverse": "supports", "family": "evidence"},
    "contradicts": {"inverse": "contradicted_by", "family": "evidence"},
    "attributed_to": {"inverse": "attributed_claim", "family": "provenance"},
    "created_by": {"inverse": "created", "family": "provenance"},
    "derived_from": {"inverse": "source_of", "family": "provenance"},
    "located_in": {"inverse": "contains_location", "family": "spatial"},
    "before": {"inverse": "after", "family": "temporal"},
    "after": {"inverse": "before", "family": "temporal"},
    "during": {"inverse": "contains_time", "family": "temporal"},
    "requires": {"inverse": "required_by", "family": "dependency"},
    "enables": {"inverse": "enabled_by", "family": "dependency"},
    "uses": {"inverse": "used_by", "family": "dependency"},
    "owns": {"inverse": "owned_by", "family": "ownership"},
    "greater_than": {"inverse": "less_than", "family": "comparison"},
    "equal_to": {"inverse": "equal_to", "family": "comparison"},
    "synonym_of": {"inverse": "synonym_of", "family": "lexical"},
    "antonym_of": {"inverse": "antonym_of", "family": "lexical"},
    "related_to": {"inverse": "related_to", "family": "association"},
}

_CUES = [
    ("contradicts", r"\b(?:contradicts?|disputes?|refutes?|conflicts with)\b"),
    ("supports", r"\b(?:supports?|confirms?|corroborates?|is consistent with)\b"),
    ("causes", r"\b(?:causes?|caused(?!\s+by)|leads? to|results? in|produces?)\b"),
    ("caused_by", r"\b(?:because of|due to|caused by|results? from)\b"),
    ("part_of", r"\bpart of\b"),
    ("contains", r"\b(?:contains?|includes?|comprises?)\b"),
    ("located_in", r"\b(?:located in|based in|inside|within)\b"),
    ("attributed_to", r"\b(?:according to|reported by|stated by|claimed by)\b"),
    ("created_by", r"\b(?:created by|written by|developed by|built by)\b"),
    ("derived_from", r"\b(?:derived from|based on|sourced from)\b"),
    ("requires", r"\b(?:requires?|depends on|needs?)\b"),
    ("enables", r"\b(?:enables?|allows?|permits?)\b"),
    ("uses", r"\b(?:uses?|used by|utilizes?)\b"),
    ("owns", r"\b(?:owns?|owned by|belongs to)\b"),
    ("greater_than", r"\b(?:greater than|more than|higher than|larger than)\b"),
    ("less_than", r"\b(?:less than|lower than|smaller than)\b"),
    ("equal_to", r"\b(?:equal to|equals?|the same as)\b"),
    ("synonym_of", r"\b(?:synonym of|means|refers to)\b"),
    ("antonym_of", r"\b(?:antonym of|opposite of)\b"),
    ("before", r"\bbefore\b"),
    ("after", r"\bafter\b"),
    ("during", r"\bduring\b"),
    ("is_a", r"\b(?:is|are|was|were)\s+(?:an?|the)\b(?=\s+[a-z])"),
]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _CUES]


def extract_relation_signals(text: str, *, offset: int = 0) -> list[dict]:
    """Return heuristic relation cues, not asserted subject/object triples."""
    candidates = []
    for relation, pattern in _COMPILED:
        for match in pattern.finditer(text):
            candidates.append({
                "relation": relation,
                "family": RELATION_TYPES.get(relation, {}).get("family", "causality"),
                "cue": match.group(0),
                "start": offset + match.start(),
                "end": offset + match.end(),
                "confidence": 0.25,
                "status": "candidate_requires_context_and_evidence",
            })
    candidates.sort(key=lambda row: (row["start"], row["end"], row["relation"]))
    # Overlapping cues are kept only when they express distinct relation types.
    deduped = []
    seen = set()
    for item in candidates:
        key = (item["relation"], item["start"], item["end"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped
