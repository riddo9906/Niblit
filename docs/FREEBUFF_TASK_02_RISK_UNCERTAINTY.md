# Freebuff Task 02 — Risk uncertainty and truthful market cognition

## Assignment and ownership
This task is addressed to Freebuff. Work only in the isolated risk-state section of `modules/adaptive_market_cognition.py`, with dedicated tests, and update this handoff. **Do not edit** `modules/strategy_manager.py`, `modules/market_thesis.py`, `modules/core_trading_sessions.py`, or any release/build/MT5/Freqtrade files. The main ChatGPT/Desktop Commander session is independently validating these integrations.

Current desktop source status: the earlier Freebuff change is present but uncommitted. Preserve all changes, existing tests, configurations, runtime files, git history, and active broker positions. r11 is the running demo executable, not a target for this task.

## Goal
Fix the known inconsistency where missing volatility data becomes `volatility_regime='unknown'` but `risk_state['volatility_state']='low'` because `_risk_state` and `_calculate_risk` clamp absent inputs to zero. Distinguish **unknown risk evidence** from **measured low risk** without silently replacing the numerical contract used by memory, retrieval, and downstream consumers.

## Required investigation
1. Read `docs/FREEBUFF_CAPABILITY_EVALUATION_20261121.md`, `modules/adaptive_market_cognition.py`, relevant consumer tests, and current git status/diff.
2. Reproduce the contradiction in a focused failing test before editing.
3. Trace all callers/consumers of `_risk_state`, `_calculate_risk`, risk score, risk labels, Qdrant/KnowledgeDB persistence and retrieval. State how missing versus zero is encoded. Check missing, None, bool, invalid strings, and NaN/infinity where relevant. Explicit measured zero must remain `low`.
4. Make the smallest safe code change that preserves public numerical output types unless justified by test-backed migration. If evidence is missing, labels must not falsely say `low`. Consider how score uncertainty is represented and whether confidence should be withheld; do not fabricate an uncertainty score or probability.
5. Add regression tests for missing data, explicit zeros, high/medium readings, partial evidence, invalid numeric values, retrieval and stable data serialization. No live broker, Qdrant mutation or installation configuration changes.
6. Run focused tests using `--basetemp` in an authorized isolated workspace-local path (never indiscriminately remove existing pytest dirs). Report command, pass/fail count and exit code. Never falsely claim full-suite success.
7. Write a separate report `docs/FREEBUFF_TASK_02_RESULT.md` with the precise diff, compatibility analysis, limitations, and remaining questions.

## Coordination protocol
This markdown is a shared on-disk task inbox. When starting, create `docs/FREEBUFF_TASK_02_STATUS.md` with status `IN_PROGRESS` and what you own. On completion write `COMPLETED`, tested commands/results, and modified file list. Do not change the ChatGPT integration files. The main session can inspect those files through Desktop Commander. This is file-based collaboration, not a live agent messaging API.

## Safety
No order submission, broker interaction, runtime launch or restart, admin/user credential access, tree resets/clean/stash, broad staging, or changes to security/governance. Do not declare an r11 deployment change or live performance impact from this isolated source fix.
