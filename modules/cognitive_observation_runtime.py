"""Core-owned reads, existing broker adapters and canonical memory; no orders."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import threading
from modules.observation_supervisor import ObservationJob,ObservationSupervisor
from modules.memory_laboratory.cognitive import CognitiveMemory

_install_lock=threading.Lock()


def episode_sink(memory, predictor=None):
    def persist(job,result):
        if predictor is not None:
            try:
                predictor.observe(job,result)
                predictor.last_error=None
            except Exception as error:
                predictor.last_error=type(error).__name__
                # Shadow evaluation failure cannot suppress honest broker observation.
                import logging
                logging.getLogger('MarketPrediction').warning('Shadow evaluation unavailable: %s',type(error).__name__)
        frame=(result.get('evidence') or {}).get('M5') or {}
        snapshot=frame.get('snapshot_id')
        if not snapshot:return {'state':'no_market_snapshot','execution_authorized':False}
        content=json.dumps({'source':job.source,'account':job.account,'terminal':job.terminal,
            'broker':(result.get('account') or {}).get('broker'),
            'server':(result.get('account') or {}).get('server'),
            'environment':(result.get('account') or {}).get('environment'),
            'symbol':job.symbol,'snapshot_id':snapshot,'evidence':frame,
            'decision':'abstain','reason':'observation_only_no_execution_authority'},sort_keys=True,allow_nan=False)
        stamp=(frame.get('indicators') or {}).get('updated_at')
        if not isinstance(stamp,(int,float)):return {'state':'closed_time_unavailable'}
        iso=datetime.fromtimestamp(stamp,timezone.utc).isoformat()
        return memory.record(domain='trading',event_id=snapshot,source=job.source+':'+job.account+':'+job.terminal,
            observed_at=iso,available_at=iso,content=content,kind='observation',rule_version='market-evidence-v1')
    return persist


def install(core, *, desktop=None, remote=None, remote_market=None, memory=None, config=None):
    """Restart resumes reads only; explicit identity configuration is mandatory."""
    with _install_lock:
        existing=getattr(core,'cognitive_observation',None)
        if existing:return existing
        if config is None:
            path=os.environ.get('NIBLIT_OBSERVATION_CONFIG','').strip()
            if not path:return None
            if not Path(path).is_absolute():raise ValueError('Absolute observation configuration required')
            config=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if set(config)!={'schema_version','jobs'} or config['schema_version']!='observation-supervisor/1':
            raise ValueError('Unsupported observation configuration')
        jobs=[ObservationJob(**item) for item in config['jobs']]
        if any(j.source not in ('desktop','vps') for j in jobs):raise ValueError('Unknown source')
        if desktop is None:
            from modules.desktop_market_intelligence import DesktopMarketIntelligence
            from modules.mt5_bridge import MT5Bridge
            from modules.trading_desk import core_market_analysis
            desktop=DesktopMarketIntelligence(MT5Bridge(),core_market_analysis)
        if remote is None:
            from modules.remote_broker_gateway import configured_gateway
            remote=configured_gateway()
        demo_profile=os.getenv('NIBLIT_MT5_DEMO_PROFILE',os.getenv('NIBLIT_EXNESS_DEMO_PROFILE','')).strip()
        if remote_market is None and demo_profile:
            from modules.remote_demo_adapter import RemoteDemoAdapter
            from modules.remote_market_intelligence import RemoteMarketIntelligence
            from modules.trading_desk import core_market_analysis
            remote_market=RemoteMarketIntelligence(RemoteDemoAdapter(demo_profile),core_market_analysis)
        if memory is None:
            from modules.memory_laboratory.runtime import runtime_memory
            runtime=runtime_memory()
            if runtime is None:raise RuntimeError('Canonical memory required for continuous observation')
            memory=CognitiveMemory(runtime)
        def vps(job):
            if job.symbol!='__account__' and remote_market is not None:
                return remote_market.observe(job.symbol,job.account,job.terminal)
            if remote is None:raise ConnectionError('Remote observation not configured')
            status=remote.status();raw=status.get('observation') or {};observed=raw.get('account_observation') or {}
            account=observed.get('account') or {}
            if account!=remote.profile.account:raise ValueError('Remote account changed or unavailable')
            if job.symbol!='__account__':raise ValueError('Remote candle adapter not yet available')
            return {'schema_version':'remote-account-observation/1','connected':status.get('broker_verified') is True,
                'account':{'identity':str(account['login']),'terminal_id':account['terminal_id'],
                           'server':account['server'],'environment':account['environment']},
                'symbol':job.symbol,'received_at':observed.get('observed_at'),
                'fresh':status.get('broker_verified') is True,'execution_authorized':False,
                'limitations':['Account observation only; remote market candles pending']}
        from modules.market_prediction import PredictionLedger
        predictor=PredictionLedger(memory)
        core.market_predictions=predictor
        supervisor=ObservationSupervisor(jobs,{'desktop':lambda j:desktop.observe(j.symbol,j.account,j.terminal),
            'vps':vps},sink=episode_sink(memory,predictor))
        core.cognitive_observation=supervisor
        supervisor.start()
        return supervisor
