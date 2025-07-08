# Task 8 Decomposition Plan: Build Comprehensive Shell Pipe Integration

## Task Overview

Build comprehensive shell pipe integration that enables dual-mode stdin handling (workflow definitions OR data) and full Unix pipe support. This is a high-priority task that builds on existing CLI infrastructure to make pflow a first-class citizen in Unix pipelines.

## Decomposition Pattern: Progressive Enhancement

The task follows a progressive enhancement pattern where we build from core utilities to full integration:
1. Foundation → Core stdin handling utilities
2. Integration → CLI modifications and shared store population
3. Enhancement → Advanced features (streaming, binary, output)
4. Polish → Signal handling and comprehensive testing

## Detailed Subtask Descriptions

### Subtask 1: Create Core Shell Integration Module
**Title**: Create shell_integration.py with dual-mode stdin handling
**Description**: Build the foundational shell integration module that provides core utilities for stdin detection, reading, and mode determination.
**Implementation**:
- Create `src/pflow/core/shell_integration.py`
- Implement `detect_stdin()` using existing pattern: `not sys.stdin.isatty()`
- Implement `read_stdin()` with proper encoding handling (UTF-8 default)
- Implement `determine_stdin_mode(content)` that detects if stdin contains workflow JSON (with "ir_version") or data
- Handle empty stdin gracefully (return None, not empty string)
- Add `populate_shared_store(shared, content)` that adds stdin data to shared["stdin"]
**Dependencies**: None
**Test Requirements**: Unit tests for all functions, mock stdin for testing, handle edge cases (empty, very large, encoding errors)

### Subtask 2: Modify CLI Validation for Dual-Mode Support
**Title**: Update CLI to allow stdin data with file/args workflows
**Description**: Modify the existing CLI validation logic to enable the dual-mode stdin behavior where stdin can be data while workflow comes from file or args.
**Implementation**:
- Modify `get_input_source()` in `src/pflow/cli/main.py`
- Update validation at lines 52-55 to allow stdin when `--file` is provided
- Implement logic: if `--file` provided → stdin is data; if no `--file` → stdin could be workflow
- Store stdin data in click context for later injection
- Preserve backward compatibility for stdin-as-workflow mode
**Dependencies**: Subtask 1 (need shell_integration module)
**Test Requirements**: Test both modes work correctly, test validation logic changes, ensure backward compatibility

### Subtask 3: Implement Shared Store Injection
**Title**: Inject stdin data into shared storage before workflow execution
**Description**: Integrate stdin data population at the correct point in the workflow execution pipeline.
**Implementation**:
- Modify workflow execution around line 89 in main.py
- Import and use shell_integration module
- If stdin data exists in context and is determined to be data (not workflow):
  - Call `populate_shared_store(shared_storage, stdin_data)`
- Ensure injection happens BEFORE `flow.run(shared_storage)`
- Add logging for debugging when stdin is populated
**Dependencies**: Subtasks 1 and 2
**Test Requirements**: Integration tests verifying stdin appears in shared store, test with real workflows

### Subtask 4: Add Binary Data and Large File Support
**Title**: Implement binary detection and streaming for large inputs
**Description**: Enhance stdin handling to support binary data and efficiently handle large files using temporary files.
**Implementation**:
- Add `detect_binary_content(sample)` to detect binary vs text
- Implement `read_stdin_with_limit(max_size=10_000_000)` for size safety
- For inputs >10MB, write to temporary file and store path in `shared["stdin_path"]`
- Auto-detect binary and store in `shared["stdin_binary"]` as bytes
- Use `sys.stdin.buffer` for binary reading
- Implement proper cleanup of temporary files
**Dependencies**: Subtask 1
**Test Requirements**: Test binary detection, large file handling, temporary file cleanup

### Subtask 5: Implement stdout Output for Pipe Chaining
**Title**: Add configurable stdout output from shared store
**Description**: Enable workflows to output results to stdout for Unix pipe chaining.
**Implementation**:
- Add `--output-key` option to CLI (default: auto-detect)
- Implement smart key detection: check for "response", "output", "result", "text" in order
- Add `safe_output(text)` function handling encoding errors and broken pipes
- After workflow execution, output the selected key's value to stdout
- Only output when stdout is not a TTY (piped) or explicitly requested
- Handle binary output appropriately
**Dependencies**: Subtasks 1-3
**Test Requirements**: Test output key selection, pipe chaining, encoding safety

### Subtask 6: Add Comprehensive Signal and Exit Code Handling
**Title**: Implement proper signal handling and exit codes
**Description**: Add Unix-compliant signal handling and exit code propagation for shell script compatibility.
**Implementation**:
- Enhance existing SIGINT handler to exit with code 130
- Add SIGPIPE handler for broken pipes (if platform supports)
- Create `ExitCodes` class with standard codes (0, 1, 2, 130, etc.)
- Ensure all error paths use appropriate exit codes
- Handle broken pipe errors gracefully with `os._exit(0)`
- Add exit code propagation from workflow execution results
**Dependencies**: Subtask 1
**Test Requirements**: Test signal handling, exit codes, broken pipe scenarios

### Subtask 7: Create Comprehensive Test Suite
**Title**: Build complete test coverage for shell integration
**Description**: Create thorough test suite covering all shell integration features with both unit and integration tests.
**Implementation**:
- Create `tests/test_shell_integration.py` with pytest
- Unit tests: Mock stdin with monkeypatch and io.StringIO
- Integration tests: Use subprocess for real shell behavior
- Test scenarios: dual-mode detection, large files, binary data, signals, exit codes
- Test with real Unix commands: `echo "data" | pflow --file workflow.json`
- Platform-specific tests for Windows vs Unix differences
- Performance tests for large data handling
**Dependencies**: All previous subtasks
**Test Requirements**: >95% coverage of shell_integration module, all user scenarios tested

## Key Patterns to Follow

### From Similar Tasks:
- **Task 2**: Use Click context (ctx.obj) for passing data between components
- **Task 3**: Test with both CliRunner (unit) and subprocess (integration)
- **Task 11**: Follow established shared store conventions

### From Research:
- **Simon's llm**: Use `sys.stdin.buffer.read()` for binary data
- **Unix Philosophy**: Silence is golden, proper exit codes, no prompts in pipe mode
- **Critical Decisions**: Temp files for >10MB, auto-detect binary/text, batch mode default

## Essential Documentation

### Primary References:
- `docs/features/shell-pipes.md` - Complete specification
- `docs/architecture/architecture.md` section 5.1.4 - stdin in shared store
- `docs/core-concepts/shared-store.md` - Reserved keys and conventions

### Research Files:
- `.taskmaster/tasks/task_8/research/external-patterns.md` - Implementation patterns
- `.taskmaster/tasks/task_8/research/stdin-handling-patterns.md` - stdin approaches
- `.taskmaster/tasks/task_8/research/unix-pipe-philosophy.md` - Unix integration

## Special Implementation Notes

1. **Backward Compatibility**: Ensure existing `echo '{workflow}' | pflow` continues to work
2. **Injection Point**: Shared storage injection must happen at line 89 in main.py
3. **Validation Modification**: Lines 52-55 need careful modification to allow new behavior
4. **Testing Challenge**: CliRunner simulates non-TTY even when empty - handle in tests
5. **Platform Differences**: SIGPIPE doesn't exist on Windows - use hasattr check

## Test-Driven Development

Each subtask should follow test-as-you-go strategy:
1. Write tests for the functionality BEFORE implementation
2. Implement to make tests pass
3. Refactor while keeping tests green
4. Document any discovered edge cases

## Time Estimates

- Subtask 1: 3-4 hours (foundation)
- Subtask 2: 2-3 hours (validation logic)
- Subtask 3: 2 hours (integration)
- Subtask 4: 3-4 hours (binary/streaming)
- Subtask 5: 2-3 hours (output handling)
- Subtask 6: 2 hours (signals/exit codes)
- Subtask 7: 4-5 hours (comprehensive testing)

Total: ~20-25 hours (3-4 days of focused work)
