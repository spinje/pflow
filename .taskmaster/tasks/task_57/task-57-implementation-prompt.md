# Task 57: Update planner tests to use better test cases with real world north star examples - Agent Instructions

## The Problem You're Solving

The planner test suite currently uses oversimplified prompts like `"generate a changelog"` instead of realistic, verbose prompts that users actually type. Task 28 discovered that 69% of workflow generator tests used non-existent mock nodes (like `claude-code`, `github-list-prs`), creating dangerously false confidence. Tests were passing but testing nothing real. Performance failures were blocking valid tests due to API variance. This task fixes these fundamental test quality issues.

## Your Mission

Update the planner test suite to use exact north star examples from `architecture/vision/north-star-examples.md`, ensuring tests validate actual user behavior patterns. Convert performance failures to warnings, validate specific parameter extraction values, and ensure Path A (reuse) vs Path B (generation) selection works correctly based on prompt verbosity.

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
**File**: `.taskmaster/tasks/task_57/task-57.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_57/starting-context/`

**Files to read (in this order):**
1. `task-57-spec.md` - The specification (FOLLOW THIS PRECISELY for requirements and test criteria)
2. `task-57-handover.md` - Critical knowledge from Task 28's discoveries and pitfalls
3. `implementation-guide.md` - Comprehensive guide with exact prompts, patterns, and lessons learned

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-57-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

You're updating planner tests to use realistic north star examples that represent actual developer workflows:

**Primary Example - Generate Changelog (Complex)**:
```python
# Verbose prompt that triggers Path B (generation)
CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

# Brief prompt that triggers Path A (reuse)
CHANGELOG_BRIEF = "generate a changelog for version 1.4"
```

These tests will validate:
- Verbose prompts trigger workflow generation (Path B)
- Brief prompts trigger workflow reuse (Path A)
- Specific parameters are extracted correctly (version="1.3", limit="20")
- Performance variations don't cause test failures

## Key Outcomes You Must Achieve

### Test Quality Improvements
- Replace simplified prompts with exact verbose north star examples
- Validate specific parameter values, not just presence
- Test complete pipelines, not isolated nodes
- Use real nodes from registry, not mock nodes

### Performance Handling
- Convert all performance assertions to warnings
- Never fail tests due to API timing variance
- Log performance issues for monitoring

### Path Selection Validation
- Ensure verbose prompts trigger `"not_found"` (Path B)
- Ensure brief prompts trigger `"found_existing"` (Path A)
- Validate confidence thresholds work correctly

## Implementation Strategy

### Phase 1: Update Existing Tests (2 hours)
1. Update `test_happy_path_mocked.py` with exact verbose prompts
2. Add parameter extraction validation assertions
3. Update `test_generator_north_star.py` with tertiary example
4. Convert performance failures to warnings

### Phase 2: Create New Tests (2 hours)
1. Create `test_north_star_realistic_e2e.py` in `llm/integration/`
2. Implement complete pipeline simulation
3. Add test registry helper for real nodes
4. Validate with production WorkflowValidator

### Phase 3: Validate and Document (1 hour)
1. Run all tests to ensure they pass
2. Document test patterns for future contributors
3. Update test README with north star approach

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### Exact Action Strings
```python
# These are verified from the codebase - use exactly
"found_existing"  # Path A (workflow reuse)
"not_found"      # Path B (workflow generation)
```

### Shared Store Keys
```python
# These are the exact keys used
shared["discovered_params"]["version"]  # Will be "1.3" (string)
shared["discovered_params"]["limit"]    # Will be "20" (string)
shared["found_workflow"]["name"]        # Will be "generate-changelog"
```

### Mock Response Format
```python
# Anthropic format is VERY specific
mock_response.json.return_value = {
    "content": [{
        "input": {
            "found": True,
            "workflow_name": "generate-changelog",
            "confidence": 0.95
        }
    }]
}
```

### Performance Warning Pattern
```python
import time
import logging

logger = logging.getLogger(__name__)

start = time.time()
# Run your test
result = do_test()
duration = time.time() - start

# NEVER DO THIS:
# assert duration < 20.0, f"Too slow: {duration}s"

# ALWAYS DO THIS:
if duration > 20.0:
    logger.warning(f"Slow performance: {duration:.2f}s (model-dependent)")
```

### WorkflowValidator Usage
```python
from pflow.core.workflow_validator import WorkflowValidator

# It's static - don't instantiate
errors = WorkflowValidator.validate(
    workflow_ir=workflow_ir,
    extracted_params=extracted_params,
    registry=registry,
    skip_node_types=False
)
```

## Critical Warnings from Experience

### The Mock Node Catastrophe
Task 28 found these non-existent nodes in tests:
- `claude-code` ❌ DOESN'T EXIST
- `github-list-prs` ❌ DOESN'T EXIST
- `slack-notify` ❌ DOESN'T EXIST

**Always verify nodes exist**:
```python
from pflow.registry import Registry
registry = Registry()
registry.load()
print(registry.get_nodes_metadata())  # See what actually exists
```

### The Performance Testing Disaster
Tests were failing because they took >20 seconds, but this was API variance:
- gpt-5-nano: 5-15 seconds
- Claude Sonnet: 20-40 seconds
- Network issues: 60+ seconds

**Never fail on performance. Always convert to warnings.**

### The Template Validation Trap
Generated workflows with required inputs fail validation because the validator checks if template variables have values at generation time:
```python
# This WILL fail validation
"inputs": {"file_path": {"required": True}}  # ${file_path} has no value yet!

# Use this instead
"inputs": {"file_path": {"required": False, "default": "output.md"}}
```

## Key Decisions Already Made

1. **MCP testing is deferred** - Skip MCP integration tests for now (separate future task)
2. **Use exact north star prompts** - Character-exact from architecture docs, no variations
3. **Performance as warnings only** - Never fail tests on timing
4. **Real nodes only** - No mock nodes unless absolutely unavoidable
5. **Test complete pipelines** - Not just isolated nodes
6. **Validate specific values** - "1.3" not just "version exists"

**📋 Note on Specifications**: The specification file (`task-57-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All three north star tiers tested with exact verbose prompts
- ✅ Parameter extraction validates "1.3" and "20" exactly
- ✅ Path A triggers on brief prompts (action="found_existing")
- ✅ Path B triggers on verbose prompts (action="not_found")
- ✅ Performance checks produce warnings, not failures
- ✅ Production WorkflowValidator used for validation
- ✅ No mock nodes when real nodes available
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)

## Common Pitfalls to Avoid

1. **Don't simplify the prompts** - Use exact character-precise north star examples
2. **Don't skip parameter validation** - Must validate "1.3" and "20" exactly
3. **Don't use non-existent nodes** - Always verify nodes exist in registry
4. **Don't fail on performance** - Convert all timing checks to warnings
5. **Don't test in isolation** - Simulate complete pipeline flow
6. **Don't trust easy tests** - If tests pass immediately, they're probably too easy

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple test updates won't conflict
2. **Identifies dependencies**: Discover what tests depend on what fixtures
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Existing Test Analysis**
   - Task: "Analyze test_happy_path_mocked.py to understand current test structure and identify what needs updating for north star prompts"
   - Task: "Examine test_generator_north_star.py to see what north star examples are already tested"

2. **Registry and Node Discovery**
   - Task: "Find all registered nodes that actually exist in the registry to avoid mock node issues"
   - Task: "Analyze how test_registry_data fixture works and what nodes it provides"

3. **Performance Pattern Analysis**
   - Task: "Search for performance assertions in planner tests that need converting to warnings"
   - Task: "Find existing patterns for logging warnings instead of asserting on timing"

4. **Parameter Validation Patterns**
   - Task: "Examine how discovered_params are validated in existing tests"
   - Task: "Find the exact format of parameter extraction in ParameterDiscoveryNode"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_57/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every test file to update/create
2. **Dependency mapping** - What fixtures and helpers are needed
3. **Risk identification** - What could break existing tests
4. **Testing strategy** - How you'll verify updates work correctly

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_57/implementation/progress-log.md`

```markdown
# Task 57 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
Reading Task 28's discoveries about test quality crisis...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Update `test_happy_path_mocked.py` with verbose prompts
2. Add parameter validation assertions
3. Convert performance failures to warnings
4. Update `test_generator_north_star.py` with tertiary example
5. Create new `test_north_star_realistic_e2e.py`
6. Run full test suite and fix issues
7. Document patterns for future contributors

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Updating test_happy_path_mocked.py
Replacing simplified prompts with exact north star examples...

Result: Tests now using realistic prompts
- ✅ What worked: Verbose prompts correctly trigger Path B
- ❌ What failed: Parameter extraction needed exact key names
- 💡 Insight: discovered_params uses strings not ints

Code that worked:
```python
assert shared["discovered_params"]["version"] == "1.3"  # String!
assert shared["discovered_params"]["limit"] == "20"     # String!
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
- Original plan: Expected "params" key
- Why it failed: Actually uses "discovered_params"
- New approach: Use correct key name
- Lesson: Always verify actual implementation
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what users actually do"

**North Star Test Philosophy**:
- Test verbose specifications for workflow generation
- Test brief commands for workflow reuse
- Validate specific parameter extraction
- Test complete pipelines, not isolated nodes

**Focus on quality over quantity**:
- 7 hard tests > 20 easy tests
- Each test should target a specific challenge
- If tests pass immediately, they're probably too easy

**What to test**:
- **Path selection**: Verbose → Path B, Brief → Path A
- **Parameter extraction**: Exact values like "1.3", "20"
- **Pipeline flow**: Complete discovery → generation → validation flow
- **Error handling**: Missing parameters, invalid workflows

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed parameter type issue
Parameters are extracted as strings, not integers.
"limit" is "20" not 20. This affects all parameter validation.
```

**Remember**: Tests that validate real user behavior > tests that just pass

## What NOT to Do

- **DON'T** simplify the north star prompts - Use them exactly as specified
- **DON'T** use mock nodes - Check registry for real nodes
- **DON'T** fail on performance - Always convert to warnings
- **DON'T** skip parameter validation - Check exact values
- **DON'T** test in isolation - Test complete pipelines
- **DON'T** add MCP tests - That's deferred to a future task

## Getting Started

1. Read all context files in order
2. Create your progress log
3. Deploy parallel subagents for context gathering
4. Create implementation plan
5. Start with `test_happy_path_mocked.py` updates
6. Run tests frequently: `pytest tests/test_planning/ -v`

## Final Notes

- The exact north star prompts are CHARACTER-PRECISE - don't change even one word
- Task 28 spent weeks discovering these issues - learn from their pain
- Performance varies 10x between models - that's why we use warnings
- The double "the" in triage prompt is intentional - it's in the original
- Parameter values are strings, not integers

## Remember

You're not just updating test prompts - you're fixing a fundamental test quality crisis where tests were passing but testing nothing real. The north star examples represent actual developer workflows that provide real value. By using exact verbose prompts and validating specific parameters, you're ensuring tests catch real bugs, not just achieve coverage.

This task directly impacts the reliability of pflow's natural language planner. Good tests here mean users get a system that actually understands their intent and generates appropriate workflows.

Think hard about test quality - it's better to have fewer tests that catch real issues than many tests that create false confidence!