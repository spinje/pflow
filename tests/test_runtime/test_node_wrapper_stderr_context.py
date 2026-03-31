"""Tests for upstream stderr context in template resolution errors.

This test validates that when template resolution encounters type validation
errors or unresolved template errors, the error message includes upstream
shell node stderr to help diagnose the root cause.

Migrated from TemplateAwareNodeWrapper tests to use standalone functions
in pflow.runtime.engine.template_resolution.

Related bug: Shell node stderr not surfaced in error messages
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
    node_id: str = "test-node",
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


class TestUpstreamStderr:
    """Test template resolution includes upstream stderr in error messages."""

    def test_unresolved_template_includes_upstream_stderr(self):
        """Unresolved template error should include upstream shell stderr."""
        shared = {
            "shell-node": {
                "stdout": "",
                "stderr": "Error: command failed silently",
                "exit_code": 0,
            }
        }

        # The resolve should raise ValueError with upstream stderr context
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"data": "${shell-node.nonexistent}"},
                shared,
            )

        error_message = str(exc_info.value)
        # Should mention unresolved template
        assert "nonexistent" in error_message or "${" in error_message
        # Should include upstream stderr
        assert "shell-node" in error_message
        assert "command failed silently" in error_message

    def test_no_stderr_context_when_upstream_has_no_stderr(self):
        """No upstream context should appear when shell has no stderr."""
        shared = {
            "shell-node": {
                "stdout": "some output",
                "stderr": "",  # No stderr
                "exit_code": 0,
            }
        }

        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"data": "${shell-node.missing}"},
                shared,
            )

        error_message = str(exc_info.value)
        # Should NOT have upstream context section (since no stderr)
        assert "Upstream node" not in error_message
