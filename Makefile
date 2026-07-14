UV ?= uv
PYTHON = $(UV) run python
PYTEST = $(PYTHON) -m pytest
PYTEST_WORKERS ?= 4
LLM_INTEGRATION_TEST := tests/test_nodes/test_llm/test_llm_integration.py
PYTEST_NON_LLM := --doctest-modules --ignore=$(LLM_INTEGRATION_TEST)
TEST_TARGETS := test test-e2e test-debug test-llm test-all test-all-local test-with-skipped

# Target-specific exports are handled by GNU Make itself, so they work with
# POSIX shells and native Windows cmd.exe. The environment variable (rather
# than Python's -X flag) is required so pytest-xdist workers inherit it.
$(TEST_TARGETS): export PYTHONWARNDEFAULTENCODING := 1
test-llm test-all: export RUN_LLM_TESTS := 1
# This diagnostic target must never make paid API calls because a developer
# happens to have RUN_LLM_TESTS set in their shell.
test-with-skipped: export RUN_LLM_TESTS :=

.PHONY: verify-encoding-warning
verify-encoding-warning:
	@$(PYTHON) -c "import sys; sys.flags.warn_default_encoding or sys.exit('PYTHONWARNDEFAULTENCODING was not inherited by Python')"

.PHONY: verify-openai-key
verify-openai-key:
	@$(PYTHON) -c "import os, sys; os.environ.get('RUN_LLM_TESTS') == '1' or sys.exit('RUN_LLM_TESTS=1 was not inherited by Python'); os.environ.get('OPENAI_API_KEY') or sys.exit('OPENAI_API_KEY must be exported to run paid LLM tests')"

$(TEST_TARGETS): verify-encoding-warning
test-llm test-all: verify-openai-key

.PHONY: install
install: ## Install the virtual environment and install the pre-commit hooks
	@echo [setup] Creating virtual environment using uv
	@$(UV) sync
	@$(UV) run pre-commit install

.PHONY: check
check: ## Run code quality tools.
	@echo [check] Checking lock file consistency with pyproject.toml
	@$(UV) lock --locked
	@echo [check] Checking Claude and Codex reusable assets are synchronized
	@$(UV) run python scripts/sync_claude_assets.py --check
	@echo [check] Linting all files with ruff
	@$(UV) run ruff check .
	@$(UV) run ruff format --check .
	@echo [check] Running pre-commit
	@$(UV) run pre-commit run -a
	@echo [check] Running mypy
	@$(UV) run mypy
	@echo [check] Checking for obsolete dependencies with deptry
	@$(UV) run deptry src

.PHONY: sync-claude-assets
sync-claude-assets: ## Regenerate Codex assets derived from Claude sources.
	@$(UV) run python scripts/sync_claude_assets.py --write

.PHONY: test
test: ## Test the code with pytest in parallel (excludes LLM tests that require API keys)
	@echo [test] Running non-e2e tests with $(PYTEST_WORKERS) workers, excluding paid LLM tests
	@$(PYTEST) -n $(PYTEST_WORKERS) --dist=worksteal $(PYTEST_NON_LLM) -m "not e2e and not paid"

.PHONY: test-e2e
test-e2e: ## Run real subprocess / shell / pipe boundary tests in parallel
	@echo [test] Running e2e tests with $(PYTEST_WORKERS) workers, excluding paid LLM tests
	@$(PYTEST) -n $(PYTEST_WORKERS) --dist=worksteal $(PYTEST_NON_LLM) -m "e2e and not paid"

.PHONY: test-debug
test-debug: ## Test the code with pytest sequentially for debugging
	@echo [test] Running all non-LLM tests sequentially for debugging, including e2e
	@$(PYTEST) -n 0 -vv --tb=short $(PYTEST_NON_LLM) -m "not paid"

.PHONY: test-llm
test-llm: ## Run LLM integration tests with real API calls (requires API keys)
	@echo [test] Running paid LLM integration tests
	@echo [test] OPENAI_API_KEY must be exported in the environment
	@$(PYTEST) $(LLM_INTEGRATION_TEST) -v

.PHONY: test-all
test-all: ## Run all tests including LLM integration tests in parallel
	@echo [test] Running all tests, including paid LLM tests, with $(PYTEST_WORKERS) workers
	@$(PYTEST) -n $(PYTEST_WORKERS) --doctest-modules

.PHONY: test-all-local
test-all-local: ## Run all non-LLM tests, including e2e, in parallel
	@echo [test] Running all non-LLM tests, including e2e, with $(PYTEST_WORKERS) workers
	@$(PYTEST) -n $(PYTEST_WORKERS) --dist=worksteal $(PYTEST_NON_LLM) -m "not paid"

.PHONY: test-with-skipped
test-with-skipped: ## Run non-paid tests showing skip reasons (useful for debugging)
	@echo [test] Running all tests without paid API calls and showing skip reasons
	@$(PYTEST) $(PYTEST_NON_LLM) -m "not paid" -v -rs

.PHONY: ui-build
ui-build: ## Build the web UI bundle into src/pflow/ui/static (requires Node).
	@echo [build] Building pflow UI frontend bundle
	@cd web && npm ci && npm run build

.PHONY: build
build: clean-build ui-build ## Build wheel file (includes the UI bundle)
	@echo [build] Creating wheel file
	@uvx --from build pyproject-build --installer uv

.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo [build] Removing build artifacts
	@$(UV) run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: publish
publish: ## Publish a release to PyPI.
	@echo [publish] Uploading release to PyPI
	@uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

.PHONY: build-and-publish
build-and-publish: build publish ## Build and publish.

.PHONY: help
help:
	@echo Available targets:
	@echo   install            Install dependencies and pre-commit hooks
	@echo   check              Run linting, formatting, pre-commit, mypy, and deptry
	@echo   test               Run non-e2e tests, excluding paid LLM tests
	@echo   test-e2e           Run subprocess and shell boundary tests
	@echo   test-debug         Run all non-LLM tests sequentially, including e2e
	@echo   test-all-local     Run all non-LLM tests in parallel, including e2e
	@echo   test-with-skipped  Run safely without paid calls and show skip reasons
	@echo   test-llm           Run paid LLM integration tests
	@echo   test-all           Run every test, including paid LLM tests
	@echo   ui-build           Build the web UI bundle
	@echo   clean-build        Remove Python build artifacts
	@echo   build              Build the Python wheel
	@echo   build-and-publish  Build and upload a release to PyPI
	@echo   publish            Upload a release to PyPI

.DEFAULT_GOAL := help
