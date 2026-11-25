"""Native symbolic, numerical and language primitives for Niblit."""
from .alphabet import LATIN_ALPHABET, classify_character, graphemes, inspect_alphabet
from .cognition import SCHEMA_VERSION, analyze_text, persist_analysis, source_chunks
from .language import classify_word, sentence_signals, split_sentences, tokenize
from .maths import MathExpressionError, evaluate_expression
from .memorization import schedule_review
from .numbers import (
    extract_numeric_literals, extract_number_word_phrases,
    parse_english_number_words, parse_numeric_literal,
)
from .relations import RELATION_TYPES, extract_relation_signals
from .seed import seed_batches, seed_memory
from .lexicon import (
    KEYWORD_GROUPS, LEXICON_VERSION, MORPHEME_HINTS,
    extract_keyword_signals, morphology_hints, summarize_keyword_signals,
)
from .scripts import (
    COGNITIVE_SCRIPT_VERSION, SCRIPT_REGISTRY,
    build_cognitive_plan, select_cognitive_scripts,
)

__all__ = [
    "LATIN_ALPHABET", "classify_character", "graphemes", "inspect_alphabet",
    "SCHEMA_VERSION", "analyze_text", "persist_analysis", "source_chunks",
    "classify_word", "sentence_signals", "split_sentences", "tokenize",
    "MathExpressionError", "evaluate_expression", "schedule_review",
    "extract_numeric_literals", "extract_number_word_phrases",
    "parse_english_number_words", "parse_numeric_literal",
    "RELATION_TYPES", "extract_relation_signals",
    "seed_batches", "seed_memory",
    "KEYWORD_GROUPS", "LEXICON_VERSION", "MORPHEME_HINTS",
    "extract_keyword_signals", "morphology_hints", "summarize_keyword_signals",
    "COGNITIVE_SCRIPT_VERSION", "SCRIPT_REGISTRY",
    "build_cognitive_plan", "select_cognitive_scripts",
]
