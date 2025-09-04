# Task 55 Review: Fix Output Control for Interactive vs Non-Interactive Execution

## Executive Summary
Implemented comprehensive output control system that detects execution context (terminal vs piped) and routes output accordingly, restoring Unix composability while adding progress indicators. The implementation touched 29 files, added 5,907 lines, and spawned multiple sub-fixes for related issues discovered during development.

## Implementation Overview

### What Was Built
Created `OutputController` class for centralized output management with TTY detection, progress callbacks via shared storage, and CLI flag override. Implementation expanded beyond original spec to include:
- MCP server output suppression (Task 55b)
- Trace output control (Task 55c)
- Progress indicator fix for non-traced workflows (Task 55d)
- User-friendly error message system
- Shell node output namespace fix
- Auto-output selection improvement (last vs first)

### Implementation Approach
Centralized all output decisions in `OutputController` with clear precedence: `-p` flag > JSON mode > TTY detection. Used shared storage for callback passing to avoid modifying PocketFlow core. Key insight: both stdin AND stdout must be TTY for interactive mode to prevent hanging in partial pipes.

## Files Modified/Created

### Core Changes
- `src/pflow/core/output_controller.py` - NEW: Central output control class with TTY detection
- `src/pflow/cli/main.py` - Modified: Added -p flag, OutputController integration, helper functions
- `src/pflow/runtime/instrumented_wrapper.py` - Modified: Added progress callback invocations
- `src/pflow/planning/debug.py` - Modified: PlannerProgress respects is_interactive flag
- `src/pflow/runtime/compiler.py` - Modified: Always apply InstrumentedNodeWrapper (critical fix)
- `src/pflow/nodes/mcp/node.py` - Modified: MCP output control via subprocess.DEVNULL
- `src/pflow/core/user_errors.py` - NEW: User-friendly error message system

### Test Files
- `tests/test_core/test_output_controller.py` - NEW: 29 comprehensive tests for OutputController
- `tests/test_nodes/test_mcp/test_mcp_output_control.py` - NEW: MCP output control tests
- `tests/test_runtime/test_compiler_integration.py` - Modified: Handle InstrumentedNodeWrapper
- `tests/test_runtime/test_flow_construction.py` - Modified: Handle wrapped nodes
- `tests/test_runtime/test_workflow_executor/test_integration.py` - Modified: Test adjustments

## Integration Points & Dependencies

### Incoming Dependencies
- CLI commands -> OutputController (for progress display decisions)
- All nodes -> OutputController callbacks (via shared storage)
- PlannerProgress -> OutputController.is_interactive()
- Error handlers -> UserFriendlyError classes

### Outgoing Dependencies
- OutputController -> sys.stdin/stdout (TTY detection)
- Progress callbacks -> click.echo(err=True) (stderr output)
- MCP nodes -> subprocess.DEVNULL (when not verbose)
- InstrumentedNodeWrapper -> shared["__progress_callback__"] (callback invocation)

### Shared Store Keys
- `__progress_callback__` - Function for node execution progress (callable or None)
- `__verbose__` - Boolean flag for verbose output mode
- `_pflow_depth` - Integer for nested workflow indentation (pre-existing, leveraged)
- `__output_controller__` - OutputController instance (considered but not implemented)

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **Dual TTY check** -> Both stdin AND stdout must be TTY -> Prevents hanging when output piped to jq
2. **Callbacks via shared storage** -> Pass via `__progress_callback__` key -> Avoids modifying PocketFlow core
3. **Always apply InstrumentedNodeWrapper** -> Changed from conditional to always -> Ensures progress works without --trace
4. **subprocess.DEVNULL for MCP** -> Use real file descriptor -> io.StringIO() lacks fileno() method
5. **Last output for auto-detection** -> Changed from first to last -> Matches Unix pipeline philosophy

### Technical Debt Incurred
- Multiple OutputController instantiations (could be centralized further)
- Progress callback exception handling repeated in multiple places
- Test mocking patterns for TTY detection are verbose

## Testing Implementation

### Test Strategy Applied
Created comprehensive test coverage for all 22 specification requirements plus edge cases. Used mocking for TTY detection, tested all flag combinations, verified Windows None handling.

### Critical Test Cases
- `test_stdin_piped_stdout_tty_non_interactive` - Validates partial pipe detection
- `test_none_stdin_forces_non_interactive` - Windows edge case handling
- `test_progress_callback_exception_handled` - Ensures callbacks never break execution
- `test_complete_workflow_execution_flow` - End-to-end progress display

## Unexpected Discoveries

### Gotchas Encountered
1. **Registry.list_nodes() doesn't exist** - Was causing command timeouts, used registry.nodes.keys() instead
2. **InstrumentedNodeWrapper conditional application** - Progress only worked with --trace flag initially
3. **Namespace wrapping hides outputs** - Shell node outputs nested under node_id, not at top level
4. **MCP SDK uses anyio.open_process** - Not subprocess.Popen, so monkey-patching doesn't work
5. **io.StringIO() has no fileno()** - Can't be used for subprocess stderr redirection

### Edge Cases Found
- Windows GUI apps where sys.stdin is None
- Partial pipes (stdin TTY but stdout piped)
- Empty workflows (0 nodes) still need header
- Progress callbacks raising exceptions
- Test environment always non-TTY (affects manual testing)

## Patterns Established

### Reusable Patterns
```python
# Output controller helper functions pattern
def _get_output_controller(ctx: click.Context) -> OutputController:
    """Get or create OutputController from context."""
    if "output_controller" not in ctx.obj:
        ctx.obj["output_controller"] = OutputController(...)
    return ctx.obj["output_controller"]

# Safe callback invocation pattern
callback = shared.get("__progress_callback__")
if callable(callback):
    try:
        callback(node_id, event_type, duration, depth)
    except Exception:
        pass  # Never let callbacks break execution

# TTY detection with None handling
if sys.stdin is None or sys.stdout is None:
    return False
return sys.stdin.isatty() and sys.stdout.isatty()
```

### Anti-Patterns to Avoid
- Don't use io.StringIO() for subprocess stderr (no fileno())
- Don't check only one stream for TTY (causes hanging)
- Don't let callback errors propagate (breaks execution)
- Don't assume sys.stdin/stdout exist (Windows edge case)

## Breaking Changes

### API/Interface Changes
- New CLI flag: `-p/--print` for non-interactive mode
- PlannerProgress constructor now accepts `is_interactive` parameter
- _prepare_shared_storage() accepts optional `output_controller` parameter

### Behavioral Changes
- Progress messages suppressed when piped (was always shown)
- Shell node output now correctly displayed (was hidden by namespace)
- Auto-output uses last node's output instead of first
- MCP server messages suppressed unless verbose

## Future Considerations

### Extension Points
- OutputController could be extended for different output formats
- Progress callback system could support custom formatters
- Helper functions could be moved to a separate module

### Scalability Concerns
- Multiple OutputController instantiations (minor performance impact)
- Callback invocation overhead on every node (negligible for current scale)

## AI Agent Guidance

### Quick Start for Related Tasks
1. **Read first**: `src/pflow/core/output_controller.py` for the pattern
2. **Check integration**: `src/pflow/cli/main.py` lines 1767-1793 for flag setup
3. **Understand callbacks**: `src/pflow/runtime/instrumented_wrapper.py` lines 246-277
4. **Review tests**: `tests/test_core/test_output_controller.py` for all scenarios

**Key pattern to follow**: Always use OutputController for ANY output decisions. Never check TTY directly.

### Common Pitfalls
1. **DON'T check stdin.isatty() alone** - Must check both stdin AND stdout
2. **DON'T forget Windows None check** - sys.stdin can be None in GUI apps
3. **DON'T use in-memory buffers for subprocess stderr** - Need real file descriptors
4. **DON'T let progress callbacks raise exceptions** - Always wrap in try/except
5. **DON'T modify PocketFlow core** - Use shared storage for communication

### Test-First Recommendations
When modifying output control:
1. Run `pytest tests/test_core/test_output_controller.py` first
2. Test with actual pipes: `echo "test" | pflow "echo hello" | cat`
3. Verify -p flag: `pflow -p "test"` should show no progress
4. Check Windows compatibility with None stdin mock

---

*Generated from implementation context of Task 55*