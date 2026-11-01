import threading

from modules.slsa_generator import SLSAGenerator, start_slsa


def test_start_is_idempotent_and_stop_interrupts_sleep(monkeypatch):
    engine = SLSAGenerator(db=object(), topics=['offline-test'], interval=3600)
    reached = threading.Event()
    monkeypatch.setattr(engine, 'generate_cycle', lambda topic: reached.set())
    thread = engine.start()
    try:
        assert reached.wait(2)
        assert engine.start() is thread
    finally:
        engine.stop(timeout=2)
    assert not thread.is_alive()


def test_generator_can_restart_after_stop(monkeypatch):
    engine = SLSAGenerator(db=object(), topics=['offline-test'], interval=3600)
    monkeypatch.setattr(engine, 'generate_cycle', lambda topic: None)
    first = engine.start()
    engine.stop(timeout=2)
    second = engine.start()
    try:
        assert second is not first
        assert second.is_alive()
    finally:
        engine.stop(timeout=2)
    assert not second.is_alive()


def test_convenience_launcher_uses_managed_thread(monkeypatch):
    monkeypatch.setattr(SLSAGenerator, 'generate_cycle', lambda self, topic: None)
    engine, thread = start_slsa(db=object(), topics=['offline-test'], interval=3600)
    try:
        assert engine.start() is thread
    finally:
        engine.stop(timeout=2)
    assert not thread.is_alive()
