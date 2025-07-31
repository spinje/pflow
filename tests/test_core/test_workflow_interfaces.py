"""Tests for workflow input and output declarations."""

import pytest

from pflow.core import ValidationError, validate_ir


class TestWorkflowInterfaces:
    """Test workflow input and output declarations."""

    class TestValidDeclarations:
        """Test valid input/output declarations."""

        def test_minimal_workflow_without_interfaces(self):
            """Test backward compatibility - workflows without interfaces are valid."""
            ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test"}]}
            # Should not raise
            validate_ir(ir)

        def test_workflow_with_empty_interfaces(self):
            """Test empty inputs and outputs objects are valid."""
            ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test"}], "inputs": {}, "outputs": {}}
            validate_ir(ir)

        def test_required_input_with_all_fields(self):
            """Test required input with description and type."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"text": {"description": "Input text to process", "required": True, "type": "string"}},
            }
            validate_ir(ir)

        def test_optional_input_with_default(self):
            """Test optional input with default value."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "max_length": {
                        "description": "Maximum output length",
                        "required": False,
                        "type": "number",
                        "default": 1000,
                    }
                },
            }
            validate_ir(ir)

        def test_multiple_inputs_with_various_types(self):
            """Test multiple inputs with different configurations."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "text": {"description": "Text to analyze", "required": True, "type": "string"},
                    "language": {"description": "Language code", "required": False, "type": "string", "default": "en"},
                    "settings": {
                        "description": "Configuration object",
                        "required": False,
                        "type": "object",
                        "default": {"mode": "fast"},
                    },
                    "tags": {"description": "Tag list", "required": False, "type": "array", "default": []},
                    "enabled": {"description": "Feature flag", "required": False, "type": "boolean", "default": True},
                },
            }
            validate_ir(ir)

        def test_minimal_input_declaration(self):
            """Test input with only required fields."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "minimal": {}  # All fields are optional
                },
            }
            validate_ir(ir)

        def test_output_declaration_with_all_fields(self):
            """Test output declaration with description and type."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": {"result": {"description": "Processing result", "type": "string"}},
            }
            validate_ir(ir)

        def test_multiple_outputs(self):
            """Test multiple output declarations."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": {
                    "summary": {"description": "Generated summary", "type": "string"},
                    "word_count": {"description": "Total words", "type": "number"},
                    "metadata": {"description": "Additional info", "type": "object"},
                },
            }
            validate_ir(ir)

        def test_output_without_description(self):
            """Test output declaration without optional description."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": {"result": {"type": "string"}},
            }
            validate_ir(ir)

        def test_complete_workflow_interface(self):
            """Test workflow with both inputs and outputs."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "analyzer", "type": "text-analyzer", "params": {"text": "$text", "lang": "$language"}}
                ],
                "inputs": {
                    "text": {"description": "Text to analyze", "required": True, "type": "string"},
                    "language": {"description": "Language code", "required": False, "type": "string", "default": "en"},
                },
                "outputs": {
                    "analysis": {"description": "Analysis results", "type": "object"},
                    "confidence": {"description": "Confidence score", "type": "number"},
                },
            }
            validate_ir(ir)

        def test_unicode_in_descriptions(self):
            """Test Unicode characters in descriptions."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"text": {"description": "Text to process 文本处理 🌍", "type": "string"}},
                "outputs": {"result": {"description": "Result 结果 ✨", "type": "string"}},
            }
            validate_ir(ir)

        def test_very_long_descriptions(self):
            """Test very long descriptions are accepted."""
            long_desc = "This is a very long description. " * 100
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"input1": {"description": long_desc, "type": "string"}},
                "outputs": {"output1": {"description": long_desc, "type": "string"}},
            }
            validate_ir(ir)

    class TestInvalidDeclarations:
        """Test invalid declarations raise appropriate errors."""

        def test_input_name_with_dash_currently_allowed(self):
            """Test that input names with dashes are currently allowed.

            Current behavior: Input names are not validated against identifier rules.
            This allows names like 'invalid-name' which might not be valid in some contexts.
            """
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"param-with-dash": {"description": "Parameter with dash", "type": "string"}},
            }

            # This currently passes - documents current behavior
            validate_ir(ir)

        def test_input_name_starting_with_number_currently_allowed(self):
            """Test that input names starting with numbers are currently allowed.

            Current behavior: Input names are not validated against identifier rules.
            This allows names like '123param' which might not be valid identifiers in some contexts.
            """
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"123param": {"description": "Parameter starting with number", "type": "string"}},
            }

            # This currently passes - documents current behavior
            validate_ir(ir)

        def test_invalid_type_value(self):
            """Test invalid type value raises error."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "text": {
                        "description": "Text input",
                        "type": "invalid_type",  # Not in enum
                    }
                },
            }

            with pytest.raises(ValidationError) as exc_info:
                validate_ir(ir)

            error = exc_info.value
            assert "invalid_type" in str(error)
            assert "enum" in str(error).lower() or "not one of" in str(error).lower()

        def test_required_field_wrong_type(self):
            """Test required field with wrong type."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "text": {
                        "description": "Text input",
                        "required": "yes",  # Should be boolean
                        "type": "string",
                    }
                },
            }

            with pytest.raises(ValidationError) as exc_info:
                validate_ir(ir)

            error = exc_info.value
            assert "boolean" in str(error).lower()

        def test_inputs_as_list_instead_of_object(self):
            """Test inputs must be object, not array."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": ["input1", "input2"],  # Wrong type
            }

            with pytest.raises(ValidationError) as exc_info:
                validate_ir(ir)

            error = exc_info.value
            assert "inputs" in error.path
            assert "list" in error.suggestion or "array" in error.suggestion

        def test_outputs_as_list_instead_of_object(self):
            """Test outputs must be object, not array."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": ["output1", "output2"],  # Wrong type
            }

            with pytest.raises(ValidationError) as exc_info:
                validate_ir(ir)

            error = exc_info.value
            assert "outputs" in error.path

        def test_output_name_with_special_chars_currently_allowed(self):
            """Test that output names with special characters are currently allowed.

            Current behavior: Output names are not validated against identifier rules.
            This allows names like 'result!data' which might not be valid identifiers in some contexts.
            """
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": {"result!data": {"description": "Result with special character", "type": "string"}},
            }

            # This currently passes - documents current behavior
            validate_ir(ir)

        def test_output_with_invalid_type(self):
            """Test output with invalid type value."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": {
                    "result": {
                        "description": "Result",
                        "type": "complex",  # Not in enum
                    }
                },
            }

            with pytest.raises(ValidationError) as exc_info:
                validate_ir(ir)

            error = exc_info.value
            assert "complex" in str(error)

        def test_input_with_extra_properties(self):
            """Test input with unknown properties raises error."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "text": {
                        "description": "Text input",
                        "type": "string",
                        "unknown_field": "value",  # Not allowed
                    }
                },
            }

            with pytest.raises(ValidationError) as exc_info:
                validate_ir(ir)

            error = exc_info.value
            assert "unknown" in error.suggestion.lower() or "additional" in str(error).lower()

        def test_output_with_extra_properties(self):
            """Test output with unknown properties raises error."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "outputs": {
                    "result": {
                        "description": "Result",
                        "type": "string",
                        "required": True,  # Not allowed for outputs
                    }
                },
            }

            with pytest.raises(ValidationError):
                validate_ir(ir)

    class TestBackwardCompatibility:
        """Test workflows without declarations still work."""

        def test_workflow_without_inputs_field(self):
            """Test workflow without inputs field is valid."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test", "params": {"value": "$input"}}],
                "outputs": {"result": {"type": "string"}},
            }
            # Should work - inputs field is optional
            validate_ir(ir)

        def test_workflow_without_outputs_field(self):
            """Test workflow without outputs field is valid."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"text": {"type": "string"}},
            }
            # Should work - outputs field is optional
            validate_ir(ir)

        def test_workflow_with_neither_field(self):
            """Test workflow without inputs or outputs is valid."""
            ir = {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test", "params": {"value": "$dynamic"}}]}
            # Should work - both fields are optional
            validate_ir(ir)

        def test_mixed_declared_and_undeclared_variables(self):
            """Test workflow can use both declared and undeclared variables."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "n1",
                        "type": "test",
                        "params": {
                            "declared": "$text",  # Declared input
                            "undeclared": "$dynamic",  # Not declared
                        },
                    }
                ],
                "inputs": {"text": {"description": "Declared input", "type": "string"}},
            }
            # Should work - undeclared variables are allowed
            validate_ir(ir)

    class TestEdgeCases:
        """Test edge cases and boundary conditions."""

        def test_empty_string_descriptions(self):
            """Test empty string descriptions are valid."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"text": {"description": "", "type": "string"}},
                "outputs": {"result": {"description": "", "type": "string"}},
            }
            validate_ir(ir)

        def test_null_default_values(self):
            """Test null default values are valid."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "optional": {"description": "Optional input", "required": False, "type": "string", "default": None}
                },
            }
            validate_ir(ir)

        def test_complex_default_values(self):
            """Test complex object and array defaults."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "config": {
                        "description": "Configuration",
                        "required": False,
                        "type": "object",
                        "default": {"nested": {"deeply": {"value": 42, "list": [1, 2, 3]}}},
                    },
                    "tags": {
                        "description": "Tags",
                        "required": False,
                        "type": "array",
                        "default": ["tag1", "tag2", {"complex": "tag"}],
                    },
                },
            }
            validate_ir(ir)

        def test_reserved_input_names(self):
            """Test common reserved names are actually allowed as inputs."""
            # These should be valid - we don't restrict input names beyond identifier rules
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "params": {"type": "object"},
                    "nodes": {"type": "array"},
                },
            }
            validate_ir(ir)

        def test_numeric_string_input_names(self):
            """Test input names that look numeric but are valid identifiers."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "input1": {"type": "string"},
                    "input2": {"type": "string"},
                    "input_3": {"type": "string"},
                    "_123": {"type": "string"},  # Valid identifier
                },
            }
            validate_ir(ir)

        def test_case_sensitive_input_names(self):
            """Test input names are case sensitive."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {"text": {"type": "string"}, "Text": {"type": "string"}, "TEXT": {"type": "string"}},
            }
            # All three are different inputs
            validate_ir(ir)

        def test_boolean_default_values(self):
            """Test boolean default values work correctly."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "enabled": {"description": "Feature flag", "required": False, "type": "boolean", "default": True},
                    "disabled": {"description": "Another flag", "required": False, "type": "boolean", "default": False},
                },
            }
            validate_ir(ir)

        def test_numeric_default_values(self):
            """Test various numeric default values."""
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test"}],
                "inputs": {
                    "integer": {"type": "number", "default": 42},
                    "float": {"type": "number", "default": 3.14},
                    "negative": {"type": "number", "default": -100},
                    "zero": {"type": "number", "default": 0},
                },
            }
            validate_ir(ir)
