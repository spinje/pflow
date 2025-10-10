# Code Analysis - Root Cause Identified

## The Bug Location

File: `src/pflow/runtime/instrumented_wrapper.py`
Method: `_extract_error_code`
Line: 867

## The Problem

```python
def _extract_error_code(self, output: dict) -> Optional[str]:
    """Extract error code from various API response formats."""
    # Try different common locations for error codes
    candidates = [
        output.get("error_code"),  # LINE 867: CRASH HERE!
        output.get("errorCode"),
        output.get("code"),
        # ... more candidates
    ]
```

## Call Chain to the Bug

1. **InstrumentedNodeWrapper._run()** (line 651)
   - Executes the inner node (HTTP node downloading binary image)

2. **Line 654**: `warning_msg = self._detect_api_warning(shared)`
   - Called after successful execution to check for API warnings

3. **_detect_api_warning()** (line 746-809)
   - Gets the node output from shared store
   - Line 763: `output = shared.get(self.node_id)`
   - For binary downloads, this is a STRING (the image data)

4. **Line 774**: `error_code = self._extract_error_code(output)`
   - Passes the output to _extract_error_code
   - NO TYPE CHECK before calling!

5. **_extract_error_code()** (line 863-878)
   - Type hint says `output: dict` but receives a string
   - Line 867: `output.get("error_code")`
   - CRASH: 'str' object has no attribute 'get'

## Why This Happens

When downloading binary images:
1. HTTP node with GET method fetches the image
2. Returns binary data (likely as base64 string or raw bytes converted to string)
3. This gets stored in `shared[node_id]` as a string
4. The instrumented wrapper assumes ALL node outputs are dicts
5. Tries to check for API errors in the "dict" response
6. Crashes because strings don't have `.get()` method

## The Type Assumption

The code assumes that if a node executes successfully, its output is always a dict that might contain error information. This is true for JSON APIs but false for binary downloads.

## Verification

You can see this assumption throughout the code:
- Line 763: Gets output without type checking
- Line 769: `output = self._unwrap_mcp_response(output)` - this returns None for non-dicts!
- Line 770-771: Checks if output is None and returns
- But between lines 763 and 769, if output is a string, it's passed directly to `_extract_error_code`

## The Fix

### Option 1: Type Check in _extract_error_code (Defensive)
```python
def _extract_error_code(self, output: dict) -> Optional[str]:
    """Extract error code from various API response formats."""
    # Add type safety
    if not isinstance(output, dict):
        return None

    # Rest of the method...
    candidates = [
        output.get("error_code"),
        # ...
    ]
```

### Option 2: Type Check in _detect_api_warning (Earlier Detection)
```python
def _detect_api_warning(self, shared: dict) -> Optional[str]:
    # ... existing code ...

    output = shared.get(self.node_id)

    # Add type check here
    if not isinstance(output, dict):
        return None  # Non-dict outputs can't have API warnings

    # ... rest of the method
```

### Option 3: Both (Most Robust)
Add type checks in both places to ensure safety at multiple levels.

## Impact Scope

This bug affects ANY workflow that:
1. Uses HTTP node with GET method
2. Downloads non-JSON content (images, PDFs, binary files, plain text)
3. The response gets stored as a string in shared store

## Test to Confirm

```python
# Minimal test case
def test_binary_download_crash():
    # Create HTTP node that downloads an image
    node = HttpNode(params={"url": "https://via.placeholder.com/150", "method": "GET"})

    # Wrap with instrumented wrapper
    wrapped = InstrumentedNodeWrapper(node, "download")

    # Execute - this should crash
    shared = {}
    result = wrapped._run(shared)  # Should crash at line 867
```

## Summary

The root cause is a **type assumption violation**: The code assumes all successful node outputs are dictionaries, but binary downloads return strings. The crash occurs when trying to call dict methods on a string object.