# PocketFlow Implementation Template

This template provides a standard structure for implementing pflow components using PocketFlow. Use this as a starting point for Tasks 4, 8, 17, 20, 22, and 23.

## Directory Structure

```
src/pflow/flows/{component_name}/
├── __init__.py           # Exports the main flow
├── flow.py               # Main flow orchestration
├── nodes/                # Individual node implementations
│   ├── __init__.py
│   ├── input_nodes.py    # Nodes for input/loading
│   ├── process_nodes.py  # Core processing nodes
│   ├── output_nodes.py   # Output/persistence nodes
│   └── error_nodes.py    # Error handling nodes
└── CLAUDE.md             # Component-specific documentation
```

## Basic Flow Template

### `flow.py` - Main Orchestration

```python
"""
{Component Name} Flow - {Brief Description}

This flow implements {detailed description of what this orchestration does}.
Part of Task {N}: {Task Title}
"""

from pocketflow import Flow, Node
from .nodes import (
    InputNode,
    ValidateNode,
    ProcessNode,
    OutputNode,
    ErrorHandlerNode
)


def create_{component}_flow(config=None):
    """
    Create the {component} flow with proper error handling and routing.

    Args:
        config: Optional configuration dictionary

    Returns:
        Flow: Configured PocketFlow instance
    """
    flow = Flow()

    # Initialize nodes
    input_node = InputNode()
    validate = ValidateNode()
    process = ProcessNode(config)
    output = OutputNode()
    error_handler = ErrorHandlerNode()

    # Set start node
    flow.start(input_node)

    # Define main path
    input_node >> validate >> process >> output >> flow.end

    # Define error paths
    input_node - "error" >> error_handler
    validate - "invalid" >> error_handler
    process - "failed" >> error_handler

    # Error recovery
    error_handler - "retry" >> input_node
    error_handler - "abort" >> flow.end

    return flow


# Convenience function for direct execution
def run_{component}(input_data, config=None):
    """
    Execute the {component} flow with given input.

    Args:
        input_data: Initial data for the flow
        config: Optional configuration

    Returns:
        dict: Final shared store state
    """
    flow = create_{component}_flow(config)

    # Initialize shared store
    shared = {
        "input": input_data,
        "timestamp": time.time(),
        "config": config or {}
    }

    return flow.run(shared)
```

### Node Implementation Template

```python
"""
Node implementations for {Component} Flow
"""

from pocketflow import Node
import logging

logger = logging.getLogger(__name__)


class InputNode(Node):
    """
    Load and prepare input data for processing.

    Reads from shared store:
        - input: Raw input data

    Writes to shared store:
        - prepared_data: Processed input ready for validation
        - input_metadata: Metadata about the input

    Actions:
        - "validate": Input loaded successfully
        - "error": Failed to load/prepare input
    """

    def __init__(self):
        # Enable retry for I/O operations
        super().__init__(max_retries=3, wait=1)

    def exec(self, shared):
        try:
            raw_input = shared.get("input")

            if not raw_input:
                shared["error"] = "No input provided"
                return "error"

            # Process input
            prepared = self._prepare_input(raw_input)

            # Store results
            shared["prepared_data"] = prepared
            shared["input_metadata"] = {
                "size": len(prepared),
                "type": type(prepared).__name__
            }

            logger.info(f"Input prepared: {shared['input_metadata']}")
            return "validate"

        except Exception as e:
            logger.error(f"Input preparation failed: {e}")
            shared["error"] = str(e)
            return "error"

    def exec_fallback(self, shared, exc):
        """
        Fallback for persistent failures.
        """
        logger.error(f"Input node failed after retries: {exc}")
        shared["error"] = f"Failed to prepare input: {exc}"
        shared["fallback_used"] = True
        return "error"

    def _prepare_input(self, raw_input):
        # Implementation specific processing
        return raw_input


class ValidateNode(Node):
    """
    Validate prepared data meets requirements.

    Reads from shared store:
        - prepared_data: Data to validate

    Writes to shared store:
        - validation_result: Detailed validation results
        - validation_errors: List of validation errors (if any)

    Actions:
        - "process": Validation passed
        - "invalid": Validation failed
    """

    def exec(self, shared):
        data = shared.get("prepared_data")

        # Perform validation
        errors = self._validate(data)

        if errors:
            shared["validation_errors"] = errors
            shared["validation_result"] = "failed"
            logger.warning(f"Validation failed: {errors}")
            return "invalid"
        else:
            shared["validation_result"] = "passed"
            logger.info("Validation passed")
            return "process"

    def _validate(self, data):
        errors = []

        # Add validation logic
        if not data:
            errors.append("Data is empty")

        # Return list of errors (empty if valid)
        return errors


class ProcessNode(Node):
    """
    Main processing logic for the flow.

    This node should contain the core business logic.
    For complex processing, consider breaking into multiple nodes.
    """

    def __init__(self, config=None):
        super().__init__(max_retries=2)
        self.config = config or {}

    def exec(self, shared):
        data = shared["prepared_data"]

        try:
            # Core processing
            result = self._process(data, shared)

            shared["result"] = result
            shared["process_status"] = "completed"

            return "output"

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            shared["process_error"] = str(e)
            return "failed"

    def exec_fallback(self, shared, exc):
        # Try simplified processing
        try:
            result = self._simple_process(shared["prepared_data"])
            shared["result"] = result
            shared["degraded_mode"] = True
            return "output"
        except:
            return "failed"

    def _process(self, data, shared):
        # Main processing logic
        pass

    def _simple_process(self, data):
        # Simplified fallback logic
        pass


class ErrorHandlerNode(Node):
    """
    Central error handling with recovery options.

    Reads from shared store:
        - error: Error message
        - validation_errors: Validation failures
        - process_error: Processing failures

    Actions:
        - "retry": Attempt retry (if retries remaining)
        - "abort": Give up and exit
    """

    def exec(self, shared):
        # Determine error type
        if "validation_errors" in shared:
            self._handle_validation_error(shared)
        elif "process_error" in shared:
            self._handle_process_error(shared)
        else:
            self._handle_generic_error(shared)

        # Check retry count
        retry_count = shared.get("error_retry_count", 0)

        if retry_count < 3:
            shared["error_retry_count"] = retry_count + 1
            logger.info(f"Retrying after error (attempt {retry_count + 1})")
            return "retry"
        else:
            logger.error("Max retries exceeded, aborting")
            return "abort"

    def _handle_validation_error(self, shared):
        errors = shared["validation_errors"]
        logger.error(f"Validation errors: {errors}")

    def _handle_process_error(self, shared):
        error = shared["process_error"]
        logger.error(f"Processing error: {error}")

    def _handle_generic_error(self, shared):
        error = shared.get("error", "Unknown error")
        logger.error(f"Generic error: {error}")
```

## Testing Template

```python
"""
Tests for {Component} Flow
"""

import pytest
from unittest.mock import Mock, patch
from pflow.flows.{component} import create_{component}_flow
from pflow.flows.{component}.nodes import InputNode, ValidateNode


class Test{Component}Flow:
    """Test the complete flow orchestration."""

    def test_successful_flow(self):
        """Test happy path through the flow."""
        flow = create_{component}_flow()

        shared = {
            "input": "test data"
        }

        result = flow.run(shared)

        assert result["process_status"] == "completed"
        assert "result" in result

    def test_validation_failure(self):
        """Test flow handles validation errors."""
        flow = create_{component}_flow()

        shared = {
            "input": ""  # Invalid empty input
        }

        result = flow.run(shared)

        assert "validation_errors" in result
        assert result["validation_result"] == "failed"

    def test_retry_on_failure(self):
        """Test retry logic works correctly."""
        # Test implementation


class TestNodes:
    """Test individual node implementations."""

    def test_input_node_success(self):
        """Test InputNode processes data correctly."""
        node = InputNode()
        shared = {"input": "test"}

        action = node.exec(shared)

        assert action == "validate"
        assert "prepared_data" in shared

    def test_input_node_missing_input(self):
        """Test InputNode handles missing input."""
        node = InputNode()
        shared = {}

        action = node.exec(shared)

        assert action == "error"
        assert "error" in shared

    @patch('some.external.service')
    def test_process_node_with_mock(self, mock_service):
        """Test ProcessNode with mocked external service."""
        mock_service.return_value = "mocked result"

        node = ProcessNode()
        shared = {"prepared_data": "test"}

        action = node.exec(shared)

        assert action == "output"
        assert shared["result"] == "mocked result"
```

## Best Practices

### 1. Node Design

- **Single Responsibility**: Each node should do one thing well
- **Clear Interface**: Document what the node reads/writes from shared store
- **Explicit Actions**: Return meaningful action strings for routing
- **Error Handling**: Use exec_fallback for graceful degradation

### 2. State Management

```python
# Good: Clear key names
shared["workflow_id"] = generate_id()
shared["validation_errors"] = errors
shared["process_start_time"] = time.time()

# Bad: Ambiguous keys
shared["data"] = data
shared["errors"] = errors
shared["temp"] = temp_value
```

### 3. Error Handling

```python
class RobustNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def exec(self, shared):
        try:
            # Main logic
            return "success"
        except SpecificError as e:
            # Handle specific error
            shared["specific_error"] = str(e)
            return "handle_specific"
        except Exception as e:
            # Generic error
            shared["error"] = str(e)
            return "error"

    def exec_fallback(self, shared, exc):
        # Last resort - graceful degradation
        logger.error(f"All retries failed: {exc}")
        shared["degraded_mode"] = True
        return "continue_degraded"
```

### 4. Logging

- Use structured logging with appropriate levels
- Include context in log messages
- Log at decision points and state changes

### 5. Testing

- Test each node in isolation
- Test complete flows with various paths
- Mock external dependencies
- Test error paths explicitly

## Common Patterns

### Pattern 1: Multi-Path Input

```python
class InputRouterNode(Node):
    def exec(self, shared):
        input_type = shared.get("input_type")

        if input_type == "file":
            return "load_file"
        elif input_type == "api":
            return "fetch_api"
        elif input_type == "stdin":
            return "read_stdin"
        else:
            return "prompt_user"
```

### Pattern 2: Progressive Enhancement

```python
class EnhancedProcessNode(Node):
    def exec(self, shared):
        # Try advanced processing first
        if shared.get("advanced_mode"):
            try:
                result = self._advanced_process(shared)
                shared["process_mode"] = "advanced"
                return "success"
            except:
                # Fall through to basic
                pass

        # Basic processing
        result = self._basic_process(shared)
        shared["process_mode"] = "basic"
        return "success"
```

### Pattern 3: Accumulating Results

```python
class CollectorNode(Node):
    def exec(self, shared):
        # Initialize results list if needed
        if "results" not in shared:
            shared["results"] = []

        # Add current result
        current = self._process_current(shared)
        shared["results"].append(current)

        # Check if more to process
        if shared.get("has_more"):
            return "process_next"
        else:
            return "aggregate_results"
```

## Migration Checklist

When implementing a task with PocketFlow:

- [ ] Create directory structure under `src/pflow/flows/`
- [ ] Define clear node boundaries (what does each node do?)
- [ ] Document shared store keys for each node
- [ ] Implement nodes with proper error handling
- [ ] Create the main flow with all paths
- [ ] Add comprehensive tests
- [ ] Document the component in README.md
- [ ] Update CLAUDE.md if needed

## Task-Specific Implementation Guides

Detailed implementation guides are available for each PocketFlow-based task:

- **Task 4**: [IR-to-PocketFlow Compiler](/.taskmaster/tasks/task_4/pocketflow-implementation-guide.md)
- **Task 8**: [Shell Integration](/.taskmaster/tasks/task_8/pocketflow-implementation-guide.md)
- **Task 17**: [LLM-based Workflow Generation](/.taskmaster/tasks/task_17/pocketflow-implementation-guide.md)
- **Task 20**: [Lockfile and Plan Storage](/.taskmaster/tasks/task_20/pocketflow-implementation-guide.md)
- **Task 22**: [Shared Store Runtime](/.taskmaster/tasks/task_22/pocketflow-implementation-guide.md)
- **Task 23**: [Tracing and Logging](/.taskmaster/tasks/task_23/pocketflow-implementation-guide.md)

## References

- [PocketFlow Documentation](pocketflow/docs/)
- [PocketFlow Cookbook](pocketflow/cookbook/)
- [ADR-001: Use PocketFlow for Orchestration](docs/architecture/adr/001-use-pocketflow-for-orchestration.md)
