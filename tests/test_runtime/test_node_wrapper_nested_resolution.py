"""Test that template resolution properly resolves nested templates.

This test verifies that nested template structures (dicts and lists containing
${...} templates) are properly resolved. Migrated from TemplateAwareNodeWrapper
tests to use standalone functions in pflow.runtime.engine.template_resolution.
"""

import pytest

from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    resolve_templates,
    split_params,
)
from pflow.runtime.engine.types import TemplateConfig


def _resolve(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
    node_id: str = "test_node",
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


class TestNodeWrapperNestedResolution:
    """Test runtime resolution of nested templates."""

    def test_resolves_nested_dict_templates_at_runtime(self):
        """Test that nested dict templates are resolved."""
        shared = {"api_token": "xoxb-123456", "channel_id": "C09C16NAU5B"}

        params = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer ${api_token}",
                "X-Channel-ID": "${channel_id}",
                "Content-Type": "application/json",  # Static value
            },
        }

        result = _resolve(params, shared)

        assert result["url"] == "https://api.example.com"
        assert result["headers"]["Authorization"] == "Bearer xoxb-123456"
        assert result["headers"]["X-Channel-ID"] == "C09C16NAU5B"
        assert result["headers"]["Content-Type"] == "application/json"

    def test_resolves_nested_list_templates_at_runtime(self):
        """Test that list templates are resolved."""
        shared = {"item1": "apple", "item2": "banana", "item3": "cherry"}

        params = {
            "items": ["${item1}", "static_value", "${item2}"],
            "nested_items": [["${item1}", "${item3}"], {"key": "${item2}"}],
        }

        result = _resolve(params, shared)

        assert result["items"] == ["apple", "static_value", "banana"]
        assert result["nested_items"][0] == ["apple", "cherry"]
        assert result["nested_items"][1]["key"] == "banana"

    def test_resolves_deeply_nested_templates_at_runtime(self):
        """Test resolution of deeply nested structures."""
        shared = {"deep_value": "found_me", "another_value": "also_found"}

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

        result = _resolve(params, shared)

        level3 = result["config"]["level1"]["level2"]["level3"]
        assert level3["value"] == "found_me"
        assert level3["items"] == ["also_found", "static"]
        assert level3["meta"]["ref"] == "found_me"

    def test_preserves_non_template_types(self):
        """Test that non-template values keep their types."""
        shared = {"name": "test"}

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

        result = _resolve(params, shared)

        assert result["message"] == "Hello test"
        assert result["count"] == 42
        assert isinstance(result["count"], int)
        assert result["enabled"] is True
        assert isinstance(result["enabled"], bool)

        # Check list items
        assert result["items"] == ["test", 123, False, None]
        assert isinstance(result["items"][1], int)
        assert isinstance(result["items"][2], bool)
        assert result["items"][3] is None

        # Check nested config
        assert result["config"]["name"] == "test"
        assert result["config"]["size"] == 100
        assert isinstance(result["config"]["size"], int)
        assert result["config"]["active"] is False

    def test_handles_missing_template_variables(self):
        """Test that missing template variables raise ValueError (Issue #95 fix)."""
        shared = {"exists": "yes"}

        params = {"headers": {"X-Exists": "${exists}", "X-Missing": "${does_not_exist}"}}

        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(params, shared)

    def test_real_world_http_scenario(self):
        """Test the exact HTTP scenario that was failing."""
        shared = {
            "slack_channel_id": "C09C16NAU5B",
            "message_count": 10,
            "slack_bot_token": "xoxb-123456789",
            "api_endpoint": "https://slack.com/api/conversations.history",
        }

        params = {
            "url": "${api_endpoint}",
            "method": "GET",
            "params": {"channel": "${slack_channel_id}", "limit": "${message_count}"},
            "headers": {"Authorization": "Bearer ${slack_bot_token}", "Content-Type": "application/json"},
        }

        result = _resolve(params, shared, node_id="api_call")

        assert result["url"] == "https://slack.com/api/conversations.history"
        assert result["method"] == "GET"
        assert result["params"]["channel"] == "C09C16NAU5B"
        # Simple templates now preserve original type (int stays int)
        assert result["params"]["limit"] == 10
        assert result["headers"]["Authorization"] == "Bearer xoxb-123456789"
        assert result["headers"]["Content-Type"] == "application/json"

    def test_shared_store_values_resolved(self):
        """Test that shared store values are resolved correctly.

        initial_params override behavior is removed. Values come from shared store.
        """
        shared = {"value": "from_shared"}
        params = {"config": {"setting": "${value}"}}

        result = _resolve(params, shared)

        assert result["config"]["setting"] == "from_shared"

    def test_complex_mixed_scenario(self):
        """Test complex scenario with all types of nesting."""
        shared = {"auth": "secret123", "endpoint": "users", "page": 1, "active": True}

        params = {
            "url": "https://api.example.com/${endpoint}",
            "auth": {"type": "bearer", "token": "${auth}"},
            "query": {"page": "${page}", "active": "${active}", "filters": ["${endpoint}", "published"]},
            "body": {"data": {"items": [{"type": "${endpoint}", "page": "${page}"}, {"type": "static", "page": 0}]}},
        }

        result = _resolve(params, shared, node_id="complex")

        assert result["url"] == "https://api.example.com/users"
        assert result["auth"]["token"] == "secret123"  # noqa: S105 - Test data, not real credentials
        # Simple templates now preserve original types (int stays int, bool stays bool)
        assert result["query"]["page"] == 1
        assert result["query"]["active"] is True  # Boolean preserved
        assert result["query"]["filters"] == ["users", "published"]
        assert result["body"]["data"]["items"][0] == {"type": "users", "page": 1}
        assert result["body"]["data"]["items"][1] == {"type": "static", "page": 0}
