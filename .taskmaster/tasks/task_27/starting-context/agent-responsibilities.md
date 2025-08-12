# Agent Responsibilities - Task 27

## Quick Reference: Who Does What

### Main Agent
**Owns: Core integration and critical flow compatibility**

| Task | File | Why Main Agent? |
|------|------|----------------|
| DebugWrapper class | `src/pflow/planning/debug.py` | Critical delegation pattern, must understand Flow |
| TraceCollector class | `src/pflow/planning/debug.py` | Tightly coupled with wrapper |
| PlannerProgress class | `src/pflow/planning/debug.py` | Simple but coupled with wrapper |
| Flow integration | `src/pflow/planning/flow.py` | Must know all 9 nodes and wiring |
| CLI integration | `src/pflow/cli/main.py` | Must understand existing CLI patterns |

### Code-Implementer Agent
**Owns: Isolated utility functions**

| Task | File | Why Code-Implementer? |
|------|------|----------------------|
| save_trace_to_file() | `src/pflow/planning/debug_utils.py` | Simple file I/O, clear spec |
| format_progress_message() | `src/pflow/planning/debug_utils.py` | Pure formatting function |
| create_llm_interceptor() | `src/pflow/planning/debug_utils.py` | Self-contained wrapper factory |
| format_trace_summary() | `src/pflow/planning/debug_utils.py` | Optional, pure formatting |

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
Day 1 Morning:
├── Main Agent: Create debug.py (2-3 hours)
└── Code-Implementer: Create utilities (1 hour, parallel)

Day 1 Afternoon:
├── Main Agent: Integrate into flow.py (1 hour)
└── Main Agent: Integrate into CLI (1 hour)

Day 1 Evening:
└── Test-Writer-Fixer: Write all tests (2-3 hours)

Day 2:
├── Manual testing and debugging
└── Documentation updates
```

## Handoff Protocol

### Main Agent → Code-Implementer
- Provide exact function signatures
- Give input/output examples
- No need to explain planner architecture

### Main Agent → Test-Writer-Fixer
- Provide completed implementation
- List critical scenarios to test
- Specify edge cases

### Code-Implementer → Main Agent
- Deliver working utilities
- Document any assumptions
- Note any error cases handled

### Test-Writer-Fixer → Main Agent
- Deliver passing test suite
- Report any issues found
- Suggest improvements

## Success Criteria by Agent

### Main Agent Success
- [ ] DebugWrapper preserves all node functionality
- [ ] Progress shows during execution
- [ ] Timeout detection works
- [ ] Integration doesn't break planner

### Code-Implementer Success
- [ ] All utilities have proper error handling
- [ ] Functions are independently testable
- [ ] Clear docstrings with examples
- [ ] Type hints on all functions

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

## Communication Points

### Questions to Clarify Before Starting

For Main Agent:
- How exactly does Flow call nodes? (Answer: via _run())
- What attributes must be preserved? (Answer: successors, params)

For Code-Implementer:
- What Python version? (Answer: 3.9+)
- Any special JSON requirements? (Answer: Use default=str)

For Test-Writer-Fixer:
- Mock or real planner? (Answer: Mock for unit, real for integration)
- Coverage target? (Answer: >90% for new code)

## Final Checklist

Before marking Task 27 complete:

- [ ] Main agent: Core debug.py complete
- [ ] Main agent: Flow integration working
- [ ] Main agent: CLI flags working
- [ ] Code-implementer: All utilities working
- [ ] Test-writer: All tests passing
- [ ] Manual test: Can debug real planner
- [ ] Documentation: README updated