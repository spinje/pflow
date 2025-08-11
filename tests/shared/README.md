# Shared Test Utilities

This directory contains reusable test utilities and fixtures that are shared across multiple test suites to avoid code duplication.

## Available Modules

### mocks.py

Provides mock fixtures for testing, including:

- **Planner Mock**: Prevents actual LLM calls during tests by mocking the `pflow.planning` module

## Usage

### Using the Planner Mock

The planner mock is designed to prevent tests from making actual LLM calls while preserving the ability to test other planning-related functionality.

#### In test suite conftest.py:

```python
from tests.shared.mocks import get_autouse_planner_mock

# Apply to all tests in the directory automatically
mock_planner_for_tests = get_autouse_planner_mock()
```

#### For manual control:

```python
from tests.shared.mocks import get_manual_planner_mock

mock_planner = get_manual_planner_mock()

def test_something(mock_planner):
    # Test with planner mocked
    pass
```

## Implementation Details

### Planner Mock

The planner mock selectively blocks imports that would trigger LLM calls:
- `create_planner_flow` - Main entry point
- `PlannerNode`, `DiscoveryNode`, `GeneratorNode` - LLM-using nodes
- `ParameterMappingNode`, `ValidationNode` - Nodes that might use LLM

Other planning module functionality (like `context_builder`) remains accessible, allowing tests that need these utilities to work normally.

## Adding New Shared Utilities

When adding new shared test utilities:

1. Create them in this directory
2. Document them in this README
3. Ensure they're well-tested and maintainable
4. Consider making them configurable (like the `autouse` parameter)
5. Provide clear usage examples