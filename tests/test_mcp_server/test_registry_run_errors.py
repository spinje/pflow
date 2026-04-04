"""Tests for registry_run error handling.

This module tests that registry_run returns formatted error strings instead of dicts,
ensuring Pydantic validation passes for all error cases.

Critical: These tests guard against the bug where registry_run returned dict on error,
causing Pydantic validation failures in MCP tool layer.
"""

import pytest

from pflow.mcp_server.services.execution_service import ExecutionService


class TestRegistryRunErrorFormat:
    """Test that all error paths return formatted strings, not dicts."""

    def test_nonexistent_node_returns_string_not_dict(self):
        """CRITICAL BUG GUARD: Returns string on 'node not found' error.

        This test catches the bug where ExecutionService.run_registry_node()
        returned dict instead of string for nonexistent nodes, causing:

        1 validation error for registry_runOutput
        result
          Input should be a valid string [type=string_type, input_value={'success': False, ...}]

        The service MUST return formatted strings for all cases to match
        the MCP tool return type declaration (-> str).
        """
        result = ExecutionService.run_registry_node("nonexistent-node-12345")

        # MUST be string, not dict
        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"

        # Should contain helpful error message
        assert "not found" in result.lower()
        assert "nonexistent-node-12345" in result

    def test_nonexistent_node_with_suggestions_returns_string(self):
        """Returns string with helpful guidance even when no exact matches found."""
        # Test with a non-matching name
        result = ExecutionService.run_registry_node("read-fle")

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert "not found" in result.lower()
        assert "read-fle" in result
        # Should include helpful guidance (rendered via format_diagnostic suggestions)
        assert "registry" in result.lower()

    def test_execution_error_returns_string_not_dict(self):
        """CRITICAL BUG GUARD: Returns string on execution exception.

        Tests the second error path where node exists but execution fails
        (e.g., missing required parameters). Must return string, not dict.
        """
        # Use a node that requires parameters but don't provide them
        result = ExecutionService.run_registry_node("read-file")  # Missing file_path param

        # MUST be string, not dict
        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"

        # Should contain error indication
        assert "❌" in result or "error" in result.lower() or "failed" in result.lower()

    def test_error_messages_are_helpful(self):
        """Error strings contain actionable guidance."""
        result = ExecutionService.run_registry_node("totally-fake-node")

        assert isinstance(result, str)
        # Should tell user how to find valid nodes (via diagnostic suggestions)
        assert "registry" in result.lower()

    def test_error_format_uses_diagnostic_style(self):
        """Node-not-found errors use diagnostic format with title and suggestions.

        After diagnostic rendering redesign (Task 144), node-not-found errors
        use format_diagnostic() which renders 'Error: Node Not Found' instead
        of the old '❌ Node not found' prefix.
        """
        result = ExecutionService.run_registry_node("bad-node")

        assert isinstance(result, str)
        assert "not found" in result.lower()
        # Diagnostic format uses titled error blocks
        assert "Node Not Found" in result


class TestRegistryRunReturnTypeConsistency:
    """Verify return type consistency across all code paths.

    This is the critical test - all paths must return str, never dict.
    """

    @pytest.mark.parametrize(
        "node_type,parameters,expected_indicator",
        [
            ("nonexistent-fake-node-xyz", None, "not found"),  # Error: node doesn't exist
            ("read-file", None, "error"),  # Error: missing required param (diagnostic format)
            ("another-fake-xyz", None, "not found"),  # Error: node doesn't exist (no suggestions)
        ],
    )
    def test_all_error_paths_return_string_type(self, node_type, parameters, expected_indicator):
        """All error paths return str, never dict.

        This is the CRITICAL test for the bug fix. Before the fix, error
        paths returned dict which caused Pydantic validation failures:

            1 validation error for registry_runOutput
            result
              Input should be a valid string [type=string_type, ...]

        After the fix, ALL paths (error and success) return formatted strings.
        """
        result = ExecutionService.run_registry_node(node_type, parameters=parameters)

        # TYPE CHECK - this is the critical assertion that prevents the bug
        assert isinstance(result, str), (
            f"registry_run must return str for all cases. "
            f"Got {type(result).__name__} for node_type='{node_type}'. "
            f"This breaks Pydantic validation in MCP tool layer."
        )

        # Content check - verify we got expected error
        assert expected_indicator.lower() in result.lower(), (
            f"Expected '{expected_indicator}' in result for '{node_type}'"
        )

        # Must be non-empty
        assert len(result) > 0, "Error message should not be empty"


class TestMCPToolIntegration:
    """Integration tests simulating how MCP tool layer calls the service."""

    def test_mcp_tool_can_handle_all_error_types(self):
        """Simulate MCP tool calling service - all errors return valid strings.

        This test simulates the full flow:
        1. MCP tool declares: async def registry_run(...) -> str
        2. Service is called: ExecutionService.run_registry_node(...)
        3. Service must return str (not dict) to pass Pydantic validation
        """
        # Simulate different error scenarios
        error_scenarios = [
            "nonexistent-node",  # Node not found
            "read-file",  # Missing params
            "another-fake-node",  # Node not found (no suggestions)
        ]

        for node_type in error_scenarios:
            result = ExecutionService.run_registry_node(node_type)

            # This is what Pydantic checks - must be str
            assert isinstance(result, str), (
                f"MCP tool expects str but got {type(result).__name__} "
                f"for '{node_type}'. This would fail Pydantic validation."
            )

            # Result should be displayable to user
            assert len(result) > 0, "Error message should not be empty"
            assert "\n" in result or len(result) < 200, "Error should be formatted (multi-line) or concise"
