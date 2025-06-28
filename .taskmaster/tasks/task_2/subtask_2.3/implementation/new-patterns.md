# Patterns Discovered

## Pattern: Click Validation Override
**Context**: When you need custom error messages but Click's built-in validators run first
**Solution**: Use basic types (str instead of click.Path(exists=True)) and handle validation manually
**Why it works**: Click's validators run before the command function, preventing custom error messages
**When to use**: When you need full control over error message formatting
**Example**:
```python
# Instead of:
@click.option("--file", type=click.Path(exists=True))

# Use:
@click.option("--file", type=str)
def main(file):
    if file:
        try:
            content = Path(file).read_text()
        except FileNotFoundError:
            raise click.ClickException("cli: Custom error message")
```

## Pattern: Complexity Reduction via Helper Functions
**Context**: When ruff complains about function complexity (C901)
**Solution**: Extract logical units into helper functions with clear interfaces
**Why it works**: Reduces cyclomatic complexity and improves readability
**When to use**: When a function exceeds complexity limit (10) or has distinct logical sections
**Example**:
```python
def read_workflow_from_file(file_path: str) -> str:
    """Read workflow from file with proper error handling."""
    try:
        return Path(file_path).read_text().strip()
    except FileNotFoundError:
        raise click.ClickException(f"cli: File not found: '{file_path}'") from None
```

## Pattern: Per-File Linting Exceptions
**Context**: When specific linting rules don't apply to certain files
**Solution**: Use per-file-ignores in pyproject.toml
**Why it works**: Allows targeted rule exceptions without disabling rules globally
**When to use**: When a file has legitimate reasons to violate specific rules
**Example**:
```toml
[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]  # Allow assert in tests
"src/pflow/cli/main.py" = ["TRY003"]  # Allow long error messages in CLI
```
