# Template Variable Type Mismatch in String Contexts

**Date**: 2025-12-29
**Status**: Design Issue - Needs Decision
**Severity**: Medium (usability friction, workarounds exist)
**Reporter**: Claude (during workflow development session)

## Executive Summary

When building a workflow that processes images with vision AI, we encountered a fundamental design limitation: **arrays cannot be embedded in shell command strings**. This is by design (type safety), but creates significant friction for common real-world patterns where multiple data sources need to be combined in a single shell command.

## Problem Statement

### The Error

```
Type mismatch in node 'build-description-map' parameter 'command':
template ${describe-images.results} has type 'array' but parameter expects 'str'
```

### Root Cause

pflow's template system correctly validates types. When a template variable resolves to an array but the target parameter expects a string, validation fails. This is intentional - it prevents silent type coercion bugs.

However, this creates a usability gap when users need to:
1. Pass multiple arrays/objects to a shell command
2. Embed structured data directly in command strings

## Reproduction Steps

### Minimal Reproduction

Create this workflow file:

```json
{
  "inputs": {
    "items": {
      "type": "array",
      "required": true
    }
  },
  "nodes": [
    {
      "id": "process",
      "type": "shell",
      "params": {
        "command": "echo '${items}' | jq '.'"
      }
    }
  ],
  "edges": [],
  "outputs": {}
}
```

Run validation:
```bash
uv run pflow --validate-only minimal-test.json
```

**Expected by user**: The array serializes to JSON and echoes
**Actual result**: Validation error - type mismatch

### Real-World Scenario That Triggered This

We were building a webpage-to-markdown workflow with optional image descriptions. The workflow:

1. Downloads images → outputs array of `{original_url, local_path, filename}`
2. Describes images with vision LLM (batch) → outputs array of `{response, llm_usage}`
3. Needs to combine both arrays to build a mapping of filename → description

The problematic node:

```json
{
  "id": "build-description-map",
  "type": "shell",
  "params": {
    "command": "images='${prepare-vision-list.stdout}'; descriptions='${describe-images.results}'; python3 -c \"import json; imgs=json.loads('$images'); descs=json.loads('$descriptions'); ...\""
  }
}
```

This fails because `${describe-images.results}` is an array.

## Current Design Analysis

### How Templates Work Now

1. Template variables like `${node.output}` are resolved at runtime
2. The resolved value retains its type (string, number, array, object, etc.)
3. Type validation compares resolved type against parameter schema
4. Mismatches cause validation errors

### The stdin Pattern

The current workaround is to use `stdin` for passing structured data:

```json
{
  "id": "process",
  "type": "shell",
  "params": {
    "stdin": "${some-array}",
    "command": "jq '.[] | .field'"
  }
}
```

**Limitation**: Only ONE value can be passed via stdin. If you need multiple arrays/objects, you're stuck.

### Relevant Code Locations

- Template resolution: `src/pflow/runtime/template_resolver.py`
- Template validation: `src/pflow/runtime/template_validator.py`
- Shell node implementation: `src/pflow/nodes/shell/`

## Solution Options

### Option 1: Auto-Serialize Arrays/Objects in String Context

**Description**: When a template variable resolves to an array or object AND the target parameter expects a string, automatically JSON-serialize the value.

**Implementation**:
```python
# In template_resolver.py
def resolve_for_string_context(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)
```

**Example**:
```json
// User writes:
{"command": "echo '${array_var}' | jq '.'"}

// After resolution:
{"command": "echo '[\"a\",\"b\",\"c\"]' | jq '.'"}
```

**Pros**:
- Most intuitive for users - matches expectations
- JSON is the universal data interchange format
- Backwards compatible (strings stay strings)
- Enables common patterns naturally

**Cons**:
- "Magic" behavior - implicit type coercion
- Quote escaping complexity (nested quotes in JSON within shell)
- Could mask errors where user didn't intend array usage
- Behavior differs from strict typing elsewhere in pflow

**Complexity**: Medium
**Breaking Changes**: None (currently fails, so any behavior is new)

---

### Option 2: Explicit Serialization Function

**Description**: Add a template function syntax for explicit serialization.

**Implementation**:
```json
{"command": "echo '${json(array_var)}' | jq '.'"}
{"command": "echo '${csv(array_var)}' | ..."}
```

**Pros**:
- Explicit - no magic
- Supports multiple serialization formats
- Clear user intent

**Cons**:
- New syntax to learn
- More verbose
- Requires template parser changes

**Complexity**: Medium-High
**Breaking Changes**: None

---

### Option 3: Environment Variables Parameter

**Description**: Add an `env` parameter to shell nodes for passing multiple values.

**Implementation**:
```json
{
  "id": "process",
  "type": "shell",
  "params": {
    "env": {
      "IMAGES": "${image_list}",
      "DESCRIPTIONS": "${descriptions}"
    },
    "command": "python3 -c 'import os, json; imgs=json.loads(os.environ[\"IMAGES\"]); ...'"
  }
}
```

**Pros**:
- Shell-native pattern (environment variables are standard)
- Explicit about what data is passed
- No changes to template resolution
- Can pass unlimited number of values

**Cons**:
- More verbose
- Environment variable size limits on some systems
- Requires shell node schema changes

**Complexity**: Low-Medium
**Breaking Changes**: None (additive)

---

### Option 4: Multiple stdin Parameters

**Description**: Allow multiple named stdin-like parameters.

**Implementation**:
```json
{
  "params": {
    "stdin": "${primary_data}",
    "stdin_images": "${image_list}",
    "stdin_descriptions": "${descriptions}",
    "command": "..."
  }
}
```

**Pros**:
- Clear data flow
- Maintains stdin pattern

**Cons**:
- How to access multiple stdins in shell? (Named pipes? Temp files?)
- Significant complexity
- Not a standard shell pattern

**Complexity**: High
**Breaking Changes**: None

---

### Option 5: Preprocessing Node Pattern (Current Workaround)

**Description**: Document the pattern of using intermediate nodes to combine data.

**Implementation**:
```json
{
  "id": "combine-data",
  "type": "shell",
  "params": {
    "stdin": "${image_list}",
    "command": "jq --argjson descs '${descriptions}' '{images: ., descriptions: $descs}'"
  }
},
{
  "id": "process-combined",
  "type": "shell",
  "params": {
    "stdin": "${combine-data.stdout}",
    "command": "jq '...'"
  }
}
```

Wait - this still has the same problem! `${descriptions}` in the command string is still an array.

**Actual workaround**: Use file-based passing or restructure workflow to avoid needing multiple arrays.

**Pros**:
- No code changes needed
- Works today

**Cons**:
- Very awkward
- Requires extra nodes
- Not intuitive
- May not even work depending on the data shapes

**Complexity**: N/A (workaround)
**Breaking Changes**: N/A

---

### Option 6: LLM Node for Complex Transformations

**Description**: Use the LLM node instead of shell for complex data transformations.

**Implementation**:
```json
{
  "id": "build-map",
  "type": "llm",
  "params": {
    "prompt": "Given these images: ${image_list}\n\nAnd these descriptions: ${descriptions}\n\nCreate a JSON mapping of filename to description.",
    "temperature": 0
  }
}
```

**Pros**:
- Works today
- LLM handles arbitrary data shapes

**Cons**:
- Expensive (API costs for simple transformation)
- Slower
- Non-deterministic
- Overkill for structured data manipulation

**Complexity**: N/A (workaround)
**Breaking Changes**: N/A

## Recommendation

**Primary Recommendation: Option 1 (Auto-Serialize) + Option 3 (Env Vars)**

Implement both:

1. **Auto-serialize arrays/objects to JSON in string contexts** - This matches user expectations and enables natural patterns. The "magic" is acceptable because:
   - JSON is the standard format
   - The alternative (current behavior) is a hard error, so any behavior is an improvement
   - Users explicitly wrote `${array}` in a string, so they expect it to work

2. **Add `env` parameter to shell nodes** - For cases where users need explicit control or multiple large data structures.

**Implementation Priority**:
1. Option 1 first (higher impact, solves most cases)
2. Option 3 second (cleaner pattern for complex cases)

## Testing Considerations

If implementing Option 1:

1. **Quote escaping**: Test JSON with quotes, newlines, special chars
2. **Nested structures**: Deep objects, arrays of objects
3. **Large data**: Memory/performance with large arrays
4. **Empty values**: Empty arrays `[]`, empty objects `{}`
5. **Null handling**: How to serialize `null`
6. **Unicode**: Non-ASCII characters in strings

## Migration Impact

- **Breaking changes**: None (currently errors, any new behavior is additive)
- **Documentation**: Update template variable docs
- **Examples**: Update shell node examples to show array usage

## Files to Modify (for Option 1)

1. `src/pflow/runtime/template_resolver.py` - Add serialization logic
2. `src/pflow/runtime/template_validator.py` - Update validation to allow array→string
3. `tests/test_runtime/test_template_resolver.py` - Add test cases
4. `architecture/core-concepts/templates.md` - Document behavior

## Open Questions

1. Should serialization be JSON only, or support other formats?
2. Should there be a way to opt-out of auto-serialization?
3. How to handle serialization errors (circular references, non-serializable types)?
4. Should this apply to all string contexts or only shell commands?

## Appendix: Full Workflow That Triggered This

See: `examples/real-workflows/webpage-to-markdown-with-images.json`

The workflow converts webpages to markdown with optional AI-generated image descriptions. The issue occurs when trying to build a mapping between downloaded image paths and their vision-generated descriptions.
