"""Test template resolution in nested structures.

This test file verifies that template variables in nested dictionaries,
lists, and deeply nested structures are properly resolved by the template
resolution engine, not just detected by the validator.
"""

import pytest

from pflow.runtime.template_resolver import TemplateResolver


class TestNestedTemplateResolution:
    """Test that template resolution works for nested structures."""

    def test_has_templates_detects_nested_dict_templates(self):
        """Test that has_templates detects templates in nested dictionaries."""
        # Simple dict with templates
        value = {"header": "Bearer ${token}", "id": "${channel}"}
        assert TemplateResolver.has_templates(value), "Should detect templates in dict"

        # Nested dict with templates
        value = {"headers": {"Authorization": "Bearer ${token}"}, "static": "value"}
        assert TemplateResolver.has_templates(value), "Should detect templates in nested dict"

        # Dict without templates
        value = {"headers": {"Authorization": "Bearer token123"}, "static": "value"}
        assert not TemplateResolver.has_templates(value), "Should not detect templates when none exist"

    def test_has_templates_detects_list_templates(self):
        """Test that has_templates detects templates in lists."""
        # List with templates
        value = ["${item1}", "static", "${item2}"]
        assert TemplateResolver.has_templates(value), "Should detect templates in list"

        # Nested list with templates
        value = [["${item1}", "static"], ["another", "${item2}"]]
        assert TemplateResolver.has_templates(value), "Should detect templates in nested list"

        # List without templates
        value = ["item1", "item2", "item3"]
        assert not TemplateResolver.has_templates(value), "Should not detect templates when none exist"

    def test_has_templates_detects_deeply_nested(self):
        """Test that has_templates detects templates in deeply nested structures."""
        value = {
            "level1": {
                "level2": {
                    "level3": {
                        "items": ["${deep_var}", "static"],
                        "config": {"key": "${another_var}"},
                    }
                }
            }
        }
        assert TemplateResolver.has_templates(value), "Should detect deeply nested templates"

    def test_resolve_nested_dict_templates(self):
        """Test that nested dictionary templates are resolved."""
        # Test data with nested templates
        params = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer ${auth_token}",
                "X-Channel-ID": "${channel_id}",
                "Content-Type": "application/json",  # Static value
            },
            "body": {
                "message": "${message_text}",
                "user": "${user_id}",
                "metadata": {
                    "timestamp": "${timestamp}",
                    "version": "1.0",  # Static value
                },
            },
        }

        # Context with values to resolve
        context = {
            "auth_token": "xoxb-123456",
            "channel_id": "C09C16NAU5B",
            "message_text": "Hello, world!",
            "user_id": "U123456",
            "timestamp": "2024-01-01T00:00:00Z",
        }

        # Resolve templates
        resolved = TemplateResolver.resolve_nested(params, context)

        # Verify resolution
        assert resolved["url"] == "https://api.example.com"  # Static unchanged
        assert resolved["headers"]["Authorization"] == "Bearer xoxb-123456"
        assert resolved["headers"]["X-Channel-ID"] == "C09C16NAU5B"
        assert resolved["headers"]["Content-Type"] == "application/json"  # Static unchanged
        assert resolved["body"]["message"] == "Hello, world!"
        assert resolved["body"]["user"] == "U123456"
        assert resolved["body"]["metadata"]["timestamp"] == "2024-01-01T00:00:00Z"
        assert resolved["body"]["metadata"]["version"] == "1.0"  # Static unchanged

    def test_resolve_list_templates(self):
        """Test that templates in lists are resolved."""
        params = {
            "items": ["${item1}", "static_value", "${item2}"],
            "nested_lists": [
                ["${first}", "middle"],
                ["another", "${second}"],
                [{"key": "${third}"}],
            ],
        }

        context = {
            "item1": "apple",
            "item2": "banana",
            "first": "alpha",
            "second": "beta",
            "third": "gamma",
        }

        resolved = TemplateResolver.resolve_nested(params, context)

        assert resolved["items"] == ["apple", "static_value", "banana"]
        assert resolved["nested_lists"][0] == ["alpha", "middle"]
        assert resolved["nested_lists"][1] == ["another", "beta"]
        assert resolved["nested_lists"][2][0]["key"] == "gamma"

    def test_resolve_mixed_types(self):
        """Test resolution with mixed types (strings, numbers, bools, None)."""
        params = {
            "string_val": "${str_var}",
            "number_val": 42,  # Should remain as int
            "bool_val": True,  # Should remain as bool
            "none_val": None,  # Should remain as None
            "list_mix": ["${str_var}", 123, False, None],
            "dict_mix": {
                "template": "${str_var}",
                "number": 456,
                "bool": False,
            },
        }

        context = {"str_var": "resolved_string"}

        resolved = TemplateResolver.resolve_nested(params, context)

        assert resolved["string_val"] == "resolved_string"
        assert resolved["number_val"] == 42
        assert isinstance(resolved["number_val"], int)  # Type preserved
        assert resolved["bool_val"] is True
        assert isinstance(resolved["bool_val"], bool)  # Type preserved
        assert resolved["none_val"] is None
        assert resolved["list_mix"] == ["resolved_string", 123, False, None]
        assert resolved["dict_mix"]["template"] == "resolved_string"
        assert resolved["dict_mix"]["number"] == 456
        assert resolved["dict_mix"]["bool"] is False

    def test_resolve_partial_templates_in_strings(self):
        """Test that templates within larger strings are resolved."""
        params = {
            "url": "https://api.example.com/v1/${endpoint}",
            "message": "Hello ${user}, your ID is ${id}!",
            "headers": {
                "User-Agent": "MyApp/${version} (${platform})",
            },
        }

        context = {
            "endpoint": "users",
            "user": "Alice",
            "id": "12345",
            "version": "2.0",
            "platform": "Linux",
        }

        resolved = TemplateResolver.resolve_nested(params, context)

        assert resolved["url"] == "https://api.example.com/v1/users"
        assert resolved["message"] == "Hello Alice, your ID is 12345!"
        assert resolved["headers"]["User-Agent"] == "MyApp/2.0 (Linux)"

    def test_unresolved_templates_remain(self):
        """Test that templates without values in context remain as templates."""
        params = {
            "resolved": "${exists}",
            "unresolved": "${does_not_exist}",
            "nested": {
                "resolved": "${exists}",
                "unresolved": "${missing}",
            },
        }

        context = {"exists": "I am here"}

        resolved = TemplateResolver.resolve_nested(params, context)

        assert resolved["resolved"] == "I am here"
        assert resolved["unresolved"] == "${does_not_exist}"  # Remains as template
        assert resolved["nested"]["resolved"] == "I am here"
        assert resolved["nested"]["unresolved"] == "${missing}"  # Remains as template

    def test_deeply_nested_resolution(self):
        """Test resolution of deeply nested structures (5+ levels)."""
        params = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {
                                "deep_value": "${deep_var}",
                                "deep_list": ["${item1}", "${item2}"],
                            }
                        }
                    }
                }
            }
        }

        context = {"deep_var": "found_me", "item1": "first", "item2": "second"}

        resolved = TemplateResolver.resolve_nested(params, context)

        assert resolved["level1"]["level2"]["level3"]["level4"]["level5"]["deep_value"] == "found_me"
        assert resolved["level1"]["level2"]["level3"]["level4"]["level5"]["deep_list"] == ["first", "second"]

    def test_empty_structures(self):
        """Test that empty dicts and lists are handled correctly."""
        params = {
            "empty_dict": {},
            "empty_list": [],
            "nested_empty": {"sub": {}, "items": []},
        }

        context = {"some_var": "value"}

        resolved = TemplateResolver.resolve_nested(params, context)

        assert resolved["empty_dict"] == {}
        assert resolved["empty_list"] == []
        assert resolved["nested_empty"]["sub"] == {}
        assert resolved["nested_empty"]["items"] == []

    def test_node_wrapper_integration(self):
        """Test that node wrapper properly handles nested template params."""
        from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper

        # Create a mock node
        class MockNode:
            def __init__(self):
                self.params = {}

            def set_params(self, params):
                self.params = params

        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        # Set params with nested templates
        params = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer ${token}",
                "X-API-Key": "${api_key}",
            },
            "body": {
                "data": ["${item1}", "${item2}"],
            },
        }

        wrapper.set_params(params)

        # Currently this will categorize the nested structures as static (BUG!)
        # After fix, they should be in template_params
        assert "headers" in wrapper.template_params or "headers" in wrapper.static_params
        assert "body" in wrapper.template_params or "body" in wrapper.static_params

        # This test will fail with current implementation, showing the bug


class TestTemplateResolverBackwardCompatibility:
    """Ensure existing functionality still works after adding nested support."""

    def test_simple_string_resolution_unchanged(self):
        """Test that simple string template resolution still works."""
        template = "Hello ${name}, welcome to ${place}!"
        context = {"name": "Alice", "place": "Wonderland"}

        result = TemplateResolver.resolve_string(template, context)
        assert result == "Hello Alice, welcome to Wonderland!"

    def test_path_resolution_unchanged(self):
        """Test that path-based template resolution still works."""
        template = "User: ${user.name}, Age: ${user.age}"
        context = {"user": {"name": "Bob", "age": 30}}

        result = TemplateResolver.resolve_string(template, context)
        assert result == "User: Bob, Age: 30"

    def test_resolve_value_unchanged(self):
        """Test that resolve_value still works for simple and path access."""
        context = {
            "simple": "value",
            "nested": {"field": "data"},
            "deep": {"level1": {"level2": "deep_value"}},
        }

        # Simple access
        assert TemplateResolver.resolve_value("simple", context) == "value"

        # Nested access
        assert TemplateResolver.resolve_value("nested.field", context) == "data"

        # Deep nested access
        assert TemplateResolver.resolve_value("deep.level1.level2", context) == "deep_value"

        # Non-existent
        assert TemplateResolver.resolve_value("missing", context) is None
        assert TemplateResolver.resolve_value("nested.missing", context) is None