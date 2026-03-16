# tests/test_cli/CLAUDE.md

## Direct Workflow Execution

The CLI supports direct execution:
- `my-workflow param=value` → Tries to load and execute directly
- `pflow workflow.pflow.md param=value` → Direct execution with params
- If workflow not found → Shows error with suggestions

Detection logic in `src/pflow/cli/main.py::is_likely_workflow_name()`:
- `my-workflow param=value` → Detected as workflow (has params)
- `my-analyzer` → Detected as workflow (kebab-case)
- `node1 => node2` → NOT workflow (has `=>` operator)
- `analyze data` → NOT workflow (has spaces)

## Writing New CLI Tests

```python
def test_example():
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["args", "here"])
    assert result.exit_code == 0
    assert "expected output" in result.output
```

**Important**:
- Use `runner.isolated_filesystem()` for file operations
- CliRunner always returns False for `isatty()` — can't test interactive prompts
- Don't use real workflow names — may trigger direct execution attempt

## If Tests Hang

Check:
1. Is the global LLM mock in tests/conftest.py working?
2. Did someone add a real LLM call without mocking?
