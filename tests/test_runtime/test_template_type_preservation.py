"""Tests for template type preservation (Task 103).

These tests verify the core behavior change: simple templates like ${var}
now preserve their original type instead of being JSON-serialized to strings.

This fixes the double-serialization bug where:
  {"key": "${dict_var}"} became {"key": "{\"nested\": \"value\"}"}
  instead of the correct {"key": {"nested": "value"}}
"""

from pflow.runtime.template_resolver import TemplateResolver


class TestInlineObjectTypePreservation:
    """Test the original bug fix: inline objects preserve inner types."""

    def test_inline_object_preserves_dict_type(self):
        """THE PRIMARY FIX: {"key": "${dict}"} should NOT double-serialize.

        This is the exact scenario from Task 103 that was broken before.
        """
        context = {
            "config": {"name": "MyApp", "version": "1.0"},
            "data": {"value": "Hello", "count": 42},
        }

        result = TemplateResolver.resolve_nested(
            {"config": "${config}", "data": "${data}"},
            context,
        )

        # CRITICAL: Inner values must be dicts, not JSON strings
        assert isinstance(result["config"], dict), "config should be dict, not string"
        assert isinstance(result["data"], dict), "data should be dict, not string"

        # Values should be exactly preserved
        assert result["config"] == {"name": "MyApp", "version": "1.0"}
        assert result["data"] == {"value": "Hello", "count": 42}

    def test_inline_object_preserves_list_type(self):
        """Lists in inline objects should also preserve type."""
        context = {
            "items": [1, 2, 3],
            "users": [{"name": "Alice"}, {"name": "Bob"}],
        }

        result = TemplateResolver.resolve_nested(
            {"numbers": "${items}", "people": "${users}"},
            context,
        )

        assert isinstance(result["numbers"], list)
        assert isinstance(result["people"], list)
        assert result["numbers"] == [1, 2, 3]
        assert result["people"] == [{"name": "Alice"}, {"name": "Bob"}]

    def test_inline_object_preserves_primitive_types(self):
        """Primitives (int, bool, None) in inline objects preserve type."""
        context = {
            "count": 42,
            "enabled": True,
            "disabled": False,
            "empty": None,
        }

        result = TemplateResolver.resolve_nested(
            {
                "count": "${count}",
                "enabled": "${enabled}",
                "disabled": "${disabled}",
                "empty": "${empty}",
            },
            context,
        )

        assert result["count"] == 42
        assert isinstance(result["count"], int)

        assert result["enabled"] is True
        assert result["disabled"] is False
        assert result["empty"] is None

    def test_mixed_simple_and_complex_templates(self):
        """Inline objects can mix simple (type-preserved) and complex (string) templates."""
        context = {
            "user": {"name": "Alice", "age": 30},
            "greeting": "Hello",
        }

        result = TemplateResolver.resolve_nested(
            {
                "user_data": "${user}",  # Simple - dict preserved
                "message": "${greeting} ${user.name}!",  # Complex - string
            },
            context,
        )

        # Simple template preserves dict
        assert isinstance(result["user_data"], dict)
        assert result["user_data"] == {"name": "Alice", "age": 30}

        # Complex template returns string
        assert isinstance(result["message"], str)
        assert result["message"] == "Hello Alice!"

    def test_deeply_nested_type_preservation(self):
        """Type preservation works at any nesting level."""
        context = {"inner_data": {"deeply": {"nested": "value"}}}

        result = TemplateResolver.resolve_nested(
            {"level1": {"level2": {"level3": "${inner_data}"}}},
            context,
        )

        assert isinstance(result["level1"]["level2"]["level3"], dict)
        assert result["level1"]["level2"]["level3"] == {"deeply": {"nested": "value"}}


class TestPathTemplateTypePreservation:
    """Test that path templates (${data.field}) also preserve type."""

    def test_path_to_dict_preserves_type(self):
        """${data.nested} where nested is a dict should return dict."""
        context = {
            "data": {
                "config": {"setting": "value"},
                "items": [1, 2, 3],
            }
        }

        # Path to dict
        result = TemplateResolver.resolve_template("${data.config}", context)
        assert isinstance(result, dict)
        assert result == {"setting": "value"}

        # Path to list
        result = TemplateResolver.resolve_template("${data.items}", context)
        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_path_to_array_element_preserves_type(self):
        """${items[0]} where element is a dict should return dict."""
        context = {
            "items": [
                {"id": 1, "name": "first"},
                {"id": 2, "name": "second"},
            ]
        }

        result = TemplateResolver.resolve_template("${items[0]}", context)
        assert isinstance(result, dict)
        assert result == {"id": 1, "name": "first"}

    def test_complex_path_preserves_type(self):
        """Deep path like ${api.response.data.users} preserves type."""
        context = {
            "api": {
                "response": {
                    "data": {
                        "users": [{"name": "Alice"}, {"name": "Bob"}],
                        "metadata": {"total": 2},
                    }
                }
            }
        }

        # Path to list
        result = TemplateResolver.resolve_template("${api.response.data.users}", context)
        assert isinstance(result, list)
        assert len(result) == 2

        # Path to dict
        result = TemplateResolver.resolve_template("${api.response.data.metadata}", context)
        assert isinstance(result, dict)
        assert result == {"total": 2}

        # Path to primitive
        result = TemplateResolver.resolve_template("${api.response.data.metadata.total}", context)
        assert isinstance(result, int)
        assert result == 2


class TestSimpleTemplateDetection:
    """Test the boundary between simple and complex templates.

    Simple templates (entire string is ${var}) preserve type.
    Complex templates (text around variable) return strings.

    This documents the exact pattern that determines behavior.
    """

    def test_simple_template_patterns_detected(self):
        """These patterns ARE simple templates - type will be preserved."""
        assert TemplateResolver.is_simple_template("${var}") is True
        assert TemplateResolver.is_simple_template("${data.field}") is True
        assert TemplateResolver.is_simple_template("${items[0]}") is True
        assert TemplateResolver.is_simple_template("${api.response.data}") is True
        assert TemplateResolver.is_simple_template("${user-id}") is True  # Hyphens allowed

    def test_complex_template_patterns_detected(self):
        """These patterns are NOT simple - will return strings."""
        assert TemplateResolver.is_simple_template(" ${var}") is False  # Leading space
        assert TemplateResolver.is_simple_template("${var} ") is False  # Trailing space
        assert TemplateResolver.is_simple_template("${a}${b}") is False  # Multiple templates
        assert TemplateResolver.is_simple_template("text ${var}") is False  # Prefix
        assert TemplateResolver.is_simple_template("${var} text") is False  # Suffix
        assert TemplateResolver.is_simple_template("Hello ${name}!") is False  # Embedded

    def test_extract_simple_template_var(self):
        """Test variable extraction from simple templates."""
        assert TemplateResolver.extract_simple_template_var("${var}") == "var"
        assert TemplateResolver.extract_simple_template_var("${data.field}") == "data.field"
        assert TemplateResolver.extract_simple_template_var("${items[0].name}") == "items[0].name"

        # Complex templates return None
        assert TemplateResolver.extract_simple_template_var("Hello ${name}") is None
        assert TemplateResolver.extract_simple_template_var("${a}${b}") is None

    def test_unresolved_simple_template_in_nested_structure(self):
        """Unresolved simple templates stay as-is in nested structures."""
        context = {"exists": "value"}

        result = TemplateResolver.resolve_nested(
            {"found": "${exists}", "missing": "${not_found}"},
            context,
        )

        assert result["found"] == "value"
        assert result["missing"] == "${not_found}"  # Stays as template string
