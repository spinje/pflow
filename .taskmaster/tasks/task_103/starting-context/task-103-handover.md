# Task 103 Handoff Memo: Preserve Type for Simple Templates in Dict/List Values

## The Core Problem I Discovered

I tested this exact scenario live and saw the double-serialization bug:

```python
# Input
"stdin": {"config": "${config}", "data": "${data}"}
# Where config = {"name": "MyApp"} and data = {"value": "Hello"}

# ACTUAL output (broken):
{"config": "{\"name\": \"MyApp\"}", "data": "{\"value\": \"Hello\"}"}

# DESIRED output:
{"config": {"name": "MyApp"}, "data": {"value": "Hello"}}
```

The inner dicts are being serialized to JSON strings, then the outer dict serializes again. Double encoding.

## Why This Happens - The Root Cause

The template resolver has two paths:

1. **Simple templates** like `stdin: "${data}"` - These ALREADY preserve type correctly. The `_resolve_simple_template()` method in `node_wrapper.py:525-559` detects when the entire value is just `${var}` and preserves the resolved type.

2. **Dict/list values** like `{"key": "${var}"}` - Each value is treated as a string template. When the resolver sees `"${config}"` as a string, it calls `_to_string()` which serializes dicts to JSON (see `template_resolver.py:275-282`).

The key insight: **The simple template detection logic exists but isn't applied when processing dict/list VALUES.**

## The Pattern to Follow

Look at `node_wrapper.py:525-559` - the `_resolve_simple_template()` method:

```python
def _resolve_simple_template(self, template: str, context: dict[str, Any]) -> tuple[Any, bool]:
    """Resolve a simple template variable like '${var}'."""
    simple_var_match = re.match(r"^\$\{([^}]+)\}$", template)
    if not simple_var_match:
        return None, False

    var_name = simple_var_match.group(1)

    if TemplateResolver.variable_exists(var_name, context):
        resolved_value = TemplateResolver.resolve_value(var_name, context)
        return resolved_value, True  # Returns actual value, not string!
```

The regex `r"^\$\{([^}]+)\}$"` detects if the ENTIRE string is just a template reference. When true, it returns the actual resolved value (dict, list, int, whatever) instead of serializing.

## Where the Fix Should Go

Two options I see:

**Option A: Modify `template_resolver.py`**

In `resolve_string()` or `_to_string()`, add logic to detect simple templates when resolving dict/list values. Before calling `_to_string()` on a value, check if it's a simple template and resolve it directly.

**Option B: Add a new method for dict/list resolution**

Create a `resolve_structure()` method that recursively resolves templates in dict/list structures, preserving types for simple templates.

I lean toward Option B because it's cleaner and doesn't risk breaking existing string resolution behavior.

## Critical Edge Cases

1. **Mixed templates SHOULD serialize**: `{"key": "prefix ${var} suffix"}` → the value should be a string, not preserve the inner type.

2. **Recursion is required**: `{"outer": {"inner": "${data}"}}` - nested structures need the same treatment.

3. **Arrays too**: `["${a}", "${b}"]` - each element should preserve type if it's a simple template.

4. **Non-template values unchanged**: `{"key": "literal string", "num": 42}` - these should pass through unchanged.

## Files You Need to Read

| File | What to Look At |
|------|-----------------|
| `src/pflow/runtime/template_resolver.py:260-285` | The `_to_string()` method that does dict/list → JSON serialization |
| `src/pflow/runtime/template_resolver.py:286-340` | The `resolve_string()` method that orchestrates resolution |
| `src/pflow/runtime/node_wrapper.py:525-559` | The `_resolve_simple_template()` pattern to replicate |
| `src/pflow/nodes/shell/shell.py:348-392` | `_adapt_stdin_to_string()` - shows correct final serialization for stdin |

## The Serialization Chain (Important!)

Understand this flow:

1. IR has: `"stdin": {"config": "${config}"}`
2. Template resolver processes the dict value `"${config}"`
3. Currently: `"${config}"` → resolves to dict → `_to_string()` → JSON string
4. **Should be**: `"${config}"` → detect simple template → preserve dict
5. Then `_adapt_stdin_to_string()` in shell node serializes the FINAL dict to JSON for subprocess

The shell node's `_adapt_stdin_to_string()` is CORRECT. The problem is step 3 happening too early.

## What NOT to Do

1. **Don't modify `_adapt_stdin_to_string()`** - it's working correctly
2. **Don't globally disable dict→string serialization** - it's needed for embedded templates
3. **Don't forget to handle the recursive case** - nested structures need processing

## Test the Fix With This Command

I used this exact test to verify the bug:

```python
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry.registry import Registry

workflow_ir = {
    'inputs': {
        'config': {'type': 'object', 'required': True},
        'data': {'type': 'object', 'required': True}
    },
    'nodes': [{
        'id': 'process',
        'type': 'shell',
        'params': {
            'stdin': {'config': '${config}', 'data': '${data}'},
            'command': 'cat'  # Echo stdin to see what we get
        }
    }],
    'edges': [],
    'outputs': {}
}

registry = Registry()
flow = compile_ir_to_flow(
    workflow_ir,
    registry=registry,
    initial_params={
        'config': {'name': 'MyApp'},
        'data': {'value': 'Hello'}
    },
    validate=True
)

shared = {}
flow.run(shared)
print('stdout:', shared.get('process', {}).get('stdout', ''))
# Should print: {"config": {"name": "MyApp"}, "data": {"value": "Hello"}}
# Currently prints: {"config": "{\"name\": \"MyApp\"}", ...} (double-encoded)
```

## Context From the User

The user specifically validated that the inline object pattern is the right solution for the multi-input problem. They asked "would this be intuitive and a good solution?" and I confirmed it is elegant because:

- It's explicit - keys are visible in the IR
- It's flexible - any JSON structure works
- It leverages existing template system
- It's consistent with how `stdin: "${data}"` already works

This feature benefits ALL nodes, not just shell. Any node that accepts structured params can use this pattern.

## Why This Matters

Without this fix, users with multiple data sources must use temp files:

```json
{"id": "save-a", "type": "write-file", "params": {"path": "/tmp/a.json", "content": "${data-a}"}},
{"id": "save-b", "type": "write-file", "params": {"path": "/tmp/b.json", "content": "${data-b}"}},
{"id": "process", "type": "shell", "params": {"command": "jq -s '.[0] * .[1]' /tmp/a.json /tmp/b.json"}}
```

With the fix, it's just:

```json
{"id": "process", "type": "shell", "params": {
  "stdin": {"a": "${data-a}", "b": "${data-b}"},
  "command": "jq '.a + .b'"
}}
```

---

## Before You Begin

**DO NOT start implementing yet.** Read the task file at `.taskmaster/tasks/task_103/task-103.md`, review the files mentioned above, and confirm you understand:

1. The double-serialization bug
2. Why simple templates preserve type but dict/list values don't
3. The `_resolve_simple_template()` pattern to follow

When ready, respond with "Ready to implement Task 103."
