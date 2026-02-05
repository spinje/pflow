"""Tests for workflow input type coercion in prepare_inputs().

This tests the integration of coerce_input_to_declared_type() into the
workflow validation pipeline, ensuring CLI-provided values are coerced
to match declared input types.

Related bug: Numeric string inputs (e.g., Discord snowflake IDs) were
silently coerced to int by CLI's infer_type() before the workflow's
declared type: string was consulted.
"""

from pflow.runtime.workflow_validator import prepare_inputs


class TestPrepareInputsTypeCoercion:
    """Test that prepare_inputs() coerces values to declared types."""

    def test_int_coerced_to_string_when_declared(self):
        """THE BUG FIX: Int value coerced to string when type: string declared."""
        workflow_ir = {
            "inputs": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel ID",
                    "required": True,
                }
            }
        }
        # Simulates CLI's infer_type() converting "1458..." to int
        provided_params = {"channel_id": 1458059302022549698}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Coerced value should be in defaults
        assert "channel_id" in defaults
        assert isinstance(defaults["channel_id"], str)
        assert defaults["channel_id"] == "1458059302022549698"

    def test_no_coercion_when_type_matches(self):
        """No coercion needed when value already matches declared type."""
        workflow_ir = {
            "inputs": {
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID",
                    "required": True,
                }
            }
        }
        provided_params = {"channel_id": "already-a-string"}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # No coercion needed, so not in defaults
        assert "channel_id" not in defaults

    def test_no_coercion_when_no_type_declared(self):
        """No coercion when input has no type declaration."""
        workflow_ir = {
            "inputs": {
                "value": {
                    "description": "Some value with no type",
                    "required": True,
                }
            }
        }
        provided_params = {"value": 123}  # Stays as int

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # No coercion, not in defaults
        assert "value" not in defaults

    def test_multiple_inputs_coerced_correctly(self):
        """Multiple inputs should each be coerced according to their types."""
        workflow_ir = {
            "inputs": {
                "channel_id": {"type": "string", "required": True},
                "count": {"type": "integer", "required": True},
                "enabled": {"type": "boolean", "required": True},
            }
        }
        provided_params = {
            "channel_id": 123456789,  # int → string
            "count": "50",  # string → int
            "enabled": "yes",  # string → bool
        }

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["channel_id"] == "123456789"
        assert defaults["count"] == 50
        assert defaults["enabled"] is True

    def test_coercion_with_optional_input(self):
        """Coercion should work for optional inputs too."""
        workflow_ir = {
            "inputs": {
                "limit": {
                    "type": "integer",
                    "description": "Optional limit",
                    "required": False,
                }
            }
        }
        provided_params = {"limit": "100"}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["limit"] == 100


class TestPrepareInputsCoercionEdgeCases:
    """Edge cases for input type coercion."""

    def test_large_int_to_string_preserves_precision(self):
        """Large integers should not lose precision when converted to string."""
        workflow_ir = {
            "inputs": {
                "snowflake": {
                    "type": "string",
                    "description": "Discord snowflake ID",
                    "required": True,
                }
            }
        }
        # This is a real Discord snowflake ID
        large_int = 1458059302022549698
        provided_params = {"snowflake": large_int}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Verify exact string representation (no precision loss)
        assert defaults["snowflake"] == "1458059302022549698"

    def test_float_to_string_preserves_value(self):
        """Float to string should preserve reasonable precision."""
        workflow_ir = {"inputs": {"value": {"type": "string", "required": True}}}
        provided_params = {"value": 3.14159265359}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Should convert cleanly
        assert "3.14159265359" in defaults["value"]

    def test_bool_to_string_gives_python_repr(self):
        """Bool to string gives Python representation (True/False)."""
        workflow_ir = {"inputs": {"flag": {"type": "string", "required": True}}}
        provided_params = {"flag": True}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["flag"] == "True"

    def test_invalid_coercion_returns_original(self):
        """Invalid coercion (e.g., 'hello' → int) returns original value."""
        workflow_ir = {
            "inputs": {
                "count": {
                    "type": "integer",
                    "description": "Count",
                    "required": True,
                }
            }
        }
        provided_params = {"count": "not-a-number"}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        # No error from prepare_inputs (coercion failure is graceful)
        # Value stays as-is - downstream validation will catch if needed
        assert errors == []
        # Original value not in defaults because coercion returned same value
        assert "count" not in defaults

    def test_type_aliases_work(self):
        """Type aliases like 'str', 'int' should work."""
        workflow_ir = {
            "inputs": {
                "id": {"type": "str", "required": True},  # alias for string
                "num": {"type": "int", "required": True},  # alias for integer
            }
        }
        provided_params = {"id": 123, "num": "456"}

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["id"] == "123"
        assert defaults["num"] == 456


class TestPrepareInputsIntegrationWithDefaults:
    """Test coercion interacts correctly with default values."""

    def test_coercion_and_defaults_both_in_result(self):
        """Coerced values and defaults should both be in defaults dict."""
        workflow_ir = {
            "inputs": {
                "channel_id": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False, "default": 10},
            }
        }
        provided_params = {"channel_id": 123456}  # Needs coercion

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Coerced value
        assert defaults["channel_id"] == "123456"
        # Default value
        assert defaults["limit"] == 10

    def test_provided_value_not_overridden_by_default(self):
        """Provided value (even after coercion) should not be overridden by default."""
        workflow_ir = {
            "inputs": {
                "limit": {"type": "integer", "required": False, "default": 10},
            }
        }
        provided_params = {"limit": "50"}  # User provided, needs coercion

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Coerced user value, not default
        assert defaults["limit"] == 50
