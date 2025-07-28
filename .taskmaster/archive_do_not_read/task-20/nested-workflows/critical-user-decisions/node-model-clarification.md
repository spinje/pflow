# Clarification: What is pflow's Node Model?

## The Current Node Model

When I say "pflow's node model expects Python classes with standard lifecycle methods," here's what I mean:

### 1. How Nodes are Discovered

The registry scanner looks for Python classes:
```python
# In scanner.py - it scans Python files and looks for:
for name, obj in inspect.getmembers(module, inspect.isclass):
    if issubclass(obj, BaseNode) and obj is not BaseNode:
        # This is a node!
```

### 2. What Gets Stored in Registry

```json
{
  "read-file": {
    "module": "pflow.nodes.file.read_file",    // Python module path
    "class_name": "ReadFileNode",               // Python class name
    "file_path": "/path/to/read_file.py"       // Python file
  }
}
```

The registry stores **Python module paths**, not workflow JSON files.

### 3. How Nodes are Instantiated

```python
# In compiler.py:
# 1. Look up the node type in registry
node_metadata = registry.get("read-file")

# 2. Import the Python module
module = importlib.import_module("pflow.nodes.file.read_file")

# 3. Get the class
node_class = getattr(module, "ReadFileNode")

# 4. Instantiate it
node = node_class()  # Must be a Python class with __init__
```

### 4. The Expected Lifecycle

Every node must have these methods (from BaseNode):
```python
class MyNode(BaseNode):
    def prep(self, shared):
        # Prepare for execution
        pass

    def exec(self, prep_res):
        # Do the actual work
        pass

    def post(self, shared, prep_res, exec_res):
        # Write results to shared storage
        pass
```

## The Problem with WorkflowExecutor

WorkflowExecutor needs to:
1. Load a JSON file (not import a Python module)
2. Parse workflow IR (not instantiate a class)
3. Compile the IR to a Flow object
4. Execute that Flow

But the registry/compiler expects:
1. A Python module path it can import
2. A class it can instantiate
3. Standard prep/exec/post methods

## What This Means

### Current System Flow:
```
Registry: "read-file" → "pflow.nodes.file.read_file.ReadFileNode"
Compiler: import module → get class → instantiate → node.set_params()
Runtime: node.prep() → node.exec() → node.post()
```

### What WorkflowExecutor Needs:
```
Registry: "my-workflow" → "~/.pflow/workflows/my-workflow.json" (???)
Compiler: load JSON → parse IR → compile to Flow → ???
Runtime: How does this fit prep/exec/post model?
```

## The Mismatch Illustrated

### Regular Node:
```python
# It's a Python class in a .py file
class ReadFileNode(BaseNode):
    def exec(self, prep_res):
        with open(self.file_path) as f:
            return f.read()
```

### WorkflowExecutor "Node":
```python
class WorkflowExecutor(BaseNode):
    def exec(self, prep_res):
        # Load a JSON file (not normal for nodes!)
        workflow_json = load_json(self.workflow_ref)

        # Compile it (nodes don't usually compile things!)
        sub_flow = compile_ir_to_flow(workflow_json)

        # Execute it (nodes don't usually execute other flows!)
        return sub_flow.run(isolated_storage)
```

## Why This is a Problem

1. **Registry Can't Handle It**: Registry expects Python modules, not JSON files
2. **Discovery Won't Work**: Scanner looks for Python classes, not workflow files
3. **Different Resource Type**: We're mixing Python code (nodes) with data files (workflows)

## The Real Issue

The current architecture assumes:
- **Nodes = Python classes** that implement computation
- **Workflows = JSON files** that describe node composition

We're trying to make:
- **A node that loads and executes workflows**

This breaks the clean separation between:
- Code (nodes)
- Configuration (workflows)

## Possible Solutions

### 1. Keep Them Separate
Don't try to make workflows into nodes. Handle workflow composition at a different layer.

### 2. Create a Special Node Type
Explicitly support nodes that load external resources (but this is a big change).

### 3. Use a Different Pattern
Maybe workflow composition isn't a node concern at all - it's an orchestration concern.

## Conclusion

When I said "pflow's node model expects Python classes," I meant:
- The entire discovery, registry, and compilation pipeline assumes nodes are Python classes
- WorkflowExecutor breaks this assumption by needing to load JSON files
- This creates a fundamental mismatch with the current architecture

The system isn't designed for nodes that load and execute other workflows - it's designed for nodes that perform discrete computations.
