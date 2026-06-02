"""Tests for automatic JSON parsing in template resolution.

Tests the feature that automatically parses JSON strings when passed to
dict/list parameters, enabling shell+jq -> MCP workflows without LLM steps.

Migrated from TemplateAwareNodeWrapper tests to use the standalone functions
in pflow.runtime.engine.template_resolution.
"""

import json

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
            {"key": "object_param", "type": "object", "description": "An object parameter"},
            {"key": "array_param", "type": "array", "description": "An array parameter"},
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


class TestSimpleTemplateJsonParsing:
    """Test auto-parsing for simple templates."""

    def test_parse_json_object_to_dict(self, interface_metadata):
        """Simple template with valid JSON object -> dict."""
        result = _resolve(
            {"dict_param": "${json_data}"},
            {"json_data": '{"key": "value", "number": 42}'},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value", "number": 42}

    def test_parse_json_array_to_list(self, interface_metadata):
        """Simple template with valid JSON array -> list."""
        result = _resolve(
            {"list_param": "${json_array}"},
            {"json_array": '[["2025-10-23", "14:30:45", "test", "data"]]'},
            interface_metadata,
        )

        assert isinstance(result["list_param"], list)
        assert result["list_param"] == [["2025-10-23", "14:30:45", "test", "data"]]

    def test_parse_with_trailing_newline(self, interface_metadata):
        """JSON with trailing newline (shell output) -> parsed."""
        result = _resolve(
            {"list_param": "${shell_output}"},
            {"shell_output": '[["data1", "data2"]]\n'},
            interface_metadata,
        )

        assert isinstance(result["list_param"], list)
        assert result["list_param"] == [["data1", "data2"]]

    def test_parse_nested_json_structures(self, interface_metadata):
        """Nested JSON structures -> parsed correctly."""
        result = _resolve(
            {"dict_param": "${nested_data}"},
            {"nested_data": '{"user": {"name": "Alice", "settings": {"theme": "dark"}}, "items": [1, 2, 3]}'},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"]["user"]["settings"]["theme"] == "dark"
        assert result["dict_param"]["items"] == [1, 2, 3]

    def test_parse_empty_array(self, interface_metadata):
        """Empty array -> parsed."""
        result = _resolve(
            {"list_param": "${empty_array}"},
            {"empty_array": "[]"},
            interface_metadata,
        )

        assert isinstance(result["list_param"], list)
        assert result["list_param"] == []

    def test_parse_empty_object(self, interface_metadata):
        """Empty object -> parsed."""
        result = _resolve(
            {"dict_param": "${empty_obj}"},
            {"empty_obj": "{}"},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {}

    def test_object_alias_works(self, interface_metadata):
        """'object' type alias works same as 'dict'."""
        result = _resolve(
            {"object_param": "${json_obj}"},
            {"json_obj": '{"test": "value"}'},
            interface_metadata,
        )

        assert isinstance(result["object_param"], dict)
        assert result["object_param"] == {"test": "value"}

    def test_array_alias_works(self, interface_metadata):
        """'array' type alias works same as 'list'."""
        result = _resolve(
            {"array_param": "${json_arr}"},
            {"json_arr": '["item1", "item2"]'},
            interface_metadata,
        )

        assert isinstance(result["array_param"], list)
        assert result["array_param"] == ["item1", "item2"]


class TestParameterizedGenericJsonParsing:
    """Auto-parse must fire for parameterized-generic params, not just bare ones.

    Regression for issue #460 / PR #461: the validator accepts a value wired into a
    ``list[str]`` / ``dict[str, int]`` param (it strips the generic), but the runtime
    auto-parse gate only knew bare names — so a JSON string fed into ``images:
    list[str]`` validated clean then stayed an un-parsed string at runtime. The fix
    normalizes declared types to their outer base in ``build_type_cache``.
    """

    def test_json_array_string_parses_for_list_str_param(self):
        """JSON-array string -> list for a ``list[str]`` param (the issue #460 case)."""
        interface = {"params": [{"key": "images", "type": "list[str]"}]}
        result = _resolve({"images": "${x}"}, {"x": '["a.png", "b.png"]'}, interface)

        assert isinstance(result["images"], list)
        assert result["images"] == ["a.png", "b.png"]

    def test_json_object_string_parses_for_dict_generic_param(self):
        """JSON-object string -> dict for a ``dict[str, int]`` param."""
        interface = {"params": [{"key": "cfg", "type": "dict[str, int]"}]}
        result = _resolve({"cfg": "${x}"}, {"x": '{"a": 1, "b": 2}'}, interface)

        assert isinstance(result["cfg"], dict)
        assert result["cfg"] == {"a": 1, "b": 2}

    def test_union_with_generic_is_not_collapsed(self):
        """A union containing a generic stays a union (no auto-parse) — not collapsed to list."""
        interface = {"params": [{"key": "p", "type": "list[str]|str"}]}
        # The runtime never auto-parses unions; the value must pass through unchanged.
        result = _resolve({"p": "${x}"}, {"x": '["a", "b"]'}, interface)

        assert result["p"] == '["a", "b"]'


class TestComplexTemplateNoParsing:
    """Test that complex templates are NOT auto-parsed (escape hatch)."""

    def test_complex_template_stays_string(self, interface_metadata):
        """Complex template (with text) -> NOT parsed (stays string)."""
        result = _resolve(
            {"dict_param": " ${json_data}"},
            {"json_data": '{"key": "value"}'},
            interface_metadata,
        )

        # Should NOT be parsed (complex template)
        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == ' {"key": "value"}'

    def test_template_with_suffix_stays_string(self, interface_metadata):
        """Template with suffix text -> NOT parsed."""
        result = _resolve(
            {"dict_param": "${json_data} "},
            {"json_data": '{"key": "value"}'},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == '{"key": "value"} '

    def test_template_with_quotes_stays_string(self, interface_metadata):
        """Template wrapped in quotes -> NOT parsed."""
        result = _resolve(
            {"dict_param": "'${json_data}'"},
            {"json_data": '{"key": "value"}'},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == '\'{"key": "value"}\''


class TestInvalidJsonGracefulFallback:
    """Test error handling for invalid JSON."""

    def test_invalid_json_raises_clear_error(self, interface_metadata):
        """Invalid JSON -> raises clear error (not graceful fallback)."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"dict_param": "${bad_json}"},
                {"bad_json": "{not valid json}"},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "malformed JSON" in error_msg
        assert "{not valid json}" in error_msg

    def test_wrong_json_type_raises_error(self, interface_metadata):
        """Wrong JSON type (array when expecting object) -> raises error."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"dict_param": "${wrong_type}"},
                {"wrong_type": '["array", "not", "object"]'},
                interface_metadata,
            )

        error_msg = str(exc_info.value)
        assert "malformed JSON" in error_msg
        assert '["array"' in error_msg

    def test_json_primitive_string_not_parsed(self, interface_metadata):
        """JSON primitive (string) -> not parsed (wrong type)."""
        result = _resolve(
            {"dict_param": "${json_string}"},
            {"json_string": '"just a string"'},
            interface_metadata,
        )

        # Parsed but wrong type, should fallback to original string
        assert isinstance(result["dict_param"], str)

    def test_json_number_not_parsed(self, interface_metadata):
        """JSON primitive (number) -> not parsed (wrong type)."""
        result = _resolve(
            {"dict_param": "${json_number}"},
            {"json_number": "42"},
            interface_metadata,
        )

        # Number doesn't start with { or [, won't even attempt parsing
        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == "42"


class TestNoTypeInfoNoParsing:
    """Test that no parsing happens without type info."""

    def test_no_parsing_without_metadata(self):
        """Parameter without type info -> no parsing attempted."""
        result = _resolve(
            {"some_param": "${json_data}"},
            {"json_data": '{"key": "value"}'},
            interface_metadata=None,
        )

        # No type info, so no parsing attempted
        assert isinstance(result["some_param"], str)
        assert result["some_param"] == '{"key": "value"}'


class TestStringParametersNotParsed:
    """Test that string parameters are never auto-parsed."""

    def test_json_string_to_str_param_not_parsed(self, interface_metadata):
        """JSON string to str parameter -> NOT parsed."""
        result = _resolve(
            {"str_param": "${json_data}"},
            {"json_data": '{"key": "value"}'},
            interface_metadata,
        )

        # str parameter should NOT be parsed (stays as string)
        assert isinstance(result["str_param"], str)
        assert result["str_param"] == '{"key": "value"}'


class TestSecurityLimits:
    """Test security limits for JSON parsing."""

    def test_oversized_json_not_parsed(self, interface_metadata):
        """JSON string exceeding 10MB -> NOT parsed (security limit)."""
        # Create a JSON string larger than 10MB
        large_item = "x" * 1024  # 1KB item
        large_json = "[" + ",".join([f'"{large_item}"'] * 11_000) + "]"  # ~11MB
        assert len(large_json) > 10 * 1024 * 1024  # Verify it's > 10MB

        # Use permissive mode to avoid strict-mode ValueError for type mismatch
        merged, _resolutions, template_errors = _resolve_full(
            {"list_param": "${large_json}"},
            {"large_json": large_json},
            interface_metadata,
            resolution_mode="permissive",
        )

        # Should stay as string due to size limit
        assert isinstance(merged["list_param"], str)
        assert len(merged["list_param"]) > 10 * 1024 * 1024

        # Should have a template error about the type mismatch
        assert len(template_errors) > 0

    def test_normal_sized_json_parsed(self, interface_metadata):
        """JSON string under 10MB -> parsed normally."""
        large_array = ["item"] * 100_000
        json_data = json.dumps(large_array)
        assert len(json_data) < 10 * 1024 * 1024  # Verify it's < 10MB

        result = _resolve(
            {"list_param": "${json_data}"},
            {"json_data": json_data},
            interface_metadata,
        )

        # Should be parsed successfully
        assert isinstance(result["list_param"], list)
        assert len(result["list_param"]) == 100_000


class TestReverseCoercionDictToString:
    """Test dict/list -> JSON string coercion when expected type is str.

    This is the fix for MCP tools that declare `param: str` but expect JSON content.
    """

    def test_dict_becomes_json_string_for_str_param(self):
        """Dict value becomes JSON string when param type is str."""
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str", "description": "JSON string"},
            ]
        }

        result = _resolve(
            {"path_params": "${data}"},
            {"data": {"channel_id": "123"}},
            interface_metadata,
        )

        assert isinstance(result["path_params"], str)
        assert json.loads(result["path_params"]) == {"channel_id": "123"}

    def test_list_becomes_json_string_for_str_param(self):
        """List value becomes JSON string when param type is str."""
        interface_metadata = {
            "params": [
                {"key": "items", "type": "str", "description": "JSON array string"},
            ]
        }

        result = _resolve(
            {"items": "${data}"},
            {"data": [1, 2, 3]},
            interface_metadata,
        )

        assert isinstance(result["items"], str)
        assert json.loads(result["items"]) == [1, 2, 3]

    def test_dict_preserved_when_type_is_dict(self, interface_metadata):
        """Dict stays dict when param type is dict (no coercion)."""
        result = _resolve(
            {"dict_param": "${data}"},
            {"data": {"key": "value"}},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_mcp_workflow_pattern(self):
        """End-to-end test: workflow JSON object -> MCP str param -> JSON string.

        This is the exact bug scenario: workflow has JSON object for param,
        but MCP tool expects JSON string.
        """
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }

        result = _resolve(
            {
                "path_params": {"channel_id": "${channel_id}"},
                "body_schema": {"content": "${message}"},
            },
            {"channel_id": "123456789", "message": "Hello from pflow!"},
            interface_metadata,
            node_id="mcp-discord-execute_action",
        )

        # Both should be JSON strings, not dicts
        assert isinstance(result["path_params"], str)
        assert isinstance(result["body_schema"], str)

        # Should be valid, parseable JSON
        parsed_path = json.loads(result["path_params"])
        parsed_body = json.loads(result["body_schema"])

        # Check the structure
        assert "channel_id" in parsed_path
        assert parsed_body == {"content": "Hello from pflow!"}

    def test_deeply_nested_inline_object_with_templates(self):
        """Deeply nested inline objects with templates should serialize correctly."""
        interface_metadata = {
            "params": [
                {"key": "data", "type": "str"},
            ]
        }

        result = _resolve(
            {"data": {"outer": {"middle": {"inner": "${value}"}}}},
            {"value": "deep"},
            interface_metadata,
        )

        assert isinstance(result["data"], str)
        parsed = json.loads(result["data"])
        assert parsed["outer"]["middle"]["inner"] == "deep"


class TestStaticParamCoercion:
    """Test dict/list -> JSON string coercion for STATIC params (no templates).

    This is the bug fix for SUPPLEMENTARY-FINDINGS.md: objects without templates
    were not being coerced because they bypassed the template resolution path.
    """

    def test_static_dict_coerced_to_json_string(self):
        """Static dict (no template) becomes JSON string when param type is str."""
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
            ]
        }

        result = _resolve(
            {"path_params": {"channel_id": "123"}},
            {},
            interface_metadata,
        )

        assert isinstance(result["path_params"], str)
        assert json.loads(result["path_params"]) == {"channel_id": "123"}

    def test_static_list_coerced_to_json_string(self):
        """Static list (no template) becomes JSON string when param type is str."""
        interface_metadata = {
            "params": [
                {"key": "items", "type": "str"},
            ]
        }

        result = _resolve(
            {"items": [1, 2, 3]},
            {},
            interface_metadata,
        )

        assert isinstance(result["items"], str)
        assert json.loads(result["items"]) == [1, 2, 3]

    def test_static_dict_preserved_when_type_is_dict(self, interface_metadata):
        """Static dict stays dict when param type is dict (no coercion)."""
        result = _resolve(
            {"dict_param": {"key": "value"}},
            {},
            interface_metadata,
        )

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_mixed_static_and_template_params(self):
        """Mixed static + template params both coerced correctly."""
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }

        result = _resolve(
            {
                "path_params": {"channel_id": "123"},  # Static - no template
                "body_schema": {"content": "${message}"},  # Has template
            },
            {"message": "Hello!"},
            interface_metadata,
        )

        # Both should be JSON strings
        assert isinstance(result["path_params"], str)
        assert isinstance(result["body_schema"], str)

        # Both should parse to correct values
        assert json.loads(result["path_params"]) == {"channel_id": "123"}
        assert json.loads(result["body_schema"]) == {"content": "Hello!"}

    def test_mcp_workflow_pattern_with_hardcoded_channel(self):
        """Real bug case: hardcoded channel_id with template message.

        This is the exact scenario from SUPPLEMENTARY-FINDINGS.md that was broken.
        """
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }

        result = _resolve(
            {
                "path_params": {"channel_id": "1458059302022549698"},  # Hardcoded!
                "body_schema": {"content": "${message}"},
            },
            {"message": "Test message"},
            interface_metadata,
            node_id="mcp-discord-execute_action",
        )

        # BOTH must be JSON strings for MCP to work
        assert isinstance(result["path_params"], str), "path_params should be JSON string"
        assert isinstance(result["body_schema"], str), "body_schema should be JSON string"

        # Verify valid JSON
        path_params = json.loads(result["path_params"])
        body_schema = json.loads(result["body_schema"])

        assert path_params == {"channel_id": "1458059302022549698"}
        assert body_schema == {"content": "Test message"}

    def test_fully_static_workflow_both_params(self):
        """All static params (no templates at all) should still coerce."""
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }

        result = _resolve(
            {
                "path_params": {"channel_id": "123"},
                "body_schema": {"content": "hardcoded message"},
            },
            {},
            interface_metadata,
        )

        # Both should be JSON strings
        assert isinstance(result["path_params"], str)
        assert isinstance(result["body_schema"], str)

        # Verify values
        assert json.loads(result["path_params"]) == {"channel_id": "123"}
        assert json.loads(result["body_schema"]) == {"content": "hardcoded message"}

    def test_json_loads_succeeds_with_coerced_static_dict(self):
        """CANARY TEST: json.loads() works with coerced static dict.

        Before: dict passed to json.loads() -> TypeError
        After:  dict coerced to JSON string -> json.loads() succeeds

        This simulates exactly what MCP nodes do and catches the bug from
        SUPPLEMENTARY-FINDINGS.md.
        """
        interface_metadata = {
            "params": [
                {"key": "json_data", "type": "str"},
            ]
        }

        result = _resolve(
            {"json_data": {"channel_id": "123", "content": "hello"}},
            {},
            interface_metadata,
            node_id="mcp-like-node",
        )

        # Verify the param is a string (not dict)
        assert isinstance(result["json_data"], str), "Node should receive string, not dict"

        # Verify json.loads() successfully parses it
        assert json.loads(result["json_data"]) == {"channel_id": "123", "content": "hello"}

    def test_static_dict_not_coerced_without_type_metadata(self):
        """Static dict stays dict when no type metadata available.

        Without type information, we cannot know if the param should be
        coerced to a string. Safe default is to pass through unchanged.
        """
        result = _resolve(
            {"unknown_param": {"key": "value"}},
            {},
            interface_metadata=None,
        )

        # Without type metadata, dict should NOT be coerced
        assert isinstance(result["unknown_param"], dict)
        assert result["unknown_param"] == {"key": "value"}

    def test_deeply_nested_static_object_serializes_correctly(self):
        """Deeply nested static objects serialize correctly to JSON string."""
        interface_metadata = {
            "params": [
                {"key": "complex_param", "type": "str"},
            ]
        }

        nested_value = {
            "level1": {
                "level2": {
                    "level3": {
                        "data": "value",
                        "numbers": [1, 2, 3],
                        "nested_array": [{"a": 1}, {"b": 2}],
                    }
                },
                "sibling": "value",
            },
            "top_array": [{"x": 1}, {"y": 2}],
        }

        result = _resolve(
            {"complex_param": nested_value},
            {},
            interface_metadata,
        )

        # Should be serialized to JSON string
        assert isinstance(result["complex_param"], str)

        # Should parse back to identical structure
        parsed = json.loads(result["complex_param"])
        assert parsed == nested_value
