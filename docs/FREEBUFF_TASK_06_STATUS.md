# Freebuff Task 06 — Status

DQI scoring stabilization and evidence calibration.

Repository: `C:\Users\Riyaad\Documents\GitHub\Niblit`
Branch: `fix/exness-demo-readiness-20261118`, HEAD `301571f0` (unchanged)
Worktree: dirty (concurrent r12 / trading-desk work in ~30 tracked files and many untracked
pytest temp dirs). Nothing was reset, stashed, cleaned, checked out or reverted.

## Scoped files

| File | State | Change |
| --- | --- | --- |
| `modules/adaptive_market_cognition.py` | modified (was already modified by Tasks 01–05) | reflection-length terms replaced with labelled-evidence scoring; policy `evidence-aware-v2`; policy-aware snapshot/status/persistence; `dqi_components` breakdown |
| `tests/test_adaptive_market_cognition_dqi.py` | new (349 lines) | 15 Task 06 regression tests |
| `tests/test_adaptive_market_cognition_quality.py` | untracked, edited | `_documented_dqi` now reads the structural reasoning term instead of `words / 40` (the risk-term assertions are unchanged and still strict) |
| `tests/test_adaptive_market_cognition_evidence.py` | untracked, edited | three assertions compare against `AdaptiveMarketCognitionLayer._DQI_POLICY` instead of the literal `evidence-aware-v1`/`-v2` |
| `tests/test_market_memory_quality_governance_r12.py` | untracked, edited | one assertion compares against `_DQI_POLICY` instead of the literal policy string; governance behaviour itself untouched |
| `docs/FREEBUFF_TASK_06_STATUS.md` | new | this file |
| `docs/FREEBUFF_TASK_06_RESULT.md` | new | findings, measurements, handoff |

Not touched: `modules/position_exit_policy.py`, `modules/adaptive_retrieval_cognition.py`,
`modules/desktop_runtime_shell.py`, `server.py`, MT5/Freqtrade configuration, release
manifests, execution permissions, trading engines. No process was started or stopped, no
order created, no build produced, no commit or push made.

`git diff --numstat modules/adaptive_market_cognition.py` = **651 insertions / 63 deletions**
(cumulative for Tasks 01–06; Task 05 ended at 380/55, so Task 06 contributes ~271/8).
All four cognition test files remain untracked (`??`), as they were before this task.

## Commands and exact results

Workspace-local basetemp: `Niblit/.pytest-task06/tmp` (created before the runs; pytest
refuses a non-existent `--basetemp` path on this host).

1. Cognition + governance set (62 tests, exit 0):

```
python -m pytest tests/test_adaptive_market_cognition_dqi.py \
  tests/test_adaptive_market_cognition_evidence.py \
  tests/test_adaptive_market_cognition_quality.py \
  tests/test_adaptive_market_cognition.py \
  tests/test_adaptive_market_cognition_risk.py \
  tests/test_market_memory_quality_governance_r12.py \
  --basetemp=.pytest-task06/tmp -q
# ..............................................................  [100%]
# 62 passed
```

2. Integration set (75 tests, exit 0) — market pipeline, event forwarding, runtime
   observation, unified memory reliability, desktop model chat, learning approval,
   r12 memory projection, stream responsiveness:

```
python -m pytest tests/test_core_market_pipeline.py tests/test_phase5v_event_forwarding.py \
  tests/test_runtime_observation_is_readonly.py tests/test_unified_memory_reliability.py \
  tests/test_desktop_model_chat.py tests/test_learning_approval.py \
  tests/test_market_memory_quality_governance_r12.py tests/test_memory_projection_budget_r12.py \
  tests/test_runtime_stream_responsiveness.py \
  --deselect "tests/test_runtime_stream_responsiveness.py::test_websocket_snapshot_runs_off_the_request_loop[server]" \
  --basetemp=.pytest-task06/tmp -q
# 75 passed
```

3. The deselected test fails for a reason outside this task:

```
test_runtime_stream_responsiveness.py::test_websocket_snapshot_runs_off_the_request_loop[server]
server.py:2747: in ws_runtime
    supplied=websocket.query_params.get('desktop_instance')
E   AttributeError: 'Socket' object has no attribute 'query_params'
```

`server.py` is dirty from concurrent trading-desk work and was **not** modified by Task 06.
The failure is a websocket-API mismatch in the runtime endpoint, not a cognition/DQI
assertion; it is reported as a deviation rather than worked around.

4. Scoring probe (temporary test file, deleted after the numbers were captured). It pinned
   `confidence=0.5` so only the reflection term and risk credit could move:

```
missing:  words=39 v1=0.4615 v2=0.4650 delta=+0.0035 reasoning=1.0 risk_credit=0.0
partial:  words=39 v1=0.5007 v2=0.5042 delta=+0.0035 reasoning=1.0 risk_credit=0.0392
complete: words=39 v1=0.6015 v2=0.6050 delta=+0.0035 reasoning=1.0 risk_credit=0.14
base(partial 0.4):    words=39 dqi=0.4885
verbose same facts:   words=74 dqi=0.4885
doubled reflection:   words=78 dqi=0.4885
96-word evidence-free: words=96 dqi=0.3485
fabricated prediction:          dqi=0.4652
```

No Qdrant, MT5 or Freqtrade connection was used; persistence was exercised only through the
existing fake `write_memory` cluster used by the regression tests.

## Deliberate omissions

- `modules/adaptive_retrieval_cognition.py:303` still scores its own index with
  `min(1, len(reflection.split()) / 50)`. It belongs to a different layer (retrieval
  cognition, weight 0.12 of another composite) and is outside the Task 06 file scope.
  Documented as a remaining issue instead of being edited.
- `modules/desktop_runtime_shell.py:878/886/898` still prints bare `risk=` / `dqi=` values
  from the last bundle. Display-only, unchanged.
- Historical Qdrant records are neither read nor rescored; only the in-memory snapshot
  filters by policy.
