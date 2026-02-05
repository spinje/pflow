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
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "read-file", "purpose": "Read file from filesystem for processing"}],
        }
        # Should not raise
        validate_ir(ir)

    def test_valid_ir_with_params(self):
        """Test node with parameters."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "reader",
                    "type": "read-file",
                    "purpose": "Read input text file with UTF-8 encoding",
                    "params": {"path": "input.txt", "encoding": "utf-8"},
                }
            ],
        }
        validate_ir(ir)

    def test_valid_ir_with_edges(self):
        """Test IR with multiple nodes and edges."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "purpose": "Read input data from file"},
                {"id": "n2", "type": "llm", "purpose": "Process text through language model"},
                {"id": "n3", "type": "write-file", "purpose": "Save processed output to file"},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        }
        validate_ir(ir)

    def test_valid_ir_with_action_edges(self):
        """Test edges with action strings."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "check", "type": "validator", "purpose": "Validate input data format and constraints"},
                {"id": "success", "type": "logger", "purpose": "Log successful validation results"},
                {"id": "error", "type": "error-handler", "purpose": "Handle validation errors and log failures"},
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
            "nodes": [
                {"id": "n1", "type": "step1", "purpose": "Execute first processing step"},
                {"id": "n2", "type": "step2", "purpose": "Execute second processing step"},
            ],
            "start_node": "n2",  # Start with second node
        }
        validate_ir(ir)

    def test_valid_ir_with_mappings(self):
        """Test IR with proxy mappings."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "llm", "type": "llm-node", "purpose": "Process text using language model API"}],
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
            "nodes": [{"id": "n1", "type": "test", "purpose": "Test node for validation purposes"}]
        }"""
        validate_ir(ir_json)

    def test_valid_ir_with_template_variables(self):
        """Test that template variables in params are preserved as strings."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "purpose": "Write template-based content to file",
                    "params": {"path": "${output_path}", "content": "Result: ${result}"},
                }
            ],
        }
        # Template variables should pass through as regular strings
        validate_ir(ir)


class TestInvalidIR:
    """Test validation catches invalid IR structures."""

    def test_missing_ir_version(self):
        """Test error when ir_version is missing."""
        ir = {"nodes": [{"id": "n1", "type": "test", "purpose": "Test node for validation check"}]}

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
            "nodes": [{"id": "n1", "type": "test", "purpose": "Test node for version validation"}],
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
                {"type": "test", "purpose": "Test node missing required id field"}  # Missing id
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
                {"id": "n1", "purpose": "Test node missing required type field"}  # Missing type
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes[0]" in error.path
        assert "'type'" in str(error)

    def test_node_extra_properties(self):
        """Test error when node has unknown properties."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "n1",
                    "type": "test",
                    "purpose": "Test node with extra unknown properties",
                    "unknown_field": "value",
                }
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error = exc_info.value
        assert "nodes[0]" in error.path
        assert "unknown properties" in error.suggestion.lower()

    def test_edge_missing_from(self):
        """Test error when edge is missing 'from' field."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "test", "purpose": "First test node for edge validation"},
                {"id": "n2", "type": "test", "purpose": "Second test node for edge validation"},
            ],
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
            "nodes": [{"id": "n1", "type": "test", "purpose": "Test node for edge reference validation"}],
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
                {"id": "n1", "type": "test1", "purpose": "First node with duplicate ID test"},
                {"id": "n1", "type": "test2", "purpose": "Second node with duplicate ID test"},  # Duplicate ID
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
            "nodes": {"n1": {"type": "test", "purpose": "Test node in wrong structure"}},  # Dict instead of array
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

        assert "Invalid workflow data" in str(exc_info.value)


class TestErrorMessages:
    """Test quality of error messages and suggestions."""

    def test_error_message_includes_path(self):
        """Verify error messages include the path to the problem."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "test", "purpose": "First node for path error testing"},
                {"id": "n2", "purpose": "Second node missing type field"},  # Missing type in second node
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
        ir = {
            "ir_version": "bad-version",
            "nodes": [{"id": "n1", "type": "test", "purpose": "Test node for version format validation"}],
        }

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        assert "0.1.0" in exc_info.value.suggestion

        # Test type mismatch suggestion
        ir = {"ir_version": "0.1.0", "nodes": "not-an-array"}

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        assert "str" in exc_info.value.suggestion
        assert "array" in exc_info.value.suggestion


class TestInputTypeAliases:
    """Test that input type field accepts both JSON Schema and Python type names."""

    def test_json_schema_types_accepted(self):
        """JSON Schema canonical types should be accepted."""
        for type_name in ["string", "number", "boolean", "object", "array"]:
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test", "purpose": "Test node"}],
                "inputs": {"param": {"type": type_name, "required": True}},
            }
            validate_ir(ir)  # Should not raise

    def test_python_type_aliases_accepted(self):
        """Python type aliases should be accepted for user convenience."""
        for type_name in ["str", "int", "integer", "float", "bool", "dict", "list"]:
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test", "purpose": "Test node"}],
                "inputs": {"param": {"type": type_name, "required": True}},
            }
            validate_ir(ir)  # Should not raise

    def test_invalid_type_rejected(self):
        """Invalid type names should be rejected with helpful error."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "purpose": "Test node"}],
            "inputs": {"param": {"type": "invalid_type", "required": True}},
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "inputs.param.type" in exc_info.value.path


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_node_id(self):
        """Test handling of very long node IDs."""
        long_id = "n" * 1000
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": long_id, "type": "test", "purpose": "Test node with extremely long identifier"}],
        }
        # Should be valid - no length restriction
        validate_ir(ir)

    def test_unicode_in_params(self):
        """Test Unicode strings in parameters."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "n1",
                    "type": "test",
                    "purpose": "Test node with Unicode parameter values",
                    "params": {"message": "Hello 世界 🌍"},
                }
            ],
        }
        validate_ir(ir)

    def test_deeply_nested_params(self):
        """Test deeply nested parameter objects."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "n1",
                    "type": "test",
                    "purpose": "Test node with deeply nested parameters",
                    "params": {"config": {"nested": {"deeply": {"value": 42}}}},
                }
            ],
        }
        validate_ir(ir)

    def test_self_referential_edge(self):
        """Test edge from node to itself."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "loop", "purpose": "Test node with self-referential edge"}],
            "edges": [
                {"from": "n1", "to": "n1"}  # Self-loop
            ],
        }
        # Should be valid - self-loops are allowed
        validate_ir(ir)


class TestBatchConfig:
    """Test validation of batch configuration on nodes."""

    def test_valid_batch_config_minimal(self):
        """Test valid batch config with only required 'items' field."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Summarize each file in parallel",
                    "batch": {
                        "items": "${files.list}",
                    },
                    "params": {"prompt": "Summarize: ${item}"},
                }
            ],
        }
        validate_ir(ir)

    def test_valid_batch_config_all_fields(self):
        """Test valid batch config with all optional fields."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Process each file with error handling",
                    "batch": {
                        "items": "${list_files.files}",
                        "as": "current_file",
                        "error_handling": "continue",
                    },
                    "params": {"prompt": "Process: ${current_file.content}"},
                }
            ],
        }
        validate_ir(ir)

    def test_valid_batch_config_fail_fast(self):
        """Test valid batch config with fail_fast error handling."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Process files, stop on first error",
                    "batch": {
                        "items": "${data}",
                        "error_handling": "fail_fast",
                    },
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_missing_items(self):
        """Test error when batch config is missing required 'items' field."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Batch node missing items field",
                    "batch": {
                        "as": "item",  # Missing required 'items'
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "'items'" in str(exc_info.value)
        assert "required" in str(exc_info.value).lower()

    def test_batch_config_items_not_template(self):
        """Test error when items is not a template reference."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Batch node with invalid items format",
                    "batch": {
                        "items": "not_a_template",  # Should be ${...}
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        # Pattern validation fails
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_invalid_as_identifier(self):
        """Test error when 'as' is not a valid identifier."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Batch node with invalid as identifier",
                    "batch": {
                        "items": "${data}",
                        "as": "123invalid",  # Invalid: starts with number
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_invalid_as_with_special_chars(self):
        """Test error when 'as' contains special characters."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Batch node with special chars in as",
                    "batch": {
                        "items": "${data}",
                        "as": "my-item",  # Invalid: contains hyphen
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_invalid_error_handling(self):
        """Test error when error_handling is not valid enum value."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Batch node with invalid error handling",
                    "batch": {
                        "items": "${data}",
                        "error_handling": "ignore",  # Invalid value
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_extra_properties_rejected(self):
        """Test error when batch config has unknown properties."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Batch node with extra properties",
                    "batch": {
                        "items": "${data}",
                        "unknown_field": "not_allowed",  # Unknown property
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_with_complex_template(self):
        """Test valid batch config with complex nested template path."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Process nested data structure",
                    "batch": {
                        "items": "${api_response.data.items}",
                        "as": "record",
                    },
                    "params": {"prompt": "Analyze: ${record.nested.field}"},
                }
            ],
        }
        validate_ir(ir)

    def test_valid_as_identifiers(self):
        """Test various valid Python identifier patterns for 'as' field."""
        valid_identifiers = ["item", "x", "_private", "Item", "my_item", "item2", "_123"]
        for identifier in valid_identifiers:
            ir = {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "batch_node",
                        "type": "llm",
                        "purpose": f"Test valid identifier: {identifier}",
                        "batch": {
                            "items": "${data}",
                            "as": identifier,
                        },
                    }
                ],
            }
            validate_ir(ir)  # Should not raise

    def test_batch_config_inline_array_with_templates(self):
        """Test inline array with templates inside elements."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "shell",
                    "purpose": "Run multiple commands with same data",
                    "batch": {
                        "items": [
                            {"cmd": "echo", "input": "${data}"},
                            {"cmd": "wc -l", "input": "${data}"},
                        ],
                        "as": "task",
                    },
                    "params": {"command": "${task.cmd}", "stdin": "${task.input}"},
                }
            ],
        }
        validate_ir(ir)  # Should not raise

    def test_batch_config_inline_array_empty_rejected(self):
        """Test that empty inline array is rejected (minItems: 1)."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Empty array should fail",
                    "batch": {
                        "items": [],  # Empty array not allowed
                    },
                }
            ],
        }
        with pytest.raises(ValidationError):
            validate_ir(ir)


class TestBatchConfigPhase2:
    """Test validation of Phase 2 batch configuration fields (parallel execution)."""

    def test_batch_config_parallel_true(self):
        """Test valid batch config with parallel execution enabled."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Process items in parallel",
                    "batch": {
                        "items": "${data}",
                        "parallel": True,
                    },
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_parallel_false(self):
        """Test valid batch config with parallel explicitly false."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Process items sequentially",
                    "batch": {
                        "items": "${data}",
                        "parallel": False,
                    },
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_parallel_with_max_concurrent(self):
        """Test valid batch config with parallel and max_concurrent."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Process items with limited concurrency",
                    "batch": {
                        "items": "${data}",
                        "parallel": True,
                        "max_concurrent": 5,
                    },
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_max_concurrent_minimum(self):
        """Test max_concurrent accepts minimum value of 1."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_concurrent": 1,
                    },
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_max_concurrent_maximum(self):
        """Test max_concurrent accepts maximum value of 100."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_concurrent": 100,
                    },
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_max_concurrent_zero_invalid(self):
        """Test max_concurrent rejects 0 (below minimum)."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_concurrent": 0,
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_max_concurrent_over_maximum_invalid(self):
        """Test max_concurrent rejects values over 100."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_concurrent": 101,
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_max_retries_valid(self):
        """Test max_retries accepts valid values (1-10)."""
        for retries in [1, 5, 10]:
            ir = {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "batch_node",
                        "type": "llm",
                        "batch": {
                            "items": "${data}",
                            "max_retries": retries,
                        },
                    }
                ],
            }
            validate_ir(ir)

    def test_batch_config_max_retries_zero_invalid(self):
        """Test max_retries rejects 0 (below minimum)."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_retries": 0,
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_max_retries_over_maximum_invalid(self):
        """Test max_retries rejects values over 10."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_retries": 11,
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_retry_wait_valid(self):
        """Test retry_wait accepts valid values (>= 0)."""
        for wait in [0, 0.5, 1, 1.5, 10]:
            ir = {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "batch_node",
                        "type": "llm",
                        "batch": {
                            "items": "${data}",
                            "retry_wait": wait,
                        },
                    }
                ],
            }
            validate_ir(ir)

    def test_batch_config_retry_wait_negative_invalid(self):
        """Test retry_wait rejects negative values."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "retry_wait": -1,
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_all_phase2_fields(self):
        """Test valid batch config with all Phase 2 fields."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "purpose": "Full Phase 2 config",
                    "batch": {
                        "items": "${data}",
                        "as": "record",
                        "error_handling": "continue",
                        "parallel": True,
                        "max_concurrent": 5,
                        "max_retries": 3,
                        "retry_wait": 1.5,
                    },
                    "params": {"prompt": "Process: ${record}"},
                }
            ],
        }
        validate_ir(ir)

    def test_batch_config_parallel_invalid_type(self):
        """Test parallel rejects non-boolean values."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "parallel": "true",  # String instead of boolean
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path

    def test_batch_config_max_concurrent_invalid_type(self):
        """Test max_concurrent rejects non-integer values."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "llm",
                    "batch": {
                        "items": "${data}",
                        "max_concurrent": 5.5,  # Float instead of integer
                    },
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)
        assert "nodes[0]" in exc_info.value.path
