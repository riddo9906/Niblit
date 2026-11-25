# Codex handoff — R14 Task 02: Persistent Position Cognition

Read `docs/R14_ADAPTIVE_MARKET_COGNITION_BUILD_PROGRAM_20261122.md` and https://github.com/riddo9906/Niblit/issues/422 first.

Repo: `C:\Users\Riyaad\Documents\GitHub\Niblit`, branch `fix/exness-demo-readiness-20261118`, baseline HEAD `301571f0`. ~141 existing worktree changes at kickoff. Inspect HEAD, status and diffs before touching files. **Never reset/clean/stash/commit/push** and never overwrite concurrent agent edits.

Task 01 is already in source (95 focused tests passed): `modules/market_decision_trace.py`, `tests/test_market_decision_trace.py`, and narrow additions to `modules/core_trading_sessions.py`. The frozen R14 executable is unchanged.

**Exclusive ownership for this task:** create `modules/position_cognition_record.py`, `tests/test_position_cognition_record.py`, `docs/R14_TASK02_POSITION_COGNITION_EVIDENCE.md`. Do NOT modify `modules/core_trading_sessions.py` itself or the Freebuff regime files. Propose an exact narrow integration diff in your report.

Implement deterministic, persistent position evidence keyed by (venue/account/broker-position-id/Core-owned-order-id). Preserve entry strategy and trace ID, original entry thesis, executable bid/ask, stop/target, observed MFE/MAE, cost evidence, order/deal lifecycle and outcomes. Reconcile duplicate/out-of-order events, restarts, partial fills/closes and multiple tickets. Never conflate floating with realized P&L; missing broker costs stay unknown; no fabricated counterfactual outcomes. Legacy/manual positions stay observation-only, not adopted. No broker orders, no live mutations.

Test account isolation, crash/restart, stale quotes, altered SL/TP, partial exits, missing fees, delayed reconciliation, and evidence provenance. Run focused pytest and report exact pass counts, diff and limitations. Stop at review gate; the assistant will integrate after reviewing.
