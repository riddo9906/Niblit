import pytest
from modules.task_admission import TaskAuthority,AdmissionBusy,AdmissionUncertain
from test_memory_laboratory_gateway import Backend,gateway


def test_foreground_gets_next_slot_without_interrupting_active_work(tmp_path):
    g=gateway(tmp_path,Backend());authority=TaskAuthority(g)
    background=authority.acquire('core_inference')
    waiting=authority.acquire('niblit_chat',request_id='a'*32)
    assert waiting['waiting'] and 'token' not in waiting
    assert authority.status()['owner']=='core_inference'
    authority.finish(background['token'])
    assert authority.status()['queued']
    with pytest.raises(AdmissionBusy):authority.acquire('local_tutor')
    chat=authority.acquire('niblit_chat',request_id='a'*32)
    assert authority.status()['owner']=='niblit_chat'
    authority.finish(chat['token'])
    assert not authority.status()['queued']
    next_task=authority.acquire('local_tutor');authority.finish(next_task['token'])


def test_one_bounded_waiter_and_restart_preserves_no_generation_authority(tmp_path):
    g=gateway(tmp_path,Backend());authority=TaskAuthority(g)
    active=authority.acquire('core_inference')
    authority.acquire('niblit_chat',request_id='a'*32)
    with pytest.raises(AdmissionBusy):authority.acquire('niblit_chat',request_id='b'*32)
    restored=TaskAuthority(g)
    assert restored.status()['owner']=='core_inference'
    with g.db() as db:assert db.execute('SELECT count(*) FROM inference_foreground_wait').fetchone()[0]==1
    restored.finish(active['token'])
    # Restart does not execute anything: the live caller must acquire its lease.
    assert restored.status()['state']=='idle' and restored.status()['queued']


def test_waiter_expiry_never_expires_an_active_or_quarantined_lease(tmp_path):
    g=gateway(tmp_path,Backend());authority=TaskAuthority(g)
    active=authority.acquire('core_inference')
    authority.acquire('niblit_chat',request_id='a'*32)
    with g.db() as db:db.execute('UPDATE inference_foreground_wait SET expires=0')
    with pytest.raises(AdmissionBusy):authority.acquire('local_tutor')
    assert authority.status()['owner']=='core_inference'
    authority.finish(active['token'],uncertain=True)
    with pytest.raises(AdmissionUncertain):authority.acquire('niblit_chat',request_id='b'*32)
    assert authority.status()['state']=='quarantined'


def test_invalid_interactive_identity_cannot_reserve_a_slot(tmp_path):
    g=gateway(tmp_path,Backend());authority=TaskAuthority(g)
    with pytest.raises(ValueError):authority.acquire('niblit_chat',request_id='bad')
    assert authority.status()['state']=='idle' and not authority.status()['queued']
