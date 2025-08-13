## Comprehensive Investigation Report

## Executive Summary

After a systematic investigation of the issues reported with Task 27's planner debugging implementation, I've identified the root causes of all three major problems:

1. **"Massive wall of text" issue**: RESOLVED - Was caused by global logging configuration, now commented out
2. **Test failures**: UNDERSTOOD - Mock system prevents debug module import, causing 11 tests to fail
3. **Command hanging issue**: ROOT CAUSE FOUND - Critical bug in DebugWrapper's flow wiring

## Detailed Findings

### 1. Test Failure Analysis

**Scope**: Only 11 tests in `test_debug_flags_no_llm.py` are failing. All other tests pass (652+ tests).

**Root Cause**: The mock system in `tests/shared/mocks.py` prevents the debug module from being imported properly:
- The CLI tries to import `pflow.planning.debug`
- The mock raises ImportError to prevent this
- The CLI falls back to the regular planner without debugging
- Tests that try to patch `create_planner_flow_with_debug` fail because it was never called

**Impact**: Test infrastructure issue only, NOT a production bug.

### 2. Logging Configuration

**Status**: RESOLVED

The "massive wall of text" was caused by:
- `logging.basicConfig(level=logging.DEBUG)` in `src/pflow/planning/__init__.py`
- This has been commented out (line 29)
- Progress indicators now work correctly and display cleanly

**Verification**:
- Progress indicators display properly: `🔍 Discovery... ✓ 4.8s`
- Output goes to stderr to avoid interfering with stdout

### 3. Critical Bug: Flow Hanging Issue

**Status**: BUG IDENTIFIED - Needs Fix

**Problem**: Commands like `pflow list` hang after the first node executes.

**Root Cause**: The DebugWrapper's flow wiring methods (`__sub__` and `__rshift__`) are adding UNWRAPPED nodes as successors instead of wrapped ones.

**Bug Location**: `src/pflow/planning/debug.py` lines 85-86 and 102-103

```python
# Current BUGGY code:
actual_target = target._wrapped if isinstance(target, DebugWrapper) else target
self.wrapper._wrapped.next(actual_target, self.action)
```

This unwraps the target node before adding it as a successor, breaking the debug chain.

**Evidence**:
- Individual nodes work fine (4.8s execution)
- Wrapped nodes work fine when called directly
- Flow hangs because it calls unwrapped successors that don't have debug functionality
- Successors dict contains raw nodes, not wrapped ones

### 4. What's Actually Working

Despite the flow hanging bug, these components work correctly:
- ✅ Progress indicators display properly
- ✅ Trace collection mechanism
- ✅ LLM interception
- ✅ Individual node wrapping
- ✅ Timeout detection
- ✅ Debug utilities

## Key Questions Answered

1. **How many tests are actually failing?**
   - 11 tests in `test_debug_flags_no_llm.py` only

2. **Is the debug module being imported even when not using --trace?**
   - No, it's only imported when needed (line 903 in main.py)

3. **Are there other logging configurations overriding our fix?**
   - No, only one location found and it's commented out

4. **Why aren't progress indicators showing in the terminal?**
   - They ARE showing when the node executes, but flow hangs after first node

5. **Do the test failures indicate real functionality breaks or just test infrastructure issues?**
   - Test infrastructure issue only - the mock prevents proper import

## Critical Bug Fix Required

The DebugWrapper needs to be fixed to maintain wrapped nodes in successors:

```python
# FIXED code should be:
def __rshift__(self, target):
    # Don't unwrap! Keep the wrapper
    self.wrapper._wrapped.next(target, self.action)
    # Update wrapper's successors with the WRAPPED target
    self.wrapper.successors[self.action] = target
    return target
```

Similar fix needed for `__rshift__` operator method.

## Recommendations

### Immediate Actions Required:
1. **FIX THE BUG**: Update DebugWrapper to maintain wrapped nodes in successors
2. **Test Mock**: Either update mock to allow debug import OR change tests to handle ImportError
3. **Verify Fix**: After fixing, test with actual commands like `pflow "write hello to test.txt"`

### Why This Matters:
- Without this fix, ALL planner commands hang after the first node
- Progress indicators show but execution never completes
- This makes the entire planner unusable

## Conclusion

Task 27's debugging implementation is mostly correct. The progress indicators, trace collection, and LLM interception all work properly. However, a critical bug in how the DebugWrapper handles flow wiring causes the planner to hang after the first node executes. This bug prevents wrapped successor nodes from being called, breaking the flow execution chain. Once this single bug is fixed, the debugging system should work as intended.