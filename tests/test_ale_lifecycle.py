"""Exercise real lifecycle methods with no Core boot, network or paid inference."""
import threading
from types import SimpleNamespace

from modules.autonomous_learning_engine import AutonomousLearningEngine
from modules.learning_status import ale_owns_research


def engine():
    # Bypass the large dependency graph; exercise production ownership methods.
    e=AutonomousLearningEngine.__new__(AutonomousLearningEngine)
    e.running=False;e.learning_thread=None;e._lifecycle_lock=threading.RLock()
    e._step_futures={};e._max_cycles=None;e._worker_error=None
    e._stop_event=threading.Event();e.kernel=None;e.step_timeout=.02
    return e


def test_bounded_worker_finishes_and_releases_running_state():
    e=engine();calls=[]
    e.startup_delay=0;e.poll_interval=1;e.is_idle=lambda:True
    e._run_autonomous_cycle=lambda:calls.append('cycle')
    assert e.start(max_cycles=1)
    e.learning_thread.join(2)
    assert calls==['cycle']
    assert e.lifecycle_status()['state']=='idle'
    assert not e.running
    assert e.stop()


def test_stop_does_not_allow_restart_over_existing_worker():
    e=engine();entered=threading.Event();release=threading.Event()
    def loop():entered.set();release.wait(2)
    e.background_loop=loop
    assert e.start();assert entered.wait(1)
    old=e.learning_thread
    try:
        assert not e.stop(join_timeout=.01)
        assert e.lifecycle_status()['state']=='stopping'
        assert ale_owns_research(e)
        assert not e.start()
        assert e.learning_thread is old
    finally:release.set();old.join(2)
    assert e.lifecycle_status()['state']=='idle'


def test_timed_out_step_is_observed_and_blocks_other_steps_and_restarts():
    e=engine();release=threading.Event();called=[]
    try:
        result=e._run_step_with_timeout('slow',lambda:release.wait(2),timeout=.01)
        assert 'timed out' in result
        assert e.lifecycle_status()['unfinished_steps']==['slow']
        assert not e.stop(join_timeout=0)
        assert not e.start()
        assert 'deferred' in e._run_step_with_timeout('next',lambda:called.append(True))
        assert called==[]
        assert ale_owns_research(e)
    finally:
        with e._lifecycle_lock:futures=list(e._step_futures)
        release.set()
        for f in futures:f.result(timeout=2)
    assert e.stop()
    assert not ale_owns_research(e)


def test_unexpected_exit_reports_failure_and_can_restart():
    e=engine()
    def crash():raise RuntimeError('test failure')
    e.background_loop=crash
    assert e.start();e.learning_thread.join(2)
    assert e.lifecycle_status()['state']=='failed'
    assert e.lifecycle_status()['last_worker_error']=='RuntimeError'
    assert not e.running
    e.background_loop=lambda:None
    assert e.start();e.learning_thread.join(2)
    assert e.lifecycle_status()['state']=='idle'


def test_ownership_is_compatible_with_legacy_engine():
    assert not ale_owns_research(None)
    assert ale_owns_research(SimpleNamespace(running=True))
    assert not ale_owns_research(SimpleNamespace(running=False))


def test_timed_out_worker_keeps_shared_ownership_until_actual_completion(monkeypatch):
    from contextlib import contextmanager
    e=engine();release=threading.Event();entered=threading.Event();exited=threading.Event()
    @contextmanager
    def lease(owner):
        assert owner=='autonomous_step';entered.set()
        try:yield
        finally:exited.set()
    monkeypatch.setattr('modules.task_admission.admitted',lease)
    try:
        assert 'timed out' in e._run_step_with_timeout('slow',lambda:release.wait(2),timeout=.02)
        assert entered.is_set() and not exited.is_set()
    finally:
        with e._lifecycle_lock:futures=list(e._step_futures)
        release.set()
        for future in futures:future.result(timeout=2)
    assert exited.is_set()


def test_local_profile_has_finite_default_and_bypasses_legacy_cycle(monkeypatch):
    e=engine();e._cycle_count=0
    monkeypatch.setenv('NIBLIT_ALE_LOCAL_SAFE','1')
    called=[]
    monkeypatch.setattr('modules.native_evidence_learning.run_cycle',lambda *a,**k:called.append(True) or {'state':'knowledge_gap'})
    assert e._run_autonomous_cycle()=='knowledge_gap'
    assert called==[True]
    e.background_loop=lambda:None
    assert e.start();e.learning_thread.join(2)
    assert e._max_cycles==3


def test_active_user_defers_native_background_cycles():
    e=engine();e.running=True;e.startup_delay=0;e.poll_interval=1
    e.is_idle=lambda:False
    calls=[];e._run_autonomous_cycle=lambda:calls.append(True)
    def stop_wait(seconds):e.running=False
    e._interruptible_sleep=stop_wait
    e.background_loop()
    assert calls==[]


def test_both_real_core_research_loops_yield_to_ale(monkeypatch):
    import ast,asyncio,logging
    from pathlib import Path
    tree=ast.parse((Path(__file__).parents[1]/'niblit_core.py').read_text(encoding='utf-8'))
    core=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NiblitCore')
    methods=[n for n in core.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('_auto_research_loop','_async_auto_research_loop')]
    namespace={'asyncio':asyncio,'log':logging.getLogger('test')}
    exec(compile(ast.Module(body=methods,type_ignores=[]),'real_core_research_methods','exec'),namespace)
    class NeverRead:
        def get_learning_queue(self):raise AssertionError('overlapping research')
    for name in ('_auto_research_loop','_async_auto_research_loop'):
        obj=SimpleNamespace(running=True,_shutdown_event=threading.Event(),db=NeverRead(),researcher=object(),autonomous_engine=SimpleNamespace(running=True))
        obj._sleep_with_shutdown=lambda seconds:False
        if name.startswith('_async'):
            async def sleep(seconds):obj.running=False
            monkeypatch.setattr(asyncio,'sleep',sleep)
            asyncio.run(namespace[name](obj))
        else:
            namespace[name](obj)
