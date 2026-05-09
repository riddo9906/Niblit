# Niblit Makefile
# Provides shortcuts for common development tasks.
# Usage: make <target>

.PHONY: help install install-dev test test-coverage lint format typecheck clean run pre-commit

# ── Variables ──────────────────────────────────────────────────────────────────
PYTHON   ?= python3
PIP      ?= pip
PYTEST   ?= pytest
RUFF     ?= ruff
BLACK    ?= black
MYPY     ?= mypy

## help: Show this help message
help:
	@echo ""
	@echo "Niblit — available make targets:"
	@echo ""
	@grep -E '^## ' Makefile | sed 's/## /  /'
	@echo ""

# ── Installation ───────────────────────────────────────────────────────────────

## install: Install core runtime dependencies
install:
	$(PIP) install -r requirements.txt

## install-dev: Install all dependencies including dev/testing tools
install-dev:
	$(PIP) install -r requirements.txt
	$(PIP) install -e ".[dev]"
	pre-commit install

# ── Testing ────────────────────────────────────────────────────────────────────

## test: Run the full test suite
test:
	$(PYTEST) -q

## test-verbose: Run tests with verbose output
test-verbose:
	$(PYTEST) -v

## test-coverage: Run tests and generate an HTML coverage report
test-coverage:
	$(PYTEST) --cov --cov-report=html --cov-report=term-missing -q
	@echo "Coverage report written to htmlcov/index.html"

## test-memory: Run niblit_memory tests only
test-memory:
	$(PYTEST) test_niblit_memory.py -v

## test-router: Run niblit_router tests only
test-router:
	$(PYTEST) test_niblit_router.py -v

## test-brain: Run niblit_brain tests only
test-brain:
	$(PYTEST) test_niblit_brain.py -v

# ── Linting / Formatting ───────────────────────────────────────────────────────

## lint: Run ruff linter (check only, no fixes)
lint:
	$(RUFF) check .

## lint-fix: Run ruff linter and apply auto-fixes
lint-fix:
	$(RUFF) check --fix .

## format: Auto-format all Python files with black
format:
	$(BLACK) --line-length 120 .

## format-check: Check formatting without making changes
format-check:
	$(BLACK) --check --line-length 120 .

## typecheck: Run mypy type checker
typecheck:
	$(MYPY) niblit_memory modules/vector_store.py modules/rag_pipeline.py

# ── Pre-commit ─────────────────────────────────────────────────────────────────

## pre-commit: Run all pre-commit hooks against all files
pre-commit:
	pre-commit run --all-files

## pre-commit-update: Update all pre-commit hooks to latest versions
pre-commit-update:
	pre-commit autoupdate

# ── Running ────────────────────────────────────────────────────────────────────

## run: Start the Niblit CLI
run:
	$(PYTHON) main.py

## run-server: Start the FastAPI server
run-server:
	$(PYTHON) -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# ── Cleanup ────────────────────────────────────────────────────────────────────

## clean: Remove Python cache files and build artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info/ .mypy_cache/ .ruff_cache/ htmlcov/ .coverage
	@echo "Cleaned up build artifacts and caches."

# ── NiblitOS C++ kernel ────────────────────────────────────────────────────────

## boot-kernel: Build the NiblitOS C++ kernel ELF (requires i686-elf cross-compiler)
boot-kernel:
	$(MAKE) -C os all

## boot-kernel-iso: Build bootable ISO image for NiblitOS
boot-kernel-iso:
	$(MAKE) -C os iso

## run-os: Boot NiblitOS in QEMU (requires make boot-kernel-iso first)
run-os:
	$(MAKE) -C os run

## run-os-elf: Boot NiblitOS ELF directly in QEMU (faster, no ISO)
run-os-elf:
	$(MAKE) -C os run-elf

## niblit-shell: Build the NiblitOS userland shell binary (gcc, no cross-compiler needed)
niblit-shell:
	$(MAKE) -C os shell

## niblit-shell-run: Launch the interactive NiblitOS shell on the host
niblit-shell-run:
	$(MAKE) -C os shell-run

## niblit-runner: Build the NiblitOS userspace Niblit tool runner (host bridge)
niblit-runner:
	$(MAKE) -C os runner

## niblit-runner-run: Run the userspace Niblit tool runner (host bridge mode)
niblit-runner-run:
	$(MAKE) -C os runner-run

## kernel-shell: Start the Python kernel/ interactive shell
kernel-shell:
	python3 -m kernel.shell
