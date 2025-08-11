# tests/test_cli/CLAUDE.md

## Critical: Planner is Mocked

**conftest.py mocks the planner** to prevent LLM calls during tests:
- All tests get `mock_planner_for_tests` fixture automatically (`autouse=True`)
- Makes `from pflow.planning import create_planner_flow` raise ImportError
- This triggers fallback to old behavior: `"Collected workflow from args: ..."`
- **DO NOT** remove or modify this mock without understanding the implications

## Test Expectations

CLI tests expect **pre-planner behavior**:
- Natural language input → Shows "Collected workflow from args: ..."
- CLI syntax input → Shows "Collected workflow from args: ..."
- NOT planner execution, NOT workflow generation, NOT LLM calls

## Workflow Name Detection

The CLI tries to detect workflow names vs natural language:
- `my-workflow param=value` → Direct execution attempt
- `node1 => node2` → NOT detected as workflow (has `=>`)
- `analyze data` → NOT detected as workflow (has spaces)

Detection logic in `src/pflow/cli/main.py::is_likely_workflow_name()`

## Writing New CLI Tests

```python
def test_example():
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["args", "here"])
    assert result.exit_code == 0
    assert "expected output" in result.output
```

**Important**:
- Tests run with planner mocked - you're testing CLI behavior, not planner
- Use `runner.isolated_filesystem()` for file operations
- CliRunner always returns False for `isatty()` - can't test interactive prompts

## Common Pitfalls

1. **Don't test actual planner** - It's mocked for a reason (LLM costs, speed)
2. **Don't modify conftest.py mock** - It fixes all tests automatically
3. **Don't expect planner output** - Tests see fallback behavior
4. **Don't use real workflow names** - May trigger direct execution attempt

## If Tests Hang

Tests hanging = planner making real LLM calls. Check:
1. Is conftest.py mock still in place?
2. Did someone change the import mechanism?
3. Is there a new code path bypassing the mock?