# Test Failure Investigation Report - UPDATED

## Executive Summary
**CRITICAL UPDATE**: The issue is more severe than initially thought. We have **40+ test failures** and tests are running **extremely slowly** (3+ minutes instead of 30 seconds). The root cause is that importing the `pflow.planning.debug` module creates performance issues and test interference.

## Findings

### 1. Scope of Failures - UPDATED
- **40+ tests failing** across multiple test files
- **Tests hanging** particularly in `tests/test_planning/unit/test_browsing_selection.py`
- **Test execution time increased from ~30 seconds to 3+ minutes**
- Tests that individually pass are failing/hanging when run together
- The issue manifests differently in different environments

### 2. Root Cause Analysis - UPDATED

#### The Core Problem
**The debug module import creates a heavy dependency chain**:

1. **Import Chain**: When `tests/shared/mocks.py` tries to handle the debug module:
   - It imports `pflow.planning.debug`
   - Which imports all 9 planner nodes from `pflow.planning.nodes`
   - Which imports various utilities and dependencies
   - This heavy import chain gets triggered for EVERY test

2. **Test Interference**: The debug module's DebugWrapper class with its `__getattr__` delegation and operator overloads (`__sub__`, `__rshift__`, `next`) may be interfering with test mocks and patches

3. **Mock System Conflict**: The mock system in `tests/shared/mocks.py` doesn't know how to handle the debug submodule properly, causing either:
   - Import errors when it blocks the debug module
   - Performance issues when it imports the debug module

#### Error Pattern
All failures show the same error:
```python
AttributeError: module 'pflow.planning' has no attribute 'debug'
```

This happens at the patch line:
```python
with patch("pflow.planning.debug.create_planner_flow_with_debug") as mock_create_flow:
```

### 3. Why Other Tests Pass

- **`test_debug.py`**: Tests the debug module directly, doesn't go through the mocked planning module
- **`test_debug_flags_no_llm.py`**: Tests lower-level functionality without trying to patch the planning.debug module
- **`test_debug_integration.py`**: Uses different import patterns that don't trigger the mock issue
- **Other CLI tests**: Don't import or patch the debug module

### 4. Code Functionality Status

The actual implementation works correctly:
- The debug wrapper properly wraps planner nodes
- Progress indicators display correctly
- Trace files are generated as expected
- Timeout detection works
- The CLI successfully imports and uses the debug module in production

### 3. Specific Test Issues Identified

#### Test Hanging in `test_browsing_selection.py`
- The third test `test_exec_uses_over_inclusive_prompt` hangs when run as part of the suite
- This test patches `pflow.planning.nodes.parse_structured_response`
- The patch might be triggering imports that interact badly with the debug module

#### CLI Flag Tests Failing
- All 11 tests in `test_debug_flags_no_llm.py` fail
- They can't access `pflow.planning.debug` through the mock
- When we allow access, it causes slowdowns

## Solutions - UPDATED

### Option 1: Move Debug Module Outside Planning (RECOMMENDED)
**Move the debug functionality to a separate package to avoid import conflicts**:
1. Move `src/pflow/planning/debug.py` to `src/pflow/debug/planner.py`
2. This breaks the circular import with `pflow.planning.nodes`
3. Tests won't trigger heavy imports through the mock system
4. The debug module remains independent and testable

### Option 2: Lazy Import in Debug Module
**Modify debug.py to use lazy imports**:
```python
def create_planner_flow_with_debug(user_input: str, trace_enabled: bool = False):
    # Import nodes only when function is called, not at module level
    from pflow.planning.nodes import (
        WorkflowDiscoveryNode,
        ComponentBrowsingNode,
        # ... etc
    )
```
This prevents the import chain from being triggered until the function is actually used.

### Option 3: Conditional Debug Loading
**Only load debug module when explicitly needed**:
```python
# In CLI main.py
if trace or planner_timeout != 60:
    from pflow.planning.debug import create_planner_flow_with_debug
    # Use debug version
else:
    from pflow.planning.flow import create_planner_flow
    # Use regular version
```

### Option 2: Restructure Test Approach
Instead of patching `pflow.planning.debug.create_planner_flow_with_debug`, the tests could:
- Import the debug module directly
- Mock at a different level (e.g., mock the underlying planner flow creation)
- Use dependency injection patterns

### Option 3: Disable Mock for Debug Tests
Add a fixture in `test_debug_flags.py` that temporarily removes the planning mock:
```python
@pytest.fixture(autouse=True)
def allow_planning_debug(monkeypatch):
    """Temporarily restore real planning module for debug tests."""
    import sys
    if "pflow.planning" in sys.modules:
        # Store and restore the real module
        pass
```

## Impact Assessment

- **Production Code**: ✅ Fully functional, no issues
- **Debug Features**: ✅ Working as designed
- **Test Coverage**: ⚠️ Debug flags not tested due to mock issue
- **Other Tests**: ✅ All passing, no regression

## Key Learnings

1. **Import Dependencies Matter**: The debug module importing all planner nodes creates a heavy dependency chain
2. **Test Mocks Are Fragile**: The mock system can't handle new submodules without explicit support
3. **Performance Impact**: Import chains in frequently-accessed modules severely impact test performance
4. **Isolation Principle**: Debug/instrumentation code should be isolated from core functionality

## Recommended Action - UPDATED

**Implement Option 2 (Lazy Imports)** as an immediate fix:
1. Fastest to implement - just move imports inside the function
2. Breaks the import chain that's causing slowdowns
3. Maintains the current module structure
4. Minimal risk of breaking other functionality

Then consider Option 1 (moving debug module) as a longer-term refactor for better architecture.

## Files Affected by Solution

If implementing Option 1, only one file needs modification:
- `tests/shared/mocks.py` - Add special handling for the "debug" attribute in `MockPlanningModule.__getattr__`

No changes needed to:
- Production code (all working correctly)
- Test files (can remain as written)
- Other test infrastructure
