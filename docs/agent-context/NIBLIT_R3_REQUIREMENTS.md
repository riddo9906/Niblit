# Niblit v2.0.2-r3 implementation requirements — 4 November 2026

The user confirms that the connected MT5 and Freqtrade accounts are demo/dry-run accounts. This confirmation does not authorize an order or autonomous session. A specific account identity, adapter, symbol/strategy scope, risk limits and session duration must be approved before demo execution. Real-money submission remains disabled until a separate authorization and acceptance process.

Extend the existing Core-governed trading architecture in the current four repositories. Preserve dirty changes, services, positions, credentials, learning permissions and canonical memory. Do not replace the trading engine or introduce a competing execution authority.

## Required environments and adapters

Support simulation, live-market observation, autonomous demo/dry-run and future real-money operation through capability-driven adapter contracts. Retain MT5 and Freqtrade and allow additional adapters. Distinguish data provenance from account environment and execution permission. Detect provider account environment from authenticated provider state; unknown or changed identity fails closed. Separate credentials and permissions by environment without copying secrets into executables or reports.

## Required execution flow

Live quotes/candles/account state -> existing registered strategies -> complete consensus or explicit ABSTAIN -> account-aware risk/sizing -> Core authorization -> durable idempotent execution claim -> broker preflight -> final identity/permission/freshness check -> submission -> reconciliation -> continuous owned-position management -> realized outcomes and canonical audit/feedback.

Preserve AI Strategy Manager, comparer, quick trading, explainable evidence-backed signals, chart annotations, disabled-session observation and desktop alerts. Model explanations and notifications cannot authorize orders. Do not invent numerical confidence, price levels, fills or profitability.

## Required controls

- Account, adapter, environment, symbol, strategy/version and expiry bound authorization; restart never rearms a session.
- Broker precision/minimum/step, currency conversion, fees, leverage, margin, protective stops and risk-per-trade validation.
- Aggregate exposure, maximum positions, session/daily loss and drawdown controls using finite verified account values.
- Emergency stop prevents new submissions, persists across restart and leaves observation/reconciliation active. Any liquidation requires explicit scope; no arbitrary closure of pre-existing/manual positions.
- Durable account-scoped idempotency and reconciliation across timeout, partial fill, restart, cancellation and duplicate signals. An uncertain submission is never retried automatically.
- Continuous management only for proven owned positions under current authority; protective broker orders remain after session expiry.
- Complete audit of observations, votes, abstentions, risk denials, authorization references, requests, responses, reconciliation, exits and realized outcomes. Use the existing canonical memory/outbox; recorded feedback is not model-weight training.
- Delivery-aware desktop alerts with freshness, disagreement, blocked reason, duplicate suppression and safe navigation actions.
- Live-account capability detection and real-money policy contracts tested in simulation/test environments. Real-money submission remains unconditionally disabled for this release until separately authorized and reviewed.

## Acceptance and release

First use simulations and controlled broker doubles, then read-only probes against existing services. No real/demo order, account mutation, bot activation or position change during preparation. Test identity/environment changes, stale data, incomplete/disagreeing strategies, invalid numeric inputs, risk limits, expired/revoked scopes, emergency stop, concurrent duplicates, ambiguous fills, reconciliation and restart. Verify packaged UI -> Core -> Cloud/Lean -> canonical memory, alerts, boot/shutdown/restart and owned-child cleanup. Keep the complete one-folder release together.

Prioritize a working r3 executable. Label the release as a candidate until the full required flow is verified. Report each demo/live capability as implemented, verified (with exact scope), blocked, or pending; compilation, file presence and mocks are not actual broker-order acceptance.
