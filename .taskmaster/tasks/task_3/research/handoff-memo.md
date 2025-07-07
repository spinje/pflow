# Task 3 Handoff: Critical Knowledge Transfer

**⚠️ STOP: Read this fully before implementing. When done, confirm you're ready to begin.**

## 🎯 Core Integration Points You MUST Know

### 1. The CLI --file Option Already Exists!
From Task 2.2, the CLI already has `--file` support:
```python
# src/pflow/cli/main.py - around line 50-60
@click.option('--file', '-f', type=click.Path(exists=True),
              help='Read workflow from file')
```
Don't create a new command - use the existing `run` command with `--file`.

### 2. Registry Scanner Quirks (CRITICAL)
The registry scanner from Task 5 has these gotchas:
- It looks for `pocketflow.BaseNode` inheritance, **NOT** `pocketflow.Node`
- Location: `src/pflow/registry/scanner.py`
- Registry file: `~/.pflow/registry.json`
- **YOU MUST RUN THE SCANNER** before Task 3 or the compiler won't find nodes:
```bash
python -m pflow.registry.scanner  # Or however it's invoked
```

### 3. File Nodes Use pocketflow.Node (Not BaseNode!)
Despite what the registry scanner looks for, the actual file nodes inherit from `pocketflow.Node`:
```python
# src/pflow/nodes/file/read_file.py
from pocketflow import Node  # NOT BaseNode!

class ReadFileNode(Node):  # This gives retry logic
    name = 'read-file'  # Explicit name attribute
```

This mismatch means you might need to:
- Check how the registry scanner actually works in practice
- The scanner might be checking for both Node and BaseNode
- Test with actual nodes before assuming it's broken

### 4. Compiler Integration Pattern
The compiler from Task 4 is at `src/pflow/runtime/compiler.py`:
```python
from pflow.runtime.compiler import compile_ir_to_flow

# It expects:
flow = compile_ir_to_flow(ir_json, registry_dict)
```

The registry dict format from Task 5:
```json
{
  "read-file": {
    "module": "pflow.nodes.file.read_file",
    "class_name": "ReadFileNode",
    "docstring": "...",
    "file_path": "/path/to/file.py"
  }
}
```

### 5. Shared Store Initialization
PocketFlow expects you to pass a shared store dict to flow.run():
```python
shared_store = {}  # Start empty
result = flow.run(shared_store)  # Modified in-place
```

### 6. The "Hello World" Workflow IR Structure
Based on Task 6's schema at `src/pflow/core/ir_schema.py`:
```json
{
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
  "edges": [
    {
      "source": "read",  // OR "from" - compiler accepts both!
      "target": "write", // OR "to" - compiler accepts both!
      "action": "default"
    }
  ]
}
```

### 7. Edge Field Name Confusion
Task 4's compiler was updated to accept BOTH formats:
- Schema says: `"source"/"target"`
- Examples use: `"from"/"to"`
- **Compiler accepts both** - see Task 4.3 implementation

### 8. File Node Parameter Sources
File nodes check shared store FIRST, then params:
```python
# Pattern in all file nodes:
file_path = shared.get("file_path") or self.params.get("file_path")
```

For the hello world workflow:
- read-file gets `file_path` from params
- write-file gets `file_path` from params AND `content` from shared store (put there by read-file)

### 9. Testing Gotchas
- Use `click.testing.CliRunner` for CLI testing
- Create actual temp files for the workflow to read/write
- The shared store is modified in-place during execution
- File nodes return tuples: `(message, success_bool)`

### 10. What NOT to Create
- ❌ Don't create new nodes - use existing ones from Task 11
- ❌ Don't modify the CLI - use existing --file option
- ❌ Don't create a new registry - use the existing one
- ❌ Don't implement template variable resolution - pass them through

## 🔗 Essential Files to Read

1. **CLI with --file**: `src/pflow/cli/main.py` (Task 2 implementation)
2. **IR Schema**: `src/pflow/core/ir_schema.py` (Task 6)
3. **Compiler**: `src/pflow/runtime/compiler.py` (Task 4)
4. **Registry**: `src/pflow/registry/scanner.py` (Task 5)
5. **File Nodes**: `src/pflow/nodes/file/read_file.py`, `write_file.py` (Task 11)
6. **PocketFlow basics**: `pocketflow/__init__.py` (100-line framework)

## 📚 Documentation References

- **Integration patterns**: `docs/architecture/pflow-pocketflow-integration-guide.md`
- **CLI runtime**: `docs/features/cli-runtime.md`
- **Schemas**: `docs/core-concepts/schemas.md`

## ⚡ Quick Implementation Path

1. Create `examples/hello_workflow.json` with the IR structure above
2. Update CLI to wire --file option to the compiler:
   ```python
   if file:
       # Load JSON
       # Load registry
       # Call compile_ir_to_flow
       # Run the flow
   ```
3. Create `tests/test_e2e_workflow.py` using CliRunner
4. Handle errors gracefully (missing files, invalid IR, etc.)

## 🚨 Final Warnings

- The registry MUST be populated before running (run the scanner!)
- Check if file nodes are actually discovered by the scanner given the Node/BaseNode mismatch
- The compiler expects registry metadata, NOT class references
- Template variables like `$var` should pass through unchanged

**Remember: This is the FIRST end-to-end test. If it doesn't work, nothing else will.**

---

**IMPORTANT**: Do not start implementing until you've read this memo and relevant files. Reply with "Ready to implement Task 3" when you're prepared.
