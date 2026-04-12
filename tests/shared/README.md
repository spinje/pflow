# Shared Test Utilities

This directory contains reusable test utilities and mock fixtures that can be shared across different test suites.

## Available Utilities

### llm_mock.py

Provides a clean LLM-level mock that prevents actual API calls during tests.

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

    # Run code that uses LLM — no actual API calls made
    result = find_workflow("find a workflow")
    assert result.found
```

### markdown_utils.py

Provides utilities for converting IR dicts to `.pflow.md` markdown format in tests. **This is the primary tool for any test that needs to write a workflow file to disk.**

#### Key Functions:

- `ir_to_markdown(ir_dict, title="Test Workflow", description=None) -> str`: Converts an IR dict to valid `.pflow.md` content
- `write_workflow_file(ir_dict, path, title="Test Workflow", description=None)`: Writes an IR dict as a `.pflow.md` file

#### Purpose:

Replaces `json.dump(workflow, f)` in tests. Handles all IR patterns: shell commands → `shell command` code blocks, prompts → `markdown prompt` code blocks, Python code → `python code` code blocks, batch configs → `yaml batch` code blocks, complex params (stdin, headers) → appropriate YAML code blocks, and simple params as `- key: value` lines.

#### Usage:

```python
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file

# Convert IR to markdown string
markdown = ir_to_markdown({"nodes": [{"id": "echo", "type": "shell", "params": {"command": "echo hello"}}]})

# Write directly to file
write_workflow_file(ir_dict, tmp_path / "workflow.pflow.md")
```

### engine_utils.py

Provides `compile_and_run()` — the standard pattern for compiling IR, seeding the shared store, and executing via `WorkflowEngine`. Matches the production path in `WorkflowRunner._compile_and_execute()`.

#### Key Function:

- `compile_and_run(ir, registry=None, initial_params=None, shared=None, *, metrics_collector=None, trace_collector=None, only_node=None) -> dict`: Compile + seed + run, returns shared store.

#### Usage:

```python
from tests.shared.engine_utils import compile_and_run

# Simple: compile and run, check outputs
shared = compile_and_run(ir, initial_params={"text": "hello"})
assert shared["echo"]["stdout"] == "hello"

# With trace collector
collector = WorkflowTraceCollector("test")
shared = compile_and_run(ir, trace_collector=collector)
assert len(collector.events) == 1

# With --only flag
shared = compile_and_run(ir, only_node="first_step")
```

## Mock Architecture

The LLM mock is applied globally to prevent API calls:
- Mocks at the LLM API level (`llm.get_model`)
- Used by all tests except those in `llm/` directories
- Configured in `tests/conftest.py`

## Test Organization

- **All tests**: Protected from real LLM calls by the global LLM mock
- **LLM tests** (in `llm/` dirs): Skip mocking when `RUN_LLM_TESTS=1` is set

## Adding New Shared Utilities

When adding new utilities:
1. Create a new Python file in this directory
2. Document the utility's purpose and usage in this README
3. Ensure the utility is well-tested
4. Use clear naming conventions
5. Prefer monkeypatch over sys.modules manipulation
6. Consider making utilities configurable for different use cases