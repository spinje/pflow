# Task 8 Project Context: Build Comprehensive Shell Pipe Integration

## Task Overview

**Task**: Build comprehensive shell pipe integration
**Priority**: High
**Dependencies**: Task 3 (Execute a Hardcoded 'Hello World' Workflow - DONE)
**Description**: Implement full Unix pipe support for stdin/stdout handling and shell integration

## Current State Analysis

### Existing CLI Implementation (src/pflow/cli/main.py)

The current CLI already has basic stdin detection:

```python
def get_input_source(file: str | None, workflow: tuple[str, ...]) -> tuple[str, str]:
    # ...
    elif not sys.stdin.isatty():
        # Read from stdin
        raw_input = sys.stdin.read().strip()
        if raw_input:  # Only use stdin if it has content
            # ...
            return raw_input, "stdin"
```

**Current Capabilities**:
- ✅ Basic stdin detection using `isatty()`
- ✅ Reading entire stdin content at once
- ✅ Signal handling for Ctrl+C (SIGINT)
- ❌ No streaming support for large data
- ❌ No population of shared['stdin']
- ❌ No stdout handling for pipe chaining
- ❌ Limited exit code handling
- ❌ No SIGPIPE handling for broken pipes

### Documentation Requirements

From `docs/features/shell-pipes.md`:

1. **Basic Usage**: Automatically populate `shared["stdin"]` when piped input detected
2. **Streaming Support**: Process large files in chunks without loading entirely into memory
3. **Exit Code Propagation**: Proper exit codes for shell scripting (0 success, non-zero failure)
4. **Signal Handling**: Graceful interruption with clean stops and partial progress saving
5. **stdout Output**: Enable workflows to output to stdout for further Unix processing

From `docs/architecture/architecture.md` section 5.1.4:
- Content automatically placed in `shared["stdin"]`
- First node can consume this data naturally or via IR mapping
- Piped content is hashed and included in execution traces

### Key Patterns from Simon Willison's llm CLI

From examining `llm-main/llm/cli.py`:

1. **stdin Detection Pattern**:
```python
if not sys.stdin.isatty():
    stdin_prompt = sys.stdin.read()
```

2. **Fragment Handling** (line 127):
```python
elif fragment == "-":
    resolved.append(Fragment(sys.stdin.read(), "-"))
```

3. **Attachment Handling** (line 195-196):
```python
if value == "-":
    content = sys.stdin.buffer.read()  # Binary mode for attachments
```

4. **Dual Input Handling** (line 543-552):
```python
# Combines stdin with command-line prompt
if stdin_prompt:
    bits = [stdin_prompt]
    if prompt:
        bits.append(prompt)
    prompt = " ".join(bits)
```

From `docs/implementation-details/simonw-llm-patterns/IMPLEMENTATION-GUIDE.md`:

Key implementation patterns:
- Signal handling for SIGINT and SIGPIPE
- Safe output with encoding error handling
- Non-blocking stdin detection using `select`
- Streaming support considerations

## Architecture Integration Points

### 1. Shared Store Integration

From `docs/core-concepts/shared-store.md`:
- Reserved key `stdin` for piped input
- Natural interfaces allow nodes to check `shared["stdin"]` as fallback
- Template variable resolution supports `$stdin`

### 2. CLI Runtime Integration

From `docs/features/cli-runtime.md`:
- Table shows pipe text scenario: `cat notes.txt | pflow llm --prompt="Summarize this"` → `{ "stdin": "<bytes>" }`
- Validation rule 5: `stdin` key reserved; nodes must handle it naturally

### 3. PocketFlow Framework Constraints

- Must work within pocketflow's Node lifecycle (prep/exec/post)
- Shell integration happens at CLI layer, not within nodes
- Shared store populated before flow execution begins

## Critical Design Decisions Needed

### 1. Streaming Architecture
- **Challenge**: How to handle large files without loading into memory
- **Options**:
  - Stream to temporary file, pass path in shared store
  - Implement chunked reading with generator pattern
  - Use memory-mapped files for large inputs

### 2. stdin Data Type
- **Challenge**: Binary vs text handling
- **Current**: CLI reads as text with `.read().strip()`
- **Need**: Support both text and binary data

### 3. Workflow Integration
- **Challenge**: How workflows consume stdin data
- **Current**: No automatic population of shared store
- **Need**: Populate `shared["stdin"]` before flow execution

### 4. Output Handling
- **Challenge**: Enabling stdout output for pipe chaining
- **Current**: Click.echo() for user messages
- **Need**: Structured output from shared store

## Implementation Scope

### Core Components to Build

1. **src/pflow/core/shell_integration.py**
   - Comprehensive Unix pipe support utilities
   - Streaming capabilities
   - Signal handling enhancements
   - Output formatting

2. **CLI Enhancement** (modify src/pflow/cli/main.py)
   - Integrate shell_integration module
   - Populate shared['stdin'] automatically
   - Handle stdout output from workflows
   - Proper exit code management

3. **Testing Requirements**
   - Test stdin detection and reading
   - Test streaming with large data
   - Test signal handling (SIGINT, SIGPIPE)
   - Test exit code propagation
   - Test binary data handling

## Key Documentation References

1. **Primary Reference**: `docs/features/shell-pipes.md`
2. **Architecture Context**: `docs/architecture/architecture.md` section 5.1.4
3. **Shared Store Pattern**: `docs/core-concepts/shared-store.md` (stdin handling)
4. **CLI Runtime**: `docs/features/cli-runtime.md` (stdin in shared store)
5. **Simon's Patterns**: `docs/implementation-details/simonw-llm-patterns/IMPLEMENTATION-GUIDE.md`

## Success Criteria

1. ✅ stdin automatically populates `shared["stdin"]` when detected
2. ✅ Large files can be processed without memory exhaustion
3. ✅ Proper exit codes (0 for success, non-zero for failure)
4. ✅ Ctrl+C handled gracefully with clean shutdown
5. ✅ Broken pipes handled without errors
6. ✅ Workflows can output to stdout for chaining
7. ✅ Both batch mode (fail fast) and interactive mode supported
8. ✅ Binary and text data handled appropriately

## Implementation Priority

1. **First**: Basic stdin→shared['stdin'] population
2. **Second**: Proper signal and exit code handling
3. **Third**: stdout output for chaining
4. **Fourth**: Streaming support for large files
5. **Fifth**: Interactive vs batch mode distinction

This comprehensive context provides the foundation for intelligent task decomposition based on deep domain understanding.
