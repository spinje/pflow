# Testing Runtime Validation Feedback Loop

## Quick Test Commands

### 1. Test with GitHub API (Real HTTP Request)

```bash
# This will trigger runtime validation if the planner guesses wrong field names
uv run pflow --trace-planner "fetch github user torvalds and show their username and biography"

# Check the trace to see runtime validation in action
cat ~/.pflow/debug/planner-trace-*.json | jq '.nodes[] | select(.node_name == "RuntimeValidationNode")'
```

### 2. Force Runtime Validation (Test Node)

Create a test workflow that intentionally uses wrong template paths:

```bash
# Create a workflow with intentionally wrong field names
cat > test_workflow.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "data",
      "type": "test_node_simple",
      "params": {}
    },
    {
      "id": "display",
      "type": "write-file",
      "params": {
        "file_path": "/tmp/test.txt",
        "content": "Value: ${data.wrong_field}"
      }
    }
  ],
  "edges": [{"from": "data", "to": "display"}],
  "start_node": "data"
}
EOF

# Run it (will fail due to missing template path)
uv run pflow test_workflow.json
```

## How Runtime Validation Works

### The Feedback Loop

1. **Initial Generation**: Planner generates workflow with guessed field names
   - Example: `${http.response.username}` (wrong - should be `login`)

2. **Runtime Validation**: Executes workflow and detects issues
   - Missing template paths
   - Available fields at each level
   - Classifies as fixable vs fatal

3. **Feedback to Generator**: Provides structured error information
   - `attempted: "${http.response.username}"`
   - `available: ["login", "id", "name", "bio", ...]`

4. **Corrected Generation**: Uses feedback to fix field names
   - Corrected: `${http.response.login}`

### What Gets Detected

- **Missing Template Paths**: `${node.field}` doesn't exist
- **Namespaced Errors**: Node reports error in shared store
- **Execution Exceptions**: Runtime failures during workflow execution

### Limits

- Maximum 3 runtime correction attempts
- Only fixes field names and paths, not logic errors
- Requires actual execution (HTTP calls, file writes, etc.)

## Verification Tests

### Test 1: Simple Template Path Detection

Run: `uv run python test_runtime_simple.py`

This shows:
- Detection of missing paths
- Available field suggestions
- Corrected paths verification

### Test 2: Full Integration Demo

Run: `uv run python test_runtime_validation_demo.py`

This demonstrates:
- Manual validation testing
- Mock planner flow
- Real execution scenarios

### Test 3: Unit Tests

```bash
# Run the runtime validation tests
uv run pytest tests/test_runtime_validation.py -v

# Run integration tests
uv run pytest tests/test_planning/integration/test_planner_integration.py -v
```

## Observing Runtime Validation

### Enable Tracing

```bash
# Enable planner tracing
uv run pflow --trace-planner "your command"

# Enable workflow tracing
uv run pflow --trace "your command"

# View traces
ls -la ~/.pflow/debug/
cat ~/.pflow/debug/planner-trace-*.json | jq .
```

### What to Look For

In the trace files, search for:

1. **RuntimeValidationNode execution**:
   ```json
   {
     "node_name": "RuntimeValidationNode",
     "phase": "exec",
     "result": {
       "ok": true,
       "shared_after": {...}
     }
   }
   ```

2. **Runtime errors detected**:
   ```json
   {
     "runtime_errors": [
       {
         "category": "missing_template_path",
         "attempted": "${http.response.username}",
         "available": ["login", "id", "name", ...]
       }
     ]
   }
   ```

3. **Routing decision**:
   - `"action": "default"` - No issues found
   - `"action": "runtime_fix"` - Fixable issues, retrying
   - `"action": "failed_runtime"` - Fatal or max attempts

## Real-World Example

```bash
# A command that will likely trigger runtime validation
uv run pflow "fetch the latest commit from github.com/anthropics/claude-code and show the commit message and author username"

# The planner might guess:
# - ${http.response.commit.message} (wrong)
# - ${http.response.author.username} (wrong)

# Runtime validation will detect and correct to:
# - ${http.response[0].commit.message} (correct - it's an array)
# - ${http.response[0].author.login} (correct - field is 'login' not 'username')
```

## Debugging Tips

1. **Check if RuntimeValidationNode is being executed**:
   ```bash
   grep -r "RuntimeValidationNode" ~/.pflow/debug/planner-trace-*.json
   ```

2. **Look for template validation errors**:
   ```bash
   grep -r "missing_template_path" ~/.pflow/debug/planner-trace-*.json
   ```

3. **Verify the flow includes RuntimeValidationNode**:
   ```python
   from pflow.planning import create_planner_flow
   flow = create_planner_flow()
   # Should show 12 nodes including RuntimeValidationNode
   ```

## Summary

The Runtime Validation Feedback Loop enables workflows to self-correct by:
1. Detecting missing template paths at execution time
2. Providing available fields for correction
3. Automatically regenerating with correct field names
4. Ensuring "Plan Once, Run Forever" philosophy

This makes pflow resilient to API changes and eliminates the need to know exact field names beforehand.