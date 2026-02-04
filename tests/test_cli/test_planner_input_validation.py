"""Tests for natural language planner input validation."""

import click
import pytest
from click.testing import CliRunner

from pflow.cli.main import (
    _handle_invalid_planner_input,
    _is_valid_natural_language_input,
    workflow_command,
)


class TestIsValidNaturalLanguageInput:
    """Tests for _is_valid_natural_language_input function."""

    def test_valid_single_quoted_argument_with_spaces(self):
        """Valid: single quoted argument with spaces."""
        assert _is_valid_natural_language_input(("do something",)) is True
        assert _is_valid_natural_language_input(("analyze this file and summarize it",)) is True
        assert _is_valid_natural_language_input(("read file.txt and process it",)) is True

    def test_invalid_multiple_unquoted_arguments(self):
        """Invalid: multiple unquoted arguments."""
        assert _is_valid_natural_language_input(("lets", "do", "this")) is False
        assert _is_valid_natural_language_input(("jkahsd", "do something")) is False
        assert _is_valid_natural_language_input(("node1", "node2", "node3")) is False

    def test_invalid_single_word_no_spaces(self):
        """Invalid: single word (no spaces)."""
        assert _is_valid_natural_language_input(("random",)) is False
        assert _is_valid_natural_language_input(("workflow",)) is False
        assert _is_valid_natural_language_input(("test",)) is False

    def test_invalid_empty_tuple(self):
        """Invalid: empty tuple."""
        assert _is_valid_natural_language_input(()) is False

    def test_invalid_file_paths(self):
        """Invalid: file paths (defensive check)."""
        assert _is_valid_natural_language_input(("workflow.json",)) is False
        assert _is_valid_natural_language_input(("./path/to/file.json",)) is False
        assert _is_valid_natural_language_input(("/absolute/path/workflow.json",)) is False


class TestHandleInvalidPlannerInput:
    """Tests for _handle_invalid_planner_input error messages."""

    def test_empty_workflow_shows_usage_error(self):
        """Empty workflow shows usage error."""
        ctx = workflow_command.make_context("pflow", [])

        with pytest.raises(click.exceptions.Exit) as exc_info:
            _handle_invalid_planner_input(ctx, ())

        assert exc_info.value.exit_code == 1

    def test_single_word_shows_helpful_error(self):
        """Single word shows targeted hint."""
        ctx = workflow_command.make_context("pflow", ["random"])

        with pytest.raises(click.exceptions.Exit) as exc_info:
            _handle_invalid_planner_input(ctx, ("random",))

        assert exc_info.value.exit_code == 1

    def test_multiple_words_shows_quote_suggestion(self):
        """Multiple unquoted words shows quote suggestion."""
        ctx = workflow_command.make_context("pflow", ["lets", "do", "this"])

        with pytest.raises(click.exceptions.Exit) as exc_info:
            _handle_invalid_planner_input(ctx, ("lets", "do", "this"))

        assert exc_info.value.exit_code == 1


class TestCLIBehaviorWithInvalidInput:
    """Integration tests for CLI behavior with invalid planner input."""

    def test_unquoted_multi_word_shows_error(self):
        """Multiple unquoted words should show helpful error."""
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["lets", "do", "this"])

        assert result.exit_code == 1
        assert "Invalid input" in result.output
        assert "must be quoted" in result.output
        assert 'pflow "lets do this"' in result.output

    def test_mixed_quoted_unquoted_shows_error(self):
        """Mixed quoted/unquoted should show helpful error."""
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["jkahsd", "do something"])

        assert result.exit_code == 1
        assert "Invalid input" in result.output
        assert "must be quoted" in result.output

    def test_single_unquoted_word_not_workflow_shows_error(self):
        """Single unquoted word that's not a workflow should error."""
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["randomnonexistent"])

        assert result.exit_code == 1
        assert "not a known workflow or command" in result.output

    def test_empty_input_shows_error(self):
        """Empty input should show error."""
        runner = CliRunner()
        result = runner.invoke(workflow_command, [])

        assert result.exit_code == 1
        # Empty input is now caught by validation
        assert "No workflow" in result.output or "not a known workflow" in result.output


class TestCLIBehaviorWithValidInput:
    """Integration tests for CLI behavior with valid input (should reach planner or workflow)."""

    @pytest.mark.skip(reason="Gated pending markdown format migration (Task 107)")
    def test_quoted_prompt_attempts_planner(self, monkeypatch):
        """Quoted multi-word prompt should attempt to use planner."""
        # Mock the planner to avoid real API calls
        planner_called = False

        def mock_execute_with_planner(*args, **kwargs):
            nonlocal planner_called
            planner_called = True
            # Don't actually execute - just track the call
            import sys

            sys.exit(0)

        from pflow.cli import main as main_module

        monkeypatch.setattr(main_module, "_execute_with_planner", mock_execute_with_planner)

        runner = CliRunner()
        result = runner.invoke(workflow_command, ["do something cool"])

        # Should attempt planner (exit 0 from our mock)
        assert result.exit_code == 0
        assert planner_called

    def test_file_path_bypasses_validation(self, tmp_path):
        """File path should bypass planner validation."""
        # Create a simple workflow file
        workflow_file = tmp_path / "test.json"
        workflow_file.write_text('{"nodes": [], "connections": []}')

        runner = CliRunner()
        result = runner.invoke(workflow_command, [str(workflow_file)])

        # Should attempt to execute (may fail for other reasons, but not validation)
        # The key is it shouldn't show "Invalid input" or "must be quoted"
        assert "Invalid input" not in result.output
        assert "must be quoted" not in result.output

    def test_saved_workflow_bypasses_validation(self):
        """Saved workflow should bypass planner validation."""
        runner = CliRunner()
        # This will fail because workflow doesn't exist, but shouldn't trigger planner validation
        result = runner.invoke(workflow_command, ["my-workflow"])

        assert result.exit_code == 1
        # Should show workflow not found, not invalid input
        assert "Workflow 'my-workflow' not found" in result.output or "not a known workflow" in result.output
        assert "must be quoted" not in result.output
