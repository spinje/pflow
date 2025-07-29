"""Tests for the compiler foundation (subtask 4.1).

This module tests the basic infrastructure of the IR compiler including
error handling, input parsing, and structure validation. Actual compilation
logic will be tested in future subtasks.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from pflow.runtime import compile_ir_to_flow
from pflow.runtime.compiler import CompilationError, _parse_ir_input
from pflow.runtime.workflow_validator import validate_ir_structure


class TestCompilationError:
    """Test the CompilationError exception class."""

    def test_error_with_all_attributes(self):
        """Test CompilationError with all optional attributes."""
        error = CompilationError(
            message="Test error",
            phase="testing",
            node_id="node1",
            node_type="test-type",
            details={"key": "value"},
            suggestion="Fix the thing",
        )

        # Check attributes are stored
        assert error.phase == "testing"
        assert error.node_id == "node1"
        assert error.node_type == "test-type"
        assert error.details == {"key": "value"}
        assert error.suggestion == "Fix the thing"

        # Check message formatting
        error_str = str(error)
        assert "compiler: Test error" in error_str
        assert "Phase: testing" in error_str
        assert "Node ID: node1" in error_str
        assert "Node Type: test-type" in error_str
        assert "Suggestion: Fix the thing" in error_str

    def test_error_with_minimal_attributes(self):
        """Test CompilationError with only required message."""
        error = CompilationError("Simple error")

        # Check defaults
        assert error.phase == "unknown"
        assert error.node_id is None
        assert error.node_type is None
        assert error.details == {}
        assert error.suggestion is None

        # Check message is simple
        assert str(error) == "compiler: Simple error"

    def test_error_with_partial_attributes(self):
        """Test CompilationError with some optional attributes."""
        error = CompilationError(message="Partial error", phase="validation", suggestion="Check your input")

        error_str = str(error)
        assert "compiler: Partial error" in error_str
        assert "Phase: validation" in error_str
        assert "Suggestion: Check your input" in error_str
        # These should not appear
        assert "Node ID:" not in error_str
        assert "Node Type:" not in error_str


class TestParseIrInput:
    """Test the _parse_ir_input helper function."""

    def test_parse_dict_input(self):
        """Test parsing when input is already a dict."""
        input_dict = {"nodes": [], "edges": []}
        result = _parse_ir_input(input_dict)
        assert result is input_dict  # Should return same object

    def test_parse_string_input(self):
        """Test parsing JSON string input."""
        input_str = '{"nodes": [], "edges": []}'
        result = _parse_ir_input(input_str)
        assert result == {"nodes": [], "edges": []}

    def test_parse_complex_json(self):
        """Test parsing more complex JSON string."""
        input_str = """{
            "nodes": [
                {"id": "n1", "type": "test", "params": {"key": "value"}}
            ],
            "edges": [
                {"from": "n1", "to": "n2"}
            ]
        }"""
        result = _parse_ir_input(input_str)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "n1"
        assert len(result["edges"]) == 1

    def test_parse_invalid_json(self):
        """Test that invalid JSON raises JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            _parse_ir_input('{"invalid": json}')


class TestValidateIrStructure:
    """Test the validate_ir_structure helper function."""

    def test_valid_structure(self):
        """Test validation passes for valid structure."""
        ir_dict = {"nodes": [], "edges": []}
        # Should not raise
        validate_ir_structure(ir_dict)

    def test_valid_structure_with_content(self):
        """Test validation passes with actual nodes and edges."""
        ir_dict = {
            "nodes": [{"id": "n1", "type": "test"}],
            "edges": [{"from": "n1", "to": "n2"}],
            "other": "fields are ignored",
        }
        # Should not raise
        validate_ir_structure(ir_dict)

    def test_missing_nodes_key(self):
        """Test validation fails when 'nodes' key is missing."""
        ir_dict = {"edges": []}

        with pytest.raises(CompilationError) as exc_info:
            validate_ir_structure(ir_dict)

        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'nodes' key" in str(error)
        assert "IR must contain 'nodes' array" in str(error)

    def test_missing_edges_key(self):
        """Test validation fails when 'edges' key is missing."""
        ir_dict = {"nodes": []}

        with pytest.raises(CompilationError) as exc_info:
            validate_ir_structure(ir_dict)

        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'edges' key" in str(error)
        assert "IR must contain 'edges' array" in str(error)

    def test_nodes_not_list(self):
        """Test validation fails when 'nodes' is not a list."""
        ir_dict = {"nodes": "not-a-list", "edges": []}

        with pytest.raises(CompilationError) as exc_info:
            validate_ir_structure(ir_dict)

        error = exc_info.value
        assert error.phase == "validation"
        assert "'nodes' must be an array" in str(error)
        assert "got str" in str(error)

    def test_edges_not_list(self):
        """Test validation fails when 'edges' is not a list."""
        ir_dict = {"nodes": [], "edges": {"not": "a-list"}}

        with pytest.raises(CompilationError) as exc_info:
            validate_ir_structure(ir_dict)

        error = exc_info.value
        assert error.phase == "validation"
        assert "'edges' must be an array" in str(error)
        assert "got dict" in str(error)


class TestCompileIrToFlow:
    """Test the main compile_ir_to_flow function."""

    def test_compile_with_dict_input(self):
        """Test compilation with dict input and empty nodes."""
        registry = MagicMock()
        ir_dict = {"nodes": [], "edges": []}

        # Now that compilation is implemented, empty nodes should raise CompilationError
        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir_dict, registry)

        assert exc_info.value.phase == "start_detection"
        assert "Cannot create flow with no nodes" in str(exc_info.value)

    def test_compile_with_string_input(self):
        """Test compilation with JSON string input and empty nodes."""
        registry = MagicMock()
        ir_string = '{"nodes": [], "edges": []}'

        # Now that compilation is implemented, empty nodes should raise CompilationError
        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir_string, registry)

        assert exc_info.value.phase == "start_detection"
        assert "Cannot create flow with no nodes" in str(exc_info.value)

    def test_compile_with_malformed_json(self):
        """Test that malformed JSON raises JSONDecodeError (not CompilationError)."""
        registry = MagicMock()
        bad_json = '{"nodes": [}}'

        with pytest.raises(json.JSONDecodeError):
            compile_ir_to_flow(bad_json, registry)

    def test_compile_with_missing_nodes(self):
        """Test compilation fails with proper error for missing nodes."""
        registry = MagicMock()
        ir_dict = {"edges": []}

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir_dict, registry)

        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'nodes' key" in str(error)

    def test_compile_with_missing_edges(self):
        """Test compilation fails with proper error for missing edges."""
        registry = MagicMock()
        ir_dict = {"nodes": []}

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir_dict, registry)

        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'edges' key" in str(error)

    def test_compile_logging(self, caplog):
        """Test that compilation logs appropriate messages."""
        registry = MagicMock()
        # Need a valid node structure now that compilation is implemented
        ir_dict = {"nodes": [{"id": "n1", "type": "test-node"}], "edges": []}

        # Mock the import_node_class to return a mock node class
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            from pocketflow import BaseNode

            # Create a simple mock node class
            class MockNode(BaseNode):
                def __init__(self):
                    super().__init__()

                def set_params(self, params):
                    self.params = params

            mock_import.return_value = MockNode

            with caplog.at_level(logging.DEBUG):
                # This should now succeed
                flow = compile_ir_to_flow(ir_dict, registry)
                assert flow is not None

            # Check log messages
            log_messages = [record.message for record in caplog.records]
            assert any("Starting IR compilation" in msg for msg in log_messages)
            assert any("IR structure validated" in msg for msg in log_messages)
            assert any("ready for compilation" in msg for msg in log_messages)
            assert any("Compilation successful" in msg for msg in log_messages)

            # Check structured logging extras
            for record in caplog.records:
                if "Starting IR compilation" in record.message:
                    assert record.phase == "init"
                elif "IR structure validated" in record.message:
                    assert record.phase == "validation"
                    assert hasattr(record, "node_count")
                    assert record.node_count == 1

    def test_compile_with_complex_ir(self):
        """Test compilation with a more realistic IR structure."""
        registry = MagicMock()
        ir_dict = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"path": "input.txt"}},
                {"id": "proc", "type": "transform", "params": {"format": "json"}},
                {"id": "save", "type": "write-file", "params": {"path": "output.txt"}},
            ],
            "edges": [{"source": "read", "target": "proc"}, {"source": "proc", "target": "save"}],
        }

        # Mock the import_node_class to return a mock node class
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            from pocketflow import BaseNode

            class MockNode(BaseNode):
                def __init__(self):
                    super().__init__()

                def set_params(self, params):
                    self.params = params

            mock_import.return_value = MockNode

            # Should now compile successfully
            flow = compile_ir_to_flow(ir_dict, registry)
            assert flow is not None

            # Verify import was called for all three node types
            assert mock_import.call_count == 3
