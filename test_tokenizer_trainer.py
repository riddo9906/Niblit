"""test_tokenizer_trainer.py — unit tests for modules.tokenizer_trainer.

All tests are offline-safe and require no real KB connection or
SentencePiece installation.

Run with::

    pytest test_tokenizer_trainer.py -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestTokenizerTrainerImport(unittest.TestCase):
    def test_module_importable(self):
        from modules import tokenizer_trainer  # noqa: F401
        self.assertTrue(True)

    def test_class_accessible(self):
        from modules.tokenizer_trainer import TokenizerTrainer
        self.assertTrue(callable(TokenizerTrainer))

    def test_get_singleton(self):
        import modules.tokenizer_trainer as tt
        tt._trainer = None
        trainer = tt.get_tokenizer_trainer()
        self.assertIsNotNone(trainer)
        trainer2 = tt.get_tokenizer_trainer()
        self.assertIs(trainer, trainer2)
        tt._trainer = None  # clean up


class TestCorpusCollection(unittest.TestCase):
    """Tests for the KB corpus collection logic."""

    def _make_trainer(self, output_dir=None):
        from modules.tokenizer_trainer import TokenizerTrainer
        return TokenizerTrainer(output_dir=output_dir or tempfile.mkdtemp())

    def test_none_knowledge_db_returns_empty(self):
        trainer = self._make_trainer()
        corpus = trainer.collect_corpus(None)
        self.assertEqual(corpus, "")

    def test_search_based_kb(self):
        """A KB that exposes search() should be used."""
        trainer = self._make_trainer()
        kb = MagicMock()
        kb.search = MagicMock(return_value=[
            {"value": "This is a research finding about transformers."},
        ])
        corpus = trainer.collect_corpus(kb)
        self.assertIn("transformers", corpus)

    def test_list_keys_fallback(self):
        """Fall back to list_keys()+get() when search() is absent."""
        trainer = self._make_trainer()
        kb = MagicMock(spec=["list_keys", "get"])
        kb.list_keys = MagicMock(return_value=["ale_research:001"])
        kb.get = MagicMock(return_value="Kelly criterion risk management text")
        corpus = trainer.collect_corpus(kb)
        self.assertIn("Kelly", corpus)

    def test_extract_text_from_dict(self):
        from modules.tokenizer_trainer import TokenizerTrainer
        text = TokenizerTrainer._extract_text({"value": "Hello world text"})
        self.assertEqual(text, "Hello world text")

    def test_extract_text_from_str(self):
        from modules.tokenizer_trainer import TokenizerTrainer
        text = TokenizerTrainer._extract_text("  plain string  ")
        self.assertEqual(text, "plain string")

    def test_extract_text_fallback_joins_dict_values(self):
        from modules.tokenizer_trainer import TokenizerTrainer
        text = TokenizerTrainer._extract_text({"a": "hello there", "b": "world"})
        self.assertIn("hello", text)


class TestWordFreqFallback(unittest.TestCase):
    """Tests for the word-frequency fallback tokenizer."""

    def _make_trainer(self):
        from modules.tokenizer_trainer import TokenizerTrainer
        tmp = tempfile.mkdtemp()
        return TokenizerTrainer(output_dir=Path(tmp), vocab_size=100, min_corpus_chars=0)

    def test_produces_json_vocab_file(self):
        trainer = self._make_trainer()
        corpus = " ".join(["hello world foo bar baz"] * 100)
        result = trainer._train_word_freq(corpus)
        self.assertIn("word-frequency", result)
        vocab_path = trainer.output_dir / "niblit_wordfreq_vocab.json"
        self.assertTrue(vocab_path.exists())

    def test_vocab_contains_special_tokens(self):
        trainer = self._make_trainer()
        corpus = "test token word " * 200
        trainer._train_word_freq(corpus)
        vocab_path = trainer.output_dir / "niblit_wordfreq_vocab.json"
        with open(vocab_path) as f:
            vocab = json.load(f)
        self.assertIn("<unk>", vocab)
        self.assertIn("<bos>", vocab)
        self.assertIn("<eos>", vocab)
        self.assertIn("<pad>", vocab)

    def test_vocab_size_respected(self):
        trainer = self._make_trainer()  # vocab_size=100
        corpus = " ".join([f"word{i}" for i in range(200)] * 5)
        trainer._train_word_freq(corpus)
        vocab_path = trainer.output_dir / "niblit_wordfreq_vocab.json"
        with open(vocab_path) as f:
            vocab = json.load(f)
        self.assertLessEqual(len(vocab), 100)


class TestTrainFromKB(unittest.TestCase):
    """Integration-level tests for train_from_kb()."""

    def _make_trainer(self, min_corpus_chars=0):
        from modules.tokenizer_trainer import TokenizerTrainer
        tmp = tempfile.mkdtemp()
        return TokenizerTrainer(
            output_dir=Path(tmp),
            vocab_size=50,
            min_corpus_chars=min_corpus_chars,
        )

    def test_small_corpus_returns_skip_message(self):
        trainer = self._make_trainer(min_corpus_chars=999_999)
        kb = MagicMock()
        kb.search = MagicMock(return_value=[{"value": "tiny"}])
        result = trainer.train_from_kb(kb)
        self.assertIn("too small", result)

    def test_none_kb_returns_skip_message(self):
        trainer = self._make_trainer(min_corpus_chars=1)
        result = trainer.train_from_kb(None)
        self.assertIn("too small", result)

    @patch("modules.tokenizer_trainer._SP_AVAILABLE", False)
    def test_trains_word_freq_when_sp_unavailable(self):
        trainer = self._make_trainer(min_corpus_chars=0)
        kb = MagicMock()
        kb.search = MagicMock(return_value=[
            {"value": " ".join(["token"] * 300)},
        ])
        result = trainer.train_from_kb(kb)
        self.assertIn("word-frequency", result)

    def test_status_dict_keys(self):
        trainer = self._make_trainer()
        s = trainer.status()
        for key in ("sentencepiece_available", "vocab_size", "model_type",
                    "output_dir", "last_train_ts", "last_train_result"):
            self.assertIn(key, s)

    def test_last_train_ts_set_after_training(self):
        trainer = self._make_trainer(min_corpus_chars=0)
        kb = MagicMock()
        kb.search = MagicMock(return_value=[{"value": "word " * 200}])
        with patch("modules.tokenizer_trainer._SP_AVAILABLE", False):
            trainer.train_from_kb(kb)
        self.assertIsNotNone(trainer._last_train_ts)


if __name__ == "__main__":
    unittest.main()
