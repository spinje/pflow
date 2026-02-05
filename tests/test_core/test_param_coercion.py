"""Tests for parameter type coercion utilities.

Focus:
1. Behavior that matters for MCP tools expecting JSON strings (coerce_to_declared_type)
2. CLI input coercion to match workflow input declarations (coerce_input_to_declared_type)
"""

import json

from pflow.core.param_coercion import coerce_input_to_declared_type, coerce_to_declared_type


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


# =============================================================================
# Tests for coerce_input_to_declared_type (CLI input → declared type)
# =============================================================================


class TestInputCoercionIntToString:
    """Test int → string coercion for workflow inputs.

    This is the PRIMARY bug fix: numeric strings coerced to int by CLI
    should be converted back to string when declared type is "string".
    """

    def test_int_coerced_to_string_when_declared_string(self):
        """THE BUG FIX: Discord snowflake ID should remain string."""
        # CLI's infer_type() converts "1458059302022549698" to int
        # But workflow declares type: string
        result = coerce_input_to_declared_type(1458059302022549698, "string")

        assert isinstance(result, str)
        assert result == "1458059302022549698"

    def test_float_coerced_to_string_when_declared_string(self):
        """Floats should also coerce to string."""
        result = coerce_input_to_declared_type(3.14159, "string")

        assert isinstance(result, str)
        assert result == "3.14159"

    def test_bool_coerced_to_string_when_declared_string(self):
        """Booleans should coerce to string."""
        result = coerce_input_to_declared_type(True, "string")

        assert isinstance(result, str)
        assert result == "True"

    def test_string_unchanged_when_declared_string(self):
        """String stays string (no change needed)."""
        original = "already a string"
        result = coerce_input_to_declared_type(original, "string")

        assert result is original  # Same object

    def test_type_alias_str_works(self):
        """Type alias 'str' should work like 'string'."""
        result = coerce_input_to_declared_type(42, "str")

        assert isinstance(result, str)
        assert result == "42"


class TestInputCoercionStringToInt:
    """Test string → int coercion for workflow inputs."""

    def test_numeric_string_coerced_to_int(self):
        """String "42" should become int 42 when declared integer."""
        result = coerce_input_to_declared_type("42", "integer")

        assert isinstance(result, int)
        assert result == 42

    def test_negative_string_coerced_to_int(self):
        """Negative number strings should work."""
        result = coerce_input_to_declared_type("-123", "integer")

        assert isinstance(result, int)
        assert result == -123

    def test_int_unchanged_when_declared_integer(self):
        """Int stays int when already correct type."""
        original = 42
        result = coerce_input_to_declared_type(original, "integer")

        assert result is original

    def test_invalid_string_returns_original(self):
        """Non-numeric string can't coerce, returns original."""
        result = coerce_input_to_declared_type("hello", "integer")

        assert result == "hello"  # Unchanged

    def test_type_alias_int_works(self):
        """Type alias 'int' should work like 'integer'."""
        result = coerce_input_to_declared_type("99", "int")

        assert isinstance(result, int)
        assert result == 99


class TestInputCoercionStringToNumber:
    """Test string → float coercion for workflow inputs."""

    def test_decimal_string_coerced_to_float(self):
        """String "3.14" should become float."""
        result = coerce_input_to_declared_type("3.14", "number")

        assert isinstance(result, float)
        assert result == 3.14

    def test_integer_string_coerced_to_float(self):
        """Integer string should also work for number type."""
        result = coerce_input_to_declared_type("42", "number")

        assert isinstance(result, float)
        assert result == 42.0

    def test_type_alias_float_works(self):
        """Type alias 'float' should work like 'number'."""
        result = coerce_input_to_declared_type("2.718", "float")

        assert isinstance(result, float)
        assert result == 2.718


class TestInputCoercionStringToBool:
    """Test string → bool coercion for workflow inputs."""

    def test_true_strings_coerce_to_true(self):
        """Various 'true' strings should become True."""
        for value in ["true", "True", "TRUE", "1", "yes", "Yes"]:
            result = coerce_input_to_declared_type(value, "boolean")
            assert result is True, f"Expected True for '{value}'"

    def test_false_strings_coerce_to_false(self):
        """Various 'false' strings should become False."""
        for value in ["false", "False", "FALSE", "0", "no", "No"]:
            result = coerce_input_to_declared_type(value, "boolean")
            assert result is False, f"Expected False for '{value}'"

    def test_invalid_bool_string_returns_original(self):
        """Invalid boolean string returns original."""
        result = coerce_input_to_declared_type("maybe", "boolean")

        assert result == "maybe"

    def test_bool_unchanged_when_declared_boolean(self):
        """Bool stays bool when already correct type."""
        assert coerce_input_to_declared_type(True, "boolean") is True
        assert coerce_input_to_declared_type(False, "boolean") is False

    def test_type_alias_bool_works(self):
        """Type alias 'bool' should work like 'boolean'."""
        result = coerce_input_to_declared_type("yes", "bool")

        assert result is True


class TestInputCoercionStringToObject:
    """Test string → dict coercion for workflow inputs."""

    def test_json_object_string_coerced_to_dict(self):
        """Valid JSON object string should become dict."""
        result = coerce_input_to_declared_type('{"key": "value"}', "object")

        assert isinstance(result, dict)
        assert result == {"key": "value"}

    def test_nested_json_object_works(self):
        """Nested JSON should parse correctly."""
        result = coerce_input_to_declared_type('{"outer": {"inner": 42}}', "object")

        assert isinstance(result, dict)
        assert result["outer"]["inner"] == 42

    def test_invalid_json_returns_original(self):
        """Invalid JSON string returns original."""
        result = coerce_input_to_declared_type("not json", "object")

        assert result == "not json"

    def test_json_array_returns_original_for_object(self):
        """JSON array should NOT coerce to object type."""
        result = coerce_input_to_declared_type("[1, 2, 3]", "object")

        assert result == "[1, 2, 3]"  # Original string

    def test_dict_unchanged_when_declared_object(self):
        """Dict stays dict when already correct type."""
        original = {"key": "value"}
        result = coerce_input_to_declared_type(original, "object")

        assert result is original

    def test_type_alias_dict_works(self):
        """Type alias 'dict' should work like 'object'."""
        result = coerce_input_to_declared_type('{"a": 1}', "dict")

        assert isinstance(result, dict)


class TestInputCoercionStringToArray:
    """Test string → list coercion for workflow inputs."""

    def test_json_array_string_coerced_to_list(self):
        """Valid JSON array string should become list."""
        result = coerce_input_to_declared_type("[1, 2, 3]", "array")

        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_array_of_objects_works(self):
        """Array of objects should parse correctly."""
        result = coerce_input_to_declared_type('[{"id": 1}, {"id": 2}]', "array")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_json_object_returns_original_for_array(self):
        """JSON object should NOT coerce to array type."""
        result = coerce_input_to_declared_type('{"key": "value"}', "array")

        assert result == '{"key": "value"}'  # Original string

    def test_list_unchanged_when_declared_array(self):
        """List stays list when already correct type."""
        original = [1, 2, 3]
        result = coerce_input_to_declared_type(original, "array")

        assert result is original

    def test_type_alias_list_works(self):
        """Type alias 'list' should work like 'array'."""
        result = coerce_input_to_declared_type("[4, 5]", "list")

        assert isinstance(result, list)


class TestInputCoercionNoType:
    """Test behavior when no type is declared."""

    def test_no_type_returns_original_int(self):
        """Without declared type, int stays int."""
        result = coerce_input_to_declared_type(42, None)

        assert result == 42
        assert isinstance(result, int)

    def test_no_type_returns_original_string(self):
        """Without declared type, string stays string."""
        result = coerce_input_to_declared_type("hello", None)

        assert result == "hello"

    def test_no_type_returns_original_dict(self):
        """Without declared type, dict stays dict."""
        original = {"key": "value"}
        result = coerce_input_to_declared_type(original, None)

        assert result is original


class TestInputCoercionUnknownType:
    """Test behavior with unknown/unsupported type names."""

    def test_unknown_type_returns_original(self):
        """Unknown type names should return original value."""
        result = coerce_input_to_declared_type("test", "custom_type")

        assert result == "test"

    def test_empty_type_returns_original(self):
        """Empty string type should return original value."""
        result = coerce_input_to_declared_type(42, "")

        assert result == 42
