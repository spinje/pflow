# Patterns Discovered

## Pattern: Click Group Exit Codes
**Context**: When testing Click CLI applications that use @click.group()
**Solution**: Expect exit code 2 when no command is provided, not 0
**Why it works**: Click groups show help and exit with code 2 to indicate usage error
**When to use**: Any time you test a Click group with no arguments
**Example**:
```python
def test_no_arguments():
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    # Click groups return exit code 2 when no command is provided
    assert result.exit_code == 2  # NOT 0!
    assert "Commands:" in result.output
```
