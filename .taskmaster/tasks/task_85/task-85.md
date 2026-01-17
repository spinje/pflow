# Task 85: Runtime Template Resolution Hardening

## Description
Prevent literal template variables (like `${variable}`) from appearing in workflow output when nodes fail or produce empty results. Currently, when a node fails to produce output, downstream templates can't resolve but the workflow continues, sending literal `${variable}` text to external APIs like Slack. This task implements detection, proper error handling, and configurable fail-fast behavior to prevent silent data corruption in production workflows.

**Related Issue**: https://github.com/spinje/pflow/issues/95 - Bug report from AI agent discovering this behavior in production workflow testing.

## Status
done

## Completed
2025-10-20

## Dependencies
- Task 56: Implement Runtime Validation and Error Feedback Loop - The runtime validation infrastructure provides the foundation for detecting template resolution failures during execution. We'll extend this to detect unresolved templates in final output.

## Priority
high

## Details

### Problem Statement

**Source**: [GitHub Issue #95](https://github.com/spinje/pflow/issues/95)

An AI agent building workflows discovered a critical issue: workflows can execute "successfully" while producing broken output. Specifically:

1. **Node fails or produces empty output** (e.g., shell command returns nothing)
2. **Downstream template can't resolve** (e.g., `${save-message.stdout}` has no value)
3. **Literal template text propagates** instead of failing (`"${save-message.stdout}"` sent to Slack as-is)
4. **Workflow reports success** despite warnings showing `⚠️ node-name (Nonems)`
5. **User sees broken data** in production (literal variables in Slack messages, Google Sheets, etc.)

**Real Example from Agent Feedback**:
```
Workflow Output:
  ⚠️ analyze-questions (Nonems)
  ⚠️ save-message (Nonems)
  "successful": True

Slack Message Received:
  "${save-message.stdout}"  ← Literal text, not resolved value!
```

### Current Architecture Issues

From `src/pflow/runtime/node_wrapper.py` (lines 209-216):
```python
# Current behavior: unresolved templates remain as literal text
if resolved_value == template and "${" in str(template):
    # Just logs warning, doesn't fail
    logger.warning(f"Template {template} could not resolve")
    return template  # ← Returns "${var}" literally
```

From architecture docs:
> "Unresolved templates: Remain for debugging visibility"

**This is catastrophic for production** - debugging visibility should not trump data integrity.

### Relationship to Fix 3 (Type Checking)

**Fix 3** catches compile-time type mismatches:
- `${node.dict_field}` → str parameter ✅ Caught before execution

**Task 85** catches runtime resolution failures:
- `${node.field}` exists in schema but node produced empty output ❌ Not currently caught

They're complementary - both improve template reliability but at different stages.

### Required Changes

#### 1. Detect Unresolved Templates in Output (Critical)

**Before sending to external APIs**, detect literal template syntax:

```python
# Add to instrumented_wrapper.py or new validator
def validate_output_resolved(output_data: Any) -> None:
    """Detect if output contains unresolved template variables."""
    if isinstance(output_data, str) and "${" in output_data:
        raise TemplateResolutionError(
            f"Output contains unresolved template: {output_data}"
        )
    # Recursively check dicts/lists...
```

**Integration Point**: Run this check in `InstrumentedNodeWrapper._run()` after node execution, before storing in shared store.

#### 2. Fail Workflows When Critical Nodes Fail (Critical)

**Current**: Nodes can fail without failing the workflow
**Should**: Failed nodes → failed workflow (unless `allow_partial_failure=True`)

```python
# Modify workflow executor to check node statuses
if any_critical_node_failed and not workflow.get("allow_partial_failure", False):
    raise WorkflowExecutionError(
        "Critical node failed",
        failed_nodes=[...],
        degraded_nodes=[...]
    )
```

**Integration Point**: `src/pflow/runtime/workflow_executor.py` or `src/pflow/execution/executor_service.py`

#### 3. Replace "Nonems" with Actionable Errors (High)

**Current**: `⚠️ save-message (Nonems)` ← Cryptic, no context

**Should**:
```
❌ save-message (shell) failed:
   • Command: cat
   • Exit code: 0
   • stdout: (empty)
   • stderr: (none)
   • Impact: Breaks downstream template ${save-message.stdout}
     in node 'send-slack-response' parameter 'text'
```

**Where**: Error formatting in `src/pflow/execution/display_manager.py` and trace collection in `src/pflow/runtime/workflow_trace.py`

#### 4. Add Strict/Permissive Mode (Medium)

Allow users to choose fail-fast behavior:

```json
{
  "workflow_config": {
    "template_resolution_mode": "strict",  // or "permissive"
    "allow_partial_failure": false
  }
}
```

**Modes**:
- **Strict** (recommended): Any template resolution failure → fail workflow immediately
- **Permissive** (current): Log warning, use empty string or null, mark workflow as degraded

**Integration Point**: Workflow IR schema (`src/pflow/core/ir_schema.py`) and compiler validation

#### 5. Fix Workflow Success/Failure Semantics (Medium)

**Current**: Boolean `successful: True` even when nodes have warnings

**Should**: Tri-state status
```json
{
  "workflow_status": "partial_failure",  // or "success", "failed"
  "node_statuses": {
    "node1": "success",
    "node2": "failed",
    "node3": "degraded"
  },
  "overall_success": false
}
```

**Integration Point**: Workflow execution output in `src/pflow/execution/executor_service.py` and trace format in `src/pflow/runtime/workflow_trace.py`

### Key Design Decisions (MVP Approach)

1. **Default to strict mode** - Better to fail loudly than corrupt data silently
2. **No backward compatibility needed** - We have zero users, can change behavior
3. **Simple error detection** - Check for `"${"` in string output
4. **Reuse existing error infrastructure** - Extend `InstrumentedNodeWrapper` and trace collector
5. **Clear migration path** - Add config option so users can choose permissive if needed

### Technical Considerations

1. **Performance**: Checking for `"${"` in output is O(n) but fast for typical data sizes
2. **False positives**: What if user legitimately wants `"${"` in output? → Escape syntax like `\${variable}`
3. **Nested data**: Must recursively check dicts/lists for unresolved templates
4. **MCP nodes**: Some MCP responses might include template-like syntax → Only check pflow-generated templates
5. **Error aggregation**: Multiple unresolved templates → show all, not just first

### Integration Points

- **Template Resolution**: `src/pflow/runtime/node_wrapper.py` (TemplateAwareNodeWrapper)
- **Workflow Execution**: `src/pflow/execution/executor_service.py`
- **Error Handling**: `src/pflow/runtime/instrumented_wrapper.py`
- **Trace Collection**: `src/pflow/runtime/workflow_trace.py`
- **Display**: `src/pflow/execution/display_manager.py`
- **IR Schema**: `src/pflow/core/ir_schema.py` (add config options)

### Success Criteria

Before:
```
⚠️ save-message (Nonems)
✓ Workflow successful
Slack receives: "${save-message.stdout}"
```

After (Strict Mode):
```
❌ Workflow failed

Error in node 'send-slack-response':
  Template ${save-message.stdout} could not be resolved

Context:
  • Node 'save-message' produced no output (exit code 0, empty stdout)
  • Parameter 'text' depends on this variable
  • Cannot proceed without resolved value

Trace: ~/.pflow/debug/workflow-trace-[ID].json
```

After (Permissive Mode):
```
⚠️ Workflow completed with degradation

Issues:
  • save-message: No output produced
    └─ Template ${save-message.stdout} → (empty string)

Results:
  • send-slack-response: Sent empty message
  • Overall status: degraded

Review required: Check if this is expected behavior.
```

## Test Strategy

### Unit Tests

**File**: `tests/test_runtime/test_template_resolution_hardening.py`

1. **Test unresolved template detection**
   - String with `"${"` → detected
   - Nested dict with unresolved template → detected
   - List with unresolved template → detected
   - Escaped template `\${var}` → not detected (legitimate use)

2. **Test strict mode**
   - Node produces empty output → workflow fails immediately
   - Clear error message with context
   - Points to trace file

3. **Test permissive mode**
   - Node produces empty output → workflow continues
   - Uses empty string or null as fallback
   - Marks workflow as degraded
   - Logs warning

4. **Test error message formatting**
   - "Nonems" replaced with actual error
   - Shows stdout/stderr/exit code
   - Shows affected downstream nodes

### Integration Tests

**File**: `tests/test_integration/test_runtime_template_failures.py`

1. **End-to-end strict mode workflow**
   - Create workflow with dependent nodes
   - First node fails (empty output)
   - Second node tries to use `${first.output}`
   - Workflow fails with clear error before sending to external API

2. **End-to-end permissive mode workflow**
   - Same setup but permissive mode
   - Workflow continues with empty value
   - Status marked as degraded
   - Output shows warnings

3. **Slack integration test**
   - Verify literal `"${var}"` never sent to Slack in strict mode
   - Verify degraded status shown in permissive mode

### Real-World Scenario Tests

**File**: `tests/test_integration/test_slack_qa_responder.py`

Test the exact scenario from agent feedback:
1. LLM node produces JSON that can't be parsed
2. Shell node receives empty input
3. Downstream Slack node tries to use `${shell.stdout}`
4. In strict mode: Workflow fails before Slack message sent
5. In permissive mode: Clear degradation warning shown

### Regression Tests

Ensure Fix 3 (type checking) still works:
1. Type mismatches still caught at compile-time
2. Runtime resolution failures caught separately
3. Both work together without conflicts

### Test Coverage Goals

- Unresolved template detection: 100%
- Strict/permissive mode behavior: 100%
- Error message formatting: 100%
- Integration scenarios: 90%+
- Real-world workflows: 85%+
