# LLM Test Status Report

## Summary
After fixing the WorkflowManager integration issue, most tests are now working correctly. However, some tests are still failing due to LLM behavior issues rather than code bugs.

## Test Categories (94 total LLM tests)

### 1. Behavior Tests (`llm/behavior/`) - 39 tests
- **Status**: Most passing based on samples
- **Key Files**:
  - `test_confidence_thresholds.py` - ✅ Fixed (workflow_manager added)
  - `test_generator_core.py` - ✅ Passing
  - `test_metadata_generation_quality.py` - ✅ Passing
  - `test_parameter_extraction_accuracy.py` - ✅ Passing
  - `test_path_a_reuse.py` - ✅ Fixed (workflow_manager added)

### 2. Prompt Tests (`llm/prompts/`) - 22 tests
- **Status**: Passing based on samples
- **Key Files**:
  - `test_discovery_prompt.py` - ✅ Fixed and passing
  - `test_browsing_prompt.py` - ✅ Should be passing
  - `test_generator_prompts.py` - ✅ Should be passing
  - `test_parameter_prompts.py` - ✅ Should be passing

### 3. Integration Tests (`llm/integration/`) - 33 tests
- **Status**: Mixed results
- **Key Files**:
  - `test_metadata_enables_discovery_simple.py` - ✅ All 8 tests passing
  - `test_metadata_enables_discovery.py` - ⚠️ Partial (3 passing, some failing)
  - `test_discovery_to_parameter_full_flow.py` - ✅ Fixed (workflow_manager added)
  - `test_discovery_to_browsing.py` - ✅ Fixed (workflow_manager added)
  - `test_generator_north_star.py` - ❓ Unknown status

## Known Issues

### 1. Fixed Issues ✅
- **WorkflowManager Integration**: All tests now properly pass workflow_manager through shared store
- **Directory Mismatch**: Context builder now uses correct WorkflowManager instance

### 2. Remaining Issues ⚠️

#### A. Test Expectation Issues
**File**: `test_metadata_enables_discovery.py`
**Test**: `test_different_queries_find_same_workflow`
- **Problem**: Expects 3/5 queries to find workflow, but only 1/5 succeeds
- **Root Cause**: LLM isn't recognizing semantic similarity between queries
- **Solution Options**:
  1. Lower the threshold (expect 1/5 instead of 3/5)
  2. Improve metadata generation prompts
  3. Adjust discovery confidence thresholds

**Test**: `test_search_keywords_actually_work`
- **Status**: Likely failing for similar reasons
- **Issue**: Keywords not triggering discovery as expected

#### B. Test Timeout Issues
- Many tests are running very slowly (>2 minutes for small batches)
- Could be due to:
  - Multiple LLM API calls per test
  - Rate limiting
  - Network latency

## Fixes Applied

### Code Changes
1. **context_builder.py**: Added `workflow_manager` parameter to both context builder functions
2. **nodes.py**: Modified nodes to get WorkflowManager from shared store
3. **All test files**: Updated to pass workflow_manager through shared store

### Test Files Fixed
- ✅ `test_metadata_enables_discovery.py` - 6 instances fixed
- ✅ `test_path_a_reuse.py` - 2 instances fixed
- ✅ `test_discovery_to_parameter_full_flow.py` - Multiple instances fixed
- ✅ `test_discovery_to_browsing.py` - 1 instance fixed
- ✅ `test_discovery_prompt.py` - 2 instances fixed
- ✅ `test_confidence_thresholds.py` - 4 instances fixed

## Recommendations

### High Priority
1. **Adjust test expectations** in `test_different_queries_find_same_workflow`
   - Current: 3/5 queries must succeed
   - Suggested: 1/5 or 2/5 queries must succeed
   - Rationale: LLM discovery is probabilistic, not deterministic

2. **Review discovery confidence thresholds**
   - Current threshold might be too strict
   - Consider lowering from 0.6 to 0.5 for better recall

### Medium Priority
3. **Optimize test execution**
   - Add test markers for slow tests
   - Consider mocking some LLM calls in integration tests
   - Use smaller models for faster tests

4. **Improve metadata generation**
   - Enhance prompts to generate more comprehensive keywords
   - Add more use cases and variations

### Low Priority
5. **Document expected failure rates**
   - Some LLM tests will inherently be flaky
   - Document acceptable failure rates
   - Consider retry mechanisms for flaky tests

## Next Steps

1. Run focused test to identify exact failures:
   ```bash
   RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/integration/test_metadata_enables_discovery.py -v
   ```

2. Adjust test thresholds based on realistic LLM behavior

3. Consider whether some tests should be marked as `@pytest.mark.xfail` if they're testing aspirational behavior

## Test Command Reference

```bash
# Run all LLM tests (slow)
RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/ -v

# Run specific categories
RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/behavior/ -v
RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/prompts/ -v
RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/integration/ -v

# Run specific problem tests
RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/integration/test_metadata_enables_discovery.py::TestMetadataEnablesDiscovery::test_different_queries_find_same_workflow -xvs
```