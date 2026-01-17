# Task 78: Save User Request History in Workflow Metadata

## Description
Add functionality to save a list of unique user requests that triggered a workflow in the workflow JSON file's metadata. This will help the pflow agent better match ambiguous user requests by learning from actual usage patterns, significantly improving confidence when users use informal language like "do the thing" that previously triggered a specific workflow.

## Status
not started

## Dependencies
- Task 24: Implement Workflow Manager - The workflow manager handles saving/loading workflows and would be the natural place to implement request history tracking
- Task 22: Named workflow execution - Need workflows to be saved and reusable before we can track their execution history

## Priority
medium

## Details
Currently, the pflow agent has to guess whether ambiguous requests like "analyze customer churn" or "do the churn thing" match existing workflows. This task will implement a request history feature that captures the actual user requests that successfully triggered workflow execution.

### Key Implementation Requirements
- Store unique user requests in the workflow's metadata section
- Each request entry should include:
  - The original request text (non-templatized)
  - Timestamp of when it was used
  - Parameters that were used for that execution
- Integrate with existing rich metadata structure that already tracks execution_count and last_execution_params
- Ensure no duplicate requests are stored
- Consider privacy implications and storage limits

### Technical Design
The request history will be stored in the workflow JSON metadata alongside existing execution tracking:

```json
{
  "metadata": {
    "execution_history": {
      "requests": [
        {
          "text": "analyze customer churn for October",
          "timestamp": "2025-10-01T10:00:00Z",
          "params_used": {"period": "October"}
        },
        {
          "text": "do the churn thing",
          "timestamp": "2025-10-02T14:30:00Z",
          "params_used": {"period": "current_month"}
        }
      ],
      "execution_count": 15,
      "last_execution_timestamp": "2025-10-04T09:00:00Z"
    }
  }
}
```

### How This Helps the Agent
1. **Pattern Recognition**: Agent can see that "do the churn thing" previously triggered the customer-churn-analysis workflow
2. **Confidence Building**: Exact or similar phrase matches provide high confidence for workflow matching
3. **Domain Language Learning**: Captures how specific users refer to workflows in their business context
4. **Intent Clarity**: Previous successful executions prove a phrase is an action request, not exploration

### Implementation Considerations
- **Storage Limits**: Keep only last N unique requests (e.g., 20) to prevent unbounded growth
- **Privacy**: Some requests might contain sensitive data - need to consider sanitization
- **Evolution Handling**: Requests that worked with old workflow versions might not work with new ones
- **Parameter Inference**: Need to handle how "do it for last week" maps to actual parameters

### Integration Points
- Workflow executor needs to capture the original user request
- Workflow manager needs to update metadata when saving
- Agent instructions should be updated to leverage this history for matching (separate task)

## Test Strategy
Testing will ensure the request history feature works correctly and provides value:

- **Unit Tests**:
  - Test unique request detection (no duplicates)
  - Test storage limit enforcement
  - Test metadata structure validation
  - Test request sanitization if implemented

- **Integration Tests**:
  - Test request capture during workflow execution
  - Test metadata persistence across save/load cycles
  - Test that request history survives workflow updates
  - Test parameter tracking alongside requests

- **End-to-End Tests**:
  - Execute workflow with various phrasings
  - Verify history accumulates correctly
  - Test agent's ability to use history for matching (future task)

- **Edge Cases**:
  - Very long request strings
  - Requests with special characters
  - Concurrent executions
  - Migration of existing workflows without history