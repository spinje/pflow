.PHONY: install
install: ## Install the virtual environment and install the pre-commit hooks
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@uv run pre-commit install

.PHONY: check
check: ## Run code quality tools.
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run -a
	@echo "🚀 Static type checking: Running mypy"
	@uv run mypy
	@echo "🚀 Checking for obsolete dependencies: Running deptry"
	@uv run deptry src

.PHONY: test
test: ## Test the code with pytest in parallel (excludes LLM tests that require API keys)
	@echo "🚀 Testing code: Running pytest in parallel with 4 workers (excluding LLM tests)"
	@uv run python -m pytest -n 4 --doctest-modules --ignore=tests/test_planning/llm --ignore=tests/test_nodes/test_llm/test_llm_integration.py

.PHONY: test-debug
test-debug: ## Test the code with pytest sequentially for debugging
	@echo "🚀 Testing code: Running pytest sequentially (for debugging)"
	@uv run python -m pytest -n 0 -vv --tb=short --doctest-modules --ignore=tests/test_planning/llm --ignore=tests/test_nodes/test_llm/test_llm_integration.py

.PHONY: test-llm
test-llm: ## Run LLM integration tests with real API calls (requires API keys)
	@echo "🚀 Testing LLM with real API calls"
	@echo "📝 Note: Requires 'llm keys set openai' (or 'llm keys set anthropic' with llm-anthropic plugin)"
	@RUN_LLM_TESTS=1 uv run python -m pytest tests/test_nodes/test_llm/test_llm_integration.py tests/test_planning/llm -v

.PHONY: test-all
test-all: ## Run all tests including LLM integration tests in parallel
	@echo "🚀 Testing code: Running all tests including LLM integration (4 workers)"
	@RUN_LLM_TESTS=1 uv run python -m pytest -n 4 --doctest-modules

.PHONY: test-with-skipped
test-with-skipped: ## Run tests showing all skipped tests (useful for debugging)
	@echo "🚀 Testing code: Running all tests (showing skipped)"
	@uv run python -m pytest --doctest-modules -v | grep -E "PASSED|FAILED|SKIPPED|ERROR"

.PHONY: build
build: clean-build ## Build wheel file
	@echo "🚀 Creating wheel file"
	@uvx --from build pyproject-build --installer uv

.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo "🚀 Removing build artifacts"
	@uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: publish
publish: ## Publish a release to PyPI.
	@echo "🚀 Publishing."
	@uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

.PHONY: build-and-publish
build-and-publish: build publish ## Build and publish.

.PHONY: help
help:
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.DEFAULT_GOAL := help
