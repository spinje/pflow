# Bug Investigation: Binary Data Crash in pflow

## Quick Summary

**BUG**: pflow crashes when HTTP nodes download binary files (images, PDFs, etc.)

**ROOT CAUSE**: `instrumented_wrapper.py` assumes all node outputs are dicts, but binary downloads return strings

**CRASH LOCATION**: Line 867 in `src/pflow/runtime/instrumented_wrapper.py`

## Files in This Investigation

1. **bug-report.md** - Initial bug report with full context and error details
2. **workflow-context.md** - The workflow structure that triggers the bug
3. **code-analysis.md** - Detailed analysis of the root cause with line numbers
4. **README.md** - This summary file

## The Bug in One Sentence

When downloading binary files, the HTTP node returns a string, but `_extract_error_code()` tries to call `.get()` on it, causing an AttributeError.

## Quick Fix

Add this type check at the beginning of `_extract_error_code()`:

```python
def _extract_error_code(self, output: dict) -> Optional[str]:
    """Extract error code from various API response formats."""
    # FIX: Add type safety for binary responses
    if not isinstance(output, dict):
        return None

    # Rest of existing code...
```

## How to Reproduce

1. Create any workflow that downloads an image:
```json
{
  "nodes": [{
    "id": "download",
    "type": "http",
    "params": {
      "url": "https://via.placeholder.com/150",
      "method": "GET"
    }
  }]
}
```

2. Run it:
```bash
uv run pflow test.json
```

3. Watch it crash with:
```
AttributeError: 'str' object has no attribute 'get'
```

## Why This Matters

This bug makes it impossible to:
- Download and save images
- Process binary files
- Work with non-JSON HTTP responses
- Build real-world workflows that handle media files

## Investigation Path

The investigation revealed several issues with the current implementation:

1. **Type assumptions**: Code assumes successful responses are always dicts
2. **Missing type checks**: No validation before calling dict methods
3. **Binary data handling**: HTTP node's binary response handling unclear
4. **Documentation gap**: Agent instructions don't cover binary data workflows

## Recommendations

1. **Immediate Fix**: Add type check in `_extract_error_code()`
2. **Better Fix**: Add type check in `_detect_api_warning()` too
3. **Long-term**: Review all places that assume node outputs are dicts
4. **Documentation**: Update agent instructions about binary data handling

## Context for Fixing Agent

The workflow that exposed this bug was trying to:
1. Generate AI images using Replicate API (returns JSON with image URLs)
2. Download those images (returns binary data) <- CRASHES HERE
3. Save them to local files

The crash happens at step 2 when the first binary download completes and the wrapper tries to check it for API errors.

## File Locations

- **Bug location**: `src/pflow/runtime/instrumented_wrapper.py:867`
- **Failing workflow**: `.pflow/workflows/spotify-art-generator.json`
- **Test with**: Any URL returning binary data (images, PDFs, etc.)