"""Integration test for unused input detection in workflow validation.

This test demonstrates the Task 17 Subtask 5 enhancement working in
a realistic scenario where a workflow declares inputs but doesn't use them all.
"""

import pytest

from pflow.registry import Registry
from pflow.runtime.template_validator import TemplateValidator


class MockRegistry(Registry):
    """Mock registry for testing with predefined node metadata."""

    def __init__(self):
        super().__init__()
        # Pre-populate with file node metadata
        self._nodes_metadata = {
            "read-file": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "content", "type": "string"}],
                    "parameters": [{"key": "path", "type": "string", "required": True}],
                }
            },
            "write-file": {
                "interface": {
                    "inputs": [{"key": "content", "type": "string"}],
                    "outputs": [],
                    "parameters": [
                        {"key": "path", "type": "string", "required": True},
                        {"key": "content", "type": "string", "required": False},
                    ],
                }
            },
            "workflow": {
                "interface": {
                    "inputs": [],
                    "outputs": [],
                    "parameters": [
                        {"key": "workflow_name", "type": "string", "required": True},
                        {"key": "params", "type": "dict", "required": False},
                    ],
                }
            },
        }

    def get_nodes_metadata(self, node_types: list[str]) -> dict:
        """Return mock metadata for requested node types."""
        result = {}
        for node_type in node_types:
            if node_type in self._nodes_metadata:
                result[node_type] = self._nodes_metadata[node_type]
        return result


def test_unused_inputs_detected_before_execution(tmp_path):
    """Test that unused inputs are detected during validation before workflow execution."""
    # Create a workflow that declares inputs but doesn't use them all
    workflow_ir = {
        "ir_version": "0.1.0",
        "name": "example-workflow",
        "inputs": {
            "input_file": {
                "type": "string",
                "description": "Path to input file",
                "required": True,
            },
            "output_file": {
                "type": "string",
                "description": "Path to output file",
                "required": True,
            },
            "unused_option": {
                "type": "string",
                "description": "An option that is never used",
                "required": False,
                "default": "default_value",
            },
            "another_unused": {
                "type": "integer",
                "description": "Another unused parameter",
                "required": False,
            },
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "$input_file"},  # Uses input_file
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {
                    "path": "$output_file",  # Uses output_file
                    "content": "$content",  # Uses node output
                },
            },
        ],
        "edges": [{"from": "reader", "to": "writer"}],
    }

    # Create mock registry with file nodes
    registry = MockRegistry()

    # Validate templates
    initial_params = {
        "input_file": str(tmp_path / "input.txt"),
        "output_file": str(tmp_path / "output.txt"),
        # Note: unused_option and another_unused are not provided but have defaults or are optional
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, registry)

    # Should detect the unused inputs
    assert len(errors) == 1
    assert "Declared input(s) never used as template variable" in errors[0]
    assert "another_unused" in errors[0]
    assert "unused_option" in errors[0]

    # The error should list them in sorted order
    assert "another_unused, unused_option" in errors[0]


def test_workflow_with_all_inputs_used(tmp_path):
    """Test that no errors occur when all declared inputs are used."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "name": "all-inputs-used",
        "inputs": {
            "source_file": {
                "type": "string",
                "description": "Source file path",
                "required": True,
            },
            "dest_file": {
                "type": "string",
                "description": "Destination file path",
                "required": True,
            },
            "backup_file": {
                "type": "string",
                "description": "Backup file path",
                "required": False,
            },
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "$source_file"},
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "$dest_file", "content": "$content"},
            },
            {
                "id": "backup",
                "type": "write-file",
                "params": {"path": "$backup_file", "content": "$content"},
            },
        ],
        "edges": [
            {"from": "reader", "to": "writer"},
            {"from": "reader", "to": "backup"},
        ],
    }

    registry = MockRegistry()

    initial_params = {
        "source_file": str(tmp_path / "source.txt"),
        "dest_file": str(tmp_path / "dest.txt"),
        "backup_file": str(tmp_path / "backup.txt"),
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, registry)

    # Should have no errors since all inputs are used
    assert len(errors) == 0


def test_unused_inputs_with_nested_workflows(tmp_path):
    """Test unused input detection with nested workflow execution."""
    # Parent workflow with unused input
    parent_workflow = {
        "ir_version": "0.1.0",
        "name": "parent-workflow",
        "inputs": {
            "config_path": {
                "type": "string",
                "description": "Configuration file path",
                "required": True,
            },
            "unused_debug_flag": {
                "type": "boolean",
                "description": "Debug flag that is never used",
                "required": False,
                "default": False,
            },
        },
        "nodes": [
            {
                "id": "read_config",
                "type": "read-file",
                "params": {"path": "$config_path"},
            },
            {
                "id": "nested_workflow",
                "type": "workflow",
                "params": {
                    "workflow_name": "child-workflow",
                    "params": {"data": "$content"},
                },
            },
        ],
        "edges": [{"from": "read_config", "to": "nested_workflow"}],
    }

    registry = MockRegistry()

    initial_params = {"config_path": str(tmp_path / "config.json")}

    errors = TemplateValidator.validate_workflow_templates(parent_workflow, initial_params, registry)

    # Should detect the unused debug flag
    assert any("unused_debug_flag" in error for error in errors)
    assert any("never used as template variable" in error for error in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
