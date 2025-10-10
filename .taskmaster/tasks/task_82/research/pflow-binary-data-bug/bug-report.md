# Bug Report: pflow Crashes When Processing Binary Image Data

## Executive Summary
pflow crashes with an AttributeError when executing a workflow that downloads and processes binary image data. The crash occurs after ~2 minutes of execution, suggesting the API calls are working but the framework fails when handling certain response types.

## Error Details

### Error Message
```
AttributeError: 'str' object has no attribute 'get'
```

### Full Traceback
```python
Traceback (most recent call last):
  File "/Users/andfal/projects/pflow/src/pflow/execution/executor_service.py", line 107, in execute_workflow
    action_result = flow.run(shared_store)
  File "/Users/andfal/projects/pflow/src/pflow/runtime/compiler.py", line 1113, in run_with_outputs
    result = original_run(shared_storage)
  File "/Users/andfal/projects/pflow/pocketflow/__init__.py", line 40, in run
    return self._run(shared)
           ~~~~~~~~~^^^^^^^^
  File "/Users/andfal/projects/pflow/pocketflow/__init__.py", line 112, in _run
    o = self._orch(shared)
  File "/Users/andfal/projects/pflow/pocketflow/__init__.py", line 106, in _orch
    last_action = curr._run(shared)
  File "/Users/andfal/projects/pflow/src/pflow/runtime/instrumented_wrapper.py", line 654, in _run
    warning_msg = self._detect_api_warning(shared)
  File "/Users/andfal/projects/pflow/src/pflow/runtime/instrumented_wrapper.py", line 774, in _detect_api_warning
    error_code = self._extract_error_code(output)
  File "/Users/andfal/projects/pflow/src/pflow/runtime/instrumented_wrapper.py", line 867, in _extract_error_code
    output.get("error_code"),
    ^^^^^^^^^^
AttributeError: 'str' object has no attribute 'get'
```

### Location of Crash
File: `src/pflow/runtime/instrumented_wrapper.py`
Line: 867
Method: `_extract_error_code`

## Reproduction Context

### Workflow Being Executed
- **File**: `.pflow/workflows/spotify-art-generator.json`
- **Nodes**: 19 total
- **Execution time before crash**: ~2 minutes

### Command Used
```bash
uv run pflow --trace .pflow/workflows/spotify-art-generator.json \
  sheet_id="1vON91vaoXqf4ITjHJd_yyMLLNK0R4FXVSfzGsi1o9_Y" \
  replicate_api_token="r8_YsSg0lSGVeWfl8QaSQy1oCoRLVBlRTa3yTouD"
```

### Workflow Execution Progress
Based on the 2-minute runtime and the workflow structure, the crash likely occurred around these nodes:

1. ✅ fetch-sheets (Google Sheets API)
2. ✅ extract-data (LLM)
3. ✅ fetch-artwork (Spotify oEmbed)
4. ✅ download-logo (Google Drive MCP)
5. ✅ enhance-prompt (LLM)
6. ✅ gen-seedream-orig (Replicate API - returns JSON)
7. ✅ gen-seedream-enhanced (Replicate API - returns JSON)
8. ✅ gen-nano-orig (Replicate API - returns JSON)
9. ✅ gen-nano-enhanced (Replicate API - returns JSON)
10. ✅ sanitize-filename (LLM)
11. ⚠️ download-seedream-orig (HTTP GET for binary image) <- LIKELY CRASH POINT
12. ❌ save-seedream-orig (write-file)
13. ❌ ... (remaining nodes)

## Suspected Root Cause

The crash occurs in `instrumented_wrapper.py` when trying to call `.get()` on what it expects to be a dict but is actually a string. This happens in the `_extract_error_code` method.

### The Problematic Node Pattern
```json
{
  "id": "download-seedream-orig",
  "type": "http",
  "params": {
    "url": "${gen-seedream-orig.response.output[0]}",
    "method": "GET"
  }
}
```

This node is downloading a binary image file from a URL like:
`https://replicate.delivery/pbxt/some-id/out-0.png`

### Why It's Failing

1. **Binary Response**: The HTTP node returns binary image data (PNG/JPEG) as the response
2. **Type Assumption**: The instrumented_wrapper assumes all HTTP responses are JSON-like dicts
3. **Error Detection Logic**: The `_extract_error_code` method tries to call `.get("error_code")` on the response
4. **String vs Dict**: Binary data might be returned as a string (base64 or raw bytes converted to string), causing the AttributeError

## Code Analysis

Looking at line 867 in `instrumented_wrapper.py`:
```python
def _extract_error_code(self, output):
    output.get("error_code"),  # Line 867 - assumes output is a dict
```

The method assumes `output` is always a dictionary, but when downloading binary files via HTTP GET, the output is likely a string containing the binary data.

## Verification Steps

1. Check `src/pflow/runtime/instrumented_wrapper.py` lines 860-875 to see the full `_extract_error_code` method
2. Check how the HTTP node handles binary responses
3. Look for type checking before calling `.get()`
4. Test with a simple workflow that just downloads an image:
   ```json
   {
     "nodes": [{
       "id": "download-image",
       "type": "http",
       "params": {
         "url": "https://via.placeholder.com/150",
         "method": "GET"
       }
     }]
   }
   ```

## Proposed Fix

Add type checking in `_extract_error_code`:
```python
def _extract_error_code(self, output):
    if not isinstance(output, dict):
        return None  # or handle binary/string responses appropriately
    return output.get("error_code")
```

## Additional Context

### Related Patterns
- The workflow uses "Prefer: wait" headers for synchronous Replicate API calls
- All Replicate responses return JSON with an `output` array containing image URLs
- The crash only happens when trying to download the actual image files

### Environment
- Platform: macOS (darwin)
- Python: 3.9+
- pflow version: Latest from main branch
- Date: 2025-10-10

## Impact
This bug prevents any workflow that:
1. Downloads binary files via HTTP
2. Processes images from external URLs
3. Handles non-JSON responses from HTTP nodes

This is a critical issue for real-world workflows that need to download and save files.