# Workflow Context for Bug Investigation

## The Failing Workflow Structure

The workflow that triggers the bug has this specific pattern where it:
1. Calls APIs that return JSON with image URLs
2. Then tries to download those images as binary data
3. Then tries to save the binary data to files

## Key Node Sequence That Causes Crash

### Working: Replicate API Call (returns JSON)
```json
{
  "id": "gen-seedream-orig",
  "type": "http",
  "params": {
    "url": "https://api.replicate.com/v1/predictions",
    "method": "POST",
    "headers": {
      "Authorization": "Bearer ${replicate_api_token}",
      "Content-Type": "application/json",
      "Prefer": "wait"
    },
    "body": {
      "version": "054cd8c667f535616fd66710ce20c8949bf64ac3d9a3459e338f026424be8bec",
      "input": {
        "prompt": "...",
        "image_input": ["..."],
        "size": "2K"
      }
    }
  }
}
```

This returns JSON like:
```json
{
  "output": ["https://replicate.delivery/pbxt/xyz/out-0.png"],
  "status": "succeeded",
  ...
}
```

### FAILING: Image Download (expects binary, crashes)
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

This tries to download the actual PNG file from the URL, which returns binary data, not JSON.

### Never Reached: Save Binary to File
```json
{
  "id": "save-seedream-orig",
  "type": "write-file",
  "params": {
    "file_path": "generated-images/${sanitize-filename.response}-seedream-original.jpg",
    "content": "${download-seedream-orig.response}"
  }
}
```

## The Problem Pattern

The issue appears when:
1. HTTP node with GET method
2. URL points to an image/binary file
3. No Content-Type header specified (defaults to expecting JSON?)
4. Response is binary data (PNG/JPEG)
5. instrumented_wrapper tries to check for error_code in the "response"
6. Assumes response is dict, but it's a string/bytes

## Test Case for Reproduction

Minimal workflow to reproduce:
```json
{
  "inputs": {
    "image_url": {
      "type": "string",
      "required": true,
      "description": "URL of an image to download"
    }
  },
  "nodes": [
    {
      "id": "download",
      "type": "http",
      "params": {
        "url": "${image_url}",
        "method": "GET"
      }
    },
    {
      "id": "save",
      "type": "write-file",
      "params": {
        "file_path": "test.jpg",
        "content": "${download.response}"
      }
    }
  ],
  "edges": [
    {"from": "download", "to": "save"}
  ]
}
```

Run with:
```bash
uv run pflow test-binary.json image_url="https://via.placeholder.com/150"
```

## Expected vs Actual Behavior

### Expected
- HTTP node should handle binary responses
- Binary data should be passable to write-file node
- Files should be saved successfully

### Actual
- HTTP node retrieves binary data
- instrumented_wrapper crashes trying to call .get() on non-dict
- Workflow fails with AttributeError

## Questions for Investigation

1. How is the HTTP node supposed to handle binary responses?
2. Is there a way to specify expected response type (json/binary/text)?
3. Should instrumented_wrapper type-check before accessing dict methods?
4. Are there other nodes that might have similar issues with non-JSON responses?

## Related Files to Check

- `src/pflow/nodes/http/` - HTTP node implementation
- `src/pflow/runtime/instrumented_wrapper.py` - Where the crash occurs
- `src/pflow/nodes/file/write_file.py` - How write-file expects to receive binary data

## Workaround Attempts

None successful. The workflow cannot proceed past the first binary download.

## Full Workflow File

The complete failing workflow is saved at:
`.pflow/workflows/spotify-art-generator.json`

Key characteristics:
- 19 nodes total
- 4 image downloads (all would fail)
- Mix of JSON API calls and binary downloads
- Uses template variables extensively
- Combines multiple external services