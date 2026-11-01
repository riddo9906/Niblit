"""Pure ownership checks shared by Core's sync/async research workers.

Observing state must not initialize a subsystem, query a model or count unrelated
research as an ALE cycle. Unfinished provider calls retain research ownership.
"""


def ale_owns_research(engine):
    if engine is None:
        return False
    lifecycle = getattr(engine, 'lifecycle_status', None)
    if callable(lifecycle):
        state = lifecycle()
        if isinstance(state, dict):
            return bool(state.get('worker_alive') or state.get('unfinished_steps'))
    return bool(getattr(engine, 'running', False))
