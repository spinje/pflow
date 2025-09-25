# API Warning System: Architectural Insights

## Date: 2025-01-23

## Executive Summary

During implementation of the cache chunks integration and MCP error handling, we discovered a fundamental gap in the workflow execution model: the need for a **third execution state** between success and failure. This document captures the insights, reasoning, and proposed architecture for handling API warnings - situations where the workflow executed correctly but the API returned a business logic error that requires user intervention rather than workflow repair.

### The Simple Solution

**Two mechanisms solve 99% of the problem:**

1. **Loop Detection** (10 lines of code): If repair produces the same error, stop trying. This catches ALL non-repairable errors.

2. **API Pattern Detection** (20 lines of code): For obvious API errors (e.g., `{"ok": false}`), skip repair entirely.

That's it. No complex error taxonomy needed.

## The Discovery

### Initial Problem
While testing the repair system with Slack's MCP integration, we found that invalid channel IDs resulted in:
- HTTP 200 (successful API call)
- Response: `{"ok": false, "error": "channel_not_found"}`
- Workflow continued with error data
- No repair triggered (because no workflow error occurred)

### The Deeper Issue
This exposed a fundamental categorization problem:
1. **Current Model**: Binary (Success ✓ or Error ✗)
2. **Reality**: Three distinct states exist
3. **Gap**: No way to distinguish repairable workflow errors from non-repairable data errors

## The Three-State Execution Model

### 1. Success (✓) - Everything Worked
- Workflow executed correctly
- API returned expected data
- Continue to next node
- **Example**: Slack returns messages from valid channel

### 2. Warning (⚠️) - Correct Execution, Wrong Data
- Workflow executed correctly
- API returned an error response
- Cannot be fixed by repair (data issue, not workflow issue)
- Needs user intervention
- **Example**: Slack returns "channel_not_found"

### 3. Error (✗) - Workflow Error
- Workflow failed to execute
- Template errors, missing nodes, syntax issues
- Potentially repairable
- **Example**: `${slack.response.username}` when field is `${slack.response.user}`

## Why This Distinction Matters

### User Experience Impact
Without warnings, users face two bad options:
1. **Continue blindly**: Workflow proceeds with error data, causing cascading failures
2. **Fail completely**: Treat as error, attempt futile repairs on non-repairable issues

### Repair System Confusion
The repair system cannot fix:
- Non-existent resources (channels, users, files)
- Invalid credentials
- Permission errors
- Rate limits

Attempting to repair these wastes LLM tokens and confuses users.

### Semantic Clarity
API errors are fundamentally different from workflow errors:
- **API Error**: "The channel doesn't exist" (data problem)
- **Workflow Error**: "I don't know how to access the channel" (structure problem)

## Architectural Solution: Two-Layer Protection

### Layer 1: Loop Detection (Primary Defense)

The simplest and most comprehensive solution is detecting when repair isn't making progress:

```python
# In workflow_execution.py
if current_errors == previous_errors:
    logger.info("Repair made no progress, stopping attempts")
    break
```

**Why this is powerful**: It catches ALL non-repairable errors regardless of type - API errors, permission errors, missing resources, etc. If repair can't fix it, the error signature won't change.

### Layer 2: API Warning Detection (Optimization)

For obvious API errors, we can skip repair attempts entirely by detecting them in InstrumentedNodeWrapper:

### Why InstrumentedNodeWrapper?

The InstrumentedNodeWrapper is the ideal location for API detection because:

1. **Universal Coverage**: Wraps ALL nodes, providing consistent behavior
2. **Result Inspection**: Already examines node outputs for metrics/tracing
3. **State Management**: Already tracks execution state in shared store
4. **Progress Reporting**: Already handles progress callbacks for display
5. **Single Implementation**: One solution for all API-like nodes (MCP, HTTP, GitHub, etc.)

### Why NOT in Individual Nodes?

Handling in each node would be problematic:
- **Code Duplication**: Same logic in every API node
- **Inconsistency Risk**: Different nodes might handle differently
- **Maintenance Burden**: Updates needed in multiple places
- **Coupling**: Nodes shouldn't know about display/repair concerns

### Detection Strategy

```python
def _detect_api_warning(self, result: Any, shared: dict) -> Optional[str]:
    """Dead simple check for obvious API errors."""

    output = shared.get(self.node_id)
    if isinstance(output, dict):
        # Just three patterns that catch 90% of cases
        if output.get("ok") is False:  # Slack
            return f"API error: {output.get('error')}"
        if output.get("success") is False and "error" in output:  # Generic
            return f"API error: {output.get('error')}"
        if output.get("isError") is True:  # MCP
            return f"API error: {output.get('error', {}).get('message')}"

    return None  # Loop detection will catch anything we miss
```

## Integration with Existing Systems

### Checkpoint System
- Warnings still record node as "completed" in checkpoint
- On resume, warning nodes are not re-executed
- Preserves the "no duplicate side effects" guarantee

### Repair System
- Checks for `__non_repairable_error__` flag
- Skips repair attempts for warnings
- Shows warnings to user instead of attempting fixes

### Display System
- New event type: `node_warning`
- Display: `node-name... ⚠️ error_message 1.2s`
- Clear visual distinction from success/failure

### Cache Chunks
- Warnings don't affect cache chunk flow
- Planner context still available if repair needed for other errors
- Maintains cost optimization benefits

## Implementation Architecture

### Data Flow
1. **Node Execution**: API node returns error data (not exception)
2. **Wrapper Detection**: InstrumentedNodeWrapper detects API warning pattern
3. **State Storage**: Warning stored in `shared["__warnings__"]`
4. **Progress Display**: Shows ⚠️ symbol with error message
5. **Flow Control**: Returns "error" action to stop workflow
6. **Repair Prevention**: Sets `__non_repairable_error__` flag
7. **User Notification**: Display shows warnings, no repair attempted

### Shared Store Structure
```python
shared = {
    "__execution__": {
        "completed_nodes": ["slack-fetch"],  # Node completed
        "node_actions": {"slack-fetch": "error"},  # But returned error
    },
    "__warnings__": {
        "slack-fetch": "API error: channel_not_found"
    },
    "__non_repairable_error__": True  # Prevents repair attempts
}
```

## Benefits of This Architecture

### 1. Separation of Concerns
- Nodes focus on API interaction
- Wrapper handles execution semantics
- Display manages user feedback
- Repair system handles only fixable issues

### 2. Extensibility
- New API nodes automatically get warning support
- New error patterns easily added to detection
- No changes needed to PocketFlow core

### 3. User Clarity
- Clear visual feedback (⚠️ vs ✓ vs ✗)
- Meaningful error messages
- No confusing repair attempts

### 4. System Efficiency
- No wasted repair attempts on unfixable issues
- Proper checkpoint tracking
- Clean error propagation

## Edge Cases and Considerations

### Multiple Warnings
If multiple nodes produce warnings, all are collected and displayed.

### Warning Recovery
Future enhancement: Allow workflows to handle warnings with conditional edges:
```python
slack_node - "warning" >> fallback_node
```

### Partial Success
Some APIs return partial data with warnings. Current approach treats as warning (conservative).

### Silent Warnings
Some warnings might not require stopping workflow. Future: severity levels.

## Future Enhancements

### 1. Warning Severity Levels
- `warning_critical`: Stop workflow (current behavior)
- `warning_info`: Log but continue
- `warning_retry`: Attempt retry with backoff

### 2. User Prompts
For critical resources, prompt user:
```
⚠️ Channel 'INVALID_CHANNEL_ID' not found.
Would you like to:
1. Create the channel
2. Use a different channel
3. Skip this step
```

### 3. Conditional Handling in Workflows
Enable planner to generate warning-aware workflows:
```python
edges = [
    {"from": "slack-fetch", "to": "process-messages"},
    {"from": "slack-fetch", "to": "create-channel", "action": "warning"}
]
```

### 4. Warning Context in Repair
If subsequent nodes fail due to missing data from warned node, include warning context in repair.

## Implementation Priority

### Phase 1: Core Warning System (Immediate)
1. Add `_detect_api_warning()` to InstrumentedNodeWrapper
2. Update OutputController with `node_warning` event
3. Modify repair system to skip non-repairable errors
4. Test with Slack MCP

### Phase 2: Enhanced Display (Near-term)
1. Show warning details in final summary
2. Add warning count to workflow completion message
3. Include warnings in trace output

### Phase 3: Workflow Integration (Future)
1. Support warning edges in IR
2. Update planner to generate warning handlers
3. Add retry logic for transient warnings

## Key Design Decisions

### 1. Stop on Warning (vs Continue)
**Decision**: Stop workflow on warning
**Rationale**: Subsequent nodes likely to fail without expected data
**Alternative**: Continue with warning flag (risked cascading failures)

### 2. Wrapper-Level Detection (vs Node-Level)
**Decision**: Detect in InstrumentedNodeWrapper
**Rationale**: Single implementation, consistent behavior, proper separation
**Alternative**: Each node handles (code duplication, inconsistency risk)

### 3. Non-Repairable Flag (vs Separate State)
**Decision**: Use flag to prevent repair
**Rationale**: Minimal change to existing repair flow
**Alternative**: New workflow state (required PocketFlow core changes)

## Testing Strategy

### Test Case 1: Slack Channel Not Found
- Input: Invalid channel ID
- Expected: ⚠️ warning display, no repair attempt

### Test Case 2: HTTP 404 Response
- Input: Non-existent URL
- Expected: ⚠️ warning for 404, workflow stops

### Test Case 3: Mixed Errors
- Input: Template error + API warning
- Expected: Repair fixes template, warning still shown

### Test Case 4: Checkpoint Resume
- Input: Warning after checkpoint
- Expected: Warned node not re-executed on resume

## Conclusion

The API warning system represents a critical evolution in the workflow execution model. By recognizing that not all failures are equal, we can provide better user experience, more efficient repair attempts, and clearer semantic distinction between workflow errors and data issues.

**The beauty is in the simplicity**: ~30 lines of code total:
- 10 lines for loop detection (catches everything)
- 20 lines for API pattern detection (optimization for obvious cases)

No complex error taxonomies. No comprehensive pattern matching. Just two simple checks that prevent the vast majority of wasted repair attempts.

This maintains PocketFlow's simplicity while solving a real problem. The three-state model (Success/Warning/Error) better reflects reality, but the implementation remains minimal and maintainable.