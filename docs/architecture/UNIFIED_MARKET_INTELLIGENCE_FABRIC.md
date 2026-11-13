# Unified Market Intelligence Fabric — implemented desktop slice

Updated 2026-11-12. Overall expansion remains **partial**; this document distinguishes the working slice from subsequent phases. Canonical task evidence lives under `C:/Users/Operator/Documents/Codex/2026-11-07/referenced-chatgpt-conversation-this-is-an-2/outputs`.

## Actual architecture

`Desktop terminal64.exe → existing MT5Bridge → DesktopMarketIntelligence → market-evidence-v1 → existing Core /api/trading/analysis → CognitiveIngress / ExecutionGraph → existing six-rule strategy_manager → analysis-only governance → canonical SQLite/outbox → existing Qdrant worker → existing Market Desk`.

The new desktop panel is independent of the existing remote broker selector. The saved VPS configuration is preserved, but no remote order path is silently redirected to desktop. Desktop observations bind account hash and terminal ID on every read and before serving cached results. Account changes reject the request and require a fresh explicit binding. No new execution authority was introduced.

| Boundary | Actual implementation | Evidence / limit |
|---|---|---|
| MT5 IPC | `modules/mt5_bridge.py`, official MetaTrader5 connector | Read-only desktop Exness demo account verified; explicit installed executable, no login/account switch/order calls |
| Shared acquisition | `modules/desktop_market_intelligence.py` | M5 200 bars, H1/H4 100 each, one acquisition per frame, 16-key / five-second cache, account/terminal recheck; broker lock released before Core HTTP |
| Recognition | `modules/market_evidence.py` | Closed candles only, stable snapshot hashes, explicit availability times, pattern provenance, confirmed swings and structure; no predictive probabilities |
| Six strategies | existing `modules/strategy_manager.py` / `demo_strategy.py` | Same M5 bars and advisory context, exactly six existing votes; rules, selection and risk thresholds preserved |
| Cognition/governance | existing `modules/cognitive_ingress.py` / `execution_graph.py` | Real Core analysis receipts, explicit execution_authorized=false; source evidence and generated interpretations remain unverified |
| Durability | existing `MemoryRuntime` / `MemoryGateway` | Actual receipt survived the host reboot; canonical outbox complete and sampled Qdrant payload matched canonical data after Docker recovery |
| UI | existing `modules/trading_desk.py` and trading-desk assets | Explicit desktop binding, indicators/patterns/structure, strategy results, cognition/memory receipts and inventory; stale after 60 seconds without another read |

## Coverage and limitations

The deterministic candle rules cover engulfing, hammer/hanging man, shooting star/inverted hammer, doji variants, pin bars, inside/outside bars, morning/evening star, tweezers, soldiers/crows and harami. Their source rules are versioned; exhaustive formation fixtures, user-configurable thresholds and statistical reliability are not accepted yet. Multi-candle matches do not cross session gaps. Swings require two closed bars to the right and retain their later availability timestamp.

Implemented indicator evidence: SMA20, EMA20, SMA-based RSI14/ATR14 and Bollinger20. Smoothing and seed differences from MT5 are explicitly labeled. MACD, stochastic, ADX, Ichimoku, CCI, momentum, additional native timeframes and calendar-aware monthly bars remain pending. Volume is broker tick count, not exchange traded volume.

MQL5 components are inventoried without execution. Compiled EX5 internals and unspecified buffers are unknown. The optional authenticated custom-indicator/EA publisher is not implemented in this slice; existing chart annotation functionality is preserved. No discovered EA/script is automatically approved or launched.

The panel uses manual snapshot requests. Expiry labeling is automatic, but continuous event-driven scanning and desktop demo-session selection remain separate acceptance work. Existing remote demo controls are preserved and remain unavailable when their gateway cannot verify its broker. No trading tests were placed.

## Learning and command modernization

`learning_commands.py` now starts actual owned work through the existing task authority: one local-only cycle, at most one 256-token model call, one source read and one observation. Start requires the existing exact permission and readiness checks; busy ownership is retained. Stop reports stopping versus finished. `command_effects.py` checks lifecycle postconditions for evolution, SLSA and HF activation; research aliases use the same ALE owner. Metadata availability is not proof every command was exercised.

A real cycle completed with one model call, one source observation and durable unverified memory. Citation checking classified its output as **knowledge_gap**, not verified knowledge. Credential-like source fragments are redacted before model input/storage; the endpoint's credential detector remains enforced. Training weights, code deployment, paid fallback and funded execution remain off. Current inventory: 414 entries, 382 executable, 17 protected trading families, 15 unavailable.

## Infrastructure and verification

The container increment is documented in `deploy/hybrid/README.md`. Native MT5/MQL5, Tauri, authoritative Core and llama.cpp remain Windows processes. The native model used the existing CPU launcher; Vulkan GPU acceleration was not newly enabled or accepted. No duplicate model or Core was introduced.

262 focused Python regressions passed, plus a Node test proving observation expiry without network/trading actions. Actual desktop-to-Core-to-Desk readback produced six rule results and durable memory receipts; HOLD and SELL were observed at different times, as analysis only. Observed service-level acquisition/analysis latency ranged approximately 4–15 seconds during concurrent startup/backup work. Low-latency continuous operation is not yet accepted. First Core boots took several minutes, including an unavailable Lean dependency; do not relabel that component healthy.

An intervening Windows reboot at 20:25 SAST interrupted native processes and Docker. After explicit user authorization Docker was restarted; its existing Freqtrade runtime was verified dry-run and stopped. Canonical outbox state and sampled Qdrant payload survived. Native services were restored through the supported launcher; automatic native startup at host boot is not claimed.

SQLite backup/restore and five Qdrant snapshot restores were verified in isolated destinations. The first undersized Qdrant test storage produced optimizer errors; the final Docker-managed validation volume reached green with matching counts/hashes and successful vector queries. Production Qdrant was never restored, recreated or deliberately restarted. Independently timed SQLite/Qdrant backups are not an atomic cross-store recovery checkpoint: recovery must reconcile the projection from canonical events.

## Remaining dependency-ready work

Follow `CAPABILITY_MODERNIZATION.md` and the task's architecture/container/accuracy plans. Priorities are live data-quality expansion; full pattern/indicator/timeframe coverage; controlled MQL5 publication; explicit desktop demo-session adapter selection; retrieval relevance and closed-loop outcome reconciliation; cost-aware walk-forward validation, calibrated uncertainty, drift and counterfactual no-trade outcomes. None may silently change consensus, risk limits or permissions.

The full container orchestration/cutover and Kubernetes API/runtime validation remain pending. VPS reintegration remains deferred until connectivity, account identity and reconciliation are freshly verified. Historical XM observations and old startup acceptance are not current guarantees.

## Rollback

Retain earlier releases and canonical databases. Stop only the owned candidate through its supported shutdown after confirming no unfinished learning/delivery; wait for the actual process and ports to exit. Launch the prior version/profile. Do not restore an old ledger or permissions file over new events. New UI and code are packaged separately from secrets/runtime data. Container rollback stops only the development candidate; production portal and Qdrant volumes remain external and unchanged. Restore helpers require fresh paths. No `down -v`, collection deletion or production restore is part of rollback.


## 2026-11-12 Phase 6 November 8 acceptance update

The actual November 8 release is updated and is the active acceptance runtime; r5 was retired. Independent desktop and VPS Exness demo observation feeds the existing six-strategy Core and Market Desk. Tunnel outage/recovery passed without execution activation. XM live remains unverified while Exness occupies the shared remote terminal. Phase 6 is partial; see docs/architecture/PHASE6_NOV8_RUNTIME_ACCEPTANCE.md for tests, limits, evidence and rollback. Approved cache cleanup removed 40,451 unchanged .pyc files (784.80 MiB logical bytes); skipped 0. Original .py sources were checked before each removal; no directories, models, databases, configuration, package source, Docker volumes or Git objects were removed. Free-space changes include other concurrent writers. Caches regenerate on import; no runtime restart is required.


## 2026-11-13 Phase 6 prediction/Chat continuation

Actual November 8 release updated to nov8+phase6-prediction-chat-20261113-r4; Core PID 11868 owns API. Native Niblit selection uses Core intent/context/scoped memory and existing local Qwen; foreground scheduling gives one bounded waiting chat the next inference slot without clearing leases. Greetings skip unrelated retrieval; fallback/memory labels corrected. Closed-candle shadow 5/15/30-minute forecasts and hypothetical outcomes persist with NUCM references; probabilities remain uncalibrated and net costs UNKNOWN. Desktop and VPS sources remain independently identity-bound; latest remote readback is Exness demo and the XM profile is consequently unverified. Earlier live XM verification is historical. No demo reactivation or funded mutations. 384 Python and 63 UI tests passed. Controlled UI wait/interrupt defect fixed; original unexplained exit remains unestablished. Full Phase 6 and new master addendum are not complete. Evidence/rollback: docs/architecture/PHASE6_SHADOW_PREDICTION_CHAT_ACCEPTANCE.md and task outputs/NIBLIT_PHASE6_CONTINUATION_REPORT.md.
