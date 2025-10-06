# Manual Testing Results - Registry Run Command

**Date**: 2025-10-06
**Status**: All tests passing ✅
**Total Tests**: 14

---

## Test Suite

### ✅ Test 1: Basic File Read
```bash
$ echo "test content" > /tmp/test-pflow.txt
$ uv run pflow registry run read-file file_path=/tmp/test-pflow.txt

✓ Node executed successfully

Outputs:
  content: 1: test content

Execution time: 0ms
```
**Result**: PASS - Basic execution working

---

### ✅ Test 2: JSON Output Mode
```bash
$ uv run pflow registry run read-file file_path=/tmp/test-pflow.txt --output-format json

{
  "success": true,
  "node_type": "read-file",
  "outputs": {
    "content": "1: test content\n"
  },
  "execution_time_ms": 0
}
```
**Result**: PASS - JSON serialization working correctly

---

### ✅ Test 3: Verbose Mode
```bash
$ uv run pflow registry run read-file file_path=/tmp/test-pflow.txt --verbose

🔄 Running node 'read-file'...
   Parameters:
     file_path: /tmp/test-pflow.txt
✓ Node executed successfully

Outputs:
  content: 1: test content

Execution time: 0ms
Action returned: 'default'
```
**Result**: PASS - Verbose output showing parameters and action

---

### ✅ Test 4: Write File Node
```bash
$ uv run pflow registry run write-file file_path=/tmp/test-write.txt content="Hello from pflow registry run!" --verbose

🔄 Running node 'write-file'...
   Parameters:
     file_path: /tmp/test-write.txt
     content: Hello from pflow registry run!
✓ Node executed successfully

Outputs:
  written: Successfully wrote to '/tmp/test-write.txt'

$ cat /tmp/test-write.txt
Hello from pflow registry run!
```
**Result**: PASS - File actually written to disk

---

### ✅ Test 5: Structure Mode with Shell Node
```bash
$ uv run pflow registry run shell command="echo test" --show-structure

✓ Node executed successfully

Outputs:
  stdout: test
  stderr:
  exit_code: 0

Available template paths:
  ✓ ${shell.stdout} (str)
  ✓ ${shell.stderr} (str)
  ✓ ${shell.exit_code} (int)

Use these paths in workflow templates.

Execution time: 3ms
```
**Result**: PASS - Structure flattening working with types

---

### ✅ Test 6: MCP Node Name Normalization (Short Form)
```bash
$ uv run pflow registry run list-directory path=/private/tmp --verbose

📝 Resolved 'list-directory' to 'mcp-filesystem-list_directory'
🔄 Running node 'mcp-filesystem-list_directory'...
```
**Result**: PASS - Short form → Full MCP format normalization

---

### ✅ Test 7: MCP Structure Mode
```bash
$ uv run pflow registry run list-directory path=/private/tmp --show-structure

✓ Node executed successfully

Outputs:
  result: [FILE] analysis-result.md...
  filesystem_list_directory_result: [FILE] analysis-result.md...

Available template paths:
  ✓ ${mcp-filesystem-list_directory.result} (Any)

Use these paths in workflow templates.

Execution time: 315ms
```
**Result**: PASS - MCP nodes work with structure mode

---

### ✅ Test 8: Git Status with Structure Mode
```bash
$ uv run pflow registry run git-status --show-structure

✓ Node executed successfully

Outputs:
  git_status: dict with 6 keys

Available template paths:
  ✓ ${git-status.git_status} (dict)
  ✓ ${git-status.git_status.ahead} (int)
  ✓ ${git-status.git_status.behind} (int)
  ✓ ${git-status.git_status.branch} (str)
  ✓ ${git-status.git_status.modified} (list[str])
  ✓ ${git-status.git_status.staged} (list[str])
  ✓ ${git-status.git_status.untracked} (list[str])

Use these paths in workflow templates.

Execution time: 25ms
```
**Result**: PASS - Complex nested structure flattened correctly

---

### ✅ Test 9: HTTP Node with API Call
```bash
$ uv run pflow registry run http url="https://api.github.com/zen" method=GET --output-format json

{
  "success": true,
  "node_type": "http",
  "outputs": {
    "response": "Favor focus over features.",
    "status_code": 200,
    "response_headers": {...},
    "response_time": 0.18644
  },
  "execution_time_ms": 191
}
```
**Result**: PASS - HTTP node working, complex outputs serialized

---

### ✅ Test 10: HTTP POST with JSON Body
```bash
$ uv run pflow registry run http \
  url="https://httpbin.org/post" \
  method=POST \
  body='{"test":"value","nested":{"key":"data"}}' \
  --output-format json

{
  "success": true,
  "outputs": {
    "response": {
      "json": {
        "nested": {"key": "data"},
        "test": "value"
      },
      ...
    }
  }
}
```
**Result**: PASS - JSON parameter parsing working correctly

---

### ✅ Test 11: Parameter Type Inference
```bash
$ uv run pflow registry run shell \
  command="echo test" \
  timeout=5 \
  check=true \
  --verbose

🔄 Running node 'shell'...
   Parameters:
     command: echo test
     timeout: 5          # Correctly parsed as int
     check: true         # Correctly parsed as bool
```
**Result**: PASS - Type inference working (int, bool, string)

---

### ✅ Test 12: Copy File Node
```bash
$ echo "source content" > /tmp/source.txt
$ uv run pflow registry run copy-file \
  source_path=/tmp/source.txt \
  dest_path=/tmp/dest.txt \
  --verbose

✓ Node executed successfully

Outputs:
  copied: Successfully copied '/tmp/source.txt' to '/tmp/dest.txt'

$ cat /tmp/dest.txt
source content
```
**Result**: PASS - File operations working end-to-end

---

### ✅ Test 13: Unknown Node Error
```bash
$ uv run pflow registry run nonexistent-node

❌ Unknown node type: 'nonexistent-node'

Available nodes:
  - __metadata__
  - claude-code
  - copy-file
  ...
  ... and 75 more

Use 'pflow registry list' to see all nodes.
```
**Result**: PASS - Helpful error with suggestions

---

### ✅ Test 14: Missing Parameter Error
```bash
$ uv run pflow registry run read-file

❌ Missing required parameter: Missing required 'file_path' in shared store or params

Use 'pflow registry describe read-file' to see required parameters.
```
**Result**: PASS - Clear error with actionable guidance

---

## Node Types Tested

- ✅ **File nodes**: read-file, write-file, copy-file
- ✅ **Git nodes**: git-status
- ✅ **Shell nodes**: shell
- ✅ **HTTP nodes**: http (GET and POST)
- ✅ **MCP nodes**: mcp-filesystem-list_directory

## Feature Coverage

- ✅ Text output mode (default)
- ✅ JSON output mode
- ✅ Structure output mode
- ✅ Verbose mode
- ✅ Parameter type inference (string, int, bool, JSON)
- ✅ MCP node name normalization
- ✅ Error handling (unknown node, missing params)
- ✅ Complex JSON parameters
- ✅ Nested structure flattening

## Performance

- Simple nodes: 0-5ms
- HTTP requests: 190-21,000ms (network dependent)
- MCP nodes: 300-1,800ms (server dependent)
- Command overhead: Minimal (~0ms for simple cases)

## Issues Found

None - all functionality working as designed.

## Recommendations

1. All core functionality is working correctly
2. Ready to proceed with automated tests
3. Consider documenting the parameter type inference rules more prominently
4. The command is production-ready for the MVP