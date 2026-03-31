"""Tests for template resolution standalone functions.

Migrated from TemplateAwareNodeWrapper tests to use the standalone functions
in pflow.runtime.engine.template_resolution. The wrapper class is removed;
template resolution is now a pure function called by the engine.
"""

import pytest

from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    contains_unresolved_template,
    resolve_templates,
    split_params,
)
from pflow.runtime.engine.types import TemplateConfig


def _resolve(
    params: dict,
    shared: dict,
    node_id: str = "test_node",
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
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


class TestParameterSeparation:
    """Test separation of template and static parameters."""

    def test_separates_template_params(self):
        """Test that params with templates are separated."""
        params = {"url": "${endpoint}", "format": "json", "message": "Processing ${count} items"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert template_params == {"url": "${endpoint}", "message": "Processing ${count} items"}
        assert static_params == {"format": "json"}

    def test_all_static_params(self):
        """Test handling when all params are static."""
        params = {"format": "json", "count": 10, "enabled": True}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert template_params == {}
        assert static_params == params

    def test_all_template_params(self):
        """Test handling when all params have templates."""
        params = {"url": "${endpoint}", "token": "${auth_token}", "id": "${item_id}"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        assert template_params == params
        assert static_params == {}

    def test_updates_params_on_subsequent_calls(self):
        """Test that split_params can be called with different params."""
        expected_types = build_type_cache(None)

        # First set
        tp1, sp1 = split_params({"a": "${var1}", "b": "static1"}, expected_types)
        assert tp1 == {"a": "${var1}"}
        assert sp1 == {"b": "static1"}

        # Second set (independent call)
        tp2, sp2 = split_params({"c": "${var2}", "d": "static2"}, expected_types)
        assert tp2 == {"c": "${var2}"}
        assert sp2 == {"d": "static2"}


class TestTemplateResolution:
    """Test template resolution during execution."""

    def test_no_templates_bypasses_resolution(self):
        """Test that execution without templates bypasses resolution."""
        result = _resolve({"format": "json", "count": 10}, {"some_data": "value"})
        assert result == {"format": "json", "count": 10}

    def test_resolves_simple_templates(self):
        """Test resolution of simple template variables."""
        shared = {"endpoint": "https://api.example.com"}
        result = _resolve({"url": "${endpoint}", "format": "json"}, shared)

        assert result["url"] == "https://api.example.com"
        assert result["format"] == "json"

    def test_shared_store_resolution(self):
        """Test resolution from shared store."""
        shared = {"item_name": "Document.pdf"}
        result = _resolve({"message": "Processing ${item_name}"}, shared)

        assert result["message"] == "Processing Document.pdf"

    def test_shared_store_values_resolved(self):
        """Test that values in shared store are resolved correctly.

        initial_params override behavior is removed. Values come from shared store only.
        """
        shared = {"count": "50"}
        result = _resolve({"message": "Count: ${count}"}, shared)

        assert result["message"] == "Count: 50"

    def test_path_resolution(self):
        """Test resolution of nested paths."""
        shared = {"video": {"title": "Python Tutorial", "metadata": {"author": "TechTeacher", "duration": 3600}}}
        result = _resolve(
            {"title": "${video.title}", "author": "${video.metadata.author}"},
            shared,
        )

        assert result["title"] == "Python Tutorial"
        assert result["author"] == "TechTeacher"

    def test_unresolved_templates_raise_error(self):
        """Test that unresolved templates raise ValueError (Issue #95 fix).

        Unresolved templates correctly raise ValueError to prevent data corruption.
        """
        shared = {"existing": "value"}
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve({"found": "${existing}", "missing": "${undefined}"}, shared)


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_multiple_template_resolution(self):
        """Test resolution of multiple templates in one parameter."""
        shared = {"repo": "pflow", "issue": "123", "status": "in_progress"}
        result = _resolve(
            {
                "message": "Working on ${repo} issue #${issue}",
                "url": "https://github.com/${repo}/issues/${issue}",
            },
            shared,
        )

        assert result["message"] == "Working on pflow issue #123"
        assert result["url"] == "https://github.com/pflow/issues/123"

    def test_complete_vs_embedded_templates(self):
        """Test that complete value templates work same as embedded."""
        shared = {"video_id": "xyz123"}
        result = _resolve(
            {
                "id": "${video_id}",  # Complete value
                "message": "Processing video ${video_id}",  # Embedded in string
            },
            shared,
        )

        assert result["id"] == "xyz123"
        assert result["message"] == "Processing video xyz123"

    def test_type_conversion_in_templates(self):
        """Test type conversion during template resolution."""
        shared = {"none": None, "zero": 0, "flag": False}
        result = _resolve(
            {"none_val": "Value: ${none}", "zero_val": "Count: ${zero}", "bool_val": "Flag: ${flag}"},
            shared,
        )

        assert result["none_val"] == "Value: "  # None -> ""
        assert result["zero_val"] == "Count: 0"
        assert result["bool_val"] == "Flag: False"


class TestErrorHandling:
    """Test error handling in template resolution."""

    def test_handles_non_string_param_values(self):
        """Test handling of non-string parameter values."""
        params = {"string": "${var}", "number": 42, "boolean": True, "list": [1, 2, 3], "dict": {"key": "value"}}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        # Only string should be in template_params
        assert template_params == {"string": "${var}"}
        assert len(static_params) == 4


class TestContainsUnresolvedTemplate:
    """Test the contains_unresolved_template helper function."""

    def test_fully_resolved(self):
        """Fully resolved string should return False."""
        assert contains_unresolved_template("hello world", "hello world") is False

    def test_unresolved_simple(self):
        """Unresolved simple template should return True."""
        assert contains_unresolved_template("${missing}", "${missing}") is True

    def test_partially_resolved(self):
        """Partially resolved string should return True if original vars remain."""
        # resolved_value still has ${count} which was in the original
        assert (
            contains_unresolved_template(
                "Hello Alice, you have ${count} items",
                "Hello ${name}, you have ${count} items",
            )
            is True
        )

    def test_resolved_data_with_dollar_sign(self):
        """Data containing ${...} from resolved content should NOT be flagged."""
        # The resolved value has a different ${...} than the original template
        mcp_result = {"message": "The old format used ${OLD_VAR} syntax"}
        assert contains_unresolved_template(mcp_result, "${mcp.result}") is False
