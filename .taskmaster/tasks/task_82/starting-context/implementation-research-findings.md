# Task 82: Critical Implementation Research Findings

## Executive Summary

This document contains critical findings from deep investigation into pflow's architecture that directly impact binary support implementation. **Read this before implementing to avoid major pitfalls.**

---

## 1. CRITICAL: Namespacing Blocks Metadata Passing

### The Problem You'll Hit

You might think you can do this:
```python
# HTTP node
shared["response"] = base64_string
shared["response_encoding"] = "base64"  # ❌ WILL NOT WORK

# Write-file node
if shared.get("response_encoding") == "base64":  # ❌ NEVER SEES THIS
    content = base64.b64decode(content)
```

### Why It Fails

With namespacing enabled (default), nodes write to isolated namespaces:
- HTTP writes to: `shared["http_node_id"]["response"]`
- Write-file can only see: `shared["write_file_id"]["*"]` and root `shared["*"]`
- Write-file NEVER sees: `shared["http_node_id"]["response_encoding"]`

### The Solution: Suffix Convention

Use `_is_binary` suffix on the SAME key:
```python
# HTTP node
shared["response"] = base64_string
shared["response_is_binary"] = True  # ✅ SAME namespace

# Template: ${download.response} and ${download.response_is_binary}
# Both resolve correctly through template system
```

**Source**: `src/pflow/runtime/namespaced_store.py:43-69`

---

## 2. Template Resolution Already Handles Everything

### Key Insight

Templates are resolved BEFORE node execution by `TemplateAwareNodeWrapper`. The template system has FULL access to the entire shared store, bypassing namespace isolation.

### Data Flow
```
shared["download"]["response"] = "base64string"
shared["download"]["response_is_binary"] = True
                    ↓
Template: "content": "${download.response}"
          "content_is_binary": "${download.response_is_binary}"
                    ↓
TemplateAwareNodeWrapper resolves BOTH before node sees them
                    ↓
Write-file.prep() receives: {"content": "base64string", "content_is_binary": True}
```

**Source**: `src/pflow/runtime/node_wrapper.py:195-235`

---

## 3. Why NOT Direct Bytes (Critical Context)

### We Considered Direct Bytes First

The shared store CAN handle bytes perfectly - it's just a Python dict. The ONLY blocker is one line:

**File**: `src/pflow/runtime/template_resolver.py`
**Line**: 284
```python
else:
    return str(value)  # Converts bytes to "b'\\x89PNG...'" - CORRUPTED!
```

### Why We Chose Base64 Instead

Fixing template resolution for bytes would require:
1. Changing return type of `resolve_string()` from `str` to `Any`
2. Updating all type hints through the wrapper chain
3. Testing impacts on complex templates like `"Hello ${name}"`
4. Verifying no downstream code expects strings

**Decision**: Base64 avoids touching core template system (lower risk for MVP).

---

## 4. Binary Detection Logic (Tested Patterns)

### HTTP Node - Content-Type Detection

```python
# Line to modify: src/pflow/nodes/http/http.py:126-137
content_type = response.headers.get("content-type", "").lower()

# Binary detection (add this)
BINARY_CONTENT_TYPES = [
    "image/", "video/", "audio/",
    "application/pdf", "application/octet-stream",
    "application/zip", "application/gzip", "application/x-tar"
]
is_binary = any(ct in content_type for ct in BINARY_CONTENT_TYPES)

if is_binary:
    response_data = response.content  # bytes - DO NOT USE response.text
else:
    # Existing JSON/text logic
```

### Read-File Node - Extension + Fallback

```python
# Binary extensions
BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.tar', '.gz'}

file_ext = Path(file_path).suffix.lower()
is_binary = file_ext in BINARY_EXTENSIONS

if is_binary:
    content = Path(file_path).read_bytes()
else:
    try:
        content = Path(file_path).read_text(encoding=encoding)
    except UnicodeDecodeError:
        # Fallback for binary files without standard extension
        content = Path(file_path).read_bytes()
        is_binary = True
```

### Shell Node - Decode Detection

```python
try:
    stdout_text = stdout_bytes.decode('utf-8')
    stdout_is_binary = False
except UnicodeDecodeError:
    stdout_text = base64.b64encode(stdout_bytes).decode('ascii')
    stdout_is_binary = True
```

---

## 5. Exact Locations to Modify

### HTTP Node
- **File**: `src/pflow/nodes/http/http.py`
- **exec() method**: Lines 115-145 (add binary detection)
- **post() method**: Lines 168-174 (add base64 encoding and flag)
- **Interface docstring**: Lines 11-37 (document new outputs)

### Write-File Node
- **File**: `src/pflow/nodes/file/write_file.py`
- **prep() method**: Lines 65-83 (check flag, decode base64)
- **exec() method**: Lines 118-157 (add binary mode write)
- **Interface docstring**: Lines 21-37 (document binary support)

### Read-File Node
- **File**: `src/pflow/nodes/file/read_file.py`
- **exec() method**: Lines 67-112 (add binary detection and reading)
- **post() method**: Lines 134-141 (add base64 encoding and flag)
- **Interface docstring**: Lines 13-27 (document new outputs)

### Shell Node
- **File**: `src/pflow/nodes/shell/shell.py`
- **exec() method**: Lines 425-487 (handle binary stdout/stderr)
- **post() method**: Lines 516-524 (add base64 encoding and flags)
- **Interface docstring**: Lines 38-152 (document binary support)

---

## 6. Memory and Performance Constraints

### Base64 Overhead
- 33% size increase (10MB file → 13.3MB base64)
- Python's base64 module is C-optimized (fast)
- All data kept in memory for workflow duration

### Current System Limits
- **No hard limits** in shared store (it's just a dict)
- **Trace limits** only affect debug output, not execution
- `PFLOW_TRACE_SHARED_MAX=1000000` (default) for debug traces only

### Recommendations
- Document 50MB soft limit for binary files
- Log warning for files >50MB but don't fail
- Future: Consider temp files for >100MB (post-MVP)

**Source**: Investigation found NO size limits in execution path

---

## 7. Testing Patterns That Work

### Unit Test Pattern
```python
def test_http_binary_response():
    """Test HTTP node handles binary response correctly."""
    with patch("requests.request") as mock_request:
        # Mock binary response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        mock_response.text = "corrupted text representation"
        mock_response.elapsed = timedelta(seconds=0.1)
        mock_request.return_value = mock_response

        node = HttpNode()
        shared = {"url": "https://example.com/image.png", "method": "GET"}
        action = node.run(shared)

        # Verify base64 encoding
        assert action == "default"
        assert shared["response"] == base64.b64encode(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR').decode('ascii')
        assert shared["response_is_binary"] is True
```

### Integration Test Pattern
```python
def test_http_to_write_file_binary_workflow():
    """Test complete binary workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup workflow
        workflow = {
            "nodes": [
                {"id": "download", "type": "http", "params": {"url": "${url}"}},
                {"id": "save", "type": "write-file", "params": {
                    "file_path": f"{tmpdir}/image.png",
                    "content": "${download.response}",
                    "content_is_binary": "${download.response_is_binary}"
                }}
            ],
            "edges": [{"from": "download", "to": "save"}]
        }

        # Run with mocked HTTP
        with patch("requests.request") as mock:
            # ... setup mock ...
            result = compile_and_run(workflow, {"url": "test.png"})

        # Verify file integrity
        saved_file = Path(f"{tmpdir}/image.png")
        assert saved_file.read_bytes() == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
```

---

## 8. Interface Declaration Format

### IMPORTANT: How to Document Binary Support

Use union types with clear descriptions:

```python
"""
Interface:
- Writes: shared["response"]: str  # Text or base64-encoded binary
- Writes: shared["response_is_binary"]: bool  # True if response is binary
- Writes: shared["status_code"]: int
- Writes: shared["response_headers"]: dict
"""
```

**Note**: The type remains `str` because base64 IS a string. The description clarifies the content.

---

## 9. Backward Compatibility Requirements

### Critical Rules

1. **Missing flags = text mode** (don't break existing workflows)
```python
is_binary = shared.get("content_is_binary", False)  # Default False
```

2. **Text data with flag = ignore flag** (defensive)
```python
if is_binary and looks_like_base64(content):
    content = base64.b64decode(content)
```

3. **No changes to existing text paths** (preserve behavior)
```python
if not is_binary:
    # Existing text logic unchanged
```

---

## 10. Common Pitfalls to Avoid

### ❌ DON'T: Try to Pass Metadata Between Nodes
```python
# This WILL NOT work due to namespacing
shared["encoding_type"] = "base64"  # Different namespace!
```

### ❌ DON'T: Use response.text for Binary
```python
response_data = response.text  # Corrupts binary!
```

### ❌ DON'T: Forget Binary Flags in Templates
```json
{
  "params": {
    "content": "${download.response}",
    // Must ALSO include:
    "content_is_binary": "${download.response_is_binary}"
  }
}
```

### ❌ DON'T: Assume Text Mode in Tests
Always test both binary and text paths in the same test file.

---

## 11. Validation with Real Workflow

The actual failing workflow is at:
`.pflow/workflows/spotify-art-generator.json`

Key nodes to test:
1. `gen-seedream-orig` - Returns JSON with image URL
2. `download-seedream-orig` - Downloads binary image (CRASH POINT)
3. `save-seedream-orig` - Saves to file

After implementation, run:
```bash
uv run pflow --trace .pflow/workflows/spotify-art-generator.json \
  sheet_id="1vON91vaoXqf4ITjHJd_yyMLLNK0R4FXVSfzGsi1o9_Y"
```

Success = Album art images saved correctly to `generated-images/` directory.

---

## 12. Architecture Documents to Reference

- `src/pflow/runtime/CLAUDE.md` - Wrapper chain and template resolution
- `architecture/core-concepts/shared-store.md` - Shared store patterns
- `pocketflow/docs/core_abstraction/communication.md` - Inter-node communication

---

## Key Takeaways for Implementation

1. **Use `_is_binary` suffix convention** - only reliable cross-node communication
2. **Base64 encode in producer nodes, decode in consumers** - avoids template issues
3. **Always check binary flag with .get(key, False)** - backward compatibility
4. **Test both binary and text in same workflow** - ensure no regression
5. **Document clearly in Interface section** - other devs need to understand

---

**Remember**: The shared store supports ANY Python type. We're using base64 strings only to avoid modifying the template resolver. This is a pragmatic choice for MVP, not a technical limitation.