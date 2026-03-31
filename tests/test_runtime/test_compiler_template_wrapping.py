"""Test that compiler properly detects templates in nested params.

This test validates that split_params() correctly classifies params with
templates in nested structures (dicts, lists) as template_params, ensuring
they'll be resolved at runtime by the engine.
"""

from pflow.runtime.engine.template_resolution import build_type_cache, split_params


class TestTemplateDetection:
    """Test that split_params correctly separates template vs static params."""

    def test_detects_nested_dict_templates(self):
        """Params with templates in nested dicts are classified as template_params."""
        params = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer ${token}",
                "Content-Type": "application/json",
            },
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "headers" in template_params
        assert "url" in static_params

    def test_detects_nested_list_templates(self):
        """Params with templates in lists are classified as template_params."""
        params = {
            "items": ["${item1}", "static", "${item2}"],
            "config": {"enabled": True},
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "items" in template_params
        assert "config" in static_params

    def test_detects_deeply_nested_templates(self):
        """Deeply nested templates are detected."""
        params = {"config": {"level1": {"level2": {"level3": {"value": "${deep_value}"}}}}}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "config" in template_params
        assert len(static_params) == 0

    def test_no_templates_all_static(self):
        """Params without templates are all classified as static."""
        params = {
            "url": "https://api.example.com",
            "headers": {"Authorization": "Bearer hardcoded_token"},
            "items": ["a", "b", "c"],
            "config": {"enabled": True, "timeout": 30},
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert len(template_params) == 0
        assert len(static_params) == 4

    def test_simple_string_templates(self):
        """Simple string templates are detected."""
        params = {"message": "Hello ${name}!", "static": "no template here"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "message" in template_params
        assert "static" in static_params

    def test_mixed_nested_and_simple_templates(self):
        """Mixed template types are all detected."""
        params = {
            "greeting": "Hello ${user}!",
            "headers": {"Authorization": "Bearer ${token}"},
            "tags": ["${user}", "active"],
            "static_value": 42,
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "greeting" in template_params
        assert "headers" in template_params
        assert "tags" in template_params
        assert "static_value" in static_params

    def test_empty_params(self):
        """Empty params produce empty splits."""
        expected_types = build_type_cache(None)
        template_params, static_params = split_params({}, expected_types)

        assert len(template_params) == 0
        assert len(static_params) == 0

    def test_numeric_boolean_params_not_templates(self):
        """Numeric/boolean params are not templates."""
        params = {
            "timeout": 30,
            "retries": 3,
            "enabled": True,
            "threshold": 0.95,
            "config": {"max_size": 1000, "active": False},
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert len(template_params) == 0
        assert len(static_params) == 5

    def test_real_world_slack_scenario(self):
        """The exact Slack scenario that originally triggered the bug."""
        params = {
            "url": "https://slack.com/api/conversations.history",
            "method": "GET",
            "params": {"channel": "${slack_channel_id}", "limit": "${message_count}"},
            "headers": {"Authorization": "Bearer ${slack_bot_token}"},
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "params" in template_params
        assert "headers" in template_params
        assert "url" in static_params
        assert "method" in static_params

    def test_body_with_nested_template_objects(self):
        """HTTP body with nested template objects detected."""
        params = {
            "url": "https://api.example.com",
            "body": {
                "channel": "${channel}",
                "text": "${message}",
                "metadata": {
                    "channel_id": "${channel}",
                    "static": "value",
                },
            },
        }
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert "body" in template_params
        assert "url" in static_params


class TestSplitParamsIntegration:
    """Integration tests for split_params with type coercion."""

    def test_static_params_preserve_types(self):
        """Static params preserve their original types."""
        params = {"url": "https://api.example.com", "timeout": 30}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert static_params["url"] == "https://api.example.com"
        assert static_params["timeout"] == 30
        assert len(template_params) == 0
