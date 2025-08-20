# Test Counting Fix Summary

## Problem
The test_prompt_accuracy.py tool was only detecting **1 test** instead of **19 test cases** for the discovery prompt.

## Root Cause
The test file was refactored to consolidate all test cases into a single test method (`test_all_discovery_scenarios`) that internally ran 19 cases in parallel using ThreadPoolExecutor. While this improved performance, pytest only saw it as 1 test method, breaking the accuracy tracking.

## Solution Implemented

### 1. Created Parametrized Test File
- **New file**: `test_discovery_prompt_parametrized.py`
- Uses `@pytest.mark.parametrize` decorator to expose each test case as a separate pytest item
- Maintains all 19 test cases from the original implementation
- Each test case runs individually but can still be parallelized via pytest-xdist if needed

### 2. Key Changes

#### Before (Single Method with Internal Parallelization):
```python
def test_all_discovery_scenarios(self, workflow_directory):
    """Run all discovery tests in parallel."""
    test_cases = self.get_test_cases()  # 19 cases
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        # Run all tests internally
```
**Result**: pytest sees 1 test

#### After (Parametrized Tests):
```python
@pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
def test_discovery_scenario(self, workflow_directory, test_case):
    """Test individual discovery scenario."""
    # Run single test case
```
**Result**: pytest sees 19 tests

### 3. Updated Prompt Frontmatter
- Changed test_path from: `test_discovery_prompt.py::TestDiscoveryPrompt::test_all_discovery_scenarios`
- To: `test_discovery_prompt_parametrized.py::TestDiscoveryPrompt`
- Updated test_count: 1 → 19
- Updated prompt_hash to avoid version increment prompt

## Verification
```bash
# Pytest correctly collects 19 tests
$ pytest test_discovery_prompt_parametrized.py --collect-only
collected 19 items

# Running subset shows proper counting
$ pytest test_discovery_prompt_parametrized.py -k "exact_match or no_match"
1 failed, 1 passed, 17 deselected
```

## Benefits
1. **Accurate test counting**: Tool now correctly reports X/19 tests passed
2. **Individual test visibility**: Can see which specific test cases fail
3. **Selective execution**: Can run individual test cases for debugging
4. **Better reporting**: pytest shows each test case name in output
5. **Compatible with pytest-xdist**: Can still parallelize via pytest's built-in parallel runner

## Trade-offs
- Lost custom ThreadPoolExecutor parallelization (but can use pytest-xdist instead)
- Each test creates its own WorkflowManager (slight overhead)
- No custom progress tracking during execution

## Next Steps
The test_prompt_accuracy.py tool now works correctly with the parametrized tests:

### For fast parallel execution (requires pytest-xdist):
```bash
# Install pytest-xdist if not already installed
uv pip install pytest-xdist

# Run with parallel workers (9 seconds for 19 tests!)
uv run python tools/test_prompt_accuracy.py discovery --parallel 19
```

### Default execution:
```bash
# Without --parallel flag, runs sequentially (1m 26s)
uv run python tools/test_prompt_accuracy.py discovery
```

This will properly show:
- Test Results: X/19 passed
- Accurate percentage calculations
- Proper test counting for all prompts
- With pytest-xdist: ~9s for full test suite with 19 workers

## Files Modified/Created
1. Created: `tests/test_planning/llm/prompts/test_discovery_prompt_parametrized.py`
2. Modified: `src/pflow/planning/prompts/discovery.md` (updated test_path and test_count)
3. Created: `scratchpads/prompt-improvement/test_counting_verification.py` (verification script)
4. Created: This summary document