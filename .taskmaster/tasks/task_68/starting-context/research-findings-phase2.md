# Task 68 Phase 2: Research Findings

## Executive Summary

This document contains comprehensive research findings essential for implementing Phase 2 of Task 68. The research confirms that InstrumentedNodeWrapper is the ideal location for checkpoint tracking, OutputController can easily support cached node display, and RuntimeValidationNode provides excellent patterns for repair service implementation.

## 1. InstrumentedNodeWrapper Analysis

### Current Implementation Flow

The `_run` method in InstrumentedNodeWrapper follows this exact flow:

1. **State Capture** (line 286): `shared_before = dict(shared)`
2. **Infrastructure Setup** (lines 289-296): Initialize `__llm_calls__`, set planner flag
3. **Progress Start** (lines 299-304): Call `node_start` event
4. **Node Execution** (line 308): `result = self.inner_node._run(shared)`
5. **Success Path** (lines 310-332): Record metrics, capture LLM usage, call `node_complete`
6. **Failure Path** (lines 334-345): Record metrics, record trace, re-raise exception

### Safe Checkpoint Injection Points

**Primary Injection Point (Before line 308)**:
```python
# Check if node already completed (resume case)
if "__execution__" in shared and self.node_id in shared["__execution__"]["completed_nodes"]:
    cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")

    # Show cached indicator via progress callback
    if callable(callback):
        with contextlib.suppress(Exception):
            callback(self.node_id, "node_cached", 0, depth)

    logger.info(f"Resuming {self.node_id} with cached action: {cached_action}")
    return cached_action

# Normal execution continues...
result = self.inner_node._run(shared)
```

**Success Recording Point (After line 308, in try block)**:
```python
# Track successful completion
if "__execution__" not in shared:
    shared["__execution__"] = {"completed_nodes": [], "node_actions": {}, "failed_node": None}

shared["__execution__"]["completed_nodes"].append(self.node_id)
shared["__execution__"]["node_actions"][self.node_id] = result
```

**Failure Recording Point (In except block, line 341)**:
```python
# Track failed node for debugging
if "__execution__" in shared:
    shared["__execution__"]["failed_node"] = self.node_id
```

### Test Preservation

Existing tests in `test_instrumented_wrapper.py` verify:
- Timing capture accuracy
- LLM usage accumulation
- Exception propagation
- Shared store transparency

Our checkpoint logic won't break these because:
- We preserve the `_run` signature
- We maintain exception propagation
- We don't modify timing capture
- We only add to shared store, not modify existing keys

## 2. OutputController Enhancement

### Current Progress Callback Implementation

The `create_progress_callback` method handles three events:
- `node_start`: Displays `"  {node_id}..."` with no newline
- `node_complete`: Displays `" ✓ {duration}s"` to complete the line
- `workflow_start`: Displays `"Executing workflow ({count} nodes):"`

### Adding node_cached Event

Add this elif block after the `node_complete` condition:

```python
elif event == "node_cached":
    # Display cached indicator
    click.echo(" ↻ cached", err=True)
```

This produces output like:
```
Executing workflow (3 nodes):
  read-file... ✓ 0.2s
  process-data... ↻ cached
  write-file... ✓ 0.3s
```

### Integration Points

- Callback stored in `shared["__progress_callback__"]`
- Called by InstrumentedNodeWrapper at node events
- Depth parameter for nested workflow indentation
- All output goes to stderr for progress display

## 3. RuntimeValidationNode Template Extraction

### Key Patterns to Port

**Template Path Extraction**:
```python
# Regex for parsing ${node_id.field.path} format
template_pattern = r"\$\{([^.]+)\.(.+)\}"
```

**Field Discovery for Suggestions**:
```python
def _get_available_paths(shared: dict, node_id: str, partial_path: str) -> list[str]:
    current = shared.get(node_id, {})
    # Navigate to specified level and return available keys
    if isinstance(current, dict):
        return list(current.keys())
    elif isinstance(current, list):
        return [f"[{i}]" for i in range(len(current))]
    return []
```

**Error Context Building**:
```python
{
    "attempted": "${http.response.login}",
    "available": ["username", "id", "created_at"],
    "message": "Template path '${http.response.login}' not found. Available: username, id, created_at"
}
```

### Simplifications for Repair Service

- Remove 3-attempt limiting logic
- Focus on template resolution errors
- Simplify fixability classification
- Extract only the field suggestion logic

## 4. Error Structures and ExecutionResult

### ExecutionResult Fields

```python
@dataclass
class ExecutionResult:
    success: bool
    shared_after: dict[str, Any]  # Complete state for repair context
    errors: list[dict[str, Any]]  # Structured error list
    action_result: Optional[str]  # Flow action (e.g., "error")
    output_data: Optional[str]  # Extracted output
    metrics_summary: Optional[dict]  # Metrics if available
```

### Error Dictionary Format

```python
{
    "source": "runtime",  # or "compilation", "validation"
    "category": "execution_failure",  # or "exception", "template_error"
    "message": "Human-readable error description",
    "fixable": True,  # Boolean for repair feasibility
    "exception_type": "KeyError",  # If from exception
    "node_id": "http",  # Context if node-specific
}
```

### Template Error Enhancement

Add template-specific context:
```python
{
    "source": "template",
    "category": "missing_template_path",
    "attempted": "${http.response.login}",
    "available": ["username", "id", "created_at"],
    "message": "Template path not found",
    "fixable": True
}
```

## 5. LLM Integration Patterns

### Model Selection for Repair

Use `anthropic/claude-3-haiku-20240307` for repairs:
- Fast response time (< 1s)
- Low cost per token
- Sufficient capability for template fixes
- Better demo experience

### Integration Pattern

```python
import llm

def repair_workflow(workflow_ir: dict, errors: list) -> tuple[bool, Optional[dict]]:
    model = llm.get_model("anthropic/claude-3-haiku-20240307")

    prompt = _build_repair_prompt(workflow_ir, errors)

    try:
        response = model.prompt(prompt, temperature=0.0)
        repaired_ir = _extract_json_from_response(response.text())
        return True, repaired_ir
    except Exception as e:
        logger.error(f"Repair failed: {e}")
        return False, None
```

### JSON Extraction

Reuse existing pattern from LLMNode:
```python
from pflow.nodes.llm.llm import LLMNode
repaired_ir = LLMNode.parse_json_response(response_text)
```

## 6. Test Infrastructure Impact

### Tests That Won't Break

- **InstrumentedNodeWrapper tests**: Checkpoint logic doesn't change existing behavior
- **OutputController tests**: Adding event type doesn't affect existing events
- **CLI tests**: Interface remains the same
- **Integration tests**: `compile_ir_to_flow` boundary preserved

### Tests to Delete

These files test RuntimeValidationNode and should be removed:
- `tests/test_runtime_validation.py`
- `tests/test_runtime_validation_simple.py`
- `tests/test_runtime/test_runtime_validation_core.py`
- `tests/test_planning/integration/test_runtime_validation_flow.py`

### New Tests Needed

1. **Checkpoint functionality**: Test resume behavior
2. **Repair service**: Test error analysis and workflow correction
3. **Unified execution**: Test repair triggering and retry
4. **Cached node display**: Test progress callback for cached nodes

## 7. Implementation Order

Based on the research, the optimal implementation order is:

1. **Extend InstrumentedNodeWrapper** (15 minutes)
   - Add checkpoint checking before execution
   - Record success/failure in shared["__execution__"]
   - Return cached action for completed nodes

2. **Extend OutputController** (10 minutes)
   - Add elif for "node_cached" event
   - Display "↻ cached" indicator

3. **Create RepairService** (1 hour)
   - Port template extraction from RuntimeValidationNode
   - Build repair prompt with error context
   - Use claude-3-haiku for fixes

4. **Create Unified Execution** (30 minutes)
   - Combine ExecutorService with repair logic
   - Handle resume from checkpoint
   - Integrate DisplayManager

5. **Update CLI** (20 minutes)
   - Add --no-repair flag
   - Use unified execution function
   - Preserve handler signatures

6. **Remove RuntimeValidationNode** (20 minutes)
   - Delete from planner (lines specified)
   - Update node count from 12 to 11
   - Redirect validator output

7. **Delete Test Files** (5 minutes)
   - Remove 4 RuntimeValidation test files
   - Update comment in parameter test

## Critical Success Factors

### Must Preserve
1. **`compile_ir_to_flow` signature** - Test boundary
2. **Handler parameter orders** - CLI compatibility
3. **Exception propagation** - Error handling
4. **Progress callback format** - UI consistency

### Must Implement
1. **Checkpoint in `shared["__execution__"]`** - At root level
2. **Cached node display** - Clear user feedback
3. **Template error context** - Helpful repair prompts
4. **Resume without re-execution** - No side effects

### Risk Mitigation
1. **Test frequently** - Run tests after each component
2. **Preserve interfaces** - Don't modify public APIs
3. **Use existing patterns** - Follow established conventions
4. **Document changes** - Update relevant documentation

## Conclusion

The research confirms that Phase 2 implementation is straightforward with minimal risk. InstrumentedNodeWrapper provides the perfect injection point for checkpoint logic, OutputController easily supports cached display, and RuntimeValidationNode offers excellent patterns for the repair service. The existing test infrastructure will largely remain intact, with only RuntimeValidation-specific tests requiring deletion.

The key insight is that we're not fighting the architecture - we're extending it naturally. The shared store was always meant to hold execution state, and InstrumentedNodeWrapper was designed for instrumentation. We're simply making that instrumentation more sophisticated to enable resume-based repair.