# Architecture source-review index

Paths verified present in this source snapshot. Presence is not runtime integration.
See SOURCE_REVIEW_STATUS.md for privacy substitutions and incomplete acceptance.

## Core and bootstrap

- `main.py`
- `niblit_core.py`
- `server.py`
- `modules/niblit_ui_launcher.py`
- `modules/runtime_lifecycle.py`

## Cognitive routing/capabilities

- `niblit_router.py`
- `niblit_brain.py`
- `modules/brain_router.py`
- `modules/command_registry.py`
- `modules/cognitive_ingress.py`
- `modules/execution_graph.py`

## Inference and embeddings

- `modules/local_brain.py`
- `modules/portal_model.py`
- `modules/task_admission.py`
- `modules/embedding_engine.py`
- `modules/memory_laboratory/setup.py`

## Memory and Qdrant

- `modules/memory_laboratory/gateway.py`
- `modules/memory_laboratory/runtime.py`
- `modules/memory_laboratory/cognitive.py`
- `modules/memory_graph.py`
- `niblit_memory/governed_qdrant_memory.py`
- `modules/hybrid_qdrant_manager.py`

## Security and recovery

- `modules/security_membrane.py`
- `modules/niblit_cyber_membrane.py`
- `modules/niblit_defensive_evolution_loop.py`
- `modules/autonomous_network.py`
- `modules/self_healer.py`
- `modules/circuit_breaker.py`

## Trading and prediction

- `modules/trading_desk.py`
- `modules/core_trading_sessions.py`
- `modules/trading_session_adapters.py`
- `modules/funded_risk.py`
- `modules/market_prediction.py`
- `modules/cognitive_observation_runtime.py`
- `modules/remote_broker_gateway.py`
- `modules/remote_demo_adapter.py`
- `deploy/vps-gateway/gateway.py`

## Path Manager

- `niblit_core/config/paths.py`

## Packaging and hybrid infrastructure

- `niblit.spec`
- `scripts/niblit-build.js`
- `deploy/hybrid/compose.yml`
- `deploy/hybrid/README.md`

## Representative tests

- `tests/test_niblit_conversation.py`
- `tests/test_chat_admission_priority.py`
- `tests/test_market_prediction.py`
- `tests/test_core_trading_sessions.py`
- `tests/test_api_process_ownership.py`
- `tests/test_hybrid_infrastructure.py`

## Sibling repositories

- UI: `src/pages/ChatPage.tsx`, `src/pages/TradingPage.tsx`, `src/components/MemoryFramework.tsx`, `src/services/niblitApi.ts`, `src-tauri/tauri.conf.json`.
- Cloud: `app/main.py`, `app/shared_gguf.py`, `app/trading/router.py`, `app/trading/freqtrade_adapter.py`, `tests/core_execution_contract_cases.py`.
- LEAN: `services/execution_coordinator.py`, `persistence/execution_repository.py`, `risk/engine.py`, `tests/test_r3_execution_safety.py`.

## Validation of reviewed changes

Core 384 passed; UI 63 passed and TypeScript no-emit passed; Cloud 68 passed (including a nested 34-case contract run, not added to the parent count); LEAN 25 passed. These are isolated fixture/source checks, not new broker/runtime/deployment acceptance. No native-model training or funded trading was performed.

## Additional validation limitation

The additional Node broker-view fixture suite has 5 passes and 1 failure. The
same failure reproduces in the untouched original source: the synthetic demo
account lacks a broker field, producing an undefined broker label in the selected
XM view. This is not caused by privacy substitutions. No application or fixture
repair was made during repository synchronization. Core validation is therefore
partial despite the 384 passing Python cases. The separate observation-freshness
and intelligence UI fixture scripts pass. Do not treat this branch as fully
accepted for production deployment.
