# Task 27 Implementation Plan

## Context Verification Complete
✅ Read epistemic manifesto - understand robust development principles
✅ Read task overview and PRD - understand two-mode debugging system
✅ Read handoff document - critical insights about Python limitations
✅ Read specification - 28 test criteria that must pass
✅ Read implementation guide - complete working code provided
✅ Read agent responsibilities - clear division of work

## Critical Learnings from Context
1. **Python threads CANNOT be interrupted** - only detect timeout after completion
2. **DebugWrapper attribute delegation is CRITICAL** - must copy successors and params
3. **LLM interception at model.prompt() level** - not at llm.get_model()
4. **Use ~/.pflow/debug/ directory** - matches project patterns
5. **Progress to stderr** - use click.echo(err=True)
6. **Working code exists** - use the implementation guide, don't reinvent

## Implementation Order

### Phase 1: Core Debug Infrastructure (NOW)
**Owner: Main Agent**
1. Create progress log
2. Create `src/pflow/planning/debug.py` with:
   - DebugWrapper class (most critical - test delegation first!)
   - TraceCollector class
   - PlannerProgress class
3. Test DebugWrapper delegation locally before proceeding

### Phase 2: Utility Functions (PARALLEL with Phase 1)
**Owner: Code-Implementer Subagent**
Deploy subagent to create `src/pflow/planning/debug_utils.py`:
- save_trace_to_file()
- format_progress_message()
- create_llm_interceptor()

### Phase 3: Flow Integration
**Owner: Main Agent**
1. Modify `src/pflow/planning/flow.py`:
   - Add create_planner_flow_with_debug() function
   - Wrap all 9 nodes with DebugWrapper
2. Verify flow wiring preserved

### Phase 4: CLI Integration
**Owner: Main Agent**
1. Modify `src/pflow/cli/main.py`:
   - Add --trace and --planner-timeout flags
   - Implement execute_with_planner_debug()
   - Add timeout detection with threading.Timer

### Phase 5: Testing
**Owner: Test-Writer-Fixer Subagent**
Deploy subagent to create comprehensive tests:
- Unit tests for debug module
- Integration tests with real planner
- CLI flag tests
- Edge case coverage

### Phase 6: Manual Testing & Refinement
**Owner: Main Agent**
1. Test with real planner execution
2. Verify all 28 test criteria pass
3. Fix any issues discovered
4. Update documentation

## Risk Mitigation

### Highest Risk: DebugWrapper Delegation
- **Mitigation**: Test delegation in isolation first
- **Verification**: Create simple test node and verify attributes preserved

### Medium Risk: LLM Interception
- **Mitigation**: Always use try/finally to restore
- **Verification**: Test with mock LLM calls

### Low Risk: Utilities
- **Mitigation**: Proper error handling
- **Verification**: Unit tests

## Success Criteria Checklist
- [ ] DebugWrapper preserves all node attributes
- [ ] Progress indicators appear during execution
- [ ] Timeout detected after 60 seconds
- [ ] Trace files saved to ~/.pflow/debug/
- [ ] LLM prompts and responses captured
- [ ] --trace flag forces trace generation
- [ ] No modifications to existing nodes
- [ ] All 28 test criteria from spec pass
- [ ] make test passes with no regressions
- [ ] make check passes (linting, type checking)

## Time Estimate
- Phase 1: 1-2 hours (core debug.py)
- Phase 2: 30 minutes (utilities - parallel)
- Phase 3: 30 minutes (flow integration)
- Phase 4: 30 minutes (CLI integration)
- Phase 5: 2 hours (testing)
- Phase 6: 1 hour (manual testing)

Total: ~5 hours

## Notes
- The implementation guide has verified working code - USE IT
- Test DebugWrapper delegation before anything else
- Python thread limitation is real - don't try to be clever
- Use the exact node-to-emoji mapping from the guide