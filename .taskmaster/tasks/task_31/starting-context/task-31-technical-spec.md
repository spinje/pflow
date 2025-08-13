# Task 31: Technical Specification

## Refactor Test Infrastructure - Mock at LLM Level

### 1. Architecture Overview

```
Current Architecture (BROKEN):
┌──────────────────────────────┐
│         Test Suite           │
├──────────────────────────────┤
│    MockPlanningModule        │ ← Complex mock with sys.modules manipulation
├──────────────────────────────┤
│     pflow.planning.*         │ ← Partially mocked, causes state pollution
├──────────────────────────────┤
│      llm.get_model()         │ ← Actual external dependency
└──────────────────────────────┘

New Architecture (CLEAN):
┌──────────────────────────────┐
│         Test Suite           │
├──────────────────────────────┤
│     pflow.planning.*         │ ← Normal Python modules, no mocking
├──────────────────────────────┤
│    mock_llm_calls fixture    │ ← Simple mock at correct boundary
└──────────────────────────────┘
```

### 2. Module Structure

```
tests/
├── shared/
│   ├── llm_mock.py          # Core LLM mock implementation
│   ├── mock_compat.py       # Compatibility layer (temporary)
│   └── mocks.py            # OLD - to be removed
├── conftest.py             # Global fixtures with autouse LLM mock
└── MIGRATION_GUIDE.md      # Developer documentation
```

### 3. API Specifications

#### 3.1 MockLLMModel Class

```python
class MockLLMModel:
    """Mock LLM model with configurable responses and call tracking."""

    def __init__(self,
                 model_name: str,
                 default_response: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize mock model.

        Args:
            model_name: Name of the model (e.g., "anthropic/claude")
            default_response: Default response data (default: {"success": True})
        """
        self.model_name: str = model_name
        self.default_response: Dict[str, Any] = default_response or {"success": True}
        self.call_history: List[Dict[str, Any]] = []
        self.prompt_count: int = 0

    def prompt(self,
               prompt_text: str,
               *,
               schema: Optional[Type] = None,
               model: Optional[str] = None,
               temperature: float = 0.0,
               max_tokens: int = 1000,
               **kwargs) -> Mock:
        """
        Mock prompt method matching llm library interface.

        Args:
            prompt_text: The prompt to send
            schema: Optional Pydantic schema for structured output
            model: Optional model override
            temperature: Temperature setting (ignored in mock)
            max_tokens: Max tokens (ignored in mock)
            **kwargs: Additional arguments to capture

        Returns:
            Mock response object with .json() method and .usage attribute
        """
        ...

    def reset_history(self) -> None:
        """Clear call history for test isolation."""
        ...

    def assert_called_with(self,
                           prompt_contains: Optional[str] = None,
                           schema: Optional[Type] = None) -> None:
        """
        Assert the model was called with specific parameters.

        Raises:
            AssertionError: If conditions not met
        """
        ...
```

#### 3.2 Mock Factory Function

```python
def create_mock_get_model(
    responses: Optional[Dict[str, Any]] = None,
    side_effect: Optional[Exception] = None
) -> Callable[[str], MockLLMModel]:
    """
    Create a mock llm.get_model function.

    Args:
        responses: Model name to response mapping
        side_effect: Exception to raise on prompt() calls

    Returns:
        Mock function that returns MockLLMModel instances

    Example:
        mock = create_mock_get_model({
            "anthropic/claude": {"workflow": "data"},
            "openai/gpt-4": {"different": "response"}
        })
    """
    ...
```

#### 3.3 Fixture API

```python
@pytest.fixture(autouse=True, scope="function")
def mock_llm_calls(monkeypatch) -> MockGetModel:
    """
    Auto-applied fixture that mocks all LLM calls.

    Yields:
        MockGetModel: Factory function with additional methods:
            - get_model(name): Get specific model instance
            - models: Dict of all created models
            - reset(): Clear all models
            - set_response(model, response): Set response for model

    Example:
        def test_something(mock_llm_calls):
            # Access the mock
            model = mock_llm_calls.get_model("anthropic/claude")
            assert model.prompt_count == 0
    """
    ...

@pytest.fixture
def mock_llm_responses(mock_llm_calls) -> ResponseConfigurator:
    """
    Configure LLM responses for specific tests.

    Yields:
        ResponseConfigurator with methods:
            - set(model_name, response): Set response
            - set_error(model_name, exception): Set error
            - get_model(name): Get model instance

    Example:
        def test_with_custom_response(mock_llm_responses):
            mock_llm_responses.set("anthropic/claude", {
                "found": True,
                "workflow_name": "test-workflow"
            })
    """
    ...
```

### 4. Implementation Details

#### 4.1 Response Handling

The mock must handle different response patterns used by planner nodes:

```python
# Pattern 1: Structured response with schema
response = model.prompt(prompt, schema=DiscoveryResult)
result = response.json()  # Returns dict

# Pattern 2: Text response
response = model.prompt(prompt)
text = response.text  # Returns string

# Pattern 3: Token usage
response = model.prompt(prompt)
tokens = response.usage  # Returns {"input_tokens": N, "output_tokens": M}
```

#### 4.2 Call History Tracking

```python
# Each call records:
{
    "timestamp": datetime.now().isoformat(),
    "prompt": prompt_text,
    "prompt_length": len(prompt_text),
    "kwargs": {
        "schema": schema.__name__ if schema else None,
        "temperature": temperature,
        "model": model,
        # ... other kwargs
    },
    "response": response_data,
    "error": error_message if failed else None
}
```

#### 4.3 Error Simulation

```python
# Configure errors per model
mock_llm_responses.set_error("anthropic/claude",
                             ValueError("API key invalid"))

# Or global error
mock = create_mock_get_model(side_effect=ConnectionError("Network error"))
```

### 5. Migration Patterns

#### 5.1 Tests That Mock Planning Module

**OLD:**
```python
with patch("pflow.planning.flow.create_planner_flow") as mock:
    mock.return_value = (mock_flow, mock_trace)
    result = runner.invoke(cli, ["test"])
```

**NEW:**
```python
def test_cli_with_planner(mock_llm_responses):
    # Configure what the planner nodes will receive
    mock_llm_responses.set("anthropic/claude", {
        "found": False,  # Discovery
        "nodes": ["read-file"],  # Browsing
        "workflow": {...}  # Generation
    })
    result = runner.invoke(cli, ["test"])
```

#### 5.2 Tests That Import Nodes Directly

**OLD:**
```python
# Would fail with module mock
from pflow.planning.nodes import WorkflowDiscoveryNode
```

**NEW:**
```python
# Works normally - no module mocking
from pflow.planning.nodes import WorkflowDiscoveryNode

def test_discovery_node(mock_llm_responses):
    mock_llm_responses.set("anthropic/claude", {"found": True})
    node = WorkflowDiscoveryNode()
    # Test node behavior
```

#### 5.3 Tests That Verify LLM Calls

**OLD:**
```python
with patch("llm.get_model") as mock_get:
    # Complex setup
    mock_model = Mock()
    mock_get.return_value = mock_model
    # Run test
    mock_model.prompt.assert_called_once()
```

**NEW:**
```python
def test_llm_called(mock_llm_calls):
    # Run test
    model = mock_llm_calls.get_model("anthropic/claude")
    assert model.prompt_count == 1
    assert "analyze" in model.call_history[0]["prompt"]
```

### 6. Test Criteria

#### 6.1 Unit Tests for Mock System

```python
# tests/test_shared/test_llm_mock.py

def test_mock_returns_consistent_responses():
    """Same model name returns same instance."""

def test_mock_tracks_call_history():
    """All calls are recorded with details."""

def test_mock_handles_schema_responses():
    """Structured responses work correctly."""

def test_mock_simulates_errors():
    """Errors can be configured and raised."""

def test_mock_isolation_between_tests():
    """Each test gets clean state."""
```

#### 6.2 Integration Tests

```python
# tests/test_integration/test_mock_integration.py

def test_planner_with_mocked_llm():
    """Full planner execution with mock LLM."""

def test_cli_with_mocked_llm():
    """CLI commands work with mock LLM."""

def test_parallel_tests_no_interference():
    """Multiple tests can run in parallel."""
```

#### 6.3 Performance Tests

```python
def test_mock_performance():
    """Mock adds <1ms overhead per call."""
    start = time.time()
    for _ in range(1000):
        model = create_mock_get_model()("test")
        model.prompt("test")
    assert time.time() - start < 0.1  # 0.1ms per call
```

### 7. Error Handling

#### 7.1 Missing Mock Configuration

```python
# Default behavior when response not configured
def test_unconfigured_model(mock_llm_calls):
    model = mock_llm_calls.get_model("unconfigured-model")
    response = model.prompt("test")
    assert response.json() == {"success": True}  # Safe default
```

#### 7.2 Invalid Response Types

```python
# Handle non-JSON responses
mock_llm_responses.set("model", "plain text response")
response = model.prompt("test")
assert response.text == "plain text response"
assert response.json() raises JSONDecodeError  # Realistic behavior
```

#### 7.3 Cleanup on Test Failure

```python
# Fixture ensures cleanup even on failure
def mock_llm_calls(monkeypatch):
    mock = create_mock_get_model()
    monkeypatch.setattr("llm.get_model", mock)
    try:
        yield mock
    finally:
        mock.reset()  # Always cleanup
```

### 8. Backwards Compatibility

#### 8.1 Environment Variable Support

```python
# Support for PFLOW_TESTING env var
if os.getenv("PFLOW_TESTING"):
    # Apply mock automatically
    import llm
    llm.get_model = create_mock_get_model()
```

#### 8.2 Old Mock Detection

```python
# Detect if old mock is active and warn
if "MockPlanningModule" in str(sys.modules.get("pflow.planning")):
    warnings.warn(
        "Old planning mock detected. "
        "Please migrate to new LLM mock. "
        "See tests/MIGRATION_GUIDE.md"
    )
```

### 9. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Test Pass Rate | 100% | `pytest tests/` |
| Execution Time | <10s | `time pytest tests/ -q` |
| Mock Code Size | <100 LOC | `wc -l tests/shared/llm_mock.py` |
| No Hanging | 0 | Run with timeout |
| State Isolation | 100% | Random order tests |
| Import Success | 100% | Direct imports work |

### 10. Edge Cases

#### 10.1 Multiple Model Types

```python
# Different models in same test
def test_multiple_models(mock_llm_responses):
    mock_llm_responses.set("anthropic/claude", {"a": 1})
    mock_llm_responses.set("openai/gpt-4", {"b": 2})

    model1 = llm.get_model("anthropic/claude")
    model2 = llm.get_model("openai/gpt-4")

    assert model1.prompt("").json() == {"a": 1}
    assert model2.prompt("").json() == {"b": 2}
```

#### 10.2 Streaming Responses

```python
# Mock streaming if needed
def mock_stream_response():
    for chunk in ["Hello", " ", "World"]:
        yield Mock(text=chunk)

model.prompt = Mock(return_value=mock_stream_response())
```

#### 10.3 Retry Logic

```python
# Test retry behavior
call_count = 0
def flaky_prompt(*args, **kwargs):
    nonlocal call_count
    call_count += 1
    if call_count < 3:
        raise ConnectionError("Temporary failure")
    return Mock(json=lambda: {"success": True})

model.prompt = flaky_prompt
```

### 11. Monitoring and Debugging

#### 11.1 Debug Mode

```python
# Enable debug logging
@pytest.fixture
def debug_llm(mock_llm_calls, caplog):
    """Enable LLM mock debug logging."""
    import logging
    logging.getLogger("llm_mock").setLevel(logging.DEBUG)
    yield mock_llm_calls
    # Print all LLM calls after test
    for model_name, model in mock_llm_calls.models.items():
        print(f"\nModel {model_name} called {model.prompt_count} times")
        for call in model.call_history:
            print(f"  - {call['prompt'][:50]}...")
```

#### 11.2 Assertion Helpers

```python
# Custom assertions
def assert_llm_called_times(mock_llm_calls, model_name, times):
    model = mock_llm_calls.get_model(model_name)
    assert model is not None, f"Model {model_name} was never created"
    assert model.prompt_count == times, \
        f"Expected {times} calls, got {model.prompt_count}"

def assert_prompt_contains(mock_llm_calls, model_name, text):
    model = mock_llm_calls.get_model(model_name)
    prompts = [call["prompt"] for call in model.call_history]
    assert any(text in p for p in prompts), \
        f"No prompt contained '{text}'"
```

### 12. Future Enhancements

1. **Response Templates**: Predefined responses for common patterns
2. **Record/Replay**: Record real LLM responses for replay in tests
3. **Cost Tracking**: Simulate token costs for budget testing
4. **Latency Simulation**: Add realistic delays for performance testing
5. **Multi-turn Conversations**: Support for chat-based models

### 13. Implementation Checklist

- [ ] Create `tests/shared/llm_mock.py` with core classes
- [ ] Create fixtures in `tests/conftest.py`
- [ ] Create compatibility layer
- [ ] Write unit tests for mock
- [ ] Disable old mock system
- [ ] Fix failing tests
- [ ] Verify performance (<10s)
- [ ] Verify isolation (random order)
- [ ] Create migration guide
- [ ] Remove old mock system
- [ ] Update documentation