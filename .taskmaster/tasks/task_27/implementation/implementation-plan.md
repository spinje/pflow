# Task 27 Implementation Plan: Planner Debugging Capabilities

## Objective
Enable visibility into planner execution failures through progress indicators and trace files, without modifying existing node implementations.

## Current State Analysis
- **Problem**: Planner hangs with zero visibility (no progress, no errors, no debugging data)
- **Root Cause**: No instrumentation in planner execution
- **Solution**: Wrap nodes with debugging capabilities

## Implementation Strategy

### Phase 1: Core Debug Infrastructure (2 hours)
**Owner**: Main Agent

1. **Create `src/pflow/planning/debug.py`**
   - DebugWrapper class with critical attribute delegation
   - TraceCollector for accumulating execution data
   - PlannerProgress for terminal output
   - Key challenges: __copy__ handling, attribute delegation

2. **Critical Requirements Validated**:
   - PocketFlow uses copy.copy() on nodes (lines 99, 107 of pocketflow/__init__.py)
   - Flow directly accesses node.successors
   - Python threads cannot be interrupted (only detected)
   - LLM interception must happen at prompt level

### Phase 2: Utility Functions (30 minutes)
**Owner**: Code-Implementer (in parallel with Phase 1)

1. **Create `src/pflow/planning/debug_utils.py`**
   - save_trace_to_file() - JSON file saving
   - format_progress_message() - Progress formatting
   - create_llm_interceptor() - LLM call interception helper

### Phase 3: Flow Integration (1 hour)
**Owner**: Main Agent

1. **Modify `src/pflow/planning/flow.py`**
   - Add create_planner_flow_with_debug() function
   - Wrap all 9 nodes with DebugWrapper
   - Preserve existing node connections

### Phase 4: CLI Integration (1 hour)
**Owner**: Main Agent

1. **Modify `src/pflow/cli/main.py`**
   - Add --trace and --planner-timeout flags
   - Implement timeout detection with threading.Timer
   - Wire up automatic trace saving on failure

### Phase 5: Testing (2 hours)
**Owner**: Test-Writer-Fixer

1. **Unit Tests** (`tests/test_planning/test_debug.py`)
   - DebugWrapper delegation and __copy__
   - TraceCollector functionality
   - PlannerProgress formatting

2. **Integration Tests** (`tests/test_planning/test_debug_integration.py`)
   - Full planner execution with debugging
   - Timeout detection
   - Trace file generation

3. **CLI Tests** (`tests/test_cli/test_debug_flags.py`)
   - New flags functionality
   - Environment variables

### Phase 6: Validation & Documentation (30 minutes)
**Owner**: Main Agent

1. **Manual Testing**
   - Run real planner with debugging
   - Verify progress indicators appear
   - Confirm trace files are valid JSON

2. **Documentation**
   - Update README with debugging instructions
   - Document flag usage

## Critical Success Factors

### Must Work Correctly
1. **DebugWrapper attribute delegation** - Use __getattr__ with special method handling
2. **__copy__ implementation** - Prevent recursion with copy.copy()
3. **successors attribute** - Must be copied directly, not delegated
4. **LLM interception** - At prompt level, with proper restoration
5. **Progress to stderr** - Use click.echo(err=True)

### Known Limitations (By Design)
1. **Timeout detection only** - Cannot interrupt threads (Python limitation)
2. **Synchronous execution** - No real-time progress during blocking calls
3. **Single-threaded** - Makes monkey-patching safe

## Risk Mitigation

### Highest Risk: DebugWrapper Breaking Nodes
- **Mitigation**: Use proven code from implementation guide
- **Verification**: Test with simple node first before full integration

### Medium Risk: LLM Interception
- **Mitigation**: Always use try/finally for restoration
- **Verification**: Test that original methods are restored

### Low Risk: File I/O
- **Mitigation**: Proper error handling with fallbacks
- **Verification**: Test with permission errors

## Dependencies & Blockers
- None - all prerequisites complete
- Test infrastructure refactored and ready (LLM-level mocking)

## Implementation Order
1. Create debug.py with DebugWrapper (test locally first)
2. Deploy code-implementer for utilities in parallel
3. Integrate with flow.py
4. Add CLI flags
5. Deploy test-writer-fixer for comprehensive tests
6. Manual validation

## Validation Checklist
- [ ] Progress indicators appear during execution
- [ ] Timeout detected after 60 seconds
- [ ] Failed executions save trace automatically
- [ ] Trace files contain LLM prompts/responses
- [ ] --trace flag forces trace generation
- [ ] No modifications to existing nodes
- [ ] All existing tests still pass
- [ ] make test passes
- [ ] make check passes

## Key Decisions Made
1. **Wrapper pattern over modification** - Safer, no changes to tested code
2. **JSON traces over binary** - Searchable by AI agents
3. **~/.pflow/debug/ directory** - Matches existing patterns
4. **60s default timeout** - Balance between patience and detection
5. **Progress to stderr** - Avoid breaking pipes
6. **Main agent owns all implementation** - Single owner for core code

## Expected Outcomes
- Users see real-time progress during 10-30s planner execution
- Every failure produces actionable debugging data
- Developers can improve prompts based on captured LLM interactions
- Timeouts are detected and reported clearly
- Zero regression in existing functionality