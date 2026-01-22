# Manual Testing Plan: Task 115 - Stdin Routing

## Understanding How pflow Works

From `cli-agent-instructions.md`:
- Run workflows: `pflow workflow.json param=value`
- Pipe data: `echo "data" | pflow workflow.json`
- Workflows need `"stdin": true` on an input to accept piped data
- Use `--verbose` for detailed output
- Use `-p` or `--print` to force output to stdout

## Test Cases to Verify

### Test 1: Basic stdin routing works
**What**: Pipe data to workflow with `stdin: true` input
**Expected**: Data routes to the marked input

### Test 2: Error when no stdin: true
**What**: Pipe data to workflow WITHOUT `stdin: true`
**Expected**: Helpful error message with JSON example

### Test 3: Error when multiple stdin: true
**What**: Workflow with two `stdin: true` inputs
**Expected**: Validation error listing both input names

### Test 4: CLI param overrides stdin
**What**: Pipe data AND provide CLI param for same input
**Expected**: CLI value wins, piped value ignored

### Test 5: No stdin provided, stdin: true input exists
**What**: Run workflow with `stdin: true` input but no piped data
**Expected**: Normal required input error (must provide via CLI)

---

## Test Workflows

### workflow-basic-stdin.json
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "data": {"type": "string", "required": true, "stdin": true, "description": "Data from stdin"}
  },
  "nodes": [
    {
      "id": "show_data",
      "type": "shell",
      "params": {"command": "echo 'Received:' && cat", "stdin": "${data}"}
    }
  ],
  "edges": [],
  "start_node": "show_data"
}
```

### workflow-no-stdin.json
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "path": {"type": "string", "required": true, "description": "A file path"}
  },
  "nodes": [
    {
      "id": "show_path",
      "type": "shell",
      "params": {"command": "echo 'Path: ${path}'"}
    }
  ],
  "edges": [],
  "start_node": "show_path"
}
```

### workflow-multiple-stdin.json
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "input_a": {"type": "string", "required": true, "stdin": true},
    "input_b": {"type": "string", "required": true, "stdin": true}
  },
  "nodes": [
    {
      "id": "noop",
      "type": "shell",
      "params": {"command": "echo 'test'"}
    }
  ],
  "edges": [],
  "start_node": "noop"
}
```

---

## Test Commands

```bash
# Create test directory
mkdir -p /tmp/task115-tests
cd /tmp/task115-tests

# Create test workflows (will do with Write tool)

# Test 1: Basic stdin routing
echo "Hello from stdin" | uv run pflow workflow-basic-stdin.json --verbose

# Test 2: No stdin: true error
echo "This should fail" | uv run pflow workflow-no-stdin.json --verbose

# Test 3: Multiple stdin: true error
uv run pflow workflow-multiple-stdin.json --verbose

# Test 4: CLI override
echo "ignored_value" | uv run pflow workflow-basic-stdin.json data="cli_value" --verbose

# Test 5: No stdin, required input
uv run pflow workflow-basic-stdin.json --verbose
```

---

## Expected Results

| Test | Exit Code | Key Output |
|------|-----------|------------|
| 1. Basic routing | 0 | "Received:" + "Hello from stdin" |
| 2. No stdin: true | 1 | "stdin": true" in error message |
| 3. Multiple stdin | 1 | "input_a" and "input_b" in error |
| 4. CLI override | 0 | Shows "cli_value", not "ignored_value" |
| 5. No stdin provided | 1 | Missing required input error |

---

## Actual Results (2026-01-22)

### Test 1: Basic stdin routing ✅ PASS
```
echo "Hello from stdin" | uv run pflow workflow-basic-stdin.json

Workflow output:
Received:
Hello from stdin
```

### Test 2: No stdin: true error ✅ PASS
```
echo "This should fail" | uv run pflow workflow-no-stdin.json

❌ Piped input cannot be routed to workflow

   This workflow has no input marked with "stdin": true.
   To accept piped data, add "stdin": true to one input declaration.

   Example:
     "inputs": {
       "data": {"type": "string", "required": true, "stdin": true}
     }

   👉 Add "stdin": true to the input that should receive piped data
```

### Test 3: Multiple stdin: true error ✅ PASS
```
uv run pflow workflow-multiple-stdin.json

❌ Multiple inputs marked with "stdin": true: input_a, input_b
   At: inputs
   👉 Only one input can receive piped stdin
```

### Test 4: CLI override ✅ PASS
```
echo "ignored_value" | uv run pflow workflow-basic-stdin.json data="cli_value"

Workflow output:
Received:
cli_value
```
Note: "ignored_value" from stdin was correctly overridden by CLI param "cli_value"

### Test 5: No stdin provided ✅ PASS
```
uv run pflow workflow-basic-stdin.json

❌ Workflow requires input 'data': Data from stdin
   At: inputs.data
```

---

## Summary

**All 5 tests passed.** Task 115 stdin routing is working correctly:

1. ✅ Stdin routes to `stdin: true` input
2. ✅ Helpful error when no `stdin: true` input exists
3. ✅ Validation error when multiple `stdin: true` inputs
4. ✅ CLI parameters override stdin
5. ✅ Normal required input behavior when no stdin provided

---

## FIFO Fix Testing (2026-01-22)

After implementing FIFO detection in `stdin_has_data()`, workflow chaining now works:

### Test 6: Direct workflow chaining ✅ PASS
```bash
uv run pflow -p producer.json | uv run pflow -p consumer.json
# Output: 3
```

### Test 7: Three-stage pipeline ✅ PASS
```bash
uv run pflow -p producer.json | uv run pflow -p passthrough.json | uv run pflow -p consumer.json
# Output: 3
```

### Test 8: No stdin, terminal mode ✅ PASS (no hang)
```bash
uv run pflow consumer.json
# Expected: Error about missing required input 'data' (not hanging)
# Got: ❌ Workflow requires input 'data': No description provided
```

**All workflow chaining functionality is now working.**
