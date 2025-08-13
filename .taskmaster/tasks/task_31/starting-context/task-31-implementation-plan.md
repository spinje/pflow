# Task 31: Implementation Plan

## Refactor Test Infrastructure - Mock at LLM Level

### Phase 0: Analysis and Preparation (30 minutes)

#### 0.1 Identify All LLM Usage Points
```bash
# Find all llm.get_model calls
grep -r "llm.get_model" src/pflow/planning/
grep -r "import llm" src/pflow/
```

**Expected findings:**
- All planner nodes use `llm.get_model(model_name)`
- Pattern: `model = llm.get_model(prep_res["model_name"])`
- Response pattern: `response = model.prompt(prompt, schema=Schema)`

#### 0.2 Analyze Current Test Patterns
```bash
# Find tests that mock planning module
grep -r "patch.*pflow.planning" tests/
grep -r "mock_planner" tests/
```

**Expected patterns:**
- Tests patching `pflow.planning.flow.create_planner_flow`
- Tests importing from `pflow.planning.nodes`
- Tests using the autouse planning mock

#### 0.3 Create Backup
```bash
# Backup current mock system
cp tests/shared/mocks.py tests/shared/mocks.py.bak
git add -A && git commit -m "Backup: Before Task 31 mock refactor"
```

### Phase 1: Implement New LLM Mock (2 hours)

#### 1.1 Create Core LLM Mock (30 min)

**File**: `tests/shared/llm_mock.py`

```python
"""
LLM mock for testing - prevents actual API calls.

This replaces the complex planning module mock with a simple,
focused mock of the actual external dependency.
"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import Any, Dict, Optional


class MockLLMModel:
    """Mock LLM model that returns configurable responses."""

    def __init__(self, model_name: str, default_response: Optional[Dict] = None):
        self.model_name = model_name
        self.default_response = default_response or {"success": True}
        self.call_history = []

    def prompt(self, prompt_text: str, **kwargs) -> Mock:
        """Mock prompt method that returns a mock response."""
        # Record the call
        self.call_history.append({
            "prompt": prompt_text,
            "kwargs": kwargs
        })

        # Create response mock
        response = Mock()

        # Handle schema-based responses
        if "schema" in kwargs:
            # Return structured response
            response.json = Mock(return_value=self.default_response)
        else:
            # Return text response
            response.text = str(self.default_response)

        # Add usage info for token counting
        response.usage = {
            "input_tokens": len(prompt_text.split()),
            "output_tokens": 50
        }

        return response


def create_mock_get_model(responses: Optional[Dict[str, Any]] = None):
    """Create a mock llm.get_model function."""
    responses = responses or {}
    models = {}

    def mock_get_model(model_name: str) -> MockLLMModel:
        if model_name not in models:
            # Create model with specific or default response
            model_response = responses.get(model_name, {"success": True})
            models[model_name] = MockLLMModel(model_name, model_response)
        return models[model_name]

    # Add inspection methods
    mock_get_model.get_model = lambda name: models.get(name)
    mock_get_model.models = models
    mock_get_model.reset = lambda: models.clear()

    return mock_get_model
```

#### 1.2 Create Fixture System (30 min)

**File**: `tests/conftest.py` (update existing or create)

```python
"""Global test configuration and fixtures."""

import pytest
import sys
from tests.shared.llm_mock import create_mock_get_model


@pytest.fixture(autouse=True)
def mock_llm_calls(monkeypatch):
    """
    Automatically mock LLM for all tests.

    This prevents actual API calls and provides consistent test behavior.
    Individual tests can override responses using the fixture.
    """
    # Create the mock
    mock_get_model = create_mock_get_model()

    # Apply the mock
    monkeypatch.setattr("llm.get_model", mock_get_model)

    # Provide access to the mock for test configuration
    yield mock_get_model

    # Clean up
    mock_get_model.reset()


@pytest.fixture
def mock_llm_responses(mock_llm_calls):
    """
    Configure specific LLM responses for a test.

    Example:
        def test_something(mock_llm_responses):
            mock_llm_responses.set("anthropic/claude", {"result": "test"})
    """
    def set_response(model_name: str, response: Any):
        # Get or create the model
        model = mock_llm_calls(model_name)
        model.default_response = response

    class ResponseSetter:
        set = set_response
        get_model = mock_llm_calls

    return ResponseSetter()
```

#### 1.3 Create Compatibility Layer (30 min)

**File**: `tests/shared/mock_compat.py`

```python
"""
Compatibility layer for tests using old mock patterns.

This allows gradual migration from the old mock system.
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_planner_flow():
    """
    Compatibility fixture for tests that mock create_planner_flow.

    This redirects to the new LLM mock approach.
    """
    with patch("pflow.planning.flow.create_planner_flow") as mock:
        # Create a mock that doesn't actually call LLM
        mock_flow = MagicMock()
        mock_trace = MagicMock()
        mock.return_value = (mock_flow, mock_trace)
        yield mock


# Marker for tests that need real planning module
requires_real_planner = pytest.mark.skipif(
    "llm" not in sys.modules,
    reason="Requires LLM module"
)
```

#### 1.4 Test the New Mock (30 min)

**File**: `tests/test_shared/test_llm_mock.py`

```python
"""Test the LLM mock system."""

import pytest
from tests.shared.llm_mock import MockLLMModel, create_mock_get_model


def test_mock_llm_model_basic():
    """Test basic MockLLMModel functionality."""
    model = MockLLMModel("test-model")
    response = model.prompt("test prompt")

    assert response.json() == {"success": True}
    assert len(model.call_history) == 1
    assert model.call_history[0]["prompt"] == "test prompt"


def test_mock_get_model_creates_models():
    """Test that mock_get_model creates and caches models."""
    mock_get_model = create_mock_get_model()

    model1 = mock_get_model("model-a")
    model2 = mock_get_model("model-a")
    model3 = mock_get_model("model-b")

    assert model1 is model2  # Same instance
    assert model1 is not model3  # Different models


def test_fixture_integration(mock_llm_calls):
    """Test that the fixture works correctly."""
    import llm  # Should be mocked

    model = llm.get_model("test-model")
    response = model.prompt("test")

    assert response.json() == {"success": True}


def test_response_override(mock_llm_responses):
    """Test that responses can be overridden per test."""
    import llm

    # Set custom response
    mock_llm_responses.set("custom-model", {"custom": "response"})

    model = llm.get_model("custom-model")
    response = model.prompt("test", schema=object)

    assert response.json() == {"custom": "response"}
```

### Phase 2: Remove Old Planning Mock (1 hour)

#### 2.1 Disable Old Mock (15 min)

**File**: `tests/shared/mocks.py`

```python
# Add deprecation notice at top
"""
DEPRECATED: This complex planning mock is being replaced with simple LLM mocking.
See tests/shared/llm_mock.py for the new approach.

This file is kept temporarily for reference during migration.
"""

# Comment out the autouse fixture
# @pytest.fixture(autouse=True)
# def mock_planner_for_tests():
#     ...

# Or rename it to prevent auto-application
def DEPRECATED_mock_planner_for_tests():
    ...
```

#### 2.2 Update Test Imports (30 min)

```bash
# Find and update imports
grep -r "from tests.shared.mocks import" tests/

# Update to use new mock if needed
# from tests.shared.mock_compat import mock_planner_flow
```

#### 2.3 Verify Planning Imports Work (15 min)

```python
# Test script to verify imports
python -c "
from pflow.planning import create_planner_flow
from pflow.planning.nodes import WorkflowDiscoveryNode
from pflow.planning.debug import DebugWrapper
print('All imports successful!')
"
```

### Phase 3: Fix Failing Tests (2 hours)

#### 3.1 Run Tests and Categorize Failures (30 min)

```bash
# Run all tests and capture output
pytest tests/ -v --tb=short > test_results.txt 2>&1

# Categorize failures:
# 1. Tests that mock planning directly
# 2. Tests that expect specific LLM responses
# 3. Tests that check if LLM was called
# 4. Tests with other issues
```

#### 3.2 Fix Direct Planning Mocks (45 min)

**Pattern 1**: Tests mocking `create_planner_flow`
```python
# OLD
with patch("pflow.planning.flow.create_planner_flow") as mock:
    ...

# NEW (using compat layer)
def test_something(mock_planner_flow):
    ...
```

**Pattern 2**: Tests importing nodes directly
```python
# These should now work without changes
from pflow.planning.nodes import ComponentBrowsingNode
```

#### 3.3 Fix LLM Response Tests (30 min)

**Pattern**: Tests expecting specific LLM responses
```python
# OLD (might have complex setup)
def test_node_with_llm():
    with patch("llm.get_model") as mock:
        mock.return_value.prompt.return_value = Mock(json=lambda: {...})

# NEW
def test_node_with_llm(mock_llm_responses):
    mock_llm_responses.set("anthropic/claude", {"expected": "response"})
    # Test code
```

#### 3.4 Fix Edge Cases (15 min)

- Tests that check LLM wasn't called
- Tests that verify specific prompt patterns
- Tests with timing dependencies

### Phase 4: Verification and Documentation (1 hour)

#### 4.1 Performance Verification (15 min)

```bash
# Measure test execution time
time pytest tests/test_planning/ -q
time pytest tests/test_cli/ -q
time pytest tests/ -q

# Should be:
# - test_planning: <5 seconds
# - test_cli: <3 seconds
# - all tests: <10 seconds
```

#### 4.2 Isolation Verification (15 min)

```bash
# Run tests in different orders
pytest tests/ -q --random-order
pytest tests/ -q --reverse
pytest tests/test_planning/unit/test_browsing_selection.py tests/test_cli/ -q

# All should pass without hanging
```

#### 4.3 Create Migration Guide (20 min)

**File**: `tests/MIGRATION_GUIDE.md`

```markdown
# Test Mock Migration Guide

## Why the Change?
We've replaced the complex planning module mock with simple LLM mocking because:
1. It mocks the actual external dependency (LLM API)
2. Eliminates module state pollution
3. Fixes test hanging and interference issues
4. Simplifies from 200+ LOC to <100 LOC

## What Changed?
- OLD: Mock entire `pflow.planning` module
- NEW: Mock only `llm.get_model()` function

## How to Update Tests

### Basic Usage (No Changes Needed)
Most tests need no changes - the LLM is automatically mocked.

### Custom LLM Responses
```python
def test_my_feature(mock_llm_responses):
    mock_llm_responses.set("model-name", {"response": "data"})
```

### Checking LLM Calls
```python
def test_llm_called(mock_llm_calls):
    # Run code
    model = mock_llm_calls.get_model("model-name")
    assert len(model.call_history) == 1
```
```

#### 4.4 Update Documentation (10 min)

Update relevant files:
- `tests/README.md` - Explain new mock approach
- `tests/CLAUDE.md` - Update testing guidance
- `.taskmaster/tasks/task_31/` - Document completion

### Phase 5: Cleanup (30 minutes)

#### 5.1 Remove Old Mock System
```bash
# After all tests pass
rm tests/shared/mocks.py.bak
git rm tests/shared/mocks.py  # If fully migrated
```

#### 5.2 Remove Compatibility Layer (if unused)
```bash
# Check if compat layer still needed
grep -r "mock_planner_flow" tests/
# If not used, remove it
```

#### 5.3 Final Test Run
```bash
# Full test suite
pytest tests/ -v

# With coverage
pytest tests/ --cov=pflow --cov-report=term-missing
```

### Rollback Plan

If issues arise:
1. `git stash` current changes
2. `git checkout tests/shared/mocks.py`
3. Re-enable autouse fixture
4. Investigate specific failure before retry

### Success Criteria Checklist

- [ ] All tests pass (100% pass rate)
- [ ] Test execution <10 seconds
- [ ] No hanging tests
- [ ] Tests pass in any order
- [ ] LLM mock <100 LOC
- [ ] Documentation updated
- [ ] Old mock removed

### Risk Log

| Risk | Mitigation | Status |
|------|------------|--------|
| Hidden LLM usage | Search codebase thoroughly | ✓ |
| Test relies on mock internals | Provide compat layer | ✓ |
| Performance regression | Measure before/after | ⏳ |
| Missing test coverage | Run with coverage report | ⏳ |