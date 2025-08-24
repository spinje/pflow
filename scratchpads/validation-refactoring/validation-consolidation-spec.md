# Validation Consolidation Specification

## Executive Summary

Consolidate all workflow validation logic into a single, reusable system that ensures production has the same (or better) validation than tests. Currently, tests have data flow validation that production lacks, creating a dangerous gap where workflows could pass production validation but fail at runtime.

## Problem Statement

### Current State
1. **ValidatorNode** performs:
   - Structural validation (via `validate_ir`)
   - Template validation (via `TemplateValidator`)
   - Node type validation (custom method)

2. **Tests** perform:
   - All of the above
   - PLUS data flow validation (execution order, forward references)

3. **Gap**: Production misses critical data flow validation that could cause runtime failures

### Risks
- Workflow with wrong execution order passes validation but fails at runtime
- Node referencing future node's output passes validation but fails at runtime
- Circular dependencies not detected until execution

## Proposed Solution

### Core Architecture

```
src/pflow/core/
├── workflow_validator.py         # NEW: Unified validation orchestrator
├── workflow_data_flow.py        # NEW: Data flow validation (from tests)
├── ir_schema.py                 # EXISTING: Structural validation
└── ...

src/pflow/runtime/
├── template_validator.py        # EXISTING: Template validation
└── ...

src/pflow/planning/
├── nodes.py                     # MODIFIED: ValidatorNode uses WorkflowValidator
└── ...
```

### New Components

#### 1. `/src/pflow/core/workflow_data_flow.py`
```python
"""Data flow validation for workflow execution order and dependencies.

This module ensures that workflows have correct execution order and that
all data dependencies are satisfied before nodes execute.
"""

from typing import Any, Optional

class CycleError(Exception):
    """Raised when circular dependency is detected."""
    pass

def build_execution_order(workflow_ir: dict[str, Any]) -> list[str]:
    """Build topological execution order of nodes.

    Args:
        workflow_ir: Workflow IR with nodes and edges

    Returns:
        List of node IDs in execution order

    Raises:
        CycleError: If circular dependency detected
    """
    # Implementation from test_workflow_generator_prompt.py
    ...

def validate_data_flow(workflow_ir: dict[str, Any]) -> list[str]:
    """Validate that data flows correctly between nodes.

    Checks:
    - No forward references (node can't reference future node's output)
    - No circular dependencies
    - All node references exist
    - Template variables reference nodes that execute before them

    Args:
        workflow_ir: The workflow IR to validate

    Returns:
        List of error messages (empty if valid)
    """
    # Implementation from test's validate_data_flow
    ...
```

#### 2. `/src/pflow/core/workflow_validator.py`
```python
"""Unified workflow validation system.

This module provides the single source of truth for all workflow validation,
ensuring consistency between production, tests, and any other consumers.
"""

from typing import Any, Optional
from pflow.registry import Registry

class WorkflowValidator:
    """Orchestrates all workflow validation checks."""

    @staticmethod
    def validate(
        workflow_ir: dict[str, Any],
        extracted_params: Optional[dict[str, Any]] = None,
        registry: Optional[Registry] = None,
        skip_node_types: bool = False
    ) -> list[str]:
        """Run complete workflow validation.

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry (uses default if None)
            skip_node_types: Skip node type validation (for mock nodes)

        Returns:
            List of all validation errors
        """
        errors = []

        # 1. Structural validation (ALWAYS run)
        struct_errors = WorkflowValidator._validate_structure(workflow_ir)
        errors.extend(struct_errors)

        # 2. Data flow validation (NEW - ALWAYS run)
        flow_errors = WorkflowValidator._validate_data_flow(workflow_ir)
        errors.extend(flow_errors)

        # 3. Template validation (if params provided)
        if extracted_params is not None:
            template_errors = WorkflowValidator._validate_templates(
                workflow_ir, extracted_params, registry
            )
            errors.extend(template_errors)

        # 4. Node type validation (if not skipped)
        if not skip_node_types and registry:
            type_errors = WorkflowValidator._validate_node_types(
                workflow_ir, registry
            )
            errors.extend(type_errors)

        return errors

    @staticmethod
    def _validate_structure(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate IR structure and schema compliance."""
        from pflow.core.ir_schema import validate_ir
        try:
            validate_ir(workflow_ir)
            return []
        except Exception as e:
            return [f"Structure: {str(e)}"]

    @staticmethod
    def _validate_data_flow(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate execution order and data dependencies."""
        from pflow.core.workflow_data_flow import validate_data_flow
        try:
            return validate_data_flow(workflow_ir)
        except Exception as e:
            return [f"Data flow: {str(e)}"]

    @staticmethod
    def _validate_templates(
        workflow_ir: dict[str, Any],
        extracted_params: dict[str, Any],
        registry: Optional[Registry]
    ) -> list[str]:
        """Validate template variables and parameters."""
        from pflow.runtime.template_validator import TemplateValidator
        if registry is None:
            registry = Registry()
        return TemplateValidator.validate_workflow_templates(
            workflow_ir, extracted_params, registry
        )

    @staticmethod
    def _validate_node_types(
        workflow_ir: dict[str, Any],
        registry: Registry
    ) -> list[str]:
        """Validate all node types exist in registry."""
        errors = []
        node_types = {
            node.get("type")
            for node in workflow_ir.get("nodes", [])
            if node.get("type")
        }

        if node_types:
            metadata = registry.get_nodes_metadata(node_types)
            for node_type in node_types:
                if node_type not in metadata:
                    errors.append(f"Unknown node type: '{node_type}'")

        return errors
```

### Modified Components

#### 1. ValidatorNode (Minimal Changes)
```python
# In src/pflow/planning/nodes.py

def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute validation using unified WorkflowValidator."""
    workflow = prep_res.get("workflow", {})
    extracted_params = prep_res.get("extracted_params", {})

    # Use the unified validator
    from pflow.core.workflow_validator import WorkflowValidator
    errors = WorkflowValidator.validate(
        workflow_ir=workflow,
        extracted_params=extracted_params,
        registry=self.registry,
        skip_node_types=False  # Always validate in production
    )

    # Return top 3 actionable errors (existing behavior)
    return {"errors": errors[:3]}
```

#### 2. Test Validation (Minimal Changes)
```python
# In test_workflow_generator_prompt.py

def validate_workflow(workflow: dict, test_case: WorkflowTestCase) -> tuple[bool, str]:
    """Validate using production WorkflowValidator."""
    from pflow.core.workflow_validator import WorkflowValidator

    # Determine if using mock nodes
    uses_mock_nodes = "(mock)" in test_case.planning_context

    # Use production validation
    errors = WorkflowValidator.validate(
        workflow_ir=workflow,
        extracted_params=test_case.discovered_params,
        registry=Registry() if not uses_mock_nodes else None,
        skip_node_types=uses_mock_nodes  # Skip for mock nodes
    )

    # Add test-specific quality checks (these are NOT correctness checks)
    node_count = len(workflow.get("nodes", []))
    if node_count < test_case.min_nodes:
        errors.append(f"[TEST] Too few nodes: {node_count} < {test_case.min_nodes}")
    if node_count > test_case.max_nodes:
        errors.append(f"[TEST] Too many nodes: {node_count} > {test_case.max_nodes}")

    # Test-specific input expectations
    # ... existing test-specific checks ...

    return len(errors) == 0, "; ".join(errors)
```

## Testing Strategy

### What Needs NEW Tests

1. **Data flow validation in production**
   - Test that ValidatorNode now catches execution order issues
   - Test that circular dependencies are detected
   - Test forward reference detection

2. **WorkflowValidator class**
   - Unit tests for each validation method
   - Integration test for complete validation
   - Test with various skip flags

### What Should NOT Change

1. **Existing ValidatorNode tests**
   - Should pass without modification
   - Same input/output format
   - Same error message structure

2. **Existing workflow_generator tests**
   - Should pass without modification
   - Same test expectations
   - Same accuracy (or better with data flow validation)

3. **Existing template validation tests**
   - TemplateValidator interface unchanged
   - Same validation behavior

### New Test Files

#### `/tests/test_core/test_workflow_data_flow.py`
```python
"""Test data flow validation logic."""

class TestWorkflowDataFlow:
    def test_detects_forward_references(self):
        """Test that forward references are caught."""
        workflow = {
            "nodes": [
                {"id": "write", "params": {"content": "${process.output}"}},
                {"id": "process", "params": {"data": "test"}}
            ],
            "edges": [{"from": "write", "to": "process"}]
        }
        errors = validate_data_flow(workflow)
        assert any("forward reference" in e.lower() for e in errors)

    def test_detects_circular_dependencies(self):
        """Test that circular dependencies are caught."""
        workflow = {
            "nodes": [
                {"id": "a", "params": {"data": "${b.output}"}},
                {"id": "b", "params": {"data": "${a.output}"}}
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"}
            ]
        }
        errors = validate_data_flow(workflow)
        assert any("circular" in e.lower() for e in errors)

    def test_valid_data_flow_passes(self):
        """Test that valid workflows pass."""
        workflow = {
            "nodes": [
                {"id": "read", "params": {"file": "test.txt"}},
                {"id": "process", "params": {"data": "${read.content}"}},
                {"id": "write", "params": {"content": "${process.output}"}}
            ],
            "edges": [
                {"from": "read", "to": "process"},
                {"from": "process", "to": "write"}
            ],
            "inputs": {}
        }
        errors = validate_data_flow(workflow)
        assert errors == []
```

#### `/tests/test_core/test_workflow_validator.py`
```python
"""Test unified WorkflowValidator."""

class TestWorkflowValidator:
    def test_complete_validation(self):
        """Test that all validations run."""
        workflow = create_test_workflow()
        errors = WorkflowValidator.validate(
            workflow,
            extracted_params={"test": "value"},
            registry=Registry()
        )
        # Should run all 4 validation types

    def test_skip_node_types_for_mocks(self):
        """Test skipping node type validation."""
        workflow = create_workflow_with_mock_nodes()
        errors = WorkflowValidator.validate(
            workflow,
            skip_node_types=True
        )
        # Should not have "Unknown node type" errors

    def test_partial_validation(self):
        """Test validation with missing params."""
        workflow = create_test_workflow()
        # No extracted_params - should skip template validation
        errors = WorkflowValidator.validate(workflow)
        # Should only run structure and data flow
```

## Migration Plan

### Phase 1: Add New Components (No Breaking Changes)
1. Create `workflow_data_flow.py` with data flow validation
2. Create `WorkflowValidator.py` as orchestrator
3. Add tests for new components
4. **No changes to existing code yet**

### Phase 2: Integration (Careful Changes)
1. Update ValidatorNode to use WorkflowValidator
2. Run existing ValidatorNode tests - **should all pass**
3. Add new tests for data flow validation in ValidatorNode
4. Update workflow_generator tests to use WorkflowValidator
5. Run workflow_generator tests - **should all pass**

### Phase 3: Cleanup (Remove Duplication)
1. Remove `validate_data_flow` from test file (now using production)
2. Remove `_validate_node_types` from ValidatorNode (now in WorkflowValidator)
3. Update any other consumers to use WorkflowValidator

## Success Criteria

1. **No regression**: All existing tests pass without modification
2. **Data flow validation**: Production catches execution order issues
3. **Single source of truth**: One place for all validation logic
4. **Reusability**: Any component can use WorkflowValidator
5. **Performance**: No significant slowdown (< 100ms added)

## Risk Analysis

### Risks
1. **Breaking existing tests**: Mitigated by careful phased approach
2. **Performance impact**: Mitigated by efficient topological sort
3. **Workflow breakage**: Mitigated by logging warnings before hard failures

### Rollback Plan
1. Feature flag to disable data flow validation
2. ValidatorNode can fall back to old methods if needed
3. Git revert if critical issues found

## Interface Stability Guarantees

### Unchanged Interfaces
- `ValidatorNode.exec()` - Same input/output format
- `TemplateValidator.validate_workflow_templates()` - Same signature
- `validate_ir()` - Same signature and behavior

### New Interfaces (Additions Only)
- `WorkflowValidator.validate()` - New unified interface
- `validate_data_flow()` - New validation function

### Changed Interfaces
- None (all changes are internal refactoring)

## Performance Considerations

### Expected Impact
- Topological sort: O(V + E) where V=nodes, E=edges
- Typical workflow (5-10 nodes): < 1ms added
- Large workflow (50 nodes): < 10ms added

### Optimization Opportunities
1. Cache execution order if workflow unchanged
2. Parallel validation of independent checks
3. Early exit on critical errors

## Documentation Updates

1. Update ValidatorNode docstring to mention data flow validation
2. Document WorkflowValidator as the canonical validation system
3. Add examples of data flow errors and how to fix them
4. Update planning system docs to mention enhanced validation

## Timeline

- **Day 1**: Create workflow_data_flow.py and tests
- **Day 2**: Create WorkflowValidator and tests
- **Day 3**: Integrate with ValidatorNode, verify no regression
- **Day 4**: Update tests to use WorkflowValidator
- **Day 5**: Cleanup and documentation

Total: 1 week for complete implementation and testing