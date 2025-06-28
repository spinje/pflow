# External Patterns for Task 29: Create comprehensive test suite

## Key Clarifications

After examining llm-main's actual test implementation:
- **CliRunner Usage**: LLM creates CliRunner instances directly in tests, not via fixtures
- **API Recording**: LLM uses `pytest-recording` (not VCR directly) with `@pytest.mark.vcr` decorator
- **Test Organization**: LLM has a flat test structure with descriptive file names
- **Fixtures**: LLM primarily uses conftest.py for mock models and environment setup

## Summary
This task benefits from LLM's testing patterns and general pytest best practices:
- **CliRunner**: Click's testing framework for CLI commands (used by llm in all CLI tests)
- **pytest-recording**: Record and replay API responses (llm uses this, not VCR directly)
- **Fixture Organization**: Shared test utilities via conftest.py
- **Parametrized Tests**: Test multiple scenarios efficiently (pytest feature used by llm)
- **Integration Testing**: End-to-end workflow validation

## Specific Implementation

### Pattern: Test Structure and Fixtures

Based on llm's test structure (see `llm-main/tests/conftest.py`), here's how to organize fixtures:

```python
# tests/conftest.py
import pytest
from click.testing import CliRunner
from pathlib import Path
import json
import os

# Note: llm doesn't define a runner fixture - they create CliRunner instances directly
# in tests. However, a runner fixture can be convenient for consistency.

@pytest.fixture
def user_path(tmpdir):
    """Similar to llm's user_path fixture - creates isolated test directory."""
    dir = tmpdir / "pflow_test"
    dir.mkdir()
    return dir

@pytest.fixture(autouse=True)
def env_setup(monkeypatch, user_path):
    """Similar to llm's env_setup - sets up environment variables."""
    monkeypatch.setenv("PFLOW_HOME", str(user_path))

@pytest.fixture
def isolated_env(user_path):
    """Provide isolated filesystem and environment for pflow tests."""
    # Create test directories
    (user_path / "workflows").mkdir(exist_ok=True)
    (user_path / "traces").mkdir(exist_ok=True)

    return {
        "home": user_path,
        "runner": CliRunner()
    }

@pytest.fixture
def sample_workflow():
    """Provide a sample workflow IR for testing."""
    return {
        "nodes": [
            {
                "id": "read1",
                "type": "read-file",
                "params": {"file_path": "input.txt"}
            },
            {
                "id": "llm1",
                "type": "llm",
                "params": {"model": "gpt-4o-mini", "temperature": 0}
            },
            {
                "id": "write1",
                "type": "write-file",
                "params": {"file_path": "output.txt"}
            }
        ],
        "edges": [
            {"from": "read1", "to": "llm1", "action": "default"},
            {"from": "llm1", "to": "write1", "action": "default"}
        ],
        "start_node": "read1"
    }

@pytest.fixture
def mock_nodes(monkeypatch):
    """Mock node implementations for testing."""
    from pocketflow import Node

    class MockReadFileNode(Node):
        def prep(self, shared):
            return self.params.get("file_path")

        def exec(self, file_path):
            # Simulate reading
            return f"Content of {file_path}"

        def post(self, shared, prep_res, exec_res):
            shared["content"] = exec_res
            shared["text"] = exec_res
            return "default"

    class MockLLMNode(Node):
        def prep(self, shared):
            return shared.get("text", "")

        def exec(self, text):
            # Simulate LLM response
            return f"Processed: {text}"

        def post(self, shared, prep_res, exec_res):
            shared["response"] = exec_res
            shared["text"] = exec_res
            return "default"

    # Would need to mock registry to return these nodes
    return {
        "read-file": MockReadFileNode,
        "llm": MockLLMNode
    }
```

### Pattern: CLI Testing with CliRunner

Following llm's pattern (see `llm-main/tests/test_llm.py`):

```python
# tests/test_cli.py
from click.testing import CliRunner
import pytest
from pflow.cli import cli

def test_version():
    """Test version display - llm pattern: create CliRunner in test."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("pflow, version ")

def test_help_command():
    """Test help display."""
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert 'Plan Once, Run Forever' in result.output

    # Test subcommand help
    result = runner.invoke(cli, ['run', '--help'])
    assert result.exit_code == 0
    assert 'Run a workflow' in result.output

    @pytest.mark.parametrize("input_method", ["args", "stdin", "file"])
    def test_run_command_input_methods(self, runner, isolated_env, input_method):
        """Test different ways to provide input."""
        workflow_text = "summarize this document"

        if input_method == "args":
            result = runner.invoke(cli, ['run', workflow_text])
        elif input_method == "stdin":
            result = runner.invoke(cli, ['run'], input=workflow_text)
        else:  # file
            Path("workflow.txt").write_text(workflow_text)
            result = runner.invoke(cli, ['run', '--file', 'workflow.txt'])

        # All methods should work
        assert result.exit_code == 0

    def test_pipe_operator_preservation(self, runner):
        """Test that >> operator is preserved correctly."""
        result = runner.invoke(cli, [
            'run',
            'read-file', '--path=input.txt',
            '>>',
            'llm', '--prompt=summarize'
        ])

        # Should capture full command with >>
        assert result.exit_code == 0

    def test_error_handling(self, runner):
        """Test error messages are helpful."""
        # No input provided
        result = runner.invoke(cli, ['run'])
        assert result.exit_code != 0
        assert 'No workflow provided' in result.output

        # Invalid file
        result = runner.invoke(cli, ['run', '--file', 'nonexistent.json'])
        assert result.exit_code != 0
```

### Pattern: API Recording for Testing

LLM uses `pytest-recording` (which wraps VCR) for API testing (see `llm-main/tests/test_tools.py`):

```python
# tests/test_integration.py
import pytest
from pathlib import Path

# LLM's approach: Use @pytest.mark.vcr decorator
# pytest-recording provides this functionality

class TestIntegration:
    @pytest.mark.vcr
    def test_llm_workflow_execution(self, isolated_env):
        """Test complete workflow with LLM calls - using llm's pytest.mark.vcr pattern."""
        runner = CliRunner()

        # Create test input
        Path("input.txt").write_text("The quick brown fox jumps over the lazy dog.")

        # Save workflow
        Path("workflow.json").write_text(json.dumps(sample_workflow))

        # Execute workflow
        result = runner.invoke(cli, ['run', '--file', 'workflow.json'])

        assert result.exit_code == 0
        assert Path("output.txt").exists()

        # Verify LLM processed the content
        output = Path("output.txt").read_text()
        assert len(output) > 0

    @pytest.mark.vcr
    def test_natural_language_to_workflow(self, isolated_env):
        """Test planning from natural language."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            'run',
            'read the file data.txt and count the words'
        ])

        # Should generate and execute workflow
        assert result.exit_code == 0

    # Note: In llm, parametrized tests with VCR would use separate cassettes
    # automatically based on the test name and parameters
```

### Pattern: Performance Testing

```python
# tests/benchmarks/test_performance.py
import pytest
import time
from statistics import mean, stdev

class TestPerformance:
    @pytest.mark.benchmark
    def test_planning_latency(self, runner, benchmark):
        """Test planning speed meets targets."""
        def plan_workflow():
            result = runner.invoke(cli, [
                'plan',  # Planning-only command
                'summarize this document'
            ])
            assert result.exit_code == 0
            return result

        # Run benchmark
        result = benchmark(plan_workflow)

        # Verify meets target (≤800ms)
        assert benchmark.stats['mean'] < 0.8

    @pytest.mark.benchmark
    def test_execution_overhead(self, runner, isolated_env, benchmark):
        """Test execution overhead meets targets."""
        # Create simple workflow without external calls
        workflow = {
            "nodes": [{"id": "n1", "type": "pass-through", "params": {}}],
            "edges": [],
            "start_node": "n1"
        }

        Path("simple.json").write_text(json.dumps(workflow))

        def execute_workflow():
            result = runner.invoke(cli, ['run', '--file', 'simple.json'])
            assert result.exit_code == 0
            return result

        # Run benchmark
        result = benchmark(execute_workflow)

        # Verify overhead ≤2s
        assert benchmark.stats['mean'] < 2.0

    def test_token_usage_optimization(self, runner, isolated_env):
        """Test that token usage is tracked and reasonable."""
        with vcr_config.use_cassette('test_token_tracking.yaml'):
            result = runner.invoke(cli, [
                'run',
                '--trace',
                'llm',
                '--prompt=Count to 5'
            ], input="Please count from 1 to 5")

            assert result.exit_code == 0

            # Check trace was created
            traces = list(Path("test_home/traces").glob("*.json"))
            assert len(traces) == 1

            # Verify token usage is tracked
            with open(traces[0]) as f:
                trace = json.load(f)

            assert trace['summary']['total_tokens'] > 0
            assert trace['summary']['total_tokens'] < 1000  # Reasonable limit
```

### Pattern: Error Recovery Testing

```python
# tests/test_error_recovery.py
class TestErrorRecovery:
    def test_missing_file_handling(self, runner, isolated_env):
        """Test graceful handling of missing files."""
        workflow = {
            "nodes": [{
                "id": "read1",
                "type": "read-file",
                "params": {"file_path": "missing.txt"}
            }],
            "edges": [],
            "start_node": "read1"
        }

        Path("workflow.json").write_text(json.dumps(workflow))

        result = runner.invoke(cli, ['run', '--file', 'workflow.json'])

        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_api_failure_recovery(self, runner, isolated_env):
        """Test handling of API failures."""
        # Use VCR cassette with simulated failure
        with vcr_config.use_cassette('test_api_failure.yaml'):
            result = runner.invoke(cli, [
                'run',
                'llm',
                '--model=gpt-4',  # Might fail on rate limits
                '--prompt=Test'
            ])

            # Should either succeed with fallback or fail gracefully
            if result.exit_code != 0:
                assert "error" in result.output.lower()
                assert "fallback" in result.output.lower() or "retry" in result.output.lower()
```

### Pattern: Test Organization

LLM's test organization (from `llm-main/tests/`):
```
tests/
├── conftest.py                 # Shared fixtures and mock models
├── test_llm.py                # Core CLI tests
├── test_cli_options.py        # CLI option handling
├── test_cli_openai_models.py  # Model-specific tests
├── test_tools.py              # Tool/function calling tests
├── test_plugins.py            # Plugin system tests
├── test_templates.py          # Template tests
├── test_keys.py               # API key management
├── test_llm_logs.py           # Logging functionality
├── test_async.py              # Async functionality
├── test_embed.py              # Embedding tests
├── test_embed_cli.py          # Embedding CLI tests
├── test_utils.py              # Utility function tests
├── cassettes/                 # pytest-recording cassettes
│   └── test_tools/           # Organized by test module
│       ├── test_tool_use_basic.yaml
│       └── test_tool_use_chain_of_two_calls.yaml
└── test-llm-load-plugins.sh   # Shell script for plugin testing
```

Recommended pflow test organization based on llm patterns:
```
tests/
├── conftest.py                # Shared fixtures (following llm's pattern)
├── test_cli.py               # Core CLI tests (like llm's test_llm.py)
├── test_run_command.py       # Run command specific tests
├── test_plan_command.py      # Plan command tests
├── test_registry.py          # Node registry tests
├── test_nodes.py             # Node implementation tests
├── test_workflow.py          # Workflow execution tests
├── test_integration.py       # End-to-end tests
├── cassettes/                # API recordings (llm pattern)
│   └── test_integration/    # Organized by test module
└── fixtures/                 # Test data
    ├── workflows/           # Sample workflow files
    └── data/               # Test input files
```

## Testing Best Practices (from llm and pytest patterns)

1. **Use CliRunner for all CLI tests**: Don't use subprocess (llm pattern)
2. **Record API calls with pytest-recording**: Makes tests fast and deterministic (llm uses this)
3. **Parametrize when possible**: Test multiple scenarios efficiently (pytest best practice)
4. **Mock at the right level**: Mock external APIs, not internal components
5. **Test the full stack**: Integration tests catch real issues
6. **Create CliRunner in tests**: LLM creates fresh CliRunner instances in each test rather than using fixtures

## Common Pitfalls to Avoid

1. **Don't test implementation details**: Test behavior, not internals
2. **Don't skip error cases**: Error paths need testing too
3. **Don't forget cleanup**: Use pytest's tmpdir and monkeypatch for isolation
4. **Don't hardcode paths**: Use tmpdir fixture (llm pattern)
5. **Don't ignore performance**: Track regressions with benchmarks

## Coverage Requirements

```ini
# .coveragerc or pyproject.toml
[tool.coverage.run]
source = ["src/pflow"]
omit = ["*/tests/*", "*/test_*.py"]

[tool.coverage.report]
fail_under = 80
show_missing = true
skip_covered = false
```

## References
- `llm-main/tests/`: Actual test implementation patterns
- `llm-main/tests/conftest.py`: Fixture organization and mock models
- `llm-main/tests/test_llm.py`: Core CLI testing patterns with CliRunner
- `llm-main/tests/test_tools.py`: pytest-recording usage example
- `llm-main/pyproject.toml`: Test dependencies including pytest-recording
- Click docs: CliRunner documentation
- pytest-recording docs: Modern VCR alternative used by llm
