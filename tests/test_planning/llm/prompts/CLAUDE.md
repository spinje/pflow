# Prompt Testing System Guide

## Executive Summary

This directory contains the **prompt accuracy testing system** - a critical infrastructure that ensures LLM prompts in pflow maintain quality, performance, and cost-effectiveness over time.

**Core Purpose**: Track prompt accuracy, prevent regressions, optimize costs, and ensure prompts work correctly across different LLM models.

**Key Achievement**: Tests run in ~10 seconds with parallel execution, cost $0.006 with test models, and provide real-time failure feedback.

## System Architecture

```
src/pflow/planning/prompts/*.md     [Prompt Files with Frontmatter]
           ↓
tests/.../test_*_prompt.py          [Behavioral Tests]
           ↓
tools/test_prompt_accuracy.py       [Test Runner & Metrics Tracker]
           ↓
Frontmatter Updates                 [Accuracy, Cost, Version Tracking]
```

### Component Relationships

1. **Prompt Files** (`src/pflow/planning/prompts/*.md`)
   - Contain the actual prompt text
   - Include YAML frontmatter with test metadata
   - Track accuracy history, costs, and test configuration

2. **Test Files** (`tests/test_planning/llm/prompts/test_*_prompt.py`)
   - Implement behavioral tests for prompts
   - MUST follow the pattern from `test_discovery_prompt.py`
   - Support parallel execution via pytest parametrization

3. **conftest.py** (Test configuration)
   - Monkey-patches `llm.get_model()` for model override
   - Captures token usage for cost tracking
   - Enables testing with cheaper models without code changes

4. **test_prompt_accuracy.py** (Orchestration)
   - Runs tests with real-time display
   - Updates frontmatter metrics
   - Handles parallel execution automatically

## The Reference Implementation: test_discovery_prompt.py

**CRITICAL**: All new prompt tests MUST follow this exact pattern. This is not a suggestion - it's the only way to ensure compatibility with the accuracy tracking system.

### Key Patterns from test_discovery_prompt.py

```python
# 1. Imports and Setup
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

import pytest

# 2. Logging for failure reporting
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 3. File-based failure reporting (bypasses pytest output capture)
FAILURE_OUTPUT_FILE = os.environ.get("PFLOW_TEST_FAILURE_FILE")

def report_failure(test_name: str, failure_reason: str):
    """Report a test failure immediately via file and logging."""
    logger.info(f"FAIL_REASON|{test_name}|{failure_reason}")
    print(f"FAIL_REASON|{test_name}|{failure_reason}", flush=True)

    if FAILURE_OUTPUT_FILE:
        try:
            failure_data = {
                "test": test_name,
                "reason": failure_reason,
                "timestamp": time.time()
            }
            with open(FAILURE_OUTPUT_FILE, 'a') as f:
                f.write(json.dumps(failure_data) + '\n')
                f.flush()
        except Exception:
            pass

# 4. Test case structure
@dataclass
class TestCase:
    name: str
    user_input: str
    should_find: bool  # Or other expected behavior
    expected_workflow_hint: Optional[str]
    confidence_level: Confidence
    category: str
    why_important: str

# 5. Test cases as a module-level function (for parametrization)
def get_test_cases() -> List[TestCase]:
    return [
        TestCase(...),
        # All test cases here
    ]

# 6. Test class with parametrized test method
class TestDiscoveryPrompt:
    @pytest.fixture(scope="class")
    def workflow_directory(self):
        # Setup fixture
        pass

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_discovery_scenario(self, workflow_directory, test_case):
        """Test individual scenario."""
        # Test implementation

        # Report failures immediately
        if not test_passed:
            failure_reason = "..."
            report_failure(test_case.name, failure_reason)
            assert False, f"[{test_case.name}] {failure_reason}"
```

### Why These Patterns Matter

1. **Parametrization**: Each test case becomes a separate pytest item, enabling:
   - Parallel execution with pytest-xdist
   - Individual test visibility in reports
   - Accurate test counting

2. **File-based failure reporting**:
   - Bypasses pytest-xdist's output capturing
   - Enables real-time failure display
   - Works reliably with parallel execution

3. **Behavioral testing**:
   - Tests outcomes, not implementation
   - Validates decisions and confidence levels
   - Ensures prompts work correctly, not just match text

## Creating New Prompt Tests

### Step 1: Create the Test File

Create `test_<prompt_name>_prompt.py` following this template:

```python
"""Comprehensive tests for <prompt_name> prompt with pytest parametrization.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

Run with:
  RUN_LLM_TESTS=1 pytest test_<prompt_name>_prompt.py -v
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

import pytest

from pflow.planning.nodes import <RelevantNode>

# Set up logger for immediate failure reporting
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Get failure output file from environment
FAILURE_OUTPUT_FILE = os.environ.get("PFLOW_TEST_FAILURE_FILE")

def report_failure(test_name: str, failure_reason: str):
    """Report a test failure immediately via file and logging."""
    logger.info(f"FAIL_REASON|{test_name}|{failure_reason}")
    print(f"FAIL_REASON|{test_name}|{failure_reason}", flush=True)

    if FAILURE_OUTPUT_FILE:
        try:
            failure_data = {
                "test": test_name,
                "reason": failure_reason,
                "timestamp": time.time()
            }
            with open(FAILURE_OUTPUT_FILE, 'a') as f:
                f.write(json.dumps(failure_data) + '\n')
                f.flush()
        except Exception:
            pass

# Skip tests unless LLM tests enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)

# Define your test case structure
@dataclass
class TestCase:
    name: str
    # Add fields specific to your prompt
    ...

def get_test_cases() -> List[TestCase]:
    """Define all test cases."""
    return [
        # Your test cases here
    ]

class Test<PromptName>Prompt:
    @pytest.fixture(scope="class")
    def setup_fixture(self):
        """Create any necessary test fixtures."""
        # Setup code
        yield fixture_data
        # Cleanup code

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_scenario(self, setup_fixture, test_case):
        """Test individual scenario."""
        # Your test implementation

        # Check results and report failures
        if not test_passed:
            failure_reason = "..."
            report_failure(test_case.name, failure_reason)
            assert False, f"[{test_case.name}] {failure_reason}"
```

### Step 2: Update Prompt File Frontmatter

Ensure the prompt file in `src/pflow/planning/prompts/<name>.md` has proper frontmatter:

```yaml
---
name: <prompt_name>
test_path: tests/test_planning/llm/prompts/test_<prompt_name>_prompt.py::Test<PromptName>Prompt
test_command: uv run python tools/test_prompt_accuracy.py <prompt_name>
version: 1.0
latest_accuracy: 0.0
test_runs: []
average_accuracy: 0.0
test_count: <number_of_test_cases>
previous_version_accuracy: 0.0
last_tested: ''
prompt_hash: ''
last_test_cost: 0.0
---
```

### Step 3: Register in test_prompt_accuracy.py

The tool automatically finds prompts by scanning the prompts directory, but ensure your prompt file follows the naming convention.

## Critical Requirements

### MUST Follow

1. **Use pytest.mark.parametrize**: Every test case must be a separate pytest item
2. **Implement report_failure()**: For real-time failure display
3. **Test behavior, not text**: Validate outcomes and decisions
4. **Support parallel execution**: No shared state between tests
5. **Use dataclasses for test cases**: Type safety and clarity
6. **Module-level get_test_cases()**: Required for parametrization

### MUST NOT Do

1. **Don't use ThreadPoolExecutor**: Let pytest-xdist handle parallelization
2. **Don't test prompt text**: Test behavior and outcomes
3. **Don't share state**: Each test must be independent
4. **Don't use class methods for test cases**: Use module-level function
5. **Don't skip report_failure()**: Critical for real-time feedback

## Running Tests

### Via test_prompt_accuracy.py (Recommended)

```bash
# Run with default model (Claude Sonnet)
uv run python tools/test_prompt_accuracy.py discovery

# Run with cheap test model
uv run python tools/test_prompt_accuracy.py discovery --model gpt-5-nano

# Dry run (no updates)
uv run python tools/test_prompt_accuracy.py discovery --dry-run

# Override parallelization
uv run python tools/test_prompt_accuracy.py discovery --parallel 10
```

### Direct pytest execution

```bash
# Run all tests for a prompt
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py -v

# Run specific test case
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPrompt::test_discovery_scenario[exact_match] -v
```

## How conftest.py Works

The `conftest.py` file provides critical test infrastructure:

### 1. Model Override
```python
@pytest.fixture(scope="session", autouse=True)
def configure_test_model():
    """Monkey-patch llm.get_model to use test model if specified."""
    override_model = os.getenv("PFLOW_TEST_MODEL")
    if override_model:
        # Redirects all model requests to the test model
```

### 2. Token Tracking
```python
tracker_file = os.environ.get("PFLOW_TOKEN_TRACKER_FILE")
if tracker_file:
    # Captures token usage from LLM responses
    # Writes to file for cost calculation
```

### 3. Temperature Compatibility
The conftest.py automatically removes temperature parameters for models that don't support them (like gpt-5-nano), preventing API errors.

This enables:
- Testing with 99% cheaper models (gpt-5-nano)
- Accurate cost tracking
- Cross-model compatibility

## Performance Optimization

### Parallel Execution
- Tests run with N workers where N = test count (max 20)
- ~10x speedup (120s → 10s for 19 tests)
- Automatic optimization, no configuration needed

### Cost Optimization
- Use `--model gpt-5-nano` for 99% cost reduction
- Track costs with frontmatter metrics
- Balance accuracy vs cost for different use cases

## Testing Philosophy

### Behavioral Testing
We test **what the prompt does**, not **how it's written**:

✅ **Good**: Test if discovery correctly identifies reusable workflows
❌ **Bad**: Test if prompt contains specific text

✅ **Good**: Test confidence levels match expectations
❌ **Bad**: Test exact confidence values

✅ **Good**: Test decision outcomes (found/not_found)
❌ **Bad**: Test response format details

### Test Categories

Organize tests by behavior category:
- **core**: Must-work basic functionality
- **edge**: Boundary conditions
- **ambiguous**: Unclear inputs
- **performance**: Speed requirements
- **robustness**: Error handling

## Troubleshooting

### Common Issues

1. **No tests found**
   - Check `RUN_LLM_TESTS=1` is set
   - Verify test file follows naming convention
   - Ensure parametrization is correct

2. **Failures not showing in real-time**
   - Verify `report_failure()` is called
   - Check `PFLOW_TEST_FAILURE_FILE` is set
   - Ensure file writes are flushed

3. **Tests running slowly**
   - Check pytest-xdist is installed
   - Verify parallel workers are configured
   - Use `--model gpt-5-nano` for faster responses

4. **Token tracking not working**
   - Check conftest.py is in the directory
   - Verify `PFLOW_TOKEN_TRACKER_FILE` is set
   - Ensure LLM responses include usage data

## Important Notes

1. **This is the source of truth** for prompt testing patterns
2. **All agents must follow these patterns** exactly
3. **test_discovery_prompt.py is the reference** implementation
4. **Real-time failure display** requires the file-based approach
5. **Parallel execution** requires pytest parametrization
6. **Cost tracking** requires conftest.py setup

## Summary

The prompt testing system ensures:
- **Quality**: Track accuracy over time
- **Performance**: ~10 second test runs
- **Cost**: $0.006 per full test suite with test models
- **Visibility**: Real-time failure feedback
- **Reliability**: Behavioral testing approach

Follow the patterns from `test_discovery_prompt.py` exactly. This is not optional - it's the only way to ensure your tests integrate properly with the accuracy tracking system.