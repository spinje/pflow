# Task 103: Preserve Type for Simple Templates in Dict/List Values

## ID
103

## Title
Preserve Type for Simple Templates in Dict/List Values

## Description
When resolving template variables inside dict/list values, preserve the original type if the value is exactly `"${template}"` (simple template) instead of serializing to JSON string. This enables constructing inline objects with multiple data sources, most useful for shell node stdin.

## Status
completed

## Dependencies
None - this is a self-contained enhancement to the template resolver.

## Priority
medium

## Details
Currently, when you write:
```json
"stdin": {"config": "${config}", "data": "${data}"}
```

The template resolver treats each dict value as a string template and serializes the resolved values to JSON strings, resulting in double-encoding:
```json
{"config": "{\"name\": \"MyApp\"}", "data": "{\"value\": \"Hello\"}"}
```

Instead of the desired:
```json
{"config": {"name": "MyApp"}, "data": {"value": "Hello"}}
```

### The Fix
In `template_resolver.py`, when resolving templates inside dict/list values:
1. Detect if the value is exactly `"${template}"` (simple template, nothing else)
2. If so, preserve the resolved type (dict, list, int, etc.) instead of serializing to JSON string
3. Only serialize when the template is embedded in a larger string like `"prefix ${var} suffix"`

### Why This Matters
This pattern enables passing multiple structured data sources to a single shell command via stdin:
```json
{
  "stdin": {"a": "${data-a}", "b": "${data-b}"},
  "command": "jq '.a.field + .b.field'"
}
```

Without this, users must use temp files or separate nodes to combine data - a significant usability gap.

### Scope
- Modify `TemplateResolver.resolve_string()` or add a new method for dict/list value resolution
- The change should be recursive - nested dicts/lists should also preserve types for simple templates
- This benefits ALL nodes, not just shell - any node accepting structured params can use this pattern

### Example Before/After

**Before (current behavior):**
```python
resolve({"items": "${my_list}"})
# → {"items": "[1, 2, 3]"}  # string, double-encoded
```

**After (desired behavior):**
```python
resolve({"items": "${my_list}"})
# → {"items": [1, 2, 3]}  # preserved as list
```

## Test Strategy
Unit tests in `tests/test_runtime/test_template_resolver.py`:

1. **Simple template in dict value preserves type**
   - `{"key": "${dict_var}"}` → dict preserved, not stringified

2. **Simple template in list value preserves type**
   - `["${item1}", "${item2}"]` → each item type preserved

3. **Mixed template still serializes**
   - `{"key": "prefix ${var} suffix"}` → string result (current behavior)

4. **Nested dict/list preservation**
   - `{"outer": {"inner": "${data}"}}` → nested type preserved

5. **Integration test with shell node**
   - Verify `stdin: {"a": "${x}", "b": "${y}"}` passes correct JSON to command
