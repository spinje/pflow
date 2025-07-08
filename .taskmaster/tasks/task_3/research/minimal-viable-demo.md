# Minimal Viable Demo - Hello World Workflow

## Purpose

Task 3 is the first end-to-end validation that proves the core execution pipeline works. It's intentionally simple to isolate core functionality from complex features.

## What Constitutes Success

A successful hello world workflow demonstrates:

1. **IR Loading**: Can read and parse JSON workflow files
2. **Validation**: IR schema validation catches malformed workflows
3. **Registry Integration**: Can look up node metadata
4. **Dynamic Import**: Can import node classes from metadata
5. **Flow Construction**: Can build pocketflow.Flow from IR
6. **Execution**: Flow runs successfully with shared store
7. **Data Flow**: Nodes communicate through shared store

## The Minimal Workflow

### hello_workflow.json
```json
{
  "ir_version": "1.0",
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {
        "file_path": "input.txt"
      }
    },
    {
      "id": "write",
      "type": "write-file",
      "params": {
        "file_path": "output.txt"
      }
    }
  ],
  "edges": [
    {
      "from": "read",
      "to": "write",
      "action": "default"
    }
  ],
  "start_node": "read"
}
```

## Expected Behavior

1. **Setup**: Create `input.txt` with content "Hello, pflow!"
2. **Execute**: `pflow --file hello_workflow.json`
3. **Result**: `output.txt` created with same content

## What We're Testing

### 1. Basic Flow
```
CLI receives --file flag
  → Reads JSON from file
  → Validates against IR schema
  → Loads registry
  → Compiles IR to Flow
  → Executes Flow
  → Success message
```

### 2. Shared Store Communication
```python
# read-file node does:
shared["content"] = file_content

# write-file node does:
content = shared["content"]
write_to_file(content)
```

### 3. Error Handling
- Missing input file → Clear error
- Invalid JSON → Schema validation error
- Missing nodes → Registry error
- Execution failure → Node error with context

## Implementation Checklist

### CLI Integration
```python
# In main.py
if file:
    # Read workflow from file
    workflow_json = read_workflow_from_file(file)

    # Try to parse as JSON
    try:
        ir_data = json.loads(workflow_json)
    except json.JSONDecodeError:
        # Not JSON - will be natural language later
        pass
```

### Validation
```python
# Validate IR structure
try:
    validate_ir(ir_data)
except ValidationError as e:
    # Clear error with path to problem
    click.echo(f"Invalid workflow: {e}")
    sys.exit(1)
```

### Registry Loading
```python
# Load registry with helpful error
registry = Registry()
if not registry.registry_path.exists():
    click.echo("Error: Node registry not found")
    click.echo("Run 'python scripts/populate_registry.py'")
    sys.exit(1)
```

### Compilation
```python
# Compile IR to Flow
try:
    flow = compile_ir_to_flow(ir_data, registry)
except CompilationError as e:
    click.echo(f"Compilation failed: {e}")
    sys.exit(1)
```

### Execution
```python
# Execute with empty shared store
shared_storage = {}
flow.run(shared_storage)

# Success!
click.echo("Workflow executed successfully")
```

## Common Issues to Avoid

### 1. Import Paths
```python
# WRONG: Importing from wrong base
from nodes.file.read_file import ReadFileNode

# RIGHT: Full package path
from pflow.nodes.file.read_file import ReadFileNode
```

### 2. Shared Store Keys
```python
# WRONG: Inconsistent keys
# read-file writes to shared["file_content"]
# write-file reads from shared["content"]

# RIGHT: Consistent natural keys
# Both use shared["content"]
```

### 3. Error Handling
```python
# WRONG: Swallowing errors
try:
    flow.run(shared)
except:
    pass  # Bad!

# RIGHT: Proper error propagation
try:
    flow.run(shared)
except Exception as e:
    click.echo(f"Workflow failed: {e}", err=True)
    sys.exit(1)
```

## Success Criteria

The demo is successful when:

1. ✅ `pflow --file hello_workflow.json` executes without errors
2. ✅ `output.txt` contains the content from `input.txt`
3. ✅ Appropriate errors shown for failure cases
4. ✅ Tests pass in `test_e2e_workflow.py`

## Testing Strategy

### Happy Path Test
```python
def test_hello_workflow_success(tmp_path, cli_runner):
    # Create input file
    input_file = tmp_path / "input.txt"
    input_file.write_text("Hello, pflow!")

    # Create workflow
    workflow = create_hello_workflow(input_file, tmp_path / "output.txt")
    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(json.dumps(workflow))

    # Execute
    result = cli_runner.invoke(main, ["--file", str(workflow_file)])

    # Verify
    assert result.exit_code == 0
    assert (tmp_path / "output.txt").read_text() == "Hello, pflow!"
```

### Error Cases
- Missing input file
- Invalid workflow JSON
- Non-existent node type
- Missing required parameters

## Why This Matters

This simple demo proves that:
1. The architecture is sound
2. All components integrate correctly
3. The shared store pattern works
4. Error handling is robust

Once this works, adding complex nodes and the planner is just extending a working system.

## Next Steps

After hello world works:
1. Add more complex workflows
2. Test action-based routing ("error" actions)
3. Add parameter validation
4. Test with multiple node types

## Remember

Keep it simple! This is about proving the foundation works, not showcasing features. Complexity comes later.
