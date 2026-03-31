"""Tests for type validation in template resolution.

These tests verify that template resolution validates resolved types
against expected parameter types from node metadata.

Migrated from TemplateAwareNodeWrapper tests to use standalone functions
in pflow.runtime.engine.template_resolution.
"""

import json

import pytest

from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    resolve_templates,
    split_params,
    validate_resolved_type,
)
from pflow.runtime.engine.types import TemplateConfig


def _resolve(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
    node_id: str = "test-node",
) -> dict:
    """Helper: split params, build config, resolve templates, return merged_params."""
    expected_types = build_type_cache(interface_metadata)
    template_params, static_params = split_params(params, expected_types)
    config = TemplateConfig(
        template_params=template_params,
        static_params=static_params,
        expected_types=expected_types,
        resolution_mode=resolution_mode,
    )
    merged_params, _last_resolutions, _template_errors = resolve_templates(config, shared, node_id)
    return merged_params


def _resolve_full(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
    node_id: str = "test-node",
) -> tuple[dict, dict, list]:
    """Helper: like _resolve but returns all three outputs."""
    expected_types = build_type_cache(interface_metadata)
    template_params, static_params = split_params(params, expected_types)
    config = TemplateConfig(
        template_params=template_params,
        static_params=static_params,
        expected_types=expected_types,
        resolution_mode=resolution_mode,
    )
    return resolve_templates(config, shared, node_id)


class TestBasicTypeValidation:
    """Test basic type validation logic."""

    def test_string_param_receives_string_no_error(self):
        """String parameter receiving string value should not raise error."""
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}

        result = _resolve(
            {"prompt": "${message}"},
            {"message": "Hello, World!"},
            interface_metadata,
        )

        assert result["prompt"] == "Hello, World!"

    def test_string_param_receives_dict_gets_coerced(self):
        """String parameter receiving dict should be coerced to JSON string."""
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}

        result = _resolve(
            {"prompt": "${data}"},
            {"data": {"status": "ok", "result": "test"}},
            interface_metadata,
        )

        # Verify the dict was serialized to JSON string
        assert isinstance(result["prompt"], str)
        assert json.loads(result["prompt"]) == {"status": "ok", "result": "test"}

    def test_string_param_receives_list_gets_coerced(self):
        """String parameter receiving list should be coerced to JSON string."""
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}

        result = _resolve(
            {"prompt": "${items}"},
            {"items": ["item1", "item2", "item3"]},
            interface_metadata,
        )

        # Verify the list was serialized to JSON string
        assert isinstance(result["prompt"], str)
        assert json.loads(result["prompt"]) == ["item1", "item2", "item3"]

    def test_any_param_receives_dict_no_error(self):
        """'any' type parameter should accept dict without error."""
        interface_metadata = {"inputs": [{"key": "data", "type": "any"}], "params": []}

        result = _resolve(
            {"data": "${response}"},
            {"response": {"status": "ok"}},
            interface_metadata,
        )

        assert result["data"] == {"status": "ok"}

    def test_dict_param_receives_dict_no_error(self):
        """'dict' type parameter should accept dict without error."""
        interface_metadata = {"inputs": [{"key": "config", "type": "dict"}], "params": []}

        result = _resolve(
            {"config": "${settings}"},
            {"settings": {"timeout": 30}},
            interface_metadata,
        )

        assert result["config"] == {"timeout": 30}

    def test_list_param_receives_list_no_error(self):
        """'list' type parameter should accept list without error."""
        interface_metadata = {"inputs": [{"key": "items", "type": "list"}], "params": []}

        result = _resolve(
            {"items": "${data}"},
            {"data": [1, 2, 3]},
            interface_metadata,
        )

        assert result["items"] == [1, 2, 3]


class TestComplexTemplates:
    """Test that complex templates skip validation (already stringified)."""

    def test_complex_template_with_dict_no_validation(self):
        """Complex template like 'text ${var}' is already string, no validation needed."""
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}

        result = _resolve(
            {"prompt": "Status: ${response}"},
            {"response": {"status": "ok"}},
            interface_metadata,
        )

        # Complex template should serialize dict to JSON
        assert "status" in result["prompt"]


class TestPermissiveMode:
    """Test permissive mode behavior."""

    def test_permissive_mode_coerces_dict_to_str(self):
        """Permissive mode should coerce dict to str without storing warning."""
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}

        merged, _resolutions, template_errors = _resolve_full(
            {"prompt": "${data}"},
            {"data": {"status": "ok"}},
            interface_metadata,
            resolution_mode="permissive",
        )

        # No template errors stored (coercion is silent)
        assert len(template_errors) == 0

        # Verify coercion happened
        assert isinstance(merged["prompt"], str)
        assert json.loads(merged["prompt"]) == {"status": "ok"}

    def test_permissive_mode_coerces_list_to_str(self):
        """Permissive mode should coerce list to str without storing warning."""
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}

        merged, _resolutions, template_errors = _resolve_full(
            {"text": "${response}"},
            {"response": ["a", "b", "c"]},
            interface_metadata,
            resolution_mode="permissive",
        )

        # Should execute successfully with coerced value
        assert len(template_errors) == 0
        assert isinstance(merged["text"], str)
        assert json.loads(merged["text"]) == ["a", "b", "c"]


class TestErrorMessages:
    """Test error message formatting for type mismatches that still raise errors.

    Note: dict/list -> str is now auto-coerced (not an error).
    These tests verify error messages for other type mismatches.
    """

    def test_error_for_malformed_json_when_dict_expected(self):
        """Malformed JSON -> dict should raise clear error."""
        interface_metadata = {"inputs": [{"key": "config", "type": "dict"}], "params": []}

        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"config": "${data}"},
                {"data": "{invalid json}"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Parameter 'config'" in error_msg
        assert "malformed JSON" in error_msg

    def test_error_for_malformed_json_when_list_expected(self):
        """Malformed JSON -> list should raise clear error."""
        interface_metadata = {"inputs": [{"key": "items", "type": "list"}], "params": []}

        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"items": "${data}"},
                {"data": "[invalid json]"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Parameter 'items'" in error_msg
        assert "malformed JSON" in error_msg

    def test_dict_to_str_no_longer_errors(self):
        """Verify that dict -> str is now coerced, not an error."""
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}

        result = _resolve(
            {"prompt": "${data}"},
            {"data": {"key": "value"}},
            interface_metadata,
        )

        assert isinstance(result["prompt"], str)
        assert json.loads(result["prompt"]) == {"key": "value"}

    def test_list_to_str_no_longer_errors(self):
        """Verify that list -> str is now coerced, not an error."""
        interface_metadata = {"inputs": [{"key": "summary", "type": "str"}], "params": []}

        result = _resolve(
            {"summary": "${items}"},
            {"items": ["a", "b", "c"]},
            interface_metadata,
        )

        assert isinstance(result["summary"], str)
        assert json.loads(result["summary"]) == ["a", "b", "c"]


class TestEdgeCases:
    """Test edge cases and graceful degradation."""

    def test_no_metadata_skips_validation(self):
        """When no metadata available, validation should be skipped."""
        result = _resolve(
            {"prompt": "${data}"},
            {"data": {"key": "value"}},
            interface_metadata=None,
        )

        # No metadata means no validation -- dict passes through
        assert result["prompt"] == {"key": "value"}

    def test_incomplete_metadata_skips_validation(self):
        """When metadata missing type info, validation should be skipped."""
        interface_metadata = {"inputs": [{"key": "prompt"}], "params": []}

        result = _resolve(
            {"prompt": "${data}"},
            {"data": {"key": "value"}},
            interface_metadata,
        )

        # Missing type info means skip validation -- dict passes through
        assert result["prompt"] == {"key": "value"}

    def test_empty_dict_coerced_to_empty_json_object(self):
        """Empty dict should be coerced to '{}'."""
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}

        result = _resolve(
            {"text": "${data}"},
            {"data": {}},
            interface_metadata,
        )

        assert result["text"] == "{}"

    def test_empty_list_coerced_to_empty_json_array(self):
        """Empty list should be coerced to '[]'."""
        interface_metadata = {"inputs": [{"key": "message", "type": "str"}], "params": []}

        result = _resolve(
            {"message": "${items}"},
            {"items": []},
            interface_metadata,
        )

        assert result["message"] == "[]"


class TestPerformance:
    """Test performance characteristics."""

    def test_type_cache_built_from_metadata(self):
        """build_type_cache should extract all types from metadata."""
        interface_metadata = {
            "inputs": [
                {"key": "prompt", "type": "str"},
                {"key": "system", "type": "str"},
                {"key": "images", "type": "list[str]"},
            ],
            "params": [{"key": "model", "type": "str"}, {"key": "temperature", "type": "float"}],
        }

        expected_types = build_type_cache(interface_metadata)

        assert len(expected_types) == 5
        assert expected_types["prompt"] == "str"
        assert expected_types["model"] == "str"
        assert expected_types["images"] == "list[str]"

    def test_type_cache_reusable(self):
        """build_type_cache can be called once and reused across multiple resolutions."""
        interface_metadata = {
            "inputs": [{"key": "prompt", "type": "str"}],
            "params": [],
        }

        expected_types = build_type_cache(interface_metadata)

        # Use same cache for multiple resolutions
        tp1, sp1 = split_params({"prompt": "${msg}"}, expected_types)
        config1 = TemplateConfig(
            template_params=tp1,
            static_params=sp1,
            expected_types=expected_types,
            resolution_mode="strict",
        )
        merged1, _, _ = resolve_templates(config1, {"msg": "Hello"}, "test")

        tp2, sp2 = split_params({"prompt": "${msg2}"}, expected_types)
        config2 = TemplateConfig(
            template_params=tp2,
            static_params=sp2,
            expected_types=expected_types,
            resolution_mode="strict",
        )
        merged2, _, _ = resolve_templates(config2, {"msg2": "World"}, "test")

        assert merged1["prompt"] == "Hello"
        assert merged2["prompt"] == "World"


class TestValidateResolvedType:
    """Test the validate_resolved_type standalone function."""

    def test_returns_none_for_matching_types(self):
        """No error when resolved type matches expected type."""
        expected_types = {"config": "dict"}
        result = validate_resolved_type("config", {"key": "value"}, "${data}", expected_types, "strict")
        assert result is None

    def test_returns_error_for_dict_when_str_expected(self):
        """Returns error message when dict given but str expected."""
        expected_types = {"prompt": "str"}
        result = validate_resolved_type("prompt", {"key": "value"}, "${data}", expected_types, "strict")
        assert result is not None
        assert "prompt" in result
        assert "str" in result

    def test_returns_none_for_any_type(self):
        """'any' type accepts everything."""
        expected_types = {"data": "any"}
        result = validate_resolved_type("data", {"key": "value"}, "${data}", expected_types, "strict")
        assert result is None

    def test_returns_none_for_unknown_param(self):
        """Unknown param (not in expected_types) skips validation."""
        expected_types = {"known": "str"}
        result = validate_resolved_type("unknown", {"key": "value"}, "${data}", expected_types, "strict")
        assert result is None
