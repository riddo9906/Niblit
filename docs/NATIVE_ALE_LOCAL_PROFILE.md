# Native ALE local-evidence profile

This is an opt-in source-runtime increment, not a rebuilt executable or full Core
boot acceptance. `deploy/runtime/native-local.env.example` records the settings;
the personal .env and configured OpenAI model were not overwritten.

## Ownership and lifecycle

ALE steps acquire shared admission INSIDE the worker thread. If the parent stops
waiting at its timeout, the worker retains task ownership until it really ends.
Subsequent steps and other participating processes cannot overlap it. An already
owned caller cannot spawn this asynchronous step and silently detach its lifetime.
Network-ambiguous failures quarantine the shared slot as documented separately.

The native background loop now yields while the user is active. Existing idle
threshold/pause/stop controls remain. Local-safe sessions default to three cycles
and accept only one to three; explicit model/cycle counts remain bounded.

## One local evidence cycle

With NIBLIT_ALE_LOCAL_SAFE=1 (also the default when shared admission is enabled),
the large legacy cycle is replaced by one local evidence study. It rotates runtime,
software and finance questions, retrieves up to three passages through the existing
authenticated memory gateway, asks the existing GGUF model once, checks citations,
and saves an unverified episodic observation or knowledge gap. It starts no second
Core, embedding model or generation worker.

The profile does not enter legacy web research, implementation, command execution,
evolve/deploy, GitHub publishing or weight-training phases. Missing explicit GGUF
configuration defers the cycle rather than falling back to Cloud/OpenAI. A stop
after inference prevents a new memory-write phase. Generated reflections are
excluded from evidence used to corroborate subsequent native studies.

This evaluates recall/citation behaviour; citations alone do not establish truth.
Saved observations remain confidence 0.2 and unverified. Source facts are not
overwritten, and code/strategy/risk settings are not changed by this learner.

## Remaining native boot work

Before starting anything, run from the repository root:

```powershell
./niblit-env/Scripts/python.exe scripts/check-native-runtime.py
```

This reads the bounded source-profile template over the existing environment for
the check only. It does not edit `.env` or configure an already-running Core.
It checks one idle local model slot and the existing authenticated memory/task
gateway. It generates no response, acquires no task, writes no memory and starts
no services or orders. Exit code 1 means dependencies are not ready; do not use
automatic retries to start competing workers. Readiness is a momentary observation,
not a guarantee against another task starting later; shared admission still applies.

On 31 October 2026 this check could not reach either dependency from the current
session. The earlier service inventory is historical until rechecked. Eleven focused
readiness/evidence/admission tests passed. Full Core startup remains unverified.

Trace the actual desktop startup configuration and remaining independent research,
curriculum/SLSA and legacy inference callers before enabling full Core. The profile
does not prove every producer participates. Cloud/tool-server delegation needs
one propagated task owner, not independent nested process reservations. Native UI
controls should show the selected profile and its real lifecycle status.

Keep paid loops and execution disarmed during boot acceptance. Then package and
verify the same source in a dated Windows release. Do not call the frozen build
updated merely because the source methods and local services were tested.
