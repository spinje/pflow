# Task 3 Implementation Handoff Memo

## Quick Start Guide for Task 3 Implementation

### What Task 3 Needs to Do
Execute a hardcoded workflow from a JSON file using the CLI:
```bash
pflow --file hello_workflow.json
```

### Prerequisites Checklist
- [x] Task 1: Package and CLI setup - COMPLETE
- [x] Task 2: CLI argument collection - COMPLETE
- [x] Task 4: IR-to-Flow compiler - COMPLETE
- [x] Task 5: Node discovery scanner - COMPLETE
- [x] Task 6: JSON IR schema - COMPLETE
- [x] Task 11: File I/O nodes - COMPLETE

### Critical Implementation Notes

#### 1. Registry Must Be Populated First

**TEMPORARY SOLUTION for MVP**:
```bash
# Run this ONCE before testing Task 3:
python scripts/populate_registry.py
```

This script is temporary and will be replaced by proper CLI commands in Task 10 (`pflow registry scan`).

**In your Task 3 implementation**, check for registry and show helpful error:
```python
registry = Registry()
if not registry.exists():
    click.echo("cli: Error - Node registry not found.", err=True)
    click.echo("cli: Run 'python scripts/populate_registry.py' to populate the registry.", err=True)
    click.echo("cli: Note: This is temporary until 'pflow registry' commands are implemented.", err=True)
    ctx.exit(1)
```

#### 2. CLI Pattern (No Subcommand!)
```python
# In src/pflow/cli/main.py - extend existing main() function
if file:
    # File input takes precedence
    try:
        with open(file, 'r') as f:
            ir_data = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"cli: Invalid JSON in file: {e}", err=True)
        ctx.exit(1)
```

#### 3. Line Numbers Will Be Added
ReadFileNode adds line numbers. If `input.txt` contains:
```
Hello
World
```

Then `shared["content"]` will be:
```
1: Hello
2: World
```

This WILL appear in `output.txt`!

### Sample hello_workflow.json
```json
{
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
  "edges": [
    {"from": "read", "to": "write"}
  ]
}
```

### Implementation Steps

1. **Extend CLI main() function**:
   ```python
   from pflow.runtime import compile_ir_to_flow, CompilationError
   from pflow.core import validate_ir, ValidationError
   from pflow.registry import Registry

   # After existing file loading...
   if ctx.obj["input_source"] == "file":
       # We have IR data in ctx.obj["raw_input"]
       # Parse, validate, compile, execute
   ```

2. **Error Handling Pattern**:
   ```python
   try:
       # Validate IR first
       validate_ir(ir_data)

       # Compile to Flow
       flow = compile_ir_to_flow(ir_data, registry)

       # Execute
       shared_storage = {}
       result = flow.run(shared_storage)

       # Check result (nodes return "default" or "error")

   except ValidationError as e:
       click.echo(f"cli: Invalid workflow - {e.message} at {e.path}", err=True)
       if e.suggestion:
           click.echo(f"cli: {e.suggestion}", err=True)
       ctx.exit(1)

   except CompilationError as e:
       click.echo(f"cli: Compilation failed - {e}", err=True)
       ctx.exit(1)
   ```

3. **Test Implementation**:
   ```python
   def test_hello_workflow(tmp_path):
       runner = CliRunner()

       # Create input file
       input_file = tmp_path / "input.txt"
       input_file.write_text("Hello\nWorld")

       # Create workflow file
       workflow_file = tmp_path / "workflow.json"
       workflow_file.write_text(json.dumps({...}))

       # Run CLI
       result = runner.invoke(main, ['--file', str(workflow_file)])

       # Verify
       assert result.exit_code == 0
       output_file = tmp_path / "output.txt"
       assert output_file.exists()
       assert "1: Hello\n2: World" in output_file.read_text()
   ```

### Common Pitfalls to Avoid

1. **Don't forget the registry** - Run `python scripts/populate_registry.py` first!
2. **Use kebab-case node names** - "read-file" not "ReadFileNode"
3. **Remember line numbers** - Output won't match input exactly
4. **Check node actions** - Handle both "default" and "error"
5. **File paths in tests** - Use tmp_path fixture or isolated_filesystem()
6. **Registry error handling** - Show helpful message, don't auto-populate in Task 3

### Minimal Working Implementation

```python
# In main() after loading file content
if file and ctx.obj["input_source"] == "file":
    try:
        # Parse JSON
        ir_data = json.loads(ctx.obj["raw_input"])

        # Validate
        validate_ir(ir_data)

        # Get registry
        registry = Registry()
        if not registry.exists():
            # Quick hack for MVP - scan on first run
            from pathlib import Path
            scan_results = scan_for_nodes([Path("src/pflow/nodes")])
            registry.update_from_scanner(scan_results)

        # Compile
        flow = compile_ir_to_flow(ir_data, registry)

        # Execute
        shared = {}
        result = flow.run(shared)

        # Simple success message
        click.echo("Workflow executed successfully")

    except Exception as e:
        click.echo(f"cli: Error - {e}", err=True)
        ctx.exit(1)
```

### Definition of Done

- [ ] CLI accepts `--file` option and loads JSON
- [ ] Registry is populated (automatically or with helper)
- [ ] IR is validated before compilation
- [ ] Flow compiles and executes successfully
- [ ] Errors are handled gracefully with clear messages
- [ ] Tests verify end-to-end execution
- [ ] Line numbering behavior is documented/tested

### Next Steps After Task 3

Once basic execution works, future tasks will add:
- Natural language planning (not needed for Task 3!)
- More nodes beyond file I/O
- Better output formatting
- Execution tracing

But for now, just make `pflow --file hello_workflow.json` work!
