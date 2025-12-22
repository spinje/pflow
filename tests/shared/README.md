# Shared Test Utilities

This directory contains reusable test utilities and mock fixtures that can be shared across different test suites.

## Available Utilities

### llm_mock.py

Provides a clean LLM-level mock that prevents actual API calls while allowing the planning module to function normally.

#### Key Components:

- `MockLLMModel`: Simulates the `llm` library's Model interface
- `MockGetModel`: Mock for `llm.get_model()` function
- `create_mock_get_model()`: Factory function to create mock instances

#### Purpose:

The LLM mock:
1. Prevents expensive LLM API calls during tests
2. Provides configurable responses for different test scenarios
3. Tracks call history for verification
4. Ensures test isolation with automatic cleanup

#### Usage:

The mock is automatically applied to all tests via `tests/conftest.py`. Tests can configure responses:

```python
def test_something(mock_llm_responses):
    # Configure what the LLM will return
    mock_llm_responses.set_response(
        "anthropic/claude-sonnet-4-5",
        WorkflowDecision,
        {"found": True, "workflow_name": "test-workflow"}
    )

    # Run code that uses LLM
    result = some_planner_function()

    # LLM is mocked, no actual API calls made
    assert result.workflow_name == "test-workflow"
```

### planner_block.py

Provides a clean way to block the planner import for CLI and integration tests that need to test fallback behavior.

#### Key Functions:

- `create_planner_block_fixture()`: Creates a fixture that blocks planner imports

#### Purpose:

The planner blocker:
1. Makes `from pflow.planning import create_planner_flow` raise ImportError
2. Triggers CLI fallback behavior (shows "Collected workflow from..." messages)
3. Allows testing of non-planner functionality
4. Uses monkeypatch for clean, scoped patching

#### Usage:

In your test's `conftest.py`:

```python
from tests.shared.planner_block import create_planner_block_fixture

# Block planner to test fallback behavior
block_planner = create_planner_block_fixture()
```

## Mock Architecture

The testing infrastructure uses two complementary mocking strategies:

1. **LLM Mock** (llm_mock.py): Applied globally to prevent API calls
   - Mocks at the LLM API level (`llm.get_model`)
   - Allows planning module to work normally
   - Used by all tests except those in `llm/` directories
   - Configured in `tests/conftest.py`

2. **Planner Blocker** (planner_block.py): Applied to CLI/integration tests
   - Blocks planner import to test fallback behavior
   - Uses clean monkeypatch approach
   - Scoped to specific test directories
   - Used in `tests/test_cli/conftest.py` and `tests/test_integration/conftest.py`

## Test Organization

- **All tests**: Protected from real LLM calls by the global LLM mock
- **CLI tests**: Use planner blocker to test fallback messages
- **Integration tests**: Use planner blocker to focus on workflow execution
- **Planning tests**: Use LLM mock with configured responses
- **LLM tests** (in `llm/` dirs): Skip mocking when `RUN_LLM_TESTS=1` is set

## Adding New Shared Utilities

When adding new utilities:
1. Create a new Python file in this directory
2. Document the utility's purpose and usage in this README
3. Ensure the utility is well-tested
4. Use clear naming conventions
5. Prefer monkeypatch over sys.modules manipulation
6. Consider making utilities configurable for different use cases