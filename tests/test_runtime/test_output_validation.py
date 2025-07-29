"""Tests for workflow output validation in the compiler."""

import logging
from unittest.mock import Mock, patch

import pytest

from pflow.core.ir_schema import ValidationError
from pflow.runtime.compiler import _validate_outputs, compile_ir_to_flow


class TestOutputValidation:
    """Test the _validate_outputs function."""

    def test_no_outputs_declared(self, caplog):
        """Test that no validation occurs when no outputs are declared."""
        workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test-node"}]}
        registry = Mock()

        with caplog.at_level(logging.DEBUG):
            _validate_outputs(workflow_ir, registry)

        # Should log that no outputs were declared
        assert "No outputs declared for workflow" in caplog.text
        # Registry shouldn't be called
        registry.get_nodes_metadata.assert_not_called()

    def test_invalid_output_name(self):
        """Test that invalid Python identifiers raise ValidationError."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "outputs": {
                "123invalid": {"description": "Starts with number"},
                "valid_name": {"description": "Valid identifier"},
            },
        }
        registry = Mock()

        with pytest.raises(ValidationError) as exc_info:
            _validate_outputs(workflow_ir, registry)

        assert "Invalid output name '123invalid'" in str(exc_info.value)
        assert "must be a valid Python identifier" in str(exc_info.value)

    def test_traceable_outputs(self, caplog):
        """Test validation when outputs can be traced to nodes."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "outputs": {"result": {"description": "Test result"}},
        }

        # Mock registry with node that produces 'result'
        registry = Mock()
        registry.get_nodes_metadata.return_value = {
            "test-node": {"interface": {"outputs": [{"key": "result", "type": "string"}]}}
        }

        with caplog.at_level(logging.DEBUG):
            _validate_outputs(workflow_ir, registry)

        # Should log successful validation
        assert "Output 'result' can be produced by workflow nodes" in caplog.text
        # Should not have warnings
        assert "cannot be traced to any node" not in caplog.text

    def test_untraceable_outputs_warning(self, caplog):
        """Test that untraceable outputs produce warnings, not errors."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "outputs": {"dynamic_key": {"description": "Written dynamically"}},
        }

        # Mock registry with node that doesn't produce 'dynamic_key'
        registry = Mock()
        registry.get_nodes_metadata.return_value = {
            "test-node": {"interface": {"outputs": [{"key": "other_key", "type": "string"}]}}
        }

        with caplog.at_level(logging.WARNING):
            # Should NOT raise an exception
            _validate_outputs(workflow_ir, registry)

        # Should have warning about untraceable output
        assert "Declared output 'dynamic_key' cannot be traced to any node" in caplog.text
        assert "This may be fine if nodes write dynamic keys" in caplog.text

    def test_nested_workflow_output_mapping(self, caplog):
        """Test that nested workflows' output_mapping is considered."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "nested",
                    "type": "workflow",
                    "params": {"workflow_ref": "child.json", "output_mapping": {"child_result": "parent_result"}},
                }
            ],
            "outputs": {"parent_result": {"description": "Mapped from child workflow"}},
        }

        # Mock registry - workflow type doesn't need interface
        registry = Mock()
        registry.get_nodes_metadata.return_value = {
            "workflow": {
                "interface": {
                    "outputs": []  # Workflow executor doesn't declare static outputs
                }
            }
        }

        with caplog.at_level(logging.DEBUG):
            _validate_outputs(workflow_ir, registry)

        # Should recognize parent_result from output_mapping
        assert "Output 'parent_result' can be produced by workflow nodes" in caplog.text

    def test_multiple_outputs_mixed_validity(self, caplog):
        """Test workflow with mix of traceable and untraceable outputs."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "outputs": {
                "known_output": {"description": "Can be traced"},
                "dynamic_output": {"description": "Cannot be traced"},
                "another_known": {"description": "Also traceable"},
            },
        }

        registry = Mock()
        registry.get_nodes_metadata.return_value = {
            "test-node": {
                "interface": {
                    "outputs": [{"key": "known_output", "type": "string"}, {"key": "another_known", "type": "number"}]
                }
            }
        }

        with caplog.at_level(logging.DEBUG):  # Changed to DEBUG to capture all logs
            _validate_outputs(workflow_ir, registry)

        # Should have debug logs for traceable outputs
        assert "Output 'known_output' can be produced" in caplog.text
        assert "Output 'another_known' can be produced" in caplog.text

        # Should have warning for untraceable output
        assert "Declared output 'dynamic_output' cannot be traced" in caplog.text

    def test_simple_output_format(self):
        """Test handling of simple string output format from interfaces."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "outputs": {"simple_output": {"description": "Test output"}},
        }

        registry = Mock()
        registry.get_nodes_metadata.return_value = {
            "test-node": {
                "interface": {
                    "outputs": ["simple_output"]  # Simple string format
                }
            }
        }

        # Should handle simple format without errors
        _validate_outputs(workflow_ir, registry)


class TestOutputValidationIntegration:
    """Test output validation as part of compile_ir_to_flow."""

    def test_compile_with_invalid_output_names(self):
        """Test that compilation fails with invalid output names."""
        ir_dict = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node", "params": {}}],
            "edges": [],
            "outputs": {"invalid-name": {"description": "Contains hyphen"}},
        }

        registry = Mock()
        registry.load.return_value = {"test-node": {"module": "test", "class_name": "TestNode"}}

        with pytest.raises(ValidationError) as exc_info:
            compile_ir_to_flow(ir_dict, registry)

        assert "Invalid output name 'invalid-name'" in str(exc_info.value)

    @patch("pflow.runtime.compiler.import_node_class")
    def test_compile_with_output_warnings(self, mock_import, caplog):
        """Test that compilation continues with warnings for untraceable outputs."""
        ir_dict = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node", "params": {}}],
            "edges": [],
            "outputs": {"maybe_dynamic": {"description": "Might be written dynamically"}},
        }

        # Mock node class
        mock_import.return_value = type("TestNode", (Mock,), {})

        # Mock registry
        registry = Mock()
        registry.load.return_value = {"test-node": {"module": "test", "class_name": "TestNode"}}
        registry.get_nodes_metadata.return_value = {
            "test-node": {
                "interface": {
                    "outputs": []  # Node doesn't declare this output
                }
            }
        }

        with caplog.at_level(logging.WARNING):
            # Should compile successfully despite warning
            flow = compile_ir_to_flow(ir_dict, registry)
            assert flow is not None

        # Should have warning about untraceable output
        assert "Declared output 'maybe_dynamic' cannot be traced" in caplog.text
