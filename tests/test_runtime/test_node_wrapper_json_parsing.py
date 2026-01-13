"""Tests for automatic JSON parsing in node wrapper.

Tests the feature that automatically parses JSON strings when passed to
dict/list parameters, enabling shell+jq → MCP workflows without LLM steps.
"""

import json

import pytest

from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper
from pocketflow import Node


class SimpleNode(Node):
    """Test node with dict and list parameters."""

    def __init__(self):
        super().__init__()

    def prep(self, shared):
        return {}

    def exec(self, prep_res):
        return self.params

    def post(self, shared, prep_res, exec_res):
        shared["result"] = exec_res
        return "default"


class JsonConsumingNode(Node):
    """Test node that calls json.loads() on a str-typed parameter.

    This simulates MCP nodes that expect JSON string parameters and parse them.
    If a dict is passed instead of a string, json.loads() will fail with:
    TypeError: the JSON object must be str, bytes or bytearray, not dict

    This is the EXACT error from the bug report in SUPPLEMENTARY-FINDINGS.md.
    """

    def __init__(self):
        super().__init__()

    def prep(self, shared):
        return {}

    def exec(self, prep_res):
        # Simulate what MCP nodes do: parse JSON string parameters
        json_param = self.params.get("json_data")
        if json_param is not None:
            # This will FAIL if json_param is a dict instead of a string
            parsed = json.loads(json_param)
            return {"parsed": parsed, "original_type": type(json_param).__name__}
        return {"parsed": None, "original_type": None}

    def post(self, shared, prep_res, exec_res):
        shared["result"] = exec_res
        return "default"


@pytest.fixture
def simple_node():
    """Create a simple test node."""
    return SimpleNode()


@pytest.fixture
def json_consuming_node():
    """Create a node that calls json.loads() on its parameter."""
    return JsonConsumingNode()


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


class TestSimpleTemplateJsonParsing:
    """Test auto-parsing for simple templates."""

    def test_parse_json_object_to_dict(self, simple_node, interface_metadata):
        """Simple template with valid JSON object → dict."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Set params with JSON string template
        wrapper.set_params({"dict_param": "${json_data}"})

        # Simulate execution with JSON string in context
        shared = {"json_data": '{"key": "value", "number": 42}'}
        wrapper._run(shared)

        # Check result from shared store (set by SimpleNode.post)
        result = shared["result"]
        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value", "number": 42}

    def test_parse_json_array_to_list(self, simple_node, interface_metadata):
        """Simple template with valid JSON array → list."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${json_array}"})
        shared = {"json_array": '[["2025-10-23", "14:30:45", "test", "data"]]'}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["list_param"], list)
        assert result["list_param"] == [["2025-10-23", "14:30:45", "test", "data"]]

    def test_parse_with_trailing_newline(self, simple_node, interface_metadata):
        """JSON with trailing newline (shell output) → parsed."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${shell_output}"})
        # Shell commands typically add trailing newline
        shared = {"shell_output": '[["data1", "data2"]]\n'}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["list_param"], list)
        assert result["list_param"] == [["data1", "data2"]]

    def test_parse_nested_json_structures(self, simple_node, interface_metadata):
        """Nested JSON structures → parsed correctly."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${nested_data}"})
        shared = {"nested_data": '{"user": {"name": "Alice", "settings": {"theme": "dark"}}, "items": [1, 2, 3]}'}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"]["user"]["settings"]["theme"] == "dark"
        assert result["dict_param"]["items"] == [1, 2, 3]

    def test_parse_empty_array(self, simple_node, interface_metadata):
        """Empty array → parsed."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${empty_array}"})
        shared = {"empty_array": "[]"}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["list_param"], list)
        assert result["list_param"] == []

    def test_parse_empty_object(self, simple_node, interface_metadata):
        """Empty object → parsed."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${empty_obj}"})
        shared = {"empty_obj": "{}"}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {}

    def test_object_alias_works(self, simple_node, interface_metadata):
        """'object' type alias works same as 'dict'."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"object_param": "${json_obj}"})
        shared = {"json_obj": '{"test": "value"}'}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["object_param"], dict)
        assert result["object_param"] == {"test": "value"}

    def test_array_alias_works(self, simple_node, interface_metadata):
        """'array' type alias works same as 'list'."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"array_param": "${json_arr}"})
        shared = {"json_arr": '["item1", "item2"]'}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["array_param"], list)
        assert result["array_param"] == ["item1", "item2"]


class TestComplexTemplateNoParsing:
    """Test that complex templates are NOT auto-parsed (escape hatch)."""

    def test_complex_template_stays_string(self, simple_node, interface_metadata):
        """Complex template (with text) → NOT parsed (stays string)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Complex template (has leading space)
        wrapper.set_params({"dict_param": " ${json_data}"})
        shared = {"json_data": '{"key": "value"}'}
        wrapper._run(shared)
        result = shared["result"]

        # Should NOT be parsed (complex template)
        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == ' {"key": "value"}'

    def test_template_with_suffix_stays_string(self, simple_node, interface_metadata):
        """Template with suffix text → NOT parsed."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${json_data} "})
        shared = {"json_data": '{"key": "value"}'}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == '{"key": "value"} '

    def test_template_with_quotes_stays_string(self, simple_node, interface_metadata):
        """Template wrapped in quotes → NOT parsed."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "'${json_data}'"})
        shared = {"json_data": '{"key": "value"}'}
        wrapper._run(shared)
        result = shared["result"]

        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == '\'{"key": "value"}\''


class TestInvalidJsonGracefulFallback:
    """Test error handling for invalid JSON."""

    def test_invalid_json_raises_clear_error(self, simple_node, interface_metadata):
        """Invalid JSON → raises clear error (not graceful fallback)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${bad_json}"})
        shared = {"bad_json": "{not valid json}"}

        # NEW BEHAVIOR: Raises clear error instead of passing garbage to node
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "malformed JSON" in error_msg  # Clear error message
        assert "{not valid json}" in error_msg  # Shows the malformed value

    def test_wrong_json_type_raises_error(self, simple_node, interface_metadata):
        """Wrong JSON type (array when expecting object) → raises error."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${wrong_type}"})
        shared = {"wrong_type": '["array", "not", "object"]'}

        # NEW BEHAVIOR: Valid JSON but wrong type raises error
        # (array parsed but dict expected, so stays as string, then detected as malformed)
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "malformed JSON" in error_msg  # Detected as JSON-like but wrong
        assert '["array"' in error_msg  # Shows the value

    def test_json_primitive_string_not_parsed(self, simple_node, interface_metadata):
        """JSON primitive (string) → not parsed (wrong type)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${json_string}"})
        shared = {"json_string": '"just a string"'}
        wrapper._run(shared)
        result = shared["result"]

        # Parsed but wrong type, should fallback to original string
        assert isinstance(result["dict_param"], str)

    def test_json_number_not_parsed(self, simple_node, interface_metadata):
        """JSON primitive (number) → not parsed (wrong type)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${json_number}"})
        shared = {"json_number": "42"}
        wrapper._run(shared)
        result = shared["result"]

        # Number doesn't start with { or [, won't even attempt parsing
        assert isinstance(result["dict_param"], str)
        assert result["dict_param"] == "42"


class TestNoTypeInfoNoParsing:
    """Test that no parsing happens without type info."""

    def test_no_parsing_without_metadata(self, simple_node):
        """Parameter without type info → no parsing attempted."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=None,  # No metadata!
        )

        wrapper.set_params({"some_param": "${json_data}"})
        shared = {"json_data": '{"key": "value"}'}
        wrapper._run(shared)
        result = shared["result"]

        # No type info, so no parsing attempted
        assert isinstance(result["some_param"], str)
        assert result["some_param"] == '{"key": "value"}'


class TestStringParametersNotParsed:
    """Test that string parameters are never auto-parsed."""

    def test_json_string_to_str_param_not_parsed(self, simple_node, interface_metadata):
        """JSON string to str parameter → NOT parsed."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"str_param": "${json_data}"})
        shared = {"json_data": '{"key": "value"}'}
        wrapper._run(shared)
        result = shared["result"]

        # str parameter should NOT be parsed (stays as string)
        assert isinstance(result["str_param"], str)
        assert result["str_param"] == '{"key": "value"}'


class TestSecurityLimits:
    """Test security limits for JSON parsing."""

    def test_oversized_json_not_parsed(self, simple_node, interface_metadata):
        """JSON string exceeding 10MB → NOT parsed (security limit)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            template_resolution_mode="permissive",  # Use permissive mode to avoid validation error
            interface_metadata=interface_metadata,
        )

        # Create a JSON string larger than 10MB
        # A single large string item, repeated to exceed 10MB
        large_item = "x" * 1024  # 1KB item
        large_json = "[" + ",".join([f'"{large_item}"'] * 11_000) + "]"  # ~11MB
        assert len(large_json) > 10 * 1024 * 1024  # Verify it's > 10MB

        wrapper.set_params({"list_param": "${large_json}"})
        shared = {"large_json": large_json}
        wrapper._run(shared)
        result = shared["result"]

        # Should stay as string due to size limit
        assert isinstance(result["list_param"], str)
        assert len(result["list_param"]) > 10 * 1024 * 1024

        # Should have warning about oversized JSON in template_errors
        assert "__template_errors__" in shared

    def test_normal_sized_json_parsed(self, simple_node, interface_metadata):
        """JSON string under 10MB → parsed normally."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Create a reasonably large but valid JSON (~800KB)
        import json as json_module

        large_array = ["item"] * 100_000
        json_data = json_module.dumps(large_array)
        assert len(json_data) < 10 * 1024 * 1024  # Verify it's < 10MB

        wrapper.set_params({"list_param": "${json_data}"})
        shared = {"json_data": json_data}
        wrapper._run(shared)
        result = shared["result"]

        # Should be parsed successfully
        assert isinstance(result["list_param"], list)
        assert len(result["list_param"]) == 100_000


class TestReverseCoercionDictToString:
    """Test dict/list → JSON string coercion when expected type is str.

    This is the fix for MCP tools that declare `param: str` but expect JSON content.
    """

    def test_dict_becomes_json_string_for_str_param(self, simple_node):
        """Dict value becomes JSON string when param type is str."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str", "description": "JSON string"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Template resolves to dict, but param expects str
        wrapper.set_params({"path_params": "${data}"})
        shared = {"data": {"channel_id": "123"}}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["path_params"], str)
        # Should be valid JSON
        assert json_module.loads(result["path_params"]) == {"channel_id": "123"}

    def test_list_becomes_json_string_for_str_param(self, simple_node):
        """List value becomes JSON string when param type is str."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "items", "type": "str", "description": "JSON array string"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"items": "${data}"})
        shared = {"data": [1, 2, 3]}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["items"], str)
        assert json_module.loads(result["items"]) == [1, 2, 3]

    def test_dict_preserved_when_type_is_dict(self, simple_node, interface_metadata):
        """Dict stays dict when param type is dict (no coercion)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,  # Has dict_param: dict
        )

        wrapper.set_params({"dict_param": "${data}"})
        shared = {"data": {"key": "value"}}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_mcp_workflow_pattern(self, simple_node):
        """End-to-end test: workflow JSON object → MCP str param → JSON string.

        This is the exact bug scenario: workflow has JSON object for param,
        but MCP tool expects JSON string.
        """
        import json as json_module

        # MCP tool interface - declares str params for JSON content
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="mcp-discord-execute_action",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Workflow defines inline objects with templates (the bug case)
        wrapper.set_params({
            "path_params": {"channel_id": "${channel_id}"},
            "body_schema": {"content": "${message}"},
        })

        # Runtime values
        shared = {"channel_id": "123456789", "message": "Hello from pflow!"}
        wrapper._run(shared)

        result = shared["result"]

        # Both should be JSON strings, not dicts
        assert isinstance(result["path_params"], str)
        assert isinstance(result["body_schema"], str)

        # Should be valid, parseable JSON
        parsed_path = json_module.loads(result["path_params"])
        parsed_body = json_module.loads(result["body_schema"])

        # Check the structure - channel_id may be int or str depending on resolver
        assert "channel_id" in parsed_path
        assert parsed_body == {"content": "Hello from pflow!"}

    def test_deeply_nested_inline_object_with_templates(self, simple_node):
        """Deeply nested inline objects with templates should serialize correctly."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "data", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Deeply nested structure with template at the deepest level
        wrapper.set_params({"data": {"outer": {"middle": {"inner": "${value}"}}}})

        shared = {"value": "deep"}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["data"], str)

        parsed = json_module.loads(result["data"])
        assert parsed["outer"]["middle"]["inner"] == "deep"


class TestStaticParamCoercion:
    """Test dict/list → JSON string coercion for STATIC params (no templates).

    This is the bug fix for SUPPLEMENTARY-FINDINGS.md: objects without templates
    were not being coerced because they bypassed the template resolution path.
    """

    def test_static_dict_coerced_to_json_string(self, simple_node):
        """Static dict (no template) becomes JSON string when param type is str."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Static dict - NO template variables
        wrapper.set_params({"path_params": {"channel_id": "123"}})

        shared = {}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["path_params"], str)
        assert json_module.loads(result["path_params"]) == {"channel_id": "123"}

    def test_static_list_coerced_to_json_string(self, simple_node):
        """Static list (no template) becomes JSON string when param type is str."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "items", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Static list - NO template variables
        wrapper.set_params({"items": [1, 2, 3]})

        shared = {}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["items"], str)
        assert json_module.loads(result["items"]) == [1, 2, 3]

    def test_static_dict_preserved_when_type_is_dict(self, simple_node, interface_metadata):
        """Static dict stays dict when param type is dict (no coercion)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,  # Has dict_param: dict
        )

        # Static dict for dict-typed param
        wrapper.set_params({"dict_param": {"key": "value"}})

        shared = {}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_mixed_static_and_template_params(self, simple_node):
        """Mixed static + template params both coerced correctly."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Mixed: one static, one with template
        wrapper.set_params({
            "path_params": {"channel_id": "123"},  # Static - no template
            "body_schema": {"content": "${message}"},  # Has template
        })

        shared = {"message": "Hello!"}
        wrapper._run(shared)

        result = shared["result"]

        # Both should be JSON strings
        assert isinstance(result["path_params"], str)
        assert isinstance(result["body_schema"], str)

        # Both should parse to correct values
        assert json_module.loads(result["path_params"]) == {"channel_id": "123"}
        assert json_module.loads(result["body_schema"]) == {"content": "Hello!"}

    def test_mcp_workflow_pattern_with_hardcoded_channel(self, simple_node):
        """Real bug case: hardcoded channel_id with template message.

        This is the exact scenario from SUPPLEMENTARY-FINDINGS.md that was broken.
        """
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="mcp-discord-execute_action",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # The bug case: hardcoded path_params, template in body_schema
        wrapper.set_params({
            "path_params": {"channel_id": "1458059302022549698"},  # Hardcoded!
            "body_schema": {"content": "${message}"},
        })

        shared = {"message": "Test message"}
        wrapper._run(shared)

        result = shared["result"]

        # BOTH must be JSON strings for MCP to work
        assert isinstance(result["path_params"], str), "path_params should be JSON string"
        assert isinstance(result["body_schema"], str), "body_schema should be JSON string"

        # Verify valid JSON
        path_params = json_module.loads(result["path_params"])
        body_schema = json_module.loads(result["body_schema"])

        assert path_params == {"channel_id": "1458059302022549698"}
        assert body_schema == {"content": "Test message"}

    def test_fully_static_workflow_both_params(self, simple_node):
        """All static params (no templates at all) should still coerce."""
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Fully static - no templates anywhere
        wrapper.set_params({
            "path_params": {"channel_id": "123"},
            "body_schema": {"content": "hardcoded message"},
        })

        shared = {}
        wrapper._run(shared)

        result = shared["result"]

        # Both should be JSON strings
        assert isinstance(result["path_params"], str)
        assert isinstance(result["body_schema"], str)

        # Verify values
        assert json_module.loads(result["path_params"]) == {"channel_id": "123"}
        assert json_module.loads(result["body_schema"]) == {"content": "hardcoded message"}

    def test_json_loads_succeeds_with_coerced_static_dict(self, json_consuming_node):
        """CANARY TEST: Node calling json.loads() works with coerced static dict.

        This is the highest-value test because it would have FAILED before the fix.
        Before: dict passed to json.loads() → TypeError
        After:  dict coerced to JSON string → json.loads() succeeds

        This simulates exactly what MCP nodes do and catches the bug from
        SUPPLEMENTARY-FINDINGS.md: "the JSON object must be str, bytes or bytearray, not dict"
        """
        interface_metadata = {
            "params": [
                {"key": "json_data", "type": "str"},  # Typed as str, expects JSON string
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=json_consuming_node,
            node_id="mcp-like-node",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Pass a dict WITHOUT templates - the exact bug case
        wrapper.set_params({"json_data": {"channel_id": "123", "content": "hello"}})

        shared = {}
        # Before fix: This would raise TypeError in json.loads()
        # After fix: Dict is coerced to JSON string, json.loads() succeeds
        wrapper._run(shared)

        result = shared["result"]

        # Verify the node received a STRING (not dict)
        assert result["original_type"] == "str", "Node should receive string, not dict"

        # Verify json.loads() successfully parsed it back
        assert result["parsed"] == {"channel_id": "123", "content": "hello"}

    def test_static_dict_not_coerced_without_type_metadata(self, simple_node):
        """Static dict stays dict when no type metadata available.

        Without type information, we cannot know if the param should be
        coerced to a string. Safe default is to pass through unchanged.
        """
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=None,  # No type metadata!
        )

        # Static dict without type info
        wrapper.set_params({"unknown_param": {"key": "value"}})

        shared = {}
        wrapper._run(shared)

        result = shared["result"]

        # Without type metadata, dict should NOT be coerced
        assert isinstance(result["unknown_param"], dict)
        assert result["unknown_param"] == {"key": "value"}

    def test_deeply_nested_static_object_serializes_correctly(self, simple_node):
        """Deeply nested static objects serialize correctly to JSON string.

        This verifies that json.dumps() handles arbitrary nesting depth,
        including nested dicts, arrays, and mixed structures.
        """
        import json as json_module

        interface_metadata = {
            "params": [
                {"key": "complex_param", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Deeply nested static structure - NO templates
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

        wrapper.set_params({"complex_param": nested_value})

        shared = {}
        wrapper._run(shared)

        result = shared["result"]

        # Should be serialized to JSON string
        assert isinstance(result["complex_param"], str)

        # Should parse back to identical structure
        parsed = json_module.loads(result["complex_param"])
        assert parsed == nested_value
