# Task 22: Final Implementation Plan

## Executive Summary

After extensive research and testing, we discovered that **named workflow execution is 70% implemented**. The core functionality works but lacks critical usability features. Our implementation will focus on enhancing what exists rather than building from scratch.

## What We Discovered Works

✅ **Parameter passing**: Both `--file` and named workflows accept parameters
✅ **Input validation**: Required parameters are validated (Task 21's work)
✅ **Default values**: Optional parameters use defaults correctly
✅ **Type conversion**: Parameters are converted from strings to proper types
✅ **Basic execution**: `pflow my-workflow param=value` works for kebab-case names

## Critical Gaps to Address

### 1. **Workflow Resolution** (Highest Priority)
- ❌ Can't use `.json` extension: `pflow my-workflow.json`
- ❌ Can't use file paths: `pflow ./workflow.json`
- ❌ Single-word names don't work: `pflow analyze`

### 2. **User Guidance** (High Priority)
- ❌ No way to discover workflows: Need `pflow workflow list`
- ❌ No interface documentation: Need `pflow workflow describe`
- ❌ Poor error messages when workflow not found

### 3. **Error Handling** (Medium Priority)
- ❌ No suggestions for typos/similar names
- ❌ Technical error messages instead of user-friendly ones
- ❌ No guidance on how to fix problems

## Implementation Plan

### Phase 1: Core Resolution & Execution (2-3 hours)

#### 1.1 Enhance Workflow Resolution
```python
def resolve_workflow(name: str) -> tuple[dict, str]:
    """
    Smart resolution that tries:
    1. Exact name in saved workflows
    2. Name without .json extension
    3. Local file path
    4. Return None if not found
    """
```

**Files to modify:**
- `src/pflow/cli/main.py`: Add `resolve_workflow()` function
- Update `_try_direct_workflow_execution()` to use new resolution
- Update `is_likely_workflow_name()` to detect .json and paths

#### 1.2 Improve Error Messages
- Add helpful suggestions when workflow not found
- Show similar workflow names
- Guide users to `workflow list` or natural language

### Phase 2: Discovery Commands (1-2 hours)

#### 2.1 Create Workflow Command Group
New file: `src/pflow/cli/workflow.py`
```python
@click.group()
def workflow():
    """Manage saved workflows."""

@workflow.command()
def list():
    """List all saved workflows."""
    # Show workflows with descriptions
    # Group by category if metadata available

@workflow.command()
@click.argument("name")
def describe(name):
    """Show workflow details and interface."""
    # Show inputs, outputs, examples
```

#### 2.2 Update Router
Modify `src/pflow/cli/main_wrapper.py`:
- Add "workflow" to routing logic
- Import workflow command group

### Phase 3: Enhanced Error Handling (1 hour)

#### 3.1 User-Friendly Errors
- Implement `find_similar_names()` helper
- Add suggestions to all error messages
- Use emoji indicators sparingly (❌, 👉)

#### 3.2 Fallback Strategy
- When ambiguous, log attempt and fall back to planner
- Maintain backward compatibility

## Testing Strategy

### Critical Behaviors to Test

1. **Resolution Works All Ways**
   - `pflow my-workflow` (saved)
   - `pflow my-workflow.json` (saved with extension)
   - `pflow ./workflow.json` (local file)

2. **Parameters Work Correctly**
   - Required parameters validated
   - Defaults applied
   - Types converted

3. **Errors Guide Users**
   - Not found → suggests similar or list command
   - Missing params → shows what's needed with examples
   - Invalid types → shows expected format

4. **Discovery Commands Help**
   - List shows all workflows
   - Describe shows interface
   - Empty state has guidance

### Test Implementation

Use behavior-driven tests:
```python
def test_user_can_run_workflow_with_json_extension():
    """User naturally types .json and it works."""
    # Not testing HOW it works, testing THAT it works
    result = run("pflow my-workflow.json")
    assert result.success
    assert "Workflow executed successfully" in result.output
```

## File Changes Summary

### New Files
- `src/pflow/cli/workflow.py` - Workflow management commands
- `tests/test_cli/test_named_workflow_execution.py` - Feature tests
- `tests/test_cli/test_workflow_discovery.py` - Discovery command tests

### Modified Files
- `src/pflow/cli/main.py` - Add resolution, improve errors
- `src/pflow/cli/main_wrapper.py` - Add workflow command routing

## Success Metrics

After implementation, users should be able to:
1. ✅ Run workflows using natural patterns (with/without .json, file paths)
2. ✅ Discover what workflows are available
3. ✅ Understand what parameters workflows need
4. ✅ Get helpful guidance when things go wrong
5. ✅ Use workflows as easily as direct node invocation

## Implementation Order

1. **Start with resolution** - Biggest usability win
2. **Add discovery commands** - Helps users understand the feature
3. **Enhance error messages** - Throughout, as we go
4. **Write tests** - For each behavior as implemented

## Time Estimate

- Phase 1: 2-3 hours (resolution and basic errors)
- Phase 2: 1-2 hours (discovery commands)
- Phase 3: 1 hour (enhanced error handling)
- Testing: 2 hours (throughout implementation)
- **Total: 6-8 hours**

## NOT in Scope

- ❌ Shell pipe bug fix (separate task)
- ❌ Complex fuzzy matching (simple substring is enough)
- ❌ Workflow aliases or shortcuts
- ❌ Tab completion
- ❌ Performance optimization

## Ready to Implement

All research is complete. We understand:
- Current implementation state
- Error handling patterns
- Testing philosophy
- User expectations

The plan focuses on high-impact, low-risk improvements that build on existing functionality.