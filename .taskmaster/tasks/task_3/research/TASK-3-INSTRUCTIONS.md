# Task 3 Implementation Instructions

## Overview
You are implementing Task 3: "Execute a Hardcoded 'Hello World' Workflow". This is a simple integration task that brings together the existing components to execute a workflow from a JSON file.

## Pre-Implementation Setup

### 1. Populate the Registry (REQUIRED)
Before you can test your implementation, you MUST populate the node registry:

```bash
python scripts/populate_registry.py
```

**Important Notes:**
- This is a TEMPORARY solution until Task 10 implements proper CLI commands
- The script scans `src/pflow/nodes/` and creates `~/.pflow/registry.json`
- You only need to run this ONCE (unless you add new nodes)
- DO NOT implement auto-population in Task 3 - just show an error message

### 2. Create Test Files
Create these files for testing:

**input.txt**:
```
Hello
World
```

**hello_workflow.json**:
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

## Implementation Steps

### 1. Modify `src/pflow/cli/main.py`

Add these imports at the top:
```python
import json
from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow, CompilationError
from pflow.core import validate_ir, ValidationError
```

### 2. Add Workflow Execution Logic

In the `main()` function, after the existing input handling, add:

```python
# Only process if we have file input
if file and ctx.obj["input_source"] == "file":
    try:
        # Parse JSON
        ir_data = json.loads(ctx.obj["raw_input"])

        # Load registry (with helpful error if missing)
        registry = Registry()
        if not registry.exists():
            click.echo("cli: Error - Node registry not found.", err=True)
            click.echo("cli: Run 'python scripts/populate_registry.py' to populate the registry.", err=True)
            click.echo("cli: Note: This is temporary until 'pflow registry' commands are implemented.", err=True)
            ctx.exit(1)

        # Validate IR
        validate_ir(ir_data)

        # Compile to Flow
        flow = compile_ir_to_flow(ir_data, registry)

        # Execute with empty shared storage
        shared_storage = {}
        result = flow.run(shared_storage)

        # Simple success message
        click.echo("Workflow executed successfully")

    except json.JSONDecodeError as e:
        click.echo(f"cli: Invalid JSON in workflow file - {e}", err=True)
        ctx.exit(1)

    except ValidationError as e:
        click.echo(f"cli: Invalid workflow - {e.message}", err=True)
        if hasattr(e, 'path') and e.path:
            click.echo(f"cli: Error at: {e.path}", err=True)
        if hasattr(e, 'suggestion') and e.suggestion:
            click.echo(f"cli: Suggestion: {e.suggestion}", err=True)
        ctx.exit(1)

    except CompilationError as e:
        click.echo(f"cli: Compilation failed - {e}", err=True)
        ctx.exit(1)

    except Exception as e:
        click.echo(f"cli: Unexpected error - {e}", err=True)
        ctx.exit(1)
```

### 3. Write Tests

Create/update `tests/test_e2e_workflow.py`:

```python
import json
from pathlib import Path
from click.testing import CliRunner
from pflow.cli.main import main
from pflow.registry import Registry, scan_for_nodes


def test_hello_workflow(tmp_path):
    """Test executing a simple read-file => write-file workflow."""
    runner = CliRunner()

    # Ensure registry exists (in real usage, user runs populate script)
    registry = Registry()
    if not registry.exists():
        # For tests only - populate registry
        scan_results = scan_for_nodes([Path("src/pflow/nodes")])
        registry.update_from_scanner(scan_results)

    with runner.isolated_filesystem():
        # Create input file
        with open("input.txt", "w") as f:
            f.write("Hello\nWorld")

        # Create workflow file
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
                {"id": "write", "type": "write-file", "params": {"file_path": "output.txt"}}
            ],
            "edges": [{"from": "read", "to": "write"}]
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI
        result = runner.invoke(main, ['--file', 'workflow.json'])

        # Verify success
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output

        # Verify output file
        assert Path("output.txt").exists()
        content = Path("output.txt").read_text()
        # Remember: ReadFileNode adds line numbers!
        assert "1: Hello" in content
        assert "2: World" in content


def test_missing_registry_error():
    """Test helpful error when registry is missing."""
    # This test would require mocking Registry.exists() to return False
    pass
```

## Testing Your Implementation

1. **First Time Setup**:
   ```bash
   # Install package
   pip install -e .

   # Populate registry
   python scripts/populate_registry.py
   ```

2. **Manual Test**:
   ```bash
   # Create test files (input.txt and hello_workflow.json)
   # Run the workflow
   pflow --file hello_workflow.json

   # Check output.txt - should contain:
   # 1: Hello
   # 2: World
   ```

3. **Run Tests**:
   ```bash
   pytest tests/test_e2e_workflow.py -v
   ```

## Important Reminders

### DO:
- ✅ Check if registry exists and show helpful error
- ✅ Use the existing error patterns (prefix with "cli:")
- ✅ Handle all exceptions gracefully
- ✅ Test with real files (nodes do actual I/O)
- ✅ Remember ReadFileNode adds line numbers

### DON'T:
- ❌ Auto-populate the registry in Task 3
- ❌ Implement natural language processing (that's Task 17)
- ❌ Add a `run` subcommand (use direct `--file` option)
- ❌ Modify the registry or node implementations
- ❌ Add features beyond basic workflow execution

## Expected Behavior

When running:
```bash
pflow --file hello_workflow.json
```

**Success Case**:
1. Loads and validates the JSON workflow
2. Compiles it to a PocketFlow Flow object
3. Executes the flow:
   - ReadFileNode reads "input.txt"
   - Adds line numbers (1:, 2:, etc.)
   - Stores content in shared["content"]
   - WriteFileNode reads shared["content"]
   - Writes to "output.txt"
4. Prints: "Workflow executed successfully"

**Error Cases**:
- Missing registry: Clear error with instruction to run populate script
- Invalid JSON: Shows JSON parse error
- Invalid IR: Shows validation error with path/suggestion
- Compilation error: Shows what went wrong
- File not found: Node execution error

## Definition of Done

- [ ] CLI accepts `--file` option and loads workflow JSON
- [ ] Registry existence is checked with helpful error message
- [ ] IR is validated before compilation
- [ ] Flow compiles and executes successfully
- [ ] All errors show clear, actionable messages
- [ ] Tests pass including edge cases
- [ ] Line numbering behavior is tested
- [ ] No features beyond basic execution are added

## Questions?

If anything is unclear:
1. Check the comprehensive report in this folder
2. Look at existing implementations in src/pflow/
3. Follow the patterns from Tasks 1, 2, 4, 5, 6, and 11

Good luck! This should be a straightforward integration task.
