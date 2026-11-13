# Phase 6 continuation acceptance — November 13, 2026

## Result and release

The actual November 8 packaged release at `C:\Users\Riyaad\Documents\GitHub\Niblit\dist\releases\build-2026-11-08T08-51-03-322Z-4395fdf0\niblit` was updated through isolated build, tests, checksummed rollback and stopped-process cutovers. Final version: `nov8+phase6-prediction-chat-20261113-r4`. Final Core PID: 11868. Its API ownership is verified; development Core was not substituted. This is the next working vertical slice, not completion of every Phase 6 capability. The newly supplied master addendum has not been started.

## Implemented and runtime-verified

Niblit is selectable in the existing Tauri model selector. Niblit mode routes through Core's existing ChatDetector, bounded persistent chat context, scoped hybrid memory, optional read-only current market evidence, shared admission and the already-running authenticated native Qwen 2.5 Coder 3B service. Existing exact commands retain CommandRegistry/governance. No model-generated tool or broker call was introduced. Existing direct model choices and their Cloud/SSE path remain in the code; the Niblit route has no paid fallback or duplicate model process.

The reported busy failure was reproduced. Ordinary chat was competing with other `core_inference` work and was immediately rejected. A dedicated `niblit_chat` owner now reserves the next slot for at most 60 seconds while the current task finishes. One waiting request is allowed; new background work cannot overtake it. This expiry applies to a scheduling preference, never an active generation lease. Quarantined tasks remain protected. Actual acceptance observed the waiting request, rejected background reentry with 409, then returned a real machine-learning explanation with HTTP 200 in 29375 ms. No broker command was involved.

The UI no longer labels the selected native model as a fallback. A greeting reports memory as not needed, rather than unavailable. Built and test-verified; final manual label acceptance pending. Prior user feedback and the supplied app image establish that selection and a greeting worked before these label corrections; that earlier ordinary follow-up was blocked and was not counted as acceptance.

Live 5-, 15- and 30-minute forecasts consume closed desktop M5 candles and versioned evidence IDs. They are a transparent seven-close continuation baseline, not a trained advanced predictor. Predictions preserve account/terminal identity, horizon, creation/availability/expiry and evidence references. Current canonical ledger: 39 forecasts, 27 evaluated hypothetical outcomes. Actual evaluated horizons: [300, 900, 1800]. Net outcomes remain UNKNOWN because commission and slippage are not verified. Probabilities remain null. Repeated observations/restarts preserve deterministic IDs and do not replay execution.

## Statistical and replay evidence

The exploratory broker dataset contains 200 closed VPS candles captured before the account change. It is historical data, not current account state. Train labels are purged before each test prediction; the rule and dataset are versioned. Results for the unconditional regularized baseline:

| Horizon | Folds | OOS observations | Brier | 0.5 baseline Brier | Net result |
|---|---:|---:|---:|---:|---|
| 5 min | 15 | 148 | 0.2510 | 0.2500 | UNKNOWN |
| 15 min | 15 | 144 | 0.2496 | 0.2500 | UNKNOWN |
| 30 min | 14 | 138 | 0.2544 | 0.2500 | UNKNOWN |

These are research measurements, not promotion or profitability evidence. Overlapping/serial outcomes invalidate simple independence assumptions; displayed Wilson intervals are descriptive under that explicit assumption. Missing historical costs are not replaced with current spread or zero commission. Full train/validation/test model selection, realistic fills, margin/sizing/session simulation, calibration validation and drift-driven adaptation remain pending.

## Current broker topology and restrictions

Desktop MT5 is bound to Exness demo `486129611 / Exness-MT5Trial10`. The latest VPS readback verifies Exness demo on Exness-MT5Trial10, matching the configured desktop demo identity. Earlier in this session the VPS verified XM live; that observation is historical. The current XM profile is unverified while Exness occupies the shared terminal. The agent issued no account-switch operation. Both sources remain independently account/terminal-bound. XM funded observation remains read-only when verified. Latest captured remote demo positions: 0, pending orders: 0. Current balances must always come from fresh readback, not this report.

No demo session was reactivated. Funded submission, modification, cancellation and closure remain disabled. No broker test orders were placed. Existing circuit breakers and emergency-stop state were preserved; no reconciliation breaker was cleared. Six strategy implementations, vote counts and deterministic risk ceilings were not changed.

## Lifecycle investigation

PID-tagged JSONL events and per-process fault output were added. The user's normal window close produced exit code 0 and owned Core cleanup. A later controlled interrupt exposed an additional failure: the attached launcher blocked indefinitely in the UI child's wait, and handled the pending interrupt only after the window closed (return 130). The launcher now polls the owned child at 250 ms and observes Core shutdown events. Real-child tests cover normal/nonzero exit and shutdown without waiting for the child to exit naturally. Final packaged controlled recovery exited in 21.56 seconds without force or manual UI closure. Conversation acceptance ran immediately before that restart on the identical executable; post-restart ownership, predictions and disabled execution were rechecked. This establishes the controlled-shutdown defect; the original spontaneous application exit remains unexplained and is not claimed resolved. Automatic restart is not enabled and never restores trading authority.

## Conversation quality and limitations

The real initial prediction explanation loosely claimed authorization; the direct same-model baseline made a stronger unsupported trading-authorization claim. Neither is evidence of improved accuracy. The final deterministic validator flags authorization/action wording and appends a verified no-broker-authority correction; it is not a full fact checker and performs no extra LLM revision pass.

A measured greeting decreased from 15619 ms / 1345 prompt tokens to 7238 ms / 272 prompt tokens after skipping irrelevant retrieval. These are single observations with cache/load confounds, not a benchmark-wide claim. Source reports retain the raw local responses and model attribution.

The live machine-learning question also retrieved trading episodes among its top-k results; successful retrieval is not proof of semantic relevance. Task-aware relevance filtering/evaluation remains pending.

Existing independent embeddings use `intfloat/multilingual-e5-small`, pinned revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, compatible versioned collections and Cosine distance. Existing scoped lexical/dense/metadata/recency ranking was reused. Retrieval returned actual results with no reported issues. No incompatible re-embedding or collection replacement occurred. Graph-aware reasoning, full NUCM consolidation/temporal supersession, advanced semantic references, multi-conversation checkpoints, Niblit streaming and full backend cancellation remain pending. Heavy cognitive kernels are not invoked or falsely reported active on every message.

## Verification and preservation

Final Python suite: 384 passed, 0 failed/errors/skipped, including the original baseline. UI: 63 passed across 12 files. Additional focused suites overlap and must not be summed. All three offline checks passed on the final candidate: Phase 6 contract, release preflight and broker-double trading self-test. Frozen bytecode from nine changed modules matches final source. The incremental code builds reused the verified full dependency graph, with no new dependencies; build receipts and source checksums are retained.

Canonical SQLite backup: `C:\Users\Riyaad\Documents\Codex\2026-11-07\referenced-chatgpt-conversation-this-is-an-2\work\phase6-continuation\state-backup\canonical-before-shadow.sqlite3`, integrity `ok`, SHA-256 `0ab20cb37e714bed61125b85b2ea2aac50335edf4ab29cd19cfd13b81a4367e0`. Docker's supported restart timed out; the user approved a restricted forced Docker-process restart. Original mounts were unchanged and all five Qdrant collections recovered green. The user updated the source-restricted SSH rule after the approved public-IP check. Firewall and SSH host-key verification were not weakened. Models, databases, private configuration, repositories, volumes and persistent memory files were not deleted or relocated. Legacy memory JSON files accidentally included by the general build were explicitly excluded from cutover. No additional workspace cleanup was performed.

## Exact source changes

New: `modules/market_prediction.py`, `modules/runtime_lifecycle.py`, `tests/test_market_prediction.py`, `tests/test_niblit_conversation.py`, `tests/test_chat_admission_priority.py`.
Extended: `server.py`, `main.py`, `modules/niblit_ui_launcher.py`, `modules/task_admission.py`, `modules/memory_laboratory/web.py`, `modules/cognitive_observation_runtime.py`, `modules/desktop_market_intelligence.py`, `modules/phase6_preflight.py`, existing Market Desk HTML/JavaScript, `niblit-ui/src/pages/ChatPage.tsx`, `niblit-ui/src/services/niblitApi.ts`.
Packaged cutover changes only six code/UI files, listed with SHA-256 in `NIBLIT_PHASE6_CONTINUATION_MANIFEST.json`. Existing dirty worktrees/HEADs were preserved; no commit, reset, clean, stash or push was performed.

## Rollback and next work

Stop the exact updated Core/UI normally and verify inference idle and demo sessions inactive. Run `C:\Users\Riyaad\Documents\Codex\2026-11-07\referenced-chatgpt-conversation-this-is-an-2\work\phase6-continuation\release-update-final.py rollback` with the existing Niblit environment's Python. It verifies final file hashes and restores the original six preimages from `C:\Users\Riyaad\Documents\Codex\2026-11-07\referenced-chatgpt-conversation-this-is-an-2\work\phase6-continuation\rollback`. Preserve new observations and prediction tables: never restore an old database or trading authorization as part of code rollback. Restore code only; config and broker credentials are unchanged.

See `NIBLIT_PHASE6_CAPABILITY_MATRIX.md` for implemented/runtime-verified versus test-only/pending scope. Full Phase 6 remains incomplete. Next work should strengthen cancellation and conversation isolation, independently evaluate retrieval/response quality, resolve competing legacy inference callers and complete the remaining calibration/NUCM/MQL5/adaptation requirements before adding authority. The user's new master addendum remains queued separately.
