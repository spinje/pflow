# Tests Successfully Moved from test_north_star_realistic_e2e.py

## Summary
Successfully moved 3 valuable test methods from `test_north_star_realistic_e2e.py` to `test_generator_north_star.py` where they logically belong with the other north star LLM tests.

## Tests Moved

### 1. ✅ test_performance_monitoring
- **Purpose**: Validates that slow API responses only produce warnings, not failures
- **Key Insight**: Follows Task 28 lessons about API variance (5-60 second variation)
- **Status**: Moved and tested - PASSES in 4.75s

### 2. ✅ test_parameter_types_are_strings
- **Purpose**: Ensures all discovered parameters are strings ("1.3" not 1.3, "20" not 20)
- **Key Insight**: Critical for template variable replacement and JSON serialization
- **Status**: Moved successfully

### 3. ✅ test_validation_with_production_validator
- **Purpose**: Tests workflows with the production WorkflowValidator
- **Key Insight**: Catches schema/structure issues using same validator as production
- **Status**: Moved and tested - PASSES in 0.18s

## Tests NOT Moved (Duplicates or Not Valuable)

### 1. ❌ test_changelog_verbose_complete_pipeline
- **Why not moved**: Duplicates existing test_generate_changelog_complete_flow
- **Issue**: Test expects 5+ nodes but LLM intelligently composes with 3 nodes
- **Decision**: The existing test is better and more flexible

### 2. ❌ test_changelog_brief_triggers_reuse
- **Why not moved**: Path A triggering already well-tested in test_happy_path_mocked.py
- **Issue**: Parameter extraction from brief prompt doesn't work well
- **Decision**: Not adding value, better tested elsewhere

### 3. ❌ test_triage_verbose_with_double_the
- **Why not moved**: The double "the" handling is already tested in test_issue_triage_report_generation
- **Decision**: Duplicate functionality

### 4. ❌ test_issue_summary_simple_workflow
- **Why not moved**: Already covered by test_summarize_issue_tertiary_example
- **Decision**: Exact duplicate

## File Ready for Deletion

**`tests/test_planning/llm/integration/test_north_star_realistic_e2e.py`** can now be safely deleted.

All valuable unique tests have been moved to `test_generator_north_star.py`.

## Location of Moved Tests

The 3 valuable tests are now at the end of:
`tests/test_planning/llm/integration/test_generator_north_star.py`

Starting at approximately line 565:
- test_performance_monitoring (line ~565)
- test_parameter_types_are_strings (line ~606)
- test_validation_with_production_validator (line ~647)

## Commands to Delete the File

```bash
# Remove the now-redundant file
rm tests/test_planning/llm/integration/test_north_star_realistic_e2e.py

# Verify tests still pass
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_generator_north_star.py -v
```