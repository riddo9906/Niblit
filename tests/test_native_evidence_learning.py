from unittest.mock import Mock
from modules.native_evidence_learning import run_cycle


def test_native_cycle_records_only_unverified_evidence(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf')
    g=Mock();g.retrieve.return_value={'results':[{'id':'a','content':'Source claim','citation':'source://a','verification':'unverified'}],'issues':[]}
    infer=Mock(return_value='Source claim [1].')
    report=run_cycle(0,stopped=lambda:False,gateway=g,infer=infer)
    assert report['state']=='candidate_for_review' and report['model_calls']==1
    assert not report['truth_verified'] and not report['weights_trained']
    assert g.ingest.call_args.kwargs['category']=='episodic'
    assert g.ingest.call_args.kwargs['metadata']['confidence']==.2
    assert g.ingest.call_args.kwargs['metadata']['source_type']=='local_model_reflection'


def test_missing_evidence_does_not_invent_an_answer(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf')
    g=Mock();g.retrieve.return_value={'results':[],'issues':[]};infer=Mock()
    report=run_cycle(1,stopped=lambda:False,gateway=g,infer=infer)
    assert report['state']=='knowledge_gap' and report['model_calls']==0
    infer.assert_not_called()


def test_stop_after_inference_prevents_new_memory_work(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf')
    g=Mock();g.retrieve.return_value={'results':[{'id':'a','content':'source','citation':'source://a'}],'issues':[]}
    stopped=[False]
    def infer(*args,**kwargs):stopped[0]=True;return 'source [1]'
    report=run_cycle(2,stopped=lambda:stopped[0],gateway=g,infer=infer)
    assert report['state']=='stopped_before_memory_write'
    g.ingest.assert_not_called()


def test_nonlocal_transport_cannot_trigger_paid_fallback(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','cloud')
    g=Mock();infer=Mock()
    assert run_cycle(0,stopped=lambda:False,gateway=g,infer=infer)['state']=='deferred'
    infer.assert_not_called();g.retrieve.assert_not_called()
