# Developer Tools

This directory contains developer tools that are NOT part of the pflow package distribution.

## test_prompt_accuracy.py

A tool for testing and tracking the accuracy and cost of LLM prompts used by the pflow planner.

### Usage

```bash
# Test a prompt and update metrics (default behavior)
uv run python tools/test_prompt_accuracy.py discovery

# Test without updating (dry run)
uv run python tools/test_prompt_accuracy.py discovery --dry-run

# Test with a specific model (e.g., Haiku for lower cost)
uv run python tools/test_prompt_accuracy.py discovery --model anthropic/claude-3-haiku-20240307

# Test all prompts with ultra-cheap model and parallelization (fastest + cheapest)
for prompt in discovery component_browsing parameter_discovery parameter_mapping workflow_generator; do
    uv run python tools/test_prompt_accuracy.py $prompt --model gpt-5-nano
done

# Or override auto-detected workers for different parallelization
uv run python tools/test_prompt_accuracy.py discovery --parallel 20
```

### Features

- Tracks test accuracy over multiple runs
- Handles LLM response variance through averaging
- Automatic version management when prompts change
- Stores all metrics in prompt file frontmatter
- Shows test count for context
- **Cost tracking** - Captures token usage and calculates API costs
- **Model selection** - Test with different models to balance cost vs accuracy
- **Parallel execution** - Run tests up to 10x faster with auto-detected parallel workers (defaults to test count, max 20)

### Cost Tracking

The tool now tracks API costs for each test run:
- Captures token usage (input/output) from LLM API responses
- Calculates costs based on model-specific pricing
- Adds `last_test_cost` field to prompt frontmatter
- Displays cost information in test results
- **Model override works via pytest conftest.py** - no production code changes needed

Supported models with pricing (per million tokens):
- `gpt-5-nano` - $0.05/$0.40 (input/output) - **Cheapest** test model
- `gpt-5-mini` - $0.25/$2.00 - Very cheap test model
- `anthropic/claude-3-haiku-20240307` - $0.25/$1.25 - Good for testing
- `anthropic/claude-sonnet-4-0` - $3.00/$15.00 - **Default**, highest quality
- `gpt-5` - $1.50/$10.00 - Alternative test model

Full list of models, but need to update pricing list in the tool.

```bash
uv run llm models
```

### Requirements

This tool requires dev dependencies to be installed:
```bash
uv sync  # Installs all dependencies including dev
```

The tool specifically needs:
- PyYAML (for frontmatter parsing)
- pytest (for running tests)
- LLM API keys configured
- llm library (for model interaction)

See `src/pflow/planning/prompts/README.md` for detailed documentation about the prompt accuracy tracking system.

### Implementation Details

The cost tracking and model override features work without modifying any production code:

1. **Model Override**: A `conftest.py` file in the test directory checks for the `PFLOW_TEST_MODEL` environment variable and monkey-patches `llm.get_model()` to redirect all model requests to the specified model.

2. **Token Tracking**: The same `conftest.py` captures token usage from LLM responses and saves it to a temporary JSON file specified by `PFLOW_TOKEN_TRACKER_FILE` environment variable.

3. **Cost Calculation**: The test runner reads back the token data from the temp file and calculates costs based on model-specific pricing.

This approach ensures that:
- Production code remains unchanged
- Model overrides only affect test execution
- Token tracking is transparent to the tests
- Clean separation between testing and production concerns

### Performance with Parallel Testing

The tool now supports parallel test execution, dramatically reducing test time:

- **Serial execution**: ~2+ minutes for comprehensive test suites
- **Parallel execution** (auto-detected workers): ~8-10 seconds
- **Parallel with 20 workers** (max): ~6-8 seconds

Tests that support parallelization (like the refactored discovery prompt tests) will automatically use the `PARALLEL_WORKERS` environment variable. Each test runs in its own thread, allowing multiple LLM calls to execute concurrently.

Example timing comparison:
```bash
# Serial (slow)
PARALLEL_WORKERS=1 uv run python tools/test_prompt_accuracy.py discovery
# Time: ~120 seconds

# Parallel (fast, auto-detects optimal workers)
uv run python tools/test_prompt_accuracy.py discovery
# Time: ~10 seconds (12x faster!)

# Maximum parallel (fastest)
uv run python tools/test_prompt_accuracy.py discovery --parallel 20
# Time: ~8 seconds
```