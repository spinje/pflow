# Refined Specification for 3.2

## Clear Objective
Capture and handle node execution results from flow.run() to provide accurate success/failure feedback and optional execution visibility.

## Context from Knowledge Base
- Building on: Error namespace convention ("cli:" prefix) from Task 2
- Avoiding: Silent node failures that confuse users (Subtask 3.1 finding)
- Following: Professional error message pattern (context + error + suggestion)

## Technical Specification

### Core Changes

1. **Capture flow.run() Result**
   - Location: `src/pflow/cli/main.py`, execute_json_workflow() function
   - Change: `result = flow.run(shared_storage)` instead of just calling it
   - Check: If result starts with "error", handle as failure
   - Success: Show "Workflow executed successfully"
   - Failure: Show "cli: Workflow execution failed - Node returned error action"

2. **Add Try/Except Around flow.run()**
   - Wrap flow.run() in try/except for unexpected failures
   - Catch generic Exception
   - Show: "cli: Workflow execution failed - {exception message}"

3. **Add --verbose Flag**
   - Location: main() function, add click.option
   - Format: `@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")`
   - Pass through context: Store in ctx.obj
   - Usage in execute_json_workflow: Show node entry/exit if verbose

4. **Fix Registry Error (if still present)**
   - Verify if double message still occurs
   - If yes, investigate Registry class constructor
   - Ensure clean error output

### Error Message Formats

**Node Execution Failure**:
```
cli: Workflow execution failed - Node returned error action
cli: Check node output above for details
```

**Unexpected Exception**:
```
cli: Workflow execution failed - {str(e)}
cli: This may indicate a bug in the workflow or nodes
```

**Verbose Output** (when --verbose):
```
cli: Executing node 'read' (read-file)...
cli: Node 'read' completed
cli: Executing node 'write' (write-file)...
cli: Node 'write' completed
```

### Implementation Constraints
- Must use: startswith("error") check for flexibility
- Must avoid: Breaking existing error handling patterns
- Must maintain: Exit code 1 for all failures

## Success Criteria
- [ ] flow.run() result is captured and checked
- [ ] Error action from nodes shows failure message
- [ ] Unexpected exceptions are caught with helpful message
- [ ] --verbose flag shows node execution trace
- [ ] All existing tests still pass
- [ ] New tests cover node failure scenarios
- [ ] Registry error message is clean (no double output)

## Test Strategy
- Unit tests: Mock flow.run() to return error actions
- Integration tests: Test with actual failing nodes (missing file)
- Manual verification: Run with missing file, check messages
- Verbose testing: Verify --verbose output format

## Dependencies
- Requires: PocketFlow understanding of action strings
- Impacts: User experience when workflows fail
- Compatible with: Existing error handling patterns

## Decisions Made
- Use startswith("error") for flexibility (User decision not needed - severity 2)
- Simple verbose output showing node lifecycle (User decision not needed - severity 1)
