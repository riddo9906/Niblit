import threading

from modules.phased_research_engine import PhasedResearchEngine, research_checkpoint


def test_phase_deadline_cancels_and_joins_the_executor():
    entered = threading.Event()
    completed = threading.Event()

    def phase(_topic):
        entered.set()
        try:
            while True:
                research_checkpoint()
                completed.wait(.01)
        finally:
            completed.set()

    result = PhasedResearchEngine()._run_phase_with_timeout(2, "fixture", phase, .15)
    assert result.error
    assert entered.is_set() and completed.is_set()
    assert not any(t.name.startswith("NiblitResearchPhase") for t in threading.enumerate())


def test_owner_stop_joins_phase_without_waiting_for_research_deadline():
    cancel = threading.Event()
    entered = threading.Event()
    completed = threading.Event()

    def phase(_topic):
        entered.set()
        try:
            while True:
                research_checkpoint()
                completed.wait(.01)
        finally:
            completed.set()

    def request_stop():
        assert entered.wait(2)
        cancel.set()

    owner = threading.Thread(target=request_stop)
    owner.start()
    try:
        result = PhasedResearchEngine()._run_phase_with_timeout(
            2, "fixture", phase, 5, cancel_event=cancel
        )
    finally:
        owner.join(timeout=2)
    assert result.error and completed.is_set()
    assert result.duration_s < 2
