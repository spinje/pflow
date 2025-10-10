# Task 82: Implement System-Wide Binary Data Support

## ID
82

## Title
Implement System-Wide Binary Data Support

## Description
Add comprehensive binary data support to pflow by implementing a base64 encoding contract across all file-handling nodes. This enables workflows to download, process, and save binary files (images, PDFs, etc.) which currently fail with encoding errors. The solution uses base64 encoding in the shared store with explicit binary flags for cross-node communication.

## Status
not started

## Dependencies
None
<!-- This is a new feature that doesn't depend on other incomplete tasks -->
<!-- The bug fix for InstrumentedWrapper crash can be done independently first -->

## Priority
high

## Details
Currently, pflow cannot handle binary data - HTTP nodes corrupt binary responses using `response.text`, write-file nodes can't write binary mode, and read-file nodes throw UnicodeDecodeError on binary files. This task implements a system-wide base64 encoding contract to enable binary workflows.

### Core Problem
The shared store can handle any Python type (including bytes), but:
1. Template resolution calls `str()` on all values, corrupting bytes
2. Nodes don't detect or handle binary content
3. No consistent pattern for binary data across nodes
4. Workflows like downloading images fail completely

### Solution: Base64 Encoding Contract
All nodes will follow this contract for binary data:

1. **Producer nodes** (HTTP, read-file, shell) detect binary content and:
   - Encode binary data as base64 strings
   - Store with `_is_binary` suffix flag (e.g., `response_is_binary: true`)

2. **Consumer nodes** (write-file, HTTP POST, shell stdin) check binary flags and:
   - Decode base64 when `_is_binary` flag is present
   - Handle both text and binary transparently

### Implementation Scope (4 Core Nodes)

#### 1. HTTP Node (`src/pflow/nodes/http/http.py`)
- Detect binary content-types (image/*, application/pdf, application/octet-stream, etc.)
- Use `response.content` for binary (not `response.text`)
- Base64 encode and set `response_is_binary` flag
- Update Interface declaration

#### 2. Write-File Node (`src/pflow/nodes/file/write_file.py`)
- Check `content_is_binary` flag
- Base64 decode if present
- Use binary write mode (`wb`) for decoded bytes
- Update Interface declaration

#### 3. Read-File Node (`src/pflow/nodes/file/read_file.py`)
- Detect binary files (by extension or magic bytes)
- Read in binary mode when detected
- Base64 encode and set `content_is_binary` flag
- Graceful fallback for encoding errors

#### 4. Shell Node (`src/pflow/nodes/shell/shell.py`)
- Handle binary stdout (detect decoding failures)
- Base64 encode binary output
- Set `stdout_is_binary` and `stderr_is_binary` flags
- Support binary stdin from other nodes

### Key Design Decisions
- **Base64 over direct bytes**: Avoids template resolution changes to core system
- **Explicit flags over auto-detection**: More robust than heuristics
- **System-wide contract**: All nodes follow same pattern for consistency
- **Backward compatible**: Text-only workflows unchanged
- **MVP approach**: No streaming, all in-memory (document size limits)

### Interface Documentation Updates
```python
# Example for HTTP node:
"""
Interface:
- Writes: shared["response"]: str  # Text or base64-encoded binary
- Writes: shared["response_is_binary"]: bool  # True if response is binary
"""
```

### Binary Detection Logic

#### HTTP Node
- Check Content-Type header for binary MIME types
- List: image/*, video/*, audio/*, application/pdf, application/octet-stream, application/zip

#### Read-File Node
- Check file extension (.png, .jpg, .pdf, .zip, etc.)
- Fallback: Try text read, catch UnicodeDecodeError

#### Shell Node
- Try UTF-8 decode, catch UnicodeDecodeError
- Binary commands: tar, gzip, base64, etc.

### Memory Considerations
- Base64 adds ~33% size overhead
- 10MB image → 13.3MB base64 string
- Document recommended limits (e.g., <50MB files)
- Future: Consider temp files for large binaries (post-MVP)

### Workflow Examples That Will Work
1. **Download and save image**: HTTP (download) → write-file (save as binary)
2. **Process binary file**: read-file (PDF) → shell (pdftotext) → write-file
3. **Binary round-trip**: read-file → HTTP POST → HTTP GET → write-file
4. **Archive creation**: shell (tar) → write-file (save .tar.gz)

## Test Strategy
Comprehensive testing across all binary-supporting nodes:

### Unit Tests (Per Node)
- **HTTP**: Mock binary response (image/png), verify base64 encoding and flag
- **Write-file**: Pass base64 with flag, verify binary file written correctly
- **Read-file**: Read test PNG file, verify base64 encoding and flag
- **Shell**: Binary command output (e.g., `echo -n "\x89PNG"`), verify encoding

### Integration Tests
- **End-to-end binary workflow**: HTTP download image → write-file saves correctly
- **Binary round-trip**: read-file (PNG) → write-file (copy), verify integrity
- **Mixed text/binary workflow**: Ensure both data types work in same workflow
- **Large file handling**: Test with 10MB+ files, verify memory usage acceptable

### Edge Cases
- Missing binary flags (backward compatibility)
- Malformed base64 data (clear error messages)
- Empty binary data
- Binary/text detection boundary cases
- Content-type mismatches

### Validation
- Test with real Spotify workflow (`.pflow/workflows/spotify-art-generator.json`)
- Verify downloaded album art matches original
- No regression in text-only workflows