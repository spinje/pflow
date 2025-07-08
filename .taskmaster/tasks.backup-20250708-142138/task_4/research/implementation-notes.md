# Task 4 Implementation Notes

This document contains additional critical information for implementing the IR-to-PocketFlow compiler that wasn't covered in the design decisions document.

## Critical Context

### 1. **Task Dependencies and Testing Challenge**

**IMPORTANT**: Task 4 depends on Tasks 5 & 6 (complete), but Task 11 (Simple Platform Nodes) is NOT complete yet. This means:
- The test nodes in `src/pflow/nodes/test_node.py` exist (created by Task 5)
- But the actual platform nodes (read-file, write-file, etc.) don't exist yet
- Your compiler tests should use the test nodes for now
- Task 3 (Hello World workflow) depends on both Task 4 AND Task 11

### 2. **Import Path Considerations**

The registry stores module paths like `pflow.nodes.file.read_file`. For these to work:
- The package must be installed in development mode (`pip install -e .` or `uv pip install -e .`)
- Otherwise, Python won't be able to import `pflow.nodes.*` modules
- Test this early in your implementation to avoid confusion

### 3. **Common Pitfalls from Integration Guide**

From `docs/architecture/pflow-pocketflow-integration-guide.md`, avoid these traps:
- **DON'T** try to implement execution logic - PocketFlow's Flow class does this
- **DON'T** create wrapper classes around PocketFlow components
- **DON'T** overthink the shared store - it's just a dict
- **DON'T** build a complex template engine - simple string substitution (Task 19)

### 4. **Testing Strategy**

Given the constraints, here's the recommended testing approach:

```python
# 1. Use test nodes from src/pflow/nodes/test_node.py
test_ir = {
    "nodes": [
        {"id": "n1", "type": "test-node", "params": {"value": "hello"}},
        {"id": "n2", "type": "test-node-retry", "params": {"max_attempts": 3}}
    ],
    "edges": [{"from": "n1", "to": "n2"}],
    "start_node": "n1"
}

# 2. Mock the registry for testing
mock_registry = {
    "test-node": {
        "module": "pflow.nodes.test_node",
        "class_name": "TestNode"
    },
    "test-node-retry": {
        "module": "pflow.nodes.test_node",
        "class_name": "TestNodeRetry"
    }
}

# 3. Test error cases with invalid data
invalid_registry = {
    "missing-node": {
        "module": "pflow.nodes.does_not_exist",
        "class_name": "MissingNode"
    }
}
```

### 5. **Template Variables - What NOT to Implement**

The compiler should NOT resolve template variables. Just pass them through:
- ✅ Pass `{"prompt": "Analyze $content"}` directly to `node.set_params()`
- ❌ Don't try to replace `$content` with actual values
- That's the job of Task 19 (template resolver) and the nodes themselves

### 6. **Security Note**

From Task 5's scanner implementation:
- `importlib.import_module()` executes module code on import
- This is a security risk if importing untrusted code
- For MVP, we trust all nodes in the pflow package
- Consider adding a comment about this security implication

### 7. **Minimal Error Messages That Help**

When errors occur, include:
- Node ID from the IR (helps locate the problem in the workflow)
- Node type (what they were trying to use)
- The actual error (ImportError, AttributeError, etc.)
- Example: `CompilationError: Node 'n1' (type: github-get-issue) - Cannot import module 'pflow.nodes.github.github_get_issue': No module named 'pflow.nodes.github'`

### 8. **What Success Looks Like**

A successful implementation will:
1. Take JSON IR + registry metadata → produce executable pocketflow.Flow
2. Handle missing nodes with clear errors
3. Pass all parameters (including templates) to nodes unchanged
4. Connect nodes properly with >> and - operators
5. Return a Flow object that can be executed with `flow.run(shared)`

### 9. **Integration with Task 3**

Task 3 will use your compiler like this:
```python
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry.registry import Registry

# Load registry and IR
registry = Registry.load()
ir_json = load_json("hello_workflow.json")

# Compile to Flow
flow = compile_ir_to_flow(ir_json, registry.nodes)

# Execute
shared = {}
result = flow.run(shared)
```

### 10. **Performance Is Not a Concern**

For the MVP:
- Don't optimize import caching
- Don't worry about compilation speed
- Focus on correctness and clear error messages
- The entire compilation will typically take <100ms

## Summary for Implementation

1. Start by setting up the module structure: `src/pflow/runtime/compiler.py`
2. Write tests FIRST using the test nodes
3. Implement the basic happy path
4. Add error handling with helpful messages
5. Don't implement features that belong to other tasks (templates, execution, etc.)
6. Keep it simple - the whole module should be <200 lines

Remember: You're building a translator from JSON to PocketFlow objects. Nothing more, nothing less.
