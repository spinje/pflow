# Task 31: Refactor Test Infrastructure - Mock at LLM Level

## Executive Summary

The current test infrastructure uses a complex mock system at the `pflow.planning` module level, causing severe test failures and performance degradation. This task refactors the test mocking strategy to mock at the LLM API level - the actual external dependency - eliminating module state pollution and test interference issues.

## Problem Statement

### Current State
- **30+ tests failing** when run together (but pass in isolation)
- **Test execution time increased from 6s to 4+ minutes** (40x slowdown)
- **Individual tests hanging** from 0.1ms to 1m+ (60,000x slowdown)
- **Module state pollution** between tests due to `sys.modules` manipulation
- **Complex mock maintenance** with special cases for submodules

### Root Cause Analysis

The fundamental issue is **architectural mismatch**:
1. The mock tries to be a **partial mock** - blocking some parts of `pflow.planning` while allowing others
2. This creates tangled dependencies:
   - Module state modifications in `sys.modules`
   - Submodule import order dependencies
   - Reference cycles between real and mocked modules
   - State pollution when tests import from `pflow.planning.nodes`

### Impact
- **Development velocity**: Developers cannot trust test results
- **CI/CD reliability**: Flaky tests cause false failures
- **Debugging difficulty**: Tests behave differently in isolation vs. together
- **Task 27 blocked**: Debugging features work but tests fail

## Solution Overview

**Mock at the correct boundary**: The LLM API level, not the planning module level.

```python
# OLD: Mock entire planning module (wrong boundary)
sys.modules["pflow.planning"] = MockPlanningModule()

# NEW: Mock only LLM calls (correct boundary)
@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    monkeypatch.setattr("llm.get_model", mock_get_model)
```

## Status
done

## Completed
2025-08-17

## Requirements

### Functional Requirements

**FR1: LLM Mock Fixture**
- MUST mock `llm.get_model()` to prevent actual API calls
- MUST return configurable mock responses
- MUST be automatically applied to all tests via `autouse=True`
- MUST support test-specific response overrides

**FR2: Planning Module Access**
- MUST allow normal imports from `pflow.planning`
- MUST allow normal imports from all submodules (`nodes`, `debug`, `flow`)
- MUST NOT modify `sys.modules` state
- MUST NOT cause import order dependencies

**FR3: Test Compatibility**
- MUST maintain backward compatibility with existing tests
- MUST support tests that need specific LLM responses
- MUST support tests that verify LLM was called
- MUST support tests that verify LLM was NOT called

**FR4: Performance**
- MUST eliminate test hanging issues
- MUST restore test execution to <10 seconds for full suite
- MUST have zero import-time overhead
- MUST NOT trigger heavy import chains

### Non-Functional Requirements

**NFR1: Simplicity**
- Mock implementation MUST be under 100 lines of code
- MUST NOT require understanding of planning module internals
- MUST be obvious where mocking happens

**NFR2: Maintainability**
- MUST NOT require updates when planning module changes
- MUST NOT have special cases for different submodules
- MUST be easily debuggable when tests fail

**NFR3: Isolation**
- Each test MUST have clean LLM mock state
- Tests MUST NOT interfere with each other
- Parallel test execution MUST be supported

**NFR4: Documentation**
- MUST document why we mock at LLM level
- MUST provide examples of common test patterns
- MUST explain migration from old mock

## Success Criteria

1. **All tests pass**: 100% of existing tests pass without modification
2. **Fast execution**: Full test suite runs in <10 seconds
3. **No hanging**: Zero tests exhibit hanging behavior
4. **Clean imports**: All planning module imports work normally
5. **Simple code**: Mock implementation is <100 LOC
6. **No state pollution**: Tests pass in any execution order

## Out of Scope

- Modifying production code to support testing
- Changing test assertions or logic
- Implementing new test features
- Mocking other external dependencies (just LLM)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Tests rely on mock internals | High | Provide compatibility shim temporarily |
| Some tests need real LLM | Medium | Support opt-out via marker/fixture |
| Hidden LLM usage discovered | Low | Add to mock as discovered |

## Timeline

- **Phase 1** (2 hours): Implement new LLM mock
- **Phase 2** (1 hour): Remove old planning mock
- **Phase 3** (2 hours): Fix failing tests
- **Phase 4** (1 hour): Verify and document

**Total: 6 hours**

## Stakeholders

- **Primary**: Development team (need reliable tests)
- **Secondary**: CI/CD pipeline (need fast tests)
- **Tertiary**: Future contributors (need maintainable tests)

## Success Metrics

- Test execution time: <10 seconds (from 4+ minutes)
- Test pass rate: 100% (from ~96%)
- Mock code size: <100 LOC (from 200+ LOC)
- Test isolation: 100% (from ~0%)

## Decision Log

**Why mock at LLM level?**
- It's the actual external dependency
- Clean boundary with no module complications
- Simple to understand and maintain
- Proven pattern in other projects

**Why not fix the current mock?**
- Fighting Python's import system is complex
- Would require tracking ALL module references
- Fragile and will break with future changes
- Not addressing the root cause

**Why not use environment variables?**
- Adds test-specific code to production
- Less explicit than fixtures
- Harder to override per test
