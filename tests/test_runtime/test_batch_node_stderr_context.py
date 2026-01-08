"""Tests for upstream stderr context in batch node errors.

This test validates that when a batch node fails because an upstream shell node
produced invalid output, the error message includes the upstream node's stderr
to help diagnose the root cause.

Related bug: Shell node stderr not surfaced in error messages
"""

import pytest

from pflow.runtime.batch_node import PflowBatchNode
from pflow.runtime.error_context import (
    extract_node_ids_from_template,
    get_upstream_shell_stderr,
)


class TestExtractNodeIds:
    """Test extract_node_ids_from_template utility."""

    def test_simple_template(self):
        """Extract node ID from simple template."""
        result = extract_node_ids_from_template("${node.stdout}")
        assert result == {"node"}

    def test_multiple_templates(self):
        """Extract multiple node IDs from template with multiple references."""
        result = extract_node_ids_from_template("${a.x} and ${b.y}")
        assert result == {"a", "b"}

    def test_array_access(self):
        """Extract node ID from template with array access."""
        result = extract_node_ids_from_template("${data[0].name}")
        assert result == {"data"}

    def test_hyphenated_node_id(self):
        """Extract hyphenated node ID (common in pflow)."""
        result = extract_node_ids_from_template("${extract-urls.stdout}")
        assert result == {"extract-urls"}

    def test_no_templates(self):
        """Return empty set when no templates present."""
        result = extract_node_ids_from_template("plain text")
        assert result == set()


class TestGetUpstreamShellStderr:
    """Test get_upstream_shell_stderr utility."""

    def test_returns_stderr_from_referenced_node(self):
        """Returns stderr when referenced shell node has non-empty stderr."""
        shared = {
            "shell-node": {
                "stdout": "",
                "stderr": "grep: invalid option -- P",
                "exit_code": 0,
            }
        }
        template = "${shell-node.stdout}"

        result = get_upstream_shell_stderr(template, shared)

        assert result is not None
        assert "shell-node" in result
        assert "grep: invalid option" in result

    def test_returns_none_when_no_stderr(self):
        """Returns None when referenced node has no stderr."""
        shared = {
            "shell-node": {
                "stdout": "some output",
                "stderr": "",
                "exit_code": 0,
            }
        }
        template = "${shell-node.stdout}"

        result = get_upstream_shell_stderr(template, shared)

        assert result is None

    def test_returns_none_when_node_not_found(self):
        """Returns None when referenced node doesn't exist in shared store."""
        shared = {}
        template = "${missing-node.stdout}"

        result = get_upstream_shell_stderr(template, shared)

        assert result is None

    def test_only_referenced_node_stderr(self):
        """Only shows stderr from nodes referenced in template, not all nodes."""
        shared = {
            "node-a": {
                "stdout": "output",
                "stderr": "ERROR FROM NODE-A - should NOT appear",
            },
            "node-b": {
                "stdout": "",
                "stderr": "ERROR FROM NODE-B - SHOULD appear",
            },
        }
        # Template only references node-b
        template = "${node-b.stdout}"

        result = get_upstream_shell_stderr(template, shared)

        assert result is not None
        assert "node-b" in result
        assert "ERROR FROM NODE-B" in result
        assert "node-a" not in result
        assert "ERROR FROM NODE-A" not in result

    def test_truncates_long_stderr(self):
        """Truncates stderr that exceeds max length."""
        long_stderr = "X" * 600
        shared = {
            "shell-node": {
                "stdout": "",
                "stderr": long_stderr,
            }
        }
        template = "${shell-node.stdout}"

        result = get_upstream_shell_stderr(template, shared, max_stderr_len=500)

        assert result is not None
        assert "..." in result
        assert len(result) < len(long_stderr) + 100  # Reasonable length with formatting


class TestBatchNodeUpstreamStderr:
    """Test batch node includes upstream stderr in error messages."""

    def test_batch_error_includes_upstream_stderr(self):
        """When batch fails due to empty upstream output, error includes stderr."""
        # Create a mock inner node
        from pocketflow import Node

        class MockNode(Node):
            def exec(self, prep_res):
                return {"result": "ok"}

        inner_node = MockNode()
        batch_config = {"items": "${shell-node.stdout}"}
        batch_node = PflowBatchNode(
            inner_node=inner_node,
            node_id="test-batch",
            batch_config=batch_config,
        )

        # Shared store simulates shell node that failed (stderr) but exited 0
        shared = {
            "shell-node": {
                "stdout": "",  # Empty - will cause batch to fail
                "stderr": "grep: invalid option -- P\nusage: grep ...",
                "exit_code": 0,
                "command": "grep -oP 'pattern' || true",
            }
        }

        # batch.prep() should raise TypeError with upstream stderr context
        with pytest.raises(TypeError) as exc_info:
            batch_node.prep(shared)

        error_message = str(exc_info.value)
        assert "Batch items must be an array" in error_message
        assert "shell-node" in error_message
        assert "grep: invalid option" in error_message

    def test_batch_error_without_upstream_stderr_is_clean(self):
        """When upstream has no stderr, error message is clean (no extra context)."""
        from pocketflow import Node

        class MockNode(Node):
            def exec(self, prep_res):
                return {"result": "ok"}

        inner_node = MockNode()
        batch_config = {"items": "${shell-node.stdout}"}
        batch_node = PflowBatchNode(
            inner_node=inner_node,
            node_id="test-batch",
            batch_config=batch_config,
        )

        # Shell node with empty stdout but no stderr
        shared = {
            "shell-node": {
                "stdout": "",
                "stderr": "",  # No stderr
                "exit_code": 0,
            }
        }

        with pytest.raises(TypeError) as exc_info:
            batch_node.prep(shared)

        error_message = str(exc_info.value)
        assert "Batch items must be an array" in error_message
        # Should NOT have upstream context section
        assert "Upstream node" not in error_message

    def test_batch_none_error_includes_upstream_stderr(self):
        """When template resolves to None, error includes upstream stderr."""
        from pocketflow import Node

        class MockNode(Node):
            def exec(self, prep_res):
                return {"result": "ok"}

        inner_node = MockNode()
        batch_config = {"items": "${shell-node.result}"}  # Accessing non-existent field
        batch_node = PflowBatchNode(
            inner_node=inner_node,
            node_id="test-batch",
            batch_config=batch_config,
        )

        shared = {
            "shell-node": {
                "stdout": "",
                "stderr": "Command failed silently",
                "exit_code": 0,
            }
        }

        with pytest.raises(ValueError) as exc_info:
            batch_node.prep(shared)

        error_message = str(exc_info.value)
        assert "resolved to None" in error_message
        assert "shell-node" in error_message
        assert "Command failed silently" in error_message
