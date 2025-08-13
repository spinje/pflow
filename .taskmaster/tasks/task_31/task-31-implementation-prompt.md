# Task 31: Refactor Test Infrastructure - Mock at LLM Level - Agent Instructions

## The Problem You're Solving

The current test infrastructure uses a complex mock system at the `pflow.planning` module level, causing severe test failures and performance degradation. 30+ tests fail when run together (but pass in isolation), test execution time has increased from 6 seconds to 4+ minutes (40x slowdown), and individual tests hang from 0.1ms to 1m+ (60,000x slowdown). The root cause is architectural mismatch - the mock tries to be a partial mock that blocks some parts of `pflow.planning` while allowing others, creating tangled dependencies and module state pollution.

## Your Mission

Refactor the test mocking strategy to mock at the LLM API level - the actual external dependency - eliminating module state pollution and test interference issues. Replace the complex 200+ LOC planning module mock with a simple sub-100 LOC LLM mock that provides clean test isolation and fast execution.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_31/task_31.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_31/starting-context/`

**Files to read (in this order):**
1. `task-31-technical-spec.md` - Complete technical specification (FOLLOW THIS PRECISELY)
2. `task-31-implementation-plan.md` - Step-by-step implementation guide with code examples

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-31-technical-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

A new LLM-level mock system that replaces the problematic planning module mock. The solution consists of:
- `MockLLMModel` class that simulates LLM API responses
- Auto-applied pytest fixture that prevents actual API calls
- Response configuration system for test-specific needs
- Call history tracking for verification
- Clean state isolation between tests

Example usage:
```python
def test_planner_with_custom_response(mock_llm_responses):
    # Configure what the LLM will return
    mock_llm_responses.set("anthropic/claude", {
        "found": True,
        "workflow_name": "test-workflow"
    })

    # Run code that uses the planner
    result = some_planner_function()

    # LLM is mocked, no actual API calls made
    assert result.workflow_name == "test-workflow"
```

## Key Outcomes You Must Achieve

### Core Infrastructure
- Create `tests/shared/llm_mock.py` with MockLLMModel class (<100 LOC)
- Implement auto-applied fixture in `tests/conftest.py`
- Support configurable responses per model
- Track call history for test verification
- Ensure complete test isolation

### Test Migration
- Disable old planning module mock
- Fix all failing tests (30+ currently failing)
- Maintain backward compatibility where needed
- Verify all planning imports work normally

### Performance & Quality
- Restore test execution to <10 seconds (from 4+ minutes)
- Eliminate all test hanging issues
- Ensure tests pass in any execution order
- Support parallel test execution

## Implementation Strategy

### Phase 0: Analysis and Preparation (30 minutes)
1. Identify all LLM usage points in the codebase
2. Analyze current test patterns and failures
3. Create backup of current mock system

### Phase 1: Implement New LLM Mock (2 hours)
1. Create core MockLLMModel class (30 min)
2. Implement fixture system (30 min)
3. Create compatibility layer (30 min)
4. Test the new mock system (30 min)

### Phase 2: Remove Old Planning Mock (1 hour)
1. Disable autouse fixture in old mock (15 min)
2. Update test imports (30 min)
3. Verify planning imports work (15 min)

### Phase 3: Fix Failing Tests (2 hours)
1. Run tests and categorize failures (30 min)
2. Fix direct planning mocks (45 min)
3. Fix LLM response tests (30 min)
4. Fix edge cases (15 min)

### Phase 4: Verification and Documentation (1 hour)
1. Verify performance (<10 seconds)
2. Verify test isolation
3. Create migration guide
4. Update documentation

### Phase 5: Cleanup (30 minutes)
1. Remove old mock system
2. Remove compatibility layer if unused
3. Final test run

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### MockLLMModel Implementation
The mock must handle different response patterns used by planner nodes:
```python
# Pattern 1: Structured response with schema
response = model.prompt(prompt, schema=DiscoveryResult)
result = response.json()  # Returns dict

# Pattern 2: Text response
response = model.prompt(prompt)
text = response.text  # Returns string

# Pattern 3: Token usage
response = model.prompt(prompt)
tokens = response.usage  # Returns {"input_tokens": N, "output_tokens": M}
```

### Fixture Architecture
Auto-applied fixture that mocks all LLM calls:
```python
@pytest.fixture(autouse=True, scope="function")
def mock_llm_calls(monkeypatch) -> MockGetModel:
    """Auto-applied fixture that mocks all LLM calls."""
    mock_get_model = create_mock_get_model()
    monkeypatch.setattr("llm.get_model", mock_get_model)
    yield mock_get_model
    mock_get_model.reset()  # Clean up
```

### Call History Tracking
Each call must record:
```python
{
    "timestamp": datetime.now().isoformat(),
    "prompt": prompt_text,
    "prompt_length": len(prompt_text),
    "kwargs": {
        "schema": schema.__name__ if schema else None,
        "temperature": temperature,
        "model": model,
    },
    "response": response_data,
    "error": error_message if failed else None
}
```

### Migration Patterns
Key patterns for migrating tests:
```python
# OLD: Mock entire planning module
with patch("pflow.planning.flow.create_planner_flow") as mock:
    mock.return_value = (mock_flow, mock_trace)

# NEW: Configure LLM responses
def test_with_planner(mock_llm_responses):
    mock_llm_responses.set("anthropic/claude", {
        "found": False,
        "nodes": ["read-file"],
        "workflow": {...}
    })
```

## Critical Warnings from Experience

### Module Import Order Matters
The old mock manipulated `sys.modules` which caused import order dependencies. The new mock must NOT touch `sys.modules` at all - only patch the `llm.get_model` function. This ensures imports from `pflow.planning` work normally.

### Test Isolation is Critical
Each test MUST get a clean mock state. The fixture scope must be "function" not "session" or "module". Always reset the mock in the fixture cleanup to prevent state leakage between tests.

### Response Handling Must Be Flexible
Different planner nodes expect different response formats. The mock must handle:
- Structured responses (with .json() method)
- Text responses (with .text attribute)
- Usage tracking (with .usage attribute)
- Error simulation (raising exceptions)

## Key Decisions Already Made

1. **Mock at LLM level, not planning module level** - This is the actual external dependency
2. **Use monkeypatch, not sys.modules manipulation** - Clean, reversible patching
3. **Autouse fixture for all tests** - Prevents accidental API calls
4. **Function-scoped fixtures** - Ensures test isolation
5. **Keep mock under 100 LOC** - Simplicity over features
6. **No modification to production code** - Tests adapt to code, not vice versa
7. **Compatibility layer for gradual migration** - Don't break everything at once

## Success Criteria

Your implementation is complete when:

- ✅ All tests pass (100% pass rate, up from ~96%)
- ✅ Test execution time <10 seconds (down from 4+ minutes)
- ✅ No hanging tests (0 tests with >1s unexplained delay)
- ✅ Tests pass in any execution order (random, reverse, parallel)
- ✅ Mock implementation <100 LOC (down from 200+)
- ✅ All planning module imports work normally
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Migration guide created for other developers

## Common Pitfalls to Avoid

1. **Don't modify sys.modules** - This causes the state pollution we're trying to fix
2. **Don't create session-scoped fixtures** - Each test needs clean state
3. **Don't forget usage tracking** - Some tests verify token counts
4. **Don't hardcode responses** - Make them configurable per test
5. **Don't skip the compatibility layer** - Some tests may need gradual migration
6. **Don't forget to disable the old mock** - Running both will cause conflicts
7. **Don't rush the migration** - Fix tests systematically, not all at once

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Mock Analysis**
   - Task: "Analyze tests/shared/mocks.py to understand the current mock implementation and identify all its features"
   - Task: "Find all tests that use the planning mock and categorize their usage patterns"

2. **LLM Usage Discovery**
   - Task: "Search for all llm.get_model() calls in src/pflow/planning/ and document the response patterns"
   - Task: "Identify how planner nodes use LLM responses (schemas, text, usage tracking)"

3. **Test Failure Analysis**
   - Task: "Run pytest tests/test_planning/ and categorize the types of failures"
   - Task: "Identify which tests hang and what causes the hanging"

4. **Import Pattern Analysis**
   - Task: "Find all imports from pflow.planning in tests and document the patterns"
   - Task: "Identify tests that would break if planning module isn't importable"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_31/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Implementation Plan Template

```markdown
# Task 31 Implementation Plan

## Context Gathered

### Current Mock System Analysis
- [Key features of the old mock]
- [Why it causes problems]

### LLM Usage Patterns
- [How planner nodes use LLM]
- [Response formats needed]

### Test Failure Categories
- [Types of failures found]
- [Root causes identified]

## Implementation Steps

### Phase 1: Core Mock Infrastructure (Parallel Execution Possible)
1. **Create LLM Mock Module** (Subagent A)
   - Files: tests/shared/llm_mock.py
   - Context: Must handle structured responses, text responses, usage tracking

2. **Create Fixture System** (Subagent B)
   - Files: tests/conftest.py
   - Context: Auto-applied, function-scoped, configurable

### Phase 2: Disable Old System (Sequential)
1. **Disable Old Mock**
   - Files: tests/shared/mocks.py
   - Dependencies: New mock must be working
   - Key considerations: Don't delete yet, just disable

### Phase 3: Fix Failing Tests (Parallel by Category)
1. **Fix Planning Mock Tests** (Subagent C)
   - Files: [List specific test files]
   - Pattern: Replace patch() with mock_llm_responses

2. **Fix Import Tests** (Subagent D)
   - Files: [List specific test files]
   - Pattern: Should work without changes

### Phase 4: Verification (Sequential)
1. **Performance Testing**
   - Run full suite with timing
   - Verify <10 second execution

2. **Isolation Testing**
   - Run tests in random order
   - Verify no interference

### Phase 5: Documentation and Cleanup
1. **Create Migration Guide**
   - File: tests/MIGRATION_GUIDE.md
   - Document patterns for future test writers

2. **Remove Old System**
   - Delete old mock if all tests pass
   - Remove compatibility layer if unused

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Hidden LLM usage | Search comprehensively first |
| Tests rely on mock internals | Provide compatibility layer |
| Performance regression | Measure before/after each phase |

## Validation Strategy

- Unit tests for mock system itself
- Integration tests for fixture behavior
- Full test suite as final validation
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_31/implementation/progress-log.md`

```markdown
# Task 31 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. **Analyze current state** - Understand what's broken and why
2. **Create new mock system** - Build the clean LLM mock
3. **Implement fixtures** - Set up auto-applied mocking
4. **Disable old system** - Turn off the problematic mock
5. **Fix failing tests** - Systematically migrate tests
6. **Verify performance** - Ensure <10 second execution
7. **Verify isolation** - Test in random order
8. **Document migration** - Help future developers
9. **Clean up** - Remove old code

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**For this task specifically**:
- Create unit tests for the mock system itself
- Verify mock isolation between tests
- Test that LLM is never actually called
- Verify response configuration works

**Core testing principles**:
- Test the mock returns configured responses
- Test call history tracking works
- Test isolation between tests
- Test error simulation

**Progress Log - Only document testing insights**:
```markdown
## 14:30 - Testing revealed mock state leakage
While testing the mock system, discovered that class-level
attributes weren't being reset between tests. Fixed by ensuring
reset() is always called in fixture cleanup.
```

## What NOT to Do

- **DON'T** modify `sys.modules` - This is what causes the current problems
- **DON'T** touch production code - Only modify test infrastructure
- **DON'T** create complex mocks - Keep it under 100 LOC
- **DON'T** use session or module scope - Only function scope for isolation
- **DON'T** hardcode LLM responses - Make them configurable
- **DON'T** skip the migration guide - Other developers need to understand the change
- **DON'T** delete old mock immediately - Disable first, delete after verification

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Analyze the current mock in `tests/shared/mocks.py`
3. Search for LLM usage patterns: `grep -r "llm.get_model" src/pflow/planning/`
4. Run tests to see current failures: `pytest tests/ -v --tb=short`
5. Start implementation with Phase 0 analysis

## Final Notes

- The current mock is fundamentally broken due to module manipulation
- The solution is simple: mock the actual external dependency (LLM API)
- Focus on test isolation - each test must have clean state
- Performance should improve dramatically once module pollution is eliminated
- The implementation plan has specific code examples - use them!

## Remember

You're fixing a critical infrastructure problem that's blocking development. The root cause is clear: mocking at the wrong boundary. The solution is straightforward: mock at the LLM API level. This will unblock Task 27 (debugging features) and restore developer productivity.

The current 40x slowdown and test failures are symptoms of architectural mismatch. By mocking at the correct boundary, you'll eliminate module state pollution and restore clean, fast test execution.

Good luck! This fix will dramatically improve the development experience and unblock critical features. Your work here ensures that tests are reliable, fast, and maintainable.