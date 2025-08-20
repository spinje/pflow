# Workflow Validation Specification - Summary

## Quick Start for Implementation

This folder contains the complete specification for adding workflow validation to pflow. An implementing agent should read the documents in this order:

1. **SUMMARY.md** (this file) - Quick overview
2. **README.md** - Complete specification with context and rationale
3. **implementation-guide.md** - Step-by-step code implementation
4. **examples-of-invalid-workflows.md** - Real examples to test against

## The Problem

Currently, pflow crashes with `KeyError: 'name'` when it encounters malformed workflow files. A recent incident involved a workflow file (`test-suite.json`) that was missing the required metadata wrapper, causing system-wide failures.

## The Solution

Add validation when loading workflows from disk to:
1. **Catch problems early** - Validate structure when loading, not when using
2. **Provide clear errors** - Tell users exactly what's wrong
3. **Be resilient** - Skip bad files in `list_all()`, fail clearly in `load()`

## Key Implementation Points

### What to Validate
1. **Level 1**: Valid JSON (already done)
2. **Level 2**: Required fields exist (`name` and `ir`) ← **Focus here**
3. **Level 3**: Valid IR structure (optional, use existing `validate_ir()`)

### Where to Implement
- **Primary file**: `/Users/andfal/projects/pflow/src/pflow/core/workflow_manager.py`
- **Bug fix**: `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py` (line ~176)
- **Tests**: `/Users/andfal/projects/pflow/tests/test_core/test_workflow_manager.py`

### Core Methods to Add
1. `_validate_metadata_structure()` - Check required fields
2. `_load_and_validate_file()` - Load and validate a file
3. Update `list_all()` - Use validation, skip invalid with warnings
4. Update `load()` - Use validation, raise exceptions for invalid

### The Bug Fix
WorkflowDiscoveryNode needs to catch `WorkflowValidationError` in addition to `WorkflowNotFoundError`.

## Validation Rules

### Required Fields
- `name`: Must be a non-empty string without invalid filesystem characters
- `ir`: Must be an object (the workflow IR)

### Invalid Characters in Name
These characters are not allowed: `/` `\` `:` `*` `?` `"` `<` `>` `|`

## Expected Behavior

### list_all()
- Skip invalid files
- Log warnings for each invalid file
- Return only valid workflows
- Never crash

### load()
- Raise `WorkflowValidationError` for invalid files
- Provide specific error messages
- Never return invalid data

## Testing Requirements

The implementation must handle these cases:
1. Missing `name` field
2. Missing `ir` field
3. Empty or whitespace-only name
4. Wrong type for name (number, null, etc.)
5. Invalid characters in name
6. Corrupted JSON
7. Root is not an object
8. Mixed valid and invalid files

## Success Metrics

- ✅ No more `KeyError: 'name'` crashes
- ✅ Clear error messages tell users what to fix
- ✅ One bad workflow doesn't break the system
- ✅ All existing valid workflows continue to work
- ✅ Minimal performance impact (< 1ms per file)

## Critical Context

### Why This Matters
- **User files are external input** that we don't control
- **Users can manually edit** workflow JSON files
- **Files can be corrupted** or from older versions
- **This is different from test mocks** which we control

### Design Philosophy
- **Validate at the boundary** (when loading from disk)
- **Trust internal data** (after validation)
- **Be strict in load()** (fail fast with clear errors)
- **Be lenient in list_all()** (skip bad files, continue)

## Don't Forget

1. **Import WorkflowValidationError** in nodes.py
2. **Test with existing workflows** to ensure backward compatibility
3. **Log warnings, don't include sensitive data**
4. **Handle edge cases** like unicode, large files
5. **Keep validation focused** on required fields only

## Questions to Consider

Before implementing, consider:
- Should IR validation be on by default? (Recommendation: No, make it optional)
- Should we add a migration script? (Recommendation: Document manual fix for now)
- Maximum file size limit? (Recommendation: No limit initially, monitor usage)

## Implementation Checklist

- [ ] Read all specification documents
- [ ] Add validation methods to WorkflowManager
- [ ] Update list_all() method
- [ ] Update load() method
- [ ] Fix WorkflowDiscoveryNode bug
- [ ] Write comprehensive tests
- [ ] Test with real workflows
- [ ] Verify no performance regression
- [ ] Update any relevant documentation

## Contact for Questions

This specification was created based on:
- Analysis of the current codebase
- The `test-suite.json` incident
- Best practices for input validation
- Existing patterns in pflow

The specification is complete and ready for implementation.