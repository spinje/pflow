# Task 57: Update planner tests to use better test cases with real world north star examples

## ID
57

## Title
Update planner tests to use better test cases with real world north star examples

## Description
Update the planner test suite to use realistic north star examples from `architecture/vision/north-star-examples.md` instead of simplified prompts. This ensures tests validate actual user behavior patterns where verbose first-time specifications trigger workflow generation (Path B) and brief commands trigger workflow reuse (Path A). The tests should validate specific parameter extraction and use exact prompts that real users would type.

## Status
in progress

## Dependencies
- Task 28: Improve performance of planner - Provides critical lessons about test quality, pipeline fidelity, and avoiding mock node pitfalls that created false confidence in workflow generator tests
- Task 33: Extract planner prompts to markdown files - Ensures prompts are properly extracted and testable
- Task 17: Implement Natural Language Planner System - The planner system that these tests will validate

## Priority
high

## Details
This task focuses on improving planner test quality by using realistic north star examples that represent actual developer workflows. The current tests use oversimplified prompts like `"generate a changelog"` instead of the verbose, detailed prompts users would actually type when creating new workflows.

### Key North Star Examples to Test
1. **Primary (Complex)**: Generate Changelog - Full GitHub → LLM → Git pipeline
   - Verbose: "generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."
   - Brief reuse: "generate a changelog for version 1.4"

2. **Secondary (Medium)**: Issue Triage Report - Analysis workflow
   - Verbose: "create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to triage-reports/2025-08-07-triage-report.md then commit the changes."
   - Brief reuse: "create a triage report for all open issues"

3. **Tertiary (Simple)**: Summarize Issue - Minimal but useful
   - "summarize github issue 1234"

### Critical Improvements Based on Task 28 Lessons
- **Use exact verbose prompts** from architecture docs, not simplified versions
- **Validate specific parameter extraction** (version="1.3", limit="20", branch="create-changelog-version-1.3")
- **Never fail tests on performance** - Convert timing checks to warnings (API speed varies 10x between models)
- **Use real nodes from registry** - Avoid mock nodes that hide issues (Task 28 found 69% of tests used non-existent nodes)
- **Simulate complete pipeline** - Include parameter transformation and all shared store states
- **Focus on test quality over quantity** - 7 hard tests > 20 easy tests

### Files to Update
1. `tests/test_planning/integration/test_happy_path_mocked.py` - Already has north star workflows but needs verbose prompts
2. `tests/test_planning/llm/integration/test_generator_north_star.py` - Needs exact prompts and tertiary example
3. Create new `test_north_star_realistic_e2e.py` for complete pipeline testing with exact prompts

### MCP Integration (Deferred)
Based on user decision, MCP testing will be handled in a separate future task. This allows focus on north star example quality without scope creep.

## Test Strategy
The testing approach emphasizes realistic scenarios that match actual user behavior:

### Unit/Integration Tests (Mocked LLM)
- Test Path A vs Path B selection based on prompt specificity
- Validate parameter extraction from verbose descriptions
- Ensure brief prompts correctly match existing workflows
- Use production `WorkflowValidator` for consistency

### LLM Tests (Real API calls when RUN_LLM_TESTS=1)
- Complete end-to-end flow with exact north star prompts
- Verify verbose prompts generate appropriate workflows with 6+ nodes
- Test parameter mapping convergence for both paths
- Validate workflow structure matches expected patterns

### Key Test Scenarios
- **Prompt specificity boundaries**: When does vague become specific enough for Path B?
- **Parameter extraction accuracy**: Are all values correctly identified (1.3, 20, paths)?
- **Workflow reusability**: Do brief prompts find the right existing workflows?
- **Test quality metrics**: Each test should target a specific challenge, not test obvious cases