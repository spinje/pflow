# PocketFlow Parameter Handling - Code Examples

## The Problem in Code

### What pflow Does (Compilation)
```python
# In compiler.py - _instantiate_nodes()
def _instantiate_nodes(ir_dict, registry):
    nodes = {}
    for node_data in ir_dict["nodes"]:
        node_id = node_data["id"]
        node_type = node_data["type"]

        # Create node instance
        node_class = import_node_class(node_type, registry)
        node_instance = node_class()

        # Set parameters from workflow JSON
        if node_data.get("params"):
            node_instance.set_params(node_data["params"])
            # At this point: node_instance.params = {"file_path": "input.txt"}

        nodes[node_id] = node_instance
    return nodes
```

### What PocketFlow Does (Execution)
```python
# In pocketflow/__init__.py
class Flow(BaseNode):
    def __init__(self, start=None):
        super().__init__()
        self.start_node = start
        # Note: self.params = {} by default

    def _run(self, shared):
        p = self.prep(shared)
        o = self._orch(shared)  # No params passed here!
        return self.post(shared, p, o)

    def _orch(self, shared, params=None):
        # params is None when called from _run()
        curr = copy.copy(self.start_node)
        p = (params or {**self.params})  # p = {} (empty flow params)
        last_action = None

        while curr:
            curr.set_params(p)  # THIS OVERWRITES! node.params = {}
            last_action = curr._run(shared)
            curr = copy.copy(self.get_next_node(curr, last_action))

        return last_action
```

### The Critical set_params() Method
```python
# In pocketflow/__init__.py
class BaseNode:
    def set_params(self, params):
        self.params = params  # REPLACES entire dict, doesn't merge!
```

## The Initial Solution (PreservingFlow)

```python
# flow_wrapper.py - First solution
from pocketflow import Flow
import copy

class PreservingFlow(Flow):
    """Flow that preserves node parameters set during compilation."""

    def _orch(self, shared, params=None):
        """Orchestrate without overwriting node params."""
        curr = copy.copy(self.start_node)
        last_action = None

        while curr:
            # Don't call set_params - preserve existing params
            last_action = curr._run(shared)
            curr = copy.copy(self.get_next_node(curr, last_action))

        return last_action
```

## The Final Solution (Modified PocketFlow)

```python
# Modified pocketflow/__init__.py
def _orch(self, shared, params=None):
    curr, p, last_action = copy.copy(self.start_node), (params or {**self.params}), None
    while curr:
        # Only override node params if explicitly passed (not for default empty flow params)
        # TODO: This is a temporary modification for pflow. When implementing BatchFlow support,
        # this will need to be revisited to ensure proper parameter inheritance.
        if params is not None:
            curr.set_params(p)
        last_action = curr._run(shared)
        curr = copy.copy(self.get_next_node(curr, last_action))
    return last_action
```

## How Nodes Use Parameters

### Example: ReadFileNode
```python
class ReadFileNode(Node):
    def prep(self, shared):
        # Check shared store first, then params as fallback
        file_path = shared.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path' in shared store or params")

        # Normalize the path
        file_path = os.path.expanduser(file_path)
        file_path = os.path.abspath(file_path)

        encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")
        return (file_path, encoding)
```

## BatchFlow - Why Parameter Overwriting is Needed

```python
# Example from pocketflow cookbook
class ProcessFilesBatch(BatchFlow):
    def prep(self, shared):
        # Return different parameters for each run
        return [
            {"filename": "doc1.txt", "output": "summary1.txt"},
            {"filename": "doc2.txt", "output": "summary2.txt"},
            {"filename": "doc3.txt", "output": "summary3.txt"}
        ]

# In BatchFlow._run()
def _run(self, shared):
    pr = self.prep(shared) or []
    for bp in pr:
        # Each iteration needs fresh parameters
        self._orch(shared, {**self.params, **bp})
    return self.post(shared, pr, None)
```

### Why Merge Would Break BatchFlow
```python
# If set_params used merge instead of replace:
def set_params(self, params):
    self.params.update(params)  # MERGE - would contaminate!

# Run 1: params = {"filename": "doc1.txt", "output": "summary1.txt"}
# Run 2: params = {"filename": "doc2.txt", "output": "summary2.txt"}
# But "output" from run 1 would still be there!
# Run 3: Would have accumulated params from all previous runs
```

## Test Case Demonstrating the Issue

```python
# Test workflow
workflow = {
    "ir_version": "0.1.0",
    "nodes": [
        {
            "id": "read",
            "type": "read-file",
            "params": {"file_path": "input.txt"}
        },
        {
            "id": "write",
            "type": "write-file",
            "params": {"file_path": "output.txt"}
        }
    ],
    "edges": [{"from": "read", "to": "write"}]
}

# What happens without the fix:
# 1. Compiler sets: read_node.params = {"file_path": "input.txt"}
# 2. Flow runs with: flow.params = {} (default)
# 3. _orch overwrites: read_node.params = {}
# 4. Node fails: "Missing required 'file_path'"

# With the fix:
# 1. Compiler sets: read_node.params = {"file_path": "input.txt"}
# 2. Flow runs with: flow.params = {} (default)
# 3. _orch sees params=None, skips set_params()
# 4. Node succeeds with original params intact
```
