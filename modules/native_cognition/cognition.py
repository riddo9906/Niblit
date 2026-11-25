"""Deterministic source-to-cognition pipeline; source remains the evidence authority."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from .alphabet import inspect_alphabet
from .language import tokenize, split_sentences, sentence_signals
from .numbers import extract_numeric_literals, extract_number_word_phrases
from .relations import extract_relation_signals
from .lexicon import extract_keyword_signals, summarize_keyword_signals
from .scripts import build_cognitive_plan

SCHEMA_VERSION = "niblit.native-cognition/0.2"

def analyze_text(text: str, *, source_uri: str = "", language: str = "auto") -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("non-empty source text required")
    if len(text) > 200_000:
        raise ValueError("source exceeds bounded analysis size")
    tokens = tokenize(text)
    sentences = split_sentences(text)
    alpha = inspect_alphabet(text)
    counts = Counter(t["normalized"] for t in tokens
                     if t["part_of_speech_hint"] not in {"punctuation", "symbol"}
                     and not t["is_stop_word"])
    sentence_rows = []
    for sentence in sentences:
        sentence_rows.append({
            **sentence,
            "signals": sentence_signals(sentence["text"]),
            "relations": extract_relation_signals(
                sentence["text"], offset=sentence["start"]),
            "token_count": sum(1 for token in tokens
                               if sentence["start"] <= token["start"] < sentence["end"]),
        })
    word_number_candidates = extract_number_word_phrases(text)[:32]
    relation_signals = [relation for row in sentence_rows
                        for relation in row["relations"]][:256]
    keyword_hits = extract_keyword_signals(text)
    keyword_summary = summarize_keyword_signals(keyword_hits)
    cognitive_plan = build_cognitive_plan(keyword_summary)
    summary = {
        "schema_version": SCHEMA_VERSION, "source_uri": source_uri,
        "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "language_hint": language,
        "normalization": "token-local NFKC; source spans retained in original text",
        "script_profile": {"grapheme_count": alpha["grapheme_count"],
                           "script_counts": alpha["script_counts"],
                           "kind_counts": alpha["kind_counts"]},
        "token_count": len(tokens), "sentence_count": len(sentences),
        "numeric_literals": extract_numeric_literals(text)[:128],
        "number_word_candidates": word_number_candidates,
        "relation_signals": relation_signals,
        "keyword_signals": keyword_summary,
        "cognitive_plan": cognitive_plan,
        "lexical_frequency": counts.most_common(128),
        "sentence_signals": sentence_rows[:256],
        "evidence_policy": {
            "external_content_is_untrusted": True,
            "source_spans_are_original_text_offsets": True,
            "model_generated_analysis_is_not_source_verification": True,
            "negation_and_modality_are_preserved": True,
        },
    }
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    summary["analysis_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION, "source_uri": source_uri,
        "source_hash": summary["source_hash"], "text": text,
        "tokens": tokens[:4096], "sentences": sentence_rows[:256],
        "alphabet": alpha, "numbers": summary["numeric_literals"],
        "keyword_hits": keyword_hits,
        "cognitive_plan": cognitive_plan,
        "summary": summary,
    }

def source_chunks(analysis: dict, *, max_chars: int = 900) -> list[tuple[str, str]]:
    """Return exact source chunks with stable character-span citations."""
    if not 100 <= max_chars <= 1000:
        raise ValueError("max_chars must be between 100 and 1000")
    text = analysis["text"]
    source = analysis.get("source_uri") or "memory://unattributed-source"
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end),
                           text.rfind("? ", start, end), text.rfind("! ", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + (1 if text[boundary] == "\n" else 2)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append((chunk, f"{source}#char={start}-{end}"))
        start = end
    return chunks

def persist_analysis(runtime, analysis: dict) -> dict:
    """Queue source chunks through the existing governed SQLite outbox."""
    summary = analysis["summary"]
    provenance = {
        "pipeline": SCHEMA_VERSION, "source_hash": analysis["source_hash"],
        "analysis_hash": summary["analysis_hash"],
        "trust_level": "external_untrusted", "source_uri": analysis.get("source_uri", ""),
    }
    chunk_ids = []
    for chunk, location in source_chunks(analysis):
        chunk_ids.append(runtime.enqueue(
            source=location, content=chunk, category="semantic",
            metadata={
                "confidence": 0.35, "source_type": "native_cognition_source",
                "sensitivity": "private", "provenance": provenance,
                "structured": {"schema_version": SCHEMA_VERSION,
                               "analysis_hash": summary["analysis_hash"],
                               "source_location": location},
            },
        ))
    return {"queued": len(chunk_ids), "outbox_ids": chunk_ids,
            "source_hash": analysis["source_hash"],
            "analysis_hash": summary["analysis_hash"],
            "verification": "unverified"}
