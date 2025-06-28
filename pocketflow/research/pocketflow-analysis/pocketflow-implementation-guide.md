# PocketFlow Implementation Guide for pflow

This guide provides concrete implementation patterns extracted from PocketFlow for the most common pflow tasks.

## 1. Basic Node Implementation Template

Based on PocketFlow patterns, here's the standard template for pflow nodes:

```python
from pocketflow import BaseNode

class ReadFileNode(BaseNode):
    """
    Read a file from disk and store its content in the shared store.

    Interface:
        Inputs:
            - file_path: Path to the file to read (from shared store)
        Outputs:
            - content: The file contents (to shared store)
    """

    def exec(self):
        # Get input from shared store
        file_path = self.get("file_path")

        # Validate required inputs
        if not file_path:
            raise ValueError("Required input 'file_path' not found in shared store")

        try:
            # Perform the operation
            with open(file_path, 'r') as f:
                content = f.read()

            # Store output in shared store
            self.set("content", content)

        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading file: {e}")
```

## 2. LLM Node Pattern

For LLM integration, following the cookbook patterns:

```python
class LLMNode(BaseNode):
    """
    General-purpose LLM node for text processing.

    Interface:
        Inputs:
            - prompt: The prompt to send to the LLM (from shared store)
        Outputs:
            - response: The LLM's response (to shared store)
    """

    def __init__(self):
        super().__init__()
        self.model = None
        self.temperature = 0.7

    def prep(self):
        # Optional: Initialize LLM client here
        # This runs once before exec
        pass

    def exec(self):
        prompt = self.get("prompt")
        if not prompt:
            raise ValueError("Required input 'prompt' not found in shared store")

        # Call LLM API (using Simon Willison's llm library or direct API)
        response = self._call_llm(prompt)

        self.set("response", response)

    def _call_llm(self, prompt):
        # Implementation details for LLM call
        pass
```

## 3. Flow Construction Pattern

For the IR-to-Flow converter (Task 4):

```python
from pocketflow import Flow

def compile_ir_to_flow(ir_json, registry):
    """Convert JSON IR to executable pocketflow.Flow"""
    flow = Flow()

    # Create nodes from IR
    for node_spec in ir_json["nodes"]:
        node_id = node_spec["id"]
        node_type = node_spec["type"]
        params = node_spec.get("params", {})

        # Look up node class from registry
        NodeClass = registry.get_node_class(node_type)
        if not NodeClass:
            raise ValueError(f"Unknown node type: {node_type}")

        # Instantiate and configure node
        node = NodeClass()
        if params:
            node.set_params(params)

        # Add to flow
        flow.add_node(node_id, node)

    # Connect nodes based on edges
    for edge in ir_json.get("edges", []):
        from_node = edge["from"]
        to_node = edge["to"]
        action = edge.get("action", "default")

        # Use the >> operator with action
        flow.add_edge(from_node, to_node, action)

    # Set start node
    start_node = ir_json.get("start_node")
    if start_node:
        flow.set_start(start_node)

    return flow
```

## 4. Shared Store Proxy Pattern

For Task 9, implementing the NodeAwareSharedStore:

```python
class NodeAwareSharedStore:
    """Proxy wrapper for shared store with collision handling"""

    def __init__(self, shared_store, node_id, mappings=None):
        self._store = shared_store
        self._node_id = node_id
        self._input_mappings = mappings.get("inputs", {}) if mappings else {}
        self._output_mappings = mappings.get("outputs", {}) if mappings else {}

    def get(self, key):
        # Apply input mapping if exists
        actual_key = self._input_mappings.get(key, key)

        # Check if key exists
        if actual_key not in self._store:
            raise KeyError(f"Required key '{key}' (mapped to '{actual_key}') not found in shared store")

        return self._store[actual_key]

    def set(self, key, value):
        # Apply output mapping if exists
        actual_key = self._output_mappings.get(key, key)

        # Check for reserved keys
        if actual_key in RESERVED_KEYS:
            raise ValueError(f"Cannot write to reserved key: {actual_key}")

        self._store[actual_key] = value
```

## 5. Tool Integration Pattern

For external tool nodes (GitHub, Git, etc.):

```python
import subprocess

class GitCommitNode(BaseNode):
    """
    Create a git commit with the provided message.

    Interface:
        Inputs:
            - message: Commit message (from shared store)
            - files: Optional list of files to stage (from shared store)
        Outputs:
            - commit_hash: The created commit's hash (to shared store)
    """

    def exec(self):
        message = self.get("message")
        if not message:
            raise ValueError("Required input 'message' not found in shared store")

        files = self.get("files", [])  # Optional with default

        try:
            # Stage files if provided
            if files:
                for file in files:
                    subprocess.run(["git", "add", file], check=True)

            # Create commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                check=True
            )

            # Extract commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True
            )

            commit_hash = hash_result.stdout.strip()
            self.set("commit_hash", commit_hash)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {e.stderr}")
```

## 6. Common Patterns and Best Practices

### Input Validation Pattern
```python
def exec(self):
    # Always validate required inputs first
    required_inputs = ["input1", "input2"]
    for input_key in required_inputs:
        if not self.get(input_key):
            raise ValueError(f"Required input '{input_key}' not found in shared store")
```

### Safe External Command Pattern
```python
def _run_command(self, cmd, check=True):
    """Run external command safely"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=30  # Prevent hanging
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out: {' '.join(cmd)}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {e.stderr}")
```

### Parameter vs Shared Store Pattern
```python
def __init__(self):
    super().__init__()
    # Node configuration parameters (behavior)
    self.timeout = 30
    self.retry_count = 3

def exec(self):
    # Data comes from shared store
    data = self.get("input_data")

    # Behavior comes from parameters
    for i in range(self.retry_count):
        try:
            result = self.process(data, timeout=self.timeout)
            break
        except Exception as e:
            if i == self.retry_count - 1:
                raise
```

## Key Implementation Rules

1. **Always inherit from BaseNode** - Don't create custom base classes
2. **Use shared store for data** - All input/output data goes through shared store
3. **Use parameters for configuration** - Behavior settings use set_params()
4. **Fail fast with clear errors** - Validate inputs early and provide helpful messages
5. **Document the interface** - Clear docstring with Inputs/Outputs sections
6. **Keep nodes focused** - One clear purpose per node
7. **Handle errors gracefully** - Catch specific exceptions and re-raise with context

## Testing Pattern

For each node implementation:

```python
def test_read_file_node():
    # Create node
    node = ReadFileNode()

    # Create shared store
    shared = {"file_path": "test.txt"}

    # Create test file
    with open("test.txt", "w") as f:
        f.write("test content")

    # Execute node
    node._shared = shared  # PocketFlow sets this internally
    node.exec()

    # Verify output
    assert shared["content"] == "test content"

    # Test error cases
    shared = {"file_path": "nonexistent.txt"}
    node._shared = shared
    with pytest.raises(FileNotFoundError):
        node.exec()
```

This guide provides the essential patterns needed for implementing pflow's core functionality using PocketFlow's proven designs.
