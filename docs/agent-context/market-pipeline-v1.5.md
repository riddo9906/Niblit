# Market pipeline v1.5 source map
Updated: 2026-11-01T16:44:24.089435+00:00

## Implemented and fixture-verified chain
UI TradingPage.tsx -> iframe Market Desk8767 -> GET /api/freqtrade/research (modules/trading_desk.create_app) -> FreqtradeResearch.snapshot -> Desk.configuration / whitelist / market -> actual six demo_strategy rules via strategy_manager.assess -> existing local research journal.
For verified dry_run=true only, snapshot forwards the same candle observations through trading_desk.core_market_analysis -> fixed loopback Core port from NIBLIT_API_PORT (default5000) -> POST /api/trading/analysis (server.market_analysis) -> bound existing unified runtime.run_cognitive_cycle -> CognitiveIngress.ingest -> Core _authorize -> ExecutionGraph.run -> strategy_manager.assess_observation -> existing assess/evaluate -> normalized BUY/SELL/HOLD/ABSTAIN -> analysis-only execution gate.
Core authorization_denied applies regardless of routed mode and precedes specialist evaluation. Context-supplied market decisions cannot survive an evaluator failure.
The endpoint does not expose an order action or treat a signal as execution permission.

## Canonical memory chain
CognitiveIngress._record_market_analysis -> existing runtime_memory singleton -> existing MemoryRuntime.enqueue -> existing ingestion_outbox/source_heads in canonical SQLite ledger.
Namespace hashes configured parent scope + symbol + venue + interval + execution mode + account/profile scope + strategy set/policy.
Pending market scopes are drained by MemoryRuntime.tick_market_partitions on the already existing worker, using the same MemoryGateway/embedder. No additional worker, model, ledger or vector authority.
Gateway.require applies to enqueue and again at projection/read. Missing grant returns pending/PermissionError; this revision grants no permissions. Reads in other scopes cannot retrieve the records even if the fake vector backend ignores filters.
Queue commit before projection, restart, outage retry and permission revocation are tested. Saved observations remain unverified at confidence0.2; no learning/profitability assertion.
Existing cognitive checkpoints retain observation data and pending queue failure status. A process crash before canonical enqueue commits can leave only the pending cognition checkpoint; automatic replay of that checkpoint is still missing.

## Existing execution and monitoring authorities retained
MT5: MT5Bridge snapshot/connect/tick -> DemoAutotrader.step/_step -> existing DemoOrders.inspect/preview/confirm -> demo account and identity checks, broker risk/margin/stop/quote checks -> durable mt5_tickets before delivery -> order_send -> history/reconcile -> DemoAutotrader.outcomes -> Desk export_outcomes -> existing MemoryRuntime.
Freqtrade manual: Desk.preview/validate -> ticket -> Desk.confirm with revalidation/idempotency/unknown-state blocking -> existing forceenter/forceexit API -> Desk.reconcile/snapshot -> persisted outcomes -> permission-gated export_outcomes.
Core paper: server /api/trading/paper/* -> PaperTradingController -> existing strategy worker8150/replay pending-ack -> existing Lean runtime8100 /v1/decisions/execute -> TradingRuntimeManager.execute_decision/_execute_decision -> ExecutionCoordinator -> DecisionValidator -> RiskEngine -> existing adapter -> ExecutionRepository/ExecutionReconciler.
The new Core analysis result is NOT automatically converted into any of these order requests. Existing human approval, account, risk and ambiguous-submit guards are unchanged and their regression tests pass with doubles.

## Other source paths inspected and unresolved
Core TradingBrain.cycle/decide_action contains legacy Binance/indicator/RL/TFT/memory paths. It is not the new structured-analysis authority and is not comprehensively migrated.
Core cognitive ingress/execution graph previously used ForecastArbitrator/TFT for free-text forecasts. That behavior remains for unstructured requests; structured market observations use the existing registry instead. Market episodes do not use unscoped general recall/write.
Core TradingRuntimeClient is a health/read-only Lean bridge; no order method was added.
Lean sibling root: C:/Users/Operator/Documents/GitHub/niblit-lean-algos, HEAD bfa656e5c4d74cb5ea6b23721b949f590bd79b57, clean at read-only inspection. Actual manager.py, api/trading_api.py, services/execution_coordinator.py, decision_validator.py and risk/engine.py own its distinct strategy/runtime execution contracts. No Lean files changed.
Cloud sibling: C:/Users/Operator/Documents/GitHub/Niblit-cloud-server, HEAD c6f2291f0ca9fc76ab77b3f2723d439c7dd78c32, clean at inspection. app/trading/pipeline.py chains MarketDataAdapter -> MarketIntelligenceEngine -> LeanAlgosBridge -> GGUF -> RiskEngine -> TradeIntent -> FreqtradeAdapter -> feedback. LeanAlgosBridge currently also reads signal files/rules; it is not proof all Lean algorithms executed.
IMPORTANT GAP: app/trading/router.py execute_trade converts payload approved using bool(), and app/trading/freqtrade_adapter.py execute lacks a verified Core authorization receipt and non-live mode check when its enable flag is on. This pre-existing route is outside the verified chain; no Cloud flag or service was activated. It needs fail-closed characterization/reconciliation with the existing Core authority before enabling any order integration. No blanket Core-denial guarantee across all old paths is claimed.
UI sibling: C:/Users/Operator/Documents/GitHub/niblit-ui, HEAD4425a4b1cdaf662552e6d8af44f408b6341bdbf3, clean at inspection. TradingPage embeds8767; paperTradingApi talks through Core paper routes. No TSX edits or UI deployment. Current UI does not yet render the new Core receipt/trace fields.

## Evidence boundaries
252 tests passed. Actual HTTP handlers, real six-rule execution, Core graph and SQLite tested with fixture feeds/brokers/vector backend. Actual unified-runtime wrapper also retains existing cognition contract regression coverage.
Current real-feed attempt: ConnectError. Native readiness: local model and memory unavailable. Docker engine unavailable. No current-market, authenticated broker, actual Qdrant service, packaged build, full Core boot or full convergence claim.
