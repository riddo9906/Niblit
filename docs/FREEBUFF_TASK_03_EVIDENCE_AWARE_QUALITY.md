# Freebuff Task 03 — Evidence-aware DQI and prediction usefulness

**Owner:** Freebuff (isolated source/testing assignment)  
**Budget:** MAXIMUM 90 minutes of your remaining daily quota. Stop immediately at this limit; provide a partial handoff rather than extending.  
**Status:** READY_FOR_FREEBUFF (not yet started by Freebuff).  
**Coordination:** ChatGPT/Desktop Commander handles integration, Qdrant, release testing and broker-side tracing.

## Context (read first)
Read `docs/FREEBUFF_TASK_02_RESULT.md`, `docs/FREEBUFF_TASK_02_STATUS.md`, `modules/adaptive_market_cognition.py`, and `tests/test_adaptive_market_cognition_risk.py`. Preserve Task 01 and 02 fixes. The current working tree is dirty and the r11 demo engine is running. Do not reset, clean, stash, checkout, stage broadly, or deploy.

## One scoped problem
The module now labels missing/partial/complete risk evidence correctly. Yet:
- `_compute_dqi` uses `risk_awareness=1-risk_score`; with `risk_score=0.0` and `risk_evidence.state=missing`, it assigns the full 0.14 quality credit to an unmeasured state.
- `_finalize_experience` uses `prediction_usefulness=max(0,1-regime_uncertainty)`; when regime uncertainty is not measured, this reports 1.0.
- `_dqi_history` also reports `risk_awareness=1-risk_score`, potentially contradicting a corrected DQI. Distinguish measurements from numerical fallback.

## Deliverable and constraints
1. Trace consumers of `dqi_score`, `_dqi_history`, `meta evaluation prediction_usefulness`, `risk_evidence`, `risk_score`, and `regime_uncertainty` within current repository. Record compatibility implications and possible scoring-version migration. Propose a precise numerical policy: missing evidence gets no fabricated *safety credit*; partial evidence should not be equated with complete evidence; complete measured records must retain documented baseline scores when possible. Avoid calling DQI a calibrated prediction.
2. Write failing focused tests **before any production edit**. Include: no measurements, measured zero, partial evidence, complete inputs, non-finite values, DQI telemetry consistency, and JSON serialization. If a policy choice materially affects existing score rankings, describe it rather than guessing silently.
3. Implement **only if backward-compatibility is defensible**. Keep edits to `modules/adaptive_market_cognition.py` plus a new focused test file (e.g. `tests/test_adaptive_market_cognition_quality.py`). Do not change `strategy_manager.py`, `market_thesis.py`, `core_trading_sessions.py`, runtime configuration, other code, deployed release or broker. If an explicit version migration is needed, document design and stop instead of speculative refactoring.
4. Run focused tests for Task 01, Task 02, Task 03 and key existing consumers. Use a fresh dedicated `--basetemp` directory; avoid wiping previously created temp directories. Record exact pass/fail and process exit code.
5. Update `docs/FREEBUFF_TASK_03_STATUS.md` and write `docs/FREEBUFF_TASK_03_RESULT.md` with tested policy, before/after numerical examples, failures/limitations, exact changed files, and handoff. Be explicit that source code is NOT deployed or live-tested.

## Safety and stop conditions
- Maximum 90 min Freebuff usage: prioritize understanding, failing-test reproduction, minimal patch, focused tests, documentation. Stop early when done; no full-suite run.
- Never access credentials, broker APIs, running r11 session, or protected D: config/runtime. No trade, order, live configuration, build, restart, Git reset/clean/stash/commit/push.
- Do not fabricate performance improvements or suggest changes to execution policy based on quality metrics.
- If another agent edits the same file or worktree changes mid-task, stop and report the conflict before overwriting.
- Shared-file handoff is the only verified agent-to-agent channel; write results into docs, not into live runtime.
