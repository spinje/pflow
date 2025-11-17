"""Tests for read-fields CLI command."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.read_fields import read_fields
from pflow.core.execution_cache import ExecutionCache


@pytest.fixture
def cache_with_data(tmp_path, monkeypatch):
    """Create ExecutionCache with test data."""
    # Mock home to use temp directory
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    cache = ExecutionCache()
    execution_id = cache.generate_execution_id()

    # Store test data
    cache.store(
        execution_id=execution_id,
        node_type="test-node",
        params={"param1": "value1"},
        outputs={
            "result": [
                {"id": 1, "title": "First item", "value": 100},
                {"id": 2, "title": "Second item", "value": 200},
            ],
            "status": "success",
        },
    )

    return execution_id, cache


class TestReadFieldsCommand:
    """Test read-fields CLI command."""

    def test_read_single_field(self, cache_with_data):
        """Test reading a single field."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id, "status"])

        assert result.exit_code == 0
        assert "status: success" in result.output

    def test_read_multiple_fields(self, cache_with_data):
        """Test reading multiple fields."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id, "result[0].title", "result[0].id"])

        assert result.exit_code == 0
        assert "result[0].title: First item" in result.output
        assert "result[0].id: 1" in result.output

    def test_read_complex_field(self, cache_with_data):
        """Test reading complex field (dict/list)."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id, "result"])

        assert result.exit_code == 0
        # Should pretty-print the list
        assert "result:" in result.output
        assert '"id": 1' in result.output
        assert '"title": "First item"' in result.output

    def test_read_nonexistent_field(self, cache_with_data):
        """Test reading field that doesn't exist."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id, "nonexistent"])

        assert result.exit_code == 0
        assert "(not found)" in result.output

    def test_read_invalid_execution_id(self, cache_with_data):
        """Test reading from invalid execution ID."""
        runner = CliRunner()
        result = runner.invoke(read_fields, ["exec-invalid-123", "status"])

        assert result.exit_code == 1
        assert "not found in cache" in result.output

    def test_json_output_format(self, cache_with_data):
        """Test JSON output format."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id, "status", "result[0].id", "--output-format", "json"])

        assert result.exit_code == 0

        # Parse JSON output
        output_data = json.loads(result.output)
        assert output_data["status"] == "success"
        assert output_data["result[0].id"] == 1

    def test_nested_field_path(self, cache_with_data):
        """Test nested field path resolution."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id, "result[1].value"])

        assert result.exit_code == 0
        assert "result[1].value: 200" in result.output

    def test_no_field_paths_error(self, cache_with_data):
        """Test error when no field paths provided."""
        execution_id, _ = cache_with_data

        runner = CliRunner()
        result = runner.invoke(read_fields, [execution_id])

        # Should fail - field_paths is required
        assert result.exit_code != 0


class TestFieldOutputFormatter:
    """Test field_output_formatter directly."""

    def test_text_format_simple_values(self):
        """Test text format with simple values."""
        from pflow.execution.formatters.field_output_formatter import format_field_output

        field_values = {"field1": "value1", "field2": 42, "field3": True}

        result = format_field_output(field_values, "text")

        assert "field1: value1" in result
        assert "field2: 42" in result
        assert "field3: True" in result

    def test_text_format_none_values(self):
        """Test text format with None values."""
        from pflow.execution.formatters.field_output_formatter import format_field_output

        field_values = {"exists": "value", "missing": None}

        result = format_field_output(field_values, "text")

        assert "exists: value" in result
        assert "missing: (not found)" in result

    def test_json_format_returns_dict(self):
        """Test JSON format returns dict."""
        from pflow.execution.formatters.field_output_formatter import format_field_output

        field_values = {"field1": "value1", "field2": None}

        result = format_field_output(field_values, "json")

        assert isinstance(result, dict)
        assert result == field_values

    def test_empty_field_values(self):
        """Test empty field values."""
        from pflow.execution.formatters.field_output_formatter import format_field_output

        result = format_field_output({}, "text")

        assert result == "(no fields retrieved)"
