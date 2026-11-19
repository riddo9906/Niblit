# Trading-model compatibility and funded-trading gates — 19 November 2026

Status: source audit and isolated regression tests. **No funded order authority is enabled by this document or the related code.** The local application and VPS must be deployed separately, with consistent permissions and independently verified broker identities.

## Existing execution architecture

The governed Core trading route is `modules/core_trading_sessions.py` → `modules/strategy_manager.py` → risk review → account-bound adapter → durable ticket ledger → final broker-identity and order guard. Remote demo uses a pinned, SSH-connected `RemoteDemoAdapter` and `deploy/vps-gateway/demo_execution.py`. Signals never independently constitute broker authority. Current source keeps funded execution disabled; the XM funded observer has a different persistent reconciliation breaker.

As of this patch, broker-double Exness/Core/demo-control/readiness suites pass in the user's isolated local test environment using `niblit-env` and a writable D: pytest basetemp. The live VPS, cost evidence, real order/deal reconciliation and newly packaged desktop build still need independent acceptance.

## Older environment variables

| Older setting | Assessment | Migration decision |
| --- | --- | --- |
| `TRADING_TFT_ENABLED` | Previously unused by current `modules/tft_forecast.py` (reads `NIBLIT_TFT_ENABLED`) | Compatible fallback added; modern variable has precedence. A disabled flag stays disabled. |
| `TRADING_TFT_HORIZON` | Current equivalent `NIBLIT_TFT_FORECAST_HORIZON` | Compatible fallback added; modern variable has precedence. |
| `TRADING_TFT_CHECKPOINT` | No current direct consumer found | Do not assume checkpoint load or train from scratch. Requires verified model version, input schema and out-of-sample acceptance. |
| `TRADING_KELLY_ENABLED`, `TRADING_KELLY_FRACTION` | No current direct consumers found; separate `TradingBrain` sizing exists | Leave inactive. A Kelly-derived size must be capped below Core's existing broker-verified limits, never grant orders. |
| `TRADING_MAX_DRAWDOWN_PCT=15.0` | No current direct consumer found | **Do not map to Core limits**. Existing governed session/daily/drawdown ceilings are much stricter; a legacy 15% switch must never relax them. |
| `NIBLIT_RL_ENABLED` | Used in `modules/trading_brain.py` | Keep disabled for live execution. Research-only evaluation can compare RL with the six-strategy consensus. |
| `TRADING_RL_LR`, `TRADING_RL_GAMMA`, `TRADING_RL_UPDATE_STEPS` | No current direct consumers found | Specify versioned training/evaluation configuration before introducing into a learned policy. |
| `AI_DEV_LAB_DB_PATH`, `FUSED_MEMORY_DB_PATH`, `ALE_CHECKPOINT_PATH`, `EVOLVED_DIR`, `NIBLIT_DB_PATH`, `NIBLIT_SQLITE_DB_PATH`, `NIBLIT_CACHE_DB_PATH`, `NIBLIT_DATA_DIR`, `NIBLIT_GAME_LOG_PATH`, `NIBLIT_GAME_STATE_PATH` | General application storage knobs; not broker order authority | Keep canonical memory, Qdrant, logs and ledgers independently pinned; never overwrite production stores for a trading test. |
| `NIBLIT_API_URL=http://10.0.2.2:5000` | Android emulator/Kivy address | Do not use as the desktop Core endpoint. Desktop Core remains loopback unless separately authenticated networking is designed. |

Importantly, `TradingBrain` and the Core six-rule broker execution route are not equivalent. A forecast or RL recommendation must enter a governed decision/evidence contract and never directly call `order_send`. The current TFT adapter may use an EWMA fallback without `pytorch-forecasting`; label the actual model/backend in any evidence.

## Near-term demo acceptance

1. Confirm local Git branch and zero unrelated worktree modifications, run focused broker-double tests in the existing virtual environment.
2. Prepare a new local Core/UI candidate; verify the installed environment really loads an exact pinned remote demo profile. Missing profile is a configuration blocker, not a hardcoded funded restriction.
3. Deploy compatible versioned gateway code via its existing restricted VPS task and SSH tunnel. Do not overwrite its SQLite ledger, funded observer, credentials, broker terminal or known-good release. Verify gateway account identity is DEMO before enabling Algo Trading.
4. **Obtain complete attributed broker prospective cost evidence** for the exact account, currency, side and symbol. The production remote gateway must reject new entry risk without it. Broker-double test cost assumptions are not suitable for the real account.
5. Test explicit reviewed activation, Core and VPS stop persistence/recovery, no auto-rearm, unique broker tickets, stale data/identity rejection, partial/unknown delivery reconciliation and owned-position protection.
6. Observe multiple bounded demo sessions and collect broker-confirmed order, fill, fee, stop, exit and realized net evidence; record zero trades when strategy consensus abstains.

## Funded-trading future milestone (NOT AUTHORIZED)

Before proposing funded execution: require long-window out-of-sample and forward-demo results across changing regimes; audited slippage/fees; verified broker terms and account identity; conservative capital and concentration limits; human-approved scope and expiry; independent operator kill switch; unowned position isolation; complete unknown-delivery recovery; failure-injection and restart/rollback acceptance; independent release and risk review. Funded authorization must be a separate account-scoped capability, not a reinterpretation of `NIBLIT_DESKTOP_OBSERVATION_ONLY`, model switches, or a generic `real_money_enabled` flag. Do not infer profitability from successful software tests.

Use a separate policy artifact and explicit operator approval per account/instrument/size before any funded pilot. Until that future milestone, preserve `funded_execution_available=False`, XM observer restrictions and the independent funded reconciliation breaker.
