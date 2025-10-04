# Task 71 Test Implementation Plan

## Overview

This document coordinates the implementation of 5 comprehensive test files for Task 71 features. All test specifications are written with a focus on **catching real bugs** and **enabling confident refactoring**, not achieving coverage metrics.

## Test Philosophy

**These tests are guardrails for AI-driven development.**

Every test must:
1. ✅ Catch real bugs, not stylistic changes
2. ✅ Enable confident refactoring by validating behavior contracts
3. ✅ Provide clear feedback about what broke and why
4. ✅ Run fast (<100ms for unit tests)
5. ✅ Not duplicate existing test coverage

**Delete bad tests** - A bad test is worse than no test.

## Test Specifications

| # | Feature | Spec File | Estimated Effort | Priority |
|---|---------|-----------|------------------|----------|
| 1 | `--validate-only` flag | `test-spec-validate-only.md` | 50 min | HIGH |
| 2 | `workflow save` command | `test-spec-workflow-save.md` | 1.5 hours | HIGH |
| 3 | Discovery commands | `test-spec-discovery-commands.md` | 1.5 hours | MEDIUM |
| 4 | Enhanced error output | `test-spec-enhanced-error-output.md` | 1.75 hours | MEDIUM |
| 5 | `registry describe` command | `test-spec-registry-describe.md` | 1.5 hours | MEDIUM |

**Total estimated effort**: ~6.75 hours

**Realistic target**: 3-4 hours (focus on highest value tests)

## Priority Breakdown

### Priority 1: Critical Agent Features (2 hours)

These validate the core contracts that agents depend on:

1. **`--validate-only` (50 min)**
   - Most critical: No execution side effects
   - Structural validation without parameters
   - Auto-normalization behavior

2. **`workflow save` (1.5 hours)**
   - Validation before save contract
   - Name validation (fixes security issue)
   - Safe file deletion
   - Reserved names blocking

**Why prioritize these**: These features enable safe agent workflow building. If they break, agents can't iterate safely.

### Priority 2: Integration & Discovery (3 hours)

These validate critical integrations and LLM-powered features:

3. **Discovery commands (1.5 hours)**
   - Workflow discover integration
   - Registry discover integration
   - Anthropic monkey patch requirement
   - Graceful LLM unavailable handling

4. **Enhanced error output (1.75 hours)**
   - Two-layer architecture validation
   - Template error suggestions
   - Execution state visibility
   - HTTP/MCP error context

**Why prioritize these**: These features make debugging possible. If they break, agents get stuck on errors.

### Priority 3: Developer Experience (1.5 hours)

These validate UX improvements:

5. **`registry describe` (1.5 hours)**
   - Name normalization
   - Multi-node support
   - MCP tool handling

**Why lower priority**: Nice to have, but agents can work around issues with `registry list`.

## Implementation Strategy

### Recommended Approach: Parallel Test Writing

Use **test-writer-fixer subagent** for each test file:

**Phase 1 - Critical Features (Deploy 2 agents in parallel)**:
```bash
# Agent 1: --validate-only tests
# Agent 2: workflow save tests
# Total time: ~1.5 hours (parallel execution)
```

**Phase 2 - Integration Tests (Deploy 2 agents in parallel)**:
```bash
# Agent 3: Discovery commands tests
# Agent 4: Enhanced error output tests
# Total time: ~1.75 hours (parallel execution)
```

**Phase 3 - Optional (Deploy 1 agent)**:
```bash
# Agent 5: registry describe tests
# Total time: ~1.5 hours
```

**Total wall-clock time with parallelization**: ~3.25 hours (vs 6.75 hours sequential)

### Subagent Instructions Template

For each test file, provide test-writer-fixer with:

```
Task: Implement tests for [FEATURE NAME] following specification

Specification: scratchpads/task-71-tests/test-spec-[NAME].md

Requirements:
1. Read the specification completely before starting
2. Follow the test structure exactly as specified
3. Focus on tests marked as "Critical Behaviors" first
4. Use real components, not mocks (unless spec says otherwise)
5. Each test must validate a behavior contract, not implementation
6. Tests must fail when the contract is violated
7. Include clear docstrings explaining WHAT contract is tested
8. Run make test to verify all tests pass
9. Estimated time: [TIME FROM TABLE]

Success criteria:
- All specified critical behaviors have tests
- All tests pass
- Tests use appropriate fixtures (cli_runner, tmp_path)
- No duplicate tests (check existing coverage mentioned in spec)
- Fast execution (<100ms per test)

Output:
- Test file at path specified in spec
- Summary of what was tested and any issues found
```

## Test Quality Checklist

Before marking tests complete, verify:

- [ ] Tests validate **contracts** (what code promises), not **implementation** (how it works)
- [ ] Tests would **fail if feature is broken** (not false positives)
- [ ] Tests use **real components** where possible (mocking is exception)
- [ ] Test names clearly state **what behavior is validated**
- [ ] Tests run **fast** (<100ms each, <1s for integration tests)
- [ ] No **duplicate coverage** of existing tests
- [ ] Clear **failure messages** (know what broke without debugging)

## Real Bugs These Tests Prevent

From Task 71 implementation experience:

1. **Execution during validation** - validate-only must not have side effects
2. **Missing workflow_manager** - Discovery commands require it in shared store
3. **Missing Anthropic patch** - Command groups need independent setup
4. **Weak name validation** - Current regex allows `-test`, `my--workflow`
5. **Unsafe file deletion** - Path check uses `in parts` (too permissive)
6. **Template errors without context** - Need available fields for debugging
7. **Signature mismatch** - _handle_workflow_error needs result parameter

## Existing Test Coverage (Don't Duplicate)

Check these before writing new tests:

- `tests/test_cli/test_workflow_save.py` - Basic workflow save (already exists)
- `tests/test_cli/test_registry_normalization.py` - MCP tool normalization (comprehensive, 227 lines)
- `tests/test_runtime/test_workflow_validator.py` - Validation logic
- `tests/test_runtime/test_template_validator.py` - Template validation
- `tests/test_runtime/test_template_validator_enhanced_errors.py` - Enhanced template errors
- `tests/test_planning/integration/test_discovery_*.py` - Discovery node behavior

**Focus on CLI integration**, not reimplementing existing tests.

## Success Metrics

### Minimum Acceptable Coverage (Priority 1 only)
- 2 test files implemented
- ~12-15 tests total
- ~40% of planned coverage
- **Blocks**: Name validation security issue, validate-only contracts
- **Enables**: Safe agent workflow iteration

### Good Coverage (Priority 1 + Priority 2)
- 4 test files implemented
- ~30-35 tests total
- ~70% of planned coverage
- **Blocks**: All security issues, integration bugs
- **Enables**: Production-ready agent features

### Complete Coverage (All priorities)
- 5 test files implemented
- ~45-50 tests total
- 100% of planned coverage
- **Blocks**: All identified bugs, UX issues
- **Enables**: Full feature confidence

## Next Steps

1. **Review staged fixes** - Verify Priority 1 and 2 fixes are ready
2. **Deploy test agents** - Start with Priority 1 (parallel)
3. **Validate tests pass** - Run `make test` after each agent
4. **Commit in phases** - Don't wait for all tests
5. **Update PR** - Push test coverage incrementally

## Estimated Timeline

**Aggressive (Priority 1 only)**: 1.5-2 hours wall-clock
- 2 agents in parallel
- Minimum for merge safety

**Balanced (Priority 1-2)**: 3-4 hours wall-clock
- 4 agents across 2 phases
- Production-ready quality

**Complete (All)**: 4-5 hours wall-clock
- 5 agents across 3 phases
- Full specification coverage

## Decision Point

**Recommendation**: Start with Priority 1, assess progress, then decide on Priority 2.

**Rationale**:
- Priority 1 tests (2 hours) fix all critical security issues
- Can merge with Priority 1 complete
- Priority 2 adds significant value but not blocking
- Priority 3 is nice-to-have

**Your call**: Which priority level should we target?
