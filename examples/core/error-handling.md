# Error Handling Example

## Purpose
This example demonstrates error handling patterns using action-based routing. It shows:
- Multiple paths through a workflow based on success/failure
- Error recovery with retry logic
- The "error" action for exception handling
- Inspired by pocketflow-flow's action-based routing pattern

## Use Case
Essential for robust workflows that need:
- File operations with error recovery
- Processing with validation
- Fallback content generation
- Any operation that might fail and needs logging

## Visual Flow
```
                  ┌─────────────────┐
                  │  read_source    │
                  └────────┬────────┘
                    │            │
                 (default)    (error)
                    ↓            ↓
           ┌────────────┐  ┌─────────────┐
           │process_file│  │  log_error  │
           └─────┬──────┘  └──────┬──────┘
             │      │              │
         (default)(error)      (default)
             ↓      └──→          ↓
      ┌────────────┐      ┌────────────────┐
      │save_result │      │create_fallback│
      └────────────┘      └────────────────┘
```

## Node Explanation
1. **read_source**: Read input file
   - On success: proceeds to process_file
   - On error: routes to log_error

2. **process_file**: Process the file content
   - On success: proceeds to save_result
   - On error: routes to log_error

3. **save_result**: Write processed result
   - On error: routes to log_error

4. **log_error**: Central error logging
   - Logs the error to a file
   - Always proceeds to create_fallback

5. **create_fallback**: Generate fallback content
   - Creates a default output file
   - Ensures workflow produces some output

## Action-Based Routing
- **default**: Implicit action for success cases (can be omitted)
- **error**: Triggered when a node fails
- All error paths lead to logging and fallback generation

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
