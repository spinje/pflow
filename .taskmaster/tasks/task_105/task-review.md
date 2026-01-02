# Task 105 Review: Auto-Parse JSON Strings During Nested Template Access

## Metadata
- **Implementation Date**: 2026-01-01
- **Branch**: `feat/auto-parse-json`
- **Pull Request**: https://github.com/spinje/pflow/pull/37

## Executive Summary

Implemented automatic JSON parsing during template path traversal, enabling `${node.stdout.field}` when stdout contains a JSON string. This required coordinating two systems (compile-time validator + runtime resolver) and establishing a shared JSON utility that consolidated 7 duplicate implementations.

## Implementation Overview

### What Was Built

1. **Core Feature**: JSON auto-parsing in `template_resolver.py` during path traversal
2. **Shared Utility**: `json_utils.py` with `try_parse_json()` returning `(success, result)` tuple
3. **Validator Relaxation**: Allow nested access on `str` types with compile-time warning
4. **Error Message Improvements**: JSON-specific hints and better path-aware suggestions

### Key Deviations from Original Plan

1. **Phase 4 was not in original plan** - Discovered validator/resolver mismatch during testing. Had to relax validator to allow `str` nested access.
2. **Error message improvements added post-review** - Code review feedback led to JSON-specific runtime hints and improved suggestion logic.
3. **Removed low-value tests** - Deleted 6 tests, replaced with 1 high-value behavioral test. Tests should verify behavior, not implementation.

## Files Modified/Created

### Core Changes

| File | Change | Impact |
|------|--------|--------|
| `src/pflow/core/json_utils.py` | **NEW** - Shared JSON parsing utility | Eliminates 7 duplicates, single source of truth |
| `src/pflow/runtime/template_resolver.py` | Added `_try_parse_json_for_traversal()` and `_get_dict_value()` helpers | Core feature - parses JSON during path traversal |
| `src/pflow/runtime/template_validator.py` | Added `_check_type_allows_traversal()`, `_strip_array_indices()` | Allows `str` nested access with warning |
| `src/pflow/runtime/node_wrapper.py` | Added `_detect_json_parse_hints()`, improved `_generate_suggestions()` | Better error messages for JSON failures |
| `src/pflow/runtime/batch_node.py` | Use `try_parse_json()` | Consolidation |

### Test Files

| File | Purpose | Critical? |
|------|---------|-----------|
| `tests/test_core/test_json_utils.py` | Utility tests (16 tests) | YES - validates core parsing logic |
| `tests/test_runtime/test_template_resolver_json_parsing.py` | Feature tests (21 tests) | YES - especially `TestValidationConsistency` |
| `tests/test_integration/test_json_nested_access_e2e.py` | E2E workflow tests (9 tests) | YES - proves feature works end-to-end |
| `tests/test_runtime/test_template_validator_warnings.py` | Warning behavior tests (8 tests) | MEDIUM - validates compile-time warnings |

## Integration Points & Dependencies

### Critical Integration: Validator ↔ Resolver

```
Compile Time                          Runtime
     │                                    │
     ▼                                    ▼
┌─────────────────┐              ┌─────────────────┐
│ TemplateValidator│              │ TemplateResolver │
│                 │              │                 │
│ Sees: stdout:str│              │ Sees: stdout=   │
│ Decision: ALLOW │──────────────│ '{"field":"v"}' │
│ (with warning)  │  Must agree  │ Action: PARSE   │
└─────────────────┘              └─────────────────┘
```

**Lesson**: When adding runtime "magic", always check if compile-time validation needs updating. These systems MUST agree on what's valid.

### Shared Store Keys

No new shared store keys. Feature operates on existing node output keys.

### Outgoing Dependencies

- `json_utils.try_parse_json()` is now used by:
  - `template_resolver.py` (path traversal)
  - `node_wrapper.py` (target-side auto-parse)
  - `batch_node.py` (items parsing)

## Architectural Decisions & Tradeoffs

### Decision 1: Two-Value Return Pattern

**Choice**: `try_parse_json()` returns `(success: bool, result: Any)`

**Reasoning**: Distinguishes three cases:
- `(True, {"key": "value"})` - Parsed successfully to dict
- `(True, None)` - Parsed successfully to JSON null
- `(False, "original string")` - Parse failed

**Alternative considered**: Return parsed value or original. Rejected because can't distinguish "parsed to None" from "failed to parse".

### Decision 2: Parse Only During Traversal

**Choice**: `${node.stdout}` returns raw string, `${node.stdout.field}` triggers parsing

**Reasoning**: Backward compatible. Existing workflows expecting raw strings continue to work.

**Alternative considered**: Always parse if valid JSON. Rejected because changes behavior for existing workflows.

### Decision 3: Warning for `str`, Not `any`

**Choice**: Only `str` type generates compile-time warning for nested access

**Reasoning**:
- `dict`/`object`: Trusted structured data, no warning
- `any`: Node author explicitly declared "could be anything", no warning
- `str`: JSON auto-parsing is implicit/surprising, warn user

### Technical Debt Incurred

1. **No caching of parsed JSON** - Same string parsed multiple times if accessed with different paths. Acceptable for MVP (parsing is <1ms vs node execution 100-1000ms).
2. **Display layer doesn't deduplicate warnings** - Multiple templates on same output generate multiple warnings. Could group in future.

## Testing Implementation

### Test Strategy Applied

**Principle**: Test behavior, not implementation. Focus on:
1. Does the feature work? (E2E tests)
2. Do the edge cases behave correctly? (Unit tests)
3. Do the systems agree? (Validation consistency tests)

### Critical Test Cases

| Test | What It Validates | Why Critical |
|------|-------------------|--------------|
| `TestValidationConsistency.test_exists_agrees_with_resolve_for_valid_json` | `variable_exists()` and `resolve_value()` agree | Prevents validator/resolver mismatch |
| `TestJsonNestedAccessE2E.test_shell_json_output_nested_access` | Original feature request scenario | Proves feature works |
| `TestRecursiveJsonParsing.test_nested_json_string_is_parsed_at_each_level` | JSON-in-JSON works | Edge case users will hit |
| `test_distinguishes_parsed_none_from_parse_failure` | Two-value return correctness | API contract |

## Unexpected Discoveries

### Gotcha 1: Validator Blocks Valid Runtime Patterns

**Discovery**: E2E tests failed because validator saw `stdout: str` and rejected nested access.

**Solution**: Relaxed validator to allow `str` nested access with warning.

**Impact**: Created new coordination requirement between validator and resolver.

### Gotcha 2: Array Access on JSON Strings

**Discovery**: `${node.stdout[0].field}` requires special handling in validator.

**Solution**: Added `_strip_array_indices()` to extract base key before validation.

### Gotcha 3: Error Message Suggestions Were Wrong

**Discovery**: For `${mynode.stdout}` (typo), suggestion was `${my-node}` not `${my-node.stdout}`.

**Solution**: Updated `_generate_suggestions()` to preserve full path when suggesting corrections.

## Patterns Established

### Pattern 1: Two-Value Return for Parse Operations

```python
def try_parse_json(value: str) -> tuple[bool, Any]:
    """Return (success, result) to distinguish parse-to-None from failure."""
    try:
        return (True, json.loads(value))
    except (json.JSONDecodeError, ValueError):
        return (False, value)
```

**When to use**: Any parse operation where the result could legitimately be None/empty.

### Pattern 2: Helper Methods for Dual-Path Consistency

```python
# In template_resolver.py
@staticmethod
def _get_dict_value(value: Any, key: str) -> tuple[bool, Any]:
    """Shared logic for resolve_value() and _traverse_path_part()."""
```

**When to use**: When two code paths must behave identically. Extract shared logic.

### Pattern 3: Actionable Warning Messages

```python
reason=(
    f"Nested access on '{output_type}' requires valid JSON at runtime. "
    f"Non-JSON strings cause 'Unresolved variables' error."
)
```

**Structure**: [What's required] + [What happens if violated]

### Anti-Pattern: Testing Implementation Details

**Don't**: Test that a specific function is called with specific arguments.
**Do**: Test that the observable behavior is correct.

Example: Don't test "JSON parsing was attempted". Test "nested access resolves to expected value".

## Breaking Changes

None. Feature is purely additive:
- Previously failing patterns (`${node.stdout.field}` on JSON string) now work
- Previously working patterns unchanged

## AI Agent Guidance

### Quick Start for Related Tasks

1. **Read first**:
   - `src/pflow/runtime/template_resolver.py` - `_try_parse_json_for_traversal()`
   - `src/pflow/runtime/template_validator.py` - `_check_type_allows_traversal()`

2. **Key insight**: Validator and resolver must agree. If you change one, check the other.

3. **Test pattern**: Always include a test that verifies `variable_exists()` agrees with `resolve_value()`.

### Common Pitfalls

1. **Don't forget the validator** - If you add runtime behavior for a type, the validator might block it at compile time.

2. **Two-value return matters** - Don't change `try_parse_json()` to return parsed-or-original. The tuple is intentional.

3. **Preserve full path in errors** - When generating suggestions for `${node.output.field}`, suggest `${other-node.output.field}`, not just `${other-node}`.

### Test-First Recommendations

When modifying template resolution:
1. Run `tests/test_runtime/test_template_resolver_json_parsing.py` - Core feature
2. Run `tests/test_runtime/test_template_validator_warnings.py` - Warning behavior
3. Run `tests/test_integration/test_json_nested_access_e2e.py` - Full flow

---

*Generated from implementation context of Task 105*
