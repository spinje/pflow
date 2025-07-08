# Patterns Discovered

## Pattern: Docstring First Line Extraction
**Context**: When you need to extract a description from a Python docstring that may have various formats
**Solution**: Use `inspect.getdoc()` and iterate through lines to find first non-empty line
**Why it works**:
- `inspect.getdoc()` handles indentation cleanup automatically
- Iterating through lines handles edge cases like empty first lines
- Provides consistent fallback for missing docstrings

**When to use**: Any time you need to extract a summary from Python docstrings
**Example**:
```python
def _extract_description(self, docstring: str | None) -> str:
    if not docstring:
        return "No description"

    lines = docstring.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line:
            return line

    return "No description"
```
