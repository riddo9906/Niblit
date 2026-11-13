"""Read-only postconditions for existing lifecycle command handlers; never an executor."""
def observe(core,text):
    name=' '.join(text.lower().split())
    family=None;expected=None;engine=None;worker=None
    if name in ('evolve start','start evolving','start evolution','evolve stop','stop evolving','stop evolution'):
        family='evolution';expected=name in ('evolve start','start evolving','start evolution')
        engine=getattr(core,'evolve_engine',None);worker=getattr(engine,'_thread',None)
    elif name.split(' ',1)[0] in ('start_slsa','restart_slsa','stop_slsa'):
        family='slsa';expected=not name.startswith('stop_slsa')
        engine=getattr(core,'slsa_engine',None);worker=getattr(core,'slsa_thread',None)
    elif name in ('hf-enable','hf-disable'):
        family='hf_provider';expected=name=='hf-enable'
        engine=(getattr(core,'hf_brain',None) or getattr(core,'hf',None)
                or getattr(getattr(core,'brain',None),'hf_brain',None))
        enabled=getattr(engine,'enabled',getattr(engine,'_enabled',None))
        return {'family':family,'expected_active':expected,'component_present':engine is not None,
                'observed_active':enabled,'verified':engine is not None and enabled is expected}
    else:return None
    alive=bool(worker and worker.is_alive())
    running=bool(getattr(engine,'running',alive))
    active=alive and running if expected else alive or running
    return {'family':family,'expected_active':expected,'component_present':engine is not None,
            'worker_alive':alive,'observed_active':active,'verified':active==expected}
