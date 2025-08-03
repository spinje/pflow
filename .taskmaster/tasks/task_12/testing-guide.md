# Task 12: LLM Node Testing Guide

## Critical Testing Philosophy

The LLM node tests should **NOT** make real API calls during normal test runs. This is essential for:
- **Cost control** - No unexpected API charges
- **CI/CD compatibility** - Tests run without API keys
- **Speed** - Tests complete instantly
- **Determinism** - Same results every time

## 🔒 Security Warning

**NEVER commit API keys to the repository!**

- Don't hardcode keys in test files
- Don't commit `.env` files with keys
- Add `.env` to `.gitignore` if using environment files
- Use environment variables or the `llm` CLI for key management
- For CI/CD, use secure secrets management

## Testing Strategy: Hybrid Approach

### 1. Primary Tests: Full Mocking (Always Run)

Location: `tests/test_nodes/test_llm.py`

**All 22 test criteria must be covered with mocks**:

```python
import pytest
from unittest.mock import Mock, patch

@patch('llm.get_model')
def test_successful_execution(mock_get_model):
    """Test normal execution with mocked LLM."""
    # Create mock response with usage data
    mock_usage = Mock()
    mock_usage.input = 150
    mock_usage.output = 75
    mock_usage.details = {
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 50
    }

    mock_response = Mock()
    mock_response.text.return_value = "Test response"
    mock_response.usage.return_value = mock_usage

    mock_model = Mock()
    mock_model.prompt.return_value = mock_response
    mock_get_model.return_value = mock_model

    # Test the node
    node = LLMNode()
    shared = {"prompt": "Test prompt"}
    action = node.run(shared)

    # Verify outputs
    assert shared["response"] == "Test response"
    assert shared["llm_usage"]["input_tokens"] == 150
    assert shared["llm_usage"]["output_tokens"] == 75
    assert shared["llm_usage"]["cache_read_input_tokens"] == 50
    assert action == "default"

@patch('llm.get_model')
def test_usage_none_handling(mock_get_model):
    """Test when usage() returns None."""
    mock_response = Mock()
    mock_response.text.return_value = "Response without usage"
    mock_response.usage.return_value = None  # Critical test case!

    mock_model = Mock()
    mock_model.prompt.return_value = mock_response
    mock_get_model.return_value = mock_model

    node = LLMNode()
    shared = {"prompt": "Test"}
    node.run(shared)

    # Should store empty dict, not crash
    assert shared["llm_usage"] == {}
```

**Key Mocking Patterns**:

1. **Mock the entire chain**:
   - `llm.get_model()` returns mock model
   - `model.prompt()` returns mock response
   - `response.text()` returns string
   - `response.usage()` returns mock usage or None

2. **Test all error conditions**:
   ```python
   @patch('llm.get_model')
   def test_unknown_model_error(mock_get_model):
       mock_get_model.side_effect = Exception("UnknownModelError: bad-model")
       # Verify helpful error message
   ```

3. **Test edge cases**:
   - Temperature clamping (< 0, > 2, boundaries)
   - Empty prompt handling
   - Empty response handling
   - None values in optional parameters

### 2. Optional Real LLM Tests (Separate Command)

Location: `tests/test_nodes/test_llm_integration.py`

#### API Key Setup for Integration Tests

The `llm` library handles API keys automatically. You have two options:

**Option 1: Environment Variables (Recommended for CI/CD)**
```bash
# Set for current session only
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."

# Or in .env file (DO NOT commit!)
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
echo 'OPENAI_API_KEY=sk-...' >> .env
```

**Option 2: LLM CLI Configuration (Recommended for local development)**
```bash
# Persistent configuration (stored in ~/.config/io.datasette.llm/)
llm keys set anthropic
# Enter key when prompted

llm keys set openai
# Enter key when prompted

# Verify setup
llm models  # Should list available models
```

**Safety Check in Tests**:

Mark these tests to skip by default AND verify API availability:

```python
import pytest
import os
import llm

def has_llm_api_key():
    """Check if we can actually use the LLM."""
    try:
        model = llm.get_model("claude-sonnet-4-20250514")
        # Don't actually call it, just check if we can get the model
        return True
    except Exception as e:
        if "NeedsKeyException" in str(e) or "API key" in str(e):
            return False
        return True  # Other errors mean key might be present

@pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="Set RUN_LLM_TESTS=1 to run real LLM tests"
)
@pytest.mark.skipif(
    not has_llm_api_key(),
    reason="No API key configured. Run 'llm keys set anthropic' to configure"
)
def test_real_llm_call():
    """Test with actual LLM API (costs money!)."""
    node = LLMNode()
    node.set_params({
        "model": "claude-sonnet-4-20250514",
        "temperature": 0.1,
        "max_tokens": 10  # Keep cost minimal
    })

    shared = {"prompt": "Say 'test' and nothing else"}
    action = node.run(shared)

    # Basic checks - response exists and usage tracked
    assert "response" in shared
    assert shared["response"]  # Not empty
    assert "llm_usage" in shared

    # Usage should have actual data
    usage = shared["llm_usage"]
    assert usage.get("input_tokens", 0) > 0
    assert usage.get("output_tokens", 0) > 0

@pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="Set RUN_LLM_TESTS=1 to run real LLM tests"
)
def test_missing_api_key_error():
    """Test that missing API key produces helpful error."""
    # Temporarily unset the key if present
    old_key = os.environ.get("ANTHROPIC_API_KEY")
    if old_key:
        del os.environ["ANTHROPIC_API_KEY"]

    try:
        node = LLMNode()
        node.set_params({"model": "claude-sonnet-4-20250514"})
        shared = {"prompt": "test"}

        with pytest.raises(ValueError) as exc_info:
            node.run(shared)

        # Should have helpful message
        assert "llm keys set" in str(exc_info.value)
    finally:
        # Restore key if it was present
        if old_key:
            os.environ["ANTHROPIC_API_KEY"] = old_key
```

**Running Real Tests**:
```bash
# Normal test run (mocked only, no keys needed)
make test

# With real LLM calls (requires API keys)
RUN_LLM_TESTS=1 pytest tests/test_nodes/test_llm_integration.py -v

# If you see "SKIPPED: No API key configured"
llm keys set anthropic  # Configure the key first
```

**CI/CD Setup**:
```yaml
# GitHub Actions example
- name: Run LLM integration tests
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    RUN_LLM_TESTS: "1"
  run: |
    pytest tests/test_nodes/test_llm_integration.py -v
```

### 3. VCR Option (Record/Replay)

For a middle ground, use VCR to record real responses once:

```python
import vcr

@vcr.use_cassette('fixtures/llm/simple_prompt.yaml')
def test_with_recording():
    """Test with recorded real response."""
    node = LLMNode()
    node.set_params({"temperature": 0.1})
    shared = {"prompt": "Say hello in 3 words"}
    node.run(shared)

    assert "response" in shared
    assert len(shared["response"].split()) <= 5  # Reasonable response
```

**Benefits**:
- First run makes real API call and records it
- Subsequent runs use the recording (no API cost)
- Tests remain deterministic
- Can commit cassettes to version control

## Test Coverage Checklist

Ensure these 22 test criteria are ALL covered with mocks:

1. ✅ Prompt from shared store
2. ✅ Prompt from params (fallback)
3. ✅ Missing prompt error
4. ✅ Model parameter usage
5. ✅ Temperature = 0.0
6. ✅ Temperature = 2.0
7. ✅ Temperature < 0 (clamped to 0)
8. ✅ Temperature > 2 (clamped to 2)
9. ✅ System parameter provided
10. ✅ System parameter None (not in kwargs)
11. ✅ Max_tokens provided
12. ✅ Max_tokens None (not in kwargs)
13. ✅ Response text extraction
14. ✅ Response stored in shared
15. ✅ Action returns "default"
16. ✅ UnknownModelError handling
17. ✅ NeedsKeyException handling
18. ✅ Generic exception handling
19. ✅ Empty prompt error
20. ✅ Empty response handling (not error)
21. ✅ Usage data present (correct fields)
22. ✅ Usage data None (empty dict stored)

## Implementation Order for Tests

1. **Start with basic mocked tests** - Get the node working
2. **Add edge case tests** - Temperature, empty values, etc.
3. **Add error condition tests** - Unknown model, missing key
4. **Add usage tracking tests** - Both with and without usage data
5. **Optional: Add VCR tests** - Record a few real responses
6. **Optional: Add integration tests** - Marked to skip by default

## Critical Testing Requirements

### MUST Mock These Imports
```python
@patch('llm.get_model')  # Always mock this
```

### MUST Test Usage None Case
This is a critical bug we discovered - usage() can return None:
```python
mock_response.usage.return_value = None  # Must handle gracefully
```

### MUST Verify Field Names
The spec requires specific field names in llm_usage:
- `input_tokens` (NOT `input`)
- `output_tokens` (NOT `output`)
- `cache_creation_input_tokens`
- `cache_read_input_tokens`

### MUST Test Temperature Clamping
```python
# Test boundary conditions
test_temps = [-1.0, 0.0, 0.7, 2.0, 3.0]
# Should clamp to [0.0, 0.0, 0.7, 2.0, 2.0]
```

## Running Tests During Development

```bash
# Run your specific tests frequently
pytest tests/test_nodes/test_llm.py -v

# Run with coverage to ensure completeness
pytest tests/test_nodes/test_llm.py --cov=src/pflow/nodes/llm

# Run the whole suite to ensure no regressions
make test
```

## Final Verification

Before considering the task complete:

1. All 22 test criteria pass with mocks
2. `make test` passes (no real API calls)
3. Coverage is high for critical paths
4. Optional integration tests documented but skipped by default
5. No API keys required for normal test runs

Remember: **The primary test suite must NEVER make real LLM API calls**. This ensures tests are fast, free, and reliable for all developers and CI/CD systems.
