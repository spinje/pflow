"""Test suite for unused input detection in TemplateValidator.

This module tests the Task 17 Subtask 5 enhancement that detects when
declared inputs are never used as template variables in the workflow.
"""

import pytest

from pflow.registry import Registry
from pflow.runtime.template_validator import TemplateValidator


class MockRegistry(Registry):
    """Mock registry for testing with predefined node metadata."""

    def __init__(self, nodes_metadata: dict):
        super().__init__()
        self._nodes_metadata = nodes_metadata

    def get_nodes_metadata(self, node_types: list[str]) -> dict:
        """Return mock metadata for requested node types."""
        result = {}
        for node_type in node_types:
            if node_type in self._nodes_metadata:
                result[node_type] = self._nodes_metadata[node_type]
        return result


@pytest.fixture
def mock_registry():
    """Create a mock registry with basic node metadata."""
    nodes_metadata = {
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
                "parameters": [{"key": "path", "type": "string", "required": True}],
            }
        },
        "transform": {
            "interface": {
                "inputs": [{"key": "data", "type": "any"}],
                "outputs": [{"key": "result", "type": "any", "structure": {"status": "string", "value": "any"}}],
                "parameters": [],
            }
        },
    }
    return MockRegistry(nodes_metadata)


def test_unused_input_single_unused(mock_registry, tmp_path):
    """Test detection of a single unused input."""
    output_path = str(tmp_path / "output.txt")
    input_path = str(tmp_path / "input.txt")
    workflow_ir = {
        "inputs": {
            "input_path": {"type": "string", "description": "Path to input file"},
            "unused_param": {"type": "string", "description": "This parameter is never used"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${input_path}"},  # Uses input_path
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": output_path},  # Doesn't use unused_param
            },
        ],
    }

    initial_params = {"input_path": input_path}  # unused_param not provided

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have exactly one error about unused input
    assert len(errors) == 1
    assert "Declared input(s) never used as template variable: unused_param" in errors[0]


def test_all_inputs_used(mock_registry, tmp_path):
    """Test when all declared inputs are properly used."""
    input_path = str(tmp_path / "input.txt")
    output_path = str(tmp_path / "output.txt")
    workflow_ir = {
        "inputs": {
            "input_path": {"type": "string", "description": "Path to input file"},
            "output_path": {"type": "string", "description": "Path to output file"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${input_path}"},  # Uses input_path
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${output_path}"},  # Uses output_path
            },
        ],
    }

    initial_params = {"input_path": input_path, "output_path": output_path}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors
    assert len(errors) == 0


def test_empty_inputs_field(mock_registry, tmp_path):
    """Test when inputs field is empty or missing."""
    # Test with empty inputs dict
    hardcoded = str(tmp_path / "hardcoded.txt")
    workflow_ir = {
        "inputs": {},
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": hardcoded},
            }
        ],
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, mock_registry)
    assert len(errors) == 0

    # Test with missing inputs field
    workflow_ir_no_inputs = {
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": hardcoded},
            }
        ]
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir_no_inputs, {}, mock_registry)
    assert len(errors) == 0


def test_input_used_in_nested_path(mock_registry, tmp_path):
    """Test when input is used with nested path access (e.g., ${input.field})."""
    input_path = str(tmp_path / "input.txt")
    output_path = str(tmp_path / "output.txt")
    workflow_ir = {
        "inputs": {
            "config": {"type": "object", "description": "Configuration object"},
            "api_settings": {"type": "object", "description": "API settings"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${config.input_file}"},  # Uses config with nested path
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${api_settings.endpoint.url}"},  # Uses api_settings with nested path
            },
        ],
    }

    initial_params = {
        "config": {"input_file": input_path},
        "api_settings": {"endpoint": {"url": output_path}},
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - both inputs are used even though with nested paths
    assert len(errors) == 0


def test_multiple_unused_inputs(mock_registry, tmp_path):
    """Test that multiple unused inputs are all reported."""
    workflow_ir = {
        "inputs": {
            "used_param": {"type": "string", "description": "This is used"},
            "unused1": {"type": "string", "description": "First unused"},
            "unused2": {"type": "integer", "description": "Second unused"},
            "unused3": {"type": "boolean", "description": "Third unused"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${used_param}"},  # Only uses used_param
            }
        ],
    }

    initial_params = {"used_param": str(tmp_path / "file.txt")}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have exactly one error listing all unused inputs
    assert len(errors) == 1
    error_msg = errors[0]
    assert "Declared input(s) never used as template variable:" in error_msg
    # Check all unused inputs are mentioned (in sorted order)
    assert "unused1" in error_msg
    assert "unused2" in error_msg
    assert "unused3" in error_msg
    # Verify they're in sorted order
    assert error_msg.endswith("unused1, unused2, unused3")


def test_node_output_not_flagged_as_unused_input(mock_registry, tmp_path):
    """Test that node outputs aren't mistakenly flagged as unused inputs."""
    output_path = str(tmp_path / "output.txt")
    input_path = str(tmp_path / "input.txt")
    workflow_ir = {
        "inputs": {
            "input_file": {"type": "string", "description": "Input file path"},
        },
        "outputs": {
            "content": {"type": "string", "description": "File content"},  # This is an output, not input
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${input_file}"},  # Uses the input
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": output_path},
            },
        ],
    }

    initial_params = {"input_file": input_path}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - outputs aren't inputs
    assert len(errors) == 0


def test_input_used_multiple_times(mock_registry, tmp_path):
    """Test when an input is used multiple times in different nodes."""
    workflow_ir = {
        "inputs": {
            "base_path": {"type": "string", "description": "Base path for files"},
        },
        "nodes": [
            {
                "id": "reader1",
                "type": "read-file",
                "params": {"path": "${base_path}/file1.txt"},  # First use
            },
            {
                "id": "reader2",
                "type": "read-file",
                "params": {"path": "${base_path}/file2.txt"},  # Second use
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${base_path}/output.txt"},  # Third use
            },
        ],
    }

    initial_params = {"base_path": str(tmp_path)}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - input is used
    assert len(errors) == 0


def test_mixed_used_and_unused_inputs(mock_registry, tmp_path):
    """Test workflow with both used and unused inputs."""
    workflow_ir = {
        "inputs": {
            "used1": {"type": "string", "description": "First used input"},
            "unused1": {"type": "string", "description": "First unused input"},
            "used2": {"type": "string", "description": "Second used input"},
            "unused2": {"type": "string", "description": "Second unused input"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${used1}"},
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${used2}"},
            },
        ],
    }

    initial_params = {"used1": str(tmp_path / "input.txt"), "used2": str(tmp_path / "output.txt")}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have one error about unused inputs
    assert len(errors) == 1
    error_msg = errors[0]
    assert "Declared input(s) never used as template variable:" in error_msg
    assert "unused1, unused2" in error_msg


def test_input_only_used_in_concatenation(mock_registry, tmp_path):
    """Test when input is used within string concatenation."""
    base = str(tmp_path)
    workflow_ir = {
        "inputs": {
            "prefix": {"type": "string", "description": "Filename prefix"},
            "suffix": {"type": "string", "description": "Filename suffix"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": base + "/${prefix}-file-${suffix}.txt"},  # Both used in concatenation
            }
        ],
    }

    initial_params = {"prefix": "test", "suffix": "data"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - both inputs are used
    assert len(errors) == 0


def test_unused_input_with_missing_required_input(mock_registry):
    """Test when there are both unused inputs and missing required inputs."""
    workflow_ir = {
        "inputs": {
            "required_path": {"type": "string", "description": "Required path", "required": True},
            "unused_param": {"type": "string", "description": "Unused parameter"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${required_path}"},  # Uses required_path
            }
        ],
    }

    # Don't provide the required input
    initial_params = {}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have two errors: one for missing required, one for unused
    assert len(errors) == 2

    error_messages = " ".join(errors)
    assert "unused_param" in error_messages
    assert "required_path" in error_messages


def test_case_sensitivity_in_unused_detection(mock_registry, tmp_path):
    """Test that unused input detection is case-sensitive."""
    workflow_ir = {
        "inputs": {
            "MyInput": {"type": "string", "description": "Camel case input"},
            "myinput": {"type": "string", "description": "Lower case input"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${MyInput}"},  # Uses MyInput (camel case)
            }
        ],
    }

    initial_params = {"MyInput": str(tmp_path / "file.txt")}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have one error about unused 'myinput' (lowercase)
    assert len(errors) == 1
    assert "myinput" in errors[0]
    assert "MyInput" not in errors[0]  # MyInput is used
