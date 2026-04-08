# Contributing to Niblit

Thank you for your interest in contributing to **Niblit — AIOS** (Neural Integrated Baseline for Learning, Intelligence, and Tasking)!

This guide covers how to set up your environment, run tests, and submit pull requests.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Submitting Changes](#submitting-changes)
- [Architecture Overview](#architecture-overview)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/Niblit.git
   cd Niblit
   ```
3. **Create a branch** for your change:
   ```bash
   git checkout -b feat/your-feature-name
   ```

---

## Development Environment

### Prerequisites

- Python ≥ 3.10
- `pip` (or `pipx` / `uv`)
- (Optional) `pre-commit` for automatic formatting/linting on commit

### Install dependencies

```bash
# Install all dependencies including dev tools
make install-dev

# Or manually
pip install -r requirements.txt
pip install pytest pytest-cov ruff black mypy pylint pre-commit
```

### Set up environment variables

```bash
cp .env.example .env
# Edit .env and fill in at least HF_TOKEN
```

### Set up pre-commit hooks (recommended)

```bash
pre-commit install
```

This will run ruff, black, and basic file-hygiene checks automatically before every commit.

---

## Running Tests

```bash
# Run the full test suite
make test

# Or directly with pytest
pytest -q

# Run a specific test file
pytest test_niblit_memory.py -v
pytest test_niblit_router.py -v
pytest test_niblit_brain.py -v

# With coverage report
make test-coverage
```

All tests must pass before a PR is merged.  Adding new tests for your changes is strongly encouraged and required for new features.

---

## Code Style

Niblit follows these conventions:

| Tool | Purpose | Command |
|------|---------|---------|
| **black** | Auto-formatter | `make format` |
| **ruff** | Linter + isort | `make lint-fix` |
| **mypy** | Type checker (gradual) | `make typecheck` |
| **pylint** | Extra checks | `pylint <file>` |

Key rules:
- **Line length**: 120 characters
- **Imports**: stdlib → third-party → local (enforced by ruff/isort)
- **Logging**: use `log.debug()` for routing/classification metadata; use `log.info()` for user-visible events
- **Optional imports**: wrap in `try/except` so Niblit degrades gracefully when heavy dependencies are absent
- **No bare `print()`** in library modules — use the logging system

---

## Submitting Changes

1. **Lint and test** before opening a PR:
   ```bash
   make lint
   make test
   ```
2. **Write a clear commit message** (imperative mood, ≤72 chars):
   ```
   feat: add concept synthesizer to SECA pipeline
   fix: resolve LocalDB deadlock on concurrent writes
   docs: update CONTRIBUTING with pre-commit setup
   ```
3. **Open a Pull Request** against `main`:
   - Describe *what* you changed and *why*.
   - Reference any related issues (`Closes #42`).
   - Add screenshots/logs for UI or behaviour changes.

All PRs require at least one passing CI run before they can be merged.

---

## Architecture Overview

Niblit is an AI Operating System (AIOS) with the following boot sequence:

```
Phase 0 — Environment    (config.py, .env)
Phase 1 — BIOS/HAL       (modules/bios.py, aios_hal.py)
Phase 2 — Bootloader     (modules/bootloader.py)
Phase 3 — Memory         (niblit_memory/, FusedMemory + KnowledgeDB)
Phase 4 — Brain          (niblit_brain.py → HFBrain / AnthropicAdapter)
Phase 5 — ALE            (modules/autonomous_learning_engine.py)
Phase 6 — Router/Agents  (niblit_router.py, agents/)
Phase 7 — Interface      (niblit_io.py, app.py, kivy_app.py)
```

Key modules to know:
- **`niblit_memory/`** — unified memory package (FusedMemory + KnowledgeDB + LocalDB)
- **`niblit_brain.py`** — LLM inference, BrainTrainer, self-improvement
- **`niblit_router.py`** — message classification and command routing
- **`niblit_core.py`** — system orchestration and command registry
- **`modules/autonomous_learning_engine.py`** — the ALE self-learning loop
- **`modules/rag_pipeline.py`** — RAG (Retrieval-Augmented Generation) pipeline

See [`NIBLIT_AIOS.md`](NIBLIT_AIOS.md) for the full architecture document.

---

## Reporting Bugs

Please open a GitHub Issue with:

1. **Steps to reproduce** the problem
2. **Expected behaviour** vs what actually happened
3. **Python version** (`python --version`) and OS
4. **Relevant log output** (set `NIBLIT_LOG_LEVEL=DEBUG`)

---

## Feature Requests

Open a GitHub Issue labelled `enhancement` with:

- A clear description of the feature and the problem it solves
- Any references to related work or prior art
- Whether you would like to implement it yourself

---

*Happy hacking! 🤖*
