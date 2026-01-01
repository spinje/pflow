# Implementation Plan: Auto-Parse JSON Strings During Nested Template Access

**Feature Branch**: `feat/auto-parse-json`
**Date**: 2026-01-01
**Status**: Ready for Implementation

---

## Executive Summary

Enable `${node.stdout.field}` to work when `stdout` contains a JSON string like `'{"field": "value"}'`. Currently, path traversal fails because the resolver treats JSON strings as opaque strings. This feature adds automatic JSON parsing during path traversal.

**Key Constraint**: Changes to `resolve_value()` and `_traverse_path_part()` MUST stay in sync to maintain validation/resolution consistency.

---

## Implementation Phases

### Phase 1: Foundation - Shared JSON Utility
**Goal**: Create a single, well-tested JSON parsing utility to replace 7 duplicates

### Phase 2: Core Feature - Template Resolver Enhancement
**Goal**: Enable JSON parsing during path traversal

### Phase 3: Consolidation - Replace Duplicates
**Goal**: Reduce technical debt by using the new utility everywhere

### Phase 4: Verification & Documentation
**Goal**: End-to-end testing and documentation updates

---

## Phase 1: Shared JSON Utility

### 1.1 Create `src/pflow/core/json_utils.py`

**File**: `src/pflow/core/json_utils.py`

```python
"""JSON parsing utilities for pflow.

Provides safe, consistent JSON parsing across the codebase with:
- Quick rejection for non-JSON strings (performance)
- Size limits to prevent memory exhaustion (security)
- Graceful fallback for invalid JSON
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Security: Prevent memory exhaustion from maliciously large JSON
DEFAULT_MAX_JSON_SIZE = 10 * 1024 * 1024  # 10MB


def try_parse_json(
    value: str,
    *,
    max_size: int = DEFAULT_MAX_JSON_SIZE,
    strip_whitespace: bool = True,
) -> tuple[bool, Any]:
    """Attempt to parse a string as JSON.

    Returns a tuple of (success, result) where:
    - (True, parsed_value) if parsing succeeded
    - (False, original_value) if parsing failed or was skipped

    This two-value return allows callers to distinguish between:
    - "Parsed successfully to None" vs "Failed to parse"
    - "Parsed successfully to False" vs "Failed to parse"

    Args:
        value: String that may contain JSON
        max_size: Maximum string size to attempt parsing (default 10MB)
        strip_whitespace: Whether to strip before checking (default True)

    Returns:
        Tuple of (success: bool, result: Any)

    Examples:
        >>> try_parse_json('{"a": 1}')
        (True, {'a': 1})
        >>> try_parse_json('not json')
        (False, 'not json')
        >>> try_parse_json('null')
        (True, None)
    """
    if not isinstance(value, str):
        return (False, value)

    text = value.strip() if strip_whitespace else value

    # Quick rejection: empty string
    if not text:
        return (False, value)

    # Security: size limit
    if len(text) > max_size:
        logger.warning(
            f"Skipping JSON parse: string exceeds size limit ({len(text)} > {max_size})",
        )
        return (False, value)

    # Quick rejection: doesn't look like JSON
    # JSON values can start with: { [ " t(rue) f(alse) n(ull) - or digit
    first_char = text[0]
    if first_char not in '{["tfn-0123456789':
        return (False, value)

    # Attempt parse
    try:
        parsed = json.loads(text)
        logger.debug(
            f"Successfully parsed JSON string to {type(parsed).__name__}",
            extra={"preview": text[:100] if len(text) > 100 else text},
        )
        return (True, parsed)
    except (json.JSONDecodeError, ValueError):
        logger.debug(
            f"String is not valid JSON, keeping as string",
            extra={"preview": text[:50] if len(text) > 50 else text},
        )
        return (False, value)


def parse_json_or_original(
    value: str,
    *,
    max_size: int = DEFAULT_MAX_JSON_SIZE,
) -> Any:
    """Parse JSON string or return original value unchanged.

    Convenience wrapper around try_parse_json() that returns just the result.
    Use try_parse_json() if you need to know whether parsing succeeded.

    Args:
        value: String that may contain JSON
        max_size: Maximum string size to attempt parsing

    Returns:
        Parsed JSON value or original string

    Examples:
        >>> parse_json_or_original('{"a": 1}')
        {'a': 1}
        >>> parse_json_or_original('hello')
        'hello'
    """
    success, result = try_parse_json(value, max_size=max_size)
    return result
```

### 1.2 Create Tests for JSON Utility

**File**: `tests/test_core/test_json_utils.py`

Test cases to implement:
1. **Valid JSON objects**: `'{"a": 1}'` → `{"a": 1}`
2. **Valid JSON arrays**: `'[1, 2, 3]'` → `[1, 2, 3]`
3. **Valid JSON primitives**: `'true'`, `'false'`, `'null'`, `'123'`, `'"string"'`
4. **Invalid JSON**: `'not json'` → returns original
5. **Partial JSON**: `'{"incomplete'` → returns original
6. **Whitespace handling**: `'  {"a": 1}\n'` → `{"a": 1}`
7. **Size limit enforcement**: Large string → skipped with warning
8. **Empty string**: `''` → returns original
9. **Non-string input**: `123` → returns original
10. **Unicode content**: `'{"emoji": "🎉"}'` → works correctly
11. **Nested JSON strings**: `'{"data": "{\"inner\": 1}"}'` → outer parsed only
12. **Null vs parse failure**: `'null'` → `(True, None)` vs `'invalid'` → `(False, 'invalid')`

### 1.3 Verification Criteria

- [ ] All tests pass
- [ ] `make check` passes (lint, types)
- [ ] No external dependencies added

---

## Phase 2: Core Feature - Template Resolver Enhancement

### 2.1 Add Import to Template Resolver

**File**: `src/pflow/runtime/template_resolver.py`

Add import at top:
```python
from pflow.core.json_utils import try_parse_json
```

### 2.2 Create Shared Helper Method

Add a private method that both `resolve_value()` and `_traverse_path_part()` can use:

```python
@staticmethod
def _try_parse_json_for_traversal(value: Any) -> Any:
    """Attempt to parse a string value as JSON for path traversal.

    Called when we need to access a property on a value that is a string.
    If the string is valid JSON object/array, returns the parsed value.
    Otherwise returns the original value unchanged.

    This enables patterns like ${node.stdout.field} when stdout
    contains a JSON string like '{"field": "value"}'.

    Args:
        value: Current value in path traversal (may be string or other type)

    Returns:
        Parsed JSON if value was a JSON string, otherwise original value
    """
    if not isinstance(value, str):
        return value

    success, parsed = try_parse_json(value)
    if success and isinstance(parsed, (dict, list)):
        # Only use parsed result if it's a container we can traverse
        return parsed
    return value
```

### 2.3 Update `resolve_value()` Method

**Location**: Lines 279-288

**Current code**:
```python
else:
    # Regular property access
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        logger.debug(
            f"Cannot resolve path '{var_name}': '{part}' not found or parent not a dict",
            extra={"var_name": var_name, "failed_at": part},
        )
        return None
```

**New code**:
```python
else:
    # Regular property access
    if isinstance(value, dict) and part in value:
        value = value[part]
    elif isinstance(value, str):
        # Attempt to parse JSON string for nested access
        # Enables: ${node.stdout.field} when stdout is '{"field": "value"}'
        parsed_value = TemplateResolver._try_parse_json_for_traversal(value)
        if isinstance(parsed_value, dict) and part in parsed_value:
            value = parsed_value[part]
        else:
            logger.debug(
                f"Cannot resolve path '{var_name}': '{part}' not found "
                f"(value is string, attempted JSON parse)",
                extra={"var_name": var_name, "failed_at": part},
            )
            return None
    else:
        logger.debug(
            f"Cannot resolve path '{var_name}': '{part}' not found or parent not a dict",
            extra={"var_name": var_name, "failed_at": part},
        )
        return None
```

### 2.4 Update `_traverse_path_part()` Method

**Location**: Lines 178-193

**Current code**:
```python
else:
    # Regular property access
    if not isinstance(current, dict):
        return False, current

    if part not in current:
        return False, current

    if part_index < total_parts - 1:
        # Not the last part - need to continue traversing
        current = current[part]
        if current is None:
            return False, current  # Can't traverse through None
    # For the last part, we just check existence, not value

    return True, current
```

**New code**:
```python
else:
    # Regular property access
    if isinstance(current, dict) and part in current:
        if part_index < total_parts - 1:
            current = current[part]
            if current is None:
                return False, current
        return True, current
    elif isinstance(current, str):
        # Attempt to parse JSON string for nested access
        parsed = TemplateResolver._try_parse_json_for_traversal(current)
        if isinstance(parsed, dict) and part in parsed:
            if part_index < total_parts - 1:
                current = parsed[part]
                if current is None:
                    return False, current
            return True, current
        return False, current
    else:
        return False, current
```

### 2.5 Handle Array Access on JSON Strings

**Location**: Lines 253-278 (array access in `resolve_value()`)

The array access block also needs JSON parsing. After getting `value[base_name]`, if it's a string, parse it:

```python
# Get the base value (should lead to a list)
if isinstance(value, dict) and base_name in value:
    value = value[base_name]
    # NEW: Parse JSON string if needed for array access
    if isinstance(value, str):
        value = TemplateResolver._try_parse_json_for_traversal(value)
else:
    # ... existing error handling
```

Similarly update `_check_array_indices()` if needed.

### 2.6 Create Tests for Template Resolver JSON Parsing

**File**: `tests/test_runtime/test_template_resolver_json_parsing.py`

Test cases:
1. **Basic nested access**: `${node.stdout.field}` where stdout is `'{"field": "value"}'`
2. **Deep nesting**: `${node.stdout.a.b.c}` where stdout is `'{"a": {"b": {"c": 3}}}'`
3. **Array access**: `${node.stdout[0]}` where stdout is `'[1, 2, 3]'`
4. **Array with object**: `${node.stdout[0].id}` where stdout is `'[{"id": 1}]'`
5. **Invalid JSON graceful fallback**: `${node.stdout.field}` where stdout is `'not json'` → unresolved
6. **Whitespace handling**: `${node.stdout.field}` where stdout is `'{"field": 1}\n'`
7. **Recursive JSON parsing**: `${node.stdout.data.inner}` where stdout is `'{"data": "{\"inner\": 1}"}'`
8. **Mixed access**: `${node.result.items[0].name}` with nested JSON
9. **Type preservation**: Parsed integers stay integers
10. **Validation consistency**: `variable_exists()` returns same result as `resolve_value()` success
11. **Simple template with JSON**: `${node.stdout}` returns raw string (NOT parsed - current behavior preserved)

### 2.7 Verification Criteria

- [ ] All new tests pass
- [ ] All existing template resolver tests still pass
- [ ] `variable_exists()` and `resolve_value()` agree on all cases
- [ ] `make test` passes
- [ ] `make check` passes

---

## Phase 3: Consolidation - Replace Duplicates

### 3.1 Files to Update

| File | Current Function | Change |
|------|------------------|--------|
| `src/pflow/cli/main.py` | `_parse_if_json()` | Replace with `parse_json_or_original()` |
| `src/pflow/execution/formatters/success_formatter.py` | `_parse_if_json()` | Replace with `parse_json_or_original()` |
| `src/pflow/execution/formatters/node_output_formatter.py` | `_try_parse_json_string()` | Replace with `parse_json_or_original()` |
| `src/pflow/runtime/node_wrapper.py` | Inline logic (745-780) | Use `try_parse_json()` |
| `src/pflow/runtime/batch_node.py` | Inline logic (252-280) | Use `try_parse_json()` |

### 3.2 Keep Separate (Do Not Consolidate)

| File | Function | Reason |
|------|----------|--------|
| `src/pflow/nodes/mcp/node.py` | `_safe_parse_json()` | Includes `ast.literal_eval` fallback for non-compliant MCP servers |
| `src/pflow/nodes/llm/llm.py` | `parse_json_response()` | Handles markdown code blocks extraction |

These have specialized behavior beyond simple JSON parsing.

### 3.3 Update Strategy for Each File

#### 3.3.1 `cli/main.py`

```python
# Before
def _parse_if_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value

# After
from pflow.core.json_utils import parse_json_or_original

# Replace _parse_if_json(x) calls with parse_json_or_original(x)
```

#### 3.3.2 `node_wrapper.py` (Lines 745-780)

The existing logic checks target parameter type. Keep that logic but use the utility:

```python
# Before (simplified)
if is_simple_template and isinstance(resolved_value, str):
    expected_type = self._expected_types.get(key)
    if expected_type in ("dict", "list", "object", "array"):
        trimmed = resolved_value.strip()
        if len(trimmed) > MAX_JSON_SIZE:
            # warning
        elif (expected_type in ("dict", "object") and trimmed.startswith("{")) or ...
            try:
                parsed = json.loads(trimmed)
                # type check
            except:
                pass

# After
from pflow.core.json_utils import try_parse_json

if is_simple_template and isinstance(resolved_value, str):
    expected_type = self._expected_types.get(key)
    if expected_type in ("dict", "list", "object", "array"):
        success, parsed = try_parse_json(resolved_value)
        if success:
            # Type validation
            if (expected_type in ("dict", "object") and isinstance(parsed, dict)) or \
               (expected_type in ("list", "array") and isinstance(parsed, list)):
                resolved_value = parsed
                logger.debug(...)
```

### 3.4 Verification Criteria

- [ ] All existing tests still pass (no behavior change)
- [ ] Removed duplicate code (~50 lines total)
- [ ] `make test` passes
- [ ] `make check` passes

---

## Phase 4: Verification & Documentation

### 4.1 End-to-End Test

Create integration test that runs the exact workflow from the feature request:

**File**: `tests/test_integration/test_json_nested_access_e2e.py`

```python
def test_shell_json_output_nested_access():
    """E2E test: ${shell.stdout.field} works when stdout is JSON."""
    workflow_ir = {
        "nodes": [
            {
                "id": "output-json",
                "type": "shell",
                "params": {
                    "command": "echo '{\"iso\": \"2026-01-01\", \"month\": \"January\"}'"
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

    # Execute and verify
    shared = {}
    flow = compile_ir_to_flow(workflow_ir, ...)
    flow.run(shared)

    assert "iso value: 2026-01-01" in shared["test-nested"]["stdout"]
```

### 4.2 Documentation Updates

#### 4.2.1 Update Agent Instructions

**File**: `src/pflow/mcp_server/resources/cli-agent-instructions.md`

Add section explaining the auto-parse behavior:

```markdown
#### JSON String Auto-Parsing During Path Traversal

When accessing nested properties on a string value, pflow automatically
attempts to parse the string as JSON:

```yaml
# Shell outputs: {"status": "success", "count": 42}
- id: api-call
  type: shell
  params:
    command: "curl -s https://api.example.com/data"

# This works! stdout is auto-parsed as JSON
- id: use-result
  type: shell
  params:
    command: "echo 'Count: ${api-call.stdout.count}'"
```

**Behavior**:
- Only triggers when accessing a property on a string value
- String must be valid JSON object `{...}` or array `[...]`
- Invalid JSON gracefully falls back (template stays unresolved)
- Recursive: nested JSON strings are also parsed
- 10MB size limit for security

**Examples**:
- `${node.stdout}` → Returns raw string (no change)
- `${node.stdout.field}` → Parses JSON, returns field value
- `${node.stdout[0].id}` → Parses JSON array, returns element's id
```

#### 4.2.2 Update Feature Request Document

Mark acceptance criteria as complete in:
`scratchpads/feature-request-json-string-nested-access.md`

### 4.3 Final Verification Checklist

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] `make test` passes
- [ ] `make check` passes
- [ ] Feature request acceptance criteria met:
  - [ ] `${node.stdout.field}` resolves when stdout is valid JSON object
  - [ ] `${node.stdout[0]}` resolves when stdout is valid JSON array
  - [ ] Invalid JSON fails gracefully with clear error
  - [ ] Deep nesting works: `${node.stdout.a.b.c}`
  - [ ] Mixed access works: `${node.stdout.items[0].name}`
  - [ ] No performance regression
  - [ ] Backward compatible
  - [ ] Debug logging shows parse attempts

---

## Risk Assessment

### Low Risk
- **Backward compatibility**: Only enables previously-failing patterns
- **Performance**: JSON parsing is <1ms, resolution happens once per node

### Medium Risk
- **Validation consistency**: Must keep `resolve_value()` and `_traverse_path_part()` in sync
  - **Mitigation**: Shared helper method, comprehensive tests

### Mitigated
- **Security (DoS)**: Large JSON strings
  - **Mitigation**: 10MB size limit (existing pattern)
- **Unexpected parsing**: String that happens to be JSON but user wants raw
  - **Mitigation**: Only parse during nested access, not terminal access

---

## Implementation Order

```
Phase 1 ──────────────────────────────────────────────────────
  │
  ├─ 1.1 Create json_utils.py
  ├─ 1.2 Create tests for json_utils.py
  └─ 1.3 Verify: make test && make check

Phase 2 ──────────────────────────────────────────────────────
  │
  ├─ 2.1 Add import to template_resolver.py
  ├─ 2.2 Add _try_parse_json_for_traversal() helper
  ├─ 2.3 Update resolve_value()
  ├─ 2.4 Update _traverse_path_part()
  ├─ 2.5 Update array access handling
  ├─ 2.6 Create template resolver JSON parsing tests
  └─ 2.7 Verify: make test && make check

Phase 3 ──────────────────────────────────────────────────────
  │
  ├─ 3.1 Update cli/main.py
  ├─ 3.2 Update success_formatter.py
  ├─ 3.3 Update node_output_formatter.py
  ├─ 3.4 Update node_wrapper.py
  ├─ 3.5 Update batch_node.py
  └─ 3.6 Verify: make test && make check

Phase 4 ──────────────────────────────────────────────────────
  │
  ├─ 4.1 Create E2E integration test
  ├─ 4.2 Update documentation
  └─ 4.3 Final verification
```

---

## Estimated Scope

| Phase | Files Changed | Lines Changed | Tests Added |
|-------|---------------|---------------|-------------|
| Phase 1 | 2 | ~80 | ~15 |
| Phase 2 | 2 | ~60 | ~15 |
| Phase 3 | 5 | ~-30 (net reduction) | 0 |
| Phase 4 | 3 | ~50 | ~5 |
| **Total** | **12** | **~160** | **~35** |

---

## Success Criteria

The feature is complete when:

1. `uv run pflow /tmp/test-json-nested-access.json` outputs:
   ```
   ✓ Workflow completed
   iso value: 2026-01-01
   ```

2. All tests pass: `make test`
3. All checks pass: `make check`
4. Documentation updated
5. Code duplication reduced (7 → 2 implementations)
