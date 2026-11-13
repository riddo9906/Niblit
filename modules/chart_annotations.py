"""Views of existing Core decisions. No strategy, order or model authority."""
from __future__ import annotations
import hashlib,json,math,time
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

class Anchor(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    time:float=Field(gt=0,strict=True)
    price:float=Field(gt=0,strict=True)

class ChartScope(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    symbol:str=Field(min_length=1,max_length=160)
    venue:str=Field(min_length=1,max_length=160)
    timeframe:Literal['1m','5m','15m','1h']
    mode:Literal['observe','paper','demo','dry-run','replay']
    account_scope:str=Field(min_length=1,max_length=160)

class Annotation(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:str=Field(pattern=r'^ann_[a-f0-9]{24}$')
    type:Literal['level','trendline','ray','zone','pivot','breakout','invalidation','entry','exit','stop','target','signal','position','disagreement','outcome']
    scope:ChartScope
    role:str=Field(min_length=1,max_length=80)
    anchors:list[Anchor]=Field(min_length=1,max_length=2)
    strategy_id:str=Field(min_length=1,max_length=100)
    strategy_version:str=Field(min_length=1,max_length=100)
    position_ref:str|None=None
    thesis_ref:str|None=None
    observation_id:str=Field(min_length=1,max_length=128)
    observed_at:float=Field(gt=0)
    source_available_at:float|None=Field(default=None,gt=0)
    created_at_basis:Literal['core_observation','source_availability_legacy']='core_observation'
    source:str=Field(min_length=1,max_length=160)
    native_time_offset_seconds:int=Field(default=0,ge=-50400,le=50400)
    fresh:bool
    signal:Literal['BUY','SELL','HOLD','ABSTAIN']|None=None
    assessment:Literal['HOLD','REVIEW','EXIT-CANDIDATE','ABSTAIN']|None=None
    basis:Literal['strategy_measurement','recorded_position','estimated_market','monitor_assessment','recorded_thesis','subsequent_observation']
    explanation:str=Field(min_length=1,max_length=2000)
    invalidation:str=Field(default='',max_length=1000)
    style:dict=Field(default_factory=dict)
    created_at:float=Field(gt=0)
    updated_at:float=Field(gt=0)
    expires_at:float=Field(gt=0)
    revision:str=Field(default='',max_length=64)
    execution_authorized:Literal[False]=False
    @model_validator(mode='after')
    def coordinates(self):
        if self.type in ('zone','trendline','ray') and len(self.anchors)!=2:raise ValueError('two anchors required')
        if len(self.anchors)==2 and self.anchors[1].time<self.anchors[0].time:raise ValueError('unordered time anchors')
        if self.updated_at<self.created_at or (self.fresh and self.scope.mode!='replay' and self.expires_at<=self.updated_at):raise ValueError('invalid lifetime')
        return self

COLORS={'trend_v1':'#4bd4be','breakout_v1':'#efa95b','rsi_reversion_v1':'#bf9fff',
        'bollinger_reversion_v1':'#79b6ff','ema_pullback_v1':'#f6d365','squeeze_breakout_v1':'#ed83b5'}

def build_annotations(observation,analysis,authorization,*,position=None):
    """Map measured fields only. A signal is not permission or a drawn forecast."""
    scope=ChartScope(**{k:observation[k] for k in ChartScope.model_fields})
    key=digest(scope.model_dump())
    base={'schema':'niblit.chart.v1','chart_key':key,'scope':scope.model_dump(),'annotations':[],
          'execution_authorized':False,'analysis_complete':analysis.get('assessment_complete') is True,
          'source':observation.get('source','unavailable'),'regime':analysis.get('regime','unknown'),'state':'core_denied'}
    if authorization.get('allowed') is not True:return base
    rows=observation.get('candles',[])
    if not rows:return {**base,'state':'missing_market'}
    bar=rows[-1]
    stamp=float(bar['timestamp']);close=float(bar['close'])
    if not math.isfinite(stamp) or not math.isfinite(close) or min(stamp,close)<=0:raise ValueError('invalid chart observation')
    interval={'1m':60,'5m':300,'15m':900,'1h':3600}[scope.timeframe]
    available=stamp+interval
    wall_observed=time.time()
    fresh=observation.get('fresh') is True and analysis.get('observation',{}).get('age_seconds',0)<=600 and not analysis.get('abstain_reason','').startswith(('stale','invalid','missing','unordered','insufficient'))
    observed=analysis.get('observation_id') or digest([scope.model_dump(),rows,analysis.get('abstain_reason')])
    position=position or observation.get('position_intelligence') or {}
    recorded=position.get('recorded',{});pref=str(recorded['trade_id']) if recorded.get('trade_id') is not None else None
    result=[]
    def add(strategy,role,kind,prices,explanation,*,basis='strategy_measurement',signal=None,position_ref=None,thesis_ref=None,anchors=None,invalidation='',assessment=None):
        if not all(isinstance(p,(int,float)) and not isinstance(p,bool) and math.isfinite(p) and p>0 for p in prices):return
        anchors=anchors or [dict(time=stamp,price=p) for p in prices]
        item=Annotation(id='ann_'+digest([scope.model_dump(),strategy,role,position_ref])[:24],type=kind,
            scope=scope,role=role,anchors=anchors,strategy_id=strategy,strategy_version='baseline-v1' if strategy in COLORS else 'chart-v1',
            position_ref=position_ref,thesis_ref=thesis_ref,observation_id=observed,observed_at=wall_observed,source_available_at=available,
            assessment=assessment,source=observation['source'],native_time_offset_seconds=observation.get('native_time_offset_seconds',0),fresh=fresh,signal=signal,basis=basis,explanation=explanation[:2000],invalidation=invalidation[:1000],
            style={'color':COLORS.get(strategy,'#c5d3e4'),'dash':basis!='strategy_measurement'},
            created_at=wall_observed,updated_at=wall_observed,expires_at=available+2*interval)
        value=item.model_dump();value['revision']=digest({k:v for k,v in value.items() if k not in ('revision','created_at','updated_at','expires_at','observed_at','created_at_basis')});result.append(value)
    for candidate in analysis.get('candidates',[])[:32]:
        name=candidate.get('strategy','unknown');e=candidate.get('evidence') or {}
        failed=candidate.get('status')=='failed' or not candidate.get('bar')
        signal='ABSTAIN' if failed or not fresh else {'buy':'BUY','sell':'SELL','wait':'HOLD'}.get(candidate.get('side'),'ABSTAIN')
        reason=candidate.get('reason','No strategy explanation supplied')
        add(name,'signal','breakout' if name in ('breakout_v1','squeeze_breakout_v1') and signal in ('BUY','SELL') else 'signal',[close],f'{name}: {signal}. {reason}',signal=signal,invalidation=candidate.get('invalidation',''))
        if failed or not fresh:continue
        fields={'trend_v1':('mean20','mean50'),'breakout_v1':('prior20_high','prior20_low'),
                'ema_pullback_v1':('ema20','ema50'),'squeeze_breakout_v1':('prior20_high','prior20_low')}.get(name,())
        for field in fields:
            if field in e:add(name,field,'level',[e[field]],f'{name}: latest measured {field}; available after this completed candle. Not a projected historical indicator.',invalidation=candidate.get('invalidation',''))
        if name=='bollinger_reversion_v1' and all(k in e for k in ('mean20','band_deviation')):
            for role,value in [('band_lower',e['mean20']-2*e['band_deviation']),('band_mean',e['mean20']),('band_upper',e['mean20']+2*e['band_deviation'])]:
                add(name,role,'level',[value],f'{name}: {role} from existing mean20 and two band_deviations; reference, not a target.')
        if name in ('breakout_v1','squeeze_breakout_v1') and all(k in e for k in ('prior20_high','prior20_low')):
            add(name,'prior_range','zone',[e['prior20_low'],e['prior20_high']],f'{name}: previous20-bar measured range; not an inferred supply/demand zone.',anchors=[dict(time=stamp,price=e['prior20_low']),dict(time=stamp+300,price=e['prior20_high'])])
        # RSI has no defensible price-level threshold; its signal tooltip carries its measured oscillator.
        if name=='rsi_reversion_v1' and 'rsi14' in e:result[-1]['explanation']+=f" RSI14={e['rsi14']:.3f}; no invented price target."
    directions={c.get('side') for c in analysis.get('candidates',[]) if c.get('side') in ('buy','sell')}
    if len(directions)>1 or analysis.get('strategy_failures'):
        add('consensus','comparison','disagreement',[close],analysis.get('selection_reason') or analysis.get('abstain_reason') or 'Incomplete or conflicting strategy assessment.',signal='ABSTAIN')
    if not fresh or not result:add('observation','freshness','position',[close],analysis.get('abstain_reason') or 'Stale/unavailable strategy evaluation; current analytical abstention.',signal='ABSTAIN',basis='estimated_market')
    if pref and recorded.get('pair')==scope.symbol:
        for field,kind,label in [('open_rate','entry','Recorded engine entry; not a broker fill verification'),('stop_loss_abs','stop','Recorded engine stop; enforcement unverified')]:
            if recorded.get(field):add('position',field,kind,[recorded[field]],label,basis='recorded_position',position_ref=pref)
        matching=position.get('estimated',{}).get('bar')==stamp and fresh and analysis.get('assessment_complete') is True and scope.timeframe=='5m'
        assessment=position.get('assessment') if matching else 'ABSTAIN'
        add('position','assessment','exit' if assessment=='EXIT-CANDIDATE' else 'position',[close],f'Position{pref}: {assessment}. '+(position.get('reason','') if matching else 'Assessment belongs to another observation.'),basis='monitor_assessment',position_ref=pref,assessment=assessment)
        later=position.get('subsequent_observation') or {}
        if later.get('current_bar')==stamp and later.get('realized') is False:
            add('position','later_observation','outcome',[close],f"Later public observation versus bar {later.get('previous_bar')}: return {later.get('public_mark_return')}; not an executed or realized profit.",basis='subsequent_observation',position_ref=pref)
        thesis=position.get('entry_thesis',{})
        context=thesis.get('monitor_context') or {}
        if thesis.get('context_identity'):
            for field in ('initial_stop','breakout_level'):
                if context.get(field):add(context.get('strategy','position'),f'thesis_{field}','stop' if field=='initial_stop' else 'invalidation',[context[field]],f'Recorded thesis {field}; {thesis.get("recommendation","ABSTAIN")}. '+thesis.get('reason',''),basis='recorded_thesis',position_ref=pref,thesis_ref=thesis['context_identity'])
        else:add('position','missing_thesis','position',[close],f'Position{pref}: no saved eligible entry thesis; none invented.',basis='recorded_position',position_ref=pref)
    for item in result:
        item['revision']=digest({k:v for k,v in item.items() if k not in ('revision','created_at','updated_at','expires_at','observed_at','created_at_basis')})
        Annotation.model_validate(item)
    return {**base,'state':('fresh' if scope.timeframe=='5m' else 'analysis_unavailable') if fresh else 'stale','annotations':result,'observation_id':observed,'bar':stamp,
            'consensus':analysis.get('signal','ABSTAIN'),'expires_at':available+2*interval}

class ChartAnnotations:
    """Derived head in the SAME ledger; immutable changes use the original outbox."""
    def __init__(self,runtime):
        self.runtime=runtime;self.gateway=runtime.gateway;self.scope=runtime.scope
        with self.gateway.db() as db:db.execute('CREATE TABLE IF NOT EXISTS chart_annotation_heads(chart_key TEXT,namespace TEXT,principal TEXT,payload TEXT NOT NULL,PRIMARY KEY(chart_key,namespace,principal))')
    def publish(self,bundle):
        self.gateway.require('ingest',**self.scope)
        if bundle['state']=='core_denied':return {'state':'core_denied','annotations':[]}
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM chart_annotation_heads WHERE chart_key=? AND namespace=? AND principal=?',(bundle['chart_key'],self.scope['namespace'],self.scope['principal'])).fetchone()
            previous=json.loads(row[0]) if row else {}
            if bundle.get('bar') is not None and previous.get('bar',0)>bundle['bar']:return {**previous,'ignored_observation':'out_of_order'}
            if bundle.get('state')=='missing_market':bundle={**bundle,'bar':previous.get('bar',0),'expires_at':previous.get('expires_at',0)}
            old={x['id']:x for x in previous.get('annotations',[])};new={x['id']:x for x in bundle['annotations']}
            changes=[]
            for key,value in new.items():
                prior=old.get(key)
                if prior:
                    value['created_at']=prior['created_at']
                    value['created_at_basis']=prior.get('created_at_basis','source_availability_legacy')
                    if prior['revision']==value['revision']:new[key]=prior
                if not prior or prior['revision']!=value['revision']:
                    changes.append({'action':'created' if not prior else 'revised','annotation':value,'previous_revision':prior.get('revision') if prior else None})
            changes.extend({'action':'invalidated','annotation':value,'reason':'Not present in the next accepted strategy observation'} for key,value in old.items() if key not in new)
            bundle={**bundle,'namespace':self.scope['namespace'],'annotations':list(new.values()),'memory':previous.get('memory')}
            if changes:
                event={'schema':'niblit.chart.delta.v1','chart_key':bundle['chart_key'],'scope':bundle['scope'],'observation_id':bundle.get('observation_id'),'changes':changes,'execution_authorized':False}
                content=json.dumps(event,sort_keys=True,allow_nan=False);identity=digest(event)
                self.gateway.require('ingest',**self.scope)
                receipt=self.runtime.enqueue(source='chart-event://'+identity,content=content,category='episodic',metadata={'source_type':'chart_annotation_delta','chart_key':bundle['chart_key'],'parent_namespace':(db.execute('SELECT parent FROM market_partitions WHERE namespace=? AND principal=?',(self.scope['namespace'],self.scope['principal'])).fetchone() or [self.scope['namespace']])[0],'verification':'analytical_visual_not_execution'},_db=db)
                bundle['memory']={'id':receipt,'queued':True,'projection':'pending_not_verified'}
                db.execute('INSERT INTO chart_annotation_heads VALUES(?,?,?,?) ON CONFLICT(chart_key,namespace,principal) DO UPDATE SET payload=excluded.payload',(bundle['chart_key'],self.scope['namespace'],self.scope['principal'],json.dumps(bundle,sort_keys=True,allow_nan=False)))
            return bundle
    def read(self,chart_key,*,history=False,now=None):
        self.gateway.require('read',**self.scope)
        with self.gateway.db() as db:
            row=db.execute('SELECT payload FROM chart_annotation_heads WHERE chart_key=? AND namespace=? AND principal=?',(chart_key,self.scope['namespace'],self.scope['principal'])).fetchone()
            if not row:return None
            bundle=json.loads(row[0])
            if history:
                rows=db.execute("SELECT body FROM ingestion_outbox WHERE json_extract(body,'$.metadata.chart_key')=? AND json_extract(body,'$.namespace')=? AND json_extract(body,'$.principal')=? ORDER BY rowid DESC LIMIT 12",(chart_key,self.scope['namespace'],self.scope['principal'])).fetchall()
                bundle['history']=[json.loads(json.loads(x[0])['content']) for x in rows]
                for event in bundle['history']:
                    if any('source_available_at' not in change['annotation'] for change in event['changes']):
                        event['timing_note']='Legacy in-session reference metadata used source availability time; not evidence that a prediction existed then.'
        stamp=time.time() if now is None else now
        if stamp>bundle.get('expires_at',0):bundle={**bundle,'state':'stale','expired':True}
        return bundle

def record_chart_annotations(runtime,observation,analysis,authorization):
    bundle=build_annotations(observation,analysis,authorization)
    if bundle['state']=='core_denied':return bundle
    # A stable view partition spans fresh/stale/failed evaluations, while the
    # original strategy-decision namespaces and their identities remain untouched.
    from modules.memory_laboratory.runtime import MemoryRuntime
    from modules.demo_strategy import STRATEGIES
    with runtime.gateway.db() as db:
        parent=db.execute('SELECT parent FROM market_partitions WHERE namespace=? AND principal=?',(runtime.scope['namespace'],runtime.scope['principal'])).fetchone()
    parent=parent[0] if parent else runtime.scope['namespace']
    identity=[observation.get(k) for k in ('symbol','venue','timeframe','mode','account_scope')]
    namespace=runtime.gateway.register_market_partition(parent,identity,{'policy':'chart-v1','strategies':sorted(STRATEGIES)},runtime.scope['principal'])
    view=MemoryRuntime(runtime.gateway,scope={'namespace':namespace,'principal':runtime.scope['principal']})
    return ChartAnnotations(view).publish(bundle)
