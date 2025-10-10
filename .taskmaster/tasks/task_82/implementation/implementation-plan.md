# Task 82: Binary Data Support - Implementation Plan

## Executive Summary

**Goal**: Implement system-wide binary data support using base64 encoding contract with explicit `_is_binary` flags across 4 core nodes.

**Approach**: Sequential implementation of nodes in dependency order, with testing after each phase.

**Estimated Time**: 6-8 hours total
- Phase 1 (HTTP): 1.5 hours
- Phase 2 (Write-File): 1 hour
- Phase 3 (Read-File): 1.5 hours
- Phase 4 (Shell): 1.5 hours
- Phase 5 (Testing): 2 hours
- Phase 6 (Validation): 0.5 hours

---

## Implementation Order & Dependencies

### Dependency Chain

```
HTTP Node (Producer)
    ↓
Write-File Node (Consumer)
    ↓
Read-File Node (Producer)
    ↓
Shell Node (Producer/Consumer)
    ↓
Integration Tests
    ↓
Full Validation
```

**Why this order?**
1. HTTP is entry point for binary data (highest priority)
2. Write-File consumes HTTP output (test HTTP→Write-File pipeline)
3. Read-File produces binary (test round-trip: Write→Read)
4. Shell completes the contract (lowest priority, complex)
5. Integration tests validate full system
6. Final validation with real workflow

---

## Phase 1: HTTP Node Binary Detection & Encoding

**Time**: 1.5 hours
**Priority**: CRITICAL (Entry point for binary data)

### Files to Modify

#### 1.1 Add base64 Import
**File**: `src/pflow/nodes/http/http.py`
**Location**: Line 1-8 (import section)
**Change**: Add `import base64`

#### 1.2 Update exec() Method - Binary Detection
**File**: `src/pflow/nodes/http/http.py`
**Location**: Lines 126-145
**Changes**:
1. Add BINARY_CONTENT_TYPES constant
2. Detect binary via Content-Type
3. Use `response.content` instead of `response.text` for binary
4. Return `is_binary` flag in result dict

**Exact Implementation**:
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute the HTTP request."""
    url = prep_res["url"]
    method = prep_res["method"]
    # ... existing request code ...

    response = requests.request(...)

    # Binary detection (NEW)
    content_type = response.headers.get("content-type", "").lower()
    BINARY_CONTENT_TYPES = [
        "image/", "video/", "audio/",
        "application/pdf", "application/octet-stream",
        "application/zip", "application/gzip", "application/x-tar"
    ]
    is_binary = any(ct in content_type for ct in BINARY_CONTENT_TYPES)

    # Parse response based on type
    if is_binary:
        response_data = response.content  # bytes - DO NOT USE response.text
    elif "json" in content_type:
        try:
            response_data = response.json()
        except (ValueError, json.JSONDecodeError):
            response_data = response.text
    else:
        response_data = response.text

    return {
        "response": response_data,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "duration": response.elapsed.total_seconds(),
        "is_binary": is_binary  # NEW - pass to post()
    }
```

#### 1.3 Update post() Method - Base64 Encoding
**File**: `src/pflow/nodes/http/http.py`
**Location**: Lines 168-184
**Changes**:
1. Check `is_binary` flag from exec_res
2. Base64 encode if binary
3. Set `response_is_binary` flag in shared store

**Exact Implementation**:
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results and determine action."""

    # Handle binary encoding (NEW)
    response_data = exec_res["response"]
    is_binary = exec_res.get("is_binary", False)

    if is_binary:
        # Encode binary data as base64
        encoded = base64.b64encode(response_data).decode('ascii')
        shared["response"] = encoded
        shared["response_is_binary"] = True
    else:
        # Store text/JSON as-is
        shared["response"] = response_data
        shared["response_is_binary"] = False

    # Store other metadata (existing)
    shared["status_code"] = exec_res["status_code"]
    shared["response_headers"] = exec_res["headers"]
    shared["response_time"] = exec_res.get("duration", 0)

    # Determine action (existing)
    status = exec_res["status_code"]
    if 200 <= status < 300:
        return "default"
    else:
        shared["error"] = f"HTTP {status}"
        return "error"
```

#### 1.4 Update Interface Documentation
**File**: `src/pflow/nodes/http/http.py`
**Location**: Lines 15-36
**Changes**: Add binary flag to Writes section

**Updated Interface**:
```python
"""
Make HTTP requests to APIs and web services.

Interface:
- Reads: shared["url"]: str  # API endpoint to call
- Reads: shared["method"]: str  # HTTP method (optional, default: GET)
- Reads: shared["body"]: dict|str  # Request payload (optional)
- Reads: shared["headers"]: dict  # Additional headers (optional)
- Reads: shared["params"]: dict  # Query parameters (optional)
- Reads: shared["timeout"]: int  # Request timeout in seconds (optional)
- Writes: shared["response"]: dict|str  # Response data (JSON parsed, raw text, or base64-encoded binary)
- Writes: shared["response_is_binary"]: bool  # True if response is binary data
- Writes: shared["status_code"]: int  # HTTP status code
- Writes: shared["response_headers"]: dict  # Response headers
- Writes: shared["response_time"]: float  # Request duration in seconds
- Writes: shared["error"]: str  # Error description for non-2xx responses
- Params: auth_token: str  # Bearer token for Authorization header (optional)
- Params: api_key: str  # API key for X-API-Key header (optional)
- Params: api_key_header: str  # Custom header name for API key (optional)
- Actions: default (success), error (failure)
"""
```

### Testing Checkpoint 1
After completing HTTP node:
- Run existing HTTP tests: `uv python -m pytest tests/test_nodes/test_http/ -v`
- Verify no regressions in text/JSON handling
- Manual test with binary URL to verify base64 encoding

---

## Phase 2: Write-File Node Binary Decoding & Writing

**Time**: 1 hour
**Priority**: CRITICAL (Enables HTTP→File pipeline)

### Files to Modify

#### 2.1 Add base64 Import
**File**: `src/pflow/nodes/file/write_file.py`
**Location**: Line 1-8 (import section)
**Change**: Add `import base64`

#### 2.2 Update prep() Method - Check Binary Flag
**File**: `src/pflow/nodes/file/write_file.py`
**Location**: Lines 47-83
**Changes**:
1. Add `is_binary` parameter retrieval
2. Decode base64 when flag is true
3. Return 5-tuple instead of 4-tuple

**Exact Implementation**:
```python
def prep(self, shared: dict) -> tuple[str | bytes, str, str, bool, bool]:
    """Prepare file writing parameters."""

    # Content - shared first, then params (existing)
    if "content" in shared:
        content = shared["content"]
    elif "content" in self.params:
        content = self.params["content"]
    else:
        raise ValueError("Missing required 'content'")

    # File path (existing)
    file_path = shared.get("file_path") or self.params.get("file_path")
    if not file_path:
        raise ValueError("Missing required 'file_path'")

    # Encoding (existing)
    encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

    # Append mode (existing)
    append = self.params.get("append", False)

    # Binary flag (NEW)
    is_binary = shared.get("content_is_binary") or self.params.get("content_is_binary", False)

    if is_binary and isinstance(content, str):
        # Decode base64 to bytes (NEW)
        try:
            content = base64.b64decode(content)
        except Exception as e:
            raise ValueError(f"Invalid base64 content: {str(e)[:100]}")

    return (content, str(file_path), encoding, append, is_binary)
```

#### 2.3 Update exec() Method - Binary Write Mode
**File**: `src/pflow/nodes/file/write_file.py`
**Location**: Lines 118-157
**Changes**:
1. Unpack 5-tuple from prep()
2. Use binary mode when is_binary=True
3. Update _atomic_write call

**Exact Implementation**:
```python
def exec(self, prep_res: tuple) -> str:
    """Write content to file."""
    content, file_path, encoding, append, is_binary = prep_res  # Unpack 5-tuple

    try:
        # Create parent directories (existing)
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)

        if append:
            # Append mode
            if is_binary:
                mode = "ab"
                with open(file_path, mode) as f:
                    f.write(content)
            else:
                mode = "a"
                with open(file_path, mode, encoding=encoding) as f:
                    f.write(str(content))
        else:
            # Write mode - use atomic write
            if is_binary:
                self._atomic_write_binary(file_path, content)
            else:
                self._atomic_write(file_path, str(content), encoding)

        return f"File written: {file_path}"

    except Exception as e:
        raise IOError(f"Failed to write file {file_path}: {e}")
```

#### 2.4 Add _atomic_write_binary() Method
**File**: `src/pflow/nodes/file/write_file.py`
**Location**: After _atomic_write() method (~line 200)
**Change**: Add new method for binary atomic writes

**New Method**:
```python
def _atomic_write_binary(self, file_path: str, content: bytes) -> None:
    """Atomically write binary content to file using temp file pattern."""
    dir_path = os.path.dirname(file_path) or "."

    # Create temp file in same directory (binary mode)
    temp_fd, temp_path = tempfile.mkstemp(dir=dir_path, text=False)  # text=False for binary

    try:
        # Write binary content
        with os.fdopen(temp_fd, "wb") as f:
            f.write(content)

        # Atomic move
        shutil.move(temp_path, file_path)

    except Exception:
        # Clean up temp file on error
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise
```

#### 2.5 Update Interface Documentation
**File**: `src/pflow/nodes/file/write_file.py`
**Location**: Lines 27-35
**Changes**: Add binary flag to Reads section

**Updated Interface**:
```python
"""
Write content to a file with atomic writes for safety.

Interface:
- Reads: shared["content"]: str  # Content to write to the file (text or base64-encoded binary)
- Reads: shared["content_is_binary"]: bool  # True if content is base64-encoded binary (optional, default: false)
- Reads: shared["file_path"]: str  # Path to the file to write
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["written"]: bool  # True if write succeeded
- Writes: shared["error"]: str  # Error message if operation failed
- Params: append: bool  # Append to file instead of overwriting (default: false)
- Actions: default (success), error (failure)
"""
```

### Testing Checkpoint 2
After completing write-file node:
- Run existing write-file tests: `uv python -m pytest tests/test_nodes/test_file/test_write_file.py -v`
- Test HTTP→Write-File pipeline with binary data
- Verify text mode still works (backward compatibility)

---

## Phase 3: Read-File Node Binary Detection & Encoding

**Time**: 1.5 hours
**Priority**: HIGH (Enables round-trip testing)

### Files to Modify

#### 3.1 Add base64 Import
**File**: `src/pflow/nodes/file/read_file.py`
**Location**: Line 1-6 (import section)
**Change**: Add `import base64`

#### 3.2 Update exec() Method - Binary Detection
**File**: `src/pflow/nodes/file/read_file.py`
**Location**: Lines 57-103
**Changes**:
1. Add binary extension detection
2. Add UnicodeDecodeError fallback
3. Store is_binary flag in self._is_binary

**Exact Implementation**:
```python
def exec(self, prep_res: tuple[str, str]) -> str | bytes:
    """Read file content."""
    file_path, encoding = prep_res

    # Check if file exists (existing)
    if not os.path.exists(file_path):
        logger.error("File not found", extra={"file_path": file_path, "phase": "exec"})
        raise FileNotFoundError(f"File '{file_path}' does not exist")

    # Binary detection by extension (NEW)
    BINARY_EXTENSIONS = {
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico',
        '.pdf', '.zip', '.tar', '.gz', '.7z', '.rar',
        '.mp3', '.mp4', '.wav', '.avi', '.mov',
        '.exe', '.dll', '.so', '.dylib'
    }

    path = Path(file_path)
    file_ext = path.suffix.lower()
    is_binary_ext = file_ext in BINARY_EXTENSIONS

    # Log file size for large files (existing)
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 1024 * 1024:  # 1MB
            logger.info(
                "Reading large file",
                extra={"file_path": file_path, "size_mb": round(file_size / (1024 * 1024), 2), "phase": "exec"},
            )
    except OSError:
        pass

    # Read file based on detection
    if is_binary_ext:
        # Known binary extension - read as binary (NEW)
        content = path.read_bytes()
        self._is_binary = True
        return content
    else:
        # Try text read first
        try:
            with open(file_path, encoding=encoding) as f:
                lines = f.readlines()

            # Add line numbers (existing)
            numbered_lines = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
            content = "".join(numbered_lines)
            self._is_binary = False
            return content

        except UnicodeDecodeError:
            # File is actually binary despite extension (NEW)
            content = path.read_bytes()
            self._is_binary = True
            return content
```

#### 3.3 Update post() Method - Base64 Encoding
**File**: `src/pflow/nodes/file/read_file.py`
**Location**: Lines 129-137
**Changes**:
1. Check self._is_binary flag
2. Base64 encode if binary
3. Set content_is_binary flag

**Exact Implementation**:
```python
def post(self, shared: dict, prep_res: tuple[str, str], exec_res: str | bytes) -> str:
    """Update shared store based on result and return action."""

    # Check if exec_res is an error message from exec_fallback (existing)
    if isinstance(exec_res, str) and exec_res.startswith("Error:"):
        shared["error"] = exec_res
        return "error"

    # Handle binary encoding (NEW)
    if hasattr(self, '_is_binary') and self._is_binary:
        # Encode binary content as base64
        encoded = base64.b64encode(exec_res).decode('ascii')
        shared["content"] = encoded
        shared["content_is_binary"] = True
    else:
        # Store text content as-is
        shared["content"] = exec_res
        shared["content_is_binary"] = False

    # Store file path (existing)
    shared["file_path"] = prep_res[0]

    return "default"
```

#### 3.4 Update Interface Documentation
**File**: `src/pflow/nodes/file/read_file.py`
**Location**: Lines 24-33
**Changes**: Add binary flag to Writes section

**Updated Interface**:
```python
"""
Read content from a file with line numbers for easy reference.

Interface:
- Reads: shared["file_path"]: str  # Path to the file to read
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents (with line numbers for text, base64-encoded for binary)
- Writes: shared["content_is_binary"]: bool  # True if content is binary data
- Writes: shared["file_path"]: str  # Path that was read
- Writes: shared["error"]: str  # Error message if operation failed
- Actions: default (success), error (failure)
"""
```

### Testing Checkpoint 3
After completing read-file node:
- Run existing read-file tests: `uv python -m pytest tests/test_nodes/test_file/test_read_file.py -v`
- Test Write→Read round-trip with binary data
- Verify text files still get line numbers

---

## Phase 4: Shell Node Binary stdout/stderr Handling

**Time**: 1.5 hours
**Priority**: MEDIUM (Completes the contract)

### Files to Modify

#### 4.1 Add base64 Import
**File**: `src/pflow/nodes/shell/shell.py`
**Location**: Line 3-6 (import section)
**Change**: Add `import base64`

#### 4.2 Update exec() Method - Binary Detection
**File**: `src/pflow/nodes/shell/shell.py`
**Location**: Lines 475-477 (subprocess.run call)
**Changes**:
1. Change `text=True` to `text=False`
2. Handle stdout/stderr as bytes
3. Try UTF-8 decode, catch UnicodeDecodeError

**Exact Implementation**:
```python
def exec(self, prep_res: tuple) -> dict[str, Any]:
    """Execute the shell command."""
    command, cwd, full_env, stdin, timeout, high_risk = prep_res

    try:
        # Run command (modified for binary handling)
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=False,  # CHANGED: Get bytes, not strings
            input=stdin.encode('utf-8') if stdin else None,  # Encode stdin to bytes
            cwd=cwd,
            env=full_env,
            timeout=timeout
        )

        # Handle stdout - try decode, fallback to binary (NEW)
        try:
            stdout = result.stdout.decode('utf-8')
            stdout_is_binary = False
        except UnicodeDecodeError:
            # Binary output - keep as bytes for post() to encode
            stdout = result.stdout
            stdout_is_binary = True

        # Handle stderr - try decode, fallback to binary (NEW)
        try:
            stderr = result.stderr.decode('utf-8')
            stderr_is_binary = False
        except UnicodeDecodeError:
            # Binary error output
            stderr = result.stderr
            stderr_is_binary = True

        return {
            "stdout": stdout,
            "stdout_is_binary": stdout_is_binary,
            "stderr": stderr,
            "stderr_is_binary": stderr_is_binary,
            "exit_code": result.returncode,
            "timeout": False
        }

    except subprocess.TimeoutExpired as e:
        # Handle timeout (modified for binary handling)
        stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""

        return {
            "stdout": stdout,
            "stdout_is_binary": False,
            "stderr": stderr,
            "stderr_is_binary": False,
            "exit_code": -1,
            "timeout": True
        }
```

#### 4.3 Update post() Method - Base64 Encoding
**File**: `src/pflow/nodes/shell/shell.py`
**Location**: Lines 517-519
**Changes**:
1. Check binary flags
2. Base64 encode if binary
3. Set binary flags in shared store

**Exact Implementation**:
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store command results."""

    # Handle stdout (NEW)
    if exec_res.get("stdout_is_binary", False):
        # Encode binary stdout as base64
        encoded = base64.b64encode(exec_res["stdout"]).decode('ascii')
        shared["stdout"] = encoded
        shared["stdout_is_binary"] = True
    else:
        shared["stdout"] = exec_res["stdout"]
        shared["stdout_is_binary"] = False

    # Handle stderr (NEW)
    if exec_res.get("stderr_is_binary", False):
        # Encode binary stderr as base64
        encoded = base64.b64encode(exec_res["stderr"]).decode('ascii')
        shared["stderr"] = encoded
        shared["stderr_is_binary"] = True
    else:
        shared["stderr"] = exec_res["stderr"]
        shared["stderr_is_binary"] = False

    # Store exit code (existing)
    shared["exit_code"] = exec_res["exit_code"]

    # Determine action (existing)
    if exec_res.get("timeout", False):
        shared["error"] = "Command timed out"
        return "error"
    elif exec_res["exit_code"] != 0 and not self.params.get("ignore_errors", False):
        return "error"

    return "default"
```

#### 4.4 Update Interface Documentation
**File**: `src/pflow/nodes/shell/shell.py`
**Location**: Lines 98-112
**Changes**: Add binary flags to Writes section

**Updated Interface**:
```python
"""
Execute shell commands with full Unix power.

Interface:
- Reads: shared["stdin"]: str  # Optional input data for the command
- Writes: shared["stdout"]: str  # Command standard output (text or base64-encoded binary)
- Writes: shared["stdout_is_binary"]: bool  # True if stdout is binary data
- Writes: shared["stderr"]: str  # Command error output (text or base64-encoded binary)
- Writes: shared["stderr_is_binary"]: bool  # True if stderr is binary data
- Writes: shared["exit_code"]: int  # Process exit code
- Params: command: str  # Shell command to execute (required)
- Params: cwd: str  # Working directory (optional, defaults to current)
- Params: env: dict  # Additional environment variables (optional)
- Params: timeout: int  # Max execution time in seconds (optional, default 30)
- Params: ignore_errors: bool  # Continue on non-zero exit (optional, default false)
- Actions: default (exit code 0 or ignore_errors=true), error (non-zero exit or timeout)
"""
```

### Testing Checkpoint 4
After completing shell node:
- Run existing shell tests: `uv python -m pytest tests/test_nodes/test_shell/ -v`
- Test binary command output (e.g., `base64 /path/to/image.png`)
- Verify text commands still work

---

## Phase 5: Comprehensive Testing

**Time**: 2 hours
**Priority**: CRITICAL (Validates implementation)

### Test Files to Create/Modify

#### 5.1 HTTP Node Binary Tests
**File**: `tests/test_nodes/test_http/test_http.py`
**Action**: Add new test methods

**Tests to add**:
1. `test_http_binary_image_response()` - Mock image/png response
2. `test_http_binary_pdf_response()` - Mock application/pdf response
3. `test_http_text_response_unchanged()` - Verify backward compatibility
4. `test_http_json_response_unchanged()` - Verify JSON parsing still works

#### 5.2 Write-File Node Binary Tests
**File**: `tests/test_nodes/test_file/test_write_file.py`
**Action**: Add new test methods

**Tests to add**:
1. `test_write_binary_with_flag()` - Write base64 with flag
2. `test_write_text_without_flag()` - Backward compatibility
3. `test_write_invalid_base64()` - Error handling
4. `test_write_binary_append_mode()` - Append binary data

#### 5.3 Read-File Node Binary Tests
**File**: `tests/test_nodes/test_file/test_read_file.py`
**Action**: Add new test methods

**Tests to add**:
1. `test_read_binary_by_extension()` - Read .png file
2. `test_read_binary_by_decode_error()` - Binary file with .txt extension
3. `test_read_text_file_unchanged()` - Verify line numbering still works
4. `test_read_empty_binary_file()` - Edge case

#### 5.4 Shell Node Binary Tests
**File**: `tests/test_nodes/test_shell/test_shell.py`
**Action**: Add new test methods

**Tests to add**:
1. `test_shell_binary_stdout()` - Command with binary output
2. `test_shell_text_stdout_unchanged()` - Backward compatibility
3. `test_shell_binary_stderr()` - Binary in stderr
4. `test_shell_mixed_binary_text()` - Binary stdout, text stderr

#### 5.5 Integration Test - Binary Data Flow
**File**: `tests/test_integration/test_binary_data_flow.py` (NEW)
**Action**: Create new file

**Tests to create**:
1. `test_http_to_write_file_binary_pipeline()` - Download → Save
2. `test_write_read_binary_roundtrip()` - Write → Read → Verify
3. `test_mixed_binary_text_workflow()` - Both types in same workflow
4. `test_large_binary_file()` - 10MB file handling

### Test Execution Strategy

**Run after each phase**:
```bash
# HTTP tests
uv python -m pytest tests/test_nodes/test_http/ -v

# Write-file tests
uv python -m pytest tests/test_nodes/test_file/test_write_file.py -v

# Read-file tests
uv python -m pytest tests/test_nodes/test_file/test_read_file.py -v

# Shell tests
uv python -m pytest tests/test_nodes/test_shell/ -v

# Integration tests
uv python -m pytest tests/test_integration/test_binary_data_flow.py -v

# Full test suite
make test
```

---

## Phase 6: Validation & Quality Checks

**Time**: 0.5 hours
**Priority**: CRITICAL (Final verification)

### 6.1 Create Test Workflow
**File**: `.pflow/workflows/test-binary-download.json` (NEW)
**Purpose**: Real workflow to validate binary support

**Content**:
```json
{
  "name": "test-binary-download",
  "description": "Test workflow for binary data support",
  "nodes": [
    {
      "id": "download",
      "type": "http",
      "params": {
        "url": "https://httpbin.org/image/png",
        "method": "GET"
      }
    },
    {
      "id": "save",
      "type": "write-file",
      "params": {
        "file_path": "/tmp/test-downloaded-image.png",
        "content": "${download.response}",
        "content_is_binary": "${download.response_is_binary}"
      }
    },
    {
      "id": "verify",
      "type": "read-file",
      "params": {
        "file_path": "/tmp/test-downloaded-image.png"
      }
    }
  ],
  "edges": [
    {"from": "download", "to": "save"},
    {"from": "save", "to": "verify"}
  ]
}
```

### 6.2 Manual Validation Tests

**Test 1: Binary Download & Save**
```bash
uv run pflow --trace .pflow/workflows/test-binary-download.json
# Verify: /tmp/test-downloaded-image.png exists and is valid PNG
file /tmp/test-downloaded-image.png
```

**Test 2: Text Workflow Still Works**
```bash
echo "Test content" > /tmp/test-input.txt
uv run pflow --trace "read /tmp/test-input.txt and count words"
# Verify: No errors, text processing works
```

**Test 3: Mixed Binary and Text**
```bash
# Create workflow with both binary image and text file
# Verify: Both types handled correctly in same workflow
```

### 6.3 Quality Checks

**Linting & Type Checking**:
```bash
make check
# Should pass with no errors
```

**Test Coverage**:
```bash
uv python -m pytest --cov=src/pflow/nodes tests/ --cov-report=term-missing
# Verify: Binary code paths covered
```

**Documentation Validation**:
- [ ] All Interface sections updated
- [ ] Binary flags documented in all 4 nodes
- [ ] Comments explain binary handling
- [ ] No TODOs or FIXME left in code

---

## Success Criteria Checklist

### Implementation Complete When:

- [ ] **HTTP Node**:
  - [ ] Detects binary Content-Type
  - [ ] Uses response.content for binary
  - [ ] Base64 encodes binary data
  - [ ] Sets response_is_binary flag
  - [ ] Interface documentation updated

- [ ] **Write-File Node**:
  - [ ] Checks content_is_binary flag
  - [ ] Decodes base64 when flag present
  - [ ] Writes in binary mode (wb/ab)
  - [ ] _atomic_write_binary() method added
  - [ ] Interface documentation updated

- [ ] **Read-File Node**:
  - [ ] Detects binary by extension
  - [ ] Fallback on UnicodeDecodeError
  - [ ] Base64 encodes binary content
  - [ ] Sets content_is_binary flag
  - [ ] Interface documentation updated

- [ ] **Shell Node**:
  - [ ] subprocess.run uses text=False
  - [ ] Catches UnicodeDecodeError
  - [ ] Base64 encodes binary stdout/stderr
  - [ ] Sets binary flags
  - [ ] Interface documentation updated

- [ ] **Testing**:
  - [ ] All existing tests pass (no regressions)
  - [ ] New binary tests pass for all 4 nodes
  - [ ] Integration tests pass
  - [ ] Test workflow completes successfully

- [ ] **Quality**:
  - [ ] `make check` passes (linting, type checking)
  - [ ] `make test` passes (full test suite)
  - [ ] No console errors or warnings
  - [ ] Code follows existing patterns

- [ ] **Validation**:
  - [ ] Test workflow downloads and saves image correctly
  - [ ] Binary file integrity verified (PNG is valid)
  - [ ] Text workflows still work (backward compatibility)
  - [ ] Mixed binary/text workflow works

### Specification Compliance

**18 Test Criteria from spec** (task-82-spec.md lines 155-175):
1. [ ] HTTP with image/png produces base64 string
2. [ ] HTTP with image/png sets response_is_binary to true
3. [ ] HTTP with text/plain keeps response as text
4. [ ] Write-file with base64 and flag writes valid binary
5. [ ] Write-file without flag writes base64 string as text
6. [ ] Write-file with malformed base64 raises ValueError
7. [ ] Read-file with .png returns base64 string
8. [ ] Read-file with .png sets content_is_binary to true
9. [ ] Read-file with .txt returns plain text string
10. [ ] Shell with binary stdout returns base64 string
11. [ ] Shell with binary stdout sets stdout_is_binary to true
12. [ ] Shell with text stdout returns plain text
13. [ ] Empty binary file produces empty base64 with flag
14. [ ] Mixed binary/text workflow preserves both types
15. [ ] 10MB binary file completes within memory limits
16. [ ] Missing flag treated as text (backward compatibility)
17. [ ] Binary without flag causes corruption but no crash
18. [ ] Base64 padding error provides fix suggestion

---

## Risk Mitigation

### Known Risks & Mitigations

**Risk 1: Breaking text workflows**
- Mitigation: Missing flags default to False (backward compatible)
- Test: Run all existing tests before deploying

**Risk 2: Base64 decode errors**
- Mitigation: Try/except with clear error messages
- Test: Test with invalid base64 strings

**Risk 3: Memory issues with large files**
- Mitigation: Log warnings for >50MB files
- Test: Test with 10MB+ files

**Risk 4: Template resolution issues**
- Mitigation: Follow suffix convention exactly
- Test: Integration tests verify template flow

**Risk 5: Shell stdin encoding**
- Mitigation: Encode string stdin to bytes
- Test: Test shell node with stdin input

---

## Parallel vs Sequential Tasks

### Can Be Done in Parallel
- Writing tests for different nodes (after implementation)
- Documentation updates for different nodes
- Code review of different node implementations

### Must Be Sequential
1. HTTP → Write-File (dependency)
2. Write-File → Read-File (test round-trip)
3. All nodes → Integration tests (dependencies)
4. Integration tests → Final validation (dependency)

---

## Implementation Notes

### Code Style Reminders
- Use f-strings for formatting
- Type hints on all functions
- Lowercase built-in types (list, dict, not List, Dict)
- Use .get() with defaults for backward compatibility
- Clear variable names (is_binary, not bin_flag)

### Testing Reminders
- Use tempfile for all file operations
- Mock HTTP requests (never make real calls)
- Test both success and error paths
- Verify exact bytes for binary data
- Check shared store state after each node

### Documentation Reminders
- Interface section at END of docstring
- Use pipe (|) for union types
- Mark optional parameters
- Document defaults
- Clear descriptions of binary handling

---

## Estimated Timeline

**Total: 6-8 hours**

- Hour 0-1.5: Phase 1 (HTTP Node)
- Hour 1.5-2.5: Phase 2 (Write-File Node)
- Hour 2.5-4: Phase 3 (Read-File Node)
- Hour 4-5.5: Phase 4 (Shell Node)
- Hour 5.5-7.5: Phase 5 (Testing)
- Hour 7.5-8: Phase 6 (Validation)

**Checkpoint after each phase** to verify no regressions.

---

## Final Notes

This implementation follows the epistemic manifesto:
- All assumptions verified against actual code
- All risks identified and documented
- All decisions justified with reasoning
- Implementation is pragmatic, not elegant
- Backward compatibility is non-negotiable

The base64 approach trades 33% memory overhead for system stability and minimal code changes. This is the right choice for MVP.

**Remember**: The shared store CAN handle bytes - we're choosing base64 for pragmatism, not necessity.
