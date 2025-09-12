# LLM Integration Tests

This directory contains integration tests that use real LLM API calls to validate the planner's functionality. These tests are critical for ensuring the planner works correctly with actual language models.

## Test Organization

The tests are organized by the planner's two main paths:

- **Path A (Reuse)**: Finding and reusing existing workflows
- **Path B (Generation)**: Creating new workflows from scratch

## Test Files (4 files, 22 tests total)

### test_path_b_generation_north_star.py (7 tests)

**Purpose**: Tests workflow GENERATION from natural language with comprehensive validation.

**What it validates**:
- Complete Path B flow including Task 52 enhancements (RequirementsAnalysis, Planning nodes)
- North Star examples (changelog, triage, issue summary) produce correct workflows
- 8-point validation on every generated workflow:
  1. Basic structure (node count, critical nodes presence)
  2. No hardcoded values (parameters properly templated)
  3. Template usage (no unused inputs declared)
  4. Node output references (data flow between nodes)
  5. Purpose field quality (descriptive, not generic)
  6. Linear workflow (no branching for MVP)
  7. Input validation (required params present, forbidden ones absent)
  8. Production WorkflowValidator validation

**Special tests**:
- Vague request detection (Task 52 feature)
- Impossible requirements detection (Task 52 feature)
- Parameter type validation (prevents integer bug from Task 57)
- Performance monitoring (ensures slow APIs don't fail tests)

**Run**: `RUN_LLM_TESTS=1 pytest test_path_b_generation_north_star.py -v -n auto`

### test_path_a_metadata_discovery.py (8 tests)

**Purpose**: Tests workflow DISCOVERY and REUSE through enhanced metadata.

**What it validates**:
- MetadataGenerationNode creates rich, searchable keywords
- Generated metadata enables workflow discovery
- Different query phrasings find the same workflow
- Search keywords are relevant to workflow purpose
- Metadata prevents duplicate workflows
- North Star examples generate appropriate metadata

**Key insights**:
- Tests that Path A (reuse) actually works after Path B (generation)
- Validates the full cycle: generate → save with metadata → discover later

**Run**: `RUN_LLM_TESTS=1 pytest test_path_a_metadata_discovery.py -v -n auto`

### test_production_planner_flow.py (5 tests)

**Purpose**: Tests the ACTUAL production planner as invoked by the CLI.

**What it validates**:
- The `create_planner_flow()` function works correctly
- Both Path A and Path B work through the production integration
- Workflows are properly saved and can be reused
- Parameter extraction works in production context
- Missing parameters are handled correctly
- Validation with extracted parameters succeeds

**Critical because**:
- This is exactly how the CLI invokes the planner
- Tests the real integration, not individual nodes
- Validates both paths converge at ParameterMappingNode
- Ensures the complete system works end-to-end

**Run**: `RUN_LLM_TESTS=1 pytest test_production_planner_flow.py -v -n auto`

### test_llm_not_mocked.py (2 tests)

**Purpose**: Meta-test that verifies real LLM is used in llm/ directories (not mocked).

**What it validates**:
- LLM is not mocked in llm/ test directories
- Real API calls are being made, not intercepted by mocks
- Mock boundaries are correctly configured
- The `mock_llm` fixture is not applied to LLM tests

**Why it matters**:
- Ensures our test isolation is working correctly
- Prevents false positives from accidentally mocked LLM tests
- Validates that tests in this directory actually test real LLM behavior

**Run**: `RUN_LLM_TESTS=1 pytest test_llm_not_mocked.py -v`

## Running the Tests

These tests require a configured LLM API key and are skipped by default.

### ⚠️ IMPORTANT: Always Use Parallel Execution

**All test files in this directory support parallel execution and SHOULD ALWAYS be run with `-n auto` flag** to significantly reduce execution time. These tests make independent LLM API calls and have no shared state between tests.

```bash
# RECOMMENDED: Run all LLM integration tests in parallel
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/ -v -n auto

# Run specific test suites IN PARALLEL (recommended)
RUN_LLM_TESTS=1 pytest test_path_b_generation_north_star.py -v -n auto  # ~45s with parallel vs ~170s sequential
RUN_LLM_TESTS=1 pytest test_path_a_metadata_discovery.py -v -n auto      # ~30s with parallel vs ~120s sequential
RUN_LLM_TESTS=1 pytest test_production_planner_flow.py -v -n auto        # ~40s with parallel vs ~150s sequential

# Sequential execution (ONLY for debugging specific failures)
RUN_LLM_TESTS=1 pytest test_path_b_generation_north_star.py -v  # NOT recommended for regular use

# Run a single test for debugging (sequential is fine here)
RUN_LLM_TESTS=1 pytest test_path_b_generation_north_star.py::TestPathBGenerationNorthStar::test_generate_changelog_north_star_primary -xvs
```

### Parallel Execution Benefits

- **Speed**: ~70% reduction in test execution time
- **Cost efficiency**: Faster feedback loop during development
- **No conflicts**: Each test creates its own `shared` dict and has no shared state
- **API friendly**: Distributes API calls across workers, avoiding rate limits

### Why These Tests Are Parallel-Safe

1. **Independent shared state**: Each test creates its own `shared = {}` dict
2. **No file conflicts**: Tests don't write to shared files
3. **Stateless nodes**: All planner nodes are stateless between executions
4. **No database**: No shared database connections or transactions
5. **Unique test data**: Each test uses distinct user inputs

## When to Run These Tests

- **Before releases**: Ensure both paths work with real LLMs
- **After prompt changes**: Validate prompts still produce correct outputs
- **After planner node changes**: Ensure the flow still works
- **After Task 52 changes**: RequirementsAnalysis and Planning nodes
- **Performance testing**: Monitor API response times

## Test Coverage

- **Path A specific**: 8 tests (metadata discovery)
- **Path B specific**: 7 tests (generation north star)
- **Both paths**: 5 tests (production flow)
- **Meta tests**: 2 tests (LLM not mocked)
- **Task 52 features**: Fully covered (requirements, planning, vague/impossible detection)
- **Edge cases**: Vague inputs, impossible requirements, missing parameters
- **Validation**: Comprehensive 8-point validation on all generated workflows

## Important Notes

1. **API Costs**: These tests make real API calls and incur costs
2. **Parallel Execution**: **ALWAYS use `-n auto`** - tests are designed for parallel execution (70% faster)
3. **Performance**: Tests use performance monitoring that warns but doesn't fail
4. **Determinism**: LLM responses can vary; tests are designed to be robust
5. **Comprehensive Validation**: Every generated workflow undergoes 8-point validation to ensure quality
6. **No Shared State**: Each test is completely independent, enabling safe parallel execution

## Key Test Scenarios

### North Star Examples
- **Changelog Generation**: GitHub issues → changelog → file → git commit
- **Issue Triage**: Fetch issues → categorize → report → commit
- **Issue Summary**: Simple single-issue summarization

### Edge Cases
- **Vague Requests**: "process the data" → clarification needed
- **Impossible Requirements**: Kubernetes/Slack → missing capabilities
- **Parameter Types**: Ensures all parameters are strings ("20" not 20)

### Production Scenarios
- **Path A Convergence**: Existing workflow → parameter extraction → execution
- **Path B Generation**: No workflow → generate → validate → save → execute
- **Missing Parameters**: Workflow needs params not in user input

## Debugging Tips

1. Use `-xvs` flags for detailed output and stop on first failure
2. Check `shared` dict contents for debugging state issues
3. Look for `_error` keys in exec results for LLM errors
4. Monitor `logger.info()` outputs for workflow details
5. Use `--tb=short` for concise tracebacks