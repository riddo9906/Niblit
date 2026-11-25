# Niblit R14 Market Desk modernization and demo activation — 22 November 2026

## Outcome
The existing live Market Desk at http://127.0.0.1:5202/market-desk/ has a hybrid dark-AIOS/fintech styling upgrade. This is a web-asset update to the current R14 mobile-integrated packaged release; no Niblit Core executable was rebuilt or replaced during this intervention.

### Verified blocking causes before the changes
- The UI was displaying BTCUSDm while the deployed release's explicit `NIBLIT_MT5_EXECUTION_SYMBOLS` permitted only `ETHUSDm`. BTC readiness included `instrument_scope`.
- ETHUSDm readiness initially failed with `risk_preflight: Account exposure or pending-order capacity reached` because BTCUSDm already occupied the account's sole configured position slot. A fresh ETH review with `max_positions=2` and otherwise unchanged scoped cash/margin/volume limits returned `activation_eligible=true`.
- No funded execution capability: `funded_execution_available=false`.

### Implemented UI
- Top navigation rail and modern R14 overview with live Core, account mode, active session count and execution instrument.
- Three-step Configure → Review → Activate workflow and separate explanation of observation versus demo execution.
- More readable broker blockers, with expandable raw readiness JSON so no evidence is discarded.
- Default reviewed execution instrument ETHUSDm; 60-minute session, 0.10-lot maximum and 2-position limit; unchanged risk_cash=25 and risk_fraction=0.0025. The MT5 symbol selector remains independent for viewing BTCUSDm.
- Compact session/observer details in expandable disclosures, refined cards/typography/spacing, improved keyboard focus and mobile responsiveness.
- Removed the stale r9.1 wording from R14's displayed execution status.
- Preserved the existing MT5 broker chart, account record, position ledger, alerts, strategies and historical evidence.
- Remote-observation CSS selectors adjusted for the new layout wrapper.

### Source assets
`C:\Users\Riyaad\Documents\GitHub\Niblit\assets\trading-desk\index.html`
`C:\Users\Riyaad\Documents\GitHub\Niblit\assets\trading-desk\desk.css`
`C:\Users\Riyaad\Documents\GitHub\Niblit\assets\trading-desk\sessions.js`
Modern authored CSS and JS are also separately retained as `desk-modern.css` and `desk-modern.js` in source. Because this frozen Core exposes a fixed asset URL set, those contents are appended into the existing recognized `desk.css` and `sessions.js`; the page only references the recognized URLs.

### Packaged assets
`D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\assets\trading-desk\`
Original packaged HTML/CSS/JS backed up to:
`D:\NiblitAIOS\diagnostics\market-desk-r14-modern-20261122\`
Source copies of the original index/CSS/JS have suffix `.r14-modern-20261122.bak`.
Core executable SHA-256 remains unchanged at `48632d5c8e9ed7fe5ea7cfc4a5ff9f2bbe1d6f5217a58db712151222fd09300e`.

### Validation
- `scripts\verify_r14_modern_market_desk.py`: PASS; all required ids are unique and present, source/package HTML/CSS/JS byte-for-byte equal, default fields verified, `node --check sessions.js` passes, and the live Core returns HTTP 200 with the updated modern assets.
- Live R14 `/api/trading/sessions/readiness`: ETHUSDm (0.10 maximum lots, 2 positions, 3 entries, 60 minutes, $25 maximum risk) returned eligible=true; no broker order from review/proposal calls.
- The normal Core propose/activate API created session `298eaa4afdab417da31dc95abe0c75f7` and verified canonical state `active` through the Core ledger, with 3600-second duration and expiry **2026-11-22 11:19:48 SAST**.
- Follow-up at 10:21 SAST: 1 of 3 entries used, one ETHUSDm order record `open`; six-stage historical strategy observation still running.
- Independent read-only native MetaTrader5 probe: demo=True, connected=True; BTCUSDm ticket `591704289` volume 0.01 and ETHUSDm ticket `592462931` volume 0.10 were broker-open; both have native SL and TP. No pending broker orders.
- Core, Android gateway and Client Portal remained HTTP 200 on 5202, 8214 and 8768. Original BTC trade was not adopted or modified by this UI update.

### Operational note
The existing browser tab may cache prior assets: hard-refresh with Ctrl+Shift+R to get the modern UI. Do not use the BTC chart selector as a substitute for the explicit execution symbol; R14 demo sessions currently authorize ETHUSDm only. Session expiry ends new entries but does not necessarily close remaining broker-open positions.
