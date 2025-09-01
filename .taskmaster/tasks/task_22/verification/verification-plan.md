# Task 22: Real-World Verification Plan

## Objective
Systematically verify that all features of Task 22 (Named Workflow Execution) work correctly in real-world usage.

## Test Categories

### 1. Discovery Commands (Basic Functionality)
- [ ] `pflow workflow list` - Shows saved workflows
- [ ] `pflow workflow list --json` - JSON output format
- [ ] `pflow workflow describe <existing>` - Shows workflow details
- [ ] `pflow workflow describe <non-existent>` - Shows helpful error

### 2. Saved Workflow Execution
- [ ] Execute existing saved workflow by name
- [ ] Execute with .json extension (should strip and find)
- [ ] Execute non-existent workflow (should show suggestions)
- [ ] Execute with parameters (validation should work)
- [ ] Execute with missing required parameters (should show error)
- [ ] Execute with default parameters (should apply defaults)
 - [ ] Case-insensitive extension: `my-workflow.JSON` resolves like `.json`

### 3. File-Based Workflow Execution
- [ ] Execute from relative path: `./workflow.json`
- [ ] Execute from absolute path: `/tmp/workflow.json`
- [ ] Execute from home path: `~/workflow.json`
- [ ] Execute non-existent file (should show error)
- [ ] Execute invalid JSON file (should show syntax error)
- [ ] Execute valid JSON but not workflow (should show error)
 - [ ] Permission error: unreadable file shows "Permission denied" message
 - [ ] Encoding error: non-UTF8 file shows "Unable to read file" message

### 4. Parameter Handling
- [ ] Type inference: boolean (true/false)
- [ ] Type inference: integer (42)
- [ ] Type inference: float (3.14)
- [ ] Type inference: list ([1,2,3])
- [ ] Type inference: dict ({"key":"value"})
- [ ] Type inference: string (plain text)
- [ ] Parameters with equals in value (key=a=b+c)
 - [ ] Invalid parameter key names (non-identifier) show clear validation error

### 5. Error Messages & UX
- [ ] Workflow not found shows suggestions
- [ ] JSON syntax errors show line/column
- [ ] Missing parameters show requirements
- [ ] File not found shows clear message
- [ ] Natural language fallback still works
 - [ ] For obvious single-word inputs show targeted hints (no planner):
   - [ ] `pflow workflows` → "Did you mean: pflow workflow list"
   - [ ] `pflow list` / `pflow ls` → "Did you mean: pflow workflow list"
   - [ ] `pflow help` / `pflow -h` / `pflow --help` → "For help: pflow --help"

### 6. Backwards Compatibility
- [ ] Old workflows still execute
- [ ] Natural language input still works
- [ ] Stdin data still works (for workflows, not JSON)

### 7. Run Prefix Handling (New)
- [ ] `pflow run my-workflow` executes same as `pflow my-workflow`
- [ ] `pflow run ./workflow.json` executes file workflow
- [ ] `pflow run "analyze this text"` routes to planner (multi-word)
- [ ] `pflow run` shows helpful usage error and exits

### 8. Single-Token Behavior (New Guardrails)
- [ ] Single token that is a saved workflow name executes (e.g., `pflow my-workflow`)
- [ ] Single token generic (not saved, no params) shows fast not-found guidance (no planner) (e.g., `pflow analyze`)
- [ ] Single token with parameters routes to planner (e.g., `pflow analyze input=data.csv`)
- [ ] Obvious tokens produce hints and exit (see section 5 above)

### 9. Cross-Platform Paths
- [ ] Backslash path separators are treated as file paths where applicable (Windows-style)
- [ ] Mixed-case extensions like `.JSON` are handled identically to `.json`

## Test Workflows to Create

### Test Workflow 1: Simple Echo
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "echo",
      "type": "write-file",
      "params": {
        "file_path": "/tmp/echo-output.txt",
        "content": "Hello from workflow!"
      }
    }
  ],
  "edges": [],
  "start_node": "echo"
}
```

### Test Workflow 2: With Parameters
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "message": {
      "description": "Message to write",
      "required": true
    },
    "count": {
      "description": "Number of times",
      "required": false,
      "default": 1
    }
  },
  "nodes": [
    {
      "id": "writer",
      "type": "write-file",
      "params": {
        "file_path": "/tmp/param-output.txt",
        "content": "${message}"
      }
    }
  ],
  "edges": [],
  "start_node": "writer"
}
```

### Test Workflow 3: Invalid JSON
```
{
  "invalid": "json",
  "missing": "comma"
  "syntax": "error"
}
```

## Execution Steps

1. **Setup Phase**
   - Check existing saved workflows
   - Create test workflow files
   - Note current state

2. **Discovery Testing**
   - Test list and describe commands
   - Verify JSON output formats
   - Test error cases

3. **Execution Testing**
   - Test saved workflows
   - Test file-based workflows
   - Test parameter handling
   - Test error scenarios

4. **Cleanup Phase**
   - Remove test files
   - Document results

## Success Criteria

- All commands execute without crashes
- Error messages are helpful and actionable
- Parameters are correctly validated and typed
- File and saved workflow resolution works
- Discovery commands provide useful information
- Natural language fallback still functions

## Expected Outcomes

### What Should Work
1. Any workflow can be executed by name or file path
2. .json extension is handled transparently
3. Parameters are validated and typed correctly
4. Discovery commands show workflow information
5. Error messages guide users to solutions

### What Should NOT Work (By Design)
1. --file flag (removed)
2. JSON workflows via stdin (removed)
3. Obvious command-like single tokens (e.g., `workflows`, `list`, `ls`, `help`) do not invoke planner; they show targeted hints and exit

## Risk Areas to Focus On

1. **Edge case**: Workflow name that looks like a file path
2. **Edge case**: File path that looks like a workflow name
3. **Edge case**: Very long parameter values
4. **Edge case**: Special characters in workflow names
5. **Performance**: Large workflow files