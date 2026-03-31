"""Tests for clear error messages when JSON parsing fails.

Tests the error handling when malformed JSON strings are passed to
dict/list parameters, ensuring users get actionable error messages.

Migrated from TemplateAwareNodeWrapper tests to use the standalone functions
in pflow.runtime.engine.template_resolution.
"""

import pytest

from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    resolve_templates,
    split_params,
)
from pflow.runtime.engine.types import TemplateConfig


@pytest.fixture
def interface_metadata():
    """Metadata with dict and list parameters."""
    return {
        "params": [
            {"key": "dict_param", "type": "dict", "description": "A dict parameter"},
            {"key": "list_param", "type": "list", "description": "A list parameter"},
            {"key": "str_param", "type": "str", "description": "A string parameter"},
        ]
    }


def _resolve(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
    node_id: str = "test",
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
    node_id: str = "test",
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


class TestMalformedJsonErrorMessages:
    """Test clear error messages for malformed JSON."""

    def test_invalid_json_to_dict_clear_error(self, interface_metadata):
        """Malformed JSON to dict -> clear error message."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"dict_param": "${bad_json}"},
                {"bad_json": "{not valid json}"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "malformed JSON string" in error_msg
        assert "dict_param" in error_msg
        assert "{not valid json}" in error_msg

    def test_invalid_json_to_list_clear_error(self, interface_metadata):
        """Malformed JSON to list -> clear error message."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"list_param": "${bad_json}"},
                {"bad_json": "[not valid json"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "malformed JSON string" in error_msg
        assert "list_param" in error_msg
        assert "[not valid json" in error_msg

    def test_single_quotes_detected(self, interface_metadata):
        """Single quotes in JSON -> error mentions it."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"dict_param": "${single_quotes}"},
                {"single_quotes": "{'key': 'value'}"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Single quotes detected" in error_msg
        assert "double quotes" in error_msg

    def test_mismatched_braces_detected(self, interface_metadata):
        """Mismatched braces -> error mentions it."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"dict_param": "${missing_brace}"},
                {"missing_brace": '{"key": "value"'},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Mismatched braces" in error_msg

    def test_mismatched_brackets_detected(self, interface_metadata):
        """Mismatched brackets -> error mentions it."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"list_param": "${missing_bracket}"},
                {"missing_bracket": '["item1", "item2"'},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Mismatched brackets" in error_msg

    def test_trailing_comma_detected(self, interface_metadata):
        """Trailing comma -> error mentions it."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"list_param": "${trailing_comma}"},
                {"trailing_comma": "[1, 2, 3,]"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Trailing comma" in error_msg

    def test_error_includes_suggestions(self, interface_metadata):
        """Error message includes actionable suggestions."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"dict_param": "${bad_json}"},
                {"bad_json": "{bad}"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "Common JSON formatting issues:" in error_msg
        assert "Fix: Ensure the source outputs valid JSON" in error_msg
        assert "Test with:" in error_msg


class TestValidJsonStillWorks:
    """Regression tests: valid JSON should still work."""

    def test_valid_json_dict_no_error(self, interface_metadata):
        """Valid JSON to dict -> no error (regression check)."""
        result = _resolve(
            {"dict_param": "${valid_json}"},
            {"valid_json": '{"key": "value"}'},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_valid_json_list_no_error(self, interface_metadata):
        """Valid JSON to list -> no error (regression check)."""
        result = _resolve(
            {"list_param": "${valid_json}"},
            {"valid_json": '["item1", "item2"]'},
            interface_metadata,
        )

        assert isinstance(result["list_param"], list)
        assert result["list_param"] == ["item1", "item2"]


class TestNonJsonStringsNotFlagged:
    """Non-JSON strings should not trigger JSON error messages."""

    def test_plain_text_to_dict_not_json_error(self, interface_metadata):
        """Plain text to dict -> doesn't mention JSON parsing."""
        result = _resolve(
            {"dict_param": "${plain_text}"},
            {"plain_text": "just plain text"},
            interface_metadata,
        )

        # Node receives string (Pydantic would catch it later if node validates)
        assert result["dict_param"] == "just plain text"

    def test_empty_string_to_dict_not_json_error(self, interface_metadata):
        """Empty string to dict -> doesn't trigger JSON error."""
        result = _resolve(
            {"dict_param": "${empty}"},
            {"empty": ""},
            interface_metadata,
        )

        assert result["dict_param"] == ""


class TestPermissiveModeStoresError:
    """Permissive mode should store error instead of raising."""

    def test_permissive_mode_stores_json_error(self, interface_metadata):
        """Permissive mode -> stores error in template_errors list."""
        _merged, _resolutions, template_errors = _resolve_full(
            {"dict_param": "${bad_json}"},
            {"bad_json": "{not valid}"},
            interface_metadata,
            resolution_mode="permissive",
        )

        # Should have template errors
        assert len(template_errors) > 0
        # At least one error should mention malformed JSON
        error_messages = [e["message"] for e in template_errors]
        assert any("malformed JSON" in msg for msg in error_messages)
