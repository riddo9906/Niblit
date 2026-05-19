import lifecycle_engine


def test_self_heal_phase_is_manual_only(monkeypatch):
    called = []

    monkeypatch.setattr(lifecycle_engine, "run_self_heal", lambda: called.append(True))

    engine = lifecycle_engine.LifecycleEngine()
    engine._execute_phase("SELF_HEAL")

    assert called == []
