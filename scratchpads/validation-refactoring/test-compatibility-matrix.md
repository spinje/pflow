# Test Compatibility Matrix for Validation Refactoring

## Overview
This document maps out exactly what tests need to change (or not) during the validation refactoring to ensure we don't break existing functionality.

## Test Impact Analysis

### 🟢 Tests That Should NOT Change (Must Pass As-Is)

#### 1. `/tests/test_planning/unit/test_validator_node.py` (if exists)
- **Why unchanged**: ValidatorNode.exec() maintains same interface
- **What it tests**: Validation error formatting, retry logic
- **Expected result**: 100% pass without modification

#### 2. `/tests/test_planning/llm/prompts/test_workflow_generator_prompt.py`
- **Why unchanged**: Only internal implementation changes
- **What it tests**: Workflow generation quality
- **Expected result**: Same accuracy (100% currently)
- **Minor change allowed**: Import path for validation function

#### 3. `/tests/test_runtime/test_template_validator.py`
- **Why unchanged**: TemplateValidator interface unchanged
- **What it tests**: Template variable validation
- **Expected result**: 100% pass without modification

#### 4. `/tests/test_core/test_ir_schema.py`
- **Why unchanged**: validate_ir() function unchanged
- **What it tests**: Structural validation
- **Expected result**: 100% pass without modification

### 🟡 Tests That Need Minor Updates (Import Changes Only)

#### 1. Any test importing from ValidatorNode
```python
# OLD
from pflow.planning.nodes import ValidatorNode
node = ValidatorNode()
errors = node._validate_node_types(workflow)  # If accessing private method

# NEW
from pflow.core.workflow_validator import WorkflowValidator
errors = WorkflowValidator._validate_node_types(workflow, registry)
```

### 🔴 Tests That Need NEW Test Cases (But Existing Tests Still Pass)

#### 1. ValidatorNode Tests
**New test cases to add**:
```python
def test_validator_catches_forward_references():
    """ValidatorNode should now catch forward references."""
    validator = ValidatorNode()
    workflow = create_workflow_with_forward_reference()
    prep_res = {"workflow": workflow, "extracted_params": {}}
    result = validator.exec(prep_res)
    assert any("forward reference" in e for e in result["errors"])

def test_validator_catches_circular_dependencies():
    """ValidatorNode should now catch circular dependencies."""
    # Similar to above

def test_validator_catches_wrong_execution_order():
    """ValidatorNode should now catch execution order issues."""
    # Similar to above
```

### 🆕 Completely NEW Test Files

#### 1. `/tests/test_core/test_workflow_data_flow.py`
```python
"""Test the NEW data flow validation module."""

import pytest
from pflow.core.workflow_data_flow import (
    validate_data_flow,
    build_execution_order,
    CycleError
)

class TestDataFlowValidation:
    """Test data flow validation logic."""

    def test_forward_reference_detection(self):
        """Test detection of forward references."""
        workflow = {
            "nodes": [
                {"id": "node2", "type": "llm", "params": {"data": "${node1.output}"}},
                {"id": "node1", "type": "read-file", "params": {"file": "test.txt"}}
            ],
            "edges": [{"from": "node2", "to": "node1"}],  # Wrong order!
            "inputs": {}
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert "node2" in errors[0]
        assert "node1" in errors[0]
        assert "after" in errors[0].lower() or "forward" in errors[0].lower()

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        workflow = {
            "nodes": [
                {"id": "a", "type": "llm", "params": {"data": "${b.output}"}},
                {"id": "b", "type": "llm", "params": {"data": "${c.output}"}},
                {"id": "c", "type": "llm", "params": {"data": "${a.output}"}}
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"}  # Creates cycle!
            ],
            "inputs": {}
        }
        with pytest.raises(CycleError):
            build_execution_order(workflow)

    def test_valid_linear_flow(self):
        """Test that valid linear workflows pass."""
        workflow = {
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file": "input.txt"}},
                {"id": "process", "type": "llm", "params": {"prompt": "Process: ${read.content}"}},
                {"id": "write", "type": "write-file", "params": {"content": "${process.response}"}}
            ],
            "edges": [
                {"from": "read", "to": "process"},
                {"from": "process", "to": "write"}
            ],
            "inputs": {}
        }
        errors = validate_data_flow(workflow)
        assert errors == []

    def test_parallel_execution_branches(self):
        """Test workflows with parallel branches."""
        workflow = {
            "nodes": [
                {"id": "input", "type": "read-file", "params": {"file": "data.txt"}},
                {"id": "branch1", "type": "llm", "params": {"data": "${input.content}"}},
                {"id": "branch2", "type": "llm", "params": {"data": "${input.content}"}},
                {"id": "merge", "type": "write-file", "params": {
                    "content": "${branch1.output} + ${branch2.output}"
                }}
            ],
            "edges": [
                {"from": "input", "to": "branch1"},
                {"from": "input", "to": "branch2"},
                {"from": "branch1", "to": "merge"},
                {"from": "branch2", "to": "merge"}
            ],
            "inputs": {}
        }
        errors = validate_data_flow(workflow)
        assert errors == []  # Valid parallel execution

    def test_disconnected_nodes(self):
        """Test handling of disconnected nodes."""
        workflow = {
            "nodes": [
                {"id": "node1", "type": "read-file", "params": {"file": "a.txt"}},
                {"id": "node2", "type": "read-file", "params": {"file": "b.txt"}},
                {"id": "orphan", "type": "write-file", "params": {"content": "test"}}
            ],
            "edges": [
                {"from": "node1", "to": "node2"}
                # orphan has no edges!
            ],
            "inputs": {}
        }
        order = build_execution_order(workflow)
        assert "orphan" in order  # Should still be included

        # But referencing orphan from earlier nodes should fail
        workflow["nodes"][0]["params"]["data"] = "${orphan.output}"
        errors = validate_data_flow(workflow)
        assert len(errors) > 0  # Can't reference disconnected future node
```

#### 2. `/tests/test_core/test_workflow_validator.py`
```python
"""Test the unified WorkflowValidator."""

import pytest
from pflow.core.workflow_validator import WorkflowValidator
from pflow.registry import Registry

class TestWorkflowValidator:
    """Test unified validation orchestration."""

    def test_complete_validation_all_checks(self):
        """Test that all validation types run."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "${input_file}"}},
                {"id": "n2", "type": "llm", "params": {"prompt": "${n1.content}"}}
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "inputs": {
                "input_file": {"type": "string", "required": True}
            }
        }

        errors = WorkflowValidator.validate(
            workflow,
            extracted_params={"input_file": "test.txt"},
            registry=Registry()
        )

        assert errors == []  # Valid workflow

    def test_skip_node_types_for_mocks(self):
        """Test selective validation skipping."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "mock-node", "params": {"data": "test"}}
            ],
            "edges": [],
            "inputs": {}
        }

        # With node type validation - should fail
        errors = WorkflowValidator.validate(
            workflow,
            registry=Registry(),
            skip_node_types=False
        )
        assert any("Unknown node type" in e for e in errors)

        # Without node type validation - should pass
        errors = WorkflowValidator.validate(
            workflow,
            registry=Registry(),
            skip_node_types=True
        )
        assert not any("Unknown node type" in e for e in errors)

    def test_partial_validation_no_params(self):
        """Test validation without extracted params."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "${missing_param}"}}
            ],
            "edges": [],
            "inputs": {"missing_param": {"type": "string"}}
        }

        # Without extracted_params - skips template validation
        errors = WorkflowValidator.validate(workflow)
        assert not any("missing_param" in e for e in errors)

        # With extracted_params - catches missing param
        errors = WorkflowValidator.validate(
            workflow,
            extracted_params={}  # Empty params
        )
        assert any("missing_param" in e for e in errors)

    def test_accumulates_all_error_types(self):
        """Test that all error types are collected."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "unknown-node", "params": {"data": "${n2.output}"}},
                {"id": "n2", "type": "another-unknown", "params": {"data": "test"}}
            ],
            "edges": [{"from": "n1", "to": "n2"}],  # Wrong order
            "inputs": {}
        }

        errors = WorkflowValidator.validate(
            workflow,
            extracted_params={},
            registry=Registry()
        )

        # Should have multiple error types
        assert any("Unknown node type" in e for e in errors)  # Node type error
        assert any("forward" in e.lower() or "after" in e.lower() for e in errors)  # Data flow error
```

## Regression Test Checklist

Before merging the refactoring, verify:

### ✅ Existing Tests Pass
- [ ] `pytest tests/test_planning/llm/prompts/test_workflow_generator_prompt.py` - 100% pass
- [ ] `pytest tests/test_runtime/test_template_validator.py` - 100% pass
- [ ] `pytest tests/test_core/test_ir_schema.py` - 100% pass
- [ ] `pytest tests/test_planning/` - All planning tests pass

### ✅ New Tests Pass
- [ ] `pytest tests/test_core/test_workflow_data_flow.py` - 100% pass
- [ ] `pytest tests/test_core/test_workflow_validator.py` - 100% pass

### ✅ Integration Works
- [ ] Run full planner with test workflow - validates correctly
- [ ] Run workflow_generator with real validation - catches data flow issues
- [ ] Performance benchmark - < 100ms added for typical workflow

## Key Testing Principles

1. **Preserve Behavior**: Existing tests must pass without logic changes
2. **Test New Functionality**: Data flow validation needs comprehensive tests
3. **Test Integration Points**: Verify ValidatorNode uses new validation
4. **Test Error Messages**: Ensure errors are actionable and clear
5. **Test Performance**: Ensure no significant slowdown

## What We're NOT Testing

1. **Old implementation details**: Private methods that are being replaced
2. **Intermediate states**: Only test final refactored state
3. **Mock validation logic**: Tests with mocks skip real validation anyway

## Migration Testing Strategy

### Phase 1: Parallel Testing
1. Keep old validation in ValidatorNode
2. Add new WorkflowValidator in parallel
3. Log when results differ
4. Fix any discrepancies

### Phase 2: Shadow Mode
1. Use WorkflowValidator as primary
2. Keep old validation as fallback
3. Monitor for any issues
4. Remove fallback after stability

### Phase 3: Full Migration
1. Remove old validation code
2. All tests use WorkflowValidator
3. Clean up any remaining duplication

## Success Metrics

1. **Zero regression**: All existing tests pass
2. **New coverage**: Data flow validation > 90% coverage
3. **Performance**: < 100ms impact on validation time
4. **Error quality**: Clear, actionable error messages
5. **Code reduction**: Net reduction in duplicated code