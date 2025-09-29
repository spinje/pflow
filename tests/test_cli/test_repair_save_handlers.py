"""Comprehensive tests for repair save handlers.

Tests cover all workflow sources (file, saved, planner) with various parameter
combinations and save modes.
"""

import json
from unittest.mock import MagicMock, patch

import click
import pytest

from pflow.cli.repair_save_handlers import (
    _save_repaired_file_workflow,
    _save_repaired_planner_workflow,
    _save_repaired_saved_workflow,
    save_repaired_workflow,
)


@pytest.fixture
def mock_ctx():
    """Create a mock Click context with required attributes."""
    ctx = MagicMock(spec=click.Context)
    ctx.obj = {}
    return ctx


@pytest.fixture
def sample_workflow_ir():
    """Sample repaired workflow IR for testing."""
    return {
        "ir_version": "1.0",
        "nodes": [{"id": "test", "type": "echo", "params": {"message": "Fixed workflow"}}],
        "edges": [],
    }


class TestSaveRepairedWorkflow:
    """Test the main save_repaired_workflow dispatcher."""

    def test_routes_to_saved_handler(self, mock_ctx, sample_workflow_ir):
        """Test that saved workflows are routed to correct handler."""
        mock_ctx.obj["workflow_source"] = "saved"
        mock_ctx.obj["workflow_name"] = "test-workflow"

        with patch("pflow.cli.repair_save_handlers._save_repaired_saved_workflow") as mock_handler:
            save_repaired_workflow(mock_ctx, sample_workflow_ir)
            mock_handler.assert_called_once_with(mock_ctx, sample_workflow_ir, False)

    def test_routes_to_file_handler(self, mock_ctx, sample_workflow_ir):
        """Test that file workflows are routed to correct handler."""
        mock_ctx.obj["workflow_source"] = "file"
        mock_ctx.obj["source_file_path"] = "/path/to/workflow.json"

        with patch("pflow.cli.repair_save_handlers._save_repaired_file_workflow") as mock_handler:
            save_repaired_workflow(mock_ctx, sample_workflow_ir)
            mock_handler.assert_called_once_with(mock_ctx, sample_workflow_ir, False)

    def test_routes_to_planner_handler(self, mock_ctx, sample_workflow_ir):
        """Test that planner workflows are routed to correct handler."""
        mock_ctx.obj["workflow_source"] = None  # Planner-generated has no source

        with patch("pflow.cli.repair_save_handlers._save_repaired_planner_workflow") as mock_handler:
            save_repaired_workflow(mock_ctx, sample_workflow_ir)
            mock_handler.assert_called_once_with(mock_ctx, sample_workflow_ir)

    def test_handles_no_update_flag(self, mock_ctx, sample_workflow_ir):
        """Test that --no-update flag is passed correctly."""
        mock_ctx.obj["workflow_source"] = "file"
        mock_ctx.obj["no_update"] = True

        with patch("pflow.cli.repair_save_handlers._save_repaired_file_workflow") as mock_handler:
            save_repaired_workflow(mock_ctx, sample_workflow_ir)
            mock_handler.assert_called_once_with(mock_ctx, sample_workflow_ir, True)


class TestSaveRepairedSavedWorkflow:
    """Test saving repaired workflows from workflow manager."""

    @patch("pflow.core.workflow_manager.WorkflowManager")
    @patch("click.echo")
    def test_default_updates_original(self, mock_echo, mock_wm_class, mock_ctx, sample_workflow_ir):
        """Test that default behavior updates original workflow."""
        mock_ctx.obj["workflow_name"] = "my-workflow"
        mock_ctx.obj["no_update"] = False

        # Setup mock workflow manager
        mock_wm = MagicMock()
        mock_wm_class.return_value = mock_wm

        _save_repaired_saved_workflow(mock_ctx, sample_workflow_ir, no_update=False)

        # Verify update_ir was called
        mock_wm.update_ir.assert_called_once_with("my-workflow", sample_workflow_ir)

        # Verify success message
        assert any("Updated saved workflow 'my-workflow'" in str(call) for call in mock_echo.call_args_list)

    @patch("pflow.cli.rerun_display.display_file_rerun_commands")
    @patch("click.echo")
    def test_no_update_saves_to_repaired_folder(self, mock_echo, mock_display, mock_ctx, sample_workflow_ir, tmp_path):
        """Test that --no-update saves to repaired/ subfolder."""
        mock_ctx.obj["workflow_name"] = "my-workflow"
        mock_ctx.obj["no_update"] = True
        mock_ctx.obj["execution_params"] = {"param1": "value1"}

        # Use temp directory for testing
        with patch("pflow.cli.repair_save_handlers.Path.home", return_value=tmp_path):
            _save_repaired_saved_workflow(mock_ctx, sample_workflow_ir, no_update=True)

        # Verify file was created in repaired/ subdirectory
        repaired_file = tmp_path / ".pflow" / "workflows" / "repaired" / "my-workflow.json"
        assert repaired_file.exists()

        # Verify content
        with open(repaired_file) as f:
            saved_data = json.load(f)
        assert saved_data == sample_workflow_ir

        # Verify display was called with params
        mock_display.assert_called_once()
        call_kwargs = mock_display.call_args.kwargs
        assert call_kwargs["params"] == {"param1": "value1"}

    @patch("pflow.core.workflow_manager.WorkflowManager")
    @patch("pflow.cli.repair_save_handlers.logger")
    @patch("click.echo")
    def test_handles_update_error_gracefully(self, mock_echo, mock_logger, mock_wm_class, mock_ctx, sample_workflow_ir):
        """Test that errors are shown to user and logged."""
        mock_ctx.obj["workflow_name"] = "my-workflow"

        # Setup mock to raise error
        mock_wm = MagicMock()
        mock_wm.update_ir.side_effect = Exception("Permission denied")
        mock_wm_class.return_value = mock_wm

        _save_repaired_saved_workflow(mock_ctx, sample_workflow_ir, no_update=False)

        # Verify user sees error
        assert any("Could not save repaired workflow" in str(call) for call in mock_echo.call_args_list)

        # Verify error was logged
        mock_logger.exception.assert_called_once()


class TestSaveRepairedFileWorkflow:
    """Test saving repaired file-based workflows."""

    @patch("click.echo")
    def test_default_overwrites_file(self, mock_echo, mock_ctx, sample_workflow_ir, tmp_path):
        """Test that default behavior overwrites original file."""
        # Create temp file
        test_file = tmp_path / "workflow.json"
        test_file.write_text('{"old": "data"}')

        mock_ctx.obj["source_file_path"] = str(test_file)
        mock_ctx.obj["no_update"] = False

        _save_repaired_file_workflow(mock_ctx, sample_workflow_ir, no_update=False)

        # Verify file was overwritten
        with open(test_file) as f:
            saved_data = json.load(f)
        assert saved_data == sample_workflow_ir

        # Verify success message
        assert any(f"Updated {test_file}" in str(call) for call in mock_echo.call_args_list)

    @patch("pflow.cli.rerun_display.display_file_rerun_commands")
    @patch("click.echo")
    def test_no_update_creates_repaired_file(self, mock_echo, mock_display, mock_ctx, sample_workflow_ir, tmp_path):
        """Test that --no-update creates .repaired.json file."""
        test_file = tmp_path / "workflow.json"
        test_file.write_text('{"old": "data"}')

        mock_ctx.obj["source_file_path"] = str(test_file)
        mock_ctx.obj["no_update"] = True
        mock_ctx.obj["execution_params"] = {"param1": "value1"}

        _save_repaired_file_workflow(mock_ctx, sample_workflow_ir, no_update=True)

        # Verify .repaired.json file was created
        repaired_file = tmp_path / "workflow.repaired.json"
        assert repaired_file.exists()

        # Original should be unchanged
        with open(test_file) as f:
            original_data = json.load(f)
        assert original_data == {"old": "data"}

        # Verify repaired content
        with open(repaired_file) as f:
            saved_data = json.load(f)
        assert saved_data == sample_workflow_ir

        # Verify display was called with params
        mock_display.assert_called_once()

    @patch("pflow.cli.repair_save_handlers.logger")
    @patch("click.echo")
    def test_handles_missing_file_path(self, mock_echo, mock_logger, mock_ctx, sample_workflow_ir):
        """Test graceful handling when source_file_path is missing."""
        # Don't set source_file_path, which means it's missing
        mock_ctx.obj["source_file_path"] = None

        _save_repaired_file_workflow(mock_ctx, sample_workflow_ir, no_update=False)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()


class TestSaveRepairedPlannerWorkflow:
    """Test saving repaired planner-generated workflows."""

    @patch("pflow.cli.rerun_display.display_file_rerun_commands")
    @patch("click.echo")
    def test_saves_with_timestamp(self, mock_echo, mock_display, mock_ctx, sample_workflow_ir):
        """Test that planner workflows are saved with timestamp."""
        with patch("pflow.cli.repair_save_handlers.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20240101-120000"

            _save_repaired_planner_workflow(mock_ctx, sample_workflow_ir)

            # Verify file would be created with timestamp
            expected_filename = "workflow-repaired-20240101-120000.json"
            assert any(expected_filename in str(call) for call in mock_echo.call_args_list)

    @patch("pflow.cli.rerun_display.display_file_rerun_commands")
    def test_includes_execution_params(self, mock_display, mock_ctx, sample_workflow_ir):
        """Test that execution params are included in display."""
        mock_ctx.obj["execution_params"] = {"param1": "value1", "param2": 123}

        with patch("pflow.cli.repair_save_handlers.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20240101-120000"

            _save_repaired_planner_workflow(mock_ctx, sample_workflow_ir)

            # Verify display was called with params
            mock_display.assert_called_once()
            call_kwargs = mock_display.call_args.kwargs
            assert call_kwargs["params"] == {"param1": "value1", "param2": 123}
            assert call_kwargs["show_save_tip"] is False  # Planner workflows can't be saved without execution

    @patch("pflow.cli.rerun_display.display_file_rerun_commands")
    def test_handles_no_params(self, mock_display, mock_ctx, sample_workflow_ir):
        """Test that it works without execution params."""
        # Don't set execution_params, which means there are none

        with patch("pflow.cli.repair_save_handlers.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20240101-120000"

            _save_repaired_planner_workflow(mock_ctx, sample_workflow_ir)

            # Verify display was called without params
            mock_display.assert_called_once()
            call_kwargs = mock_display.call_args.kwargs
            assert call_kwargs["params"] is None


class TestIntegration:
    """Integration tests for the full repair save flow."""

    @patch("pflow.core.workflow_manager.WorkflowManager")
    def test_full_flow_saved_workflow_with_params(self, mock_wm_class, mock_ctx, sample_workflow_ir):
        """Test complete flow for saved workflow with parameters."""
        # Setup context
        mock_ctx.obj = {
            "workflow_source": "saved",
            "workflow_name": "slack-bot",
            "execution_params": {"channel_id": "C123", "message_count": 10},
            "no_update": False,
        }

        # Setup mock workflow manager
        mock_wm = MagicMock()
        mock_wm_class.return_value = mock_wm

        # Run the main dispatcher
        save_repaired_workflow(mock_ctx, sample_workflow_ir)

        # Verify workflow was updated
        mock_wm.update_ir.assert_called_once_with("slack-bot", sample_workflow_ir)

    def test_full_flow_file_workflow_no_update(self, mock_ctx, sample_workflow_ir, tmp_path):
        """Test complete flow for file workflow with --no-update."""
        # Setup file
        test_file = tmp_path / "broken.json"
        test_file.write_text('{"old": "data"}')

        # Setup context
        mock_ctx.obj = {
            "workflow_source": "file",
            "source_file_path": str(test_file),
            "execution_params": {"api_key": "<REDACTED>", "limit": 5},
            "no_update": True,
        }

        # Run the main dispatcher
        with patch("pflow.cli.rerun_display.display_file_rerun_commands"):
            save_repaired_workflow(mock_ctx, sample_workflow_ir)

        # Verify .repaired.json was created
        repaired_file = tmp_path / "broken.repaired.json"
        assert repaired_file.exists()

        # Original should be unchanged
        assert json.loads(test_file.read_text()) == {"old": "data"}

    def test_full_flow_planner_workflow(self, mock_ctx, sample_workflow_ir):
        """Test complete flow for planner-generated workflow."""
        # Setup context
        mock_ctx.obj = {
            "workflow_source": None,  # Planner has no source
            "execution_params": {"query": "test", "max_results": 10},
        }

        # Run the main dispatcher
        with (
            patch("pflow.cli.rerun_display.display_file_rerun_commands"),
            patch("pflow.cli.repair_save_handlers.datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = "20240101-120000"

            save_repaired_workflow(mock_ctx, sample_workflow_ir)

            # Would create workflow-repaired-20240101-120000.json
            mock_dt.now.assert_called()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @patch("pflow.cli.repair_save_handlers.logger")
    @patch("builtins.open", side_effect=PermissionError("Permission denied"))
    def test_handles_io_error(self, mock_open, mock_logger, mock_ctx, sample_workflow_ir, tmp_path):
        """Test handling of I/O errors during save."""
        # Setup file path
        test_file = tmp_path / "workflow.json"

        mock_ctx.obj = {"workflow_source": "file", "source_file_path": str(test_file), "no_update": False}

        _save_repaired_file_workflow(mock_ctx, sample_workflow_ir, no_update=False)

        # Should log the error (file handler uses warning, not exception)
        mock_logger.warning.assert_called()

    def test_handles_empty_workflow_name(self, mock_ctx, sample_workflow_ir):
        """Test handling when workflow name is empty or missing."""
        mock_ctx.obj = {"workflow_source": "saved", "workflow_name": None}

        with patch("pflow.cli.repair_save_handlers.logger") as mock_logger:
            _save_repaired_saved_workflow(mock_ctx, sample_workflow_ir, no_update=False)

            # Should log warning
            mock_logger.warning.assert_called()

    def test_preserves_json_formatting(self, mock_ctx, sample_workflow_ir, tmp_path):
        """Test that JSON is saved with proper formatting."""
        test_file = tmp_path / "workflow.json"
        test_file.write_text("{}")

        mock_ctx.obj = {"workflow_source": "file", "source_file_path": str(test_file), "no_update": False}

        _save_repaired_file_workflow(mock_ctx, sample_workflow_ir, no_update=False)

        # Read and verify formatting (should have indentation)
        content = test_file.read_text()
        assert "    " in content  # Has indentation
        assert content.count("\n") > 2  # Multi-line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
