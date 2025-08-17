# Task 27 Review: Planner Debugging Capabilities

## Executive Summary
Implemented comprehensive debugging infrastructure for the Natural Language Planner through a non-invasive wrapper pattern that captures LLM interactions, displays progress indicators, and saves detailed trace files. The implementation revealed and fixed critical bugs in template resolution and established patterns for future instrumentation tasks.

## Implementation Overview

### What Was Built
A two-mode debugging system that provides real-time progress visibility and detailed trace files for the planner execution:
- **DebugWrapper**: Non-invasive node wrapper that intercepts all planner node execution
- **TraceCollector**: Accumulates execution data including LLM prompts/responses
- **PlannerProgress**: Displays emoji-based progress indicators to stderr
- **DebugContext**: Dependency injection pattern for clean separation of concerns
- **CLI Integration**: --trace and --planner-timeout flags for user control

Deviations from spec:
- Used DebugContext pattern instead of boolean flags (cleaner architecture)
- Timeout detection only, cannot interrupt threads (Python limitation)
- Single global LLM interceptor instead of per-node (simpler, more reliable)

### Implementation Approach
Wrapper pattern chosen to avoid modifying existing node implementations. This preserves tested production code while adding instrumentation. Key architectural decision was to intercept at the prep/exec/post level rather than modifying nodes directly.

## Files Modified/Created

### Core Changes
- `src/pflow/planning/debug.py` - Complete debugging infrastructure (DebugWrapper, TraceCollector, PlannerProgress, DebugContext)
- `src/pflow/planning/debug_utils.py` - Utility functions for trace saving and formatting
- `src/pflow/planning/flow.py` - Modified create_planner_flow() to accept optional DebugContext
- `src/pflow/cli/main.py` - Added CLI flags, timeout detection, and debug context creation

### Test Files
- `tests/test_planning/test_debug.py` - Unit tests for debug components (critical)
- `tests/test_planning/test_debug_integration.py` - Integration tests with real planner (critical)
- `tests/test_cli/test_debug_flags.py` - CLI flag functionality tests

## Integration Points & Dependencies

### Incoming Dependencies
- CLI -> DebugContext (creates and passes to planner)
- create_planner_flow() -> DebugWrapper (wraps all 9 planner nodes)
- All planner nodes -> DebugWrapper (transparent wrapping)

### Outgoing Dependencies
- DebugWrapper -> PocketFlow.Node (must preserve all Node attributes)
- TraceCollector -> llm.get_model (monkey-patches for interception)
- PlannerProgress -> click.echo (outputs to stderr)

### Shared Store Keys
- `_trace_collector` - Temporary key for trace access during execution
- No permanent keys added to shared store

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **Wrapper Pattern** -> Non-invasive instrumentation -> Alternative: Modify nodes directly (rejected - too risky)
2. **DebugContext Injection** -> Clean separation of concerns -> Alternative: Boolean flags (rejected - anti-pattern)
3. **Single Global Interceptor** -> Simpler state management -> Alternative: Per-node interceptors (rejected - complex)
4. **JSON Trace Format** -> AI/human readable -> Alternative: Binary format (rejected - not searchable)
5. **~/.pflow/debug/ Directory** -> Consistent with project patterns -> Alternative: /tmp (rejected - not persistent)

### Technical Debt Incurred
- LLM interception via monkey-patching (fragile if library changes)
- Cannot interrupt hung LLM calls (Python GIL limitation)
- Timeout detection only after completion (not true interruption)

## Testing Implementation

### Test Strategy Applied
- Unit tests for each debug component in isolation
- Integration tests with real planner execution
- CLI tests for new flags and options
- Manual testing with various failure scenarios

### Critical Test Cases
- `test_wrapper_preserves_node_functionality` - Ensures wrapper doesn't break nodes
- `test_llm_calls_captured` - Validates LLM interception works
- `test_timeout_detection` - Confirms timeout mechanism functions
- `test_trace_file_generation` - Verifies JSON output format

## Unexpected Discoveries

### Gotchas Encountered
1. **Flow uses copy.copy() on nodes** - MUST implement __copy__ or entire planner breaks
2. **response.usage is a method, not property** - Must call response.usage() with parentheses
3. **Python threads cannot be interrupted** - Can only detect timeout after completion
4. **hasattr() vs boolean value** - _llm_interceptor_installed is always present, must check value
5. **Template resolution was broken** - Debugging revealed 3 critical bugs in template system

### Edge Cases Found
- Nodes without 'name' attribute (use class name as fallback)
- LLM responses without usage data (defensive checks needed)
- Nested workflow execution after planner (must clean up interceptor)

## Patterns Established

### Reusable Patterns
```python
# Wrapper pattern with proper attribute delegation
class DebugWrapper:
    def __init__(self, node, context):
        self._wrapped = node
        # CRITICAL: Copy Flow-required attributes
        self.successors = node.successors
        self.params = getattr(node, 'params', {})

    def __getattr__(self, name):
        # Delegate unknown attributes
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(self._wrapped, name)

    def __copy__(self):
        # CRITICAL: Flow uses copy.copy()
        import copy
        return DebugWrapper(copy.copy(self._wrapped), self.context)
```

### Anti-Patterns to Avoid
- Don't use hasattr() to check initialization flags - check the value directly
- Don't assume all nodes have standard attributes - use getattr with defaults
- Don't output progress to stdout - use stderr to avoid breaking pipes

## Breaking Changes

### API/Interface Changes
None - all changes are additive and optional

### Behavioral Changes
- Planner now always shows progress indicators (minimal visual change)
- Failed planning automatically saves debug trace (new file in ~/.pflow/debug/)

## Future Considerations

### Extension Points
- `DebugWrapper` pattern can be reused for any node instrumentation
- `TraceCollector` format can be extended with additional data
- Progress indicators can be customized via NODE_ICONS mapping

### Scalability Concerns
- Trace files can grow large with many LLM calls (consider rotation)
- LLM interception via monkey-patching may break with library updates

## AI Agent Guidance

### Quick Start for Related Tasks
1. Start by reading `src/pflow/planning/debug.py` - contains all core patterns
2. Understand PocketFlow's _run() lifecycle in `pocketflow/__init__.py`
3. Use DebugWrapper pattern for any node instrumentation needs
4. Always test with real planner execution, not just unit tests

Key patterns to follow:
- Wrapper pattern for non-invasive changes
- DebugContext for dependency injection
- Single global interceptor for API hooking
- Progress to stderr, traces to ~/.pflow/debug/

### Common Pitfalls
1. **Forgetting __copy__**: Flow will crash without it
2. **Not capturing references in closures**: Use `trace = self.trace` before nested functions
3. **Assuming thread interruption works**: It doesn't in Python
4. **Using hasattr() on initialized attributes**: Check value, not existence
5. **Not cleaning up monkey-patches**: Will break subsequent executions

### Test-First Recommendations
When modifying debug infrastructure:
1. Run `pytest tests/test_planning/test_debug.py -v` first
2. Test with real command: `uv run pflow "test" --trace`
3. Check trace file is created and contains LLM calls
4. Verify no interference with workflow execution

## Implementer ID

These changes was made with Claude Code with Session ID: `84adead1-0fd8-408d-b91d-9ba3f2e3a142`

---

*Generated from implementation context of Task 27*