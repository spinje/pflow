# PocketFlow Patterns for Task 3: Execute a Hardcoded 'Hello World' Workflow

## Task Context

- **Goal**: Execute a simple workflow from JSON IR to validate the core pipeline
- **Dependencies**: Tasks 1, 2, 4, 5, 6, 11 (core infrastructure)
- **Constraints**: Must establish patterns that ALL future workflows will follow

## Overview

This task involves executing a simple, hardcoded workflow from a JSON file using PocketFlow's core components. **CRITICAL: The patterns established here set precedents for all flow execution in pflow.**

## Foundation Patterns (NEW)

These patterns from our advanced analysis of 7 PocketFlow applications are fundamental to pflow's success:

### Pattern: Linear Flow Composition
**Found in**: ALL 7 repositories analyzed
**Why It's Fundamental**: Proves complex behavior emerges from simple composition

```python
# The canonical pflow pattern - simple >> chaining
flow = read_file >> process >> write_file

# NOT: Complex conditional flows (deferred to v2.0)
# NOT: Async execution (not in MVP)
# NOT: Dynamic flow modification
```

### Pattern: Natural Shared Store Keys
**Found in**: ALL repositories (eliminated proxy needs in 90% of cases)
**Why It's Fundamental**: Intuitive keys prevent collisions naturally

```python
# YES: Natural, self-documenting keys
shared = {
    "file_path": "input.txt",
    "content": "file contents",
    "processed_content": "transformed data",
    "output_path": "output.txt"
}

# NO: Generic keys that collide
shared = {
    "data": "...",
    "input": "...",
    "output": "..."
}
```

### Pattern: Progressive State Building
**Found in**: 6/7 repositories
**Why It's Fundamental**: Enables free debugging and tracing

```python
# Each node adds to shared store, never removes
class ProcessNode(Node):
    def post(self, shared, prep_res, exec_res):
        # Add new keys
        shared["processed_content"] = exec_res
        shared["processing_time"] = time.time() - self.start_time
        # Never: del shared["content"] or shared.clear()
        return "default"
```

## Relevant Cookbook Examples

- `cookbook/pocketflow-hello-world`: Basic flow setup and execution
- `cookbook/pocketflow-flow`: Interactive flow with action-based transitions
- `cookbook/pocketflow-communication`: Shared store usage patterns

## Patterns to Adopt

### Pattern: Basic Flow Execution
**Source**: `cookbook/pocketflow-hello-world/`
**Compatibility**: ✅ Direct
**Description**: Simple flow creation and execution with shared store

**Original PocketFlow Pattern**:
```python
from pocketflow import Flow, Node

# Create nodes
hello_node = HelloNode()
world_node = WorldNode()

# Create flow
flow = Flow()
flow.start(hello_node) >> world_node

# Execute with shared store
shared = {}
result = flow.run(shared)
```

**Adapted for pflow**:
```python
# Load IR from JSON file
with open("hello_workflow.json") as f:
    ir_json = json.load(f)

# Compile to Flow (using Task 4's converter)
flow = compile_ir_to_flow(ir_json)

# Initialize shared store
shared = {}
if stdin_detected():  # Task 8 pattern
    shared["stdin"] = read_stdin()

# Execute
result = flow.run(shared)

# Validate results
validate_shared_store(shared)
```

**Key Adaptations**:
- JSON IR loading instead of hardcoded flow
- Shared store initialization with stdin handling
- Post-execution validation

### Pattern: Shared Store Initialization
**Source**: `cookbook/pocketflow-communication/`
**Compatibility**: ✅ Direct
**Description**: Proper shared store setup and lifecycle

**Original PocketFlow Pattern**:
```python
shared = {"initial_data": "value"}
flow.run(shared)
# Nodes modify shared during execution
```

**Adapted for pflow**:
```python
def initialize_shared_store(cli_args=None, stdin_content=None):
    """Initialize clean shared store for workflow execution."""
    shared = {}

    # Pre-populate with stdin if available
    if stdin_content:
        shared["stdin"] = stdin_content

    # Add CLI data flags (not params)
    if cli_args:
        data_flags, _ = categorize_flags(cli_args)
        shared.update(data_flags)

    return shared

def validate_execution_result(shared, expected_keys):
    """Validate shared store after execution."""
    for key in expected_keys:
        if key not in shared:
            warnings.warn(f"Expected key '{key}' not found in shared store")

    # Log final state for debugging
    logger.debug(f"Final shared store: {list(shared.keys())}")
```

### Pattern: Minimal Node Implementation
**Source**: `cookbook/pocketflow-node/`
**Compatibility**: ✅ Direct
**Description**: Simple read/write nodes for hello world

**Implementation for pflow**:
```python
from pocketflow import Node

class ReadFileNode(Node):
    def prep(self, shared):
        file_path = shared.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required input: file_path")
        return file_path

    def exec(self, file_path):
        with open(file_path, 'r') as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        return "default"

class WriteFileNode(Node):
    def prep(self, shared):
        content = shared.get("content")
        file_path = shared.get("file_path") or self.params.get("file_path")
        return {"content": content, "file_path": file_path}

    def exec(self, prep_res):
        with open(prep_res["file_path"], 'w') as f:
            f.write(prep_res["content"])
        return prep_res["file_path"]

    def post(self, shared, prep_res, exec_res):
        shared["written_file"] = exec_res
        return "default"
```

## Patterns to Avoid

### Pattern: Complex Execution Logic
**Source**: Various advanced examples
**Issue**: Reimplementing what PocketFlow already provides
**Alternative**: Use Flow.run() directly, don't wrap execution

### Pattern: Dynamic Flow Modification
**Source**: Advanced flow manipulation examples
**Issue**: Not needed for MVP hello world
**Alternative**: Static IR-based flow definition

### Anti-Pattern: Over-Engineering Simple Flows
**Found in**: Tutorial-Cursor (agent loops)
**Issue**: Adding complexity where none is needed
**Alternative**: Linear composition for deterministic execution

### Anti-Pattern: Generic Key Names
**Found in**: Early iterations of several tutorials
**Issue**: Leads to collisions and proxy requirements
**Alternative**: Natural, descriptive key names

## Implementation Guidelines

1. **Keep it simple**: This is the first integration test of core components
2. **Use PocketFlow directly**: Don't add unnecessary abstractions
3. **Focus on integration**: CLI → IR → Flow → Execution → Results
4. **Test the full pipeline**: This validates the entire architecture
5. **Clear error messages**: Help debug integration issues

## Example Workflow JSON

```json
{
  "nodes": [
    {
      "id": "reader",
      "type": "read-file",
      "params": {"file_path": "input.txt"}
    },
    {
      "id": "writer",
      "type": "write-file",
      "params": {"file_path": "output.txt"}
    }
  ],
  "edges": [
    {"from": "reader", "to": "writer"}
  ],
  "start_node": "reader"
}
```

## Testing Approach

```python
def test_hello_world_workflow():
    # Create test files
    with open("input.txt", "w") as f:
        f.write("Hello, World!")

    # Load and execute workflow
    cli_runner = CliRunner()
    result = cli_runner.invoke(cli, ["run", "--file", "hello_workflow.json"])

    # Verify execution
    assert result.exit_code == 0
    assert os.path.exists("output.txt")
    with open("output.txt") as f:
        assert f.read() == "Hello, World!"
```

This hello world workflow validates the entire pflow architecture from CLI to execution.

## Integration Points

### Connection to Task 4 (IR-to-Flow Converter)
Task 3 depends on Task 4's `compile_ir_to_flow()` function:
```python
# Task 3 uses Task 4's converter
flow = compile_ir_to_flow(ir_json)  # Task 4 provides this
result = flow.run(shared)           # Task 3 executes this
```

### Connection to Task 9 (Shared Store)
Task 3 establishes the natural key pattern that Task 9 builds upon:
```python
# Natural keys established here prevent proxy needs later
shared["file_path"] = "input.txt"   # Clear, no collision
shared["content"] = file_contents    # Descriptive, natural
```

### Connection to Task 11 (File Nodes)
The simple read/write nodes here are the prototypes for Task 11's full implementation.

### Connection to Task 23 (Execution Tracing)
Progressive state building established here enables tracing:
```python
# Task 23 can diff states because we build progressively
before = {"file_path": "input.txt"}
after = {"file_path": "input.txt", "content": "data", "written_file": "output.txt"}
# Diff shows exactly what each node added
```

## Minimal Test Case

```python
# Save as test_hello_patterns.py and run with pytest
import json
import os
from pocketflow import Node, Flow

class SimpleReadNode(Node):
    """Minimal node following all patterns"""
    def prep(self, shared):
        # Natural key, check shared first then params
        self.file_path = shared.get("file_path") or self.params.get("file_path")
        if not self.file_path:
            raise ValueError("Missing required input: file_path")

    def exec(self, prep_res):
        with open(self.file_path, 'r') as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        # Progressive building - add, don't remove
        shared["content"] = exec_res
        shared["read_from"] = self.file_path
        return "default"

def test_foundation_patterns():
    # Create test file
    with open("test_input.txt", "w") as f:
        f.write("Hello, pflow!")

    # Natural key naming
    shared = {"file_path": "test_input.txt"}

    # Linear flow composition
    node = SimpleReadNode()
    flow = Flow(start=node)

    # Execute
    result = flow.run(shared)

    # Verify progressive state building
    assert "file_path" in shared  # Original key preserved
    assert "content" in shared     # New key added
    assert "read_from" in shared   # Metadata added
    assert shared["content"] == "Hello, pflow!"

    # Cleanup
    os.remove("test_input.txt")

if __name__ == "__main__":
    test_foundation_patterns()
    print("✓ All foundation patterns validated")
```

## Summary

Task 3 establishes three critical patterns that permeate all of pflow:
1. **Linear Flow Composition** - Simple >> chaining for deterministic execution
2. **Natural Shared Store Keys** - Intuitive naming prevents 90% of proxy needs
3. **Progressive State Building** - Append-only state enables free debugging

Every future task should reference these foundation patterns.
