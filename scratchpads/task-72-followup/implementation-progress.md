# Output Source Validation - Implementation Progress

**Date**: 2025-10-13
**Issue**: Missing validation for workflow output source fields
**Status**: ✅ Complete

---

## Critical Discovery: Workflow Save Bypass Bug

**Problem Found During Manual Testing**:
- `pflow workflow save` was only doing IR schema validation
- Did NOT call `WorkflowValidator.validate()`
- Invalid workflows with bad output sources could be saved to library
- Would only fail at runtime (terrible UX)

**Root Cause**: `workflow_save_service.py` called `validate_ir()` (schema only) but not `WorkflowValidator.validate()` (comprehensive)

**Fix Applied**: Modified `_validate_and_normalize_ir()` to perform BOTH validations:
1. IR schema validation (structure, required fields)
2. WorkflowValidator validation (data flow, output sources, node types)

**Impact**: All save operations now protected (CLI and MCP)

---

## Implementation Summary

### Files Modified (3)

**1. `src/pflow/core/workflow_validator.py` (~100 lines)**
- Added `_validate_output_sources()` static method (85 lines)
- Integrated as 5th validation check in `validate()` method
- Updated docstring to document new validation

**2. `tests/test_core/test_output_source_validation.py` (200 lines, NEW)**
- 15 comprehensive test cases covering all edge cases
- 100% pass rate, zero regressions

**3. `src/pflow/core/workflow_save_service.py` (~30 lines modified)**
- Enhanced `_validate_and_normalize_ir()` with comprehensive validation
- Prevents invalid workflows from entering the system

### What Gets Validated

**Output source field validation**:
```python
"outputs": {
    "result": {"source": "node_id.output_key"}  # Validates node_id exists
}
```

**Catches**:
- Non-existent node references: `"fake_node.output"`
- Empty source strings: `""`
- Whitespace-only sources: `"   "`
- Case-sensitive mismatches

**Allows**:
- Valid node references: `"node_id"` or `"node_id.output"`
- Nested paths: `"node_id.a.b.c"` (splits on first dot)
- Template variables: `"${dynamic_node}.output"` (skipped - can't validate statically)
- Missing source field (optional)

---

## Design Decisions

### 1. Check Empty String Before None

**Bug Found**: Initial implementation checked `if not source:` which catches both `None` and `""`.

**Fix**: Changed to `if source is None:` so empty strings are caught separately with clear error message.

### 2. Template Variables Skipped

Template variables like `"${variable}"` cannot be validated statically. These are skipped with debug log (no warning to user).

### 3. Output Key Validation Deferred

Only validates node exists, not output key. Reason: No reliable node output metadata at validation time. Marked for future enhancement.

### 4. Two-Stage Validation in Save Service

Save service now does:
1. IR schema validation (fast, catches structure issues)
2. Comprehensive validation (slower, catches logic issues)

Both must pass before workflow is saved.

---

## Test Results

```
✅ New tests: 15/15 passing (0.28s)
✅ Save service tests: 35/35 passing
✅ Full suite: 2917 passing (13.45s)
✅ Zero regressions
✅ Type checking: PASSED
✅ Code quality: PASSED
```

---

## Integration Points (Auto-Protected)

All validation points now reject invalid output sources:

1. ✅ `pflow --validate-only` - CLI validation command
2. ✅ `pflow workflow save` - CLI workflow save ⭐ **FIXED**
3. ✅ MCP `workflow_validate` - Validation API
4. ✅ MCP `workflow_save` - Save API ⭐ **FIXED**
5. ✅ Pre-execution validation - Runtime validation

**Zero additional code changes needed** for integration - all use `WorkflowValidator.validate()`

---

## Key Takeaway

**Always test the complete user workflow**, not just individual functions. The manual workflow save test revealed a critical gap that unit tests didn't catch.

The validation implementation is correct - the bug was in the integration layer (save service not calling the validator).
