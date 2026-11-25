# R13 activation record — 2026-11-21

R13 was activated as an isolated, observation-only Core on 127.0.0.1:5201.

## Verified running processes
- R12: PID 9040, port 5200, source candidate build-20261121-r12-memory-governed, retained as current demo-trading owner.
- R13: PID 7416, port 5201, source candidate build-20261121-r13-exit-dqi, running as a separate headless service.
- MT5 terminal PID 19080 remained running. Native demo readback before activation showed an existing BTCUSDm position ticket 591704289 (0.01 lot), with a separate historical EURUSD 'unknown' Core record. No orders or stops were changed.

## R13 runtime profile
- Configuration: D:\NiblitAIOS\config\r13-observe-20261121\r13-observe.env
- Bound manifest: D:\NiblitAIOS\config\r13-observe-20261121\installation-r13-observe.json
- Installation ID: r13-observe-20261121
- Manifest SHA-256 pin was verified.
- Separate runtime state: D:\NiblitAIOS\data\r13-observe-20261121
- R13 memory and ledger were copied from existing sources into isolated files (not shared for writes). Existing source memory/ledger were not changed by the copy.
- Trading disabled: NIBLIT_TRADING_ENABLED=false, NIBLIT_TRADING_ALLOW_EXECUTION=false, NIBLIT_FREQTRADE_ALLOW_EXECUTION=false, both native demo deliveries disabled, no Core-trading observers configured. Local UI autostart and packaged Cloud management disabled to avoid colliding with r12 services.
- Original r13 release binding is backed up as release-runtime-original-r13.json in the candidate directory.

## HTTP checks
- R13 port 5201: /health=200, /api/boot=200 (ready=true), /market-desk/=200, /v1/inference/health=200, /api/status=200, /api/runtime/state=200.
- R13 /api/trading/software-readiness=503, /api/trading/sessions=503 and /api/trading/positions=503 because the observation-only trading stack is not initialized. **No trading acceptance is claimed.**
- R12 port 5200: /health=200, /api/boot=200 (ready=true), /market-desk/=200, /v1/inference/health=200, /api/trading/software-readiness=200 (execution_authorized=false).

## Activation decision
**R13 is actively serving the new Core on port 5201 for read-only/AI/UI evaluation. It is NOT the primary trading runtime or live-money enabled.**
Do not terminate R12 during its existing open demo position without broker-native reconciliation and verified ownership handover. R11 and R12 candidate files remain preserved.

Access the r13 Market Desk at http://127.0.0.1:5201/market-desk/ .
