# Comprehensive Report: Discovery Prompt Testing Infrastructure Improvements

## Executive Summary

This report documents the complete journey of improving the discovery prompt testing infrastructure, addressing critical issues with GPT model compatibility, parallel test execution, and performance optimization. Through systematic debugging and refactoring, we achieved:

- **3x faster test execution** (57s → 20s)
- **Fixed GPT model temperature incompatibility**
- **Solved parallel execution thread safety issues**
- **Consolidated test structure for maintainability**

## Part 1: Initial State and Problem Discovery

### Starting Conditions
- **14 test cases** for discovery prompt (from previous work documented in `discovery-test-implementation-journey.md`)
- **57% accuracy** on discovery decisions (8/14 tests passing)
- **Parallel execution working** for Claude models but failing for GPT models
- **Test execution time**: 57.79 seconds total

### Critical Issues Identified

1. **GPT Model Temperature Incompatibility**
   - GPT models like `gpt-5-nano` don't support `temperature=0.0`
   - Planning nodes hardcode `temperature=0.0` in their params
   - Tests failed with temperature-related errors

2. **Parallel Execution Problems**
   - Worker threads couldn't access monkey-patched functions
   - Infinite recursion when applying model overrides
   - Plugin loading issues in ThreadPoolExecutor workers

3. **Performance Bottleneck**
   - 3 test methods running sequentially
   - Only first method used parallel execution
   - Total time: 57.79s despite parallel capability

## Part 2: Temperature Fix Implementation

### The Challenge
When `PFLOW_TEST_MODEL=gpt-5-nano` was set, tests failed because:
1. GPT models require default temperature or no temperature parameter
2. Multiple layers of fixes conflicted (conftest.py, llm_helpers.py, worker threads)
3. Thread isolation prevented sharing of monkey-patches

### Solution Architecture

#### Layer 1: Conftest.py Enhancement
```python
# Added temperature handling to model override
DEFAULT_TEMP_ONLY_MODELS = {"gpt-5-nano", "gpt-5-mini", "gpt-5", "gpt-4o-mini"}

def wrapped_prompt(*args, **kwargs):
    # Remove temperature for incompatible models
    for prefix in DEFAULT_TEMP_ONLY_MODELS:
        if prefix in actual_model.lower() and 'temperature' in kwargs:
            del kwargs['temperature']
            break
    return original_prompt(*args, **kwargs)
```

#### Layer 2: Recursion Prevention
```python
# Added recursion guard to prevent infinite loops
_in_redirect = {"value": False}

def wrapped_get_model(model_name: str, **kwargs):
    if _in_redirect["value"]:
        return original_get_model(model_name, **kwargs)

    # Only redirect if model names differ
    if override_model and model_name != override_model:
        actual_model = override_model
```

#### Layer 3: Thread-Local Setup
```python
# Each worker thread loads plugins independently
def run_single_test(...):
    import llm
    # Force plugin loading for ALL plugins in this thread
    llm.pm.load_setuptools_entrypoints()

    # Apply model override if needed
    if override_model and not hasattr(llm.get_model, '_thread_patched'):
        # Thread-specific monkey-patch
```

### Key Insights

1. **Plugin Architecture**: The `llm` library uses lazy plugin loading, requiring explicit initialization in each thread
2. **Monkey-Patch Scope**: Session-level fixtures don't propagate to worker threads
3. **Model Variations**: Different models have different constraints (temperature, response format)

## Part 3: Parallel Execution Optimization

### Performance Analysis

#### Time Breakdown (Original)
- **test_discovery_comprehensive_parallel**: 17.8s (14 tests parallel)
- **test_performance_benchmark**: ~25s (5 tests sequential)
- **test_empty_workflow_context**: ~10s (1 test)
- **Setup/teardown**: ~5s
- **Total**: 57.79s

The critical discovery: pytest runs test **methods** sequentially, not in parallel!

### Refactoring Strategy

#### Consolidation Approach
1. **Merged all tests into single method**: `test_all_discovery_scenarios`
2. **Added 5 performance cases** to existing test cases
3. **Removed redundant methods** that ran sequentially
4. **Updated timeout thresholds** (10s → 20s for GPT models)

#### Implementation
```python
def get_test_cases(self) -> List[TestCase]:
    return [
        # Core tests (4)
        # Ambiguous tests (4)
        # Edge cases (3)
        # Multiple matches (1)
        # Synonyms (2)
        # NEW: Performance benchmarks (5)
        TestCase("perf_changelog", "generate changelog", ...),
        TestCase("perf_analyze", "analyze data", ...),
        # ... etc
    ]

def test_all_discovery_scenarios(self, workflow_directory):
    """Single test method running all 19 cases in parallel"""
```

### Results

#### Performance Improvement
- **Before**: 57.79 seconds (3 methods sequential)
- **After**: ~18-20 seconds (1 method, all parallel)
- **Speedup**: **3x faster**

#### Scalability Analysis
- With 15 workers and 19 tests: ~18s (limited by slowest test)
- With 5 workers: ~40s (some serialization)
- With 20 workers: ~18s (no additional benefit)

## Part 4: Test Quality and Coverage

### Current Test Distribution
- **Core behaviors**: 4 tests (basic functionality)
- **Ambiguous cases**: 4 tests (hard decisions)
- **Edge cases**: 3 tests (unusual patterns)
- **Multiple matches**: 1 test (conflict handling)
- **Synonyms**: 2 tests (terminology variations)
- **Performance**: 5 tests (speed benchmarks)
- **Total**: 19 comprehensive test cases

### Accuracy Results with GPT-5-nano
- **Overall**: 29% (needs prompt improvement)
- **Categories**:
  - Core: 25% (1/4)
  - Ambiguous: 0% (0/4)
  - Edge: 33% (1/3)
  - Multiple: 100% (1/1)
  - Synonyms: 50% (1/2)

### Key Findings
1. **Confidence calibration issues**: Model returns 0.6-0.65 when expecting <0.4
2. **Parameter strictness**: Rejects valid variations
3. **Ambiguity handling**: Struggles with unclear intent

## Part 5: Lessons Learned

### Technical Insights

1. **Thread Safety in Python Testing**
   - ThreadPoolExecutor doesn't copy execution context
   - Each thread needs explicit initialization
   - Monkey-patches don't propagate automatically

2. **LLM API Performance Reality**
   - Individual calls: 3-17 seconds
   - Parallel execution crucial for multiple tests
   - Rate limiting affects high parallelism

3. **Test Infrastructure Design**
   - Consolidate related tests into single parallel execution
   - Avoid sequential test methods for LLM tests
   - Use environment variables for configuration

### Best Practices Established

1. **Model Override Pattern**
   ```bash
   PFLOW_TEST_MODEL=gpt-5-nano  # Override for cost/speed
   PARALLEL_WORKERS=15           # Optimize parallelism
   RUN_LLM_TESTS=1              # Explicit opt-in
   ```

2. **Temperature Compatibility**
   - Maintain list of models requiring special handling
   - Remove temperature parameter rather than modifying
   - Apply fixes at lowest possible layer

3. **Performance Optimization**
   - Parallel execution is essential (10x speedup)
   - Consolidate tests to minimize overhead
   - Set realistic timeouts (20s for GPT models)

## Part 6: Future Recommendations

### Immediate Actions
1. **Improve discovery prompt** to handle ambiguous cases better
2. **Add confidence calibration** instructions
3. **Relax parameter matching** strictness

### Infrastructure Enhancements
1. **Consider pytest-xdist** for method-level parallelism
2. **Implement response caching** for development
3. **Add cost tracking** for LLM API usage

### Testing Strategy
1. **Use cheaper models** (claude-3-haiku) for development
2. **Run comprehensive tests** before merging
3. **Monitor accuracy trends** over time

## Conclusion

This work transformed the discovery prompt testing infrastructure from a slow, GPT-incompatible system to a fast, robust, multi-model testing framework. The 3x performance improvement (57s → 20s) makes iterative prompt development feasible, while the temperature fix enables testing with diverse models.

The key breakthrough was understanding that effective parallel testing requires careful attention to thread isolation, plugin architecture, and test organization. By consolidating tests and fixing thread-safety issues, we created a sustainable testing framework that will accelerate future prompt improvements.

## Files Created/Modified

### New Files
- `test_temperature_fix.py` - Temperature fix verification
- `test_parallel_temperature_fix.py` - Parallel execution test
- `test_refactored_parallel.py` - Refactoring verification
- `discovery-test-analysis.md` - Test failure analysis
- `parallel-testing-results.md` - Performance analysis
- This report - Comprehensive documentation

### Modified Files
- `/tests/test_planning/llm/prompts/conftest.py` - Added temperature fix and recursion prevention
- `/tests/test_planning/llm/prompts/test_discovery_prompt.py` - Consolidated tests, fixed threading
- `/src/pflow/planning/prompts/discovery.md` - Updated test path

### Key Metrics
- **Test execution time**: 57.79s → ~20s (3x improvement)
- **Test count**: 19 comprehensive cases
- **Model compatibility**: Claude + GPT models
- **Parallel workers**: Optimized at 10-15 workers

The infrastructure is now ready for rapid iteration on prompt improvements, with the goal of achieving >90% accuracy on core behaviors and >70% on ambiguous cases.