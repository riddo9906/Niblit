import copy,json,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from modules.chart_annotations import Annotation,ChartAnnotations,build_annotations
from modules.chart_views import ChartView,freqtrade_annotations,mt5_tsv,pine_export
from modules.strategy_manager import assess_observation
from modules.memory_laboratory.runtime import MemoryRuntime
from test_core_market_pipeline import observation,pipeline,ingest
from test_memory_laboratory_gateway import Backend,gateway

@pytest.fixture
def evidence():
    o=observation();return o,assess_observation(o)

def bundle(evidence):return build_annotations(*evidence,{'allowed':True})

def test_actual_six_strategy_mapping_and_coordinates(evidence):
    o,a=evidence;b=bundle(evidence);ann=b['annotations']
    assert len({x['strategy_id'] for x in ann if x['strategy_id'].endswith('_v1')})==6
    values={c['strategy']:c for c in a['candidates']}
    for item in ann:
        Annotation.model_validate(item)
        assert item['anchors'][0]['time']==o['candles'][-1]['timestamp']
        assert item['execution_authorized'] is False and item['observation_id']==a['observation_id']
        if item['role'] in ('mean20','mean50','ema20','ema50','prior20_high','prior20_low'):
            assert item['anchors'][0]['price']==values[item['strategy_id']]['evidence'][item['role']]
    assert not [x for x in ann if x['strategy_id']=='rsi_reversion_v1' and x['type']=='level']
    assert not any('confidence' in x for x in ann)

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),0,-1,True])
def test_schema_rejects_bad_coordinates(evidence,bad):
    a=copy.deepcopy(bundle(evidence)['annotations'][0]);a['anchors'][0]['price']=bad
    with pytest.raises(ValidationError):Annotation.model_validate(a)

@pytest.mark.parametrize('change',[
    {'type':'zone'},{'expires_at':1},{'id':'manual-user-line'},{'execution_authorized':True},
    {'scope':dict(symbol='X',venue='Y',timeframe='2m',mode='demo',account_scope='A')},
])
def test_schema_rejects_invalid_lifetime_identity_and_authority(evidence,change):
    a=copy.deepcopy(bundle(evidence)['annotations'][0]);a.update(change)
    with pytest.raises(ValidationError):Annotation.model_validate(a)

def test_no_invented_levels_for_signal_only_output(evidence):
    o,a=evidence;a={**a,'candidates':[{'strategy':'external','bar':o['candles'][-1]['timestamp'],'side':'buy','reason':'Only direction provided'}]}
    b=build_annotations(o,a,{'allowed':True})
    assert len(b['annotations'])==1 and b['annotations'][0]['type']=='signal'
    assert b['annotations'][0]['anchors'][0]['price']==o['candles'][-1]['close']

def test_core_denial_has_no_drawings(evidence):
    b=build_annotations(*evidence,{'allowed':False});assert not b['annotations'] and b['state']=='core_denied'

def test_stale_and_partial_failure_preserve_abstention(evidence):
    o,a=evidence;o['fresh']=False;b=build_annotations(o,a,{'allowed':True})
    assert b['state']=='stale' and all(x.get('signal') in (None,'ABSTAIN') for x in b['annotations'])
    assert not any(x['type']=='level' for x in b['annotations'])
    o['fresh']=True;a['candidates'][0].update(status='failed',evidence={});a['strategy_failures']=[{'strategy':'trend_v1'}]
    b=build_annotations(o,a,{'allowed':True});assert any(x['type']=='disagreement' for x in b['annotations'])
    assert not any(x['strategy_id']=='trend_v1' and x['type']=='level' for x in b['annotations'])

def test_disagreement_never_becomes_visual_consensus(evidence):
    o,a=evidence;a['candidates'][0]['side']='buy';a['candidates'][1]['side']='sell';a['signal']='ABSTAIN'
    b=build_annotations(o,a,{'allowed':True});assert b['consensus']=='ABSTAIN'
    assert [x['signal'] for x in b['annotations'] if x['type']=='disagreement']==['ABSTAIN']

def test_memory_idempotence_revision_invalidation_and_restart(tmp_path,evidence):
    g=gateway(tmp_path,Backend());r=MemoryRuntime(g);view=ChartAnnotations(r)
    b=view.publish(bundle(evidence));receipt=b['memory']['id'];size=g.path.stat().st_size
    assert view.publish(bundle(evidence))['memory']['id']==receipt
    with g.db() as db:assert db.execute('SELECT count(*) FROM ingestion_outbox').fetchone()[0]==1
    o,a=copy.deepcopy(evidence);a['candidates']=a['candidates'][1:];a['observation_id']='next-observation'
    newer=view.publish(build_annotations(o,a,{'allowed':True}))
    assert newer['memory']['id']!=receipt
    reopened=ChartAnnotations(MemoryRuntime(gateway(tmp_path,Backend())))
    found=reopened.read(b['chart_key'],history=True,now=b['bar']+301)
    assert found['annotations']==newer['annotations']
    assert any(c['action']=='invalidated' for e in found['history'] for c in e['changes'])
    assert 'candles' not in json.dumps(found['history'])
    assert reopened.read(b['chart_key'],now=b['expires_at']+1)['state']=='stale'

def test_old_observation_does_not_rewind_annotations(tmp_path,evidence):
    g=gateway(tmp_path,Backend());view=ChartAnnotations(MemoryRuntime(g));b=view.publish(bundle(evidence));old=copy.deepcopy(b);old['bar']-=300
    assert view.publish(old)['ignored_observation']=='out_of_order'

def test_stable_annotation_ids_across_next_bar(evidence):
    first=bundle(evidence);o,a=copy.deepcopy(evidence)
    for row in o['candles']:row['timestamp']+=300
    a['observation_id']='next';second=build_annotations(o,a,{'allowed':True})
    assert {x['id'] for x in first['annotations']}=={x['id'] for x in second['annotations']}
    assert first['annotations'][0]['revision']!=second['annotations'][0]['revision']

@pytest.mark.parametrize('field,value',[('symbol','other'),('venue','other'),('mode','paper'),('account_scope','other')])
def test_scope_and_memory_isolation(tmp_path,evidence,field,value):
    first=bundle(evidence);o,a=copy.deepcopy(evidence);o[field]=value;other=build_annotations(o,a,{'allowed':True})
    assert first['chart_key']!=other['chart_key']
    assert not {x['id'] for x in first['annotations']} & {x['id'] for x in other['annotations']}
    g=gateway(tmp_path,Backend());ChartAnnotations(MemoryRuntime(g,scope={'namespace':'test','principal':'owner'})).publish(first)
    assert ChartAnnotations(MemoryRuntime(g,scope={'namespace':'other','principal':'owner'})).read(first['chart_key']) is None

def test_permission_revocation_precedes_read_or_write(tmp_path,evidence):
    g=gateway(tmp_path,Backend());v=ChartAnnotations(MemoryRuntime(g));b=v.publish(bundle(evidence));g.authorize=lambda *args:False
    with pytest.raises(PermissionError):v.read(b['chart_key'])
    with pytest.raises(PermissionError):v.publish(b)

def test_position_values_are_recorded_and_absent_thesis_not_invented(evidence):
    o,a=evidence;record={'recorded':{'trade_id':42,'pair':o['symbol'],'open_rate':90.,'stop_loss_abs':120.},'estimated':{'bar':o['candles'][-1]['timestamp']},'assessment':'HOLD','entry_thesis':{'state':'not_eligible'}}
    b=build_annotations(o,a,{'allowed':True},position=record)
    assert next(x for x in b['annotations'] if x['role']=='open_rate')['anchors'][0]['price']==90
    assert next(x for x in b['annotations'] if x['role']=='missing_thesis')['basis']=='recorded_position'
    assert not any(x['basis']=='recorded_thesis' for x in b['annotations'])

def test_mt5_rejects_futures_alias_and_maps_broker_time(evidence):
    with pytest.raises(ValueError):mt5_tsv(bundle(evidence))
    o,a=evidence;o.update(venue='mt5:fixture',account_scope='mt5-abcdef',native_time_offset_seconds=7200)
    b=build_annotations(o,a,{'allowed':True});text=mt5_tsv(b);fields=text.splitlines()[1].split('\t')
    assert fields[1]==o['symbol'] and fields[2]=='5' and fields[3]=='mt5-abcdef'
    assert fields[4]=='demo' and int(fields[6])==o['candles'][-1]['timestamp']+7200
    assert text.endswith('END\n')

def test_freqtrade_supported_area_contract_and_pine_snapshot(evidence):
    b=bundle(evidence);areas=freqtrade_annotations(b)
    assert areas and {x['type'] for x in areas}=={'area','line','point'}
    assert all(x['y_end']>=x['y_start'] for x in areas if x['type']=='area')
    pine=pine_export(b)
    assert '//@version=6' in pine and 'expectedTicker' in pine and 'xloc=xloc.bar_time' in pine
    assert 'strategy.entry' not in pine and 'strategy.exit' not in pine

def test_original_core_pipeline_publishes_drawings_and_failure_isolation(pipeline,monkeypatch):
    event=ingest(pipeline,observation());b=event.metadata['chart_annotations']
    assert b['annotations'] and b['memory']['queued'] and event.metadata['market_memory']['queued']
    monkeypatch.setattr('modules.chart_annotations.record_chart_annotations',lambda *args:(_ for _ in ()).throw(RuntimeError('adapter unavailable')))
    event=ingest(pipeline,observation())
    assert event.metadata['chart_annotations']['state']=='pending' and event.metadata['market_memory']['queued']

def test_native_source_owns_only_namespaced_objects_and_no_execution():
    root=Path(__file__).resolve().parents[1];source=(root/'integrations/mt5/NiblitChartObjects.mq5').read_text(encoding='utf-8')
    assert 'NIBLIT.ANN.' in source and 'StringFind(name,prefix)==0' in source
    assert 'OBJ_HLINE' in source and 'OBJ_RECTANGLE' in source and 'OBJ_TREND' in source
    assert not any(x in source for x in ('OrderSend','CTrade','PositionClose','WebRequest','TRADE_ACTION'))

def test_native_clock_requires_two_fresh_receipts(tmp_path,monkeypatch):
    scope='mt5-identity';folder=tmp_path/'Files/NiblitCharts';folder.mkdir(parents=True)
    clock=folder/f'clock_EURUSD_{scope}.tsv';now=int(time.time())
    account=SimpleNamespace();terminal=SimpleNamespace(commondata_path=tmp_path)
    mt5=SimpleNamespace(connect=lambda:(None,account,terminal),identity=lambda a:'identity')
    view=ChartView(None,mt5,None);native={'symbol':'EURUSD','account':{'identity':'identity'}}
    clock.write_text(f'NIBLIT_CLOCK_V1\tEURUSD\t{scope}\t{now+7200}\t{now}\t{now+7200}')
    assert view.native_clock(native)['verified'] is False
    monkeypatch.setattr('modules.chart_views.time.time',lambda:now+6)
    clock.write_text(f'NIBLIT_CLOCK_V1\tEURUSD\t{scope}\t{now+7206}\t{now+6}\t{now+7206}')
    assert view.native_clock(native)['offset_seconds']==7200 and view.native_clock(native)['verified']


def test_existing_market_worker_drains_chart_after_last_market_event(pipeline):
    event=ingest(pipeline,observation());chart=event.metadata['chart_annotations']
    for _ in range(3):pipeline.runtime.tick_market_partitions()
    with pipeline.gateway.db() as db:
        row=db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(chart['memory']['id'],)).fetchone()
        assert row[0]=='complete'


def test_stale_observation_invalidates_fresh_drawings_in_same_view(pipeline):
    fresh=ingest(pipeline,observation()).metadata['chart_annotations']
    stale=observation();stale['fresh']=False
    current=ingest(pipeline,stale).metadata['chart_annotations']
    assert current['namespace']==fresh['namespace'] and current['state']=='stale'
    runtime=MemoryRuntime(pipeline.gateway,scope={'namespace':current['namespace'],'principal':'desktop_operator'})
    history=ChartAnnotations(runtime).read(current['chart_key'],history=True)
    assert any(c['action']=='invalidated' for e in history['history'] for c in e['changes'])


def test_freqtrade_reader_matches_scope_profile_and_never_mutates(tmp_path,evidence):
    import hashlib
    from modules.freqtrade_chart_adapter import read_plot_annotations
    root=tmp_path;profile=root/'config.json';profile.write_text('{"dry_run":true}')
    b=bundle(evidence);pair=b['scope']['symbol'];b['scope']['mode']='dry-run'
    payload={'schema':'niblit.frequi.v1','scope':b['scope'],'annotations':freqtrade_annotations(b),'expires_at':time.time()+60,'core_authorization':{'allowed':True},'execution_authorized':False,'profile_sha256':hashlib.sha256(profile.read_bytes()).hexdigest()}
    folder=root/'niblit_chart_annotations';folder.mkdir();p=folder/(hashlib.sha256((pair+'|5m').encode()).hexdigest()+'.json');p.write_text(json.dumps(payload))
    config={'dry_run':True,'user_data_dir':root};before=p.read_bytes()
    assert read_plot_annotations(config,pair,'5m') and p.read_bytes()==before
    assert read_plot_annotations({'dry_run':False,'user_data_dir':root},pair,'5m')==[]
    assert read_plot_annotations(config,pair,'1h')==[]
    profile.write_text('{"dry_run":false}')
    assert read_plot_annotations(config,pair,'5m')==[]


def test_other_timeframe_only_displays_observation_not_m5_rules(evidence):
    o,a=evidence;o['timeframe']='1h';a=assess_observation(o);b=build_annotations(o,a,{'allowed':True})
    assert b['state']=='analysis_unavailable' and b['consensus']=='ABSTAIN'
    assert not any(x['strategy_id'].endswith('_v1') for x in b['annotations'])
    assert b['annotations'][0]['source_available_at']==o['candles'][-1]['timestamp']+3600


def test_position_assessment_never_reuses_a_different_bar_or_timeframe(evidence):
    o,a=evidence;position={'recorded':{'trade_id':45,'pair':o['symbol'],'open_rate':100.},'estimated':{'bar':o['candles'][-1]['timestamp']-300},'assessment':'HOLD'}
    b=build_annotations(o,a,{'allowed':True},position=position)
    assert next(x for x in b['annotations'] if x['role']=='assessment')['assessment']=='ABSTAIN'
    position['estimated']['bar']=o['candles'][-1]['timestamp']
    b=build_annotations(o,a,{'allowed':True},position=position)
    assert next(x for x in b['annotations'] if x['role']=='assessment')['assessment']=='HOLD'
    a['assessment_complete']=False
    b=build_annotations(o,a,{'allowed':True},position=position)
    assert next(x for x in b['annotations'] if x['role']=='assessment')['assessment']=='ABSTAIN'


def test_actual_creation_time_is_not_backdated_to_the_candle(tmp_path,evidence):
    started=time.time();b=bundle(evidence);a=b['annotations'][0]
    assert a['created_at']>=started and a['observed_at']>=started
    assert a['source_available_at']==evidence[0]['candles'][-1]['timestamp']+300
    g=gateway(tmp_path,Backend());v=ChartAnnotations(MemoryRuntime(g));one=v.publish(b)
    time.sleep(.01);two=v.publish(bundle(evidence))
    assert one['memory']['id']==two['memory']['id'] and one['annotations']==two['annotations']


def test_missing_feed_retires_drawings_without_inventing_a_price(tmp_path,evidence):
    g=gateway(tmp_path,Backend());v=ChartAnnotations(MemoryRuntime(g));first=v.publish(bundle(evidence))
    o,a=copy.deepcopy(evidence);o['candles']=[];a['assessment_complete']=False
    latest=v.publish(build_annotations(o,a,{'allowed':True}))
    assert latest['state']=='missing_market' and latest['annotations']==[]
    assert latest['memory']['id']!=first['memory']['id']


def test_chart_cache_rechecks_execution_mode_before_reuse(tmp_path,evidence,monkeypatch):
    import httpx
    o,a=evidence;root=tmp_path/'core';root.mkdir();profile=root.parent/'freqtrade/user_data/config.json';profile.parent.mkdir(parents=True);profile.write_text('{}')
    current={'dry_run':True,'exchange':'fixture','timeframe':'5m'}
    calls=[]
    class Desk:
        def configuration(self):return dict(current)
        def api(self,path,payload=None):
            assert payload is None
            return {'whitelist':[o['symbol']]} if path=='whitelist' else []
        def market(self,symbol,config):return {'fresh':True,'source':'fixture','candles':o['candles']}
    desk=Desk();desk.root=root
    def core(obs):
        calls.append(obs['mode']);return {'analysis':a,'authorization':{'allowed':True},'annotations':build_annotations(obs,a,{'allowed':True})}
    class Offline:
        def __enter__(self):raise ConnectionError('No monitor in this controlled test')
        def __exit__(self,*args):pass
    monkeypatch.setattr(httpx,'Client',lambda **kw:Offline())
    v=ChartView(desk,None,core);one=v.snapshot('freqtrade',o['symbol']);current['dry_run']=False;two=v.snapshot('freqtrade',o['symbol'])
    assert calls==['dry-run','observe'] and one['annotations']['scope']['mode']!=two['annotations']['scope']['mode']
