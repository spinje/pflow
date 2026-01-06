"""Tests for parameter type coercion utilities.

Focus: Behavior that matters for MCP tools expecting JSON strings.
"""

import json

from pflow.core.param_coercion import coerce_to_declared_type


class TestDictToStringCoercion:
    """Test dict -> JSON string coercion for str-typed parameters."""

    def test_dict_becomes_json_string_when_type_is_str(self):
        """Main use case: MCP tool expects JSON string, we have dict."""
        result = coerce_to_declared_type({"channel_id": "123"}, "str")

        assert isinstance(result, str)
        # Should be valid JSON that parses back to original
        assert json.loads(result) == {"channel_id": "123"}

    def test_nested_dict_serializes_correctly(self):
        """Nested structures should serialize to valid JSON."""
        value = {"outer": {"inner": {"deep": "value"}}}
        result = coerce_to_declared_type(value, "str")

        assert isinstance(result, str)
        assert json.loads(result) == value

    def test_empty_dict_becomes_empty_json_object(self):
        """Empty dict should become '{}'."""
        result = coerce_to_declared_type({}, "str")
        assert result == "{}"


class TestListToStringCoercion:
    """Test list -> JSON string coercion for str-typed parameters."""

    def test_list_becomes_json_string_when_type_is_str(self):
        """List should serialize to JSON array string."""
        result = coerce_to_declared_type([1, 2, 3], "str")

        assert isinstance(result, str)
        assert json.loads(result) == [1, 2, 3]

    def test_list_of_dicts_serializes_correctly(self):
        """Complex list structures should serialize properly."""
        value = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = coerce_to_declared_type(value, "str")

        assert isinstance(result, str)
        assert json.loads(result) == value

    def test_empty_list_becomes_empty_json_array(self):
        """Empty list should become '[]'."""
        result = coerce_to_declared_type([], "str")
        assert result == "[]"


class TestNoCoercionWhenTypeMatches:
    """Ensure we don't break params that should stay as dict/list."""

    def test_dict_unchanged_when_type_is_dict(self):
        """Dict stays dict when expected type is dict."""
        original = {"key": "value"}
        result = coerce_to_declared_type(original, "dict")

        assert result is original  # Same object, not serialized
        assert isinstance(result, dict)

    def test_dict_unchanged_when_type_is_object(self):
        """Dict stays dict when expected type is object (JSON Schema alias)."""
        original = {"key": "value"}
        result = coerce_to_declared_type(original, "object")

        assert result is original
        assert isinstance(result, dict)

    def test_list_unchanged_when_type_is_list(self):
        """List stays list when expected type is list."""
        original = [1, 2, 3]
        result = coerce_to_declared_type(original, "list")

        assert result is original
        assert isinstance(result, list)

    def test_list_unchanged_when_type_is_array(self):
        """List stays list when expected type is array (JSON Schema alias)."""
        original = [1, 2, 3]
        result = coerce_to_declared_type(original, "array")

        assert result is original
        assert isinstance(result, list)


class TestPassthroughBehavior:
    """Values that should pass through unchanged."""

    def test_string_unchanged_when_type_is_str(self):
        """String passes through unchanged (no double-encoding)."""
        result = coerce_to_declared_type("already a string", "str")
        assert result == "already a string"

    def test_json_string_not_double_encoded(self):
        """If user already passed JSON string, don't double-encode."""
        json_string = '{"already": "json"}'
        result = coerce_to_declared_type(json_string, "str")
        assert result == json_string  # Same string, not '"{...}"'

    def test_none_passes_through(self):
        """None should pass through (let node handle it)."""
        result = coerce_to_declared_type(None, "str")
        assert result is None

    def test_no_coercion_when_type_unknown(self):
        """No coercion when expected_type is None (unknown)."""
        original = {"key": "value"}
        result = coerce_to_declared_type(original, None)
        assert result is original


class TestUnicodeHandling:
    """Test Unicode and special characters."""

    def test_unicode_in_dict_serializes_correctly(self):
        """Unicode characters should serialize and parse correctly."""
        result = coerce_to_declared_type({"emoji": "🚀", "chinese": "你好"}, "str")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["emoji"] == "🚀"
        assert parsed["chinese"] == "你好"

    def test_special_characters_in_values(self):
        """Special characters (newlines, quotes) should be escaped."""
        result = coerce_to_declared_type({"text": 'line1\nline2\twith "quotes"'}, "str")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["text"] == 'line1\nline2\twith "quotes"'


class TestNonSerializableHandling:
    """Test graceful handling of non-JSON-serializable objects."""

    def test_non_serializable_object_falls_back(self):
        """Non-serializable objects should fall back to original value."""

        class CustomClass:
            pass

        original = {"obj": CustomClass()}
        result = coerce_to_declared_type(original, "str")

        # Should return original dict (not crash)
        assert result is original
        assert isinstance(result, dict)

    def test_partially_serializable_dict_falls_back(self):
        """Dict with non-serializable values should fall back."""
        import io

        # File handles are not JSON serializable
        original = {"file": io.StringIO("test")}
        result = coerce_to_declared_type(original, "str")

        assert result is original
