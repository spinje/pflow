"""Tests for upstream stderr context in node wrapper type errors.

This test validates that when a node wrapper encounters type validation errors
or unresolved template errors, the error message includes upstream shell node
stderr to help diagnose the root cause.

Related bug: Shell node stderr not surfaced in error messages
"""

import pytest

from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper


class TestNodeWrapperUpstreamStderr:
    """Test node wrapper includes upstream stderr in error messages."""

    def test_unresolved_template_includes_upstream_stderr(self):
        """Unresolved template error should include upstream shell stderr."""
        from pflow.pocketflow import Node

        class MockNode(Node):
            def exec(self, prep_res):
                return {"result": "ok"}

        inner_node = MockNode()

        # Create wrapper
        wrapper = TemplateAwareNodeWrapper(
            inner_node=inner_node,
            node_id="test-node",
            initial_params={},
        )
        # Set params with template referencing non-existent field
        wrapper.set_params({"data": "${shell-node.nonexistent}"})

        # Shell node exists but doesn't have the 'nonexistent' field
        shared = {
            "shell-node": {
                "stdout": "",
                "stderr": "Error: command failed silently",
                "exit_code": 0,
            }
        }

        # The wrapper should raise ValueError with upstream stderr context
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_message = str(exc_info.value)
        # Should mention unresolved template
        assert "nonexistent" in error_message or "${" in error_message
        # Should include upstream stderr
        assert "shell-node" in error_message
        assert "command failed silently" in error_message

    def test_no_stderr_context_when_upstream_has_no_stderr(self):
        """No upstream context should appear when shell has no stderr."""
        from pflow.pocketflow import Node

        class MockNode(Node):
            def exec(self, prep_res):
                return {"result": "ok"}

        inner_node = MockNode()

        wrapper = TemplateAwareNodeWrapper(
            inner_node=inner_node,
            node_id="test-node",
            initial_params={},
        )
        # Set params with template referencing missing field
        wrapper.set_params({"data": "${shell-node.missing}"})

        # Shell node with no stderr
        shared = {
            "shell-node": {
                "stdout": "some output",
                "stderr": "",  # No stderr
                "exit_code": 0,
            }
        }

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_message = str(exc_info.value)
        # Should NOT have upstream context section (since no stderr)
        assert "Upstream node" not in error_message
