# Task 141: Baseline Error Output

Captured: 2026-03-31, branch `refactor/consolidate-exception-hierarchy`, commit `917e4bb2`

Fixtures in `baseline-fixtures/`. Re-run after implementation to compare.

## Re-run command

```bash
FIXTURES=.taskmaster/tasks/task_141/implementation/baseline-fixtures
for f in valid malformed duplicate-ids unclosed-code-block missing-type bad-schema bad-sub-workflow exec-failure exec-failure-chain; do
  echo "====== $f ======"
  echo "--- text ---"
  uv run pflow $FIXTURES/$f.pflow.md 2>&1; echo "[exit: $?]"
  echo "--- json ---"
  uv run pflow --output-format json $FIXTURES/$f.pflow.md 2>&1; echo "[exit: $?]"
  echo ""
done
echo "====== WorkflowNotFoundError ======"
uv run pflow nonexistent-workflow-xyz 2>&1; echo "[exit: $?]"
uv run pflow --output-format json nonexistent-workflow-xyz 2>&1; echo "[exit: $?]"
echo ""
echo "====== validate-only ======"
uv run pflow --validate-only $FIXTURES/valid.pflow.md 2>&1; echo "[exit: $?]"
uv run pflow --validate-only $FIXTURES/malformed.pflow.md 2>&1; echo "[exit: $?]"
uv run pflow --validate-only $FIXTURES/bad-schema.pflow.md 2>&1; echo "[exit: $?]"
```

## Expected changes after implementation

- **All error messages should remain identical** in text mode (same user-facing output)
- **JSON `category` for MarkdownParseError**: stays `"parse_error"` (via `error_output.py:_exception_to_errors`)
- **JSON `category` for SchemaValidationError**: stays `"validation"` (via `error_output.py:_exception_to_errors`)
- **No new fields appear** in JSON output for pre-execution errors (the `_exception_to_result` changes only affect errors from `WorkflowRunner.run()`, not pre-execution `_exception_to_errors`)
- **Exit codes**: remain 1 for all error cases, 0 for valid

## Baseline Output

### 0. Happy path: valid.pflow.md

**text**: `Workflow completed in 0.019s` — greet node runs, outputs "hello from baseline"
**json**: `{"success": true, "result": {"stdout": "hello from baseline"}, ...}`
**exit**: 0

### 1. MarkdownParseError: malformed.pflow.md (no Steps section)

**text**:
```
✗ Missing '## Steps' section.

Every workflow needs a Steps section with at least one node:

    ## Steps

    ### my-node

    Description of what this node does.

    - type: shell
```

**json**:
```json
{
  "success": false,
  "status": "failed",
  "error": "Missing '## Steps' section.\n\nEvery workflow needs a Steps section...",
  "errors": [
    {
      "message": "Missing '## Steps' section...",
      "category": "parse_error",
      "suggestion": "Every workflow needs a Steps section..."
    }
  ]
}
```
**exit**: 1

### 2. MarkdownParseError: duplicate-ids.pflow.md

**text**:
```
✗ Line 11: Duplicate entity ID 'step1'.

An entity with ID 'step1' was already defined at line 7.
```

**json**:
```json
{
  "errors": [
    {
      "message": "Line 11: Duplicate entity ID 'step1'...",
      "category": "parse_error",
      "line": 11,
      "suggestion": "An entity with ID 'step1' was already defined at line 7."
    }
  ]
}
```
**exit**: 1

### 3. MarkdownParseError: unclosed-code-block.pflow.md

**text**:
```
✗ Line 8: Unclosed code block.

Add a closing fence (```) to match the opening fence at line 8.
```

**json**:
```json
{
  "errors": [
    {
      "message": "Line 8: Unclosed code block...",
      "category": "parse_error",
      "line": 8,
      "suggestion": "Add a closing fence..."
    }
  ]
}
```
**exit**: 1

### 4. MarkdownParseError: missing-type.pflow.md

**text**:
```
✗ Line 7: Node 'step1' is missing a 'type' parameter.

Every node needs a type:

    ### step1

    Description of what this node does.

    - type: shell
```

**json**:
```json
{
  "errors": [
    {
      "message": "Line 7: Node 'step1' is missing a 'type' parameter...",
      "category": "parse_error",
      "line": 7,
      "suggestion": "Every node needs a type..."
    }
  ]
}
```
**exit**: 1

### 5. CompilationError: bad-schema.pflow.md (unknown node type)

**text**:
```
❌ Workflow execution failed

Error 1:
  Category: validation
  Message: Unknown node type: 'nonexistent-node-type-xyz'
```

**json**:
```json
{
  "errors": [
    {
      "source": "validation",
      "message": "Unknown node type: 'nonexistent-node-type-xyz'",
      "category": "validation",
      "validation_errors": ["Unknown node type: 'nonexistent-node-type-xyz'"]
    }
  ]
}
```
**exit**: 1

### 6. WorkflowNotFoundError

**text**:
```
❌ Workflow 'nonexistent-workflow-xyz' not found.

Use 'pflow workflow list' to see available workflows.
```

**json**:
```json
{
  "errors": [
    {
      "message": "Workflow 'nonexistent-workflow-xyz' not found",
      "category": "not_found"
    }
  ]
}
```
**exit**: 1

### 7. Sub-workflow file not found: bad-sub-workflow.pflow.md

**text**:
```
❌ Workflow execution failed

Error 1:
  Category: validation
  Message: Step 'step1': sub-workflow file not found: '...'
```

**json**:
```json
{
  "errors": [
    {
      "source": "validation",
      "message": "Step 'step1': sub-workflow file not found: ...",
      "category": "validation",
      "validation_errors": ["Step 'step1': sub-workflow file not found: ..."]
    }
  ]
}
```
**exit**: 1

### 8. Execution failure: exec-failure.pflow.md (runtime path)

**text**:
```
WARNING: Command failed with exit code 1
❌ Workflow execution failed

Error 1 at node 'fail-step':
  Category: execution_failure
  Message: Command failed with exit code 1

  Shell details:
    Command: exit 1
```

**json** (key fields):
```json
{
  "errors": [
    {
      "source": "runtime",
      "category": "execution_failure",
      "message": "Command failed with exit code 1",
      "node_id": "fail-step",
      "shell_command": "exit 1",
      "shell_exit_code": 1
    }
  ]
}
```
**exit**: 1

### 9. Execution failure chain: exec-failure-chain.pflow.md (step2 fails)

**text**:
```
WARNING: Command failed with exit code 42
❌ Workflow execution failed

Error 1 at node 'step2':
  Category: execution_failure
  Message: Command failed with exit code 42

  Shell details:
    Command: exit 42
```

**json** (key fields):
```json
{
  "errors": [
    {
      "source": "runtime",
      "category": "execution_failure",
      "message": "Command failed with exit code 42",
      "node_id": "step2"
    }
  ]
}
```
**exit**: 1

### 10. Validate-only: valid workflow

**text**: `✓ Workflow is valid`
**exit**: 0

### 11. Validate-only: malformed

Same as #1 text output. **exit**: 1

### 12. Validate-only: bad-schema

**text**:
```
✗ Static validation failed:
  • Unknown node type: 'nonexistent-node-type-xyz'

Suggestions:
  • Use 'registry list' to see available nodes
```
**exit**: 1
