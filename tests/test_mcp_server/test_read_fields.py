"""Tests for read_fields MCP tool and FieldService.

This test suite verifies:
1. FieldService business logic
2. MCP tool registration and behavior
3. CLI/MCP parity (both use same formatter)
"""

import pytest

from pflow.core.execution_cache import ExecutionCache
from pflow.mcp_server.services.field_service import FieldService


@pytest.fixture
def cache_with_test_data():
    """Create a cache with comprehensive test data."""
    cache = ExecutionCache()
    exec_id = cache.generate_execution_id()

    # Store comprehensive test data
    cache.store(
        execution_id=exec_id,
        node_type="test-node",
        params={},
        outputs={
            "result": "test-value",
            "title": "Test Title",
            "id": 12345,
            "status": "active",
            "nested": [
                {
                    "title": "Issue 1",
                    "author": {"login": "user1"},
                },
                {
                    "title": "Issue 2",
                    "author": {"login": "user2"},
                },
            ],
            "dict_value": {"key": "value", "nested": {"data": 123}},
            "list_value": [1, 2, 3],
            "binary_field": b"Binary data content",
            "items": [1, 2, 3],
            "url": "https://example.com/path?query=value&foo=bar",
            "markdown": "**bold** and *italic*",
            "emoji": "✓ Success 🎉",
        },
    )

    return exec_id


class TestFieldService:
    """Test suite for FieldService business logic."""

    def test_read_single_field_returns_formatted_text(self, cache_with_test_data):
        """Should retrieve and format a single field value."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["result"])

        assert isinstance(result, str)
        assert "result: test-value" in result

    def test_read_multiple_fields_returns_all_values(self, cache_with_test_data):
        """Should retrieve multiple fields in single call."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["title", "id", "status"])

        assert "title: Test Title" in result
        assert "id: 12345" in result
        assert "status: active" in result

    def test_read_nested_field_path_resolves_correctly(self, cache_with_test_data):
        """Should resolve complex nested field paths."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["nested[0].title", "nested[0].author.login"])

        assert "nested[0].title: Issue 1" in result
        assert "nested[0].author.login: user1" in result

    def test_invalid_field_path_returns_none(self, cache_with_test_data):
        """Should gracefully handle invalid field paths."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["nonexistent_field"])

        assert "nonexistent_field: (not found)" in result

    def test_invalid_execution_id_raises_value_error(self):
        """Should raise ValueError for nonexistent execution_id."""
        with pytest.raises(ValueError) as exc_info:
            FieldService.read_fields("exec-nonexistent-id", ["result"])

        error_msg = str(exc_info.value)
        assert "exec-nonexistent-id" in error_msg
        assert "not found in cache" in error_msg
        assert "Run registry_run" in error_msg

    def test_complex_values_formatted_correctly(self, cache_with_test_data):
        """Should format complex values (dicts, lists) properly."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["result", "dict_value", "list_value"])

        assert "result: test-value" in result
        assert "dict_value:" in result
        assert '"key": "value"' in result  # JSON formatted
        assert "list_value:" in result
        assert "[" in result  # Array notation

    def test_binary_data_decoded_correctly(self, cache_with_test_data):
        """Should decode binary data from base64 encoding."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["binary_field"])

        assert "binary_field:" in result
        # Binary data is decoded and shown as bytes repr
        assert "Binary data content" in result or "b'" in result

    def test_empty_field_paths_returns_empty_output(self, cache_with_test_data):
        """Should handle empty field paths gracefully."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, [])

        # Formatter returns friendly message for empty field list
        assert result == "(no fields retrieved)"

    def test_out_of_bounds_array_access_returns_none(self, cache_with_test_data):
        """Should handle array index out of bounds gracefully."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["items[10]"])

        assert "items[10]: (not found)" in result

    def test_malformed_field_path_returns_none(self, cache_with_test_data):
        """Should handle malformed field paths gracefully."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["result[[[invalid", "..bad..path"])

        assert "(not found)" in result

    def test_special_characters_in_field_values(self, cache_with_test_data):
        """Should handle special characters in values."""
        exec_id = cache_with_test_data

        result = FieldService.read_fields(exec_id, ["url", "markdown", "emoji"])

        assert "https://example.com/path?query=value&foo=bar" in result
        assert "**bold**" in result
        assert "✓" in result or "Success" in result


class TestMCPToolIntegration:
    """Test suite for MCP tool registration and async bridge."""

    def test_read_fields_tool_is_registered(self):
        """Should register read_fields tool with MCP server."""
        from pflow.mcp_server.tools import execution_tools

        assert hasattr(execution_tools, "read_fields")
        assert "read_fields" in execution_tools.__all__

    def test_read_fields_tool_has_correct_signature(self):
        """Should have correct async signature with annotations."""
        import inspect

        from pflow.mcp_server.tools.execution_tools import read_fields

        assert inspect.iscoroutinefunction(read_fields)

        sig = inspect.signature(read_fields)
        assert "execution_id" in sig.parameters
        assert "field_paths" in sig.parameters
        assert sig.return_annotation is str


class TestCLIMCPParity:
    """Test suite verifying CLI and MCP produce identical output."""

    def test_cli_and_mcp_produce_identical_output(self, cache_with_test_data):
        """CLI and MCP should return identical formatted text."""
        exec_id = cache_with_test_data

        # Execute CLI version (use formatter directly, simulating CLI logic)
        from pflow.execution.formatters.field_output_formatter import format_field_output
        from pflow.runtime.template_resolver import TemplateResolver

        # Get cache data
        cache = ExecutionCache()
        cache_data = cache.retrieve(exec_id)
        outputs = cache_data["outputs"]

        cli_field_values = {}
        for field_path in ["title", "id", "nested[0].author.login"]:
            try:
                value = TemplateResolver.resolve_value(field_path, outputs)
                cli_field_values[field_path] = value
            except Exception:
                cli_field_values[field_path] = None

        cli_result = format_field_output(cli_field_values, format_type="text")

        # Execute MCP version
        mcp_result = FieldService.read_fields(exec_id, ["title", "id", "nested[0].author.login"])

        # Verify: Identical output
        assert cli_result == mcp_result

    def test_error_handling_parity(self):
        """CLI and MCP should handle errors identically."""
        invalid_exec_id = "exec-nonexistent-12345"

        # MCP raises ValueError
        with pytest.raises(ValueError) as exc_info:
            FieldService.read_fields(invalid_exec_id, ["field"])

        error_msg = str(exc_info.value)
        assert "not found in cache" in error_msg
        assert "Run registry_run" in error_msg
