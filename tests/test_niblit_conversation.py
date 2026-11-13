"""Contract tests isolate the existing API functions without booting a second Core."""
import ast
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


def functions():
    tree=ast.parse((Path(__file__).parents[1]/'server.py').read_text('utf-8'))
    wanted={'chat','_niblit_assistant_chat','_model_backed_chat','_niblit_response_validation'}
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in wanted]
    for node in nodes:node.decorator_list=[]
    scope={'ChatBody':object,'_json':json,'os':os,'logging':__import__('logging'),'re':__import__('re'),'JSONResponse':__import__('fastapi.responses',fromlist=['JSONResponse']).JSONResponse}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'server.py','exec'),scope)
    return scope


def test_selector_routes_niblit_to_core_orchestration():
    scope=functions();core=object();orchestrate=Mock(return_value={'reply':'grounded'})
    scope.update(get_core=lambda:core,_is_registered_chat_command=lambda *a:False,_niblit_assistant_chat=orchestrate)
    body=SimpleNamespace(text='Hello',model='niblit',use_model=True,attachment_ids=[])
    assert scope['chat'](body)['reply']=='grounded'
    orchestrate.assert_called_once_with(core,'Hello',[])


def test_registered_commands_keep_existing_governance():
    scope=functions();dispatch=Mock(return_value='denied');core=object()
    scope.update(get_core=lambda:core,_is_registered_chat_command=lambda *a:True,
                 _get_unified_runtime=lambda:SimpleNamespace(dispatch_command=dispatch),
                 _has_project_file_cue=lambda t:False,
                 _PROJECT_FILE_FOLLOWUP_START=__import__('re').compile(r'nevermatch'))
    body=SimpleNamespace(text='trade live',model='niblit',use_model=True,attachment_ids=[])
    assert scope['chat'](body)['reply']=='denied'
    dispatch.assert_called_once_with(command='trade live',core=core)


def test_niblit_uses_local_authority_and_actual_read_only_context(monkeypatch):
    scope=functions();calls=[]
    monkeypatch.setitem(sys.modules,'niblit_router',SimpleNamespace(ChatDetector=SimpleNamespace(classify=lambda t:('general',None))))
    scope['_model_backed_chat']=lambda *a,**k:calls.append((a,k)) or {'reply':'ok'}
    core=SimpleNamespace(cognitive_observation=SimpleNamespace(status=lambda:{'running':True,'execution_authorized':False}))
    scope['_niblit_assistant_chat'](core,'Explain current market health')
    args,kw=calls[0];assert args[1]=='local'
    assert kw['cognitive_context']['market_sources']['running']
    assert kw['cognitive_context']['tools_executed']==[]
    assert not kw['cognitive_context']['execution_authorized']


def test_ui_keeps_direct_mode_and_existing_models():
    ui=Path(__file__).parents[2]/'niblit-ui/src/pages/ChatPage.tsx'
    text=ui.read_text('utf-8')
    assert 'Niblit — Unified Cognitive Assistant' in text
    assert 'models.map((model)' in text and 'streamInferenceChat(history, selectedModel' in text
    assert "selectedModel !== 'niblit' && chatMode === 'inference'" in text


def model_scope(monkeypatch,complete):
    scope=functions(); memory=SimpleNamespace(load_messages=lambda **k:[],add_exchange=Mock())
    retrieval=Mock(side_effect=lambda messages:(messages,{'enabled':True,'citations':[],'issues':[]}))
    monkeypatch.setitem(sys.modules,'niblit_brain',SimpleNamespace(get_niblit_cloud_brain=Mock(side_effect=AssertionError('Cloud fallback forbidden'))))
    monkeypatch.setitem(sys.modules,'modules.llm_chat_memory',SimpleNamespace(get_llm_chat_memory=lambda:memory))
    monkeypatch.setitem(sys.modules,'modules.memory_laboratory.context',SimpleNamespace(augment_messages=retrieval))
    scope['_niblit_local_completion']=complete
    return scope,memory,retrieval


def test_niblit_busy_reports_admission_without_cloud_fallback(monkeypatch):
    from modules.task_admission import AdmissionBusy
    scope,memory,retrieval=model_scope(monkeypatch,Mock(side_effect=AdmissionBusy('busy')))
    result=scope['_model_backed_chat']('Explain the market','local',cognitive_context={'execution_authorized':False})
    assert result.status_code==503
    assert json.loads(result.body)['error']['code']=='local_inference_busy'
    memory.add_exchange.assert_not_called()


def test_greeting_skips_irrelevant_memory(monkeypatch):
    complete=Mock(return_value={'choices':[{'message':{'content':'Hello!'}}],'model':'qwen2.5-coder-3b'})
    scope,memory,retrieval=model_scope(monkeypatch,complete)
    result=scope['_model_backed_chat']('hi','local',cognitive_context={'execution_authorized':False})
    assert result['reply']=='Hello!' and result['memory_retrieval']['reason']=='not_needed_for_greeting'
    retrieval.assert_not_called();memory.add_exchange.assert_called_once()


def test_unsupported_authorization_is_flagged_and_corrected(monkeypatch):
    complete=Mock(return_value={'choices':[{'message':{'content':'Predictions can authorize trades.'}}]})
    scope,memory,retrieval=model_scope(monkeypatch,complete)
    result=scope['_model_backed_chat']('Explain predictions','local',cognitive_context={'execution_authorized':False})
    assert 'unsupported_authorization_wording' in result['validation']['flags']
    assert 'Runtime correction:' in result['reply'] and not result['validation']['action_authority']
