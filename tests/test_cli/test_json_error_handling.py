"""Tests for JSON error handling in CLI.

Tests that malformed JSON files show helpful syntax errors
instead of incorrectly triggering the natural language planner.
"""

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner

from pflow.cli.main import main


class TestJSONErrorHandling:
    """Test JSON syntax error handling."""

    def test_malformed_json_shows_syntax_error(self):
        """Test that malformed JSON shows syntax error instead of triggering planner."""
        # Create a malformed JSON file (missing closing brace)
        malformed_json = """{
  "ir_version": "0.1.0",
  "outputs": {
    "content": "missing closing brace"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(malformed_json)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show JSON syntax error
            assert "Invalid JSON syntax" in result.output
            assert "Error at line" in result.output
            assert "Fix the JSON syntax error" in result.output

            # Should NOT mention planner
            assert "planner" not in result.output.lower()
            assert "natural language" not in result.output.lower()

        finally:
            Path(temp_path).unlink()

    def test_json_with_trailing_comma_shows_error(self):
        """Test JSON with trailing comma shows specific error."""
        json_with_comma = """{
  "ir_version": "0.1.0",
  "nodes": [],
  "outputs": {
    "result": "test",
  }
}"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(json_with_comma)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show JSON syntax error
            assert "Invalid JSON syntax" in result.output
            assert "Error at line" in result.output

            # Should show context about the JSON error
            # Different Python versions report JSON errors differently, so be flexible
            assert any([
                '"result": "test",' in result.output,  # Python 3.13+ shows actual line
                "Line 6:" in result.output,  # Python 3.10-3.12 shows next line
                "line 5" in result.output.lower(),  # Some versions show line number in text
            ])

        finally:
            Path(temp_path).unlink()

    def test_json_array_detected_as_json(self):
        """Test that JSON arrays (starting with [) are detected as JSON attempts."""
        malformed_array = '[{"test": "incomplete"'

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(malformed_array)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show JSON syntax error
            assert "Invalid JSON syntax" in result.output
            assert "Error at line" in result.output

        finally:
            Path(temp_path).unlink()

    def test_natural_language_not_treated_as_json(self):
        """Test that natural language text doesn't trigger JSON error."""
        # With the new system, only files ending in .json or with / in the path
        # are treated as file paths. Natural language is passed directly.
        runner = CliRunner()
        result = runner.invoke(main, ["analyze the data in my file and summarize it", "--verbose"])

        # Should NOT show JSON syntax errors since it's not a file path
        assert "Invalid JSON syntax" not in result.output

        # It will either try the planner or fail if no API key,
        # but shouldn't show JSON errors

    def test_valid_json_workflow_no_error(self):
        """Test that valid JSON workflow doesn't show JSON errors."""
        # Create a minimal valid workflow
        valid_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1",
                    "node_type": "test_node",  # This will fail at runtime but that's OK
                    "config": {},
                }
            ],
            "outputs": {},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(valid_workflow, f)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should NOT show JSON syntax errors
            # (May show other errors like node not found, but that's OK)
            assert "Invalid JSON syntax" not in result.output

        finally:
            Path(temp_path).unlink()

    def test_error_message_shows_line_and_pointer(self):
        """Test that error message includes line content and pointer."""
        malformed_json = """{
  "test": "value",
  "broken": incomplete
}"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(malformed_json)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should show the problematic line
            assert '"broken": incomplete' in result.output

            # Should show a pointer (^) to the error location
            assert "^" in result.output

        finally:
            Path(temp_path).unlink()
