# Feature: binary_data_support

## Objective

Enable binary file handling across pflow nodes via base64 encoding.

## Requirements

- Must detect binary content in HTTP, read-file, shell nodes
- Must encode binary data as base64 strings in shared store
- Must use `_is_binary` suffix flags for binary detection
- Must decode base64 in consumer nodes (write-file, shell)
- Must preserve backward compatibility for text workflows
- Must handle files up to 50MB without failure
- Must provide clear errors for malformed base64

## Scope

- Does not modify template resolution system
- Does not add streaming or chunking for large files
- Does not change shared store structure
- Does not require planner modifications
- Does not support partial binary downloads
- Does not add binary format conversions

## Inputs

- `content_type`: str - HTTP Content-Type header for binary detection
- `file_path`: str - File path for extension-based binary detection
- `binary_data`: bytes - Raw binary data to encode
- `base64_string`: str - Base64-encoded data to decode
- `is_binary_flag`: bool - Explicit binary indicator flag

## Outputs

Returns: Modified shared store entries with base64 strings and binary flags

Side effects:
- `shared["response"]`: str - Base64 string when binary
- `shared["response_is_binary"]`: bool - True when binary
- `shared["content"]`: str - Base64 string when binary
- `shared["content_is_binary"]`: bool - True when binary
- `shared["stdout"]`: str - Base64 string when binary
- `shared["stdout_is_binary"]`: bool - True when binary
- Binary files written to disk in binary mode

## Structured Formats

```json
{
  "binary_contract": {
    "encoding": "base64",
    "flag_suffix": "_is_binary",
    "max_size_mb": 50,
    "mime_types_binary": [
      "image/*", "video/*", "audio/*",
      "application/pdf", "application/octet-stream",
      "application/zip", "application/gzip"
    ]
  },
  "node_changes": {
    "http": ["detect_binary", "encode_response", "set_flag"],
    "write_file": ["check_flag", "decode_content", "binary_mode"],
    "read_file": ["detect_binary", "encode_content", "set_flag"],
    "shell": ["detect_binary", "encode_stdout", "set_flags"]
  }
}
```

## State/Flow Changes

- `text_data` → `base64_encoded` when binary detected
- `base64_encoded` → `binary_bytes` when flag present
- `write_mode_text` → `write_mode_binary` when bytes received
- `encoding_utf8` → `encoding_none` when binary mode

## Constraints

- Base64 overhead ≤ 33% of original size
- Binary detection time ≤ 10ms
- Decode errors must not crash workflow
- Flag names must use `_is_binary` suffix only
- Binary files must preserve exact byte sequence

## Rules

1. HTTP node detects binary via Content-Type header containing binary MIME types
2. HTTP node encodes response.content as base64 when binary detected
3. HTTP node sets response_is_binary to true when binary detected
4. Write-file node checks content_is_binary flag before processing
5. Write-file node decodes base64 when content_is_binary is true
6. Write-file node uses wb mode when writing decoded bytes
7. Read-file node detects binary via file extension or UnicodeDecodeError
8. Read-file node reads file in rb mode when binary detected
9. Read-file node encodes content as base64 when binary
10. Read-file node sets content_is_binary to true when binary
11. Shell node catches UnicodeDecodeError on stdout decode
12. Shell node encodes stdout as base64 when decode fails
13. Shell node sets stdout_is_binary to true when binary
14. All nodes ignore missing binary flags for backward compatibility
15. All nodes preserve original data when binary flag is false

## Edge Cases

- Empty binary file → base64 empty string with flag true
- Text file with .png extension → detect via content not extension
- Malformed base64 string → raise ValueError with clear message
- Missing binary flag → treat as text for compatibility
- Binary content without flag → corruption accepted for compatibility
- Mixed stdout/stderr in shell → handle each stream independently
- Content-Type application/json with binary → follow Content-Type
- File without extension → attempt text read first
- Base64 decode padding error → include padding fix suggestion

## Error Handling

- UnicodeDecodeError in read-file → switch to binary mode automatically
- Base64 decode error → raise ValueError with input snippet
- File not found → standard FileNotFoundError unchanged
- Binary file exceeds 50MB → log warning but continue
- Content-Type missing → assume text unless extension indicates binary

## Non-Functional Criteria

- Binary detection ≤ 10ms per node
- Base64 encoding ≤ 100MB/s throughput
- Memory usage ≤ 2.33x file size during processing
- Error messages include first 100 chars of problematic input

## Examples

### HTTP Binary Download
```python
# Input: Response with image/png content-type
response.headers = {"content-type": "image/png"}
response.content = b'\x89PNG\r\n\x1a\n...'

# Output in shared store:
shared["response"] = "iVBORw0KGgo..."  # base64
shared["response_is_binary"] = True
```

### Write-File Binary Decode
```python
# Input from shared store:
shared["content"] = "iVBORw0KGgo..."
shared["content_is_binary"] = True

# Action: Decode and write
content = base64.b64decode(shared["content"])
with open(path, "wb") as f:
    f.write(content)
```

## Test Criteria

1. HTTP node with image/png content-type produces base64 string
2. HTTP node with image/png sets response_is_binary to true
3. HTTP node with text/plain keeps response as text
4. Write-file with base64 and flag writes valid binary file
5. Write-file without flag writes base64 string as text
6. Write-file with malformed base64 raises ValueError
7. Read-file with .png extension returns base64 string
8. Read-file with .png sets content_is_binary to true
9. Read-file with .txt returns plain text string
10. Shell with binary stdout returns base64 string
11. Shell with binary stdout sets stdout_is_binary to true
12. Shell with text stdout returns plain text
13. Empty binary file produces empty base64 with flag
14. Mixed binary/text workflow preserves both types
15. 10MB binary file completes within memory limits
16. Missing flag treated as text for backward compatibility
17. Binary without flag causes corruption but no crash
18. Base64 padding error provides fix suggestion

## Notes (Why)

- Base64 chosen over direct bytes to avoid template resolver modifications requiring return type changes
- Explicit flags chosen over heuristics because auto-detection via content inspection is unreliable
- _is_binary suffix prevents collision with user data keys
- 50MB limit balances memory usage with practical file sizes
- Backward compatibility critical for existing text workflows

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 3                       |
| 2      | 1                          |
| 3      | 2                          |
| 4      | 4, 5                       |
| 5      | 4                          |
| 6      | 4                          |
| 7      | 7, 9                       |
| 8      | 7                          |
| 9      | 7                          |
| 10     | 8                          |
| 11     | 10, 12                     |
| 12     | 10                         |
| 13     | 11                         |
| 14     | 16                         |
| 15     | 3, 5, 9, 12                |

## Versioning & Evolution

- **Version:** 1.0.0
- **Changelog:**
  - 1.0.0 - Initial binary support via base64 encoding contract

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes Python base64 module available in all environments
- Assumes shared store remains in-memory dictionary
- Assumes Content-Type headers accurately reflect content
- Unknown: Actual memory ceiling on user systems
- Unknown: Performance impact on workflows with many binary files

### Conflicts & Resolutions

- Template resolver calls str() on bytes → Resolution: Use base64 strings instead of bytes
- Namespacing prevents metadata passing → Resolution: Use key suffix convention (_is_binary)
- Direct bytes would require template system changes → Resolution: Accepted base64 overhead

### Decision Log / Tradeoffs

- Base64 encoding vs direct bytes: Chose base64 to avoid core system changes (33% overhead accepted)
- Auto-detection vs explicit flags: Chose flags for determinism (requires coordinated changes)
- All nodes vs HTTP/write-file only: Chose all nodes for consistency (larger scope accepted)
- Streaming vs in-memory: Chose in-memory for MVP simplicity (50MB limit accepted)

### Ripple Effects / Impact Map

- Template variables containing binary become base64 strings (visible to users in traces)
- Shared store inspection shows base64 blobs instead of readable text
- Memory usage increases by 33% for binary data
- All 4 node types require coordinated release
- Future streaming support will require contract revision

### Residual Risks & Confidence

- Risk: Users confused by base64 in template variables. Mitigation: Document clearly. Confidence: Medium
- Risk: Memory exhaustion with multiple large files. Mitigation: 50MB warning. Confidence: Medium
- Risk: Binary detection false positives. Mitigation: Explicit Content-Type priority. Confidence: High
- Risk: Backward compatibility break. Mitigation: Missing flags default to text. Confidence: High
- Overall confidence in implementation: High

### Epistemic Audit (Checklist Answers)

1. Assumed base64 module universally available; wrong = implementation fails
2. Wrong assumption breaks core functionality requiring alternative encoding
3. Prioritized robustness (explicit flags) over elegance (auto-detection)
4. All rules mapped to tests; all tests cover rules
5. Touches 4 nodes, shared store inspection, template visibility, memory profile
6. Memory ceiling uncertain; performance impact unmeasured; Confidence: Medium-High