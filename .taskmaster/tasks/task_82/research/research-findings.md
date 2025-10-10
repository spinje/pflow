# Research Findings: Binary Data Bug Fix

**Date**: 2025-10-10
**Session**: 13578c48-fd00-42db-a4f5-b82e49d22fd9
**Bug**: AttributeError when downloading binary files (images, PDFs, etc.)

---

## Executive Summary

The bug report identified a crash at `instrumented_wrapper.py:867` when downloading binary files. Research reveals this is **not just a simple type-check issue** - it's exposing a fundamental gap: **pflow currently has NO binary data support**.

### Critical Findings

1. ✅ **Immediate Bug**: InstrumentedWrapper assumes all outputs are dicts (line 774-775)
2. ⚠️ **Deeper Issue**: HTTP node corrupts binary data by using `response.text` instead of `response.content`
3. ⚠️ **Missing Feature**: Write-file only supports text mode, cannot write binary files
4. ⚠️ **No Pattern**: Zero convention or documentation for binary data in shared store
5. ⚠️ **No Tests**: Complete absence of binary data test coverage

### Fix Strategy

**Phase 1 (Immediate)**: Add type guards to prevent crashes
**Phase 2 (Complete)**: Implement proper binary data support across HTTP, write-file, and shared store

---

## 1. HTTP Node Binary Handling Analysis

**File**: `src/pflow/nodes/http/http.py`

### Current Implementation (BROKEN for Binary)

**Response Type Detection** (lines 126-137):
```python
content_type = response.headers.get("content-type", "").lower()
is_json = "json" in content_type

if is_json:
    try:
        response_data = response.json()
    except (ValueError, json.JSONDecodeError):
        response_data = response.text
else:
    response_data = response.text  # ← LINE 137: CORRUPTS BINARY DATA
```

**The Problem**:
- `response.text` decodes bytes using UTF-8 encoding
- Binary data (PNG, JPEG, PDF) contains invalid UTF-8 sequences
- Results in `UnicodeDecodeError` or corrupted mojibake characters
- No detection for binary content-types (image/*, application/pdf, etc.)

**Output Structure** (lines 168-174):
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    shared["response"] = exec_res["response"]  # Stored directly, not wrapped
    shared["status_code"] = exec_res["status_code"]
    shared["response_headers"] = exec_res["headers"]
    shared["response_time"] = exec_res.get("duration", 0)
```

**Key Finding**: Response data stored directly in `shared["response"]`, not wrapped in dict.

### What Binary Downloads Actually Return

| Content-Type | Current Behavior | Result |
|--------------|------------------|--------|
| `application/json` | `response.json()` → dict | ✅ Works |
| `text/plain` | `response.text` → str | ✅ Works |
| `image/png` | `response.text` → corrupted str | ❌ Broken |
| `application/pdf` | `response.text` → corrupted str | ❌ Broken |

**Evidence from Documentation** (`architecture/mcp-guide.md:274`):
```markdown
Future enhancements will add:
- HTTP/SSE transports
- Binary content (images, files)  # ← Explicitly planned for future
```

**Conclusion**: Binary handling intentionally omitted from MVP.

---

## 2. InstrumentedWrapper Type Assumptions Analysis

**File**: `src/pflow/runtime/instrumented_wrapper.py`

### The Bug Location

**Call Chain**:
```
_run() line 654
  ↓
_detect_api_warning(shared) line 654
  ↓
output = shared.get(self.node_id) line 763
  ↓
output = _unwrap_mcp_response(output) line 769
  ↓
error_code = _extract_error_code(output) line 774  ← CRASH HERE
```

### Root Cause: Line 834

**In `_unwrap_mcp_response()`**:
```python
# Line 829-838
if "response" in output and "status_code" in output:
    status_code = output.get("status_code", 200)
    if 200 <= status_code < 300:
        return output.get("response")  # ← CAN RETURN ANY TYPE
    return None

return output
```

**The Issue**:
- Line 834 returns `output.get("response")` which is the HTTP node's response field
- This can be: dict (JSON), str (text/binary), list (JSON array), int, bool, None
- Line 774-775 then call dict-assuming methods **without type checking**:

```python
output = self._unwrap_mcp_response(output)
if not output:
    return None

# NO TYPE CHECK - just existence check!
error_code = self._extract_error_code(output)     # Expects dict
error_msg = self._extract_error_message(output)   # Expects dict
```

### All Dict Assumptions Found

**UNSAFE - No Runtime Type Guards**:

1. **`_extract_error_code()`** (lines 867-872): 6 × `.get()` calls
2. **`_check_boolean_error_flags()`** (lines 890-906): 5 × `.get()` calls
3. **`_check_status_field()`** (line 919): 1 × `.get()` call
4. **`_check_graphql_errors()`** (lines 933-934): 2 × dict accesses
5. **`_extract_error_message()`** (lines 970-971): 1 × `.get()` call

**All called from `_detect_api_warning()` after unwrapping**, assuming result is dict.

### Purpose of API Warning Detection

**From code analysis**:
- **Goal**: Detect API responses that succeeded technically (no exception) but contain error indicators
- **Focus**: Distinguish repairable errors (bad params) from non-repairable (missing resources)
- **Scope**: Designed for API responses, but runs **after every node execution**

**3-Tier Priority**:
1. Error codes (most reliable) → categorize as validation/resource
2. Validation patterns (73 patterns) → let repair handle
3. Resource patterns (20 patterns) → stop workflow

**The Design Assumption**: All nodes producing API-like responses return dicts with potential error fields.

### The Fix Required

After line 770, add type guard:
```python
output = self._unwrap_mcp_response(output)
if not output:
    return None

# ADD THIS CHECK:
if not isinstance(output, dict):
    return None  # Only check dict responses for API errors

error_code = self._extract_error_code(output)
error_msg = self._extract_error_message(output)
```

**Rationale**: API warning detection only makes sense for structured (dict) responses. Binary data, plain text, and primitive types cannot have API error fields.

---

## 3. Binary Data Flow Pattern Analysis

### Write-File Node (CANNOT Handle Binary)

**File**: `src/pflow/nodes/file/write_file.py`

**Current Implementation**:
```python
# Line 83: Content converted to string
return (str(content), str(file_path), encoding, append)

# Line 118-157: Always text mode
with open(file_path, "a", encoding=encoding) as f:  # Text mode "a"
    f.write(content)
```

**Problems**:
- Uses text mode (`"w"`, `"a"`) not binary mode (`"wb"`, `"ab"`)
- Always applies encoding (default UTF-8)
- Converts all content to string via `str(content)`

**Interface Declaration** (line 28):
```python
- Reads: shared["content"]: str  # Content to write to the file
```

**Explicitly declares `str` type, not `bytes`.**

### Read-File Node (Binary Causes Errors)

**File**: `src/pflow/nodes/file/read_file.py`

**Test Evidence** (`tests/test_nodes/test_file/test_read_file.py:83-99`):
```python
def test_encoding_error(self):
    """Test behavior when file has encoding issues."""
    # Write binary data that's not valid UTF-8
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(b"\x80\x81\x82\x83")

    action = node.run(shared)

    assert action == "error"
    assert "encoding" in shared["error"].lower()
```

**Binary files cause encoding errors when read.**

### Other Non-Dict Producers

**Nodes that return non-dict outputs**:

1. **Read-File**: Returns `str` (formatted with line numbers)
   - Stores: `shared["content"]: str`

2. **LLM**: Returns `Any` (auto-parsed JSON or string)
   - Stores: `shared["response"]: Any`
   - Can be dict, list, str, int, etc.

3. **Shell**: Returns `str` (stdout)
   - Stores: `shared["stdout"]: str`, `shared["stderr"]: str`, `shared["exit_code"]: int`

4. **HTTP**: Returns `dict|str` (JSON or text)
   - Stores: `shared["response"]: dict|str`
   - **Should** return bytes for binary, but doesn't

### Shared Store Conventions

**From** `pocketflow/docs/core_abstraction/communication.md`:

**Principle**: Use semantic keys, not type-specific prefixes
```python
shared["data"] = "Some text content"
shared["summary"] = summary_result
shared["response"] = api_response
```

**No documented convention for binary data.**

**Technical Reality**: Shared store is just a Python dict - it CAN hold any type including bytes:
```python
shared["text"] = "string"      # Text
shared["data"] = {"key": "val"} # Structured
shared["bytes"] = b"\x00\x01"  # Binary (technically possible)
```

### No Established Binary Data Pattern

**Search results**:
- ❌ No base64 encoding in file nodes
- ❌ No binary mode file operations
- ❌ No binary download examples
- ❌ No documentation for binary conventions

**Conclusion**: System is text-only. Binary support needs cross-cutting implementation.

---

## 4. Test Coverage Analysis

### Existing Test Patterns

**HTTP Node Tests** (`tests/test_nodes/test_http/test_http.py`):
- ✅ Plain text responses (lines 207-225)
- ✅ JSON parsing (lines 187-205)
- ✅ Empty responses (lines 487-505)
- ✅ Large payloads (lines 459-485)
- ❌ **NO binary content tests**

**Mock Pattern Used**:
```python
with patch("requests.request") as mock_request:
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.text = "Hello, World!"
    mock_response.elapsed = timedelta(seconds=0.1)
    mock_request.return_value = mock_response
```

**InstrumentedWrapper Tests** (`tests/test_runtime/test_instrumented_wrapper.py`):
- ✅ Wrapper transparency (lines 582-601)
- ✅ Shared store preservation (lines 602-625)
- ✅ Return value preservation (lines 626-640)
- ❌ **NO tests for `_detect_api_warning()`**
- ❌ **NO tests for different data types**

**Write-File Tests** (`tests/test_nodes/test_file/test_write_file.py`):
- ✅ Text writing (lines 14-36)
- ✅ Custom encoding (lines 124-139)
- ❌ **NO binary mode tests**

**Integration Tests** (`tests/test_integration/test_e2e_workflow.py`):
- ✅ Read → Write workflows (lines 14-68)
- ✅ Template variables (lines 275-320)
- ❌ **NO HTTP → Write-File workflows**
- ❌ **NO binary download → save tests**

### Test Coverage Gaps

**Missing Tests**:
1. HTTP node with binary content-type → returns bytes
2. InstrumentedWrapper with non-dict outputs → no crash
3. Write-file with bytes content → binary mode
4. Integration: HTTP download → write-file for images

**Test Pattern to Follow**:
```python
def test_binary_response_handling():
    """Test HTTP node handles binary responses correctly."""
    with patch("requests.request") as mock_request:
        binary_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.content = binary_data  # bytes
        mock_response.text = binary_data.decode('latin-1')  # corrupted
        mock_response.elapsed = timedelta(seconds=0.1)
        mock_request.return_value = mock_response

        node = HttpNode()
        shared = {"url": "https://example.com/image.png"}
        action = node.run(shared)

        assert action == "default"
        assert isinstance(shared["response"], bytes)
        assert shared["response"] == binary_data
```

---

## 5. Implementation Strategy

### Phase 1: Immediate Fix (Prevent Crashes)

**Goal**: Stop crashes when downloading binary data

**Changes Required**:

1. **Add type guard in `instrumented_wrapper.py`** (after line 770):
   ```python
   if not isinstance(output, dict):
       return None
   ```

2. **Add defensive type check in `_extract_error_code()`** (line 863):
   ```python
   def _extract_error_code(self, output: dict) -> Optional[str]:
       if not isinstance(output, dict):
           return None
       # ... rest of method
   ```

**Impact**: Prevents crash, but binary data still corrupted by HTTP node.

### Phase 2: Complete Binary Support

**Goal**: Enable binary file workflows (download image → save to disk)

**Changes Required**:

1. **HTTP Node - Detect and preserve binary data** (`src/pflow/nodes/http/http.py`):
   ```python
   # Line 128: Add binary detection
   is_binary = any([
       content_type.startswith("image/"),
       content_type.startswith("application/pdf"),
       content_type.startswith("application/octet-stream"),
       content_type.startswith("video/"),
       content_type.startswith("audio/"),
   ])

   if is_binary:
       response_data = response.content  # bytes
   elif is_json:
       response_data = response.json()
   else:
       response_data = response.text
   ```

2. **Write-File Node - Support binary mode** (`src/pflow/nodes/file/write_file.py`):
   ```python
   # Line 118: Detect content type and choose mode
   if isinstance(content, bytes):
       with open(file_path, "wb" if not append else "ab") as f:
           f.write(content)
   else:
       with open(file_path, "w" if not append else "a", encoding=encoding) as f:
           f.write(str(content))
   ```

3. **Update Interface Declarations**:
   - HTTP node: `shared["response"]: dict|str|bytes`
   - Write-file node: `shared["content"]: str|bytes`

4. **Add Comprehensive Tests**:
   - HTTP binary response test
   - Write-file binary mode test
   - Integration test: download image → save file
   - InstrumentedWrapper with bytes test

---

## 6. Key Decisions and Trade-offs

### Decision 1: Fix Scope

**Options**:
- **A**: Minimal - just add type guard (Phase 1 only)
- **B**: Complete - implement full binary support (Phase 1 + 2)

**Recommendation**: **Option A (Minimal)** first
- **Why**: Binary support excluded from MVP (confirmed in docs)
- **Rationale**: Fix immediate crash, defer feature to post-MVP
- **Follow-up**: Create Task 82 for binary data support

### Decision 2: Type Guard Location

**Options**:
- **A**: Only in `_detect_api_warning()` after unwrap (line 770)
- **B**: Also in `_extract_error_code()` as defensive check
- **C**: Both locations (belt and suspenders)

**Recommendation**: **Option C (Both)**
- **Why**: Defense in depth prevents future issues
- **Rationale**: Minimal performance cost, maximum safety
- **Pattern**: Matches existing type guards (line 813, 350-352)

### Decision 3: Binary Data Format in Shared Store

**Options**:
- **A**: Store as `bytes` directly
- **B**: Store as base64-encoded string
- **C**: Store in temp file, pass file path

**Recommendation**: **Option A (bytes)** - for Phase 2
- **Why**: Simplest, no encoding overhead
- **Rationale**: Python dicts can hold bytes, nodes can type-check
- **Alternative**: Base64 only if serialization to JSON needed

---

## 7. Testing Requirements

### Tests for Phase 1 (Immediate Fix)

**Test 1**: InstrumentedWrapper handles string output without crashing
```python
def test_wrapper_with_string_output():
    class StringOutputNode(Node):
        def _run(self, shared):
            shared["data"] = "plain string response"
            return "default"

    wrapper = InstrumentedNodeWrapper(StringOutputNode(), "test")
    shared = {}
    result = wrapper._run(shared)

    assert result == "default"
    assert shared["data"] == "plain string response"
```

**Test 2**: HTTP node with binary content-type (currently fails, will skip or mark expected)
```python
@pytest.mark.skip(reason="Binary support not implemented - MVP limitation")
def test_http_binary_download():
    # Test that will pass after Phase 2 implementation
```

### Tests for Phase 2 (Complete Binary Support)

1. HTTP node returns bytes for image content-type
2. Write-file writes bytes in binary mode
3. Integration: HTTP → write-file preserves binary data
4. InstrumentedWrapper passes bytes transparently

---

## 8. Documentation Updates Needed

### Phase 1
- Document known limitation: Binary downloads not supported in MVP
- Add to `architecture/future-version/` for post-MVP roadmap

### Phase 2
- Update HTTP node Interface declaration
- Update write-file node Interface declaration
- Document binary data convention in shared store
- Add binary workflow example
- Update agent instructions about binary handling

---

## 9. Related Code Locations

| Component | File | Lines | Notes |
|-----------|------|-------|-------|
| **Bug location** | `instrumented_wrapper.py` | 774-775 | Missing type check |
| **Root cause** | `instrumented_wrapper.py` | 834 | Returns non-dict |
| **HTTP text mode** | `http.py` | 137 | Corrupts binary |
| **Write-file text mode** | `write_file.py` | 118-157 | No binary support |
| **Error detection** | `instrumented_wrapper.py` | 867-878 | Assumes dict |
| **MCP unwrap** | `instrumented_wrapper.py` | 811-838 | Can return any type |

---

## 10. Questions Resolved

✅ **Q: How does HTTP node handle binary responses?**
A: It doesn't - uses `response.text` which corrupts binary data.

✅ **Q: What format does write-file expect for binary?**
A: It doesn't support binary - only accepts strings in text mode.

✅ **Q: Are there other nodes producing non-dict outputs?**
A: Yes - read-file (str), shell (str), LLM (any), HTTP (dict|str).

✅ **Q: What's the shared store convention for binary?**
A: None exists - no documented pattern, no implementation.

✅ **Q: Should API warning detection run on all outputs?**
A: Currently yes, but should only run on dict outputs (API responses).

---

## 11. Recommendations for Implementation

### Immediate Actions (Phase 1)

1. ✅ Add type guard after `_unwrap_mcp_response()` call (line 770)
2. ✅ Add defensive check in `_extract_error_code()` (line 863)
3. ✅ Write test for wrapper with string output
4. ✅ Run full test suite to ensure no regressions
5. ✅ Document limitation in scratchpad

### Future Actions (Phase 2 - Post-MVP)

1. Create Task 82: Binary Data Support
2. Implement HTTP node binary detection
3. Implement write-file binary mode
4. Add read-file binary mode (optional)
5. Document binary data conventions
6. Write comprehensive test coverage
7. Update agent instructions

### Priority

**Phase 1**: CRITICAL - Blocks real-world workflows
**Phase 2**: IMPORTANT - Required for production readiness, but deferred to post-MVP

---

**End of Research Findings**
