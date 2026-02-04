"""Tests for markdown parse error handling in CLI.

Tests that malformed .pflow.md files show helpful syntax errors
with line numbers and suggestions.
"""

import tempfile
from pathlib import Path

from click.testing import CliRunner

from pflow.cli.main import main


class TestMarkdownParseErrorHandling:
    """Test markdown parse error handling."""

    def test_missing_steps_section_shows_parse_error(self):
        """Test that markdown without ## Steps section shows helpful error."""
        # Markdown without Steps section (required)
        malformed_md = """# Test Workflow

This workflow has no steps section.
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(malformed_md)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show markdown parse error
            assert "Invalid workflow syntax" in result.output
            assert "Steps" in result.output

        finally:
            Path(temp_path).unlink()

    def test_missing_type_param_shows_error(self):
        """Test node without type parameter shows helpful error."""
        malformed_md = """# Test Workflow

## Steps

### node1

A node without type.

- command: echo test
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(malformed_md)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show markdown parse error with line number
            assert "Invalid workflow syntax" in result.output
            assert "type" in result.output.lower()

        finally:
            Path(temp_path).unlink()

    def test_invalid_yaml_param_shows_error(self):
        """Test invalid YAML parameter shows error."""
        malformed_md = """# Test Workflow

## Steps

### node1

A node.

- type: shell
- invalid-yaml: {unclosed bracket
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(malformed_md)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show parse error
            assert "Invalid workflow syntax" in result.output or "error" in result.output.lower()

        finally:
            Path(temp_path).unlink()

    def test_json_file_shows_migration_message(self):
        """Test that .json files show clear migration message."""
        json_content = '{"ir_version": "0.1.0", "nodes": []}'

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(json_content)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show clear migration message
            assert "JSON workflow format is no longer supported" in result.output
            assert ".pflow.md format" in result.output

        finally:
            Path(temp_path).unlink()

    def test_valid_markdown_workflow_no_error(self):
        """Test that valid markdown workflow parses successfully."""
        valid_md = """# Test Workflow

Test workflow description.

## Steps

### node1

A test node.

- type: shell
- command: echo test
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(valid_md)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should NOT show parse errors
            # (May show other errors like node execution, but no parse errors)
            assert "Invalid workflow syntax" not in result.output

        finally:
            Path(temp_path).unlink()

    def test_permission_error_shows_helpful_message(self, tmp_path):
        """Test permission error shows helpful message."""
        wf = tmp_path / "wf.pflow.md"
        wf.write_text("# Test\n\n## Steps\n\n### a\n\nDesc.\n\n- type: shell\n- command: echo test\n")

        from unittest.mock import patch

        def raise_perm(*args, **kwargs):
            raise PermissionError

        runner = CliRunner()

        with patch("pathlib.Path.read_text", raise_perm):
            result = runner.invoke(main, [str(wf)])
            assert result.exit_code != 0
            assert "Permission denied" in result.output

    def test_unicode_decode_error_shows_helpful_message(self, tmp_path):
        """Test unicode decode error shows helpful message."""
        wf = tmp_path / "wf.pflow.md"
        wf.write_text("placeholder")

        from unittest.mock import patch

        def raise_decode(*args, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        runner = CliRunner()

        with patch("pathlib.Path.read_text", raise_decode):
            result = runner.invoke(main, [str(wf)])
            assert result.exit_code != 0
            assert "Unable to read file" in result.output

    def test_error_shows_file_path(self):
        """Test that error messages include the file path."""
        malformed_md = """# Bad

## Steps

### node1

Missing type.

- command: echo test
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(malformed_md)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should mention the file path in error
            # The file path appears somewhere in the error message
            assert temp_path in result.output or Path(temp_path).name in result.output

        finally:
            Path(temp_path).unlink()

    def test_unclosed_code_block_shows_error(self):
        """Test unclosed code block shows parse error."""
        malformed_md = """# Test Workflow

## Steps

### node1

A node with unclosed code block.

- type: shell

```shell command
echo test
# Missing closing backticks
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(malformed_md)
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(main, [temp_path])

            # Should exit with error
            assert result.exit_code != 0

            # Should show parse error
            assert "Invalid workflow syntax" in result.output or "error" in result.output.lower()

        finally:
            Path(temp_path).unlink()
