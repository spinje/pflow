# Cleanup Plan: Remove Redundant Metadata-Level Inputs/Outputs

## Summary

Since we have no users and don't need backward compatibility, we can simply DELETE the metadata-level inputs/outputs fields and update the code to use the IR-level declarations. This is a cleanup, not a migration.

## What We're Removing

The redundant fields at the workflow wrapper level:
```json
{
  "name": "workflow-name",
  "description": "...",
  "inputs": ["input1", "input2"],    // DELETE THESE
  "outputs": ["output1"],             // DELETE THESE
  "ir": {
    // Keep the IR-level inputs/outputs - these are the source of truth
  }
}
```

## Implementation Steps

### Step 1: Update Context Builder (~1 hour)

**File**: `src/pflow/planning/context_builder.py`

1. **Remove from validation** (line 96):
   ```python
   # Change from:
   required_fields = ["name", "description", "inputs", "outputs", "ir"]
   # To:
   required_fields = ["name", "description", "ir"]
   ```

2. **Delete type checks** (lines 107-108):
   ```python
   # Delete these lines:
   if not isinstance(workflow.get("inputs"), list):
       return False, "Field 'inputs' must be a list"
   if not isinstance(workflow.get("outputs"), list):
       return False, "Field 'outputs' must be a list"
   ```

3. **Update display formatting** (lines 711-729):
   ```python
   # Replace the simple list formatting with IR extraction:
   def _format_workflow_section(self, workflow: dict[str, Any], section_type: str) -> list[str]:
       # ... existing code ...

       # Extract from IR instead of metadata
       workflow_ir = workflow.get("ir", {})

       # Format inputs
       ir_inputs = workflow_ir.get("inputs", {})
       if ir_inputs:
           lines.append("**Inputs**:")
           for name, spec in ir_inputs.items():
               desc = spec.get("description", "")
               type_hint = spec.get("type", "any")
               required = spec.get("required", True)
               default = spec.get("default")

               line = f"- `{name}: {type_hint}`"
               if desc:
                   line += f" - {desc}"
               if not required and default is not None:
                   line += f" (optional, default: {default})"
               elif not required:
                   line += " (optional)"
               lines.append(line)

       # Similar for outputs...
   ```

### Step 2: Fix Test Fixtures (~30 minutes)

**Directory**: `tests/test_planning/fixtures/workflows/`

For each JSON file, simply DELETE the inputs/outputs fields:

```json
// Before:
{
  "name": "test-workflow",
  "description": "Test workflow",
  "inputs": ["input1", "input2"],    // DELETE
  "outputs": ["output1"],             // DELETE
  "ir": { ... }
}

// After:
{
  "name": "test-workflow",
  "description": "Test workflow",
  "ir": { ... }  // IR already has inputs/outputs declarations
}
```

Files to update:
- `test-simple-workflow.json`
- `test-complex-workflow.json`
- `test-invalid-ir.json`
- `test-no-ir.json`

### Step 3: Update Example Workflows (~15 minutes)

Check and clean any example workflows that have metadata-level inputs/outputs:
- Remove the fields
- Ensure IR has proper declarations

### Step 4: Run Tests and Fix Issues (~30 minutes)

1. Run `make test` to see what breaks
2. Fix any test assertions that expect the old fields
3. Add tests for the new IR extraction logic

### Step 5: Update Documentation (~15 minutes)

- Update `docs/core-concepts/schemas.md` to remove any mention of metadata-level inputs/outputs
- Update any other docs that show the old format

## Total Time Estimate

~2.5 hours (much simpler than a migration!)

## Benefits of This Approach

1. **No compatibility code** - Just delete the old way
2. **Cleaner codebase** - No "migration" logic to maintain
3. **Single source of truth** - IR is the only place for interface declarations
4. **Better information** - Display shows types, descriptions, defaults (not just names)

## Deployment Strategy

Since there are no users:
1. Make all changes in one PR
2. Update all tests and examples together
3. No feature flags or gradual rollout needed
4. No deprecation warnings needed

Just rip off the band-aid! 🩹

## Success Criteria

- [ ] Context builder no longer validates inputs/outputs fields
- [ ] Display shows richer information from IR
- [ ] All tests pass
- [ ] All example workflows updated
- [ ] Documentation updated
- [ ] No references to metadata-level inputs/outputs remain
