# PocketFlow Parameter Handling - Investigation Process

## Timeline of Discovery

### 1. Initial Implementation (Task 3)
Another AI agent implemented the workflow execution feature with a seemingly correct approach:
- Created `compile_ir_to_flow()` function
- Set parameters on nodes during compilation
- Used standard PocketFlow Flow class

### 2. The Mystery Bug
When testing with a simple workflow (read file → write file), the execution failed with:
```
Error: Missing required 'file_path' in shared store or params
```

This was puzzling because:
- The compiler clearly set params: `node.set_params({"file_path": "input.txt"})`
- The nodes were designed to check params as fallback
- Everything looked correct in the code

### 3. Initial Hypothesis
First thought was that parameters weren't being set correctly, but debugging showed:
- Parameters were set successfully during compilation
- Node inspection after compilation showed correct params
- Something was happening during execution

### 4. The Discovery
By adding logging to the node's prep() method, we discovered:
- During compilation: `self.params = {"file_path": "input.txt"}`
- During execution: `self.params = {}`

The parameters were being cleared somehow!

### 5. Root Cause Analysis
Tracing through PocketFlow's execution flow:
1. `flow.run(shared)` calls `_run()`
2. `_run()` calls `_orch(shared)` with no params argument
3. `_orch()` does: `p = (params or {**self.params})` - which is `{}`
4. Then: `curr.set_params(p)` - overwrites node params with empty dict!

### 6. Understanding the Design
Reading PocketFlow documentation revealed this is intentional:
- Parameters flow from parent → child
- BatchFlow uses this to run flows with different parameters
- The docs explicitly state: "Only set the uppermost Flow params because others will be overwritten"

## Key Investigation Techniques

### 1. Logging at Multiple Points
Added logging to understand parameter state:
- After compilation
- Before execution
- Inside node prep()
- Inside PocketFlow's _orch()

### 2. Reading Source Code
Critical to read the actual PocketFlow implementation, not just documentation:
- Found the exact line causing the issue
- Understood the parameter flow model
- Discovered `set_params()` replaces, not merges

### 3. Understanding Use Cases
Examined PocketFlow cookbook examples:
- BatchFlow examples showed why parameter overwriting is needed
- Understood the hierarchical parameter model
- Realized pflow's use case is fundamentally different

### 4. Testing Hypotheses
Created minimal test cases to verify understanding:
- Confirmed parameters are overwritten even when Flow has empty params
- Tested what happens with explicit flow parameters
- Verified BatchFlow dependency on current behavior

## Lessons for Future Debugging

### 1. Don't Assume Framework Behavior
Even well-designed frameworks may have surprising behavior for valid reasons.

### 2. Log State Transitions
When data mysteriously changes, log it at every transition point.

### 3. Read the Source
Documentation explains intent, but source code reveals actual behavior.

### 4. Understand the Design Context
A "bug" might be intentional behavior for a different use case.

### 5. Test Minimal Cases
Strip away complexity to isolate the exact issue.

## Red Herrings Avoided

### 1. "Maybe parameters aren't being set"
Easy to assume the problem is in our code, but parameters were set correctly.

### 2. "Maybe nodes are checking wrong"
The fallback pattern `shared.get() or self.params.get()` was correct.

### 3. "Maybe it's a deep copy issue"
PocketFlow does copy nodes, but that wasn't the issue.

### 4. "Maybe we need to use shared store only"
This would have worked but missed the real issue and created worse design.
