# Test Plan for Task 27 - Planner Debugging

## Overview

Write comprehensive tests for the planner debugging capabilities. Tests should verify that debugging doesn't break existing functionality while adding visibility.

**IMPORTANT**: The test infrastructure has been refactored. Tests now mock at the LLM level, not the module level. This means:
- You can import from `pflow.planning.debug` normally
- You can patch specific functions without issues
- The `mock_llm_responses` fixture handles LLM mocking automatically
- No need to worry about module state pollution

## Test Files to Create

1. `tests/test_planning/test_debug.py` - Unit tests for debug module
2. `tests/test_planning/test_debug_integration.py` - Integration tests with planner
3. `tests/test_cli/test_debug_flags.py` - CLI flag tests
4. `tests/test_planning/test_debug_utils.py` - Utility function tests

## 1. Unit Tests (`tests/test_planning/test_debug.py`)

### Test DebugWrapper

```python
def test_debug_wrapper_delegates_attributes():
    """Wrapper should delegate all unknown attributes to wrapped node"""
    # Create a mock node with custom attributes
    # Wrap it with DebugWrapper
    # Verify accessing custom attributes works
    # Verify successors is preserved

def test_debug_wrapper_handles_special_methods():
    """Wrapper should handle __copy__ and __deepcopy__ without recursion"""
    # Create wrapper
    # Test copy.copy(wrapper) doesn't cause recursion
    # Test copy.deepcopy(wrapper) doesn't cause recursion
    # Verify copied wrapper still works

def test_debug_wrapper_preserves_node_lifecycle():
    """Wrapper should call prep, exec, post correctly"""
    # Create mock node with prep, exec, post methods
    # Wrap it and call _run()
    # Verify all methods called in order
    # Verify return values passed through

def test_debug_wrapper_records_progress():
    """Wrapper should call progress callbacks"""
    # Create mock progress object
    # Wrap node and execute
    # Verify on_node_start called with node name
    # Verify on_node_complete called with duration

def test_debug_wrapper_handles_exceptions():
    """Wrapper should record exceptions and re-raise"""
    # Create node that raises in exec()
    # Wrap and execute
    # Verify exception recorded in trace
    # Verify exception re-raised

def test_debug_wrapper_intercepts_llm_calls(mock_llm_responses):
    """Wrapper should intercept LLM calls when model_name in prep_res"""
    # Use mock_llm_responses fixture to configure LLM response
    # Create node that uses LLM (model_name in prep_res)
    # Execute wrapped node
    # Verify LLM prompt/response recorded
    # Verify original methods restored
```

### Test TraceCollector

```python
def test_trace_collector_records_node_execution():
    """Should record node execution with timing"""
    # Create TraceCollector
    # Record several node executions
    # Verify all recorded with correct structure

def test_trace_collector_detects_path():
    """Should detect Path A vs Path B based on nodes"""
    # Test Path A: No ComponentBrowsingNode
    # Test Path B: Has ComponentBrowsingNode
    # Verify path_taken set correctly

def test_trace_collector_records_llm_calls():
    """Should record LLM request/response pairs"""
    # Record request
    # Record response
    # Verify paired correctly in llm_calls

def test_trace_collector_saves_to_file():
    """Should save valid JSON to correct location"""
    # Use tmp_path fixture
    # Add some data
    # Save to file
    # Verify file exists
    # Verify JSON is valid
    # Verify all data present

def test_trace_collector_handles_non_serializable():
    """Should handle non-JSON-serializable objects"""
    # Add objects that can't serialize (e.g., datetime)
    # Save to file
    # Verify uses default=str
```

### Test PlannerProgress

```python
def test_planner_progress_formats_node_names():
    """Should map node names to display names with emojis"""
    # Test each known node
    # Verify correct emoji and display name

def test_planner_progress_shows_duration():
    """Should format duration correctly"""
    # Test on_node_complete with various durations
    # Verify format like "✓ 2.1s"
```

## 2. Integration Tests (`tests/test_planning/test_debug_integration.py`)

### Test with Real Planner Flow

```python
def test_wrapped_planner_executes_successfully(mock_llm_responses):
    """Wrapped planner should still execute correctly"""
    # Configure mock_llm_responses for planner nodes
    # Create planner flow with debug wrapping
    # Execute with simple input
    # Verify planner_output is successful
    # Verify trace data collected

def test_progress_output_during_execution(capsys):
    """Should see progress output in terminal"""
    # Execute wrapped planner
    # Capture output with capsys
    # Verify progress messages appear
    # Verify format is correct

def test_timeout_detection():
    """Should detect timeout after specified duration

    NOTE: Python limitation - timeout is detected AFTER completion, not during.
    """
    # Mock a node to sleep for long time
    # Execute with 1 second timeout
    # Run planner (will complete despite timeout)
    # Verify timeout detected AFTER completion
    # Verify trace saved
    # Verify timeout message shown

def test_trace_saved_on_failure():
    """Should automatically save trace when planner fails"""
    # Make planner fail (e.g., invalid input)
    # Verify trace file created
    # Verify error recorded in trace

def test_trace_saved_with_flag():
    """Should save trace when --trace flag provided"""
    # Execute with trace=True
    # Verify successful execution
    # Verify trace still saved

def test_llm_calls_captured_in_trace():
    """Should capture all LLM prompts and responses"""
    # Execute planner that makes LLM calls
    # Load trace file
    # Verify llm_calls contains entries
    # Verify prompts are complete
    # Verify responses captured
```

### Test Path Detection

```python
def test_path_a_detection():
    """Should detect Path A (workflow reuse)"""
    # Set up workflow that will be found
    # Execute planner
    # Verify trace shows path_taken = "A"

def test_path_b_detection():
    """Should detect Path B (generation)"""
    # Use input that won't match existing
    # Execute planner
    # Verify trace shows path_taken = "B"
```

## 3. CLI Tests (`tests/test_cli/test_debug_flags.py`)

### Test CLI Flags

```python
def test_trace_flag_added():
    """--trace flag should be available"""
    # Invoke CLI with --help
    # Verify --trace in output

def test_planner_timeout_flag_added():
    """--planner-timeout flag should be available"""
    # Invoke CLI with --help
    # Verify --planner-timeout in output

def test_trace_flag_creates_file(tmp_path):
    """Using --trace should create trace file"""
    # Mock planner execution
    # Run CLI with --trace
    # Verify trace file created

def test_timeout_flag_respected():
    """--planner-timeout should set timeout duration"""
    # Mock slow planner
    # Run with --planner-timeout 2
    # Verify times out after 2 seconds

def test_trace_dir_flag():
    """--trace-dir should change trace location"""
    # Run with --trace-dir /custom/path
    # Verify trace saved to custom path
```

### Test Environment Variables

```python
def test_env_var_trace_always(monkeypatch):
    """PFLOW_TRACE_ALWAYS=1 should always save traces"""
    # Set environment variable
    # Execute without --trace
    # Verify trace still saved

def test_env_var_timeout(monkeypatch):
    """PFLOW_PLANNER_TIMEOUT should set default timeout"""
    # Set environment variable
    # Execute without --planner-timeout
    # Verify uses env var value
```

## 4. Debug Utilities Tests (`tests/test_planning/test_debug_utils.py`)

Test the utility functions from code-implementer:

```python
def test_save_trace_to_file():
    """Test trace file saving"""
    # Test with valid data
    # Test with permission error
    # Test with non-serializable objects

def test_format_progress_message():
    """Test progress message formatting"""
    # Test all node types
    # Test with/without duration
    # Test unknown nodes

def test_create_llm_interceptor():
    """Test LLM interception helper"""
    # Create interceptor
    # Mock llm.get_model
    # Verify callbacks called
    # Verify restoration works
```

## Critical Test Scenarios

### Must Test:
1. **Wrapper doesn't break nodes** - Most critical
2. **Timeout detection works** - User-facing feature
3. **Trace files are valid JSON** - Needed for debugging
4. **LLM calls are captured** - Core debugging need
5. **Progress shows in terminal** - User experience

### Edge Cases:
1. Node with no `name` attribute - Should use class name
2. Large trace files - Should still save
3. Non-writable trace directory - Should show error
4. Timeout during LLM call - Should detect after completion
5. Multiple planner executions - Each gets own trace

## Test Fixtures Needed

```python
@pytest.fixture
def mock_node():
    """Create a mock PocketFlow node"""
    class MockNode:
        def __init__(self):
            self.successors = {}
            self.params = {}
        def prep(self, shared):
            return {"model_name": "test"}
        def exec(self, prep_res):
            return {"result": "test"}
        def post(self, shared, prep_res, exec_res):
            return "complete"
        def _run(self, shared):
            # Simulate PocketFlow's _run
            p = self.prep(shared)
            e = self.exec(p)
            return self.post(shared, p, e)
    return MockNode()

# NOTE: The mock_llm_responses fixture is already provided globally
# No need to create your own LLM mock - use the existing one:
def test_example(mock_llm_responses):
    """Example of using the global LLM mock"""
    mock_llm_responses.set_response(
        "anthropic/claude-sonnet-4-0",
        SomeSchema,
        {"key": "value"}
    )
```

## Success Criteria

- [ ] All tests pass
- [ ] No existing planner tests break
- [ ] Coverage > 90% for debug.py
- [ ] Integration tests verify real usage
- [ ] CLI tests verify flags work
- [ ] Edge cases handled gracefully

## Notes for Test Writer

1. **Use tmp_path fixture** for file operations
2. **Mock time.time()** for consistent durations
3. **Use capsys/caplog** to verify output
4. **Mock the planner** for CLI tests (don't run real planner)
5. **Test both success and failure paths**