# Knowledge Synthesis for 8.5

## Relevant Patterns from Previous Tasks

### Shell Integration Foundation (8.1)
- **Pattern**: Pure utility functions in shell_integration.py
- **Where used**: `src/pflow/core/shell_integration.py`
- **Why relevant**: Already have detect_stdin(), read_stdin(), populate_shared_store() - foundation to build on for output

### Dual-Mode stdin Handling (8.2)
- **Pattern**: CLI integration with stdin injection
- **Where used**: `src/pflow/cli/main.py` lines 55-62, 136-161
- **Why relevant**: Shows where to add stdout output logic (after workflow execution)

### Binary and Large File Handling (8.4)
- **Pattern**: StdinData class with three types (text, binary, path)
- **Where used**: Enhanced stdin reading with `read_stdin_enhanced()`
- **Why relevant**: Output logic needs to handle these different data types appropriately

### Signal Handling Pattern (8.1 research)
- **Pattern**: SIGINT handler already exists at line 25-28 in main.py
- **Where used**: `handle_sigint()` function
- **Why relevant**: Already uses exit code 130, just need to add SIGPIPE

### Exit Code Pattern (8.2)
- **Pattern**: Error detection through flow return value
- **Where used**: Lines 161-164 in main.py check for "error" prefix
- **Why relevant**: Current exit code logic to enhance/replace

## Known Pitfalls to Avoid

### Empty String vs None (8.1)
- **Pitfall**: Not distinguishing between `""` and `None`
- **Where failed**: Initial stdin reading
- **How to avoid**: Always use explicit `== ""` or `is None` checks

### Backward Compatibility (8.4)
- **Pitfall**: Breaking existing APIs
- **Where failed**: Initial attempt to modify read_stdin()
- **How to avoid**: Add new functionality alongside old, don't replace

### Platform-Specific Code (Research)
- **Pitfall**: Using Unix-only signals on Windows
- **Where failed**: SIGPIPE doesn't exist on Windows
- **How to avoid**: Always check `hasattr(signal, 'SIGPIPE')`

### Type Checking with Unions (8.4)
- **Pitfall**: Assuming type without checking
- **Where failed**: Called len() on StdinData object
- **How to avoid**: Use isinstance() before type-specific operations

## Established Conventions

### Shared Store Keys (All subtasks)
- **Convention**: Reserved keys for stdin data
- **Where decided**: Task 8 project context
- **Must follow**:
  - `shared["stdin"]` - text data
  - `shared["stdin_binary"]` - binary data
  - `shared["stdin_path"]` - temp file path

### Click Context Usage (8.2)
- **Convention**: Access shared store via ctx.obj
- **Where decided**: Task 2 CLI patterns
- **Must follow**: Use Click's context for passing data

### Testing Approach (All subtasks)
- **Convention**: Test-as-you-go with comprehensive coverage
- **Where decided**: CLAUDE.md and all previous tasks
- **Must follow**: Create tests alongside implementation

### Temp File Cleanup (8.4)
- **Convention**: Use finally blocks for cleanup
- **Where decided**: 8.4 implementation
- **Must follow**: Always clean up resources in finally blocks

## Codebase Evolution Context

### Current State After 8.4
- **What changed**: stdin now supports binary and large files
- **When**: Just completed in 8.4
- **Impact**: Output logic must handle all three stdin types

### CLI Structure Evolution
- **What changed**: Progressive enhancement of run command
- **When**: Through tasks 8.1-8.4
- **Impact**: Clear injection points for new features

### Testing Infrastructure
- **What changed**: Comprehensive test suite for shell integration
- **When**: Built up through subtasks
- **Impact**: Can follow established test patterns

## Key Insights for 8.5

1. **Output Detection Logic**: Need to check multiple keys in order (response, output, result, text)
2. **Binary Output Handling**: Must check if output value is bytes vs string
3. **Exit Code Sources**: Three options - flow return, shared["exit_code"], or flow.exit_code
4. **Signal Registration**: Add handlers early in main() function
5. **BrokenPipeError**: Different from SIGPIPE, need to handle both
6. **Platform Safety**: Windows compatibility for signal handling
7. **Output Only When Piped**: Check stdout.isatty() before outputting
