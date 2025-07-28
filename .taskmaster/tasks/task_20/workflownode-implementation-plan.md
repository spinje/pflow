# WorkflowNode Step-by-Step Implementation Plan

## Overview

This document provides a precise, actionable implementation plan for adding WorkflowNode to pflow. The implementation is broken into atomic steps that can be executed independently or in parallel using subagents.

## Prerequisites

- Familiarity with pflow architecture
- Understanding of PocketFlow's Node lifecycle
- Python 3.8+ development environment
- All tests passing before starting

## Implementation Steps

### Phase 1: Core Implementation (Can be done in parallel)

#### Step 1.1: Create WorkflowNode Package Structure

**Task**: Create the basic package structure for WorkflowNode

```bash
mkdir -p src/pflow/nodes/workflow
touch src/pflow/nodes/workflow/__init__.py
touch src/pflow/nodes/workflow/workflow_node.py
```

**File**: `src/pflow/nodes/workflow/__init__.py`
```python
"""Workflow execution node for nested workflow support."""
from .workflow_node import WorkflowNode

__all__ = ["WorkflowNode"]
```

#### Step 1.2: Implement WorkflowNode Class

**Task**: Implement the complete WorkflowNode class with all safety checks

**File**: `src/pflow/nodes/workflow/workflow_node.py`

```python
"""A node that executes another workflow as a sub-workflow."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pocketflow import BaseNode
from pflow.runtime import compile_ir_to_flow
from pflow.runtime.template_resolver import TemplateResolver


class WorkflowNode(BaseNode):
    """Execute another workflow as a sub-workflow.

    This node enables workflow composition by loading and executing
    other workflows with controlled parameter passing and storage isolation.

    Inputs:
        - Any keys defined in param_mapping will be read from shared store

    Outputs:
        - Keys defined in output_mapping will be written to shared store

    Parameters:
        - workflow_ref (str): Path to workflow file (absolute or relative)
        - workflow_ir (dict): Inline workflow definition (alternative to ref)
        - param_mapping (dict): Map parent values to child parameters
        - output_mapping (dict): Map child outputs to parent keys
        - storage_mode (str): "mapped" (default), "scoped", "isolated", or "shared"
        - max_depth (int): Maximum nesting depth (default: 10)
        - error_action (str): Action to return on error (default: "error")

    Actions:
        - default: Workflow executed successfully
        - error: Workflow execution failed (or custom error_action)
    """

    # Class-level constants
    MAX_DEPTH_DEFAULT = 10
    RESERVED_KEY_PREFIX = "_pflow_"

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Load and prepare the sub-workflow for execution."""
        # Get parameters with defaults
        workflow_ref = self.params.get("workflow_ref")
        workflow_ir = self.params.get("workflow_ir")
        max_depth = self.params.get("max_depth", self.MAX_DEPTH_DEFAULT)

        # Validate inputs
        if not workflow_ref and not workflow_ir:
            raise ValueError("Either 'workflow_ref' or 'workflow_ir' must be provided")
        if workflow_ref and workflow_ir:
            raise ValueError("Only one of 'workflow_ref' or 'workflow_ir' should be provided")

        # Check nesting depth
        current_depth = shared.get(f"{self.RESERVED_KEY_PREFIX}depth", 0)
        if current_depth >= max_depth:
            raise RecursionError(f"Maximum workflow nesting depth ({max_depth}) exceeded")

        # Track execution stack for circular dependency detection
        execution_stack = shared.get(f"{self.RESERVED_KEY_PREFIX}stack", [])

        # Load workflow
        if workflow_ref:
            # Validate path security
            workflow_path = self._resolve_safe_path(workflow_ref, shared)

            # Check circular dependency
            if str(workflow_path) in execution_stack:
                cycle = " -> ".join(execution_stack + [str(workflow_path)])
                raise ValueError(f"Circular workflow reference detected: {cycle}")

            # Load workflow file
            workflow_ir = self._load_workflow_file(workflow_path)

        # Prepare child parameters
        param_mapping = self.params.get("param_mapping", {})
        child_params = self._resolve_parameter_mappings(param_mapping, shared)

        return {
            "workflow_ir": workflow_ir,
            "workflow_path": str(workflow_path) if workflow_ref else "<inline>",
            "child_params": child_params,
            "storage_mode": self.params.get("storage_mode", "mapped"),
            "current_depth": current_depth,
            "execution_stack": execution_stack
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Compile and execute the sub-workflow."""
        workflow_ir = prep_res["workflow_ir"]
        workflow_path = prep_res["workflow_path"]
        child_params = prep_res["child_params"]
        storage_mode = prep_res["storage_mode"]

        # Get registry from shared storage (if available)
        registry = self.params.get("__registry__")

        try:
            # Compile the sub-workflow
            sub_flow = compile_ir_to_flow(
                workflow_ir,
                registry=registry,
                initial_params=child_params,
                validate_templates=True
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to compile sub-workflow: {str(e)}",
                "workflow_path": workflow_path
            }

        # Create appropriate storage for child
        child_storage = self._create_child_storage(
            self.params.get("__shared__", {}),  # Parent shared storage
            storage_mode,
            prep_res
        )

        try:
            # Execute the sub-workflow
            result = sub_flow.run(child_storage)

            return {
                "success": True,
                "result": result,
                "child_storage": child_storage,
                "storage_mode": storage_mode
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Sub-workflow execution failed: {str(e)}",
                "workflow_path": workflow_path,
                "child_storage": child_storage
            }

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
             exec_res: Dict[str, Any]) -> str:
        """Process results and update parent storage."""
        if not exec_res.get("success", False):
            # Handle failure
            error_msg = exec_res.get("error", "Unknown error")
            workflow_path = exec_res.get("workflow_path", "<unknown>")

            # Store error in shared storage
            shared["error"] = f"WorkflowNode failed at {workflow_path}: {error_msg}"

            # Return error action
            return self.params.get("error_action", "error")

        # Success - apply output mappings
        output_mapping = self.params.get("output_mapping", {})
        if output_mapping and exec_res.get("storage_mode") != "shared":
            child_storage = exec_res.get("child_storage", {})

            for child_key, parent_key in output_mapping.items():
                # Skip reserved keys
                if parent_key.startswith(self.RESERVED_KEY_PREFIX):
                    continue

                if child_key in child_storage:
                    shared[parent_key] = child_storage[child_key]

        # Return result action or default
        child_result = exec_res.get("result")
        if isinstance(child_result, str):
            return child_result
        return "default"

    def _resolve_safe_path(self, workflow_ref: str, shared: Dict[str, Any]) -> Path:
        """Resolve workflow path."""
        # Convert to Path object
        path = Path(workflow_ref)

        # If relative, resolve from parent workflow location
        if not path.is_absolute():
            parent_file = shared.get(f"{self.RESERVED_KEY_PREFIX}workflow_file")
            if parent_file:
                base_dir = Path(parent_file).parent
                path = base_dir / path
            else:
                # Resolve from current working directory
                path = Path.cwd() / path

        # Return resolved absolute path
        return path.resolve()

    def _load_workflow_file(self, path: Path) -> Dict[str, Any]:
        """Load workflow from file."""
        # Check file exists
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {path}")

        # Load and parse JSON
        try:
            with open(path, 'r') as f:
                workflow_ir = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in workflow file: {e}")
        except Exception as e:
            raise IOError(f"Error reading workflow file: {e}")

        # Basic validation
        if not isinstance(workflow_ir, dict):
            raise ValueError("Workflow must be a JSON object")
        if "nodes" not in workflow_ir:
            raise ValueError("Workflow must contain 'nodes' array")

        return workflow_ir

    def _resolve_parameter_mappings(self, param_mapping: Dict[str, Any],
                                   shared: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve parameter mappings using template resolution."""
        if not param_mapping:
            return {}

        # Build resolution context
        context = dict(shared)

        # Resolve each parameter
        resolved = {}
        for child_param, parent_value in param_mapping.items():
            if isinstance(parent_value, str) and TemplateResolver.has_templates(parent_value):
                # Resolve template
                try:
                    resolved[child_param] = TemplateResolver.resolve_string(parent_value, context)
                except Exception as e:
                    raise ValueError(f"Failed to resolve parameter '{child_param}': {e}")
            else:
                # Static value
                resolved[child_param] = parent_value

        return resolved

    def _create_child_storage(self, parent_shared: Dict[str, Any],
                             storage_mode: str, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Create storage for child workflow based on isolation mode."""
        # Update depth and stack for child
        child_depth = prep_res["current_depth"] + 1
        child_stack = prep_res["execution_stack"] + [prep_res["workflow_path"]]

        if storage_mode == "mapped":
            # Only mapped parameters available
            child_storage = prep_res["child_params"].copy()

        elif storage_mode == "isolated":
            # Completely empty storage
            child_storage = {}

        elif storage_mode == "scoped":
            # Filtered view of parent storage
            prefix = self.params.get("scope_prefix", "child_")
            child_storage = {
                k[len(prefix):]: v
                for k, v in parent_shared.items()
                if k.startswith(prefix) and not k.startswith(self.RESERVED_KEY_PREFIX)
            }
            # Also include mapped parameters
            child_storage.update(prep_res["child_params"])

        elif storage_mode == "shared":
            # Direct reference to parent storage (dangerous!)
            child_storage = parent_shared

        else:
            raise ValueError(f"Invalid storage_mode: {storage_mode}")

        # Always set execution context
        child_storage[f"{self.RESERVED_KEY_PREFIX}depth"] = child_depth
        child_storage[f"{self.RESERVED_KEY_PREFIX}stack"] = child_stack
        child_storage[f"{self.RESERVED_KEY_PREFIX}workflow_file"] = prep_res["workflow_path"]

        # Pass through registry if available
        if "__registry__" in self.params:
            child_storage["__registry__"] = self.params["__registry__"]

        return child_storage
```

#### Step 1.3: Add Exception Classes

**Task**: Add WorkflowNode-specific exceptions

**File**: `src/pflow/core/exceptions.py`

Add at the end of the file:

```python
class WorkflowExecutionError(PflowError):
    """Error during nested workflow execution."""

    def __init__(self, message: str, workflow_path: Optional[List[str]] = None,
                 original_error: Optional[Exception] = None):
        self.workflow_path = workflow_path or []
        self.original_error = original_error

        # Build detailed message
        if workflow_path:
            path_str = " -> ".join(workflow_path)
            message = f"{message}\nWorkflow path: {path_str}"
        if original_error:
            message = f"{message}\nOriginal error: {str(original_error)}"

        super().__init__(message)


class CircularWorkflowReferenceError(WorkflowExecutionError):
    """Circular reference detected in workflow execution."""
    pass
```

### Phase 2: Testing (Can be done in parallel with Phase 1)

#### Step 2.1: Create Test Directory Structure

**Task**: Set up test infrastructure

```bash
mkdir -p tests/test_nodes/test_workflow
touch tests/test_nodes/test_workflow/__init__.py
touch tests/test_nodes/test_workflow/test_workflow_node.py
touch tests/test_nodes/test_workflow/test_integration.py
```

#### Step 2.2: Create Unit Tests

**File**: `tests/test_nodes/test_workflow/test_workflow_node.py`

```python
"""Unit tests for WorkflowNode."""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from pflow.nodes.workflow import WorkflowNode
from pflow.core.exceptions import WorkflowExecutionError


class TestWorkflowNode:
    """Test WorkflowNode functionality."""

    def test_node_creation(self):
        """Test basic node instantiation."""
        node = WorkflowNode()
        assert node is not None
        assert hasattr(node, 'prep')
        assert hasattr(node, 'exec')
        assert hasattr(node, 'post')

    def test_parameter_validation(self):
        """Test parameter validation in prep phase."""
        node = WorkflowNode()
        shared = {}

        # No parameters should raise error
        node.set_params({})
        with pytest.raises(ValueError, match="Either 'workflow_ref' or 'workflow_ir'"):
            node.prep(shared)

        # Both parameters should raise error
        node.set_params({
            "workflow_ref": "test.json",
            "workflow_ir": {"nodes": []}
        })
        with pytest.raises(ValueError, match="Only one of"):
            node.prep(shared)

    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        node = WorkflowNode()

        # Set up circular reference
        shared = {
            "_pflow_stack": ["/path/to/workflow1.json", "/path/to/workflow2.json"]
        }

        node.set_params({
            "workflow_ref": "/path/to/workflow1.json"  # Already in stack
        })

        with pytest.raises(ValueError, match="Circular workflow reference"):
            node.prep(shared)

    def test_max_depth_enforcement(self):
        """Test maximum nesting depth."""
        node = WorkflowNode()

        shared = {
            "_pflow_depth": 10  # Already at max depth
        }

        node.set_params({
            "workflow_ir": {"nodes": []},
            "max_depth": 10
        })

        with pytest.raises(RecursionError, match="Maximum workflow nesting depth"):
            node.prep(shared)

    def test_parameter_mapping(self):
        """Test parameter mapping resolution."""
        node = WorkflowNode()

        shared = {
            "input_data": "test_value",
            "config": {"api_key": "secret"}
        }

        node.set_params({
            "workflow_ir": {"nodes": []},
            "param_mapping": {
                "data": "$input_data",
                "key": "$config.api_key",
                "static": "fixed_value"
            }
        })

        prep_res = node.prep(shared)

        assert prep_res["child_params"]["data"] == "test_value"
        assert prep_res["child_params"]["key"] == "secret"
        assert prep_res["child_params"]["static"] == "fixed_value"

    def test_storage_modes(self):
        """Test different storage isolation modes."""
        node = WorkflowNode()
        parent_shared = {
            "parent_data": "value",
            "child_data": "child_value",
            "_pflow_internal": "reserved"
        }

        prep_res = {
            "child_params": {"param": "value"},
            "current_depth": 0,
            "execution_stack": [],
            "workflow_path": "test.json"
        }

        # Test mapped mode
        storage = node._create_child_storage(parent_shared, "mapped", prep_res)
        assert storage["param"] == "value"
        assert "parent_data" not in storage

        # Test isolated mode
        storage = node._create_child_storage(parent_shared, "isolated", prep_res)
        assert len([k for k in storage if not k.startswith("_pflow_")]) == 0

        # Test scoped mode
        node.set_params({"scope_prefix": "child_"})
        storage = node._create_child_storage(parent_shared, "scoped", prep_res)
        assert storage["data"] == "child_value"
        assert "parent_data" not in storage

        # Test shared mode
        storage = node._create_child_storage(parent_shared, "shared", prep_res)
        assert storage is parent_shared  # Same reference
```

#### Step 2.3: Create Integration Tests

**File**: `tests/test_nodes/test_workflow/test_integration.py`

```python
"""Integration tests for WorkflowNode with full workflow execution."""
import json
import tempfile
from pathlib import Path

import pytest

from pflow.nodes.workflow import WorkflowNode
from pflow.runtime import compile_ir_to_flow
from pocketflow import Flow


class TestWorkflowNodeIntegration:
    """Integration tests for WorkflowNode."""

    @pytest.fixture
    def simple_workflow_ir(self):
        """Create a simple test workflow IR."""
        return {
            "nodes": [
                {
                    "id": "echo",
                    "type": "pflow.nodes.test.echo",  # Assuming test node exists
                    "params": {"message": "$input_message"}
                }
            ],
            "edges": []
        }

    @pytest.fixture
    def workflow_file(self, simple_workflow_ir, tmp_path):
        """Create a temporary workflow file."""
        workflow_path = tmp_path / "test_workflow.json"
        with open(workflow_path, 'w') as f:
            json.dump(simple_workflow_ir, f)
        return workflow_path

    def test_inline_workflow_execution(self, simple_workflow_ir, mock_registry):
        """Test executing an inline workflow."""
        # Create parent workflow with WorkflowNode
        parent_ir = {
            "nodes": [
                {
                    "id": "sub",
                    "type": "workflow",
                    "params": {
                        "workflow_ir": simple_workflow_ir,
                        "param_mapping": {
                            "input_message": "$message"
                        },
                        "output_mapping": {
                            "echo_result": "result"
                        }
                    }
                }
            ],
            "edges": []
        }

        # Compile and run
        flow = compile_ir_to_flow(parent_ir, registry=mock_registry)
        shared = {"message": "Hello from parent"}
        result = flow.run(shared)

        assert result == "default"
        assert shared.get("result") == "Hello from parent"

    def test_file_workflow_execution(self, workflow_file, mock_registry):
        """Test loading and executing workflow from file."""
        parent_ir = {
            "nodes": [
                {
                    "id": "sub",
                    "type": "workflow",
                    "params": {
                        "workflow_ref": str(workflow_file),
                        "param_mapping": {
                            "input_message": "Hello from file"
                        }
                    }
                }
            ],
            "edges": []
        }

        flow = compile_ir_to_flow(parent_ir, registry=mock_registry)
        shared = {}
        result = flow.run(shared)

        assert result == "default"

    def test_nested_workflow_execution(self, mock_registry):
        """Test workflows calling other workflows."""
        # Create a deeply nested structure
        level3 = {
            "nodes": [{"id": "leaf", "type": "echo", "params": {"message": "Level 3"}}],
            "edges": []
        }

        level2 = {
            "nodes": [
                {
                    "id": "l2",
                    "type": "workflow",
                    "params": {"workflow_ir": level3}
                }
            ],
            "edges": []
        }

        level1 = {
            "nodes": [
                {
                    "id": "l1",
                    "type": "workflow",
                    "params": {"workflow_ir": level2}
                }
            ],
            "edges": []
        }

        flow = compile_ir_to_flow(level1, registry=mock_registry)
        shared = {}
        result = flow.run(shared)

        assert result == "default"
        # Check depth was tracked
        assert "_pflow_depth" in shared
```

### Phase 3: Documentation

#### Step 3.1: Update Node Reference Documentation

**File**: `docs/reference/node-reference.md`

Add a new section:

```markdown
### Workflow Execution Nodes

#### WorkflowNode

Executes another workflow as a sub-workflow with parameter mapping and storage isolation.

**Type**: `workflow`

**Parameters**:
- `workflow_ref` (string): Path to workflow JSON file
- `workflow_ir` (object): Inline workflow definition
- `param_mapping` (object): Map parent values to child parameters
- `output_mapping` (object): Map child outputs to parent storage
- `storage_mode` (string): Storage isolation mode - "mapped", "isolated", "scoped", or "shared"
- `max_depth` (integer): Maximum nesting depth (default: 10)
- `error_action` (string): Action to return on error (default: "error")

**Example**:
```json
{
  "id": "analyze_data",
  "type": "workflow",
  "params": {
    "workflow_ref": "~/.pflow/workflows/analyzer.json",
    "param_mapping": {
      "input_data": "$raw_data",
      "config": "$analysis_config"
    },
    "output_mapping": {
      "analysis_result": "processed_data"
    },
    "storage_mode": "mapped"
  }
}
```
```

#### Step 3.2: Create WorkflowNode Usage Guide

**File**: `docs/features/nested-workflows.md`

Create comprehensive usage documentation covering:
- When to use nested workflows
- Parameter mapping examples
- Storage isolation strategies
- Error handling patterns
- Best practices

### Phase 4: Integration and Validation

#### Step 4.1: Run Tests

```bash
# Run all tests to ensure nothing broke
make test

# Run specific workflow tests
pytest tests/test_nodes/test_workflow/ -v
```

#### Step 4.2: Manual Testing

Create test workflows and verify:
1. Simple nested execution works
2. Parameter mapping functions correctly
3. Error propagation preserves context
4. Circular dependencies are caught
5. Resource limits are enforced

#### Step 4.3: Update Examples

Create example workflows in `examples/nested/`:
- Basic nested workflow
- Parameter mapping showcase
- Error handling example
- Multi-level nesting

## Parallelization Strategy

The following tasks can be done in parallel by subagents:

**Agent 1**: Core Implementation (Steps 1.1, 1.2, 1.3)
**Agent 2**: Test Implementation (Steps 2.1, 2.2, 2.3)
**Agent 3**: Documentation (Steps 3.1, 3.2)

Synchronization points:
- After Phase 1-3: Integration testing
- After all phases: Final validation

## Risk Mitigation

1. **Before Starting**: Create a feature branch
2. **During Development**: Run tests frequently
3. **Code Review**: Focus on error handling and test coverage
4. **Performance Testing**: Test with deeply nested workflows
5. **Documentation Review**: Ensure all edge cases are documented

## Success Criteria

- [ ] All tests pass
- [ ] No performance regression in existing workflows
- [ ] Clear error messages for all failure modes
- [ ] Documentation complete and reviewed
- [ ] Examples demonstrate key features
- [ ] Code follows project style guidelines

## Next Steps After Implementation

1. Monitor for issues in real-world usage
2. Consider workflow caching optimization
3. Implement workflow registry if needed
4. Add async execution support
5. Create visual debugging tools
