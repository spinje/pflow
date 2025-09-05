# Feature: update_planner_tests_north_star

## Objective

Update planner tests using exact north star prompts.

## Requirements

- Must use exact verbose prompts from `architecture/vision/north-star-examples.md`
- Must validate specific parameter extraction values
- Must test Path A vs Path B selection
- Must convert performance failures to warnings
- Must use real nodes from registry
- Must simulate complete pipeline with parameter transformation

## Scope

- Does not test MCP integration
- Does not create new north star examples
- Does not modify planner implementation
- Does not change test directory structure

## Inputs

- `north_star_examples`: dict - Verbose and brief prompts from architecture docs
  - `primary_verbose`: str - Full changelog generation prompt
  - `primary_brief`: str - Brief changelog reuse prompt
  - `secondary_verbose`: str - Full triage report prompt
  - `secondary_brief`: str - Brief triage reuse prompt
  - `tertiary`: str - Simple issue summary prompt
- `test_files`: list[str] - Files requiring updates
  - `tests/test_planning/integration/test_happy_path_mocked.py`
  - `tests/test_planning/llm/integration/test_generator_north_star.py`
  - `tests/test_planning/llm/integration/test_north_star_realistic_e2e.py` (new)

## Outputs

Returns: Updated test suite with north star examples
Side effects:
- Modified test files with verbose prompts
- New test file for complete pipeline testing
- Test assertions for specific parameter values
- Performance warnings instead of failures

## Structured Formats

```json
{
  "test_cases": {
    "changelog_verbose": {
      "input": "generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes.",
      "expected_path": "B",
      "expected_action": "not_found",
      "expected_params": {
        "version": "1.3",
        "limit": "20",
        "branch": "create-changelog-version-1.3",
        "path": "versions/1.3/CHANGELOG.md"
      }
    },
    "changelog_brief": {
      "input": "generate a changelog for version 1.4",
      "expected_path": "A",
      "expected_action": "found_existing",
      "workflow_match": "generate-changelog"
    }
  },
  "shared_store_keys": {
    "discovered_params": "discovered_params",
    "found_workflow": "found_workflow",
    "user_input": "user_input",
    "planning_context": "planning_context",
    "browsed_components": "browsed_components"
  },
  "validation": {
    "validator_import": "from pflow.core.workflow_validator import WorkflowValidator",
    "validator_call": "WorkflowValidator.validate(workflow_ir, extracted_params, registry)",
    "performance_timeout_ms": 20000,
    "performance_is_warning": true
  }
}
```

## State/Flow Changes

- `test_running` → `test_passed` when assertions succeed
- `test_running` → `test_failed` when assertions fail
- `performance_slow` → `warning_logged` when duration > 20s

## Constraints

- Verbose prompts must be character-exact from architecture docs
- Parameter keys must match ParameterDiscoveryNode output format
- Performance checks must not cause test failures
- Test files in llm/ subdirectories require RUN_LLM_TESTS=1

## Rules

1. Use exact verbose prompt for changelog generation from north star docs
2. Use exact verbose prompt for triage report from north star docs
3. Use exact simple prompt for issue summary from north star docs
4. Assert shared["discovered_params"]["version"] equals "1.3" exactly
5. Assert shared["discovered_params"]["limit"] equals "20" exactly
6. Assert "create-changelog-version-1.3" in str(shared["discovered_params"].values())
7. Convert performance assertions to logger.warning calls
8. Call WorkflowValidator.validate() statically with workflow_ir and registry
9. Use test_registry_data fixture from conftest.py for mock tests
10. Use MetadataGenerationNode._transform_user_input_with_parameters for transformation
11. Assert action equals "found_existing" for Path A
12. Assert action equals "not_found" for Path B
13. Place new e2e test in tests/test_planning/llm/integration/

## Edge Cases

- Prompt with 1 word difference → Path B should still trigger
- Performance takes 30 seconds → warning logged, test passes
- Parameter value "twenty" instead of "20" → test fails
- Missing shared["discovered_params"] → test fails
- Mock node in workflow → use test_registry_data fixture

## Error Handling

- Missing north star workflow → create fixture with exact structure
- Registry missing node → use test_registry_data fixture
- Parameter transformation missing → use _transform_user_input_with_parameters
- Validation fails → check skip_node_types parameter

## Non-Functional Criteria

- Test execution time < 60 seconds total
- Memory usage < 500MB per test
- Parallel test execution supported
- RUN_LLM_TESTS flag respected for llm/ tests

## Examples

### Verbose prompt test case
```python
def test_changelog_verbose_path_b(self):
    shared = {
        "user_input": "generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."
    }
    # Run discovery node
    node = WorkflowDiscoveryNode()
    action = node.run(shared)

    # Should trigger Path B
    assert action == "not_found"
    assert shared["discovered_params"]["version"] == "1.3"
    assert shared["discovered_params"]["limit"] == "20"
```

### Brief prompt test case
```python
def test_changelog_brief_path_a(self):
    shared = {"user_input": "generate a changelog for version 1.4"}
    # Run discovery node
    node = WorkflowDiscoveryNode()
    action = node.run(shared)

    # Should trigger Path A
    assert action == "found_existing"
    assert shared["found_workflow"]["name"] == "generate-changelog"
```

### Performance warning
```python
import time
import logging

logger = logging.getLogger(__name__)

start = time.time()
# Run test
duration = time.time() - start
if duration > 20.0:
    logger.warning(f"Slow performance: {duration:.2f}s (model-dependent)")
    # Do NOT raise assertion error
```

## Test Criteria

1. test_happy_path_mocked.py contains exact verbose prompts
2. test_generator_north_star.py includes tertiary example
3. shared["discovered_params"]["version"] equals "1.3"
4. shared["discovered_params"]["limit"] equals "20"
5. shared["discovered_params"] contains "create-changelog-version-1.3" in values
6. Performance > 20s produces logger.warning not AssertionError
7. action equals "found_existing" for brief prompts
8. action equals "not_found" for verbose prompts
9. test_north_star_realistic_e2e.py exists in llm/integration/
10. WorkflowValidator.validate() called statically
11. test_registry_data fixture used for mocked tests
12. _transform_user_input_with_parameters used for transformation
13. All three north star tiers tested

## Notes (Why)

- Exact prompts ensure tests match real user behavior
- Task 28 found 69% of tests used fake nodes creating false confidence
- Performance varies 10x between models so must not fail tests
- Verbose first-time prompts trigger generation, brief prompts trigger reuse
- Static WorkflowValidator avoids instantiation complexity

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 1                          |
| 3      | 2                          |
| 4      | 3                          |
| 5      | 4                          |
| 6      | 5                          |
| 7      | 6                          |
| 8      | 10                         |
| 9      | 11                         |
| 10     | 12                         |
| 11     | 7                          |
| 12     | 8                          |
| 13     | 9                          |

## Versioning & Evolution

- v1.0.0 — Initial specification for north star test updates
- v1.0.1 — Verified all implementation details against codebase

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes exact north star prompts are finalized in architecture docs
- Assumes discovered parameter keys will match expected names
- Unknown if all parameter values will be strings or could be other types

### Conflicts & Resolutions

- Task 28 lessons vs current test structure — Resolution: Apply Task 28 patterns incrementally
- MCP testing scope — Resolution: Deferred per user decision to separate task
- Test location ambiguity — Resolution: Verified llm/integration/ for real LLM tests

### Decision Log / Tradeoffs

- Chose exact string matching for critical params over fuzzy matching for precision
- Chose warnings over failures for performance to handle model variance
- Chose static WorkflowValidator methods over instantiation for simplicity
- Chose existing test_registry_data fixture over creating new helper

### Ripple Effects / Impact Map

- Affects all planner integration tests
- May reveal issues in parameter extraction logic
- Could expose gaps in workflow discovery matching
- Tests in llm/ directory require RUN_LLM_TESTS environment variable

### Residual Risks & Confidence

- Risk: Tests may be brittle to prompt variations; Mitigation: Document exact requirements
- Risk: Parameter types may not match expectations; Mitigation: Use str() for comparisons
- Confidence: Very High after codebase verification

### Epistemic Audit (Checklist Answers)

1. All implementation details now verified against actual code
2. Wrong action strings would cause immediate test failures
3. Prioritized test realism over test simplicity
4. All rules mapped to test criteria with verified details
5. Changes touch planner test suite only
6. No remaining uncertainty on implementation details; Confidence: Very High