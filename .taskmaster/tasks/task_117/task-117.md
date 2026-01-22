# Task 117: Unify JSON Error Structures

## Description

Unify the two different JSON error structures (validation errors vs runtime errors) into one consistent format. Currently, pflow outputs different JSON structures depending on when an error occurs, which complicates programmatic consumption.

## Status

not started

## Priority

low

## Problem

pflow has **two different JSON error structures**:

**Validation errors** (early, before execution):
```json
{
  "success": false,
  "error": "Workflow validation failed",
  "validation_errors": ["..."],
  "metadata": {"action": "unsaved", "name": "..."}
}
```

**Runtime errors** (during execution):
```json
{
  "success": false,
  "status": "failed",
  "error": "Workflow execution failed",
  "is_error": true,
  "errors": [
    {
      "source": "runtime",
      "category": "execution_failure",
      "message": "...",
      "node_id": "...",
      "fixable": true
    }
  ],
  "failed_node": "...",
  "execution": {...},
  "duration_ms": ...,
  "metrics": {...}
}
```

This inconsistency means:
- Consumers must handle two different structures
- Field names differ (`validation_errors` vs `errors`, `metadata` vs `workflow`)
- Some fields only exist in one structure (`status`, `is_error`, `execution`, `metrics`)

## Solution

Design and implement a unified JSON error structure that works for all error types:

```json
{
  "success": false,
  "error": "Human readable summary",
  "errors": [
    {
      "source": "validation" | "runtime" | "cli",
      "category": "stdin_routing" | "template_error" | "execution_failure" | "...",
      "message": "Detailed error message",
      "suggestion": "How to fix (optional)"
    }
  ],
  "workflow": {"name": "...", "action": "unsaved" | "reused" | "created"},

  // Optional fields (null/omitted for validation errors)
  "duration_ms": null,
  "metrics": null,
  "execution": null
}
```

## Design Considerations

### What stays the same
- `success: false` for all errors
- Exit code 1 for all errors
- JSON to stdout, text to stderr

### What changes
- `validation_errors` array → unified `errors` array
- `metadata` → `workflow` (consistent naming)
- All errors use same `errors` array structure with `source` field to distinguish type

### Open questions
- Should optional fields be `null` or omitted entirely?
- Should we version the JSON output format?
- How to handle backward compatibility (if any consumers exist)?

## Dependencies

- Task 115: Automatic Stdin Routing — Adds stdin routing error (uses current validation pattern)

## Implementation Notes

### Files to modify

- `src/pflow/cli/main.py` — Multiple error output locations
  - `_create_json_error_output()` — Runtime error helper
  - Lines 2099-2113 — Validation error pattern
  - `_show_stdin_routing_error()` — Stdin routing error
  - ~19 other `ctx.exit(1)` sites

### Approach

1. Define the unified structure in a central location (maybe a formatter)
2. Create helper function for building error JSON
3. Migrate all error sites to use the unified structure
4. Update tests to expect new structure
5. Update any documentation

### Current error locations

Search for `ctx.exit(1)` in main.py to find all early error sites (~19).
Search for `"success": False` to find all JSON error constructions.

## Verification

```bash
# All these should output the SAME JSON structure:

# Validation error (stdin routing)
echo "data" | uv run pflow --output-format json workflow-no-stdin.json

# Validation error (missing input)
uv run pflow --output-format json workflow.json

# Runtime error (node failure)
uv run pflow --output-format json failing-workflow.json

# All should have: success, error, errors[], workflow
# Runtime errors additionally have: duration_ms, metrics, execution
```

## Acceptance Criteria

- Single JSON error structure for all error types
- `errors` array with `source` field distinguishes validation vs runtime
- All existing error information preserved (just restructured)
- `make check` and `make test` pass
- Documentation updated if any exists for JSON output format
