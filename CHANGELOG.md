# Changelog

All notable changes to **Niblit — AIOS** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- `pyproject.toml` — PEP 621 packaging config consolidating build, tool settings (ruff, black, mypy, pytest, coverage), and metadata.
- `.pre-commit-config.yaml` — pre-commit hooks for black, ruff, and file hygiene.
- `Makefile` — common dev tasks (`make test`, `make lint`, `make format`, `make run`, …).
- `CONTRIBUTING.md` — contributor guide covering environment setup, testing, code style, and PR process.
- `CHANGELOG.md` — this file, following the Keep a Changelog format.
- `py.typed` marker file for PEP 561 compliance.
- Unit tests for `niblit_memory` (`test_niblit_memory.py`) — 37 tests covering `FusedMemory`, `FusedMemoryPrimary`, `LocalDB`, and the ingestion helpers.
- Unit tests for `niblit_router` (`test_niblit_router.py`) — 32 tests covering `ChatDetector.classify()`, `NiblitRouter.process()`, and helper functions.
- Unit tests for `niblit_brain` (`test_niblit_brain.py`) — 31 tests covering `NiblitBrain`, `BrainTrainer`, `process_query()`, and `handle()`.

### Fixed
- **`LocalDB` deadlock** — changed `threading.Lock()` to `threading.RLock()` in `LocalDB.__init__()` to prevent a re-entrancy deadlock when `add_fact()`, `store_learning()`, or `store_preferences()` called `_save()` while already holding the lock.

---

## [2.0.0] — 2026-02-01

### Added
- **NIBLIT-AIOS** architecture — full AI Operating System with 7-phase boot sequence (BIOS → HAL → Bootloader → Memory → Brain → ALE → Interface).
- **SECA** (Self-Evolving Cognitive Architecture) — `MemoryGraph` (ARG), `RewardModel` (SRM), and `ConceptSynthesizer` integrated into `KnowledgeComprehension`.
- **RAG Pipeline** — `RAGPipeline` combining dense vector retrieval (`VectorStore`) and SECA graph search (`search_graph()`).
- **LLM Provider Manager** — unified switching between HuggingFace Router (primary) and Anthropic (fallback); CLI `llm-provider` command.
- **LLM Chat Memory** — SQLite-backed persistent conversation history (`LLMChatMemory`).
- **LLM Training Agent** — structured Q/A pair generation for knowledge gaps (`LLMTrainingAgent`).
- **RL Trading Policy** — PPO, DQN, and Transformer policies via `RLTradingPolicy`; wired into `TradingBrain`.
- **TradingBrain** — 7-dimensional state vector (close, volume, RSI, MACD, EMA-20, ATR-14, volatility).
- **Autonomous GitHub** — self-push of evolved files to GitHub (`modules/autonomous_github.py`).
- **Nibblebot** — weekly improvement bot that studies top GitHub repos and creates issues (`nibblebots/improvement_bot.py`).
- **Research Bot** — autonomous research pipeline with Niblit integration (`nibblebots/research_bot.py`).
- **MCP Server** — Model Context Protocol server for tool exposure (`modules/mcp_server.py`).
- **GradedCurriculum** — grade-aligned ALE topic progression from primary school to advanced programming.
- **Distributed Niblit** — experimental multi-node mode (`distributed_niblit/`).
- **Hybrid Qdrant Manager** — local + cloud Qdrant routing (`modules/hybrid_qdrant_manager.py`).

### Changed
- `niblit_memory/` rewritten as a canonical package, merging `FusedMemory`, `FusedMemoryPrimary`, `LocalDB`, `KnowledgeDB`, and ingestion helpers into a single importable surface.
- `logging.basicConfig()` centralized in `main.py`; individual modules only call `logging.getLogger()`.
- All routing/classification metadata in `niblit_router.py` demoted to `log.debug()`.
- Embedding model changed to `intfloat/multilingual-e5-small` (384-dim, 100-language support).

---

## [1.0.0] — 2025-11-01

### Added
- Initial release of Niblit AI agent.
- HuggingFace LLM integration.
- REST API (FastAPI).
- SQLite memory backend.
- Kivy mobile app with Android APK support via Buildozer.
- Vercel + Render + Fly.io deployment support.
- Self-researcher, self-healer, and self-teacher modules.
- Autonomous Learning Engine (ALE) with background research loop.

---

[Unreleased]: https://github.com/riddo9906/Niblit/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/riddo9906/Niblit/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/riddo9906/Niblit/releases/tag/v1.0.0
