# tests/test_cli/CLAUDE.md

## Critical: Planner is Mocked

**Shared mock from tests/shared/mocks.py** prevents LLM calls during tests:
- Applied via `conftest.py` to all CLI tests automatically (`autouse=True`)
- Makes `from pflow.planning import create_planner_flow` raise ImportError
- This triggers fallback to old behavior: `"Collected workflow from args: ..."`
- **DO NOT** remove or modify this mock without understanding the implications
- Same mock is used by test_integration tests for consistency

## Test Expectations

CLI tests expect **mocked planner behavior**:
- Natural language from args → Shows "Collected workflow from args: ..."
- Natural language from file → Shows "Collected workflow from file: ..."
- CLI syntax input → Shows "Collected workflow from args: ..."
- NOT planner execution, NOT workflow generation, NOT LLM calls

## Direct Workflow Execution

The CLI now supports **direct execution** bypassing the planner:
- `my-workflow param=value` → Tries to load and execute directly (100ms)
- `pflow --file workflow.json param=value` → Direct execution with params
- If workflow not found → Falls back to planner

Detection logic in `src/pflow/cli/main.py::is_likely_workflow_name()`:
- `my-workflow param=value` → Detected as workflow (has params)
- `my-analyzer` → Detected as workflow (kebab-case)
- `node1 => node2` → NOT workflow (has `=>` operator)
- `analyze data` → NOT workflow (has spaces)
- `analyze` → NOT workflow (common natural language word)

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