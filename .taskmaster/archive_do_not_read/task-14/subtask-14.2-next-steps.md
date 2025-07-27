# Next Steps for Subtask 14.2 Implementation

**CRITICAL**: Follow these steps IN ORDER to complete subtask 14.2.

## Current Status Summary

✅ **DONE**:
- Implementation plan created
- `_extract_navigation_paths()` function implemented
- `_format_node_section()` updated with structure hints
- Structure hint limiting added (MAX_STRUCTURE_HINTS = 30)
- All core functionality implemented

❌ **TODO**:
- Run and fix tests
- Create implementation review
- Update task status

## Step-by-Step Instructions

### Step 1: Verify Current State
```bash
# Check you're in the right directory
pwd  # Should be /Users/andfal/projects/pflow

# Check current git status
git status

# Verify the changes are there
git diff --stat
```

Expected output:
- Modified: src/pflow/planning/context_builder.py
- Modified: tests/test_planning/test_context_builder.py

### Step 2: Run Tests and Fix Issues

#### 2.1 Run all tests first
```bash
make test
```

**EXPECTED ISSUES**:
1. **Existing tests failing**: Many tests call `_format_node_section()` expecting string return, but it now returns tuple
2. **Import error**: Tests import `_extract_navigation_paths` which might not be in __all__

#### 2.2 Fix the failing tests

**Issue 1 Fix**: Update all test calls to handle tuple return
```python
# OLD (will fail):
result = _format_node_section("node-name", node_data)

# NEW (correct):
result, _ = _format_node_section("node-name", node_data)
# OR if you need the count:
result, hint_count = _format_node_section("node-name", node_data)
```

**Files to check and fix**:
- `tests/test_planning/test_context_builder.py` - Already partially fixed, but check all occurrences
- Any other test files that might use `_format_node_section()`

#### 2.3 Run specific test file
```bash
# Run just the context builder tests
uv run pytest tests/test_planning/test_context_builder.py -xvs
```

#### 2.4 Fix any remaining issues
Common issues and fixes:
- **ImportError**: Make sure `_extract_navigation_paths` is imported in the test file
- **AttributeError**: Make sure you're unpacking the tuple correctly
- **AssertionError**: Update assertions to match new output format with navigation hints

### Step 3: Run Quality Checks

```bash
# Run all quality checks
make check
```

This runs:
- Linting (ruff)
- Type checking (mypy)
- Format checking

**Expected issues**:
- Might have line length issues (fix with line breaks)
- Might have complexity warnings (add # noqa: C901 if needed)
- Type hints might need adjustment

### Step 4: Verify Integration Works

Create a quick integration test:
```bash
# Start Python REPL
uv run python

# Test the integration
from pflow.registry.metadata_extractor import PflowMetadataExtractor
from pflow.planning.context_builder import build_context

# Create test metadata with structure
test_registry = {
    "test-node": {
        "module": "pflow.nodes.file.read_file",
        "class_name": "ReadFileNode",
        "file_path": "/path/to/node.py"
    }
}

# Build context and check output
output = build_context(test_registry)
print(output)
# Should show the node with types if it has enhanced format
```

### Step 5: Create Implementation Review

Once all tests pass, create the review document:

```bash
# Create the review file
touch .taskmaster/tasks/task_14/subtask_14.2/implementation/subtask-review.md
```

**Template for the review** (copy from 14.1's review):
```markdown
# Implementation Review for Subtask 14.2

## Summary
- Started: 2025-01-16 16:00
- Completed: [current time]
- Deviations from plan: [any deviations]

## What Worked Well
1. **Navigation path extraction**: Clean recursive implementation
2. **Structure hint formatting**: Inline hints are readable and helpful
3. **Hint limiting**: Prevents context overflow effectively

## What Didn't Work
[Document any issues encountered]

## Key Learnings
1. **Tuple return pattern**: Changing return types requires updating all callers
2. **Structure navigation**: Dot notation is intuitive for LLMs
3. **Global state tracking**: Hint count across nodes prevents overflow

## Test Creation Summary
- Updated existing tests to handle tuple returns
- Added unit tests for path extraction
- Added integration tests for structure hints
- All tests passing

## Impact on Other Tasks
- **Task 14.3-14.4**: Nodes can now use enhanced format and get navigation hints
- **Task 17 (Planner)**: Will have navigation paths for complex data structures

## Advice for Future Implementers
1. Always check return type changes impact all callers
2. Test with real metadata from enhanced nodes
3. Consider context limits when adding information
```

### Step 6: Update Task Status

```bash
# Mark subtask as complete
task-master set-status --id=14.2 --status=done
```

### Step 7: Verify Everything Works End-to-End

```bash
# Run a full check
make test
make check

# Check git status - should show:
# - Modified files (implementation)
# - New files (task management)
git status
```

## Troubleshooting Guide

### If tests won't import `_extract_navigation_paths`:
- Check if it needs to be added to `__all__` in context_builder.py
- Or import it directly from the module in tests

### If existing tests fail with "too many values to unpack":
- The test is calling `_format_node_section()` without unpacking tuple
- Fix: Add `, _` or `, hint_count` to the assignment

### If mypy complains about types:
- Add type hints to new functions if missing
- Use `Any` for complex nested dicts if needed

### If ruff complains about complexity:
- Add `# noqa: C901` to complex functions
- Or refactor if genuinely too complex

### If tests show wrong output format:
- Check that structure hints only appear for dict/list types
- Check that hint count limiting is working
- Verify backward compatibility with string format

## Success Criteria

Before marking complete, verify:
- [ ] All tests pass (`make test`)
- [ ] Quality checks pass (`make check`)
- [ ] Structure hints appear for complex types
- [ ] Navigation paths are readable (e.g., `.user.login`)
- [ ] Hint limiting works (only first 30 get hints)
- [ ] Backward compatibility maintained
- [ ] Implementation review created
- [ ] Task status updated to done

## What Happens Next

After completing 14.2:
1. Move to subtask 14.3 or 14.4 (updating nodes to enhanced format)
2. These subtasks will create nodes that actually use the enhanced format
3. The context builder will then show their type information and structure hints

## Important Context

Remember:
- The metadata extractor (14.1) already returns rich format
- Basic type display was already working when you started
- You only added structure navigation hints
- This is a minimal change that adds maximum value
- The planner will use these hints to generate valid data access paths

---

This plan provides exact steps to complete the implementation. The main work is running tests and fixing any issues that arise.
