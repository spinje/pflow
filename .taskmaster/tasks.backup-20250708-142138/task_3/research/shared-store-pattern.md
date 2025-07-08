# Shared Store Pattern for Task 3

## Overview
Task 3 requires initializing "a clean shared store dictionary and run the flow with it."

## Shared Store Basics
From the documentation and examples:
- Shared store is a simple Python dictionary
- Nodes communicate by reading/writing to this dictionary
- Initialize as: `shared = {}`

## File Node Interface Pattern
From Task 11 and documentation:

### ReadFileNode
- **Input**: `shared['file_path']` - Path to file to read
- **Output**: `shared['content']` - File contents

### WriteFileNode
- **Input**:
  - `shared['content']` - Content to write
  - `shared['file_path']` - Where to write it

## Flow Execution Example
```python
# Initialize shared store
shared = {}

# For hello_workflow.json with params:
# read-file node params: {"file_path": "hello_input.txt"}
# write-file node params: {"file_path": "hello_output.txt"}

# The flow execution would:
# 1. read-file node reads from params['file_path']
# 2. read-file writes content to shared['content']
# 3. write-file reads shared['content']
# 4. write-file writes to its params['file_path']
```

## Testing Shared Store State
In the test, verify final state:
```python
# After flow execution
assert 'content' in shared
assert shared['content'] == expected_content
```

## Important Notes
- Nodes can read from both params (set_params) and shared store
- Priority: Check shared store first, then params
- This enables data flow between nodes
