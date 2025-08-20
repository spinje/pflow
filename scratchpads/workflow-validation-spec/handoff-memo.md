# Handoff Memo: Workflow Validation Implementation

**⚠️ IMPORTANT**: Read this entire memo before implementing. When you're done reading, confirm you're ready to begin. Do NOT start implementing until you've absorbed all this context.

## The Real Story Behind This Task

We discovered this issue through a chain of events that nearly sent us down the wrong path entirely. Here's what actually happened:

### The Incident That Triggered Everything

1. **Initial symptom**: User reported `KeyError: 'name'` when running the planner with error: "Unknown workflows: workflow-1"
2. **First wrong diagnosis**: We thought the context builder was creating fake names for workflows without names
3. **The wrong fix we almost made**: Made the code "defensive" by using `.get("name", "workflow-1")` everywhere
4. **The revelation**: The REAL problem was a malformed `test-suite.json` file that lacked the metadata wrapper
5. **The correct insight**: Production workflows ALWAYS have names. If they don't, they're invalid and shouldn't be loaded

File that caused it: `/Users/andfal/.pflow/workflows/test-suite.json` (I already fixed it, but it was missing the wrapper)

## Critical Context You Need to Know

### The Philosophical Battle We Had

We had a heated discussion about whether to make code defensive against missing fields. The conclusion was crucial:

- **For test mocks**: Code should EXPECT valid data. Bad mocks = bad tests
- **For disk files**: These are EXTERNAL INPUT and must be validated
- **The principle**: "Validate external input at the boundary, then trust internal data"

This distinction is WHY we're adding validation to WorkflowManager but NOT making context_builder defensive.

### The Hidden Bug You Must Fix

**Location**: `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py` around line 176

The WorkflowDiscoveryNode only catches `WorkflowNotFoundError` but not `WorkflowValidationError`. This means if a workflow exists but is invalid, it crashes instead of falling back to Path B (generation).

```python
# Current (BROKEN):
except WorkflowNotFoundError:
    return "not_found"

# Must be:
except (WorkflowNotFoundError, WorkflowValidationError):
    return "not_found"
```

Don't forget to import `WorkflowValidationError`!

### The Context Builder Refactoring Connection

We just finished refactoring the context builder (`src/pflow/planning/context_builder.py`) to remove redundant headers and use numbered lists. During this refactoring, we made functions assume `workflow["name"]` exists, which is correct for production but exposed the validation gap.

Key changes we made:
- Removed defensive `.get("name", "default")` patterns
- Changed from markdown headers to numbered lists
- Separated `build_nodes_context()` and `build_workflows_context()`

This is all correct and should stay. The fix is validation at load time, not defensive coding.

## Patterns Already in Place

### list_all() Already Has the Right Pattern

Look at the current `list_all()` in WorkflowManager - it ALREADY skips invalid JSON files with warnings:

```python
try:
    with open(file_path, encoding="utf-8") as f:
        metadata = json.load(f)
    workflows.append(metadata)
except Exception as e:
    logger.warning(f"Failed to load workflow from {file_path}: {e}")
    continue
```

You're extending this pattern to also validate structure, not just JSON syntax.

### validate_ir() Already Exists

Don't reinvent the wheel! There's already a `validate_ir()` function in `/Users/andfal/projects/pflow/src/pflow/core/ir_schema.py` that validates IR structure. Use it for Level 3 validation if you implement that.

## Subtle Things That Will Bite You

### 1. The Sorting Assumption

After validation, the code does `workflows.sort(key=lambda w: w["name"])`. This is safe ONLY because validated workflows have names. Don't add defensive coding here.

### 2. Test Files vs Real Files

Some tests create workflow files directly without the wrapper. These tests might break after your changes. That's GOOD - the tests were wrong. Fix the tests, not the validation.

### 3. The _load_saved_workflows() Mock Check

In `build_discovery_context()` there's a weird check:
```python
if hasattr(_load_saved_workflows, "_mock_name"):
```

This is checking if the function is mocked. Don't worry about this - it's for test compatibility.

### 4. Performance Consideration

The current `list_all()` loads the ENTIRE workflow file into memory for each file. For Level 2 validation this is fine, but if you add Level 3 (IR validation), consider that some workflows might be huge.

## Files You'll Actually Touch

Don't get overwhelmed by the spec. You're really only changing:

1. **Main implementation**: `/Users/andfal/projects/pflow/src/pflow/core/workflow_manager.py`
   - Add 2 new methods
   - Modify 2 existing methods

2. **Bug fix**: `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py`
   - One line change around line 176
   - One import addition

3. **Tests**: `/Users/andfal/projects/pflow/tests/test_core/test_workflow_manager.py`
   - Add new test cases

Everything else (context_builder, other files) should NOT be touched.

## What Success Actually Looks Like

When you're done:
1. Run: `uv run pflow --output-format json "create a workflow about llamas"`
2. Create a malformed workflow: `echo '{"ir": {}}' > ~/.pflow/workflows/bad.json`
3. Run again - should skip bad.json with warning but still work
4. Try to load it directly - should get clear error about missing 'name'

## The Tests That Already Exist

There's already a test `test_list_all_skip_invalid` that tests skipping corrupted JSON. Your job is to extend this pattern to structural validation.

## Edge Cases We Discovered

1. **Unicode in names**: Should work fine, Python handles it
2. **Filesystem-invalid characters**: Must reject `/\:*?"<>|` in names
3. **Whitespace-only names**: Treat as invalid (use `str.strip()`)
4. **Very large files**: Current approach loads entire file - might be issue

## What NOT to Do

1. **DON'T make context_builder defensive** - It should assume valid data
2. **DON'T validate in multiple places** - Only in WorkflowManager
3. **DON'T break backward compatibility** - Valid workflows must still work
4. **DON'T overthink Level 3** - Make IR validation optional
5. **DON'T forget the import** - WorkflowValidationError in nodes.py

## Why This Matters More Than It Seems

This isn't just about preventing KeyErrors. It's about establishing the principle that external input gets validated at system boundaries. This pattern will be crucial as pflow grows and accepts more external data sources.

## Final Critical Reminder

The test-suite.json incident was a perfect storm:
1. A workflow without metadata wrapper
2. Code that assumed all workflows have names  
3. A discovery system that showed "workflow-1" when the name was missing
4. A downstream system trying to load "workflow-1" which didn't exist

Your validation will prevent step 1, making steps 2-4 impossible.

---

**Remember**: Read everything, understand the context, then confirm you're ready. Don't start coding until you've internalized why we're doing this and what we learned along the way.