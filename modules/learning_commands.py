"""Explicit operator learning activation through the existing scoped task authority."""
import os
from pathlib import Path

def start(core,topic=''):
    engine=getattr(core,'autonomous_engine',None)
    if engine is None:return {'state':'unavailable','execution_started':False,'reason':'ALE is not initialized'}
    from server import _get_learning_control,_learning_decision_lock
    from modules.native_runtime_readiness import check_readiness
    with _learning_decision_lock:
        pm,gateway,runtime_id,_=_get_learning_control();pm._load()
        if not pm.check('command.operator.autonomous_learn_start'):
            raise PermissionError('Explicit ALE start command authorization required')
        lifecycle=engine.lifecycle_status()
        if lifecycle['worker_alive'] or lifecycle['unfinished_steps'] or engine.running:
            return {'state':'busy','execution_started':False,'reason':'Existing ALE work still owns its lifecycle','lifecycle':lifecycle}
        readiness=check_readiness(os.environ,Path(os.getenv('NIBLIT_WORKSPACE_ROOT','.')))
        if not readiness['ready']:
            return {'state':'unavailable','execution_started':False,'reason':'Local learning dependencies are not ready','checks':readiness['checks']}
        topic=topic.strip() or 'Niblit canonical memory durability'
        ident=pm.propose_learning(gateway,topic,'Explicit operator Start command: one bounded local-only evidence cycle; no paid calls, code deployment, weight training or trading.',renew=True)
        proposal=next(p for p in pm.learning_requests(gateway,runtime_id) if p['id']==ident)
        pm.decide_learning(gateway,ident,proposal['spec_hash'],'approve_once',runtime_id)
        try:
            accepted=engine.start(max_cycles=1,task_authorization=(pm,gateway,ident,runtime_id))
        except Exception:
            pm.finish_learning(gateway,ident,'failed',{'reason':'ALE worker startup failed'});raise
        if not accepted:
            pm.finish_learning(gateway,ident,'failed',{'reason':'ALE lifecycle became busy'})
            return {'state':'busy','execution_started':False,'reason':'ALE lifecycle became busy'}
        state=engine.lifecycle_status()
        if not state['worker_alive'] and not engine.running:
            task=next(p for p in pm.learning_requests(gateway,runtime_id) if p['id']==ident)
            if task['state'] not in ('completed',):
                pm.finish_learning(gateway,ident,'failed',{'reason':'Worker exited without completion'})
                return {'state':'failed','execution_started':False,'reason':'Worker exited before activation was observed','task_id':ident}
        return {'state':'started','execution_started':True,'task_id':ident,'topic':topic,
                'cycles':1,'limits':proposal['spec']['limits'],'local_only':True,'paid_requests':0,
                'lifecycle':state,'funded_execution_enabled':False}

def stop(core):
    engine=getattr(core,'autonomous_engine',None)
    if engine is None:return {'state':'unavailable','execution_started':False,'reason':'ALE is not initialized'}
    finished=engine.stop()
    state=engine.lifecycle_status()
    done=bool(finished and not state['worker_alive'] and not state['unfinished_steps'])
    return {'state':'stopped' if done else 'stopping','execution_started':False,
            'stop_requested':True,'worker_finished':done,'lifecycle':state}
