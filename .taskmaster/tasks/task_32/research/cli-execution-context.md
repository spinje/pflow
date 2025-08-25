# CLI Execution Context for Tracing Implementation

This document provides essential implementation context from the CLI and shell integration work that is relevant for implementing the execution tracing system (Task 23).

## Workflow Execution Flow

### 1. Main Execution Point
The workflow execution happens in `src/pflow/cli/main.py` at line 295:
```python
result = flow.run(shared_storage)
```

This is the critical hook point where tracing would capture:
- Pre-execution shared storage state
- Post-execution shared storage state
- Execution result (success/error action)
- Timing information

### 2. Shared Storage Initialization
Shared storage is created as an empty dictionary at line 289:
```python
shared_storage: dict[str, Any] = {}
```

Before execution, stdin data may be injected via `_inject_stdin_data()` at line 292, which can populate:
- `shared["stdin"]` - text data
- `shared["stdin_binary"]` - binary data as bytes
- `shared["stdin_path"]` - path to temp file for large data

### 3. Verbose Mode Pattern
The verbose flag is retrieved from Click context at line 283:
```python
verbose = ctx.obj.get("verbose", False)
```

Current verbose output includes:
- Line 286: Node count at start of execution
- Line 208-209: stdin injection details (e.g., "Injected stdin data (45 bytes)")
- Line 304: "Workflow execution completed" message
- Line 242: Temp file cleanup messages

## Output Handling Integration

### 1. Output Detection Logic
After workflow execution, the system checks for output at line 305 (calls `_handle_workflow_output()`):
- Checks keys in priority order: `response`, `output`, `result`, `text`
- The `_handle_workflow_output()` function (line 214-231) returns boolean indicating if output was produced
- This information would be valuable for tracing to show which key was selected for output

### 2. Output Key Context
The output key can be explicitly specified via `--output-key` option, stored in:
```python
ctx.obj["output_key"]  # Set at line 443
```

## Error Handling Patterns

### 1. Node Error Detection
Error detection happens at line 298-301:
```python
if result and isinstance(result, str) and result.startswith("error"):
    click.echo("cli: Workflow execution failed - Node returned error action", err=True)
```

This shows that nodes return error actions as strings starting with "error".

### 2. Exception Handling
General exceptions during execution are caught at line 315-318:
```python
except Exception as e:
    click.echo(f"cli: Workflow execution failed - {e}", err=True)
    click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)
    ctx.exit(1)
```

## CLI Context Object

The Click context object (`ctx.obj`) contains:
- `raw_input` - Original workflow input (line 439)
- `input_source` - Where input came from: "file", "stdin", or "args" (line 440)
- `stdin_data` - Any stdin data collected (line 441)
- `verbose` - Verbose flag (line 442)
- `output_key` - Specified output key (line 443)

## Flow Compilation Context

Before execution, the workflow goes through:
1. Registry loading (line 269-274)
2. IR validation via `validate_ir(ir_data)` (line 277)
3. Compilation via `compile_ir_to_flow(ir_data, registry)` (line 280)

The `flow` object returned is what gets executed with `flow.run(shared_storage)`.

## Relevant File References

### Core Files
- `src/pflow/cli/main.py` - Main CLI implementation
- `src/pflow/core/shell_integration.py` - Contains `StdinData` class definition
- `src/pflow/runtime/compiler.py` - Contains `compile_ir_to_flow()` function

### Key Functions
- `execute_json_workflow()` (line 247-322) - Main workflow execution function
- `_handle_workflow_output()` (line 214-231) - Output detection and handling
- `_inject_stdin_data()` (line 200-211) - stdin injection logic

## Integration Considerations for Tracing

1. **Execution Hook Point**: Line 295 is where `flow.run()` is called - tracing would need to wrap or hook into this

2. **Shared Store Mutations**: The shared storage dictionary is passed by reference, so nodes mutate it directly during execution

3. **Output Awareness**: Tracing should capture which output key was selected (if any) from the `_handle_workflow_output()` return value

4. **Error Context**: Both error actions and exceptions need to be captured with their full context

5. **Verbose Integration**: The existing verbose mode pattern could be extended for trace output

6. **Stdin Context**: Special keys (`stdin`, `stdin_binary`, `stdin_path`) should be noted in traces as they represent external input

## Current Output Prefixes

The CLI uses consistent prefixes for output:
- `cli:` - CLI-level messages
- `cli: Error -` - Error messages
- `cli: Warning -` - Warning messages

This pattern could be extended for trace output.

## Exit Codes

Current exit codes used:
- 0 - Success
- 1 - General error
- 130 - SIGINT (Ctrl+C)

The tracing system should capture the exit code that would be used.
