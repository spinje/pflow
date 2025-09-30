# API Warning System: Implementation Guide

## Date: 2025-01-23

## Overview

This document provides the concrete implementation details for adding the API warning system to pflow, addressing the critical gap where API business errors trigger futile repair attempts.

## Current State Analysis

### The Repair Loop Problem
```python
# workflow_execution.py lines 133-195
while runtime_attempt < max_runtime_attempts:  # 3 attempts
    result = executor.execute_workflow(...)
    if not result.success:
        # repair_workflow_with_validation itself has 3 attempts
        # Each attempt validates, which could trigger 3 more repairs
        # Total: up to 27 LLM calls for unfixable API errors!
```

**Critical Issue**: No detection of non-repairable errors before repair attempts.

### Checkpoint System Integration Points
```python
# instrumented_wrapper.py lines 298-304
shared["__execution__"] = {
    "completed_nodes": [],      # Nodes that ran successfully
    "node_actions": {},         # Action each node returned
    "failed_node": None        # Node that failed (if any)
}
```

**Key Insight**: Warnings must be recorded as completed (no re-execution) but with error action (stop workflow).

## Implementation Philosophy

**We're NOT trying to**:
- Predict all repairable vs non-repairable errors
- Create a comprehensive error taxonomy
- Handle every edge case

**We ARE trying to**:
- Prevent obvious waste (API errors)
- Detect when we're stuck (loop detection)
- Keep it simple and maintainable

## Implementation Plan

### Phase 0: Loop Detection (Simplest, Most Effective)

**This catches ALL non-repairable errors, not just API ones.**

#### Location: `src/pflow/execution/workflow_execution.py` line 135

```python
# Add before the while loop
last_error_signature = None

while runtime_attempt < max_runtime_attempts:
    result = executor.execute_workflow(...)

    if result.success:
        return result

    # NEW: Check if we're stuck in a loop
    error_signature = "|".join(e.get("message", "")[:50] for e in result.errors[:3])
    if error_signature == last_error_signature:
        logger.info("Same error after repair attempt, stopping repair loop")
        return result  # Stop trying, we're stuck

    last_error_signature = error_signature

    # Continue with repair attempts...
```

**Why this works**: If repair can't fix something, the same error repeats. This is a universal signal of non-repairability.

### Phase 1: Minimal Viable Warning System (Urgent)

#### Step 1.1: Add Detection to InstrumentedNodeWrapper

**Location**: `src/pflow/runtime/instrumented_wrapper.py` after line 335

```python
# After successful execution (line 335), before recording success
result = self.inner_node._run(shared)

# NEW: Check for API warning patterns
warning_message = self._detect_api_warning(result, shared)
if warning_message:
    # Record as completed but with warning
    shared["__execution__"]["completed_nodes"].append(self.node_id)
    shared["__execution__"]["node_actions"][self.node_id] = "error"

    # Store warning details
    if "__warnings__" not in shared:
        shared["__warnings__"] = {}
    shared["__warnings__"][self.node_id] = warning_message

    # CRITICAL: Set non-repairable flag to prevent repair attempts
    shared["__non_repairable_error__"] = True

    # Calculate duration
    duration_ms = (time.perf_counter() - start_time) * 1000

    # Record metrics
    if self.metrics_collector:
        self.metrics_collector.record_node_execution(
            self.node_id, duration_ms, is_planner=self.is_planner
        )

    # Call progress callback with warning
    if callable(callback):
        with contextlib.suppress(Exception):
            # Show warning with message
            callback(self.node_id, "node_warning", warning_message, depth)

    # Record trace
    self._record_trace(duration_ms, shared_before, dict(shared),
                      success=False, warning=warning_message)

    # Return error action to stop workflow
    return "error"

# Continue with normal success recording...
```

#### Step 1.2: Add Simple Detection Method

**Location**: Add to InstrumentedNodeWrapper class

```python
def _detect_api_warning(self, result: Any, shared: dict) -> Optional[str]:
    """
    Dead simple check for obvious API errors.

    Principle: If execution succeeded but returned error data,
    it's probably not fixable by workflow repair.
    """
    # Check the node's output in shared store
    if self.node_id not in shared:
        return None

    output = shared[self.node_id]

    # Just check for obvious "successful but error" patterns
    if isinstance(output, dict):
        # These patterns mean API call worked but returned error
        if output.get("ok") is False:  # Slack pattern
            return f"API error: {output.get('error', 'unknown')}"

        if output.get("success") is False and "error" in output:  # Generic
            return f"API error: {output.get('error', 'unknown')}"

        if output.get("isError") is True:  # MCP pattern
            error_info = output.get('error', {})
            if isinstance(error_info, dict):
                return f"API error: {error_info.get('message', 'unknown')}"
            return f"API error: {error_info}"

    # That's it. Loop detection will catch everything else.
    return None
```

**Note**: We're NOT trying to be comprehensive. Just catch the most obvious cases.

#### Step 1.3: Prevent Repair Attempts

**Location**: `src/pflow/execution/workflow_execution.py` after line 157

```python
if result.success:
    return result

# NEW: Check for non-repairable errors before attempting repair
if result.shared_after.get("__non_repairable_error__"):
    logger.info("Non-repairable API error detected, skipping repair attempts")

    # Include warning details in result
    warnings = result.shared_after.get("__warnings__", {})
    if warnings:
        # Add warnings to errors list for visibility
        for node_id, warning_msg in warnings.items():
            result.errors.append({
                "source": "api",
                "category": "non_repairable",
                "node_id": node_id,
                "message": warning_msg,
                "fixable": False
            })

    return result  # Return failure without repair

# Runtime execution failed - continue with repair...
runtime_attempt += 1
```

#### Step 1.4: Update Display

**Location**: `src/pflow/core/output_controller.py` line 109

```python
elif event == "node_warning":
    # Display warning with message
    if duration is not None and isinstance(duration, str):
        # Duration is actually the warning message
        click.echo(f"  {node_id}... ⚠️  {duration}")
    else:
        click.echo(f"  {node_id}... ⚠️  API warning")
```

### Phase 2: Enhanced Warning System

#### Step 2.1: Create Warning Action Type

**Location**: `pocketflow/__init__.py` (would require PocketFlow change)

Instead of returning "error", introduce "warning" action:
```python
# In Flow.get_next_node()
if action == "warning":
    # Treat like error but semantically different
    warnings.warn(f"Node {curr} returned warning: stopping workflow")
    return None
```

**Note**: This requires PocketFlow core changes, so Phase 1 uses "error" action.

#### Step 2.2: Enhanced Detection Patterns

Add more sophisticated pattern detection:

```python
class APIWarningDetector:
    """Centralized API warning detection with extensible patterns."""

    PATTERNS = {
        'slack': {
            'indicators': [('ok', False), ('error', str)],
            'extractor': lambda d: f"Slack: {d.get('error')}"
        },
        'github': {
            'indicators': [('message', 'Not Found')],
            'extractor': lambda d: f"GitHub: {d.get('message')}"
        },
        'mcp': {
            'indicators': [('isError', True)],
            'extractor': lambda d: f"MCP: {d.get('error', {}).get('message', 'Unknown')}"
        },
        'http': {
            'status_range': (400, 500),
            'extractor': lambda d: f"HTTP {d.get('status_code')}: {d.get('message', '')}"
        }
    }

    @classmethod
    def detect(cls, node_type: str, result: Any, shared: dict) -> Optional[str]:
        """Detect API warning based on node type and result."""
        # Implementation...
```

#### Step 2.3: Warning Recovery Edges

Future enhancement for PocketFlow:
```python
# In workflow IR
"edges": [
    {"from": "slack-fetch", "to": "process"},
    {"from": "slack-fetch", "to": "handle-missing", "action": "warning"}
]
```

## Testing Implementation

### Test Case 1: Basic Warning Detection
```python
def test_api_warning_prevents_repair():
    """Test that API warnings don't trigger repair."""

    # Create workflow with MCP node
    workflow_ir = {
        "nodes": [{
            "id": "slack-msg",
            "type": "mcp",
            "config": {"tool": "send_message", "channel": "INVALID"}
        }]
    }

    # Mock MCP to return channel_not_found
    with patch("mcp_node.execute") as mock_mcp:
        mock_mcp.return_value = {"ok": False, "error": "channel_not_found"}

        result = execute_workflow(workflow_ir, {}, enable_repair=True)

        # Verify no repair attempted
        assert result.shared_after.get("__non_repairable_error__") is True
        assert "slack-msg" in result.shared_after.get("__warnings__", {})
        assert mock_repair.call_count == 0  # No repair attempts
```

### Test Case 2: Resume After Warning
```python
def test_resume_after_warning():
    """Test that warned nodes aren't re-executed on resume."""

    # Simulate checkpoint with warning
    checkpoint = {
        "__execution__": {
            "completed_nodes": ["fetch-data"],
            "node_actions": {"fetch-data": "error"},
            "failed_node": "fetch-data"
        },
        "__warnings__": {"fetch-data": "API error: resource not found"},
        "__non_repairable_error__": True
    }

    # Resume should not re-execute fetch-data
    result = execute_workflow(workflow_ir, {}, resume_state=checkpoint)

    # Verify fetch-data was skipped
    assert "fetch-data" in result.shared_after["__execution__"]["completed_nodes"]
    # Verify it shows as cached
    assert mock_progress_callback.called_with("fetch-data", "node_cached")
```

### Test Case 3: Mixed Errors
```python
def test_template_error_with_api_warning():
    """Test repair fixes template error but preserves warning."""

    workflow_ir = {
        "nodes": [
            {"id": "api-call", "type": "mcp", "config": {...}},
            {"id": "process", "type": "shell",
             "config": {"command": "echo ${api-call.wrong_field}"}}
        ]
    }

    # First execution: API warning + template error
    # Repair should fix template but not API issue
    result = execute_workflow(workflow_ir, {}, enable_repair=True)

    # Verify template was fixed but API warning remains
    assert "${api-call.wrong_field}" not in result  # Template fixed
    assert "__warnings__" in result.shared_after  # Warning preserved
```

## Implementation Priority

### Must Have: Loop Detection (Phase 0)
**Implement this first**. It's 10 lines of code and solves 100% of stuck repair loops.

### Nice to Have: API Detection (Phase 1)
**Implement if time permits**. It's an optimization that prevents some repair attempts, but loop detection catches everything it misses.

## Rollout Plan

### Day 1: Loop Detection
1. Add error signature comparison to workflow_execution.py
2. Test with any failing workflow
3. Deploy immediately (no risk, huge benefit)

### Week 1: API Detection
1. Add simple pattern detection to InstrumentedNodeWrapper
2. Add non-repairable check to workflow_execution.py
3. Update OutputController for warning display
4. Deploy with feature flag

### Week 2: Testing and Refinement
1. Test with real Slack/GitHub APIs
2. Refine detection patterns
3. Add metrics tracking
4. Document patterns

### Week 3: Phase 2 Planning
1. Design warning recovery edges
2. Propose PocketFlow changes
3. Create migration plan
4. User documentation

## Risk Mitigation

### Risk 1: False Positives
**Mitigation**: Start with conservative patterns, log detections without blocking repair initially.

### Risk 2: Breaking Existing Workflows
**Mitigation**: Feature flag for gradual rollout.

### Risk 3: User Confusion
**Mitigation**: Clear warning messages explaining why repair won't help.

## Success Metrics

1. **Repair Efficiency**: Reduction in futile repair attempts (target: 90% reduction)
2. **User Clarity**: Reduction in support tickets about "repair not working"
3. **Cost Savings**: Reduced LLM token usage on non-repairable errors
4. **Time Savings**: Faster failure feedback (no waiting for repair attempts)

## Configuration

Add to settings for customization:
```json
{
  "api_warning_detection": {
    "enabled": true,
    "patterns": {
      "slack": ["ok", "error"],
      "github": ["message", "Not Found"],
      "http": {"client_errors": true, "range": [400, 499]}
    },
    "prevent_repair": true,
    "log_warnings": true
  }
}
```

## Conclusion

This implementation provides a pragmatic solution to prevent futile repair attempts on API business errors. Phase 1 can be implemented immediately without PocketFlow changes, while Phase 2 enables more sophisticated warning handling with workflow-level recovery options.

The key insight is using the existing checkpoint and repair prevention mechanisms to handle a new class of errors, maintaining backward compatibility while significantly improving the user experience and system efficiency.