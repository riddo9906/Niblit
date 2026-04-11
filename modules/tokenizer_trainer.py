#!/usr/bin/env python3
"""
modules/tokenizer_trainer.py — Domain-Specific Tokenizer Trainer for Niblit
=============================================================================
Trains a vocabulary tuned to AI / trading text from Niblit's own Knowledge
Base (KB) corpus, producing a tokenizer that understands Niblit's domain
language better than a generic off-the-shelf vocabulary.

Two backends are supported (both optional — Niblit degrades gracefully):

  **SentencePiece** (preferred)
    When ``sentencepiece`` is installed, trains a BPE or unigram model
    directly on KB text.  The serialised ``*.model`` and ``*.vocab`` files
    are written to ``<output_dir>/``.

  **Fallback word-frequency tokenizer** (always available)
    A lightweight tokenizer that builds a ``word → id`` mapping from the
    most frequent tokens in the corpus.  Not as powerful as SentencePiece
    but requires no extra dependencies.

Usage::

    from modules.tokenizer_trainer import TokenizerTrainer

    trainer = TokenizerTrainer()
    result = trainer.train_from_kb(knowledge_db)   # uses default output dir
    print(result)
    # e.g. "Trained SentencePiece BPE tokenizer — 8000 tokens saved to
    #        /data/niblit/tokenizer/niblit_tokenizer.model"

Singleton via ``get_tokenizer_trainer()``.

Configuration (environment variables)::

    NIBLIT_TOKENIZER_DIR   — Output directory for tokenizer artefacts.
                             Defaults to ``<NIBLIT_DATA_DIR>/tokenizer/`` or
                             ``./niblit_tokenizer/`` if NIBLIT_DATA_DIR is unset.
    NIBLIT_TOKENIZER_VOCAB_SIZE — Target vocabulary size (default 8000).
    NIBLIT_TOKENIZER_MODEL_TYPE — SentencePiece model type: ``bpe`` or
                                   ``unigram`` (default ``bpe``).
    NIBLIT_TOKENIZER_MIN_CORPUS_CHARS — Minimum corpus character count before
                                        training is attempted (default 5000).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Optional SentencePiece ────────────────────────────────────────────────────
_SP_AVAILABLE = False
try:
    import sentencepiece as spm  # type: ignore[import]
    _SP_AVAILABLE = True
except ImportError:
    spm = None  # type: ignore[assignment]

# ── Paths and defaults ────────────────────────────────────────────────────────
def _default_tokenizer_dir() -> Path:
    data_dir = os.environ.get("NIBLIT_DATA_DIR", "")
    if data_dir:
        return Path(data_dir) / "tokenizer"
    # Fall back to a directory next to the project root
    return Path(os.environ.get("NIBLIT_TOKENIZER_DIR", "niblit_tokenizer"))


_VOCAB_SIZE = int(os.environ.get("NIBLIT_TOKENIZER_VOCAB_SIZE", "8000"))
_MODEL_TYPE = os.environ.get("NIBLIT_TOKENIZER_MODEL_TYPE", "bpe").lower()
_MIN_CORPUS_CHARS = int(os.environ.get("NIBLIT_TOKENIZER_MIN_CORPUS_CHARS", "5000"))


class TokenizerTrainer:
    """Train and persist a domain-specific tokenizer from Niblit's KB corpus.

    Args:
        output_dir:   Directory where tokenizer artefacts are saved.
                      Defaults to the path resolved by :func:`_default_tokenizer_dir`.
        vocab_size:   Target vocabulary size for SentencePiece training.
        model_type:   SentencePiece algorithm: ``"bpe"`` or ``"unigram"``.
        min_corpus_chars: Minimum corpus size (characters) required before
                          attempting to train.  Returns an informational
                          message if the corpus is too small.
    """

    # KB key prefixes to harvest for the training corpus
    _CORPUS_PREFIXES = [
        "ale_research:",
        "ale_reflection:",
        "topic_knowledge:",
        "ale_llm_train:",
        "slsa:",
    ]

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        vocab_size: int = _VOCAB_SIZE,
        model_type: str = _MODEL_TYPE,
        min_corpus_chars: int = _MIN_CORPUS_CHARS,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else _default_tokenizer_dir()
        self.vocab_size = vocab_size
        self.model_type = model_type if model_type in ("bpe", "unigram") else "bpe"
        self.min_corpus_chars = min_corpus_chars

        self._lock = threading.Lock()
        self._last_train_ts: Optional[int] = None
        self._last_train_result: str = ""

        log.info(
            "[TokenizerTrainer] Initialised — sentencepiece=%s vocab_size=%d "
            "model_type=%s output_dir=%s",
            _SP_AVAILABLE, self.vocab_size, self.model_type, self.output_dir,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Corpus collection
    # ─────────────────────────────────────────────────────────────────────────

    def collect_corpus(self, knowledge_db: Any) -> str:
        """Harvest raw text from the KB and return it as a single string.

        Iterates over ``_CORPUS_PREFIXES`` and extracts string / dict values
        from each KB entry, concatenating them into one large text block.

        Args:
            knowledge_db: A KnowledgeDB-compatible object with a
                          ``search(prefix)`` or ``list_keys()`` / ``get(key)``
                          interface.

        Returns:
            Concatenated corpus text (may be empty if the KB is unavailable).
        """
        parts: List[str] = []

        if knowledge_db is None:
            return ""

        for prefix in self._CORPUS_PREFIXES:
            try:
                # Try search() first (most KnowledgeDB implementations)
                if hasattr(knowledge_db, "search"):
                    entries = knowledge_db.search(prefix) or []
                    for entry in entries:
                        text = self._extract_text(entry)
                        if text:
                            parts.append(text)
                # Fallback: list_keys() + get()
                elif hasattr(knowledge_db, "list_keys") and hasattr(knowledge_db, "get"):
                    for key in (knowledge_db.list_keys() or []):
                        if str(key).startswith(prefix):
                            val = knowledge_db.get(key)
                            text = self._extract_text(val)
                            if text:
                                parts.append(text)
            except Exception as exc:
                log.debug("[TokenizerTrainer] Corpus collection error for prefix %s: %s", prefix, exc)

        return "\n".join(parts)

    @staticmethod
    def _extract_text(value: Any) -> str:
        """Extract a plain-text string from a KB value (str, dict, or other)."""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            # Common KnowledgeDB patterns
            for field in ("value", "text", "content", "summary", "body",
                          "completion", "answer", "definition"):
                v = value.get(field)
                if isinstance(v, str) and len(v) > 10:
                    return v.strip()
            # Fallback: join all string values
            return " ".join(
                str(v) for v in value.values()
                if isinstance(v, str) and len(v) > 5
            ).strip()
        return ""

    # ─────────────────────────────────────────────────────────────────────────
    # SentencePiece training
    # ─────────────────────────────────────────────────────────────────────────

    def _train_sentencepiece(self, corpus: str) -> str:
        """Train a SentencePiece tokenizer on *corpus* and save artefacts."""
        import tempfile

        self.output_dir.mkdir(parents=True, exist_ok=True)
        model_prefix = str(self.output_dir / "niblit_tokenizer")

        # Write corpus to a temp file (SentencePiece requires a file path)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(corpus)
            tmp_path = tmp.name

        try:
            spm.SentencePieceTrainer.train(  # type: ignore[union-attr]
                input=tmp_path,
                model_prefix=model_prefix,
                vocab_size=self.vocab_size,
                model_type=self.model_type,
                character_coverage=0.9995,
                pad_id=3,
                bos_id=1,
                eos_id=2,
                unk_id=0,
                shuffle_input_sentence=True,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        model_file = model_prefix + ".model"
        vocab_file = model_prefix + ".vocab"

        actual_vocab = self.vocab_size
        if Path(vocab_file).exists():
            try:
                with open(vocab_file, encoding="utf-8") as f:
                    actual_vocab = sum(1 for _ in f)
            except OSError:
                pass

        result = (
            f"Trained SentencePiece {self.model_type.upper()} tokenizer — "
            f"{actual_vocab} tokens saved to {model_file}"
        )
        log.info("[TokenizerTrainer] %s", result)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Fallback word-frequency tokenizer
    # ─────────────────────────────────────────────────────────────────────────

    def _train_word_freq(self, corpus: str) -> str:
        """Build a word-frequency vocabulary and save it as JSON."""
        # Tokenise with a simple regex that handles contractions and numbers
        tokens = re.findall(r"[a-zA-Z0-9_'\-]+", corpus.lower())
        counts = Counter(tokens)

        # Reserve slots 0–3 for special tokens
        special = {"<unk>": 0, "<bos>": 1, "<eos>": 2, "<pad>": 3}
        vocab: Dict[str, int] = dict(special)
        next_id = len(special)

        for token, _ in counts.most_common(self.vocab_size - len(special)):
            if token not in vocab:
                vocab[token] = next_id
                next_id += 1

        self.output_dir.mkdir(parents=True, exist_ok=True)
        vocab_path = self.output_dir / "niblit_wordfreq_vocab.json"
        with open(vocab_path, "w", encoding="utf-8") as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)

        result = (
            f"Trained word-frequency tokenizer (fallback) — "
            f"{len(vocab)} tokens saved to {vocab_path}"
        )
        log.info("[TokenizerTrainer] %s", result)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def train_from_kb(self, knowledge_db: Any = None) -> str:
        """Collect KB text and train a domain-specific tokenizer.

        Selects the SentencePiece backend when available, otherwise falls
        back to the word-frequency approach.

        Args:
            knowledge_db: KnowledgeDB instance (or *None*).  When *None*
                          an empty corpus is used and training is skipped.

        Returns:
            A human-readable status string describing the outcome.
        """
        with self._lock:
            corpus = self.collect_corpus(knowledge_db)

            if not corpus or len(corpus) < self.min_corpus_chars:
                msg = (
                    f"[TokenizerTrainer] Corpus too small "
                    f"({len(corpus)} chars < {self.min_corpus_chars} minimum) — skipping."
                )
                log.info(msg)
                return msg

            try:
                if _SP_AVAILABLE:
                    result = self._train_sentencepiece(corpus)
                else:
                    log.info(
                        "[TokenizerTrainer] sentencepiece not installed — "
                        "using word-frequency fallback.  "
                        "Install with: pip install sentencepiece"
                    )
                    result = self._train_word_freq(corpus)
            except Exception as exc:
                log.warning("[TokenizerTrainer] Training failed: %s", exc)
                # Attempt fallback if SentencePiece failed
                try:
                    result = self._train_word_freq(corpus)
                except Exception as exc2:
                    result = f"[TokenizerTrainer] Both backends failed: {exc} / {exc2}"

            import time as _time
            self._last_train_ts = int(_time.time())
            self._last_train_result = result
            return result

    def status(self) -> Dict[str, Any]:
        """Return a status dict for this trainer."""
        return {
            "sentencepiece_available": _SP_AVAILABLE,
            "vocab_size": self.vocab_size,
            "model_type": self.model_type,
            "output_dir": str(self.output_dir),
            "min_corpus_chars": self.min_corpus_chars,
            "last_train_ts": self._last_train_ts,
            "last_train_result": self._last_train_result,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
_trainer: Optional[TokenizerTrainer] = None
_trainer_lock = threading.Lock()


def get_tokenizer_trainer(**kwargs) -> TokenizerTrainer:
    """Return the process-level :class:`TokenizerTrainer` singleton.

    On first call a new instance is created using module-level defaults.
    Subsequent calls return the same instance; *kwargs* are ignored.
    """
    global _trainer  # pylint: disable=global-statement
    with _trainer_lock:
        if _trainer is None:
            _trainer = TokenizerTrainer(**kwargs)
        return _trainer
