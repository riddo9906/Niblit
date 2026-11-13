import pytest
from aios_scheduler import AIOSScheduler

def scheduler(monkeypatch, **kwargs):
    import aios_scheduler
    monkeypatch.setattr(aios_scheduler, "_LC_AVAILABLE", False)
    return AIOSScheduler(**kwargs)

def test_backpressure_preserves_interactive_capacity(monkeypatch):
    s=scheduler(monkeypatch,max_pending=3,reserve_interactive=1)
    s.submit(lambda:None)
    s.submit(lambda:None)
    with pytest.raises(RuntimeError):s.submit(lambda:None)
    s.submit(lambda:None,priority=1)
    with pytest.raises(RuntimeError):s.submit(lambda:None,priority=1)
    assert s.status()["pending_tasks"]==3
    assert s.status()["rejected_tasks"]==2

def test_pressure_defers_background_and_resumes_without_reordering(monkeypatch):
    available=[1000]
    s=scheduler(monkeypatch,resource_provider=lambda:available[0])
    s.resource_admission=True
    background=s.submit(lambda: "background")
    interactive=s.submit(lambda: "interactive",priority=1)
    task=s._pop_ready_task()
    assert task.task_id==interactive
    assert not s.cancel(interactive)
    s._execute(task)
    assert s._pop_ready_task() is None
    available[0]=3000
    task=s._pop_ready_task()
    assert task.task_id==background
    s._execute(task)
    assert s.status()["pending_tasks"]==0

def test_cancel_pending_releases_budget_and_invalid_delay_is_rejected(monkeypatch):
    s=scheduler(monkeypatch,max_pending=2,reserve_interactive=0)
    ident=s.submit(lambda:None)
    assert s.cancel(ident)
    s.submit(lambda:None)
    s.submit(lambda:None)
    with pytest.raises(ValueError):s.submit(lambda:None,delay_secs=float("nan"))
