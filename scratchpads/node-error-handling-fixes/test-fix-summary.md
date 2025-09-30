# Git Status Node Test Fixes

## Summary
Fixed 2 failing tests in `tests/test_nodes/test_git/test_status.py` that were expecting incorrect behavior after the error handling improvements in the Git nodes.

## Root Cause
The GitStatusNode was recently fixed to properly return "error" action when errors occur (instead of always returning "default"). This is the CORRECT behavior as it enables the repair system to detect and handle failures. The tests were written with the old incorrect expectations.

## Tests Fixed

### 1. `test_post_with_error`
- **Issue**: Expected `post()` to return "default" when there's an error in `exec_res`
- **Fix**: Updated to expect "error" action when errors are present
- **Why this is correct**: Returning "error" enables the repair system to handle failures

### 2. `test_retry_exhaustion_raises_error` → `test_retry_exhaustion_returns_error`
- **Issue**: Expected "default" action after retries exhausted with persistent failure
- **Fix**: Updated to expect "error" action and renamed test to reflect actual behavior
- **Why this is correct**: When exec_fallback returns error info, post() should return "error" to trigger repair

## Changes Made
1. Updated test assertions from `assert action == "default"` to `assert action == "error"`
2. Added documentation comments explaining the fix and why the behavior is correct
3. Added additional assertions to verify error propagation through shared store
4. Renamed test to better reflect what it's actually testing (returns error, not raises)

## Verification
- All 24 tests in test_status.py pass ✅
- All 139 tests across all Git nodes pass ✅
- No other tests were broken by this fix

## Key Learning
The implementation was correct - it properly returns "error" action to enable the repair system. The tests needed updating to expect this correct behavior. This demonstrates the importance of understanding the intended behavior before "fixing" tests.