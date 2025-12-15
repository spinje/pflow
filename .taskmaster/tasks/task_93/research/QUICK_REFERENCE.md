# Quick Reference: Template Error Suggestions

## TL;DR

When an agent uses wrong template like `${node.wrong_field}`, pflow shows:
1. All available fields from that node (up to 20)
2. Up to 3 "Did you mean?" suggestions
3. Concrete fix example

## Key Files

```
src/pflow/runtime/template_validator.py  # Main error generation (lines 386-463)
src/pflow/core/suggestion_utils.py       # Reusable suggestion utilities
tests/test_runtime/test_template_validator_enhanced_errors.py  # Tests
```

## Error Format

```
Node 'fetch' does not output 'msg'

Available outputs from 'fetch':
  ✓ ${fetch.result} (dict)
  ✓ ${fetch.result.messages} (array)
  ✓ ${fetch.result.messages[0].text} (string)
  ... and 14 more

Did you mean: ${fetch.result.messages}?
Common fix: Change ${fetch.msg} to ${fetch.result.messages}
```

## How It Works

### 1. Available Fields
- **Source**: Registry metadata from node interfaces
- **Process**: Recursive structure flattening
- **Limit**: 20 fields (MAX_DISPLAYED_FIELDS)

### 2. Suggestions
- **Algorithm**: Substring matching (case-insensitive)
- **Example**: `"msg"` finds `"messages"`
- **Limit**: 3 suggestions (MAX_DISPLAYED_SUGGESTIONS)

### 3. Type Validation
- **Shows**: Fields matching expected type
- **Example**: For `str` parameter, shows string fields only
- **Limit**: 5 fields per type error

## Configuration Constants

```python
# src/pflow/runtime/template_validator.py (lines 42-45)
MAX_DISPLAYED_FIELDS = 20      # Available outputs shown
MAX_DISPLAYED_SUGGESTIONS = 3  # "Did you mean?" options
MAX_FLATTEN_DEPTH = 5          # Prevent infinite recursion
```

## Usage Locations

1. **Pre-execution** - Validation before workflow runs
2. **Runtime** - During execution if strict mode enabled
3. **Repair** - After validation failures for auto-fix

## Common Agent Patterns

| Mistake | Error Shows | Agent Fixes |
|---------|-------------|-------------|
| `${node.msg}` | Did you mean: `messages`? | `${node.messages}` |
| `${node.result}` (dict) | Available fields with correct type | `${node.result.text}` |
| `${node.output}` | Available: `result`, `data` | `${node.result}` |

## Suggestion Utilities API

```python
from pflow.core.suggestion_utils import find_similar_items, format_did_you_mean

# Find similar items
suggestions = find_similar_items("msg", ["messages", "message", "text"])
# Returns: ["messages", "message"]

# Format message
message = format_did_you_mean("msg", suggestions, item_type="field")
# Returns: "Did you mean one of these fields?\n  - messages\n  - message"
```

## Security

All error values sanitized to prevent:
- Terminal escape sequences
- Log injection (newlines removed)
- Buffer overflow (100 char limit)

## Performance

- **Typical workflow**: <50ms validation
- **Structure flattening**: O(depth × fields)
- **Substring matching**: O(paths × key_length)
- **Caching**: Results cached during compilation

## Implementation Notes

**Task 71** added this system:
- Enhanced error messages with structure
- Multi-section error format
- Type-aware suggestions
- Security sanitization

**Related**: `suggestion_utils.py` provides reusable logic for CLI/MCP/runtime
