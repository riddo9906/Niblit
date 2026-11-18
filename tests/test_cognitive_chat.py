from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.cognitive_chat import admission, evidence_reply, execute_readonly


@pytest.mark.parametrize('text,intent', [
    ('Which model generated this response?', 'identity'),
    ('so not qwen?', 'identity'),
    ('no local ai model active?', 'identity'),
    ('you are not really what you say you are', 'identity_challenge'),
    ('Perform a complete self-assessment. Do not execute real trades.', 'diagnostic'),
    ('Explain how you would perform a self-assessment', 'retrieval'),
    ('Read file modules/cognitive_chat.py', 'file'),
    ('Research canonical memory durability', 'research'),
    ('Execute powershell to delete a database', 'authorization_required'),
    ('Activate funded trading', 'authorization_required'),
    ('hello', 'conversation'),
    ('Learn name, version from file sample.json for subject demo.package', 'learning'),
    ('Learn from this document and explain what you discovered.', 'learning_clarification'),
    ('Use learned facts for demo.package to build a name@version label.', 'learned_recall'),
])
def test_admission_does_not_confuse_discussion_with_execution(text, intent):
    assert admission(text)[0] == intent


def test_unknown_identity_never_invents_native_generation():
    facts = {'available_models': [], 'provider':'UNKNOWN', 'endpoint':'UNKNOWN', 'observed_at':'now'}
    reply = evidence_reply('identity_challenge', facts, [])
    assert 'UNKNOWN' in reply and 'no generative model' in reply
    assert "can't assist" not in reply


def test_learning_plan_has_explicit_bounded_permissions():
    intent,plan=admission('Learn name, version from file sample.json for subject demo.package')
    assert intent=='learning'
    name,args=plan[0]
    assert name=='run_learning' and args['subject']=='demo.package'
    assert args['sources']==[{'kind':'workspace_json','path':'sample.json','fields':['name','version']}]
    assert args['max_research_calls']==1 and args['max_accepted_records']==2


def test_explicit_cors_origin_takes_precedence_without_wildcard(monkeypatch):
    import server
    monkeypatch.setattr(server,'_origins','http://localhost:5173')
    monkeypatch.delenv('NIBLIT_CORS_PERMISSIVE',raising=False)
    monkeypatch.setenv('NIBLIT_UI_ORIGINS','http://127.0.0.1:5183')
    assert server._resolve_cors_origins()==['http://127.0.0.1:5183']


def test_dispatch_uses_existing_governance_and_records_real_failure(monkeypatch):
    import modules.core_tool_runtime as runtime
    loop = Mock()
    loop.invoke.return_value = {'status':'success', 'result':{'error':'unavailable'}, 'duration_ms':1}
    monkeypatch.setattr(runtime, 'get_governed_tool_loop', lambda getter: loop)
    result = execute_readonly(object(), [('knowledge_stats', {})])
    loop.invoke.assert_called_once_with('knowledge_stats', {})
    assert result[0]['status'] == 'error' and result[0]['id']
    assert execute_readonly(object(), [('shell', {'command':'anything'})])[0]['status'] == 'rejected'
    assert loop.invoke.call_count == 1


def test_chat_endpoint_self_assessment_executes_and_persists(monkeypatch):
    import server
    from modules import cognitive_chat, llm_chat_memory
    from fastapi.testclient import TestClient
    facts = {'controller':'Niblit Core','available_models':['qwen2.5-coder-3b'],
             'provider':'llama.cpp','endpoint':'http://127.0.0.1:8766','observed_at':'now'}
    monkeypatch.setattr(cognitive_chat, 'inference_snapshot', lambda: facts)
    core = SimpleNamespace(command_registry=None)
    monkeypatch.setattr(server, 'get_core', lambda: core)
    loop = Mock()
    loop.invoke.return_value = {'status':'success','result':{'status':'observed'},'duration_ms':1}
    import modules.core_tool_runtime as runtime
    monkeypatch.setattr(runtime, 'get_governed_tool_loop', lambda getter: loop)
    memory = Mock()
    memory.add_exchange.return_value = True
    monkeypatch.setattr(llm_chat_memory,'get_llm_chat_memory',lambda: memory)
    generation = Mock(side_effect=AssertionError('No model needed for diagnostic receipts'))
    monkeypatch.setattr(server, '_niblit_local_completion', generation)
    client = TestClient(server.app)
    result = client.post('/chat',json={'model':'niblit','text':'Perform a safe read-only self-assessment'}).json()
    assert len(result['cognitive']['tools_executed']) == 2
    assert result['persistence']['conversation_saved']
    assert 'Completed' in result['reply']
    assert loop.invoke.call_count == 2
    result = client.post('/chat',json={'model':'niblit','text':'Which model generated this response?'}).json()
    assert 'qwen2.5-coder-3b' in result['reply']
    assert result['niblit_model']['generation_performed'] is False
    assert loop.invoke.call_count == 2
    generation.assert_not_called()


def test_record_id_requires_exact_evidence_and_keeps_scope():
    from modules.memory_laboratory.context import augment_messages
    identifier = '264bd319-1b80-4b37-8c87-d01766391cf5'
    class Gateway:
        def retrieve(self, query, **kwargs):
            assert kwargs['namespace']=='test' and kwargs['principal']=='operator'
            return {'issues':[], 'results':[{'id':'wrong','content':'A stopped trading session',
                    'citation':'old.txt','verification':'verified','confidence':1}]}
    _, report = augment_messages([{'role':'user','content':f'Explain outcome {identifier}'}],
                                gateway=Gateway(),scope=('test','operator'))
    assert not report['citations']
    assert report['issues'] == ['requested_record_not_found_in_retrieved_evidence']


def test_record_id_retains_related_chunks_only():
    from modules.memory_laboratory.context import augment_messages
    identifier = '264bd319-1b80-4b37-8c87-d01766391cf5'
    class Gateway:
        def retrieve(self, query, **kwargs):
            return {'issues':[], 'results':[
                {'id':str(i),'content':text,'citation':source,'verification':'unverified','confidence':.5}
                for i,(text,source) in enumerate([(identifier,'episode#offset=0'),
                    ('Substantive finding','episode#offset=1000'),('Unrelated','other')])]}
    _, report = augment_messages([{'role':'user','content':identifier}],gateway=Gateway(),scope=('t','p'))
    assert report['citations'] == ['episode#offset=0','episode#offset=1000']


def test_gateway_exact_identifier_outranks_semantic_neighbours(tmp_path):
    from test_memory_laboratory_gateway import Backend, gateway, ingest
    backend = Backend()
    g = gateway(tmp_path, backend)
    for i in range(15):
        g.ingest([(f'Canonical memory research neighbour {i}', f'decoy{i}')],
                 source=f'decoy{i}', namespace='test', principal='operator')
    identifier = '264bd319-1b80-4b37-8c87-d01766391cf5'
    g.ingest([(f'Outcome: {identifier}', 'episode#offset=8000')], source='episode',
             namespace='test', principal='operator')
    result = g.retrieve(identifier, namespace='test', principal='operator', limit=4)
    assert identifier in result['results'][0]['content']
    # A foreign namespace cannot gain an exact-match shortcut.
    assert not g.retrieve(identifier, namespace='foreign', principal='operator')['results']


def test_gateway_identifier_split_across_contiguous_chunks(tmp_path):
    from test_memory_laboratory_gateway import Backend, gateway
    from modules.memory_laboratory.context import augment_messages
    g = gateway(tmp_path, Backend())
    identifier = '264bd319-1b80-4b37-8c87-d01766391cf5'
    left, right = 'Observation ' + identifier[:28], identifier[28:] + ' SQLite owns evidence.'
    g.ingest([(left,'episode#offset=0'),(right,f'episode#offset={len(left)}')],
             source='episode',namespace='test',principal='operator')
    result = g.retrieve(identifier, namespace='test',principal='operator')
    assert len(result['results']) == 2
    assert all(h['matched_identifiers']==[identifier] for h in result['results'])
    _, report = augment_messages([{'role':'user','content':identifier}],gateway=g,scope=('test','operator'))
    assert len(report['citations']) == 2 and not report['issues']
