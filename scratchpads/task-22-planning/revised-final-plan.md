# Revised Implementation Plan - With Refactoring

## Key Insight: Massive Code Duplication!

Both file and named workflow execution do **exactly the same thing**:
1. Get workflow IR (from different sources)
2. Parse parameters
3. Call `execute_json_workflow()`

We're duplicating ~100 lines of code for no good reason!

## New Approach: Unified Execution Path

### Core Refactoring (Do This FIRST)

```python
def resolve_workflow(identifier: str, is_file_flag: bool = False) -> tuple[dict, str]:
    """
    Single function to get workflow IR from ANY source.

    Tries in order:
    1. If is_file_flag: Load from file path only
    2. Saved workflow (exact name)
    3. Saved workflow (without .json)
    4. Local file path

    Returns: (workflow_ir, source_type) or (None, None)
    """

def execute_resolved_workflow(
    ctx: click.Context,
    workflow_args: tuple[str, ...],
    is_file_flag: bool = False,
) -> bool:
    """
    Single execution path for ALL workflows.
    Replaces both _try_direct_workflow_execution() and _execute_json_workflow_from_file()
    """
    if not workflow_args:
        return False

    identifier = workflow_args[0]
    params = parse_workflow_params(workflow_args[1:])

    # Resolve from any source
    workflow_ir, source = resolve_workflow(identifier, is_file_flag)

    if not workflow_ir:
        if is_file_flag:
            # Explicit file not found
            raise click.ClickException(f"File not found: {identifier}")
        # Let it fall back to planner
        return False

    # Single execution path
    execute_json_workflow(
        ctx, workflow_ir, ctx.obj.get("stdin_data"),
        ctx.obj.get("output_key"), params, None,
        ctx.obj.get("output_format", "text"), None
    )
    return True
```

### Simplified Main Flow

```python
def main(file, workflow, ...):
    # Set up context...

    if file:
        # --file flag: treat first arg as file path
        if not execute_resolved_workflow(ctx, (file,) + workflow, is_file_flag=True):
            raise click.ClickException("Could not load workflow file")
    elif workflow:
        # Try workflow execution first
        if not execute_resolved_workflow(ctx, workflow):
            # Fall back to natural language planner
            process_natural_language(ctx, workflow)
    else:
        # No input error
```

## What We Can Delete

1. ❌ `_try_direct_workflow_execution()` - replaced by unified function
2. ❌ `_execute_json_workflow_from_file()` - replaced by unified function
3. ❌ `_get_file_execution_params()` - just use `parse_workflow_params()`
4. ❌ `process_file_workflow()` - simplify to just call unified function
5. ❌ Duplicate parameter parsing logic
6. ❌ Duplicate error handling

## Implementation Order (Revised)

### Phase 0: Refactor Foundation (1 hour) - DO THIS FIRST!
1. Create `resolve_workflow()` function
2. Create `execute_resolved_workflow()` function
3. Update main() to use unified path
4. Delete duplicate code
5. Test everything still works

### Phase 1: Enhanced Resolution (1 hour)
1. Add .json extension support to resolver
2. Add file path detection
3. Add better error messages with suggestions
4. Test all resolution patterns work

### Phase 2: Discovery Commands (1 hour)
1. Create `workflow.py` with list/describe
2. Update router
3. Test discovery works

### Phase 3: Polish (30 min)
1. User-friendly error messages throughout
2. Final testing

## Benefits of Refactoring First

1. **Cleaner codebase** - One path instead of two
2. **Easier to enhance** - Add features in one place
3. **Better testing** - Test one unified path
4. **Less bugs** - Single source of truth
5. **Easier maintenance** - Future changes in one place

## Code Statistics

**Before Refactoring:**
- ~200 lines across multiple functions
- 2 separate execution paths
- Duplicate parameter parsing
- Duplicate error handling

**After Refactoring:**
- ~100 lines in unified functions
- 1 execution path
- Single parameter parsing
- Consistent error handling

## Testing Strategy (Updated)

Test the unified path with all inputs:
```python
def test_unified_workflow_execution():
    """All these should use the same code path."""

    # Named workflow
    assert execute_resolved_workflow(ctx, ("my-workflow", "param=1"))

    # With .json extension
    assert execute_resolved_workflow(ctx, ("my-workflow.json", "param=1"))

    # Local file
    assert execute_resolved_workflow(ctx, ("./workflow.json", "param=1"))

    # --file flag
    assert execute_resolved_workflow(ctx, ("workflow.json", "param=1"), is_file_flag=True)
```

## Summary

By refactoring FIRST, we:
1. Eliminate code duplication
2. Create a clean foundation
3. Make enhancements easier
4. Reduce testing burden
5. Improve maintainability

Since we have **no users**, this is the perfect time to clean up the architecture before adding new features!