"""Tests for the compiler foundation (subtask 4.1).

This module tests the basic infrastructure of the IR compiler including
error handling, input parsing, and structure validation. Actual compilation
logic will be tested in future subtasks.
"""

import json
from unittest.mock import MagicMock

import pytest

from pflow.runtime import compile_ir_to_flow
from pflow.runtime.compiler import CompilationError, _parse_ir_input
from pflow.runtime.workflow_validator import validate_ir_structure


class TestCompilationError:
    """Test the CompilationError exception class behavior.

    FIX HISTORY:
    - Removed string formatting tests that tested implementation details
    - Focus on testing that error context is preserved for debugging
    - Test error inheritance and exception handling behavior
    """

    def test_error_preserves_context_for_debugging(self):
        """Test CompilationError preserves all context attributes for debugging."""
        error = CompilationError(
            message="Test error",
            phase="testing",
            node_id="node1",
            node_type="test-type",
            details={"key": "value"},
            suggestion="Fix the thing",
        )

        # Test that context is preserved (what debuggers and error handlers need)
        assert error.phase == "testing"
        assert error.node_id == "node1"
        assert error.node_type == "test-type"
        assert error.details == {"key": "value"}
        assert error.suggestion == "Fix the thing"

        # Test it's a proper exception
        assert isinstance(error, Exception)

    def test_error_has_sensible_defaults(self):
        """Test CompilationError provides sensible defaults when context is missing."""
        error = CompilationError("Simple error")

        # Test defaults don't break error handling
        assert error.phase == "unknown"
        assert error.node_id is None
        assert error.node_type is None
        assert error.details == {}
        assert error.suggestion is None

        # Test it can be raised and caught
        with pytest.raises(CompilationError) as exc_info:
            raise error
        assert exc_info.value is error

    def test_error_can_be_chained_and_handled(self):
        """Test CompilationError works properly in exception chains."""
        original_error = ValueError("Original problem")

        try:
            raise original_error
        except ValueError as e:
            compilation_error = CompilationError(
                "Compilation failed", phase="validation", details={"original_error": str(e)}
            )

            # Test the compilation error can be raised and preserves context
            with pytest.raises(CompilationError) as exc_info:
                raise compilation_error from e

            caught_error = exc_info.value
            assert caught_error.phase == "validation"
            assert "Original problem" in caught_error.details["original_error"]
            assert caught_error.__cause__ is original_error


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

    def test_compile_single_node_workflow_succeeds(self):
        """Test that compilation produces working flow for single node workflow.

        FIX HISTORY:
        - Removed log message testing (brittle implementation details)
        - Use real ExampleNode instead of mock
        - Focus on testing that compilation produces working flow
        """
        import tempfile
        from pathlib import Path

        from pflow.registry.registry import Registry

        # Create test registry with real node metadata
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Save real node metadata for ExampleNode
            test_node_metadata = {
                "test-node": {
                    "module": "pflow.nodes.test_node",
                    "class_name": "ExampleNode",
                    "docstring": "Test node for validation",
                    "file_path": "src/pflow/nodes/test_node.py",
                }
            }
            registry.save(test_node_metadata)

            # Create simple IR with one node
            ir_dict = {"nodes": [{"id": "n1", "type": "test-node"}], "edges": []}

            # Compile the workflow
            flow = compile_ir_to_flow(ir_dict, registry)

            # Test that compilation succeeded and produced working flow
            assert flow is not None
            from pflow.pocketflow import Flow

            assert isinstance(flow, Flow)

            # Test that the flow can actually execute
            shared_store = {"test_input": "hello"}
            flow.run(shared_store)

            # Verify the node executed correctly (with namespacing)
            assert "n1" in shared_store
            assert "test_output" in shared_store["n1"]
            assert shared_store["n1"]["test_output"] == "Processed: hello"

    def test_compile_multi_node_workflow_with_chaining(self):
        """Test compilation with multiple nodes connected by edges.

        FIX HISTORY:
        - Removed mock import call counting (testing implementation details)
        - Use real ExampleNode instead of MockNode
        - Focus on testing actual workflow execution with multiple nodes
        """
        import tempfile
        from pathlib import Path

        from pflow.registry.registry import Registry

        # Create test registry with multiple real nodes
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Save metadata for multiple test nodes
            test_nodes_metadata = {
                "test-node": {
                    "module": "pflow.nodes.test_node",
                    "class_name": "ExampleNode",
                    "docstring": "Test node for validation",
                    "file_path": "src/pflow/nodes/test_node.py",
                },
                "test-node-retry": {
                    "module": "pflow.nodes.test_node_retry",
                    "class_name": "RetryExampleNode",
                    "docstring": "Test node with retry",
                    "file_path": "src/pflow/nodes/test_node_retry.py",
                },
            }
            registry.save(test_nodes_metadata)

            # Create multi-node workflow IR
            ir_dict = {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "input", "type": "test-node"},
                    {"id": "process", "type": "test-node"},
                    {"id": "output", "type": "test-node-retry"},
                ],
                "edges": [{"source": "input", "target": "process"}, {"source": "process", "target": "output"}],
            }

            # Compile the workflow
            flow = compile_ir_to_flow(ir_dict, registry)
            assert flow is not None

            # Test that the multi-node flow executes correctly
            shared_store = {"test_input": "start", "retry_input": "test data"}
            flow.run(shared_store)

            # Verify all nodes executed in sequence (with namespacing)
            # Each ExampleNode processes its input and passes to next
            # The last node is RetryExampleNode which writes to retry_output
            assert "output" in shared_store
            assert "retry_output" in shared_store["output"]
            output = shared_store["output"]["retry_output"]
            assert "Processed" in output  # RetryExampleNode's output format

            # Also verify the other nodes ran
            assert "input" in shared_store
            assert "process" in shared_store
