# Loop Detection Implementation

## Date: 2025-01-24

## Problem Statement

The repair system can attempt up to 27 repairs in pathological cases (3 runtime attempts × 3 validation attempts × 3 repair attempts), wasting LLM tokens on unfixable errors. Even with cache invalidation fixed, the system doesn't know when to stop trying.

## Solution

Implement a simple loop detection mechanism that compares error signatures before and after repair attempts. If the same error persists, stop trying.

## Why This Is Critical

After implementing cache invalidation (which fixes nodes getting stuck with cached errors), we still have the problem of the repair system not knowing when to give up. This causes:

1. **Wasted LLM tokens**: Attempting repairs on unfixable issues (e.g., "channel_not_found")
2. **Poor user experience**: Long waits while system futilely attempts repairs
3. **Resource exhaustion**: Up to 27 LLM calls in worst case

## What This Implementation Does

Adds a simple check in the runtime repair loop:
- Tracks the error signature from the previous attempt
- Compares with current error signature
- If identical, stops repair attempts

## What This Implementation Does NOT Do

- Does NOT detect API warnings (that's a separate optimization)
- Does NOT classify errors as repairable/non-repairable
- Does NOT prevent the first repair attempt
- Does NOT modify checkpoint behavior

## Implementation Details

### Location
- File: `src/pflow/execution/workflow_execution.py`
- Function: `execute_workflow()`
- Lines: ~133-195 (runtime repair loop)

### Changes
1. Add `_get_error_signature()` helper function
2. Track `last_error_signature` before loop
3. Compare signatures after each execution
4. Stop if no progress detected

### Code Changes
```python
# Helper function to create error signature
def _get_error_signature(errors: list) -> str:
    """Create a signature to detect if we're seeing the same errors."""
    return "|".join(
        e.get("message", "")[:50]
        for e in errors[:3]
    )

# In the runtime repair loop
last_error_signature = None

while runtime_attempt < max_runtime_attempts:
    result = executor.execute_workflow(...)

    if result.success:
        return result

    # Check if we're stuck in a loop
    error_signature = _get_error_signature(result.errors)
    if error_signature == last_error_signature:
        logger.info("Same error after repair attempt, stopping repair loop")
        return result  # Stop trying, we're stuck

    last_error_signature = error_signature
    # Continue with repair...
```

## Why This Works

This simple approach catches ALL non-repairable errors because:
- If repair can't fix something, the error message won't change
- Comparing signatures is universal - works for any error type
- No need for complex error classification

## Relationship to Other Systems

### Cache Invalidation (Already Implemented)
- **Purpose**: Ensures nodes can be retried after repair
- **This adds**: Detection of when retries aren't helping

### API Warning Detection (Future)
- **Purpose**: Skip repair for obvious API errors
- **This provides**: Fallback for anything API detection misses

### The Stack
1. **Cache invalidation**: Makes repair possible
2. **Loop detection**: Prevents infinite attempts (this implementation)
3. **API detection**: Optimization to skip obvious cases (future)

## Test Cases

### Test 1: Repair Makes Progress
- Error 1: "Template ${foo.bar} not found"
- Repair fixes template
- Error 2: "Command failed with exit code 1"
- Different signature → Continue trying ✓

### Test 2: Repair Stuck
- Error 1: "API error: channel_not_found"
- Repair attempts fix
- Error 2: "API error: channel_not_found"
- Same signature → Stop trying ✓

### Test 3: Multiple Same Errors
- Multiple nodes fail with different errors
- Signature captures first 3
- If signature unchanged after repair → Stop ✓

## Success Metrics

1. **No more 27-attempt scenarios**: Loop stops after 1-2 attempts
2. **Genuine repairs still work**: Different errors allow continuation
3. **Clear logging**: User sees "Same error after repair attempt, stopping"
4. **No performance impact**: Just string comparison

## Risk Analysis

### Risks
1. **False positives**: Stopping when minor variation might be fixable
   - **Mitigation**: Only compare first 50 chars of messages

2. **False negatives**: Not catching very similar errors
   - **Mitigation**: 50 chars is usually enough to identify error type

### Non-Risks
- **No checkpoint changes**: Completely orthogonal to cache system
- **No API changes**: Just adds early exit to existing loop
- **No test breakage**: Only affects repair loop behavior

## Why Implement Now

1. **Cache invalidation is done**: Foundation is ready
2. **Simple implementation**: ~15 lines of code
3. **High impact**: Solves the 27-attempt problem
4. **Low risk**: Just adds early exit condition
5. **Universal solution**: Catches all non-repairable errors

## Implementation Status

**Status**: READY TO IMPLEMENT

**Prerequisites**:
- ✅ Cache invalidation implemented and tested
- ✅ Understanding of repair loop structure verified
- ✅ Error signature approach validated
- ✅ Test strategy defined

**Next Steps**:
1. Implement the helper function
2. Add loop detection logic
3. Test with known stuck scenarios
4. Verify existing tests still pass
5. Document in progress log

## Long-term Vision

This loop detection is the **pragmatic foundation** for preventing futile repairs. Future enhancements can add:
- API-specific detection (optimization)
- Error classification (nice-to-have)
- Retry strategies (backoff, etc.)

But this simple loop detection solves 90% of the problem with 10% of the complexity.

## Conclusion

Loop detection is a critical missing piece that makes the repair system practical. Combined with cache invalidation, it ensures the system:
- Can retry what's fixable (cache invalidation)
- Knows when to stop trying (loop detection)
- Provides a good user experience (no endless waiting)

This should be implemented immediately after cache invalidation is verified stable.