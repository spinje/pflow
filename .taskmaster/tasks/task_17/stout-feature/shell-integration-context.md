# Shell Integration Context for Natural Language Planner

This document provides essential context from the shell integration implementation (Task 8) that is critical for implementing the Natural Language Planner System (Task 17).

## Reserved Shared Store Keys for stdin

The shell integration reserves specific keys in the shared store for stdin data. The planner must be aware of these to avoid conflicts and to understand how piped data flows into workflows.

### Three Types of stdin Keys

Based on the `StdinData` class definition in `src/pflow/core/shell_integration.py` (lines 28-39):

```python
@dataclass
class StdinData:
    """Container for different types of stdin data.

    Only one of the fields will be populated based on the data type:
    - text_data: For text content under memory limit
    - binary_data: For binary content under memory limit
    - temp_path: For any content over memory limit
    """

    text_data: str | None = None
    binary_data: bytes | None = None
    temp_path: str | None = None
```

### stdin Injection Logic

The injection happens in `src/pflow/cli/main.py` at `_inject_stdin_data()` (lines 200-211):

1. **`shared["stdin"]`** - Populated for text data (lines 187, 207):
   - Used when stdin contains UTF-8 text under 10MB
   - This is the most common case for piped text data
   - Empty stdin (`""`) is treated as `None` per line 90 in shell_integration.py

2. **`shared["stdin_binary"]`** - Populated for binary data (line 191):
   - Used when stdin contains null bytes (binary detection)
   - Stores raw bytes object

3. **`shared["stdin_path"]`** - Populated for large files (line 195):
   - Used when stdin exceeds 10MB (configurable via `PFLOW_STDIN_MEMORY_LIMIT`)
   - Contains path to temporary file
   - Temp files are cleaned up after execution (lines 234-246)

### Key Implementation Detail

The stdin injection happens **before** workflow execution at line 292 in `execute_json_workflow()`:
```python
# Inject stdin data if present
_inject_stdin_data(shared_storage, stdin_data, verbose)

try:
    result = flow.run(shared_storage)  # Line 295
```

## Output Key Detection Priority

The planner should understand how pflow determines which shared store key to output when no explicit `--output-key` is specified.

### Priority Order

From `_handle_workflow_output()` in `src/pflow/cli/main.py` (lines 227-230):

```python
# Auto-detect output from common keys
for key in ["response", "output", "result", "text"]:
    if key in shared_storage:
        return safe_output(shared_storage[key])
```

The detection order is:
1. **`response`** - Highest priority, typically used by LLM nodes
2. **`output`** - Common for shell/exec nodes
3. **`result`** - Used by processing/transform nodes
4. **`text`** - Used by file/content nodes

### Why This Order Matters

This priority order aligns with typical workflow patterns:
- LLM-based workflows often want to output the LLM response
- Command execution workflows want the command output
- Data processing workflows want the processing result
- File manipulation workflows want the file content

The planner should generate workflows that use these conventional keys when the user's intent includes outputting results.

## CLI Workflow Execution Flow

Understanding where and how workflows execute is critical for the planner.

### Execution Point

Workflow execution happens at line 295 in `src/pflow/cli/main.py`:
```python
result = flow.run(shared_storage)
```

### Shared Storage Initialization

The shared storage is initialized as an empty dict at line 289:
```python
# Execute with shared storage
shared_storage: dict[str, Any] = {}
```

### Compilation Before Execution

The planner's JSON IR must be compiled before execution (line 280):
```python
# Compile to Flow
flow = compile_ir_to_flow(ir_data, registry)
```

### Error Handling

The execution checks for error results (lines 298-301):
```python
if result and isinstance(result, str) and result.startswith("error"):
    click.echo("cli: Workflow execution failed - Node returned error action", err=True)
    ctx.exit(1)
```

## CLI Context Object Structure

The Click context object (`ctx.obj`) carries all parameters through the execution flow.

### Context Keys

From `src/pflow/cli/main.py` (lines 456-460):

```python
# Store in context
ctx.obj["raw_input"] = raw_input      # The workflow content (JSON or natural language)
ctx.obj["input_source"] = source       # Where input came from: "file", "stdin", or "args"
ctx.obj["stdin_data"] = stdin_data     # Piped data (str or StdinData object)
ctx.obj["verbose"] = verbose           # Verbose output flag
ctx.obj["output_key"] = output_key     # User-specified output key (--output-key option)
```

### Context Flow

1. Context is populated in `main()` function
2. Passed to `process_file_workflow()`
3. Then to `execute_json_workflow()` where output_key is extracted (line 345):
   ```python
   execute_json_workflow(ctx, ir_data, stdin_data, ctx.obj.get("output_key"))
   ```

## Integration Points for the Planner

### 1. Workflow Generation with Output Awareness

The planner should consider output requirements when generating workflows:
- If user intent includes "show", "display", "output", etc., ensure the workflow puts results in a conventional output key
- For LLM-based workflows, use `shared["response"]`
- For command execution, use `shared["output"]`

### 2. stdin Data Availability

When the planner generates a workflow, it should know:
- `shared["stdin"]` will be pre-populated if data was piped
- Nodes can check for stdin as fallback: `shared.get("data") or shared.get("stdin")`
- The planner can reference stdin in template variables: `$stdin`

### 3. Output Key Configuration

The planner could potentially:
- Detect when users want specific output (e.g., "show me just the error count")
- Generate metadata suggesting an output key for the workflow
- This would integrate with named workflow execution in Task 22

### 4. Processing Entry Point

From the TODO comment at lines 466-469 in `main()`:
```python
else:
    # Temporary output for non-file inputs
    click.echo(f"Collected workflow from {source}: {raw_input}")
    _display_stdin_data(stdin_data)
```

This is where natural language input will be processed by the planner.

## Binary Data Considerations

The planner should be aware that:
- Binary data is detected by checking for null bytes (see `_is_binary()` in shell_integration.py)
- Binary output is skipped with a warning (see `safe_output()` lines 38-41 in main.py)
- Large data automatically streams to temp files

## Related Documentation

- **Planner Specification**: `architecture/features/planner.md`
- **Shared Store Pattern**: `architecture/core-concepts/shared-store.md`
- **Shell Pipes Feature**: `architecture/features/shell-pipes.md`
- **CLI Runtime**: `architecture/features/cli-runtime.md`
- **Template Variables**: Section 6.3 in `architecture/core-concepts/shared-store.md`

## Summary for Planner Implementation

The Natural Language Planner must:

1. **Respect reserved keys**: Never use `stdin`, `stdin_binary`, or `stdin_path` for other purposes
2. **Use conventional output keys**: Follow the priority pattern for predictable output behavior
3. **Understand execution flow**: Generated JSON IR → Compilation → Execution with shared storage
4. **Leverage stdin availability**: Know that piped data is available in `shared["stdin"]` before node execution
5. **Consider output requirements**: Generate workflows that put results in appropriate keys based on user intent

This context ensures the planner generates workflows that integrate seamlessly with pflow's shell integration features.
