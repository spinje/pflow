# Bug Report: Optional Inputs Without Defaults Fail Template Resolution

## Summary

When a workflow input is declared with `required: false` but no `default` value, and the user doesn't provide a value, any template referencing that input fails with "Unresolved variables".

Expected behavior: Optional inputs should resolve to `null` or empty string when not provided.

## Problem Statement

Users declare optional inputs to allow flexible workflow usage. However, if they reference an optional input in a template and the user doesn't provide a value, the workflow fails - defeating the purpose of making it optional.

### Current Behavior

```json
{
  "inputs": {
    "optional_param": {"type": "string", "required": false}
  },
  "nodes": [{
    "id": "test",
    "type": "shell",
    "params": {
      "stdin": "${optional_param}",
      "command": "cat"
    }
  }]
}
```

Running without the optional param:
```
$ pflow workflow.json

❌ Workflow execution failed
Error: Unresolved variables in parameter 'stdin': ${optional_param}
```

### Expected Behavior

The workflow should succeed with `${optional_param}` resolving to `null` or empty string:

```
$ pflow workflow.json
✓ Workflow completed
(empty output)
```

## Steps to Reproduce

### Test 1: Optional input without default (FAILS)

```json
{
  "inputs": {
    "optional_name": {"type": "string", "required": false}
  },
  "nodes": [{
    "id": "greet",
    "type": "shell",
    "params": {"stdin": "${optional_name}", "command": "cat"}
  }],
  "edges": []
}
```

```bash
pflow test.json  # No value provided
# Result: FAILS with "Unresolved variables"
```

### Test 2: Optional input WITH default (WORKS)

```json
{
  "inputs": {
    "optional_name": {"type": "string", "required": false, "default": "World"}
  },
  "nodes": [{
    "id": "greet",
    "type": "shell",
    "params": {"stdin": "${optional_name}", "command": "cat"}
  }],
  "edges": []
}
```

```bash
pflow test.json  # No value provided
# Result: WORKS, outputs "World"
```

### Test 3: Mixed templates - misleading error (FAILS)

```json
{
  "inputs": {
    "provided": {"type": "string", "required": true},
    "missing": {"type": "string", "required": false}
  },
  "nodes": [{
    "id": "test",
    "type": "shell",
    "params": {
      "stdin": {"a": "${provided}", "b": "${missing}"},
      "command": "jq ."
    }
  }],
  "edges": []
}
```

```bash
pflow test.json provided="hello"
```

**Actual error:**
```
Error: Unresolved variables in parameter 'stdin': ${provided}, ${missing}

Available context keys:
  • provided (str): hello
```

**Issue:** Error says `${provided}` is unresolved, but it's clearly in context. The error should only list `${missing}`.

## Root Cause Analysis

1. Optional inputs without defaults are **not added to the context** at all
2. Template resolution **fails on first unresolvable variable**
3. Error reporting **lists all templates** in the parameter as unresolved, not just the problematic ones

## Impact

- **Workaround tax:** Users must always provide `default` for optional inputs, even when empty string isn't semantically correct
- **Confusing errors:** Error message suggests ALL templates failed, even ones with valid values
- **Design limitation:** Can't distinguish between "user provided empty string" vs "user didn't provide value"

## Proposed Solutions

### Option A: Resolve missing optional inputs to null (Recommended)

When an optional input has no default and no value is provided:
- Add it to context with value `null`
- Templates like `${optional_param}` resolve to `null` (or empty string in string contexts)

**Pros:** Most intuitive behavior, matches how optional parameters work in most languages
**Cons:** Might break workflows that rely on current "fail if missing" behavior

### Option B: Resolve to empty string

Similar to Option A but use empty string `""` instead of `null`.

**Pros:** Simpler, no null handling needed
**Cons:** Can't distinguish between "not provided" and "provided empty"

### Option C: Add explicit null syntax

Allow workflows to handle missing values explicitly:
```json
"stdin": "${optional_param ?? 'default_value'}"
```

**Pros:** Maximum flexibility
**Cons:** More complex, changes template syntax

## Secondary Issue: Misleading Error Message

When multiple templates exist and ONE is unresolvable, the error lists ALL as unresolved:

```
Error: Unresolved variables in parameter 'stdin': ${provided}, ${missing}
```

Should only list actually unresolvable ones:
```
Error: Unresolved variables in parameter 'stdin': ${missing}
```

This is lower priority but would help debugging.

## Test Cases

See `test-cases/` directory for reproduction workflows.

## Environment

- pflow version: (current)
- OS: macOS (Darwin 24.6.0)
- Date discovered: 2026-01-08
