# Error Handling Example

## Purpose
This example demonstrates error handling patterns using action-based routing. It shows:
- Multiple paths through a workflow based on success/failure
- Error recovery with retry logic
- The "error" action for exception handling
- Inspired by pocketflow-flow's action-based routing pattern

## Use Case
Essential for robust workflows that need:
- API calls with retry logic
- Data processing with validation
- Database operations with rollback
- Any operation that might fail and needs recovery

## Visual Flow
```
                  ┌─────────────────┐
                  │   fetch_data    │
                  └────────┬────────┘
                    │            │
                 (default)    (error)
                    ↓            ↓
           ┌────────────┐  ┌─────────────┐
           │process_data│  │handle_error │
           └─────┬──────┘  └──────┬──────┘
             │      │           (retry)
         (default)(error)         ↓
             ↓      └──→  ┌─────────────┐
      ┌────────────┐      │ retry_fetch │
      │save_result │      └──────────────┘
      └────────────┘
```

## Node Explanation
1. **fetch_data**: Initial API call
   - On success: proceeds to process_data
   - On error: routes to handle_error

2. **process_data**: Transform the fetched data
   - On success: proceeds to save_result
   - On error: routes to handle_error

3. **save_result**: Persist processed data
   - On error: routes to handle_error

4. **handle_error**: Central error handling
   - Logs the error with severity
   - Can trigger retry via "retry" action

5. **retry_fetch**: Retry logic with increased timeout
   - Uses $retry_count to track attempts
   - Feeds back to process_data

## Action-Based Routing
- **default**: Implicit action for success cases (can be omitted)
- **error**: Triggered when a node fails
- **retry**: Custom action from error handler to trigger retry

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('error-handling.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Multiple retry strategies**: Different retry nodes for different failures
2. **Fallback paths**: Alternative processing when retries exhausted
3. **Partial success**: Some nodes continue despite others failing
4. **Circuit breaker**: Stop retrying after threshold

## Implementation Notes
This pattern is inspired by the pocketflow-flow cookbook example, which demonstrates:
- Action strings for conditional routing
- Multiple paths through a workflow
- State management for retry counts

## Notes
- Error actions are triggered by node failures
- Each node can have multiple outgoing edges with different actions
- The same node can be reached via different paths
- Retry limits should be implemented in the node logic
