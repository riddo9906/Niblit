# Core demo activation review UI — 2026-11-19

## User-visible problem

The Core-reported `activation_available: true` means a bounded demo session may be reviewed, **not** that an execution transport is ready or a safe activation already exists. The installed Core was observed with `delivery_authorized: false`, `remote_demo.configured: false`, a persisted emergency stop and one historical `mt5/EURUSD` entry in `unknown` state. Market Desk therefore kept the final activation control disabled.

## Change

- Market Desk exposes `exness_demo` in the Core-governed execution environment selector, using the matching remote demo symbol, lot ceiling, duration, entry limits and risk inputs. It does **not** reuse the local MT5 account or Freqtrade adapter for this selection.
- The legacy market snapshot script does not route `exness_demo` to the Freqtrade API or display local MT5/Freqtrade order controls.
- `execution_controls.recovery.activation_blockers` and `activation_ready` offer strictly read-only, advisory explanations of the missing demo transport, unresolved visible delivery claims, and latched stop. The emergency stop remains a separate, reviewable gate; status cannot reset it.
- Market Desk explains the selected adapter's transport readiness and each independent blocker in a dedicated visible status element. Existing readiness review, pending proposal, operator confirmation, Core rearm, remote demo identity checks, and Broker authorization remain unchanged.

## Guardrails

- No live money authorization, no speculative broker retry, no SQLite state edit, no emergency latch clearing, no private profile fabrication, and no VPS change.
- The unknown MT5 delivery requires broker-backed reconciliation. The Exness VPS profile remains absent and the version 0.2 VPS gateway has not been verified compatible with the modern desktop protocol.
- `activation_ready` is a diagnostic projection, not an approval, grant, or guarantee: the Core session owner still enforces the full final account-bound risk, delivery and stop controls.
