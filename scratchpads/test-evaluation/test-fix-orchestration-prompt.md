# Test Suite Quality Fix - Master Orchestration Prompt

## Your Mission

You are the master orchestrator for fixing all quality issues in the pflow test suite. Based on our comprehensive evaluation that found 287 anti-patterns across 779 tests, you will systematically deploy specialized test-implementation agents to fix each test directory.

## Context

We've completed a thorough evaluation of the test suite and found:
- Average quality score: 26.3/40 (Good, but needs improvement)
- 287 total anti-patterns
- ~35% of tests suffer from excessive mocking
- ~45% test implementation instead of behavior

Detailed reports are available at:
- **Consolidated Report**: `/Users/andfal/projects/pflow/scratchpads/test-evaluation/consolidated-report.md`
- **Test-Writer-Fixer Agent Instructions**: `/Users/andfal/projects/pflow/scratchpads/test-evaluation/test-implementation-agent-prompt.md`
- **Individual Directory Reports**:
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/cli-tests-report.md`
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/registry-tests-report.md`
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/runtime-tests-report.md`
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/planning-tests-report.md`
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/nodes-tests-report.md`
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/integration-tests-report.md`
  - `/Users/andfal/projects/pflow/scratchpads/test-evaluation/core-tests-report.md`

## Process Instructions

### 1. Initialize Task Tracking

First, use TodoWrite to create a task list for all directories that need fixing, ordered by priority (worst performing first):

```
1. test_cli (20/40) - Heavy mocking, implementation testing
2. test_registry (18/40) - Tests internals, excessive granularity
3. test_runtime (21/40) - Mocks PocketFlow components
4. test_planning (27/40) - Over-mocking, no LLM testing
5. test_nodes (27/40) - Generally good but some issues
6. test_integration (30.3/40) - Some tests mock too much
7. test_core (31.8/40) - Best quality, minor improvements only
```

**Directory to Report Mapping:**
| Directory | Report File |
|-----------|------------|
| test_cli | cli-tests-report.md |
| test_registry | registry-tests-report.md |
| test_runtime | runtime-tests-report.md |
| test_planning | planning-tests-report.md |
| test_nodes | nodes-tests-report.md |
| test_integration | integration-tests-report.md |
| test_core | core-tests-report.md |

### 2. For Each Directory (Sequentially)

Execute these steps for each directory, ONE AT A TIME:

#### Step 1: Update Todo Status
Mark the current directory as "in_progress" using TodoWrite.

#### Step 2: Deploy Test-Writer-Fixer Sub-Agent
Use the Task tool with subagent_type="general-purpose" and this template:

```
You are a specialized test-writer-fixer agent tasked with fixing all test quality issues in /Users/andfal/projects/pflow/tests/[DIRECTORY_NAME]/

Your system prompt with detailed instructions is at: /Users/andfal/projects/pflow/scratchpads/test-evaluation/test-implementation-agent-prompt.md

The specific issues for this directory are documented at: /Users/andfal/projects/pflow/scratchpads/test-evaluation/[REPORT_FILENAME]

Your task:
1. Read the test implementation instructions thoroughly
2. Read the specific report for this directory
3. Fix ALL issues identified in the report
4. Focus on the most critical issues first:
   - Remove excessive mocking
   - Test behavior, not implementation
   - Fix brittle assertions
   - Improve test names
   - Add missing test coverage

Specific issues to address:
[INSERT KEY ISSUES FROM REPORT]

Constraints:
- ONLY fix tests in this directory
- Run ONLY tests for files you modify (pytest path/to/specific_test.py)
- Do NOT run 'make test' or fix unrelated failures
- Preserve test coverage while improving quality
- Document significant changes in docstrings

Deliverables:
1. Summary of tests fixed
2. Count of anti-patterns removed
3. Any tests that couldn't be fixed and why
4. Confirmation that all modified tests pass
```

#### Step 3: Wait for Completion
Let the agent complete their work. They will provide a summary.

#### Step 4: Verify and Document
- Review the agent's summary
- Note key improvements made
- Document any issues that couldn't be fixed

#### Step 5: Update Todo Status
Mark the directory as "completed" using TodoWrite.

### 3. Error Handling

If an agent encounters issues:
- Document what went wrong
- Mark as "completed with issues"
- Continue to the next directory
- Include issues in final report

### 4. Quality Standards

Each test fix should achieve:
- **Behavior Testing**: Tests what users see, not how code works
- **Minimal Mocking**: Only external boundaries
- **Clear Names**: Describe what's being tested
- **Fast Execution**: <100ms for unit tests
- **Independent**: No shared state between tests
- **Meaningful Assertions**: Test outcomes, not calls

### 5. Final Report

After all directories are processed, create a comprehensive report at:
`/Users/andfal/projects/pflow/scratchpads/test-evaluation/test-fix-summary.md`

Include:
- Total tests modified
- Anti-patterns removed by type
- Directories completed successfully
- Any unfixed issues
- Overall quality improvement estimate
- Recommendations for maintaining quality

## Execution Checklist

- [ ] Initialize todo list with all directories
- [ ] Process each directory sequentially
- [ ] Deploy agents with specific reports
- [ ] Track progress systematically
- [ ] Handle errors gracefully
- [ ] Create final summary report

## Key Reminders

1. **Sequential, Not Parallel**: Process one directory at a time
2. **Focus on Quality**: Better to fix fewer tests well than many poorly
3. **Use Specific Reports**: Each agent needs their directory's report
4. **Track Everything**: Use todos for visibility
5. **Don't Break Working Tests**: Improve quality without losing coverage

## Example: First Directory (test_cli)

Here's exactly how to deploy the test-writer-fixer sub-agent for the first directory:

```python
# Using the Task tool:
Task(
    subagent_type="general-purpose",
    description="Fix test quality in test_cli",
    prompt="""
You are a specialized test-writer-fixer agent tasked with fixing all test quality issues in /Users/andfal/projects/pflow/tests/test_cli/

Your system prompt with detailed instructions is at: /Users/andfal/projects/pflow/scratchpads/test-evaluation/test-implementation-agent-prompt.md

The specific issues for this directory are documented at: /Users/andfal/projects/pflow/scratchpads/test-evaluation/cli-tests-report.md

Your task:
1. Read the test implementation instructions thoroughly
2. Read the specific report for this directory
3. Fix ALL issues identified in the report
4. Focus on the most critical issues first:
   - Remove excessive mocking
   - Test behavior, not implementation
   - Fix brittle assertions
   - Improve test names
   - Add missing test coverage

Specific issues to address:
- Excessive mocking (18 instances) - especially in stdin and integration tests
- Implementation testing (12 instances) - testing internals rather than behavior
- Poor isolation (8 instances) - complex dependencies between tests
- Missing coverage (9 instances) - no edge cases or error paths

Constraints:
- ONLY fix tests in the test_cli directory
- Run ONLY tests for files you modify (pytest tests/test_cli/specific_test.py)
- Do NOT run 'make test' or fix unrelated failures
- Preserve test coverage while improving quality
- Document significant changes in docstrings

Deliverables:
1. Summary of tests fixed
2. Count of anti-patterns removed
3. Any tests that couldn't be fixed and why
4. Confirmation that all modified tests pass
"""
)
```

## Start Execution

Begin by creating the todo list with all directories, then start with test_cli as it has the most issues.
