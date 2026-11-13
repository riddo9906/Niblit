"""Bounded read-only source scheduling. No execution, account discovery or failover.

Collectors own authenticated transport, binding checks and bounded I/O. A blocked
collector occupies only its own lane; it is never duplicated or forcefully killed.
"""
from copy import deepcopy
from dataclasses import dataclass
import math
import threading
import time


@dataclass(frozen=True)
class ObservationJob:
    source: str
    symbol: str
    account: str
    terminal: str
    interval: float = 30
    max_age: float = 60

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() or len(v)>128
               for v in (self.source,self.symbol,self.account,self.terminal)):
            raise ValueError('Explicit bounded source binding required')
        if (not all(type(v) in (int,float) and math.isfinite(v) for v in (self.interval,self.max_age))
                or not 5 <= self.interval <= 3600 or not 5 <= self.max_age <= 7200):
            raise ValueError('Invalid observation timing')


class ObservationSupervisor:
    def __init__(self, jobs, collectors, *, sink=None, clock=time.time):
        if not 1 <= len(jobs) <= 16 or len({j.source for j in jobs})>2:
            raise ValueError('At most two source lanes and sixteen jobs')
        self.jobs=tuple(jobs);self.collectors=dict(collectors);self.sink=sink;self.clock=clock
        self.keys=[(j.source,j.symbol,j.account,j.terminal) for j in jobs]
        if len(set(self.keys))!=len(self.keys) or any(j.source not in collectors for j in jobs):
            raise ValueError('Duplicate job or missing explicit collector')
        self.lock=threading.RLock();self.stop_event=threading.Event();self.threads=[]
        self.state={k:{'next_due':0,'failures':0,'reads':0,'state':'not_observed',
                       'last_good':None,'last_error':None} for k in self.keys}

    def poll_source(self, source):
        """One bounded pass, oldest due job first; independent source lanes."""
        due=[]
        with self.lock:
            for job,key in zip(self.jobs,self.keys):
                state=self.state[key]
                if job.source==source and state['state']!='reading' and state['next_due']<=self.clock():
                    due.append((state['next_due'],job,key))
            if not due or self.stop_event.is_set():return False
            _,job,key=min(due,key=lambda item:item[0]);state=self.state[key];state['state']='reading'
        try:
            result=self.collectors[source](job)
            identity=result.get('account') or {}
            if (result.get('connected') is not True or identity.get('identity')!=job.account
                    or identity.get('terminal_id')!=job.terminal
                    or result.get('symbol')!=job.symbol or result.get('execution_authorized') is not False):
                raise ValueError('Observation binding or read-only contract rejected')
            stamp=result.get('received_at')
            if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=self.clock()-stamp<=job.max_age:
                raise ValueError('Invalid observation receipt time')
            receipt=self.sink(job,result) if self.sink else None
            with self.lock:
                state.update(state='observed',last_good=deepcopy(result),last_error=None,
                             failures=0,reads=state['reads']+1,next_due=self.clock()+job.interval,
                             episode_receipt=receipt)
        except Exception as exc:
            with self.lock:
                state.update(state='unavailable',last_error=type(exc).__name__,
                             failures=state['failures']+1)
                state['next_due']=self.clock()+min(300,job.interval*2**min(state['failures'],4))
        return True

    def status(self):
        with self.lock:
            result=[]
            for job,key in zip(self.jobs,self.keys):
                state=self.state[key];last=state['last_good'];age=None if last is None else self.clock()-last['received_at']
                fresh=bool(last and last.get('fresh') is True and 0<=age<=job.max_age
                           and state['state'] not in ('unavailable','not_observed'))
                result.append({'source':job.source,'symbol':job.symbol,'account':job.account,
                    'terminal':job.terminal,'state':state['state'],'fresh':fresh,
                    'age_seconds':age,'last_success_at':last['received_at'] if last else None,
                    'failures':state['failures'],'reads':state['reads'],'error_type':state['last_error'],
                    'episode_receipt':state.get('episode_receipt'),'execution_authorized':False})
            return {'schema_version':'observation-supervisor/1','jobs':result,
                    'running':any(t.is_alive() for t in self.threads),
                    'comparisons':self.compare_sources(),
                    'execution_authorized':False,'restart_policy':'revalidate_sources_only'}

    def compare_sources(self):
        """Exact-symbol, aligned quote evidence only; never an arbitrage vote."""
        comparisons=[]
        with self.lock:
            for i,(left,lk) in enumerate(zip(self.jobs,self.keys)):
                for right,rk in list(zip(self.jobs,self.keys))[i+1:]:
                    if left.source==right.source or left.symbol!=right.symbol:continue
                    states=[self.state[lk],self.state[rk]];values=[s['last_good'] for s in states]
                    base={'symbol':left.symbol,'sources':[left.source,right.source],
                          'execution_authorized':False,'meaning':'analytical_comparison_not_execution_signal'}
                    if any(v is None for v in values):
                        comparisons.append({**base,'state':'source_unavailable'});continue
                    quotes=[v.get('quote') or {} for v in values]
                    numbers=[q.get(k) for q in quotes for k in ('bid','ask','timestamp')]
                    fresh=all(v.get('fresh') is True and 0<=self.clock()-v['received_at']<=j.max_age
                              and s['state']!='unavailable' for v,j,s in zip(values,(left,right),states))
                    valid=all(type(n) in (int,float) and math.isfinite(n) and n>0 for n in numbers)
                    valid=valid and all(q['ask']>=q['bid'] for q in quotes)
                    if not fresh or not valid:
                        comparisons.append({**base,'state':'stale_or_invalid'});continue
                    if abs(quotes[0]['timestamp']-quotes[1]['timestamp'])>5:
                        comparisons.append({**base,'state':'timestamps_not_aligned'});continue
                    comparisons.append({**base,'state':'aligned',
                        'quotes':deepcopy(quotes),'mid_difference':sum(quotes[0][k] for k in ('bid','ask'))/2-sum(quotes[1][k] for k in ('bid','ask'))/2,
                        'spread_difference':(quotes[0]['ask']-quotes[0]['bid'])-(quotes[1]['ask']-quotes[1]['bid']),
                        'contract_equivalence':'not_assumed'})
        return comparisons

    def start(self):
        with self.lock:
            if any(t.is_alive() for t in self.threads):return False
            self.stop_event.clear();self.threads=[]
            for source in sorted({j.source for j in self.jobs}):
                def run(selected=source):
                    while not self.stop_event.is_set():
                        if not self.poll_source(selected):self.stop_event.wait(.5)
                thread=threading.Thread(target=run,name='market-observe-'+source,daemon=True)
                self.threads.append(thread);thread.start()
            return True

    def stop(self, timeout=2):
        self.stop_event.set();deadline=time.monotonic()+timeout
        for thread in self.threads:thread.join(max(0,deadline-time.monotonic()))
        return not any(t.is_alive() for t in self.threads)
