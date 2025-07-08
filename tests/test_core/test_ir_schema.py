"""Tests for workflow IR schema validation."""

import pytest

from pflow.core import FLOW_IR_SCHEMA, ValidationError, validate_ir


class TestSchemaStructure:
    """Test the schema definition itself."""

    def test_schema_is_valid_json_schema(self):
        """Verify the schema follows JSON Schema Draft 7 format."""
        # This is validated internally by validate_ir, but let's be explicit
        from jsonschema import Draft7Validator

        # Should not raise
        Draft7Validator.check_schema(FLOW_IR_SCHEMA)

    def test_schema_has_required_top_level_properties(self):
        """Check schema defines expected top-level properties."""
        assert "properties" in FLOW_IR_SCHEMA
        props = FLOW_IR_SCHEMA["properties"]

        assert "ir_version" in props
        assert "nodes" in props
        assert "edges" in props
        assert "start_node" in props
        assert "mappings" in props

    def test_schema_requires_minimal_fields(self):
        """Verify only ir_version and nodes are required."""
        assert FLOW_IR_SCHEMA["required"] == ["ir_version", "nodes"]


class TestValidIR:
    """Test validation of valid IR structures."""

    def test_minimal_valid_ir(self):
        """Test the simplest valid IR with single node."""
        ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "read-file"}]}
        # Should not raise
        validate_ir(ir)

    def test_valid_ir_with_params(self):
        """Test node with parameters."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "reader", "type": "read-file", "params": {"path": "input.txt", "encoding": "utf-8"}}],
        }
        validate_ir(ir)

    def test_valid_ir_with_edges(self):
        """Test IR with multiple nodes and edges."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file"},
                {"id": "n2", "type": "llm"},
                {"id": "n3", "type": "write-file"},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        }
        validate_ir(ir)

    def test_valid_ir_with_action_edges(self):
        """Test edges with action strings."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "check", "type": "validator"},
                {"id": "success", "type": "logger"},
                {"id": "error", "type": "error-handler"},
            ],
            "edges": [
                {"from": "check", "to": "success", "action": "valid"},
                {"from": "check", "to": "error", "action": "invalid"},
            ],
        }
        validate_ir(ir)

    def test_valid_ir_with_start_node(self):
        """Test explicit start_node specification."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "step1"}, {"id": "n2", "type": "step2"}],
            "start_node": "n2",  # Start with second node
        }
        validate_ir(ir)

    def test_valid_ir_with_mappings(self):
        """Test IR with proxy mappings."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "llm", "type": "llm-node"}],
            "mappings": {
                "llm": {
                    "input_mappings": {"prompt": "formatted_prompt"},
                    "output_mappings": {"response": "article_summary"},
                }
            },
        }
        validate_ir(ir)

    def test_valid_ir_from_json_string(self):
        """Test validation of JSON string input."""
        ir_json = """{
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test"}]
        }"""
        validate_ir(ir_json)

    def test_valid_ir_with_template_variables(self):
        """Test that template variables in params are preserved as strings."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "writer", "type": "write-file", "params": {"path": "$output_path", "content": "Result: $result"}}
            ],
        }
        # Template variables should pass through as regular strings
        validate_ir(ir)


class TestInvalidIR:
    """Test validation catches invalid IR structures."""

    def test_missing_ir_version(self):
        """Test error when ir_version is missing."""
        ir = {"nodes": [{"id": "n1", "type": "test"}]}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "ir_version" in str(error)
        assert "required" in str(error).lower()
        assert error.path == "root"

    def test_missing_nodes(self):
        """Test error when nodes array is missing."""
        ir = {"ir_version": "0.1.0"}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes" in str(error)
        assert "required" in str(error).lower()

    def test_empty_nodes_array(self):
        """Test error when nodes array is empty."""
        ir = {"ir_version": "0.1.0", "nodes": []}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "at least one" in str(error).lower()
        assert error.path == "nodes"

    def test_invalid_version_format(self):
        """Test error for invalid version format."""
        ir = {
            "ir_version": "1.0",  # Missing patch version
            "nodes": [{"id": "n1", "type": "test"}],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "ir_version" in error.path
        assert "semantic versioning" in error.suggestion.lower()

    def test_node_missing_id(self):
        """Test error when node is missing ID."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"type": "test"}  # Missing id
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes[0]" in error.path
        assert "'id'" in str(error)

    def test_node_missing_type(self):
        """Test error when node is missing type."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1"}  # Missing type
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes[0]" in error.path
        assert "'type'" in str(error)

    def test_node_extra_properties(self):
        """Test error when node has unknown properties."""
        ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test", "unknown_field": "value"}]}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes[0]" in error.path
        assert "unknown properties" in error.suggestion.lower()

    def test_edge_missing_from(self):
        """Test error when edge is missing 'from' field."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test"}, {"id": "n2", "type": "test"}],
            "edges": [
                {"to": "n2"}  # Missing from
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "edges[0]" in error.path
        assert "'from'" in str(error)

    def test_edge_references_nonexistent_node(self):
        """Test error when edge references non-existent node."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test"}],
            "edges": [
                {"from": "n1", "to": "n2"}  # n2 doesn't exist
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "non-existent node 'n2'" in str(error)
        assert "edges[0].to" in error.path
        assert "['n1']" in error.suggestion  # Suggests valid nodes

    def test_duplicate_node_ids(self):
        """Test error when multiple nodes have same ID."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "test1"},
                {"id": "n1", "type": "test2"},  # Duplicate ID
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "Duplicate node ID 'n1'" in str(error)
        assert "nodes[1].id" in error.path
        assert "unique" in error.suggestion.lower()

    def test_wrong_type_for_nodes(self):
        """Test error when nodes is not an array."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": {"n1": {"type": "test"}},  # Dict instead of array
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes" in error.path
        assert "dict" in error.suggestion
        assert "array" in error.suggestion

    def test_invalid_json_string(self):
        """Test error handling for malformed JSON."""
        with pytest.raises(ValueError) as exc_info:
            validate_ir("{invalid json")

        assert "Invalid JSON" in str(exc_info.value)


class TestErrorMessages:
    """Test quality of error messages and suggestions."""

    def test_error_message_includes_path(self):
        """Verify error messages include the path to the problem."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "test"},
                {"id": "n2"},  # Missing type in second node
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert error.path == "nodes[1]"
        assert "nodes[1]" in str(error)

    def test_error_suggestions_are_helpful(self):
        """Test that suggestions provide actionable guidance."""
        # Test version format suggestion
        ir = {"ir_version": "bad-version", "nodes": [{"id": "n1", "type": "test"}]}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        assert "0.1.0" in exc_info.value.suggestion

        # Test type mismatch suggestion
        ir = {"ir_version": "0.1.0", "nodes": "not-an-array"}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        assert "str" in exc_info.value.suggestion
        assert "array" in exc_info.value.suggestion


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_node_id(self):
        """Test handling of very long node IDs."""
        long_id = "n" * 1000
        ir = {"ir_version": "0.1.0", "nodes": [{"id": long_id, "type": "test"}]}
        # Should be valid - no length restriction
        validate_ir(ir)

    def test_unicode_in_params(self):
        """Test Unicode strings in parameters."""
        ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test", "params": {"message": "Hello 世界 🌍"}}]}
        validate_ir(ir)

    def test_deeply_nested_params(self):
        """Test deeply nested parameter objects."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {"config": {"nested": {"deeply": {"value": 42}}}}}],
        }
        validate_ir(ir)

    def test_self_referential_edge(self):
        """Test edge from node to itself."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "loop"}],
            "edges": [
                {"from": "n1", "to": "n1"}  # Self-loop
            ],
        }
        # Should be valid - self-loops are allowed
        validate_ir(ir)
