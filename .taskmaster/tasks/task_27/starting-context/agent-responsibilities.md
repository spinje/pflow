# Agent Responsibilities - Task 27

## Quick Reference: Who Does What

### Main Agent
**Owns: Complete implementation of debugging infrastructure**

| Task | File | Description |
|------|------|-------------|
| DebugWrapper class | `src/pflow/planning/debug.py` | Wraps nodes to capture debug data, handles delegation |
| TraceCollector class | `src/pflow/planning/debug.py` | Collects execution trace data throughout run |
| PlannerProgress class | `src/pflow/planning/debug.py` | Displays progress indicators in terminal |
| Utility functions | `src/pflow/planning/debug_utils.py` | Helper functions for trace saving, formatting |
| Flow integration | `src/pflow/planning/flow.py` | Create wrapped flow with debugging enabled |
| CLI integration | `src/pflow/cli/main.py` | Add flags, timeout handling, trace control |

### Test-Writer-Fixer Agent
**Owns: All test files**

| Test Type | File | What to Test |
|-----------|------|--------------|
| Unit tests | `tests/test_planning/test_debug.py` | DebugWrapper, TraceCollector, PlannerProgress |
| Integration | `tests/test_planning/test_debug_integration.py` | Full planner with debugging |
| CLI tests | `tests/test_cli/test_debug_flags.py` | New flags work correctly |
| Utility tests | `tests/test_planning/test_debug_utils.py` | Utility functions |

## Execution Timeline

```
Phase 1: Core Implementation (4-5 hours)
├── Main Agent: Create debug.py with all classes
├── Main Agent: Create debug_utils.py with utilities
├── Main Agent: Integrate into flow.py
└── Main Agent: Integrate into CLI

Phase 2: Testing (2-3 hours)
└── Test-Writer-Fixer: Write all tests

Phase 3: Validation
├── Manual testing and debugging
└── Documentation updates
```

## Handoff Protocol

### Main Agent → Test-Writer-Fixer
- Provide completed implementation
- List critical scenarios to test
- Specify edge cases
- Note any Python-specific gotchas encountered

### Test-Writer-Fixer → Main Agent
- Deliver passing test suite
- Report any issues found
- Suggest improvements
- Note test coverage achieved

## Success Criteria by Agent

### Main Agent Success
- [ ] DebugWrapper preserves all node functionality
- [ ] Wrapper handles special methods (__copy__, __deepcopy__)
- [ ] Progress shows during execution
- [ ] Timeout detection works (after completion only)
- [ ] Integration doesn't break planner
- [ ] All utilities have proper error handling
- [ ] LLM interception at prompt level (not module level)
- [ ] Clean trace files generated

### Test-Writer-Fixer Success
- [ ] All tests pass
- [ ] >90% coverage on debug.py
- [ ] Edge cases covered
- [ ] No existing tests broken

## Risk Mitigation

### Highest Risk: DebugWrapper
- **Risk**: Breaking node delegation
- **Mitigation**: Main agent handles with full context
- **Test**: Extensive delegation tests

### Medium Risk: LLM Interception
- **Risk**: Not restoring original methods
- **Mitigation**: Always use try/finally
- **Test**: Verify restoration in tests

### Low Risk: Utilities
- **Risk**: File I/O errors
- **Mitigation**: Proper error handling
- **Test**: Unit tests with mocks

## Key Implementation Notes

### Critical Python Gotchas (from test infrastructure insights)
1. **Threading cannot be interrupted** - Timeout detection happens after completion
2. **__getattr__ delegation needs __copy__/__deepcopy__** - Prevents recursion errors
3. **Logging is global state** - Configure specific loggers, not basicConfig
4. **Wrapper must observe, not recreate** - Don't duplicate Flow logic

### Questions Clarified

For Main Agent:
- How exactly does Flow call nodes? **Answer: via _run()**
- What attributes must be preserved? **Answer: successors, params**
- Can we interrupt hung threads? **Answer: No, Python limitation**

For Test-Writer-Fixer:
- Mock or real planner? **Answer: Use new LLM-level mock infrastructure**
- Coverage target? **Answer: >90% for new code**
- Test infrastructure status? **Answer: Fixed - mocks at LLM level now**

## Final Checklist

Before marking Task 27 complete:

- [ ] Main agent: Core debug.py complete with special method handling
- [ ] Main agent: debug_utils.py with all utility functions
- [ ] Main agent: Flow integration working
- [ ] Main agent: CLI flags working with timeout detection
- [ ] Test-writer: All tests passing with new mock infrastructure
- [ ] Manual test: Can debug real planner
- [ ] Documentation: README updated