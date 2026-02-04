# tests/test_cli/CLAUDE.md

## Critical: Planner is Gated

**Planner is gated at the production level** (Task 107 — pending markdown format prompt rewrite):
- The planner entry point in `cli/main.py` shows a user-facing message instead of invoking the planner
- **Planner blocker from tests/shared/planner_block.py** is still applied via `conftest.py` as an additional safety layer
- Same blocker is used by test_integration tests for consistency

**LLM calls are prevented globally** by `tests/conftest.py`

## Test Expectations

CLI tests expect **blocked planner behavior**:
- Natural language from args → Shows "Collected workflow from args: ..."
- Natural language from file → Shows "Collected workflow from file: ..."
- CLI syntax input → Shows "Collected workflow from args: ..."
- NOT planner execution, NOT workflow generation, NOT LLM calls

## Direct Workflow Execution

The CLI now supports **direct execution** bypassing the planner:
- `my-workflow param=value` → Tries to load and execute directly (100ms)
- `pflow workflow.pflow.md param=value` → Direct execution with params
- If workflow not found → Shows error with suggestions (planner is gated)

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
- Tests run with planner blocked - you're testing CLI behavior, not planner
- Use `runner.isolated_filesystem()` for file operations
- CliRunner always returns False for `isatty()` - can't test interactive prompts

## Common Pitfalls

1. **Don't test actual planner** - It's blocked for a reason (testing fallback behavior)
2. **Don't modify conftest.py blocker** - It ensures consistent test behavior
3. **Don't expect planner output** - Tests see fallback behavior
4. **Don't use real workflow names** - May trigger direct execution attempt

## If Tests Hang

Tests hanging = planner making real LLM calls. Check:
1. Is conftest.py blocker still in place?
2. Did someone change the import mechanism?
3. Is there a new code path bypassing the blocker?
4. Is the global LLM mock in tests/conftest.py working?