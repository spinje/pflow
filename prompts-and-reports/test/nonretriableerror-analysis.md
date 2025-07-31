# NonRetriableError Retry Behavior Analysis

## Assessment: CONFIRMED BUG ✅

After deep investigation of the code, I can confirm with **high confidence** that the NonRetriableError retry behavior is indeed a fault in the code.

## Evidence

### 1. Clear Design Intent

The `NonRetriableError` exception class documentation explicitly states its purpose:
```python
class NonRetriableError(Exception):
    """Exception for errors that should not be retried.

    Use this for validation errors or conditions that will not
    change with retries (e.g., wrong file type, invalid parameters).
    """
```

### 2. Usage Pattern Shows Expected Behavior

The file nodes use `NonRetriableError` for validation errors that should fail immediately:
```python
# From copy_file.py
if not os.path.isfile(source_path):
    # This is a validation error that won't change with retries
    raise NonRetriableError(
        f"Source path '{source_path}' is not a file. This node only copies files, not directories."
    )
```

The comments explicitly state "won't change with retries" - indicating the developer expectation that these errors should NOT be retried.

### 3. PocketFlow Implementation Ignores NonRetriableError

The PocketFlow `Node` class implementation (lines 67-76 of `__init__.py`):
```python
def _exec(self, prep_res):
    for self.cur_retry in range(self.max_retries):
        try:
            return self.exec(prep_res)
        except Exception as e:  # Catches ALL exceptions
            if self.cur_retry == self.max_retries - 1:
                return self.exec_fallback(prep_res, e)
            if self.wait > 0:
                time.sleep(self.wait)
```

**The bug**: This catches `Exception` (which includes `NonRetriableError`) and retries ALL exceptions without any check for exception type.

### 4. Documentation Confirms Expected Behavior

The pflow node implementation guide (`src/pflow/nodes/CLAUDE.md`) states:
> "Use NonRetriableError for validation errors that shouldn't retry"

This documentation was written with the expectation that NonRetriableError would bypass the retry mechanism.

### 5. Test Discovery Confirms Issue

The test comment explicitly states:
```python
# LESSON LEARNED: Current implementation retries NonRetriableError despite intention.
# This test verifies retry behavior works as currently implemented.
```

## The Fix Required

The PocketFlow `Node._exec` method should be modified to check for NonRetriableError:

```python
def _exec(self, prep_res):
    for self.cur_retry in range(self.max_retries):
        try:
            return self.exec(prep_res)
        except NonRetriableError as e:  # Add this check
            # Don't retry NonRetriableError - fail immediately
            return self.exec_fallback(prep_res, e)
        except Exception as e:
            if self.cur_retry == self.max_retries - 1:
                return self.exec_fallback(prep_res, e)
            if self.wait > 0:
                time.sleep(self.wait)
```

## Impact

### Current Behavior (Bug)
- Configuration errors (e.g., "source is a directory") retry 3 times
- Users wait unnecessarily for retries on errors that will never succeed
- Poor user experience with delayed error reporting

### Expected Behavior
- Configuration errors should fail immediately
- Only transient errors (network, temporary file locks) should retry
- Faster feedback for user errors

## Confidence Level: 95%

This is clearly a bug where:
1. The exception was designed for one purpose (skip retries)
2. The implementation doesn't honor that design
3. All usage assumes the design works as documented
4. Tests had to be adjusted to match the buggy behavior

The only reason this isn't 100% confidence is the possibility that PocketFlow intentionally chose this behavior for simplicity, but all evidence points to this being an oversight in the implementation.
