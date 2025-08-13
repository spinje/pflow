# Task 27: Planner Debugging Implementation Summary

## What Was Implemented

### Core Debugging Infrastructure

1. **DebugWrapper Class** (`src/pflow/planning/debug.py`)
   - Wraps PocketFlow nodes to capture debugging data
   - Preserves all node functionality through attribute delegation
   - Critical implementation of `__copy__` method (Flow uses copy.copy() on nodes)
   - Intercepts LLM calls at the prompt level for recording

2. **TraceCollector Class** (`src/pflow/planning/debug.py`)
   - Accumulates execution trace data throughout planner run
   - Records node execution times, LLM calls, and errors
   - Detects Path A vs Path B based on executed nodes
   - Saves JSON trace files to `~/.pflow/debug/`

3. **PlannerProgress Class** (`src/pflow/planning/debug.py`)
   - Displays real-time progress indicators in terminal
   - Maps node names to user-friendly emojis and descriptions
   - Outputs to stderr to avoid interfering with stdout piping

4. **DebugContext Class** (`src/pflow/planning/debug.py`)
   - Encapsulates TraceCollector and PlannerProgress
   - Provides clean dependency injection pattern
   - Created by CLI and passed to flow creation

5. **Utility Functions** (`src/pflow/planning/debug_utils.py`)
   - `save_trace_to_file()` - JSON file saving with error handling
   - `format_progress_message()` - Progress message formatting
   - `create_llm_interceptor()` - Helper for LLM call interception

### Integration Points

1. **Flow Integration** (`src/pflow/planning/flow.py`)
   - Modified `create_planner_flow()` to accept optional DebugContext
   - Wraps all 9 planner nodes when DebugContext provided
   - Clean separation - flow doesn't create debug infrastructure

2. **CLI Integration** (`src/pflow/cli/main.py`)
   - Added `--trace` flag to save debug trace even on success
   - Added `--planner-timeout` flag with 60s default timeout
   - CLI creates DebugContext and passes to flow
   - Timeout detection using threading.Timer
   - Automatic trace saving on failure

## Why These Design Decisions

### 1. Wrapper Pattern Over Modification
**Decision**: Use DebugWrapper to wrap nodes instead of modifying them

**Why**:
- Preserves tested production code
- No risk of breaking existing functionality
- Clean separation of concerns
- Easy to disable debugging

### 2. DebugContext Dependency Injection
**Decision**: Pass DebugContext to flow instead of creating it inside

**Why**:
- Flow creation only cares about creating flows
- CLI is the right place to know about user input
- More testable (can pass mock debug context)
- Consistent return type (Flow, not sometimes tuple)

### 3. Timeout Detection Only
**Decision**: Detect timeout after completion, not interrupt

**Why**:
- Python limitation - threads cannot be interrupted
- CPython GIL prevents true thread interruption
- Can only detect that time elapsed, not stop execution

### 4. JSON Trace Format
**Decision**: Save traces as JSON instead of binary/custom format

**Why**:
- Searchable and parseable by AI agents
- Human-readable for debugging
- Standard format with good tooling
- Easy to analyze programmatically

### 5. ~/.pflow/debug/ Directory
**Decision**: Use ~/.pflow/debug/ instead of /tmp

**Why**:
- Matches existing project patterns (~/.pflow/registry.json, ~/.pflow/workflows/)
- Persistent across reboots
- User-specific storage
- Consistent with project conventions

### 6. Progress to stderr
**Decision**: Output progress using `click.echo(err=True)`

**Why**:
- Doesn't interfere with stdout piping
- Consistent with CLI error messages
- Allows workflow output to remain clean

### 7. LLM Interception at Prompt Level
**Decision**: Intercept at `model.prompt()` not `llm.get_model()`

**Why**:
- Cleaner boundary - intercept actual API calls
- More reliable - catches the actual LLM interaction
- Easier restoration with try/finally

## Key Implementation Challenges Solved

### 1. Flow Compatibility
**Challenge**: Flow uses `copy.copy()` on nodes and directly accesses `node.successors`

**Solution**:
- Implemented `__copy__` method in DebugWrapper
- Copy successors attribute directly (not delegated)
- Preserve all Flow-required attributes

### 2. Attribute Delegation
**Challenge**: DebugWrapper must act exactly like the wrapped node

**Solution**:
- Use `__getattr__` for unknown attribute delegation
- Handle special methods to prevent recursion
- Copy critical attributes directly

### 3. Clean Architecture
**Challenge**: Initial implementation had flow creating debug infrastructure

**Solution**:
- Refactored to DebugContext pattern
- Dependency injection from CLI
- Flow only wraps if context provided

## Expected User Experience

### Normal Execution
```bash
$ pflow "create a changelog"
🔍 Discovery... ✓ 2.1s
📝 Parameters... ✓ 1.5s
✅ Workflow ready: generate-changelog
```

### Timeout Detection
```bash
$ pflow "complex request" --planner-timeout 30
🔍 Discovery... ✓ 2.1s
🤖 Generating...
⏰ Operation exceeded 30s timeout
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20240111-103000.json
```

### Explicit Trace Request
```bash
$ pflow "analyze data" --trace
🔍 Discovery... ✓ 2.1s
✅ Workflow ready: analyzer
📝 Trace saved: ~/.pflow/debug/pflow-trace-20240111-104000.json
```

### Automatic Trace on Failure
```bash
$ pflow "invalid request"
🔍 Discovery... ✓ 2.1s
❌ Planner failed: Validation error
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20240111-105000.json
```

## Files Modified

1. `src/pflow/planning/debug.py` - Created with all debug classes
2. `src/pflow/planning/debug_utils.py` - Created with utility functions
3. `src/pflow/planning/flow.py` - Modified to accept DebugContext
4. `src/pflow/cli/main.py` - Added flags and debug integration

## Progress Log Updated

The implementation progress has been documented in:
`.taskmaster/tasks/task_27/implementation/progress-log.md`

This log includes:
- Timestamped progress entries
- Key decisions and insights
- Problems encountered and solutions
- Refactoring decisions

## Testing Status

- ✅ Planning tests passing (276 tests)
- ✅ CLI flags available and working
- ⏳ Comprehensive test suite pending (to be done by test-writer-fixer)
- ⏳ End-to-end testing with real planner pending

## Next Steps

1. Deploy test-writer-fixer agent for comprehensive test coverage
2. Perform end-to-end testing with real planner execution
3. Document debugging features in README
4. Consider splitting complex CLI function to address linting warning

## Summary

The debugging infrastructure has been successfully implemented following the specifications. It provides:
- Real-time progress visibility during planner execution
- Comprehensive trace files for debugging failures
- Timeout detection for hung operations
- Clean architecture with dependency injection
- No modifications to existing node implementations

The implementation follows Python best practices and project conventions while working within Python's threading limitations.