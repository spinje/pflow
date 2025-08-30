# Shell Integration Context for Platform Nodes

This document provides essential context about pflow's shell integration that is relevant for implementing platform nodes (Task 13). All information is based on the implemented shell integration from Task 8.

## Reserved Shared Store Keys for stdin

The shell integration reserves specific keys in the shared store for piped input. These keys are populated automatically when data is piped to pflow.

### Three Types of stdin Data

Based on the content and size, stdin data is stored in one of three keys (src/pflow/core/shell_integration.py):

1. **`shared["stdin"]`** - Text data under memory limit
   - Type: `str`
   - Used when: stdin contains valid UTF-8 text under 10MB (default)
   - Populated by: `_inject_stdin_data()` at src/pflow/cli/main.py:207

2. **`shared["stdin_binary"]`** - Binary data under memory limit
   - Type: `bytes`
   - Used when: stdin contains null bytes or invalid UTF-8
   - Populated by: `_inject_stdin_object()` at src/pflow/cli/main.py:191
   - Detection: Checks for `b"\x00"` in first 8KB (line 181 in shell_integration.py)

3. **`shared["stdin_path"]`** - Path to temporary file for large data
   - Type: `str` (file path)
   - Used when: stdin exceeds `PFLOW_STDIN_MEMORY_LIMIT` (default 10MB)
   - Populated by: `_inject_stdin_object()` at src/pflow/cli/main.py:195
   - Cleanup: Handled in `_cleanup_temp_files()` at src/pflow/cli/main.py:234

### StdinData Class Structure

```python
@dataclass
class StdinData:  # src/pflow/core/shell_integration.py:29
    text_data: str | None = None
    binary_data: bytes | None = None
    temp_path: str | None = None

    @property
    def is_text(self) -> bool
    @property
    def is_binary(self) -> bool
    @property
    def is_temp_file(self) -> bool
```

## Output Key Conventions

The shell integration includes automatic output detection that checks specific keys in priority order.

### Auto-Detection Order

When no `--output-key` is specified, the system checks these keys in order (src/pflow/cli/main.py:228):

1. **`response`** - Typically used by LLM nodes
2. **`output`** - Generic output key
3. **`result`** - Processing results
4. **`text`** - Plain text content

The first matching key with a value is output to stdout.

### Output Behavior

The `safe_output()` function (src/pflow/cli/main.py:32) handles different data types:

- **String values**: Output directly to stdout
- **Bytes values**: Skipped with warning to stderr ("cli: Skipping binary output")
- **Other types**: Converted to string via `str()`
- **BrokenPipeError**: Exits cleanly with `os._exit(0)`

## Integration Points in the CLI

### Stdin Injection

Stdin data is injected into the shared store before workflow execution:

```python
# src/pflow/cli/main.py:269
_inject_stdin_data(shared_storage, stdin_data, verbose)

# Then workflow executes at line 272:
result = flow.run(shared_storage)
```

### Output Handling

After workflow execution, output is handled at:

```python
# src/pflow/cli/main.py:287
output_produced = _handle_workflow_output(shared_storage, output_key)
```

## Example: How File Nodes Handle stdin

The read-file node demonstrates a pattern where nodes check shared store first, then params:

```python
# src/pflow/nodes/file/read_file.py:41
file_path = shared.get("file_path") or self.params.get("file_path")
```

This allows nodes to work with both explicit parameters and shared store values.

## Shell Pipes Documentation

The feature is documented in `architecture/features/shell-pipes.md`. Key points:

- stdin content is placed in `shared["stdin"]` (line 46)
- Nodes can check `shared["stdin"]` as fallback for their primary input key (line 47)
- The feature enables Unix-style command composition (line 15)

## Environment Variables

- **`PFLOW_STDIN_MEMORY_LIMIT`** - Controls threshold for temp file usage (default: 10485760 bytes)
  - Checked at src/pflow/core/shell_integration.py:262

## File References

- **Shell integration utilities**: `src/pflow/core/shell_integration.py`
- **CLI integration**: `src/pflow/cli/main.py`
  - Stdin injection: lines 200-212, 269
  - Output handling: lines 214-231, 287
  - Temp file cleanup: lines 234-243
- **Documentation**: `architecture/features/shell-pipes.md`
- **Example node**: `src/pflow/nodes/file/read_file.py`

## Signal Handling

The CLI registers signal handlers that may be relevant for long-running operations:

- **SIGINT** (Ctrl+C): Handled at src/pflow/cli/main.py:415, exits with code 130
- **SIGPIPE**: Handled at src/pflow/cli/main.py:418 (Unix only)

These ensure clean exit when pipes are broken or users interrupt execution.
