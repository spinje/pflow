# PocketFlow Patterns for Task 3: Execute a Hardcoded 'Hello World' Workflow

## Overview

This task involves executing a simple, hardcoded workflow from a JSON file using PocketFlow's core components. The patterns here establish the foundation for all flow execution in pflow.

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
