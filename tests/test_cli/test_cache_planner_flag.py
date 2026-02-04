"""Test the --cache-planner CLI flag functionality."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pflow.cli.main import workflow_command

# GATED: Planner cache tests skipped pending markdown format migration (Task 107).
pytestmark = pytest.mark.skip(reason="Gated pending markdown format migration (Task 107)")


class TestCachePlannerFlag:
    """Test the --cache-planner flag functionality."""

    def test_cache_planner_flag_defaults_to_false(self):
        """Test that cache_planner defaults to False when flag is not provided."""
        runner = CliRunner()

        with patch("pflow.cli.main._execute_with_planner") as mock_execute:
            # Set up to avoid actual planner execution
            runner.invoke(workflow_command, ["test workflow"], catch_exceptions=False)

            # Check that the function was called
            assert mock_execute.called

            # Get the arguments passed to _execute_with_planner
            call_args = mock_execute.call_args[0]
            # The last argument should be cache_planner=False
            assert not call_args[-1]  # cache_planner should be False

    def test_cache_planner_flag_set_to_true(self):
        """Test that cache_planner is True when --cache-planner flag is provided."""
        runner = CliRunner()

        with patch("pflow.cli.main._execute_with_planner") as mock_execute:
            # Set up to avoid actual planner execution
            runner.invoke(workflow_command, ["--cache-planner", "test workflow"], catch_exceptions=False)

            # Check that the function was called
            assert mock_execute.called

            # Get the arguments passed to _execute_with_planner
            call_args = mock_execute.call_args[0]
            # The last argument should be cache_planner=True
            assert call_args[-1]  # cache_planner should be True

    def test_cache_planner_propagates_to_shared_store(self):
        """Test that cache_planner flag is properly propagated to the shared store."""
        import click

        from pflow.cli.main import _setup_planner_execution

        # Create a mock context
        ctx = click.Context(click.Command("test"))

        # Test without flag
        ctx.obj = {"output_format": "text", "cache_planner": False}
        _, _, _, shared = _setup_planner_execution(ctx, "test input", None, False, False)
        assert "cache_planner" in shared
        assert not shared["cache_planner"]

        # Test with flag
        ctx.obj = {"output_format": "text", "cache_planner": True}
        _, _, _, shared = _setup_planner_execution(ctx, "test input", None, False, True)
        assert "cache_planner" in shared
        assert shared["cache_planner"]

    def test_cache_planner_flag_appears_in_help(self):
        """Test that the --cache-planner flag appears in the help text."""
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--help"])

        assert result.exit_code == 0
        assert "--cache-planner" in result.output
        # Check for key parts of the help text (might be wrapped)
        assert "Enable cross-session caching" in result.output
        assert "planner LLM" in result.output
