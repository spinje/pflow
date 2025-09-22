"""Integration tests for the compiler's input/output validation.

This module contains comprehensive tests for verifying that the compiler correctly
validates inputs and outputs during compilation. It follows existing test patterns
from the pflow test suite.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.core.ir_schema import ValidationError
from pflow.runtime.compiler import compile_ir_to_flow
from pocketflow import BaseNode


class MockNode(BaseNode):
    """Simple mock node for testing."""

    def __init__(self):
        super().__init__()
        self.params = {}

    def set_params(self, params):
        self.params = params


@pytest.fixture
def registry_with_nodes():
    """Mock registry with test nodes."""
    mock_registry = Mock()

    # Define node metadata with interfaces
    nodes_data = {
        "read-file": {
            "module": "pflow.nodes.file",
            "class_name": "ReadFile",
            "metadata": {
                "interface": {
                    "inputs": [{"key": "path", "type": "string", "description": "File path to read"}],
                    "outputs": [{"key": "content", "type": "string", "description": "File content"}],
                }
            },
        },
        "write-file": {
            "module": "pflow.nodes.file",
            "class_name": "WriteFile",
            "metadata": {
                "interface": {
                    "inputs": [
                        {"key": "content", "type": "string", "description": "Content to write"},
                        {"key": "path", "type": "string", "description": "File path"},
                    ],
                    "outputs": [],
                }
            },
        },
        "transform": {
            "module": "pflow.nodes.transform",
            "class_name": "Transform",
            "metadata": {
                "interface": {
                    "inputs": [{"key": "data", "type": "any", "description": "Data to transform"}],
                    "outputs": [{"key": "result", "type": "any", "description": "Transformed data"}],
                }
            },
        },
    }

    mock_registry.load.return_value = nodes_data

    # Mock get_nodes_metadata method for template validator
    def get_nodes_metadata_mock(node_types):
        result = {}
        for node_type in node_types:
            if node_type in nodes_data:
                # Return the full node data including interface at top level
                metadata = nodes_data[node_type].get("metadata", {})
                result[node_type] = {
                    "module": nodes_data[node_type]["module"],
                    "class_name": nodes_data[node_type]["class_name"],
                    "interface": metadata.get("interface", {}),
                }
        return result

    mock_registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata_mock)

    return mock_registry


@pytest.fixture
def mock_node_import():
    """Mock the import_node_class function."""
    with patch("pflow.runtime.compiler.import_node_class") as mock_import:
        mock_import.return_value = MockNode
        yield mock_import


class TestCompilerInterfaces:
    """Test compiler validation of workflow interfaces."""

    # === Input Validation Tests ===

    def test_required_input_validation_success(self, registry_with_nodes, mock_node_import):
        """Test that compilation succeeds when all required inputs are provided."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {"file_path": {"description": "Path to the input file", "required": True, "type": "string"}},
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "${file_path}"}}],
            "edges": [],
        }

        initial_params = {"file_path": "test.txt"}

        # Should compile successfully
        flow = compile_ir_to_flow(ir, registry_with_nodes, initial_params)
        assert flow is not None

    def test_missing_required_input_raises_error(self, registry_with_nodes, mock_node_import):
        """Test that missing required inputs raise ValidationError with description."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {"file_path": {"description": "Path to the input file", "required": True, "type": "string"}},
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "${file_path}"}}],
            "edges": [],
        }

        # No initial_params provided
        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {})

        error = exc_info.value
        assert "file_path" in error.message
        assert "Path to the input file" in error.message
        assert error.path == "inputs.file_path"
        assert "initial_params" in error.suggestion

    def test_optional_input_with_default_value(self, registry_with_nodes, mock_node_import, caplog):
        """Test that optional inputs with default values are applied."""
        import logging

        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "output_format": {
                    "description": "Output format",
                    "required": False,
                    "type": "string",
                    "default": "json",
                }
            },
            "nodes": [{"id": "formatter", "type": "transform", "params": {"format": "${output_format}"}}],
            "edges": [],
        }

        # Don't provide the optional parameter
        initial_params = {}

        # Should compile successfully and apply default
        with caplog.at_level(logging.DEBUG):
            flow = compile_ir_to_flow(ir, registry_with_nodes, initial_params)

        assert flow is not None

        # Check logging to verify default was applied
        assert any(
            "Applying default value for optional input 'output_format'" in record.message for record in caplog.records
        )

        # Verify the default value was logged
        for record in caplog.records:
            if "Applying default value" in record.message and "output_format" in record.message:
                assert record.default == "json"

    def test_multiple_missing_required_inputs(self, registry_with_nodes, mock_node_import):
        """Test error message when multiple required inputs are missing."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "source_file": {"description": "Source file path", "required": True, "type": "string"},
                "target_file": {"description": "Target file path", "required": True, "type": "string"},
            },
            "nodes": [
                {"id": "copy", "type": "transform", "params": {"from": "${source_file}", "to": "${target_file}"}}
            ],
            "edges": [],
        }

        # Only provide one of the required inputs
        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {"source_file": "source.txt"})

        error = exc_info.value
        assert "target_file" in error.message
        assert "Target file path" in error.message

    def test_hyphenated_input_names_now_allowed(self, registry_with_nodes, mock_node_import):
        """Test that hyphenated input names are now allowed."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "api-key": {  # Now allowed: hyphens are OK
                    "description": "Valid hyphenated input name",
                    "required": True,
                    "type": "string",
                },
                "user-email": {  # Another hyphenated name
                    "description": "User's email address",
                    "required": False,
                    "type": "string",
                },
            },
            "nodes": [{"id": "node1", "type": "transform", "params": {"key": "${api-key}", "email": "${user-email}"}}],
            "edges": [],
        }

        # Should compile successfully now
        flow = compile_ir_to_flow(ir, registry_with_nodes, {"api-key": "test_value", "user-email": "test@example.com"})
        assert flow is not None  # Compilation succeeded

    def test_shell_special_chars_in_input_name_raises_error(self, registry_with_nodes, mock_node_import):
        """Test that input names with shell special characters raise errors."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "my$input": {  # Invalid: contains $ which conflicts with template syntax
                    "description": "Invalid input name",
                    "required": True,
                    "type": "string",
                }
            },
            "nodes": [{"id": "node1", "type": "transform", "params": {"value": "${my$input}"}}],
            "edges": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {"my$input": "value"})

        error = exc_info.value
        assert "Invalid input name 'my$input'" in error.message
        assert "shell special characters" in error.message or "template syntax" in error.message

    def test_empty_initial_params_with_required_inputs(self, registry_with_nodes, mock_node_import):
        """Test that empty initial_params dict with required inputs raises error."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {"api_key": {"description": "API key for authentication", "required": True, "type": "string"}},
            "nodes": [{"id": "api_call", "type": "transform", "params": {"key": "${api_key}"}}],
            "edges": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {})

        error = exc_info.value
        assert "api_key" in error.message
        assert "API key for authentication" in error.message

    # === Output Validation Tests ===

    def test_valid_outputs_that_match_node_capabilities(self, registry_with_nodes, mock_node_import):
        """Test that valid outputs matching node capabilities compile successfully."""
        ir = {
            "ir_version": "0.1.0",
            "outputs": {"content": {"description": "File content read from disk", "type": "string"}},
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "test.txt"}}],
            "edges": [],
        }

        # Should compile successfully
        flow = compile_ir_to_flow(ir, registry_with_nodes)
        assert flow is not None

    def test_outputs_that_cannot_be_traced_log_warning(self, registry_with_nodes, mock_node_import, caplog):
        """Test that outputs that can't be traced to nodes log warnings, not errors."""
        ir = {
            "ir_version": "0.1.0",
            "outputs": {"dynamic_key": {"description": "A dynamically generated key", "type": "string"}},
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "test.txt"}}],
            "edges": [],
        }

        # Should compile successfully but log warning
        flow = compile_ir_to_flow(ir, registry_with_nodes)
        assert flow is not None

        # Check for warning
        warning_found = False
        for record in caplog.records:
            if record.levelname == "WARNING" and "dynamic_key" in record.message:
                warning_found = True
                assert "cannot be traced to any node" in record.message
                assert "may be fine if nodes write dynamic keys" in record.message
                break

        assert warning_found, "Expected warning about untraceable output not found"

    def test_hyphenated_output_names_now_allowed(self, registry_with_nodes, mock_node_import):
        """Test that hyphenated output names are now allowed."""
        ir = {
            "ir_version": "0.1.0",
            "outputs": {
                "valid-output": {  # Now allowed: contains hyphen
                    "description": "Valid hyphenated output name",
                    "type": "string",
                },
                "another-output": {
                    "description": "Another hyphenated output",
                    "type": "string",
                },
            },
            "nodes": [{"id": "node1", "type": "transform", "params": {}}],
            "edges": [],
        }

        # Should compile successfully now
        flow = compile_ir_to_flow(ir, registry_with_nodes)
        assert flow is not None  # Compilation succeeded

    def test_shell_special_chars_in_output_name_raises_error(self, registry_with_nodes, mock_node_import):
        """Test that output names with shell special characters raise errors."""
        ir = {
            "ir_version": "0.1.0",
            "outputs": {
                "my$output": {  # Invalid: contains $ which conflicts with template syntax
                    "description": "Invalid output name",
                    "type": "string",
                }
            },
            "nodes": [{"id": "node1", "type": "transform", "params": {}}],
            "edges": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes)

        error = exc_info.value
        assert "Invalid output name 'my$output'" in error.message
        assert "shell special characters" in error.message or "template syntax" in error.message

    def test_nested_workflow_outputs_via_output_mapping(self, registry_with_nodes, mock_node_import):
        """Test that nested workflow outputs are recognized through output_mapping."""
        # Add workflow executor to registry with proper interface structure
        registry_with_nodes.load.return_value["workflow"] = {
            "module": "pflow.runtime.workflow_executor",
            "class_name": "WorkflowExecutor",
            "metadata": {
                "interface": {
                    "inputs": {},
                    "outputs": {},  # Dynamic outputs handled via output_mapping
                }
            },
        }

        # Also update the get_nodes_metadata mock to return proper structure
        original_get_nodes_metadata = registry_with_nodes.get_nodes_metadata.side_effect

        def updated_get_nodes_metadata(node_types):
            result = original_get_nodes_metadata(node_types)
            if "workflow" in node_types:
                result["workflow"] = {
                    "module": "pflow.runtime.workflow_executor",
                    "class_name": "WorkflowExecutor",
                    "interface": {"inputs": {}, "outputs": {}},
                }
            return result

        registry_with_nodes.get_nodes_metadata.side_effect = updated_get_nodes_metadata

        ir = {
            "ir_version": "0.1.0",
            "outputs": {"final_result": {"description": "Result from nested workflow", "type": "string"}},
            "nodes": [
                {
                    "id": "nested",
                    "type": "workflow",
                    "params": {"workflow_path": "nested.json", "output_mapping": {"nested_output": "final_result"}},
                }
            ],
            "edges": [],
        }

        # Mock the WorkflowExecutor import for the special case
        from pflow.runtime.workflow_executor import WorkflowExecutor

        with patch.object(mock_node_import, "return_value", WorkflowExecutor):
            # Should compile successfully - output_mapping makes final_result available
            flow = compile_ir_to_flow(ir, registry_with_nodes)
            assert flow is not None

    # === Backward Compatibility Tests ===

    def test_workflow_without_inputs_outputs_compiles_normally(self, registry_with_nodes, mock_node_import):
        """Test that workflows without inputs/outputs sections compile normally."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "test.txt"}}],
            "edges": [],
        }

        # Should compile successfully
        flow = compile_ir_to_flow(ir, registry_with_nodes)
        assert flow is not None

    def test_empty_inputs_outputs_objects_work(self, registry_with_nodes, mock_node_import):
        """Test that empty inputs/outputs objects are valid."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {},
            "outputs": {},
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "test.txt"}}],
            "edges": [],
        }

        # Should compile successfully
        flow = compile_ir_to_flow(ir, registry_with_nodes)
        assert flow is not None

    # === Integration Tests ===

    def test_complete_workflow_with_inputs_outputs_and_execution(self, registry_with_nodes, mock_node_import):
        """Test a complete workflow with inputs, outputs, and mock execution."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "input_file": {"description": "Input file to process", "required": True, "type": "string"},
                "output_file": {"description": "Output file location", "required": True, "type": "string"},
            },
            "outputs": {
                "content": {"description": "Processed content", "type": "string"},
                "result": {"description": "Transform result", "type": "any"},
            },
            "nodes": [
                {"id": "reader", "type": "read-file", "params": {"path": "${input_file}"}},
                {"id": "processor", "type": "transform", "params": {"data": "{{content}}"}},
                {"id": "writer", "type": "write-file", "params": {"path": "${output_file}", "content": "{{result}}"}},
            ],
            "edges": [{"from": "reader", "to": "processor"}, {"from": "processor", "to": "writer"}],
        }

        initial_params = {"input_file": "input.txt", "output_file": "output.txt"}

        # Should compile successfully
        flow = compile_ir_to_flow(ir, registry_with_nodes, initial_params)
        assert flow is not None

    def test_default_values_are_accessible_in_nodes(self, registry_with_nodes, mock_node_import, caplog):
        """Test that default values are applied and accessible during compilation."""
        import logging

        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "mode": {"description": "Processing mode", "required": False, "type": "string", "default": "fast"}
            },
            "nodes": [{"id": "processor", "type": "transform", "params": {"mode": "${mode}"}}],
            "edges": [],
        }

        # Test that defaults are applied when no initial_params are provided
        with caplog.at_level(logging.DEBUG):
            flow = compile_ir_to_flow(ir, registry_with_nodes)

        assert flow is not None

        # Verify default was applied via logging
        assert any("Applying default value for optional input 'mode'" in record.message for record in caplog.records)

    def test_template_resolution_works_with_validated_inputs(self, registry_with_nodes, mock_node_import):
        """Test that template resolution works correctly with validated inputs."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "prefix": {"description": "File prefix", "required": True, "type": "string"},
                "suffix": {"description": "File suffix", "required": False, "type": "string", "default": ".txt"},
            },
            "nodes": [
                {
                    "id": "reader",
                    "type": "read-file",
                    "params": {"path": "${prefix}${suffix}"},  # Concatenated template
                }
            ],
            "edges": [],
        }

        initial_params = {"prefix": "file"}

        # Should compile and apply default suffix
        flow = compile_ir_to_flow(ir, registry_with_nodes, initial_params)
        assert flow is not None
        assert initial_params["suffix"] == ".txt"

    # === Error Message Quality Tests ===

    def test_error_messages_include_input_descriptions(self, registry_with_nodes, mock_node_import):
        """Test that error messages include helpful input descriptions."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "github_token": {
                    "description": "GitHub personal access token for API calls",
                    "required": True,
                    "type": "string",
                }
            },
            "nodes": [{"id": "api", "type": "transform", "params": {"token": "${github_token}"}}],
            "edges": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {})

        error = exc_info.value
        assert "GitHub personal access token for API calls" in error.message

    def test_error_paths_are_specific(self, registry_with_nodes, mock_node_import):
        """Test that error paths point to specific fields."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {"issue_number": {"description": "GitHub issue number", "required": True, "type": "number"}},
            "nodes": [{"id": "fetch", "type": "transform", "params": {"issue": "${issue_number}"}}],
            "edges": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {})

        error = exc_info.value
        assert error.path == "inputs.issue_number"

    def test_suggestions_are_helpful(self, registry_with_nodes, mock_node_import):
        """Test that error suggestions provide actionable guidance."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "config_path": {"description": "Path to configuration file", "required": True, "type": "string"}
            },
            "nodes": [{"id": "loader", "type": "read-file", "params": {"path": "${config_path}"}}],
            "edges": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir, registry_with_nodes, {})

        error = exc_info.value
        assert "Provide this parameter in initial_params" in error.suggestion
