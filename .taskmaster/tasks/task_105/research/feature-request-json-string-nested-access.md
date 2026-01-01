# Feature Request: Auto-Parse JSON Strings During Nested Template Access

**Type**: Feature Enhancement
**Priority**: Medium
**Component**: `src/pflow/runtime/template_resolver.py`
**Date**: 2026-01-01

---

## Summary

When a node output contains a JSON string (e.g., `stdout` from a shell command), nested template access like `${node.stdout.field}` fails because the intermediate value is a string, not a parsed object. Users expect JSON strings to be automatically parsed when accessing nested properties.

---

## Problem Statement

### Current Behavior

Template resolution treats JSON strings as opaque strings. Nested property access on a string value fails:

```
${node.stdout}       → '{"iso": "2026-01-01", "month": "January"}'  ✅ Works
${node.stdout.iso}   → Unresolved variable error                    ❌ Fails
```

### Expected Behavior

When accessing a nested property on a value that is a valid JSON string, automatically parse it first:

```
${node.stdout}       → '{"iso": "2026-01-01", "month": "January"}'  ✅ Works
${node.stdout.iso}   → '2026-01-01'                                 ✅ Should work
```

---

## Steps to Reproduce

### Test Workflow

Save as `/tmp/test-json-nested-access.json`:

```json
{
  "nodes": [
    {
      "id": "output-json",
      "type": "shell",
      "params": {
        "command": "echo '{\"iso\": \"2026-01-01\", \"month_year\": \"January 2026\"}'"
      }
    },
    {
      "id": "test-nested",
      "type": "shell",
      "params": {
        "command": "echo 'iso value: ${output-json.stdout.iso}'"
      }
    }
  ],
  "edges": [
    {"from": "output-json", "to": "test-nested"}
  ]
}
```

### Run Command

```bash
uv run pflow /tmp/test-json-nested-access.json
```

### Actual Output

```
❌ Workflow execution failed

Error 1 at node 'test-nested':
  Category: exception
  Message: Unresolved variables in parameter 'command': ${output-json.stdout.iso}

Available context keys:
  • output-json (dict)

💡 Suggestions:
  Did you mean '${output-json}'? (instead of '${output-json.stdout.iso}')
```

### Expected Output

```
✓ Workflow completed
iso value: 2026-01-01
```

---

## Technical Analysis

### Why This Happens

1. Shell node stores output as:
   ```python
   {
     "stdout": '{"iso": "2026-01-01", "month_year": "January 2026"}\n',
     "stderr": "",
     "exit_code": 0,
     ...
   }
   ```

2. Template resolver accesses `stdout` → returns the **string** `'{"iso": ...}'`

3. Resolver then tries to access `.iso` on the string → fails because strings don't have `.iso` attribute

4. The existing auto-parsing feature (documented in agent instructions) only applies when the **target parameter** expects a dict/list type, not during **source traversal**.

### Current Auto-Parsing Scope

From `cli-agent-instructions.md`:
> ✅ **Auto-parsed**: Simple templates like `${node.output}` when target expects dict/list

This means:
```json
// Target expects dict → auto-parses JSON string
{"body": "${shell.stdout}"}  // JSON string → parsed dict ✅

// Nested source access → no auto-parsing
{"command": "echo ${shell.stdout.field}"}  // Fails ❌
```

### Relevant Code Location

The template resolution logic is in:
- `src/pflow/runtime/template_resolver.py`

The path traversal happens in the resolver, likely in a method that walks the dot-separated path. The fix would add JSON parsing when:
1. Current value is a string
2. String looks like JSON (starts with `{` or `[`)
3. Next path segment exists (we're not at the end)

---

## Proposed Solution

### Option A: Auto-Parse During Path Traversal (Recommended)

When traversing a template path like `node.stdout.iso`:

```python
def resolve_path(value, remaining_path):
    if not remaining_path:
        return value

    next_key = remaining_path[0]
    rest = remaining_path[1:]

    # NEW: Auto-parse JSON strings when accessing nested properties
    if isinstance(value, str) and remaining_path:
        parsed = try_parse_json(value)
        if parsed is not None:
            value = parsed

    if isinstance(value, dict):
        return resolve_path(value.get(next_key), rest)
    # ... rest of resolution
```

**Pros**:
- Intuitive behavior matching user expectations
- No workflow changes needed
- Works seamlessly with shell+jq patterns

**Cons**:
- Implicit behavior might be surprising in edge cases
- Performance overhead for JSON parsing attempts
- Could mask errors if user didn't intend JSON parsing

### Option B: Explicit JSON Parse Function

Add a template function for explicit parsing:

```
${json(node.stdout).iso}
```

**Pros**:
- Explicit, no surprises
- Clear intent in workflow

**Cons**:
- More verbose
- Requires user knowledge of the function

### Option C: New Output Type for Shell Nodes

Add `stdout_json` output that auto-parses:

```
${node.stdout}      → raw string
${node.stdout_json} → parsed object (if valid JSON)
${node.stdout_json.iso} → nested access works
```

**Pros**:
- Backward compatible
- Clear distinction between raw and parsed

**Cons**:
- More outputs to document
- Doesn't solve the general case for other node types

---

## Recommendation

**Option A** is recommended because:

1. **Matches existing auto-parsing precedent** - pflow already auto-parses JSON when target expects dict/list
2. **Follows principle of least surprise** - if `stdout` contains `{"iso": "..."}`, users naturally expect `.iso` to work
3. **Reduces workflow complexity** - eliminates need for intermediate jq extraction nodes
4. **Shell+jq is a core pattern** - this enhancement directly supports the documented "shell for structured data" approach

### Safeguards for Option A

1. Only attempt parse when next path segment exists (not at end of path)
2. Only parse if string starts with `{` or `[` (quick check before full parse)
3. On parse failure, continue with string value (graceful fallback)
4. Add debug logging for parse attempts in verbose mode

---

## Impact Assessment

### Workflows That Would Benefit

1. **Shell nodes outputting JSON** (most common case)
   ```json
   {"command": "curl -s https://api.example.com/data"}
   // Then: ${curl-node.stdout.results[0].id}
   ```

2. **jq producing structured output**
   ```json
   {"command": "echo '$data' | jq '{iso: .date, label: .formatted}'"}
   // Then: ${jq-node.stdout.iso}
   ```

3. **Any node producing JSON strings**
   - HTTP response bodies stored as strings
   - LLM responses containing JSON

### Backward Compatibility

- **Fully backward compatible** - existing workflows don't access `.field` on strings
- No breaking changes - only enables previously-failing patterns

---

## Test Cases

### Case 1: Basic Nested Access
```json
{"command": "echo '{\"a\": 1}'"}
// ${node.stdout.a} → 1
```

### Case 2: Deep Nesting
```json
{"command": "echo '{\"a\": {\"b\": {\"c\": 3}}}'"}
// ${node.stdout.a.b.c} → 3
```

### Case 3: Array Access
```json
{"command": "echo '[{\"id\": 1}, {\"id\": 2}]'"}
// ${node.stdout[0].id} → 1
```

### Case 4: Invalid JSON (Graceful Fallback)
```json
{"command": "echo 'not json'"}
// ${node.stdout.field} → Unresolved variable error (unchanged behavior)
```

### Case 5: Non-JSON String Starting with Brace
```json
{"command": "echo '{partial json'"}
// ${node.stdout.field} → Unresolved variable error (parse fails, fallback)
```

### Case 6: Null/Empty Handling
```json
{"command": "echo 'null'"}
// ${node.stdout.field} → Unresolved (null has no .field)
```

---

## Workaround (Current)

Until this feature is implemented, users must use separate nodes:

```json
// Instead of one node with JSON output:
{
  "id": "get-dates",
  "type": "shell",
  "params": {"command": "echo '{\"iso\": \"'$(date +%Y-%m-%d)'\", \"month\": \"'$(date +\"%B %Y\")'\"}'" }
}
// ❌ ${get-dates.stdout.iso} fails

// Use separate nodes:
{
  "id": "get-date-iso",
  "type": "shell",
  "params": {"command": "date +%Y-%m-%d"}
},
{
  "id": "get-date-month",
  "type": "shell",
  "params": {"command": "date +\"%B %Y\""}
}
// ✅ ${get-date-iso.stdout} and ${get-date-month.stdout} work
```

---

## Related

- Agent instructions mention auto-parsing for target parameters: `cli-agent-instructions.md` line ~884
- Template resolver: `src/pflow/runtime/template_resolver.py`
- Existing auto-parsing logic for simple templates

---

## Acceptance Criteria

- [ ] `${node.stdout.field}` resolves when `stdout` is valid JSON object string
- [ ] `${node.stdout[0]}` resolves when `stdout` is valid JSON array string
- [ ] Invalid JSON strings fail gracefully with clear error message
- [ ] Deep nesting works: `${node.stdout.a.b.c}`
- [ ] Mixed access works: `${node.stdout.items[0].name}`
- [ ] No performance regression for non-JSON string values
- [ ] Backward compatible with existing workflows
- [ ] Debug logging in verbose mode shows parse attempts
