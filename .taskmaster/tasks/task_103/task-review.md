# Task 103 Review: Preserve Inline Object Type in Template Resolution

## Metadata

- **Implementation Date**: 2026-01-01
- **Branch**: `feat/inline-object-type`
- **Pull Request**: #32

## Executive Summary

Fixed the double-serialization bug where `{"key": "${dict_var}"}` produced `{"key": "{\"nested\": \"value\"}"}` instead of `{"key": {"nested": "value"}}`. Renamed `resolve_string` to `resolve_template` with type-preserving behavior for simple templates (`${var}`), while maintaining string interpolation for complex templates (`Hello ${name}`). This fix benefits ALL nodes automatically through the wrapper chain.

## Implementation Overview

### What Was Built

1. **Type-preserving template resolution**: Simple templates (`${var}`) now return the original value type (dict, list, int, bool, None). Complex templates (`"Hello ${name}"`) still return strings.

2. **Helper methods**: Added `is_simple_template()` and `extract_simple_template_var()` to TemplateResolver for reuse.

3. **Shared pattern constant**: Extracted `_VAR_NAME_PATTERN` to ensure consistency between `TEMPLATE_PATTERN` and `SIMPLE_TEMPLATE_PATTERN`.

4. **Refactored node_wrapper**: Uses shared helper instead of duplicating regex.

### Deviation from Original Spec

The spec suggested fixing only `resolve_nested()`. We chose a more comprehensive approach:
- Renamed `resolve_string` → `resolve_template` for API clarity
- Fixed `workflow_executor.py` too (nested workflow param mapping had same bug)
- Added strict pattern validation (PR review feedback)

## Files Modified/Created

### Core Changes

| File | Change |
|------|--------|
| `src/pflow/runtime/template_resolver.py` | Added `_VAR_NAME_PATTERN`, `SIMPLE_TEMPLATE_PATTERN`, `is_simple_template()`, `extract_simple_template_var()`. Renamed `resolve_string` → `resolve_template` with type preservation. Updated `resolve_nested` to call new method. |
| `src/pflow/runtime/node_wrapper.py` | `_resolve_simple_template()` now uses `TemplateResolver.extract_simple_template_var()`. Changed call from `resolve_string` to `resolve_template`. |
| `src/pflow/runtime/workflow_executor.py` | Changed `resolve_string` → `resolve_template` for nested workflow param mapping. |

### Test Files

| File | Change | Priority |
|------|--------|----------|
| `tests/test_runtime/test_template_type_preservation.py` | **NEW** - 13 tests for type preservation behavior | Critical |
| `tests/test_integration/test_shell_stdin_type_preservation.py` | **NEW** - 4 integration tests for shell stdin | Critical |
| `tests/test_runtime/test_template_resolver.py` | Updated 22 calls to `resolve_template` | High |
| `tests/test_runtime/test_node_wrapper_nested_resolution.py` | Fixed 2 assertions expecting old stringified behavior | High |
| `tests/test_nodes/test_mcp/test_json_text_parsing.py` | Rewrote tests for new type-preserving behavior | Medium |
| `tests/test_runtime/test_template_resolver_arrays.py` | Updated 6 calls | Low |
| `tests/test_runtime/test_template_resolver_nested.py` | Updated 2 calls | Low |
| `tests/test_runtime/test_template_array_notation.py` | Updated 1 call | Low |

## Integration Points & Dependencies

### Incoming Dependencies

All nodes benefit automatically:
```
TemplateAwareNodeWrapper
    └── calls TemplateResolver.resolve_nested()
        └── calls TemplateResolver.resolve_template()
            └── Type preserved for simple templates
```

Specific nodes affected:
- **Shell node**: `stdin` can now be `{"a": "${data-a}", "b": "${data-b}"}` without double-encoding
- **HTTP node**: `body`, `headers`, `params` preserve types
- **MCP node**: Dynamic tool arguments preserve types
- **LLM node**: Structured params preserve types
- **All other nodes**: Same benefit through wrapper chain

### Outgoing Dependencies

```
resolve_template() depends on:
├── extract_simple_template_var() - Pattern detection
├── variable_exists() - Check if var is in context
├── resolve_value() - Get the actual value (any type)
└── _convert_to_string() - Only for complex templates
```

### Shared Store Keys

No new shared store keys. Template resolution reads from:
- `shared` store (runtime data)
- `initial_params` (planner parameters)

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|----------|-----------|----------------------|
| Rename `resolve_string` → `resolve_template` | Name should reflect return type (`Any`, not `str`) | Keep name, change behavior (confusing API) |
| Delete `resolve_string` entirely | No backward compat needed per user | Keep as deprecated alias (adds noise) |
| Extract `_VAR_NAME_PATTERN` | Single source of truth for valid variable pattern | Duplicate regex in both patterns (drift risk) |
| Fix in `TemplateResolver`, not `node_wrapper` | Fixes all callers automatically, single location | Fix in each caller (scattered, error-prone) |

### Technical Debt Incurred

None significant. The implementation is cleaner than before:
- Eliminated duplicate regex in node_wrapper
- Consolidated detection logic in TemplateResolver
- Stricter validation after PR review

## Testing Implementation

### Test Strategy Applied

1. **Unit tests**: Direct testing of `resolve_template()` behavior
2. **Integration tests**: Shell node stdin with real workflow execution
3. **Edge case tests**: Pattern boundary (simple vs complex vs invalid)
4. **Regression tests**: Updated existing tests expecting old behavior

### Critical Test Cases

| Test | What It Validates |
|------|-------------------|
| `test_inline_object_preserves_dict_type` | THE primary bug fix - `{"key": "${dict}"}` preserves inner dict |
| `test_shell_stdin_inline_object_not_double_encoded` | End-to-end with real shell execution |
| `test_complex_template_in_stdin_still_stringifies` | `"Hello ${name}"` still returns string |
| `test_invalid_variable_names_not_simple` | `${123}`, `${ var }` correctly rejected |

## Unexpected Discoveries

### Gotchas Encountered

1. **Tests expecting old behavior**: Two tests in `test_node_wrapper_nested_resolution.py` explicitly tested the broken behavior with comments like "Template resolution converts numbers to strings". Had to update these to expect correct behavior.

2. **Original SIMPLE_TEMPLATE_PATTERN too permissive**: Initial pattern `r"^\$\{([^}]+)\}$"` matched invalid names like `${123}`, `${ var }`. Fixed by extracting shared pattern from TEMPLATE_PATTERN.

3. **workflow_executor.py also affected**: Nested workflow parameter mapping had the same bug. Would have been missed if we only fixed `resolve_nested()`.

### Edge Cases Found

| Edge Case | Behavior |
|-----------|----------|
| `${missing}` (unresolved) | Stays as `${missing}` in output |
| `${data.field}` (path) | Simple template - preserves type |
| `${items[0]}` (array index) | Simple template - preserves type |
| `${a}${b}` (adjacent) | Complex template - returns string |
| ` ${var}` (leading space) | Complex template - returns string |
| `$${var}` (escaped) | Not a template - literal `${var}` |

## Patterns Established

### Reusable Patterns

**Simple vs Complex Template Detection**:
```python
# Simple template pattern - preserves type
SIMPLE_TEMPLATE_PATTERN = re.compile(rf"^\$\{{({_VAR_NAME_PATTERN})\}}$")

# Usage:
if TemplateResolver.is_simple_template(value):
    return TemplateResolver.resolve_value(var_name, context)  # Type preserved
else:
    return TemplateResolver.resolve_string(value, context)  # String interpolation
```

**Shared Pattern Extraction**:
```python
# Extract reusable pattern for DRY
_VAR_NAME_PATTERN = r"[a-zA-Z_][\w-]*(?:(?:\[\d+\])?(?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)?"

# Use in multiple regex
TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_VAR_NAME_PATTERN})\}}")
SIMPLE_TEMPLATE_PATTERN = re.compile(rf"^\$\{{({_VAR_NAME_PATTERN})\}}$")
```

### Anti-Patterns to Avoid

1. **Don't duplicate regex patterns**: If you need to detect simple templates elsewhere, use `TemplateResolver.is_simple_template()`, don't copy the regex.

2. **Don't call `_convert_to_string()` for simple templates**: The whole point is to preserve types. Only use it for complex templates.

3. **Don't assume `resolve_template()` returns string**: It returns `Any` now. Check `is_simple_template()` if you need to know the return type.

## Breaking Changes

### API/Interface Changes

| Change | Migration |
|--------|-----------|
| `resolve_string()` removed | Use `resolve_template()` instead |
| Return type of template resolution | Now `Any` instead of always `str` |

### Behavioral Changes

| Before | After |
|--------|-------|
| `resolve_nested({"key": "${dict}"})` → `{"key": "{\"nested\":\"value\"}"}` | `{"key": {"nested": "value"}}` |
| Simple templates in nested structures stringified | Type preserved |
| `int` in nested template became `"42"` | Stays `42` |
| `bool` in nested template became `"True"` | Stays `True` |

## Future Considerations

### Extension Points

- **Type coercion**: If a node expects string but receives dict from simple template, the JSON auto-parsing in node_wrapper handles this. Could be extended for other coercions.

- **Custom serialization**: If someone needs the old behavior (stringify simple templates), they could add a `force_string=True` parameter to `resolve_template()`.

### Scalability Concerns

None. Template resolution is O(n) with template count, unchanged from before.

## AI Agent Guidance

### Quick Start for Related Tasks

1. **Read first**:
   - `src/pflow/runtime/template_resolver.py:336-434` - The `resolve_template()` method
   - `tests/test_runtime/test_template_type_preservation.py` - All behavior documented in tests

2. **Key insight**: Simple template = entire string is `${var}` → type preserved. Anything else → string.

3. **Pattern to follow**: Use `TemplateResolver.is_simple_template()` and `extract_simple_template_var()` for any new detection logic.

### Common Pitfalls

1. **Don't assume string return**: `resolve_template("${data}", ctx)` might return a dict. Check before string operations.

2. **Pattern consistency**: If you modify `_VAR_NAME_PATTERN`, both `TEMPLATE_PATTERN` and `SIMPLE_TEMPLATE_PATTERN` change. Test both.

3. **Test the boundary**: When adding template features, test both `${var}` (simple) and `"prefix ${var}"` (complex) cases.

### Test-First Recommendations

When modifying template resolution:
1. Run `test_template_type_preservation.py` first - covers core behavior
2. Run `test_shell_stdin_type_preservation.py` - integration test
3. Run full `tests/test_runtime/test_template_*.py` - all template tests

```bash
uv run pytest tests/test_runtime/test_template_type_preservation.py tests/test_integration/test_shell_stdin_type_preservation.py -v
```

---

*Generated from implementation context of Task 103*
