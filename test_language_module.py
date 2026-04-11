"""
test_language_module.py — Unit tests for modules/language_module.py

Run with::
    pytest test_language_module.py -v
"""

import pytest


# ---------------------------------------------------------------------------
# VocabEntry structure
# ---------------------------------------------------------------------------

class TestVocabEntry:
    def _get(self, word):
        from modules.language_module import get_language_module
        return get_language_module().lookup(word)

    def test_red_is_a_colour(self):
        e = self._get("red")
        assert e is not None
        assert "colour" in e["definition"].lower() or "color" in e["definition"].lower()
        assert e["category"] == "colour"

    def test_cat_is_an_animal(self):
        e = self._get("cat")
        assert e is not None
        assert "animal" in e["definition"].lower() or "pet" in e["definition"].lower()
        assert e["category"] == "animal"

    def test_shape_has_definition(self):
        e = self._get("shape")
        assert e is not None
        assert "shape" in e["definition"].lower()

    def test_circle_is_a_shape(self):
        e = self._get("circle")
        assert e is not None
        assert e["category"] == "shape"

    def test_addition_is_maths(self):
        e = self._get("addition")
        assert e is not None
        assert e["category"] == "mathematics"

    def test_photosynthesis_is_science(self):
        e = self._get("photosynthesis")
        assert e is not None
        assert "plant" in e["definition"].lower() or "sunlight" in e["definition"].lower()

    def test_respect_is_life_orientation(self):
        e = self._get("respect")
        assert e is not None
        assert e["category"] in ("life_orientation", "life orientation")

    def test_democracy_exists(self):
        e = self._get("democracy")
        assert e is not None
        assert "government" in e["definition"].lower() or "vote" in e["definition"].lower()

    def test_noun_is_grammar(self):
        e = self._get("noun")
        assert e is not None
        assert e["category"] in ("grammar", "language")

    def test_sentence_exists(self):
        e = self._get("sentence")
        assert e is not None
        assert e["definition"]


class TestLookupFuzzy:
    def _lm(self):
        from modules.language_module import get_language_module
        return get_language_module()

    def test_plural_dogs(self):
        e = self._lm().lookup("dogs")
        assert e is not None
        assert "dog" in e["definition"].lower()

    def test_plural_cats(self):
        e = self._lm().lookup("cats")
        assert e is not None

    def test_case_insensitive(self):
        e1 = self._lm().lookup("Red")
        e2 = self._lm().lookup("red")
        assert e1 == e2

    def test_unknown_word_returns_none(self):
        assert self._lm().lookup("xyznonexistentword") is None

    def test_butterflies_to_butterfly(self):
        e = self._lm().lookup("butterflies")
        assert e is not None


# ---------------------------------------------------------------------------
# Vocabulary size
# ---------------------------------------------------------------------------

class TestVocabularySize:
    def test_at_least_400_words(self):
        from modules.language_module import get_language_module
        lm = get_language_module()
        assert len(lm.vocabulary) >= 400

    def test_at_least_200_subject_facts(self):
        from modules.language_module import get_language_module
        lm = get_language_module()
        total = sum(len(facts) for facts in lm.subject_facts.values())
        assert total >= 200

    def test_all_required_categories_present(self):
        from modules.language_module import get_language_module
        lm = get_language_module()
        cats = {e["category"] for e in lm.vocabulary.values()}
        for expected in ("colour", "animal", "shape", "mathematics", "language", "science"):
            assert expected in cats, f"Category '{expected}' missing"


# ---------------------------------------------------------------------------
# detect_question_type
# ---------------------------------------------------------------------------

class TestDetectQuestionType:
    def _fn(self, q):
        from modules.language_module import get_language_module
        return get_language_module().detect_question_type(q)

    def test_what_is_definition(self):
        assert self._fn("What is a shape?") == "definition"

    def test_what_are_definition(self):
        assert self._fn("What are verbs?") == "definition"

    def test_define_definition(self):
        assert self._fn("Define photosynthesis") == "definition"

    def test_what_colour_category(self):
        assert self._fn("What colour is the sky?") == "category"

    def test_what_type_category(self):
        assert self._fn("What type of animal is a dolphin?") == "category"

    def test_how_does_process(self):
        assert self._fn("How does photosynthesis work?") == "process"

    def test_how_do_process(self):
        assert self._fn("How do plants make food?") == "process"

    def test_why_is_reason(self):
        assert self._fn("Why is the sky blue?") == "reason"

    def test_example_of_example(self):
        assert self._fn("Give an example of a verb") == "example"

    def test_compare_comparison(self):
        assert self._fn("Compare lions and tigers") == "comparison"

    def test_how_many_count(self):
        assert self._fn("How many planets are there?") == "count"

    def test_unknown_defaults_to_definition_for_what(self):
        t = self._fn("What is happening?")
        assert t in ("definition", "conversational")


# ---------------------------------------------------------------------------
# extract_topic
# ---------------------------------------------------------------------------

class TestExtractTopic:
    def _fn(self, q):
        from modules.language_module import get_language_module
        return get_language_module().extract_topic(q)

    def test_what_is_a_shape(self):
        assert self._fn("What is a shape?") == "shape"

    def test_what_is_photosynthesis(self):
        assert self._fn("What is photosynthesis?") == "photosynthesis"

    def test_define_democracy(self):
        assert self._fn("Define democracy") == "democracy"

    def test_how_does_rain_form(self):
        topic = self._fn("How does rain form?")
        assert "rain" in topic

    def test_explain_addition(self):
        assert self._fn("Explain addition") == "addition"

    def test_tell_me_about_gravity(self):
        topic = self._fn("Tell me about gravity")
        assert "gravity" in topic

    def test_empty_question(self):
        result = self._fn("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# format_definition_answer
# ---------------------------------------------------------------------------

class TestFormatDefinitionAnswer:
    def _fn(self, word, definition=None):
        from modules.language_module import get_language_module
        lm = get_language_module()
        return lm.format_definition_answer(word, definition)

    def test_with_explicit_definition(self):
        result = self._fn("cat", "a small furry animal kept as a pet")
        assert result.startswith("A cat")
        assert result.endswith(".")

    def test_with_vowel_start(self):
        result = self._fn("elephant", "a large grey mammal with a trunk")
        assert result.lower().startswith("an elephant")

    def test_lookup_from_vocab(self):
        result = self._fn("red")
        assert "colour" in result.lower() or "color" in result.lower()

    def test_empty_definition_uses_vocab(self):
        result = self._fn("circle")
        assert "circle" in result.lower()

    def test_ends_with_period(self):
        result = self._fn("dog", "a furry pet animal")
        assert result.endswith(".")

    def test_no_double_article(self):
        result = self._fn("cat", "A cat is a furry animal")
        # Should not produce "A cat A cat is..."
        assert "A cat A cat" not in result
        assert "a cat A cat" not in result.lower()


# ---------------------------------------------------------------------------
# format_factual_answer — junk filtering
# ---------------------------------------------------------------------------

class TestFormatFactualAnswer:
    def _fn(self, question, facts):
        from modules.language_module import get_language_module
        return get_language_module().format_factual_answer(question, facts)

    def test_filters_concept_freq_json(self):
        raw = [{"key": "k", "value": {"topic": "shapes", "concepts": [{"phrase": "shapes", "freq": 10, "docs": 3}]}}]
        result = self._fn("what is a shape", raw)
        # Should return vocab definition or None, NOT the freq JSON
        if result:
            assert '"freq"' not in result
            assert "concepts" not in result

    def test_filters_self_question(self):
        raw = [{"key": "k", "value": {"question": "Why does free matter?", "concept": "free", "topic": "shapes"}}]
        result = self._fn("what is a shape", raw)
        # vocab fallback should take over
        if result:
            assert "Why does free matter?" not in result

    def test_filters_code_artifacts(self):
        raw = [{"key": "k", "value": "def my_function(x):\n    return x * 2"}]
        result = self._fn("what is addition", raw)
        if result:
            assert "def my_function" not in result

    def test_returns_clean_prose(self):
        raw = [{"key": "k", "value": "Photosynthesis is the process by which plants use sunlight to make food."}]
        result = self._fn("what is photosynthesis", raw)
        assert result is not None
        assert "Photosynthesis" in result or "photosynthesis" in result.lower()

    def test_vocab_fallback_for_known_word(self):
        raw = [{"key": "k", "value": {"topic": "shapes", "concepts": []}}]
        result = self._fn("what is a shape", raw)
        # Should fall back to vocab definition
        if result:
            assert "shape" in result.lower()

    def test_returns_none_for_all_junk(self):
        raw = [{"key": "k", "value": {"freq": 5, "docs": 2}}]
        result = self._fn("what is x", raw)
        # Either None or a vocab-derived answer, never raw metadata
        if result:
            assert "freq" not in result

    def test_empty_list_returns_none_or_vocab(self):
        result = self._fn("what is a shape", [])
        # Should return vocab definition since "shape" is in vocabulary
        assert result is not None
        assert "shape" in result.lower()


# ---------------------------------------------------------------------------
# format_paragraph
# ---------------------------------------------------------------------------

class TestFormatParagraph:
    def _fn(self, topic, sentences):
        from modules.language_module import get_language_module
        return get_language_module().format_paragraph(topic, sentences)

    def test_joins_sentences(self):
        result = self._fn("colour", ["Red is a colour.", "Blue is a colour."])
        assert "Red" in result
        assert "Blue" in result

    def test_empty_list_returns_string(self):
        result = self._fn("topic", [])
        assert isinstance(result, str)

    def test_single_sentence_unchanged(self):
        result = self._fn("cat", ["A cat is a furry pet."])
        assert "cat" in result.lower()

    def test_no_leading_trailing_whitespace(self):
        result = self._fn("dog", ["A dog is a loyal animal."])
        assert result == result.strip()


# ---------------------------------------------------------------------------
# seed_graph_rag
# ---------------------------------------------------------------------------

class TestSeedGraphRag:
    def test_returns_positive_count(self):
        from modules.language_module import get_language_module
        from unittest.mock import MagicMock
        lm = get_language_module()
        mock_pipeline = MagicMock()
        mock_pipeline.add_fact = MagicMock()
        count = lm.seed_graph_rag(mock_pipeline)
        assert count > 0
        mock_pipeline.add_fact.assert_called()

    def test_none_pipeline_returns_int(self):
        from modules.language_module import get_language_module
        lm = get_language_module()
        # When None is passed, seed_graph_rag may use the singleton pipeline
        # or return 0 if unavailable — in either case it must return an int.
        count = lm.seed_graph_rag(None)
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_same_instance(self):
        from modules.language_module import get_language_module
        import modules.language_module as mod
        mod._instance = None
        a = get_language_module()
        b = get_language_module()
        assert a is b


if __name__ == "__main__":
    print("Running test_language_module.py")
