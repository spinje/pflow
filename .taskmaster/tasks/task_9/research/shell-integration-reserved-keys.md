# Shell Integration Reserved Keys - Context for Collision Detection

This document provides essential context about reserved shared store keys established by the shell integration implementation (Task 8). These keys have special meaning and must be considered when implementing collision detection and proxy mapping.

## Reserved Input Keys

The shell integration reserves three keys for stdin data injection:

### 1. `stdin` - Text Data
- **Usage**: Contains text data piped from stdin
- **Injection Location**: `src/pflow/cli/main.py:188` and `src/pflow/cli/main.py:208`
- **Example Code**:
  ```python
  # Line 206-209
  if isinstance(stdin_data, str):
      # Backward compatibility: string data
      shared_storage["stdin"] = stdin_data
  ```
- **Note**: This key is used for both legacy string stdin and new text StdinData

### 2. `stdin_binary` - Binary Data
- **Usage**: Contains binary data (bytes) piped from stdin
- **Injection Location**: `src/pflow/cli/main.py:192`
- **Example Code**:
  ```python
  # Line 190-193
  elif stdin_data.is_binary and stdin_data.binary_data is not None:
      shared_storage["stdin_binary"] = stdin_data.binary_data
  ```
- **Detection**: Binary is detected by presence of null bytes (`\x00`) in first 8KB sample

### 3. `stdin_path` - Large File Path
- **Usage**: Contains path to temporary file for stdin data exceeding memory limit
- **Injection Location**: `src/pflow/cli/main.py:196`
- **Example Code**:
  ```python
  # Line 194-197
  elif stdin_data.is_temp_file and stdin_data.temp_path is not None:
      shared_storage["stdin_path"] = stdin_data.temp_path
  ```
- **Threshold**: Default 10MB, configurable via `PFLOW_STDIN_MEMORY_LIMIT` environment variable

## Special Output Keys

The CLI implements automatic output detection that checks keys in a specific priority order:

### Output Detection Priority
- **Location**: `src/pflow/cli/main.py:228`
- **Priority Order**: `["response", "output", "result", "text"]`
- **Implementation**:
  ```python
  # Line 227-230
  # Auto-detect output from common keys
  for key in ["response", "output", "result", "text"]:
      if key in shared_storage:
          return safe_output(shared_storage[key])
  ```

### Key Conventions
These keys have conventional meanings based on node types:
- `response` - Typically used by LLM nodes for AI-generated responses
- `output` - Commonly used by shell/exec nodes for command output
- `result` - Used by processing nodes for computation results
- `text` - Used by content/file nodes for text data

## Critical Implementation Details

### Empty String vs None Distinction
The shell integration explicitly distinguishes between empty string and None:

1. **In shell_integration.py**:
   ```python
   # Line 89-91 in read_stdin()
   # Treat empty stdin as no input per spec
   if content == "":
       return None
   ```

2. **In CLI stdin handling**:
   ```python
   # Line 83 in main.py
   if stdin_content is None:  # Only when actually None, not empty string
       enhanced_stdin = read_stdin_enhanced()
   ```

This distinction is critical because:
- Empty stdin (`""`) is explicitly converted to `None`
- This prevents empty values from being injected into the shared store
- Collision detection must understand this behavior

### Key Injection Timing
All stdin keys are injected **before** workflow execution:
- **Function**: `_inject_stdin_data()` at `src/pflow/cli/main.py:201`
- **Called at**: Line 269 in `execute_json_workflow()`
- **Before**: `flow.run(shared_storage)` at line 272

## Implications for Collision Detection

When implementing collision detection, be aware that:

1. **These keys may already exist** in the shared store when nodes execute
2. **Only one stdin key** will be populated per execution (never multiple)
3. **Output keys** have special significance for CLI piping functionality
4. **Empty values** are not injected (converted to None)

## Related Documentation

- Shell pipes feature specification: `architecture/features/shell-pipes.md`
- Shared store concepts: `architecture/core-concepts/shared-store.md`
- StdinData class definition: `src/pflow/core/shell_integration.py:104-115`

## Code References

- Main stdin injection: `src/pflow/cli/main.py:201-211` (_inject_stdin_data function)
- Output detection: `src/pflow/cli/main.py:214-231` (_handle_workflow_output function)
- Shell integration utilities: `src/pflow/core/shell_integration.py`
- Safe output implementation: `src/pflow/cli/main.py:32-55`
