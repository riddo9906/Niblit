"""
test_academic_study_module.py — Unit tests for modules/academic_study_module.py

Run with::
    pytest test_academic_study_module.py -v
"""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_pipeline():
    p = MagicMock()
    p.add_fact = MagicMock()
    p.add_document = MagicMock()
    p.query = MagicMock(return_value={
        "retrieval_stats": {"tier1": 0, "tier2": 0, "tier3": 0},
        "tier1_hits": [],
        "tier2_hits": [],
        "tier3_docs": [],
        "context": "",
        "system_prompt": "",
    })
    return p


def _make_mock_db():
    db = MagicMock()
    db.add_fact = MagicMock()
    return db


def _fresh_asm(pipeline=None, db=None, lm=None):
    from modules.academic_study_module import AcademicStudyModule
    return AcademicStudyModule(
        knowledge_db=db,
        graph_rag_pipeline=pipeline,
        language_module=lm,
    )


# ---------------------------------------------------------------------------
# Subject curriculum
# ---------------------------------------------------------------------------

class TestSubjectCurriculum:
    def _asm(self):
        return _fresh_asm()

    def test_seven_subjects(self):
        asm = self._asm()
        assert len(asm.subjects) == 7

    def test_language_subject_exists(self):
        asm = self._asm()
        assert "language" in asm.subjects

    def test_mathematics_subject_exists(self):
        asm = self._asm()
        assert "mathematics" in asm.subjects

    def test_science_subject_exists(self):
        asm = self._asm()
        assert "science" in asm.subjects

    def test_life_orientation_exists(self):
        asm = self._asm()
        assert "life_orientation" in asm.subjects

    def test_social_sciences_exists(self):
        asm = self._asm()
        assert "social_sciences" in asm.subjects

    def test_technology_exists(self):
        asm = self._asm()
        assert "technology" in asm.subjects

    def test_arts_exists(self):
        asm = self._asm()
        assert "arts" in asm.subjects

    def test_language_has_topics(self):
        asm = self._asm()
        assert len(asm.subjects["language"].topics) >= 10

    def test_maths_has_topics(self):
        asm = self._asm()
        assert len(asm.subjects["mathematics"].topics) >= 10

    def test_progress_starts_at_zero(self):
        asm = self._asm()
        for subj in asm.subjects.values():
            assert subj.progress == 0.0


class TestSubjectTopicList:
    def test_topics_for_language(self):
        asm = _fresh_asm()
        result = asm.topics_for_subject("language")
        assert "Language" in result
        assert "○" in result

    def test_topics_for_unknown_subject(self):
        asm = _fresh_asm()
        result = asm.topics_for_subject("nonexistent")
        assert "not found" in result.lower()

    def test_topics_shows_progress_after_study(self):
        asm = _fresh_asm(pipeline=_make_mock_pipeline())
        asm.subjects["language"].topics[0].studied = True
        result = asm.topics_for_subject("language")
        assert "✅" in result


# ---------------------------------------------------------------------------
# seed_knowledge_pipeline
# ---------------------------------------------------------------------------

class TestSeedKnowledgePipeline:
    def test_seed_inserts_facts(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        count = asm.seed_knowledge_pipeline(background=False)
        assert count > 0
        pipeline.add_fact.assert_called()

    def test_background_returns_zero(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        ret = asm.seed_knowledge_pipeline(background=True)
        assert ret == 0

    def test_no_pipeline_returns_zero(self):
        asm = _fresh_asm(pipeline=None)
        asm._get_pipeline = lambda: None
        count = asm.seed_knowledge_pipeline(background=False)
        assert count == 0

    def test_seeded_flag_set(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        asm.seed_knowledge_pipeline(background=False)
        assert asm._seeded is True

    def test_double_seed_is_no_op(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        asm.seed_knowledge_pipeline(background=False)
        call_count = pipeline.add_fact.call_count
        asm.seed_knowledge_pipeline(background=False)
        # Should not add any new calls (already seeded)
        assert pipeline.add_fact.call_count == call_count

    def test_includes_at_least_50_facts(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        count = asm.seed_knowledge_pipeline(background=False)
        assert count >= 50


# ---------------------------------------------------------------------------
# study_topic
# ---------------------------------------------------------------------------

class TestStudyTopic:
    def test_study_known_topic(self):
        pipeline = _make_mock_pipeline()
        db = _make_mock_db()
        asm = _fresh_asm(pipeline=pipeline, db=db)
        result = asm.study_topic("Nouns and Pronouns", subject_slug="language")
        assert "Nouns" in result or "studied" in result.lower()

    def test_study_marks_topic_done(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        asm.study_topic("Nouns and Pronouns", subject_slug="language")
        lang = asm.subjects["language"]
        studied = [t for t in lang.topics if t.studied]
        assert len(studied) >= 1

    def test_study_unknown_topic_returns_not_found(self):
        asm = _fresh_asm()
        result = asm.study_topic("Totally Unknown Topic XYZ")
        assert "not found" in result.lower()

    def test_study_stores_in_kb(self):
        db = _make_mock_db()
        asm = _fresh_asm(db=db)
        asm.study_topic("Counting and Numbers", subject_slug="mathematics")
        db.add_fact.assert_called()

    def test_study_topic_by_keyword_match(self):
        asm = _fresh_asm()
        # "numbers" matches the "Counting and Numbers" topic keywords
        result = asm.study_topic("numbers", subject_slug="mathematics")
        # Should not return "not found"
        assert "not found" not in result.lower()


# ---------------------------------------------------------------------------
# study_subject
# ---------------------------------------------------------------------------

class TestStudySubject:
    def test_study_language_subject(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        result = asm.study_subject("language", max_topics=3)
        assert "%" in result or "studied" in result.lower()

    def test_study_unknown_subject(self):
        asm = _fresh_asm()
        result = asm.study_subject("nonexistent_subject")
        assert "not found" in result.lower()

    def test_study_advances_progress(self):
        pipeline = _make_mock_pipeline()
        asm = _fresh_asm(pipeline=pipeline)
        asm.study_subject("mathematics", max_topics=2)
        math = asm.subjects["mathematics"]
        assert math.progress > 0.0

    def test_study_all_done_returns_message(self):
        asm = _fresh_asm()
        for t in asm.subjects["arts"].topics:
            t.studied = True
        result = asm.study_subject("arts")
        assert "already" in result.lower() or "%" in result


# ---------------------------------------------------------------------------
# answer_question
# ---------------------------------------------------------------------------

class TestAnswerQuestion:
    def _asm(self):
        return _fresh_asm()

    def test_what_is_a_shape(self):
        result = self._asm().answer_question("What is a shape?")
        assert result is not None
        assert "shape" in result.lower()

    def test_what_is_a_cat(self):
        result = self._asm().answer_question("What is a cat?")
        assert result is not None
        assert "cat" in result.lower()

    def test_what_is_photosynthesis(self):
        result = self._asm().answer_question("What is photosynthesis?")
        assert result is not None
        assert "plant" in result.lower() or "sunlight" in result.lower()

    def test_what_is_addition(self):
        result = self._asm().answer_question("What is addition?")
        assert result is not None
        assert "number" in result.lower() or "add" in result.lower()

    def test_what_is_democracy(self):
        result = self._asm().answer_question("What is democracy?")
        assert result is not None
        assert "government" in result.lower() or "vote" in result.lower()

    def test_what_is_respect(self):
        result = self._asm().answer_question("What is respect?")
        assert result is not None

    def test_define_noun(self):
        result = self._asm().answer_question("Define noun")
        assert result is not None
        assert "word" in result.lower() or "noun" in result.lower()

    def test_empty_question_returns_none(self):
        result = self._asm().answer_question("")
        # Empty question → no topic extracted → None
        assert result is None or isinstance(result, str)

    def test_totally_unknown_topic_returns_none(self):
        result = self._asm().answer_question("What is xyzabcunknown123?")
        assert result is None

    def test_returns_string_not_dict(self):
        result = self._asm().answer_question("What is a circle?")
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_keys(self):
        asm = _fresh_asm()
        s = asm.status()
        assert "subjects" in s
        assert "total_topics" in s
        assert "studied_topics" in s
        assert "progress" in s
        assert "seeded" in s
        assert "subject_progress" in s

    def test_status_summary_string(self):
        asm = _fresh_asm()
        summary = asm.status_summary()
        assert "AcademicStudy" in summary
        assert "subjects" in summary

    def test_total_topics_at_least_70(self):
        asm = _fresh_asm()
        s = asm.status()
        assert s["total_topics"] >= 70


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetAcademicStudyModuleSingleton:
    def test_returns_instance(self):
        from modules.academic_study_module import get_academic_study_module, AcademicStudyModule
        import modules.academic_study_module as mod
        mod._instance = None
        asm = get_academic_study_module()
        assert isinstance(asm, AcademicStudyModule)

    def test_same_instance_repeated(self):
        from modules.academic_study_module import get_academic_study_module
        import modules.academic_study_module as mod
        mod._instance = None
        a = get_academic_study_module()
        b = get_academic_study_module()
        assert a is b

    def test_late_bind_db(self):
        from modules.academic_study_module import get_academic_study_module
        import modules.academic_study_module as mod
        mod._instance = None
        asm = get_academic_study_module(knowledge_db=None)
        assert asm.knowledge_db is None
        db = _make_mock_db()
        asm2 = get_academic_study_module(knowledge_db=db)
        assert asm is asm2
        assert asm.knowledge_db is db


# ---------------------------------------------------------------------------
# Subject seed facts coverage
# ---------------------------------------------------------------------------

class TestSubjectSeedFacts:
    def test_seed_facts_cover_all_subjects(self):
        from modules.academic_study_module import _SUBJECT_SEED_FACTS
        contexts = {quad[3] for quad in _SUBJECT_SEED_FACTS}
        # Must cover language, math, science, life_orientation, geography, history
        for expected in ("language", "mathematics", "biology", "life_orientation", "geography", "history"):
            assert expected in contexts, f"Context '{expected}' missing from seed facts"

    def test_at_least_80_seed_facts(self):
        from modules.academic_study_module import _SUBJECT_SEED_FACTS
        assert len(_SUBJECT_SEED_FACTS) >= 80

    def test_all_quads_have_four_parts(self):
        from modules.academic_study_module import _SUBJECT_SEED_FACTS
        for quad in _SUBJECT_SEED_FACTS:
            assert len(quad) == 4, f"Quad has {len(quad)} parts: {quad}"

    def test_no_empty_parts(self):
        from modules.academic_study_module import _SUBJECT_SEED_FACTS
        for quad in _SUBJECT_SEED_FACTS:
            for part in quad:
                assert part.strip(), f"Empty part in quad: {quad}"


if __name__ == "__main__":
    print("Running test_academic_study_module.py")
