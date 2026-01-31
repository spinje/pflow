"""Test that compiler properly detects and wraps nodes with nested templates.

This test specifically validates the fix to _apply_template_wrapping that
ensures nodes with templates in nested structures (dicts, lists) get wrapped
with TemplateAwareNodeWrapper.
"""

from unittest.mock import Mock

from pflow.pocketflow import BaseNode
from pflow.runtime.compiler import _apply_template_wrapping
from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper


class TestCompilerTemplateWrapping:
    """Test that the compiler properly detects templates and applies wrapping."""

    def test_wraps_node_with_nested_dict_templates(self):
        """Test that nodes with templates in nested dicts get wrapped."""
        # Create a mock node
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {"token": "abc123"}

        # Params with templates in nested dictionary (like HTTP headers)
        params = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer ${token}",  # Template in nested dict!
                "Content-Type": "application/json",
            },
        }

        # Apply wrapping
        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should be wrapped because of nested template
        assert isinstance(result, TemplateAwareNodeWrapper)
        assert result.inner_node is node
        assert result.node_id == node_id

    def test_wraps_node_with_nested_list_templates(self):
        """Test that nodes with templates in lists get wrapped."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {"item1": "a", "item2": "b"}

        # Params with templates in list
        params = {
            "items": ["${item1}", "static", "${item2}"],  # Templates in list!
            "config": {"enabled": True},
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should be wrapped because of templates in list
        assert isinstance(result, TemplateAwareNodeWrapper)

    def test_wraps_node_with_deeply_nested_templates(self):
        """Test that deeply nested templates are detected."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {"deep_value": "found"}

        # Params with deeply nested template
        params = {
            "config": {
                "level1": {
                    "level2": {
                        "level3": {
                            "value": "${deep_value}"  # 4 levels deep!
                        }
                    }
                }
            }
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should be wrapped even for deeply nested templates
        assert isinstance(result, TemplateAwareNodeWrapper)

    def test_does_not_wrap_node_without_templates(self):
        """Test that nodes without templates are not wrapped."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {}

        # Params without any templates
        params = {
            "url": "https://api.example.com",
            "headers": {"Authorization": "Bearer hardcoded_token", "Content-Type": "application/json"},
            "items": ["a", "b", "c"],
            "config": {"enabled": True, "timeout": 30},
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should NOT be wrapped - no templates
        assert result is node  # Same instance, not wrapped
        assert not isinstance(result, TemplateAwareNodeWrapper)

    def test_wraps_node_with_simple_string_templates(self):
        """Test backward compatibility - simple string templates still work."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {"name": "Alice"}

        # Simple string template (original case)
        params = {"message": "Hello ${name}!", "static": "no template here"}

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should be wrapped for simple string templates
        assert isinstance(result, TemplateAwareNodeWrapper)

    def test_mixed_nested_and_simple_templates(self):
        """Test that mixed template types are all detected."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {"token": "xyz", "user": "Bob"}

        params = {
            "greeting": "Hello ${user}!",  # Simple string template
            "headers": {
                "Authorization": "Bearer ${token}"  # Nested template
            },
            "tags": ["${user}", "active"],  # Template in list
            "static_value": 42,  # No template
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should be wrapped due to multiple template types
        assert isinstance(result, TemplateAwareNodeWrapper)

    def test_empty_params_not_wrapped(self):
        """Test that nodes with empty params are not wrapped."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {}
        params = {}

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should not be wrapped - no params
        assert result is node

    def test_params_with_only_numbers_not_wrapped(self):
        """Test that numeric/boolean params don't trigger wrapping."""
        node = Mock(spec=BaseNode)
        node_id = "test_node"
        initial_params = {}

        params = {
            "timeout": 30,
            "retries": 3,
            "enabled": True,
            "threshold": 0.95,
            "config": {"max_size": 1000, "active": False},
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Should not be wrapped - no templates
        assert result is node

    def test_real_world_slack_scenario(self):
        """Test the exact Slack/Google Sheets scenario that was failing."""
        node = Mock(spec=BaseNode)
        node_id = "fetch_messages"
        initial_params = {"slack_channel_id": "C123", "message_count": 10, "slack_bot_token": "xoxb-123"}

        # The exact params structure from the failing workflow
        params = {
            "url": "https://slack.com/api/conversations.history",
            "method": "GET",
            "params": {"channel": "${slack_channel_id}", "limit": "${message_count}"},
            "headers": {"Authorization": "Bearer ${slack_bot_token}"},
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # MUST be wrapped - this was the bug!
        assert isinstance(result, TemplateAwareNodeWrapper), (
            "Failed to wrap node with nested templates - this was the original bug!"
        )

        # Verify the wrapper has the correct attributes
        assert result.inner_node is node
        assert result.node_id == node_id
        assert result.initial_params == initial_params

    def test_body_with_nested_template_objects(self):
        """Test HTTP body with nested template objects."""
        node = Mock(spec=BaseNode)
        node_id = "api_call"
        initial_params = {"channel": "C456", "message": "Hello"}

        params = {
            "url": "https://api.example.com",
            "body": {
                "channel": "${channel}",
                "text": "${message}",
                "metadata": {
                    "channel_id": "${channel}",  # Nested template in body
                    "static": "value",
                },
            },
        }

        result = _apply_template_wrapping(node, node_id, params, initial_params)

        # Must be wrapped for body templates
        assert isinstance(result, TemplateAwareNodeWrapper)


class TestTemplateWrappingIntegration:
    """Integration tests for template wrapping in the compilation process."""

    def test_wrapped_node_receives_params_correctly(self):
        """Test that wrapped nodes receive and store params correctly."""

        # Create a real node class for testing
        class TestNode(BaseNode):
            def __init__(self):
                super().__init__()
                self.params = {}

            def set_params(self, params):
                self.params = params

        node = TestNode()
        node_id = "test"
        initial_params = {"key": "value"}

        params_with_templates = {"headers": {"Auth": "Bearer ${key}"}}

        # Apply wrapping
        wrapped = _apply_template_wrapping(node, node_id, params_with_templates, initial_params)

        # Verify it's wrapped
        assert isinstance(wrapped, TemplateAwareNodeWrapper)

        # Set params on the wrapper
        wrapped.set_params(params_with_templates)

        # Verify the wrapper categorized them correctly
        assert "headers" in wrapped.template_params
        assert wrapped.template_params["headers"] == {"Auth": "Bearer ${key}"}

    def test_no_wrapping_means_direct_param_setting(self):
        """Test that unwrapped nodes get params directly."""

        class TestNode(BaseNode):
            def __init__(self):
                super().__init__()
                self.params = {}

            def set_params(self, params):
                self.params = params

        node = TestNode()
        node_id = "test"
        initial_params = {}

        params_no_templates = {"url": "https://api.example.com", "timeout": 30}

        # Apply wrapping (should not wrap)
        result = _apply_template_wrapping(node, node_id, params_no_templates, initial_params)

        # Should be the same node
        assert result is node

        # Set params directly
        result.set_params(params_no_templates)
        assert result.params == params_no_templates
