"""Tests for clear error messages when JSON parsing fails.

Tests the error handling when malformed JSON strings are passed to
dict/list parameters, ensuring users get actionable error messages.
"""

import pytest

from pflow.pocketflow import Node
from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper


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
        ]
    }


class TestMalformedJsonErrorMessages:
    """Test clear error messages for malformed JSON."""

    def test_invalid_json_to_dict_clear_error(self, simple_node, interface_metadata):
        """Malformed JSON to dict → clear error message."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${bad_json}"})
        shared = {"bad_json": "{not valid json}"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "malformed JSON string" in error_msg
        assert "dict_param" in error_msg
        assert "{not valid json}" in error_msg

    def test_invalid_json_to_list_clear_error(self, simple_node, interface_metadata):
        """Malformed JSON to list → clear error message."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${bad_json}"})
        shared = {"bad_json": "[not valid json"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "malformed JSON string" in error_msg
        assert "list_param" in error_msg
        assert "[not valid json" in error_msg

    def test_single_quotes_detected(self, simple_node, interface_metadata):
        """Single quotes in JSON → error mentions it."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${single_quotes}"})
        shared = {"single_quotes": "{'key': 'value'}"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Single quotes detected" in error_msg
        assert "double quotes" in error_msg

    def test_mismatched_braces_detected(self, simple_node, interface_metadata):
        """Mismatched braces → error mentions it."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${missing_brace}"})
        shared = {"missing_brace": '{"key": "value"'}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Mismatched braces" in error_msg

    def test_mismatched_brackets_detected(self, simple_node, interface_metadata):
        """Mismatched brackets → error mentions it."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${missing_bracket}"})
        shared = {"missing_bracket": '["item1", "item2"'}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Mismatched brackets" in error_msg

    def test_trailing_comma_detected(self, simple_node, interface_metadata):
        """Trailing comma → error mentions it."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${trailing_comma}"})
        shared = {"trailing_comma": "[1, 2, 3,]"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Trailing comma" in error_msg

    def test_error_includes_suggestions(self, simple_node, interface_metadata):
        """Error message includes actionable suggestions."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${bad_json}"})
        shared = {"bad_json": "{bad}"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Common JSON formatting issues:" in error_msg
        assert "Fix: Ensure the source outputs valid JSON" in error_msg
        assert "Test with:" in error_msg


class TestValidJsonStillWorks:
    """Regression tests: valid JSON should still work."""

    def test_valid_json_dict_no_error(self, simple_node, interface_metadata):
        """Valid JSON to dict → no error (regression check)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${valid_json}"})
        shared = {"valid_json": '{"key": "value"}'}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_valid_json_list_no_error(self, simple_node, interface_metadata):
        """Valid JSON to list → no error (regression check)."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"list_param": "${valid_json}"})
        shared = {"valid_json": '["item1", "item2"]'}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["list_param"], list)
        assert result["list_param"] == ["item1", "item2"]


class TestNonJsonStringsNotFlagged:
    """Non-JSON strings should not trigger JSON error messages."""

    def test_plain_text_to_dict_not_json_error(self, simple_node, interface_metadata):
        """Plain text to dict → doesn't mention JSON parsing."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${plain_text}"})
        shared = {"plain_text": "just plain text"}

        # Should NOT raise error (doesn't start with { or [)
        # The string doesn't look like JSON, so no JSON error
        wrapper._run(shared)

        # Node receives string (Pydantic would catch it later if node validates)
        result = shared["result"]
        assert result["dict_param"] == "just plain text"

    def test_empty_string_to_dict_not_json_error(self, simple_node, interface_metadata):
        """Empty string to dict → doesn't trigger JSON error."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${empty}"})
        shared = {"empty": ""}

        # Should NOT raise error (empty string)
        wrapper._run(shared)

        result = shared["result"]
        assert result["dict_param"] == ""


class TestPermissiveModeStoresError:
    """Permissive mode should store error instead of raising."""

    def test_permissive_mode_stores_json_error(self, simple_node, interface_metadata):
        """Permissive mode → stores error in __template_errors__."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            template_resolution_mode="permissive",  # Permissive mode
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"dict_param": "${bad_json}"})
        shared = {"bad_json": "{not valid}"}

        # In permissive mode, should NOT raise, but store error
        wrapper._run(shared)

        # Check error was stored
        assert "__template_errors__" in shared
        assert "test" in shared["__template_errors__"]
        error_info = shared["__template_errors__"]["test"]
        assert "malformed JSON" in error_info["message"]
