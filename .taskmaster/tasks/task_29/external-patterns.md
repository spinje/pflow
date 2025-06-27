# External Patterns for Task 29: Create comprehensive test suite

## Summary
This task heavily benefits from LLM's testing patterns:
- **CliRunner**: Click's testing framework for CLI commands
- **VCR Pattern**: Record and replay API responses
- **Fixture Organization**: Shared test utilities
- **Parametrized Tests**: Test multiple scenarios efficiently
- **Integration Testing**: End-to-end workflow validation

## Specific Implementation

### Pattern: Test Structure and Fixtures

```python
# tests/conftest.py
import pytest
from click.testing import CliRunner
from pathlib import Path
import json
import os

@pytest.fixture
def runner():
    """Provide a CliRunner for testing CLI commands."""
    return CliRunner()

@pytest.fixture
def isolated_env(runner, tmp_path):
    """Provide isolated filesystem and environment."""
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Set up test environment
        old_home = os.environ.get("PFLOW_HOME")
        os.environ["PFLOW_HOME"] = str(Path.cwd() / "test_home")

        # Create test directories
        Path("test_home").mkdir(exist_ok=True)
        Path("test_home/workflows").mkdir(exist_ok=True)
        Path("test_home/traces").mkdir(exist_ok=True)

        # Mock LLM settings
        os.environ["OPENAI_API_KEY"] = "test-key"

        yield {
            "home": Path("test_home"),
            "runner": runner
        }

        # Restore environment
        if old_home:
            os.environ["PFLOW_HOME"] = old_home
        else:
            os.environ.pop("PFLOW_HOME", None)

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

```python
# tests/test_cli.py
import pytest
from pflow.cli import cli

class TestCLI:
    def test_version_command(self, runner):
        """Test version display."""
        result = runner.invoke(cli, ['--version'])
        assert result.exit_code == 0
        assert 'pflow' in result.output
        assert '0.1.0' in result.output

    def test_help_command(self, runner):
        """Test help display."""
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

### Pattern: VCR for API Testing

```python
# tests/test_integration.py
import vcr
import pytest
from pathlib import Path

# Configure VCR
vcr_config = vcr.VCR(
    cassette_library_dir='tests/fixtures/cassettes',
    filter_headers=['authorization', 'x-api-key'],
    filter_post_data_parameters=['api_key'],
    match_on=['method', 'path', 'query'],
    record_mode='once'  # Change to 'new_episodes' to update
)

class TestIntegration:
    @vcr_config.use_cassette('test_llm_workflow.yaml')
    def test_llm_workflow_execution(self, runner, isolated_env, sample_workflow):
        """Test complete workflow with LLM calls."""
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
        assert "fox" in output.lower() or "processed" in output.lower()

    @vcr_config.use_cassette('test_natural_language_planning.yaml')
    def test_natural_language_to_workflow(self, runner, isolated_env):
        """Test planning from natural language."""
        result = runner.invoke(cli, [
            'run',
            'read the file data.txt and count the words'
        ])

        # Should generate and execute workflow
        assert result.exit_code == 0

    @pytest.mark.parametrize("model", ["gpt-4o-mini", "claude-3-haiku"])
    def test_multiple_llm_providers(self, runner, isolated_env, model):
        """Test different LLM providers."""
        with vcr_config.use_cassette(f'test_{model.replace("-", "_")}.yaml'):
            result = runner.invoke(cli, [
                'run',
                'llm',
                f'--model={model}',
                '--prompt=Say hello'
            ], input="Hello, World!")

            assert result.exit_code == 0
            assert result.output.strip() != ""
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

```
tests/
├── conftest.py                 # Shared fixtures
├── test_cli.py                # CLI command tests
├── test_integration.py        # End-to-end workflow tests
├── test_nodes/               # Node-specific tests
│   ├── test_llm_node.py
│   ├── test_file_nodes.py
│   └── test_github_nodes.py
├── test_planning/            # Planner tests
│   ├── test_workflow_generation.py
│   └── test_prompt_templates.py
├── test_runtime/             # Runtime engine tests
│   ├── test_compiler.py
│   ├── test_tracing.py
│   └── test_shared_store.py
├── benchmarks/               # Performance tests
│   └── test_performance.py
├── test_error_recovery.py    # Error handling tests
└── fixtures/                 # Test data
    ├── cassettes/           # VCR recordings
    ├── workflows/           # Sample workflows
    └── data/               # Test files
```

## Testing Best Practices

1. **Use CliRunner for all CLI tests**: Don't use subprocess
2. **Record API calls with VCR**: Makes tests fast and deterministic
3. **Parametrize when possible**: Test multiple scenarios efficiently
4. **Mock at the right level**: Mock external APIs, not internal components
5. **Test the full stack**: Integration tests catch real issues

## Common Pitfalls to Avoid

1. **Don't test implementation details**: Test behavior, not internals
2. **Don't skip error cases**: Error paths need testing too
3. **Don't forget cleanup**: Use fixtures for proper teardown
4. **Don't hardcode paths**: Use tmp_path and isolated_filesystem
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
- IMPLEMENTATION-GUIDE.md: Testing patterns section
- LLM source: Test suite organization
- Click docs: CliRunner documentation
- VCR.py docs: Recording HTTP interactions
