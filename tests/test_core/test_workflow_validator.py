"""Test the unified WorkflowValidator."""

import pytest

from pflow.core.workflow_validator import WorkflowValidator
from pflow.registry import Registry

# Note: Removed autouse fixture that was modifying user's registry.
# The global test isolation in tests/conftest.py now ensures tests use
# temporary registry paths, and nodes are auto-discovered as needed.


@pytest.fixture
def registry_with_nodes():
    """Create a registry with required nodes for validation tests.

    The Registry class automatically discovers core nodes when load() is called
    on an empty registry, so we just need to create and load it.
    """
    registry = Registry()
    # This will trigger auto-discovery if the registry doesn't exist yet
    registry.load()
    return registry


class TestWorkflowValidator:
    """Test unified validation orchestration."""

    def test_complete_validation_all_checks(self, registry_with_nodes):
        """Test that all validation types run for valid workflow."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "${input_file}"}},
                {"id": "n2", "type": "llm", "params": {"prompt": "${n1.content}"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "inputs": {"input_file": {"type": "string", "required": True}},
        }

        errors, warnings = WorkflowValidator.validate(
            workflow, extracted_params={"input_file": "test.txt"}, registry=registry_with_nodes, skip_node_types=True
        )

        # Valid workflow should have no errors
        assert errors == []

    def test_structural_validation_errors(self):
        """Test that structural errors are caught."""
        workflow = {
            # Missing required ir_version
            "nodes": [{"id": "n1", "type": "test"}],
            "edges": [],
        }

        errors, warnings = WorkflowValidator.validate(workflow)

        assert len(errors) > 0
        assert any("Structure:" in e for e in errors)
        assert any("ir_version" in e for e in errors)

    def test_data_flow_validation_errors(self):
        """Test that data flow errors are caught."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n2", "type": "test", "params": {"data": "${n1.output}"}},
                {"id": "n1", "type": "test", "params": {}},
            ],
            "edges": [
                {"from": "n2", "to": "n1"}  # Wrong order!
            ],
            "inputs": {},
        }

        errors, warnings = WorkflowValidator.validate(workflow, skip_node_types=True)

        assert len(errors) > 0
        assert any("after" in e for e in errors)

    def test_template_validation_errors(self, registry_with_nodes):
        """Test that template errors are caught when params provided."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "read-file", "params": {"file_path": "${missing_param}"}}],
            "edges": [],
            "inputs": {"missing_param": {"type": "string", "required": True}},
        }

        # With extracted_params but missing the required param
        errors, warnings = WorkflowValidator.validate(
            workflow,
            extracted_params={},  # Empty params
            registry=registry_with_nodes,
        )

        assert len(errors) > 0
        assert any("missing_param" in e for e in errors)

    def test_skip_template_validation_without_params(self):
        """Test that template validation is skipped without extracted_params."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {"file_path": "${missing_param}"}}],
            "edges": [],
            "inputs": {"missing_param": {"type": "string"}},
        }

        # Without extracted_params - should skip template validation
        errors, warnings = WorkflowValidator.validate(workflow, skip_node_types=True)

        # Should not have template errors
        assert not any("missing_param" in e for e in errors)

    def test_node_type_validation_errors(self, registry_with_nodes):
        """Test that unknown node types are caught."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "unknown-node-type", "params": {}}],
            "edges": [],
            "inputs": {},
        }

        # With node type validation enabled
        errors, warnings = WorkflowValidator.validate(workflow, registry=registry_with_nodes, skip_node_types=False)

        assert len(errors) > 0
        assert any("Unknown node type" in e for e in errors)
        assert any("unknown-node-type" in e for e in errors)

    def test_skip_node_types_for_mocks(self, registry_with_nodes):
        """Test selective validation skipping for mock nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "mock-node", "params": {"data": "test"}}],
            "edges": [],
            "inputs": {},
        }

        # With node type validation - should fail
        errors_with_validation, _ = WorkflowValidator.validate(
            workflow, registry=registry_with_nodes, skip_node_types=False
        )
        assert any("Unknown node type" in e for e in errors_with_validation)

        # Without node type validation - should pass
        errors_without_validation, _ = WorkflowValidator.validate(
            workflow, registry=registry_with_nodes, skip_node_types=True
        )
        assert not any("Unknown node type" in e for e in errors_without_validation)

    def test_accumulates_all_error_types(self, registry_with_nodes):
        """Test that all error types are collected."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "unknown-node", "params": {"data": "${n2.output}"}},
                {"id": "n2", "type": "another-unknown", "params": {"data": "${missing_input}"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],  # Wrong order for data flow
            "inputs": {},
        }

        errors, warnings = WorkflowValidator.validate(workflow, extracted_params={}, registry=registry_with_nodes)

        # Should have multiple error types
        assert len(errors) >= 3
        # Node type errors
        assert any("Unknown node type" in e and "unknown-node" in e for e in errors)
        assert any("Unknown node type" in e and "another-unknown" in e for e in errors)
        # Data flow error
        assert any(("forward" in e.lower() or "after" in e.lower()) for e in errors)
        # Template error
        assert any("missing_input" in e for e in errors)

    def test_circular_dependency_detection(self):
        """Test that circular dependencies are caught."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "test", "params": {"data": "${b.output}"}},
                {"id": "b", "type": "test", "params": {"data": "${a.output}"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},  # Creates cycle
            ],
            "inputs": {},
        }

        errors, warnings = WorkflowValidator.validate(workflow, skip_node_types=True)

        assert len(errors) > 0
        assert any("Circular dependency" in e for e in errors)

    def test_valid_complex_workflow(self, registry_with_nodes):
        """Test that a complex valid workflow passes all checks."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fetch",
                    "type": "http",
                    "params": {
                        "url": "${api_url}",
                        "method": "GET",
                    },
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {
                        "prompt": "Analyze this response: ${fetch.response}",
                        "model": "gpt-4",
                    },
                },
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {
                        "file_path": "${output_file}",
                        "content": "${analyze.response}",
                    },
                },
            ],
            "edges": [
                {"from": "fetch", "to": "analyze"},
                {"from": "analyze", "to": "write"},
            ],
            "inputs": {
                "api_url": {"type": "string", "required": True},
                "output_file": {"type": "string", "required": True},
            },
        }

        errors, warnings = WorkflowValidator.validate(
            workflow,
            extracted_params={
                "api_url": "https://api.example.com/data",
                "output_file": "report.md",
            },
            registry=registry_with_nodes,
            skip_node_types=True,
        )

        # Should pass all validations
        assert errors == []
