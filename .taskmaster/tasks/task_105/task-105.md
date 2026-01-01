# Task 105: Auto-Parse JSON Strings During Nested Template Access

## Status: ✅ Completed

## Problem Statement

When a node output contains a JSON string (e.g., `stdout` from a shell command), nested template access like `${node.stdout.field}` fails because the intermediate value is a string, not a parsed object.

### Current Behavior
```
${node.stdout}       → '{"iso": "2026-01-01", "month": "January"}'  ✅ Works
${node.stdout.iso}   → Unresolved variable error                    ❌ Fails
```

### Expected Behavior
```
${node.stdout}       → '{"iso": "2026-01-01", "month": "January"}'  ✅ Works
${node.stdout.iso}   → '2026-01-01'                                 ✅ Should work
```

### Use Case

Shell commands with `jq`, `curl`, or other tools frequently output JSON. Users expect to access fields directly:

```yaml
- id: api-call
  type: shell
  params:
    command: "curl -s https://api.example.com/data"

- id: use-result
  type: shell
  params:
    command: "echo 'Status: ${api-call.stdout.status}'"  # Should work
```

## Solution Implemented

**Auto-parse JSON strings during path traversal** in the template resolver.

### Key Design Decisions

1. **Parse only when traversing deeper** - `${node.stdout}` returns raw string, `${node.stdout.field}` triggers parsing
2. **Shared JSON utility** - Created `src/pflow/core/json_utils.py` to consolidate 7 duplicate implementations
3. **Two-value return** - `(success, result)` distinguishes "parsed to None" from "failed to parse"
4. **Validator coordination** - Relaxed compile-time validator to allow `str` nested access with warning

### Files Changed

**New Files:**
- `src/pflow/core/json_utils.py` - Shared JSON parsing utility
- `tests/test_core/test_json_utils.py` - Utility tests
- `tests/test_runtime/test_template_resolver_json_parsing.py` - Feature tests
- `tests/test_integration/test_json_nested_access_e2e.py` - E2E tests

**Modified Files:**
- `src/pflow/runtime/template_resolver.py` - Core feature implementation
- `src/pflow/runtime/template_validator.py` - Allow `str` nested access with warning
- `src/pflow/runtime/node_wrapper.py` - Use shared utility
- `src/pflow/runtime/batch_node.py` - Use shared utility
- `src/pflow/cli/main.py` - Use shared utility
- `src/pflow/execution/formatters/success_formatter.py` - Use shared utility
- `src/pflow/execution/formatters/node_output_formatter.py` - Use shared utility

## Acceptance Criteria

- [x] `${node.stdout.field}` resolves when stdout is valid JSON object
- [x] `${node.stdout[0]}` resolves when stdout is valid JSON array
- [x] Invalid JSON fails gracefully with clear error message
- [x] Deep nesting works: `${node.stdout.a.b.c}`
- [x] Mixed access works: `${node.stdout.items[0].name}`
- [x] No performance regression
- [x] Backward compatible with existing workflows
- [x] Debug logging shows parse attempts

## Key Insights

### Two-System Coordination
This feature required coordinating compile-time validation and runtime resolution:
- **Validator** sees `stdout: str` → must allow nested access (with warning)
- **Resolver** sees `stdout = '{"field": "value"}'` → parses JSON at runtime

### Warning Behavior by Type
| Type | Nested Access | Warning | Rationale |
|------|--------------|---------|-----------|
| `dict` | ✅ Allowed | No | Trusted structured data |
| `any` | ✅ Allowed | No | Explicit declaration by node author |
| `str` | ✅ Allowed | **Yes** | JSON auto-parsing is implicit |

### Test Quality Principle
Removed 6 low-value tests, added 1 high-value test. Key insight: test behavior, not implementation details.

## Related

- Feature request: `scratchpads/feature-request-json-string-nested-access.md`
- Implementation plan: `.taskmaster/tasks/task_105/implementation/implementation-plan.md`
- Progress log: `.taskmaster/tasks/task_105/implementation/progress-log.md`
