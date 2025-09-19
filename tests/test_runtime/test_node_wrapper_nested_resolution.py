"""Test that TemplateAwareNodeWrapper properly resolves nested templates at runtime.

This test verifies that when a wrapped node executes, the nested template
structures are properly resolved before being passed to the inner node.
"""

from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper
from pocketflow import BaseNode


class MockNode(BaseNode):
    """Mock node that captures params at execution time."""

    def __init__(self):
        super().__init__()
        self.params = {}
        self.exec_params = None  # Will capture params during exec

    def set_params(self, params):
        self.params = params

    def prep(self, shared):
        return {"params": self.params}

    def exec(self, prep_res):
        # Capture the params we receive during execution
        self.exec_params = prep_res.get("params", {})
        return {"result": "success"}

    def post(self, shared, prep_res, exec_res):
        shared["result"] = exec_res["result"]
        return "default"


class TestNodeWrapperNestedResolution:
    """Test runtime resolution of nested templates in node wrapper."""

    def test_resolves_nested_dict_templates_at_runtime(self):
        """Test that nested dict templates are resolved during execution."""
        # Create node and wrapper
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        # Set initial params for template resolution
        wrapper.initial_params = {"api_token": "xoxb-123456", "channel_id": "C09C16NAU5B"}

        # Set params with nested templates
        params = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer ${api_token}",
                "X-Channel-ID": "${channel_id}",
                "Content-Type": "application/json",  # Static value
            },
        }

        wrapper.set_params(params)

        # Verify wrapper detected templates
        assert "headers" in wrapper.template_params

        # Execute the wrapper (simulates runtime)
        shared = {}
        wrapper._run(shared)

        # Check what params the inner node actually received
        assert node.exec_params is not None
        assert node.exec_params["url"] == "https://api.example.com"
        assert node.exec_params["headers"]["Authorization"] == "Bearer xoxb-123456"
        assert node.exec_params["headers"]["X-Channel-ID"] == "C09C16NAU5B"
        assert node.exec_params["headers"]["Content-Type"] == "application/json"

    def test_resolves_nested_list_templates_at_runtime(self):
        """Test that list templates are resolved during execution."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        wrapper.initial_params = {"item1": "apple", "item2": "banana", "item3": "cherry"}

        params = {
            "items": ["${item1}", "static_value", "${item2}"],
            "nested_items": [["${item1}", "${item3}"], {"key": "${item2}"}],
        }

        wrapper.set_params(params)

        # Execute
        shared = {}
        wrapper._run(shared)

        # Verify resolution
        assert node.exec_params["items"] == ["apple", "static_value", "banana"]
        assert node.exec_params["nested_items"][0] == ["apple", "cherry"]
        assert node.exec_params["nested_items"][1]["key"] == "banana"

    def test_resolves_deeply_nested_templates_at_runtime(self):
        """Test resolution of deeply nested structures."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        wrapper.initial_params = {"deep_value": "found_me", "another_value": "also_found"}

        params = {
            "config": {
                "level1": {
                    "level2": {
                        "level3": {
                            "value": "${deep_value}",
                            "items": ["${another_value}", "static"],
                            "meta": {"ref": "${deep_value}"},
                        }
                    }
                }
            }
        }

        wrapper.set_params(params)

        # Execute
        shared = {}
        wrapper._run(shared)

        # Verify deep resolution
        level3 = node.exec_params["config"]["level1"]["level2"]["level3"]
        assert level3["value"] == "found_me"
        assert level3["items"] == ["also_found", "static"]
        assert level3["meta"]["ref"] == "found_me"

    def test_preserves_non_template_types(self):
        """Test that non-template values keep their types."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        wrapper.initial_params = {"name": "test"}

        params = {
            "message": "Hello ${name}",  # String template
            "count": 42,  # Integer - should stay integer
            "enabled": True,  # Boolean - should stay boolean
            "items": ["${name}", 123, False, None],  # Mixed types in list
            "config": {
                "name": "${name}",
                "size": 100,  # Should stay integer
                "active": False,  # Should stay boolean
            },
        }

        wrapper.set_params(params)

        # Execute
        shared = {}
        wrapper._run(shared)

        # Verify types are preserved
        assert node.exec_params["message"] == "Hello test"
        assert node.exec_params["count"] == 42
        assert isinstance(node.exec_params["count"], int)
        assert node.exec_params["enabled"] is True
        assert isinstance(node.exec_params["enabled"], bool)

        # Check list items
        assert node.exec_params["items"] == ["test", 123, False, None]
        assert isinstance(node.exec_params["items"][1], int)
        assert isinstance(node.exec_params["items"][2], bool)
        assert node.exec_params["items"][3] is None

        # Check nested config
        assert node.exec_params["config"]["name"] == "test"
        assert node.exec_params["config"]["size"] == 100
        assert isinstance(node.exec_params["config"]["size"], int)
        assert node.exec_params["config"]["active"] is False

    def test_handles_missing_template_variables(self):
        """Test that missing template variables remain unresolved."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        wrapper.initial_params = {"exists": "yes"}

        params = {"headers": {"X-Exists": "${exists}", "X-Missing": "${does_not_exist}"}}

        wrapper.set_params(params)

        # Execute
        shared = {}
        wrapper._run(shared)

        # Existing variable should be resolved
        assert node.exec_params["headers"]["X-Exists"] == "yes"
        # Missing variable should remain as template
        assert node.exec_params["headers"]["X-Missing"] == "${does_not_exist}"

    def test_real_world_http_scenario(self):
        """Test the exact HTTP scenario that was failing."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="api_call")

        # Real-world initial params
        wrapper.initial_params = {
            "slack_channel_id": "C09C16NAU5B",
            "message_count": 10,
            "slack_bot_token": "xoxb-123456789",
            "api_endpoint": "https://slack.com/api/conversations.history",
        }

        # Real-world nested params structure
        params = {
            "url": "${api_endpoint}",
            "method": "GET",
            "params": {"channel": "${slack_channel_id}", "limit": "${message_count}"},
            "headers": {"Authorization": "Bearer ${slack_bot_token}", "Content-Type": "application/json"},
        }

        wrapper.set_params(params)

        # Execute
        shared = {}
        wrapper._run(shared)

        # Verify complete resolution
        assert node.exec_params["url"] == "https://slack.com/api/conversations.history"
        assert node.exec_params["method"] == "GET"
        assert node.exec_params["params"]["channel"] == "C09C16NAU5B"
        # Template resolution converts numbers to strings when in nested structures
        assert node.exec_params["params"]["limit"] == "10"
        assert node.exec_params["headers"]["Authorization"] == "Bearer xoxb-123456789"
        assert node.exec_params["headers"]["Content-Type"] == "application/json"

    def test_initial_params_override_shared_store(self):
        """Test that initial params (planner parameters) have higher priority than shared store."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="test_node")

        wrapper.initial_params = {"value": "from_initial"}

        params = {"config": {"setting": "${value}"}}

        wrapper.set_params(params)

        # Execute with value in shared store
        shared = {"value": "from_shared"}
        wrapper._run(shared)

        # Initial params should override shared store (by design)
        assert node.exec_params["config"]["setting"] == "from_initial"

    def test_complex_mixed_scenario(self):
        """Test complex scenario with all types of nesting."""
        node = MockNode()
        wrapper = TemplateAwareNodeWrapper(node, node_id="complex")

        wrapper.initial_params = {"auth": "secret123", "endpoint": "users", "page": 1, "active": True}

        params = {
            "url": "https://api.example.com/${endpoint}",
            "auth": {"type": "bearer", "token": "${auth}"},
            "query": {"page": "${page}", "active": "${active}", "filters": ["${endpoint}", "published"]},
            "body": {"data": {"items": [{"type": "${endpoint}", "page": "${page}"}, {"type": "static", "page": 0}]}},
        }

        wrapper.set_params(params)

        # Execute
        shared = {}
        wrapper._run(shared)

        # Verify all resolutions
        assert node.exec_params["url"] == "https://api.example.com/users"
        assert node.exec_params["auth"]["token"] == "secret123"  # noqa: S105 - Test data, not real credentials
        # Template resolution converts to strings
        assert node.exec_params["query"]["page"] == "1"
        assert node.exec_params["query"]["active"] == "True"  # Boolean becomes string
        assert node.exec_params["query"]["filters"] == ["users", "published"]
        assert node.exec_params["body"]["data"]["items"][0] == {"type": "users", "page": "1"}
        assert node.exec_params["body"]["data"]["items"][1] == {"type": "static", "page": 0}
