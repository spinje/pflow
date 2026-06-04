"""Tests for claude-code schema coercion and retry (Task #465)."""

import pytest

from pflow.nodes.claude.claude_code import ClaudeCodeNode


class TestSchemaCoercion:
    """Test Phase 1: Scalar coercion (Shape B)."""

    def test_coerce_boolean_string_to_bool(self):
        """Test coercion of "false"/"true" strings to boolean."""
        schema = {
            "type": "object",
            "properties": {
                "continue": {"type": "boolean"},
                "enabled": {"type": "boolean"},
            },
            "required": ["continue"],
        }

        # Test "false" → False
        structured_output = {"continue": "false", "enabled": "true"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["continue"] is False
        assert coerced["enabled"] is True
        assert conforming is True
        assert set(coerced_fields) == {"continue", "enabled"}

        # Test case-insensitive and whitespace handling
        structured_output = {"continue": "  False  ", "enabled": " TRUE"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["continue"] is False
        assert coerced["enabled"] is True
        assert conforming is True

    def test_coerce_integer_string_to_int(self):
        """Test coercion of numeric strings to integers."""
        schema = {
            "type": "object",
            "properties": {
                "commits_made": {"type": "integer"},
                "files_changed": {"type": "integer"},
            },
            "required": ["commits_made"],
        }

        # Test string integers
        structured_output = {"commits_made": "3", "files_changed": "5"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["commits_made"] == 3
        assert coerced["files_changed"] == 5
        assert conforming is True
        assert set(coerced_fields) == {"commits_made", "files_changed"}

        # Test "3.0" → 3
        structured_output = {"commits_made": "3.0"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["commits_made"] == 3
        assert conforming is True

    def test_coerce_number_string_to_float(self):
        """Test coercion of numeric strings to floats."""
        schema = {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "score": {"type": "number"},
            },
        }

        structured_output = {"confidence": "0.95", "score": "42"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["confidence"] == 0.95
        assert coerced["score"] == 42.0
        assert conforming is True

    def test_coerce_scalar_to_string(self):
        """Test coercion of non-string scalars to string."""
        schema = {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "status": {"type": "string"},
            },
        }

        structured_output = {"message": 42, "status": True}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["message"] == "42"
        assert coerced["status"] == "True"
        assert conforming is True

    def test_correct_typed_dict_unchanged(self):
        """Test that correctly-typed dict is unchanged (no coercion)."""
        schema = {
            "type": "object",
            "properties": {
                "continue": {"type": "boolean"},
                "count": {"type": "integer"},
                "name": {"type": "string"},
            },
        }

        structured_output = {"continue": True, "count": 5, "name": "test"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced == structured_output
        assert conforming is True
        assert coerced_fields == []  # No fields were coerced

    def test_uncoercible_boolean_non_conforming(self):
        """Test that uncoercible values (e.g., 'maybe' for boolean) → non-conforming."""
        schema = {
            "type": "object",
            "properties": {
                "continue": {"type": "boolean"},
            },
        }

        structured_output = {"continue": "maybe"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert conforming is False
        assert coerced["continue"] == "maybe"  # Unchanged

    def test_nested_fields_not_coerced(self):
        """Test that nested object/array fields are NOT coerced (v1 scope limit)."""
        schema = {
            "type": "object",
            "properties": {
                "top_level": {"type": "boolean"},
                "nested": {
                    "type": "object",
                    "properties": {
                        "inner": {"type": "boolean"},
                    },
                },
            },
        }

        structured_output = {
            "top_level": "true",
            "nested": {"inner": "false"},  # Nested, should NOT be coerced
        }
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["top_level"] is True  # Top-level coerced
        assert coerced["nested"]["inner"] == "false"  # Nested NOT coerced
        assert "top_level" in coerced_fields
        assert "nested" not in coerced_fields

    def test_extra_fields_ignored(self):
        """Test that extra fields (not in schema) are ignored."""
        schema = {
            "type": "object",
            "properties": {
                "required_field": {"type": "boolean"},
            },
        }

        structured_output = {
            "required_field": "true",
            "extra_field": "value",
        }
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["required_field"] is True
        assert coerced["extra_field"] == "value"  # Preserved
        assert conforming is True

    def test_missing_required_field_non_conforming(self):
        """Test that missing required fields → non-conforming."""
        schema = {
            "type": "object",
            "properties": {
                "required_field": {"type": "boolean"},
            },
            "required": ["required_field"],
        }

        structured_output = {"other_field": "value"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert conforming is False

    def test_object_schema_without_properties_conforms(self):
        """A generic object schema (no 'properties') is unconstrained → conforming as-is.

        Regression (#465 review): this used to return conforming=False, which under the
        default schema_retries triggered a pointless retry and then dropped valid output to
        raw text. (The node-level gate that coercion only runs when an output_schema is set
        is covered by test_schema_retries_no_op_without_output_schema in test_claude_code.py.)
        """
        schema = {"type": "object"}  # no 'properties' key
        output = {"anything": 1, "nested": {"x": 2}}
        coerced, conforming, fields = ClaudeCodeNode._coerce_structured_output(output, schema)
        assert conforming is True
        assert coerced == output
        assert fields == []

    def test_enum_violation_non_conforming(self):
        """A value of the right TYPE but outside the enum is non-conforming (triggers retry)."""
        schema = {
            "type": "object",
            "properties": {"risk_level": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": ["risk_level"],
        }
        _, conforming, _ = ClaudeCodeNode._coerce_structured_output({"risk_level": "unknown"}, schema)
        assert conforming is False

    def test_enum_valid_conforming(self):
        """A value within the enum conforms."""
        schema = {
            "type": "object",
            "properties": {"risk_level": {"type": "string", "enum": ["low", "medium", "high"]}},
        }
        _, conforming, _ = ClaudeCodeNode._coerce_structured_output({"risk_level": "low"}, schema)
        assert conforming is True

    def test_const_violation_non_conforming(self):
        """A field constrained by const must equal it, else non-conforming."""
        schema = {"type": "object", "properties": {"kind": {"const": "report"}}}
        _, bad, _ = ClaudeCodeNode._coerce_structured_output({"kind": "other"}, schema)
        assert bad is False
        _, good, _ = ClaudeCodeNode._coerce_structured_output({"kind": "report"}, schema)
        assert good is True

    def test_enum_checked_after_coercion(self):
        """enum is validated against the POST-coercion value (e.g. integer enum given "2")."""
        schema = {
            "type": "object",
            "properties": {"level": {"type": "integer", "enum": [1, 2, 3]}},
        }
        coerced, conforming, fields = ClaudeCodeNode._coerce_structured_output({"level": "2"}, schema)
        assert coerced["level"] == 2
        assert conforming is True
        assert "level" in fields

    def test_type_array_with_null(self):
        """Test type: ["string", "null"] accepts None."""
        schema = {
            "type": "object",
            "properties": {
                "optional_field": {"type": ["string", "null"]},
            },
        }

        structured_output = {"optional_field": None}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["optional_field"] is None
        assert conforming is True
        assert coerced_fields == []

    def test_type_array_coerce_to_matching_type(self):
        """Test type: ["boolean", "integer"] accepts runtime value that matches after coercion."""
        schema = {
            "type": "object",
            "properties": {
                "flexible_field": {"type": ["boolean", "integer"]},
            },
        }

        # Runtime value is "42" → coerce to integer (matches "integer" in type list)
        structured_output = {"flexible_field": "42"}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        # Should coerce to integer since "42" matches integer type after coercion
        assert coerced["flexible_field"] == 42
        assert conforming is True
        assert "flexible_field" in coerced_fields

    def test_mutation_safety(self):
        """Test that coercion returns a new dict, doesn't mutate input."""
        schema = {
            "type": "object",
            "properties": {
                "field": {"type": "boolean"},
            },
        }

        original = {"field": "true"}
        original_copy = original.copy()

        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(original, schema)

        # Original should be unchanged
        assert original == original_copy
        assert original["field"] == "true"

        # Coerced should have boolean
        assert coerced["field"] is True
        assert coerced is not original  # New dict

    def test_coerce_python_float_to_int(self):
        """Regression test for float-to-int coercion bug.

        When the SDK returns a Python float (5.0) but schema expects integer,
        it should coerce. The original implementation only handled STRING "5.0"
        → int coercion, not actual float 5.0 → int.

        Bug found during verification adversarial testing on 2026-06-03.
        """
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }

        # Test Python float → int (the bug case)
        structured_output = {"count": 5.0}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["count"] == 5
        assert isinstance(coerced["count"], int)
        assert conforming is True
        assert "count" in coerced_fields

        # Test float with non-integer value (should NOT coerce)
        structured_output = {"count": 5.5}
        coerced, conforming, coerced_fields = ClaudeCodeNode._coerce_structured_output(structured_output, schema)

        assert coerced["count"] == 5.5  # Unchanged
        assert conforming is False  # Non-conforming


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
