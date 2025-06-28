# Patterns Discovered

## Pattern: Empty stdin handling with CliRunner
**Context**: When you need to handle both stdin and command arguments in Click CLI tests
**Solution**: Check if stdin has content before using it to avoid conflicts with CliRunner
**Why it works**: CliRunner simulates a non-tty stdin even when empty, so checking content prevents false positives
**When to use**: Any CLI command that accepts both stdin and other input methods
**Example**:
```python
elif not sys.stdin.isatty():
    raw_input = sys.stdin.read().strip()
    if raw_input:  # Only use stdin if it has content
        # Process stdin input
        source = "stdin"
    else:
        # Fall back to other input method
        source = "args"
```

## Pattern: Context storage verification in tests
**Context**: When you need to verify Click context storage in tests but can't directly access ctx.obj
**Solution**: Create a simplified test that verifies behavior indirectly through output
**Why it works**: The output reflects the stored values, avoiding complex monkey-patching
**When to use**: Testing Click commands that use ctx.obj for passing data between commands
**Example**:
```python
def test_run_context_storage_verification():
    """Test that context stores values correctly."""
    runner = click.testing.CliRunner()

    # Test through output instead of direct context access
    result = runner.invoke(cli, ["run", "test"])
    assert "expected output reflecting context" in result.output
```
