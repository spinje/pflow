# Migration Plan: Remove Metadata-Level Inputs/Outputs

## Executive Summary

Remove the redundant `inputs` and `outputs` fields from the workflow metadata wrapper, establishing the IR-level declarations as the single source of truth. Since we're building an MVP with no users, we can make breaking changes without backward compatibility concerns.

## Current State

### Dual Declaration Problem
```json
{
  "name": "fix-issue",
  "description": "Fixes a GitHub issue",
  "inputs": ["issue_number", "repo"],     // Metadata level - simple strings
  "outputs": ["pr_url"],                  // Metadata level - simple strings
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {                          // IR level - detailed declarations
      "issue_number": {
        "description": "Issue to fix",
        "required": true,
        "type": "string"
      }
    },
    "outputs": {                         // IR level - detailed declarations
      "pr_url": {
        "description": "Created PR URL",
        "type": "string"
      }
    }
  }
}
```

## Migration Strategy

### Phase 1: Update Context Builder (2 hours)

#### 1.1 Remove Validation Requirements
**File**: `src/pflow/planning/context_builder.py`

- **Line 96**: Remove "inputs" and "outputs" from required fields
- **Lines 107-108**: Remove type validation for these fields
- Update validation to only require: `["name", "description", "ir"]`

#### 1.2 Create IR Extraction Logic
Add helper methods to extract interface info from IR:

```python
@staticmethod
def _extract_ir_inputs(workflow_ir: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Extract input declarations from workflow IR."""
    inputs = workflow_ir.get("inputs", {})
    return [(name, spec) for name, spec in inputs.items()]

@staticmethod
def _extract_ir_outputs(workflow_ir: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Extract output declarations from workflow IR."""
    outputs = workflow_ir.get("outputs", {})
    return [(name, spec) for name, spec in outputs.items()]
```

#### 1.3 Update Display Formatting
**Method**: `_format_workflow_section` (lines 692-738)

Replace current formatting with IR-based extraction:
```python
# Old way:
inputs = workflow.get("inputs", [])

# New way:
ir_inputs = self._extract_ir_inputs(workflow.get("ir", {}))
if ir_inputs:
    lines.append("**Inputs**:")
    for name, spec in ir_inputs:
        desc = spec.get("description", "")
        type_hint = spec.get("type", "any")
        required = spec.get("required", True)
        default = spec.get("default")

        # Format: - `name: type` - description (optional, default: value)
        parts = [f"- `{name}: {type_hint}`"]
        if desc:
            parts.append(f" - {desc}")
        if not required:
            if default is not None:
                parts.append(f" (optional, default: {default})")
            else:
                parts.append(" (optional)")
        lines.append("".join(parts))
```

### Phase 2: Update Test Fixtures (1 hour)

#### 2.1 Remove Metadata Fields from Fixtures
**Directory**: `tests/test_planning/fixtures/workflows/`

For each `.json` file:
- Remove top-level "inputs" field
- Remove top-level "outputs" field
- Ensure IR has proper input/output declarations

Example transformation:
```json
// Before:
{
  "name": "test-workflow",
  "inputs": ["input1"],
  "outputs": ["output1"],
  "ir": { ... }
}

// After:
{
  "name": "test-workflow",
  "description": "Test workflow",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {
      "input1": {
        "description": "Test input",
        "required": true,
        "type": "string"
      }
    },
    "outputs": {
      "output1": {
        "description": "Test output",
        "type": "string"
      }
    },
    "nodes": [...]
  }
}
```

#### 2.2 Update Test Cases
**File**: `tests/test_planning/test_workflow_loading.py`

- Remove tests that check for metadata-level inputs/outputs
- Update assertions to work with new format
- Add tests for IR extraction logic

### Phase 3: Update Examples (30 minutes)

#### 3.1 Clean Up Example Workflows
**Directory**: `examples/`

- Remove any workflows with metadata-level inputs/outputs
- Ensure all examples use IR-level declarations only

### Phase 4: Documentation Updates (30 minutes)

#### 4.1 Update Schema Documentation
**File**: `docs/core-concepts/schemas.md`

- Remove references to metadata-level inputs/outputs
- Clarify that IR is the single source of truth
- Update examples to show new format

#### 4.2 Update CLAUDE.md Files
- Update any CLAUDE.md files that reference the old format
- Clarify the new workflow structure

## Implementation Order

1. **Create feature branch**: `remove-metadata-inputs-outputs`

2. **Phase 1**: Update context_builder.py
   - Remove validation requirements
   - Add IR extraction helpers
   - Update formatting logic
   - Run tests to see what breaks

3. **Phase 2**: Fix broken tests
   - Update test fixtures
   - Modify test assertions
   - Add new tests for IR extraction

4. **Phase 3**: Update examples
   - Clean up example workflows
   - Ensure consistency

5. **Phase 4**: Update documentation
   - Schema docs
   - CLAUDE.md files

6. **Final validation**:
   - Run `make test`
   - Run `make check`
   - Manual testing with pflow CLI

## Benefits

1. **Single Source of Truth**: IR contains the complete interface contract
2. **Richer Information**: Display includes types, descriptions, defaults
3. **No Duplication**: Eliminates maintenance burden
4. **Better UX**: Users see more helpful information about workflows
5. **Cleaner Architecture**: Aligns with "IR = Contract" principle

## Risks and Mitigation

| Risk | Mitigation |
|------|-----------|
| Breaking existing workflows | No users yet - can update all examples |
| Tests failing | Comprehensive test update in Phase 2 |
| Missing edge cases | Thorough testing with various workflow types |
| Context builder complexity | Simple extraction helpers keep it clean |

## Success Criteria

- [ ] All tests pass
- [ ] Context builder displays richer interface information
- [ ] No metadata-level inputs/outputs in any workflow
- [ ] Documentation reflects new structure
- [ ] CLI works correctly with updated workflows

## Estimated Time

- Phase 1: 2 hours
- Phase 2: 1 hour
- Phase 3: 30 minutes
- Phase 4: 30 minutes
- Testing & Validation: 1 hour
- **Total: ~5 hours**

## Next Steps

1. Review this plan
2. Create feature branch
3. Begin implementation with Phase 1
4. Use subagents for parallel work where possible
