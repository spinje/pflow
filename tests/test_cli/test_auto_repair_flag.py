"""Test the --auto-repair CLI flag functionality.

This test verifies that the --auto-repair flag properly enables
automatic workflow repair when workflows fail.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import click.testing
import pytest

from pflow.cli.main import main
from pflow.pocketflow import BaseNode

# GATED: Auto-repair tests skipped pending markdown format migration (Task 107).
pytestmark = pytest.mark.skip(reason="Gated pending markdown format migration (Task 107)")


class FailingNode(BaseNode):
    """Node that always fails to test repair behavior."""

    def run(self, shared):
        """Always fail with a template-like error."""
        raise ValueError("Template ${data.missing} not found")


class TestAutoRepairFlag:
    """Test the --auto-repair CLI flag."""

    @pytest.fixture
    def failing_workflow(self):
        """Create a workflow that will fail."""
        return {"ir_version": "0.1.0", "nodes": [{"id": "fail", "type": "failing-node", "params": {}}]}

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry with failing node."""
        with patch("pflow.registry.Registry") as MockRegistry:
            mock_reg = MagicMock()
            mock_reg.load.return_value = {
                "failing-node": {"module": "tests.test_cli.test_auto_repair_flag", "class_name": "FailingNode"}
            }
            MockRegistry.return_value = mock_reg
            yield mock_reg

    def test_repair_disabled_by_default(self, failing_workflow, mock_registry):
        """Test that repair is disabled by default."""
        runner = click.testing.CliRunner()

        # Create workflow file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(failing_workflow, f)
            workflow_file = f.name

        try:
            with (
                patch("pflow.core.workflow_validator.WorkflowValidator.validate", return_value=([], [])),
                patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute,
            ):
                mock_execute.return_value = MagicMock(
                    success=False,
                    errors=[{"message": "Failed"}],
                    shared_after={},
                    output_data=None,
                    repaired_workflow_ir=None,
                )

                # Run without --auto-repair flag
                runner.invoke(main, [workflow_file])

                # Check that repair was disabled (default)
                mock_execute.assert_called_once()
                args, kwargs = mock_execute.call_args
                assert kwargs.get("enable_repair") is False

        finally:
            Path(workflow_file).unlink()

    def test_auto_repair_flag_enables_repair(self, failing_workflow, mock_registry):
        """Test that --auto-repair flag enables automatic repair."""
        runner = click.testing.CliRunner()

        # Create workflow file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(failing_workflow, f)
            workflow_file = f.name

        try:
            # Note: With --auto-repair, validation happens inside execute_workflow, not CLI
            with (
                patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute,
            ):
                mock_execute.return_value = MagicMock(
                    success=False,
                    errors=[{"message": "Failed"}],
                    shared_after={},
                    output_data=None,
                    repaired_workflow_ir=None,
                )

                # Run WITH --auto-repair flag
                runner.invoke(main, ["--auto-repair", workflow_file])

                # Check that repair was enabled
                mock_execute.assert_called_once()
                args, kwargs = mock_execute.call_args
                assert kwargs.get("enable_repair") is True

        finally:
            Path(workflow_file).unlink()

    def test_successful_workflow_ignores_repair_flag(self, mock_registry):
        """Test that successful workflows work the same regardless of repair flag."""
        runner = click.testing.CliRunner()

        # Create a successful workflow
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [],  # Empty workflow succeeds
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            with (
                patch("pflow.core.workflow_validator.WorkflowValidator.validate", return_value=([], [])),
                patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute,
            ):
                mock_execute.return_value = MagicMock(
                    success=True, errors=[], shared_after={}, output_data=None, repaired_workflow_ir=None
                )

                # Run without --auto-repair (shouldn't matter for success)
                result = runner.invoke(main, [workflow_file])
                assert result.exit_code == 0

                # Run with --auto-repair (should be same result)
                result = runner.invoke(main, ["--auto-repair", workflow_file])
                assert result.exit_code == 0

        finally:
            Path(workflow_file).unlink()

    def test_auto_repair_flag_with_verbose(self, failing_workflow, mock_registry):
        """Test that --auto-repair works with other flags like --verbose."""
        runner = click.testing.CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(failing_workflow, f)
            workflow_file = f.name

        try:
            # Note: With --auto-repair, validation happens inside execute_workflow, not CLI
            with (
                patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute,
            ):
                mock_execute.return_value = MagicMock(
                    success=False,
                    errors=[{"message": "Failed"}],
                    shared_after={},
                    output_data=None,
                    repaired_workflow_ir=None,
                )

                # Run with both --auto-repair and --verbose
                runner.invoke(main, ["--verbose", "--auto-repair", workflow_file])

                # Repair should be enabled
                mock_execute.assert_called_once()
                args, kwargs = mock_execute.call_args
                assert kwargs.get("enable_repair") is True

        finally:
            Path(workflow_file).unlink()

    def test_without_auto_repair_preserves_error_message(self, failing_workflow, mock_registry):
        """Test that error messages are preserved when repair is disabled (default)."""
        runner = click.testing.CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(failing_workflow, f)
            workflow_file = f.name

        try:
            with (
                patch("pflow.core.workflow_validator.WorkflowValidator.validate", return_value=([], [])),
                patch("pflow.runtime.compiler.compile_ir_to_flow") as mock_compile,
            ):
                mock_flow = MagicMock()
                mock_flow.run.side_effect = ValueError("Template ${data.missing} not found")
                mock_compile.return_value = mock_flow

                # Run without --auto-repair (repair disabled by default)
                result = runner.invoke(main, [workflow_file])

                # Should fail with exit code 1
                assert result.exit_code == 1

                # Error message should be shown
                assert "Template ${data.missing}" in result.output or "Workflow execution failed" in result.output

        finally:
            Path(workflow_file).unlink()
