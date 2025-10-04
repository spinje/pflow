# Agent Error Visibility Investigation

## Executive Summary

**Problem**: We need to understand what error information agents actually see when workflow execution fails, to determine if they have enough context to fix validation errors when using `--no-repair`.

**Finding**: Agents get **minimal, lossy error information** - just generic messages without the detailed validation context needed for effective repair.

---

## 1. CLI Error Presentation

### Location: `src/pflow/cli/main.py`

#### For Validation Failures (--no-repair mode)

When `--no-repair` is set, validation happens in `_validate_and_handle_workflow_errors()` (line 896):

**Text Mode Output**:
```python
# Line 946
click.echo(f"cli: Invalid workflow - {e}", err=True)
```

**JSON Mode Output**:
```python
# Lines 936-944
error_output = _create_json_error_output(
    e,  # ValidationError exception
    None,  # No metrics collector
    None,  # No shared storage
    workflow_metadata,
)
_serialize_json_result(error_output, verbose)
```

**What agents see**:
- Text: `"cli: Invalid workflow - <error message>"`
- JSON: Structured output from `_create_json_error_output()`

#### For Execution Failures

When execution fails, `_handle_workflow_error()` is called (line 1034):

**Text Mode Output**:
```python
# Lines 1045-1046
click.echo("cli: Workflow execution failed - Node returned error action", err=True)
click.echo("cli: Check node output above for details", err=True)
```

**JSON Mode Output**:
```python
# Lines 1054-1058
error_output = {
    "error": "Workflow execution failed",
    "is_error": True,
    **metrics_summary
}
_serialize_json_result(error_output, verbose)
```

**What agents see**:
- Text: Generic "Workflow execution failed" message
- JSON: Basic error flag with metrics, **NO error details**

---

## 2. ValidatorNode Error Output

### Location: `src/pflow/planning/nodes.py`

#### Validation Process (lines 2364-2392)

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Orchestrate validation checks using WorkflowValidator."""
    from pflow.core.workflow_validator import WorkflowValidator

    workflow = prep_res.get("workflow")
    if not workflow:
        return {"errors": ["No workflow provided for validation"]}

    # Use unified WorkflowValidator for all validation
    errors = WorkflowValidator.validate(
        workflow,
        extracted_params=prep_res.get("extracted_params", {}),
        registry=self.registry,
        skip_node_types=False,
    )

    # Return top 3 most actionable errors
    if errors:
        logger.info(f"Validation found {len(errors)} total errors, returning top 3")

    return {"errors": errors[:3]}  # Only top 3 errors
```

#### Error Routing (lines 2400-2432)

```python
def post(self, shared, prep_res, exec_res):
    errors = exec_res.get("errors", [])
    attempts = prep_res.get("generation_attempts", 0)

    if not errors:
        # Success path
        shared.pop("validation_errors", None)
        return "metadata_generation"

    if attempts >= 3:
        # Failed after max attempts
        shared["validation_errors"] = errors
        return "failed"

    # Retry path
    shared["validation_errors"] = errors  # Stored for retry
    return "retry"
```

**What's in validation_errors**:
- List of error strings from `WorkflowValidator.validate()`
- Limited to top 3 errors
- Stored in `shared["validation_errors"]`

---

## 3. Error Types and Messages

### Location: `src/pflow/core/workflow_validator.py`

#### WorkflowValidator.validate() Returns (line 29)

```python
def validate(...) -> list[str]:
    """Run complete workflow validation.

    Returns:
        List of all validation errors (empty if valid)
    """
```

**Error Format**: Plain strings, not structured objects

#### Error Categories (lines 49-69)

1. **Structural errors** (from IR schema):
   ```python
   return [f"Structure: {error_msg}"]
   ```

2. **Data flow errors** (execution order):
   ```python
   return validate_data_flow(workflow_ir)  # List of strings
   ```

3. **Template errors** (variable resolution):
   ```python
   return TemplateValidator.validate_workflow_templates(...)  # List of strings
   ```

4. **Node type errors** (registry verification):
   ```python
   errors.append(f"Unknown node type: '{node_type}'")
   ```

**Example Error Messages**:
- `"Structure: nodes[2].type is required"`
- `"Unknown node type: 'fake-node'"`
- `"Template ${data.field} not found in node 'process'"`
- `"Node 'analyze' references output from future node 'fetch'"`

---

## 4. Test Case Expectations

### Location: `tests/test_cli/test_no_repair_flag.py`

#### Expected Behavior (lines 178-205)

```python
def test_no_repair_preserves_error_message(self, failing_workflow, mock_registry):
    """Test that error messages are preserved when repair is disabled."""

    with (
        patch("pflow.cli.main.validate_ir"),
        patch("pflow.runtime.compiler.compile_ir_to_flow") as mock_compile,
    ):
        mock_flow = MagicMock()
        mock_flow.run.side_effect = ValueError("Template ${data.missing} not found")
        mock_compile.return_value = mock_flow

        # Run with --no-repair
        result = runner.invoke(main, ["--no-repair", workflow_file])

        # Should fail with exit code 1
        assert result.exit_code == 1

        # Error message should be shown
        assert "Template ${data.missing}" in result.output or "Workflow execution failed" in result.output
```

**Test shows**: Tests expect EITHER specific error OR generic message - acknowledging current lossy behavior!

---

## 5. Critical Findings

### What Error Details Are Lost

1. **Execution Failures (Text Mode)**:
   - ❌ No error messages from `result.errors`
   - ❌ No node IDs that failed
   - ❌ No error categories
   - ❌ No fixable flags
   - ✅ Only: "Workflow execution failed - Node returned error action"

2. **Execution Failures (JSON Mode)**:
   - ❌ No `result.errors` included in output
   - ❌ No structured error details
   - ✅ Only: `{"error": "Workflow execution failed", "is_error": true, ...metrics}`

3. **Validation Failures**:
   - ✅ Error message passed through from ValidationError
   - ❌ Only first validation error shown (not all errors)
   - ❌ No structured error details in text mode

### Error Structure That Exists But Isn't Shown

**ExecutionResult.errors format** (`src/pflow/execution/executor_service.py`):

```python
errors: list[dict[str, Any]]  # Structured error data

# Example error object:
{
    "source": "runtime",              # Where error originated
    "category": "api_validation",     # Error type for repair strategy
    "message": "Field 'title' required",  # Human-readable description
    "node_id": "create-issue",        # Which node failed
    "fixable": True,                  # Whether repair should attempt
    "repair_attempted": True,         # If repair was tried
    "repair_reason": "Could not fix"  # Why repair failed
}
```

**This rich structure is built but NOT displayed to CLI users/agents!**

---

## 6. Examples of Actual Error Output

### Scenario 1: Validation Error with --no-repair

**Agent sees (text)**:
```
cli: Invalid workflow - Structure: nodes[2].type is required
```

**Agent does NOT see**:
- Which node (by ID) is missing the type
- Other validation errors that might exist
- Suggestions for fixing

### Scenario 2: Runtime Execution Failure

**Agent sees (text)**:
```
cli: Workflow execution failed - Node returned error action
cli: Check node output above for details
```

**Agent sees (JSON)**:
```json
{
  "error": "Workflow execution failed",
  "is_error": true,
  "execution_time_seconds": 1.23,
  "llm_costs": {...}
}
```

**Agent does NOT see**:
- Which node failed (`node_id`)
- What the error was (`message`)
- Error category (`category`)
- Whether it's fixable (`fixable`)
- Attempted operations (`attempted`)
- Available fields (`available`)

### Scenario 3: What's in ExecutionResult but Not Shown

**Available in `result.errors` but not displayed**:
```python
[
  {
    "source": "runtime",
    "category": "template_error",
    "message": "Template ${data.field} not found",
    "node_id": "process-data",
    "fixable": True
  },
  {
    "source": "api",
    "category": "non_repairable",
    "message": "GitHub API rate limit exceeded",
    "node_id": "fetch-issues",
    "fixable": False
  }
]
```

**Agent only sees**: "Workflow execution failed - Node returned error action"

---

## 7. Impact on Agent Repair Capability

### With Current Error Output

**Agents can**:
- Know that execution failed
- See basic metrics (time, cost)
- Possibly see validation schema errors

**Agents CANNOT**:
- Identify which node failed
- Understand what went wrong
- Distinguish fixable vs non-fixable errors
- See multiple error contexts
- Get actionable repair guidance

### Why This Matters for --no-repair Flag

The `--no-repair` flag is meant for agents to handle repair themselves, but:

1. **Insufficient Context**: Agents get generic "execution failed" without specifics
2. **Lost Structure**: Rich error objects exist but aren't exposed
3. **Multiple Errors**: Only first error shown, agents miss full context
4. **No Guidance**: No fixable flags or repair suggestions
5. **Node Blindness**: Can't identify which node needs fixing

---

## 8. Recommendations

### Short-term: Improve Error Display

**Option A - Text Mode**: Show structured errors
```python
def _handle_workflow_error(...):
    if output_format != "json":
        click.echo("cli: Workflow execution failed", err=True)

        # NEW: Show error details from result.errors
        for err in result.errors[:3]:  # Top 3 errors
            click.echo(f"  - [{err.get('node_id', 'unknown')}] {err.get('message', 'Unknown error')}", err=True)
```

**Option B - JSON Mode**: Include full error structure
```python
def _handle_workflow_error(...):
    if output_format == "json":
        error_output = {
            "error": "Workflow execution failed",
            "is_error": True,
            "errors": result.errors,  # NEW: Include full error list
            **metrics_summary
        }
```

### Long-term: Structured Error API

Create dedicated error output format:
```json
{
  "success": false,
  "errors": [
    {
      "node_id": "process-data",
      "type": "template_error",
      "message": "Template ${data.field} not found",
      "fixable": true,
      "suggestion": "Check available fields: data.id, data.title"
    }
  ],
  "metrics": {...}
}
```

---

## Conclusion

**Agents currently see**: Generic failure messages
**Agents need to see**: Structured error details with node IDs, categories, and fixability

The system generates rich error context but throws most of it away before displaying to users/agents. This makes `--no-repair` mode less useful for agentic workflows since agents lack the information needed to effectively repair issues.
