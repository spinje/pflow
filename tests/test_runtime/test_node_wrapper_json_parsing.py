"""Tests for automatic JSON parsing in node wrapper.

Tests the feature that automatically parses JSON strings when passed to
dict/list parameters, enabling shell+jq → MCP workflows without LLM steps.
"""

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


@pytest.fixture
def simple_node():
    """Create a simple test node."""
    return SimpleNode()


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
