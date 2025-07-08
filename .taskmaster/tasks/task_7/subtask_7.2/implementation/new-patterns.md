# Patterns Discovered

## Pattern: Multi-line Regex Matching with Optional Newlines
**Context**: When you need to parse structured text that may have multi-line continuations and the last item might not end with a newline
**Solution**: Use `\n?` to make the final newline optional in your regex pattern
**Why it works**: Text at the end of strings or docstrings often lacks a trailing newline
**When to use**: Parsing any structured text format where items span multiple lines
**Example**:
```python
# Original pattern that required newline after each item
INTERFACE_PATTERN = r'Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n)*)'

# Fixed pattern with optional final newline
INTERFACE_PATTERN = r'Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)'
```

## Pattern: Extracting Names from Descriptive Text
**Context**: When you need to extract just the identifier from text that includes descriptions or metadata
**Solution**: Use regex to match just the identifier part before any parenthetical descriptions
**Why it works**: Identifiers typically follow predictable patterns (word characters) before descriptions
**When to use**: Parsing parameter lists, action names, or any formatted list with optional descriptions
**Example**:
```python
def _extract_params(self, content: str) -> list[str]:
    # Remove global notes first
    content = re.sub(r'\s*\(as fallbacks[^)]*\)', '', content)

    params = []
    for param in content.split(','):
        param = param.strip()
        if param:
            # Extract just the parameter name (before any parentheses)
            match = re.match(r'(\w+)', param)
            if match:
                params.append(match.group(1))
    return params
```
