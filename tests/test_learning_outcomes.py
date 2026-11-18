"""Evidence failures must not be transformed into successful learned knowledge."""
from unittest.mock import Mock
import pytest
from modules.research_contracts import learning_outcome
from modules.phased_research_engine import PhasedResearchEngine, PhasedResearchResult, PhaseResult
from modules.autonomous_learning_engine import AutonomousLearningEngine


@pytest.mark.parametrize('text', ['', '(no research findings)', 'No data found for topic', 'Research on empty topic', 'What should we research next?'])
def test_empty_placeholders_and_questions_are_not_learning(text):
    result = learning_outcome('topic', [{'content': text, 'citation': 'local://source'}])
    assert not result['learning_succeeded']
    assert result['status'] == 'completed_no_findings'
    assert not result['findings'] and not result['follow_up_questions']


def test_retrieval_failure_and_no_findings_are_distinct():
    assert learning_outcome('topic', [], errors=['workspace:unavailable'])['status'] == 'retrieval_failure'
    assert learning_outcome('topic', [])['status'] == 'completed_no_findings'


def test_source_claim_and_generated_interpretation_are_separate():
    data = [{'content': 'SQLite retains the original queued source evidence.', 'citation': 'workspace://runtime.py'}]
    outcome = learning_outcome('durability', data, interpretation='A model proposes a new idea.')
    assert outcome['status'] == 'tentative_findings'
    assert not outcome['interpretation_verified'] and not outcome['hypotheses']
    assert outcome['findings'][0]['excerpt'] == data[0]['content']


def test_model_synthesis_is_not_source_findings():
    data = [{'content': 'An unsupported local model makes a confident assertion.', 'citation': 'local_brain', 'source_type': 'model_synthesis'}]
    assert not learning_outcome('topic', data)['learning_succeeded']


def test_empty_phased_artifact_is_not_ale_learned():
    db = Mock()
    engine = PhasedResearchEngine(knowledge_db=db)
    result = PhasedResearchResult(topic='empty', phases_run=[0], phase_results={0: PhaseResult(0, 'empty')})
    artifact = engine._build_research_artifact(result)
    engine._persist_research_artifact(artifact)
    assert artifact.outcome['status'] == 'completed_no_findings'
    assert artifact.confidence_score == 0 and not artifact.follow_up_topics
    assert all('ale_learned' not in call.kwargs.get('tags', []) for call in db.add_fact.call_args_list)


def test_phased_artifact_retains_source_excerpt_and_reference():
    engine = PhasedResearchEngine()
    result = PhasedResearchResult(topic='durability', phases_run=[1], phase_results={1: PhaseResult(1, 'durability', snippets=['SQLite retains the original queued source evidence.'], sources=['workspace://runtime.py'])})
    artifact = engine._build_research_artifact(result)
    assert artifact.outcome['learning_succeeded']
    assert artifact.references == ['workspace://runtime.py']


def test_out_of_cycle_module_reflection_cannot_create_empty_learning():
    engine = object.__new__(AutonomousLearningEngine)
    engine.learning_history = {}
    engine._last_research_results = []
    engine.reflect = Mock()
    engine.knowledge_db = Mock()
    assert 'skipped' in engine._autonomous_reflection()
    assert 'skipped' in engine._autonomous_idea_generation()
    assert 'skipped' in engine._autonomous_learning()
    engine.reflect.reflect_on_research.assert_not_called()
    engine.knowledge_db.add_fact.assert_not_called()


def test_native_failed_research_is_persisted_as_failure_without_teacher_questions(monkeypatch):
    from modules.native_evidence_learning import run_cycle
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT', 'local_gguf')
    g = Mock()
    g.retrieve.return_value = {'results': [], 'issues': []}
    teacher = Mock()
    infer = Mock()
    def fail(topic):
        raise ConnectionError('controlled failure')
    result = run_cycle(0, stopped=lambda: False, gateway=g, infer=infer,
                       research=fail, teacher=teacher, authorize=lambda op: None)
    assert result['state'] == 'retrieval_failure'
    assert not result['learning_succeeded']
    assert result['outcome']['status'] == 'retrieval_failure'
    teacher.assess_evidence.assert_not_called()
    infer.assert_not_called()
    g.ingest.assert_called_once()


def test_phased_ale_hands_same_topic_findings_to_next_steps(monkeypatch):
    from types import SimpleNamespace
    topic = 'SQLite outbox durability'
    phase = PhaseResult(1, topic, snippets=['SQLite retains the original queued source evidence.'], sources=['workspace://runtime.py'])
    result = PhasedResearchResult(topic=topic, phases_run=[1], phase_results={1: phase})
    result.artifact = PhasedResearchEngine()._build_research_artifact(result)
    monkeypatch.setattr('modules.phased_research_engine.get_phased_research_engine', lambda **kwargs: SimpleNamespace(research=lambda topic: result))
    ale = object.__new__(AutonomousLearningEngine)
    ale._current_cycle_topic = topic
    ale._cycle_count = 1
    ale.learning_history = {'research_completed': 0}
    ale.knowledge_db = Mock()
    ale.tiered_knowledge = None
    for name in ('_get_internet', '_get_scrapy_agent', '_get_serpex_agent', '_get_github_code_search'):
        setattr(ale, name, lambda: None)
    ale._emit_sync_artifact = Mock()
    ale._phased_research()
    assert ale.learning_history['last_research_topic'] == topic
    assert ale._has_research_findings()
    assert ale._last_research_results == ['SQLite retains the original queued source evidence.']
    assert ale._last_learning_outcome['status'] == 'tentative_findings'


def test_manual_runtime_keeps_curriculum_queued_without_starting_teacher(monkeypatch):
    from modules.graded_curriculum import GradedCurriculum
    curriculum = object.__new__(GradedCurriculum)
    curriculum._defer_teaching = False
    curriculum._seed_grade_topics = Mock()
    monkeypatch.setenv('NIBLIT_LOOPS', 'false')
    curriculum.start_teaching()
    assert curriculum._defer_teaching is True
    curriculum._seed_grade_topics.assert_not_called()


def test_unrelated_topic_cannot_be_claimed_as_local_source_learning():
    from modules.native_evidence_learning import research_local_evidence, UnsupportedLocalResearchTopic
    with pytest.raises(UnsupportedLocalResearchTopic):
        research_local_evidence('seasons of the year')
    outcome=learning_outcome('seasons of the year',[],errors=['research:UnsupportedLocalResearchTopic'])
    assert outcome['status']=='inconclusive_research' and not outcome['learning_succeeded']
    assert 'appropriate approved research source' in outcome['next_action']


def test_unrelated_recalled_memory_does_not_make_unsupported_topic_successful(monkeypatch):
    from modules.native_evidence_learning import run_cycle
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf')
    gateway=Mock()
    gateway.retrieve.return_value={'results':[{'content':'SQLite retains original source evidence in its durable outbox.',
        'citation':'workspace://runtime.py','verification':'verified'}],'issues':[]}
    infer=Mock();research=Mock();teacher=Mock()
    result=run_cycle(0,topic='seasons of the year',stopped=lambda:False,gateway=gateway,
                     infer=infer,research=research,teacher=teacher,authorize=lambda op:None)
    assert result['outcome']['status']=='inconclusive_research' and not result['learning_succeeded']
    infer.assert_not_called();research.assert_not_called();teacher.assess_evidence.assert_not_called()
