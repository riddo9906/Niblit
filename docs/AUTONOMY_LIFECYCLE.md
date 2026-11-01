# Learning worker ownership and stop semantics

Source repair: 29 October 2026. This is not yet packaged into the frozen desktop
release. Core port 5000 was unavailable during this continuation; no live desktop
cycle was started, and no paid inference or trading setting was enabled.

## Why memory can change while ALE reports stopped

`niblit_core.py` deliberately initializes `autonomous_engine` loaded but idle.
Its `running` flag describes the ALE background worker, not every research
producer in Niblit. Core's sync/async research loops, curriculum jobs, SLSA and
kernel research paths are separate callers. In particular, SLSA and the kernel
can call `PhasedResearchEngine.research` without an ALE background cycle; that
engine can write `ale_phase2_research` records. The key prefix alone does not
identify the worker that initiated a request.

This explains why the previous two observations are not proof that one flag is
wrong. A full producer/activity ledger remains necessary to reconcile individual
historical records. No unobserved runtime producer is claimed as the definitive
cause of a particular old record.

## Concrete source corrections

- Core's sync research loop already yielded while ALE's running flag was true;
  the async equivalent did not. Both now use one ownership check, including a
  worker stopping or a timed-out provider step that is still alive.
- ALE start/stop now share a lock. A stopped flag cannot permit a second worker
  while the previous worker remains alive.
- Worker exit always clears the running flag, with an error type on unexpected
  failure. Status distinguishes idle, running, stopping and failed.
- `stop()` requests cancellation and waits at most ten seconds. It only returns
  success when the worker and tracked step calls have actually finished. The
  UI/command text no longer claims completion while calls remain active.
- A thread-pool timeout does not terminate its Python operation. Such futures
  are now tracked; later steps/cycles defer, and restart is rejected until they
  finish. The old claim that these were disposable daemon tasks was removed.
- `get_learning_stats()` observes already-wired components rather than invoking
  lazy agent constructors. Reading status must not manufacture availability.
- `start(max_cycles=N)` optionally limits the number of iterations. It does not
  impose a hard provider deadline, authorize external actions or change budgets.

## Verification

The focused lifecycle/status regressions cover one finite owned iteration,
unexpected worker failure and restart, stop while work remains alive, timeout
tracking, prevention of overlapping steps/restarts, and both actual Core research
method bodies yielding to ALE. A status test rejects lazy research-agent creation.

The worker tests use deterministic local callables and the Core-method test
extracts the real method bodies with AST to avoid booting the entire application.
They do not prove a full research→memory→evaluation cycle or model improvement.
Source syntax parsing also covers Core, Router, Server and the changed modules.

Still required: process-wide leases across other research producers, domain
evaluations, evidence-linked cycle receipts, sustained restart/recovery acceptance,
and a rebuilt desktop verification. A provider operation that never returns may
require process isolation; Python threads cannot provide forcible cancellation.
