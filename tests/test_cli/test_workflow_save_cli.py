"""Tests for `pflow workflow save` command.

Tests the CLI command that saves draft workflows to the global library.
Focuses on command-line behavior, not WorkflowManager internals.
"""

import json
from typing import Any

import click.testing
import pytest

from pflow.cli.commands.workflow import workflow as workflow_cmd


class TestWorkflowSaveCLI:
    """Test suite for `pflow workflow save` command."""

    @pytest.fixture
    def runner(self) -> click.testing.CliRunner:
        """Create CLI test runner."""
        return click.testing.CliRunner()

    @pytest.fixture
    def sample_workflow_ir(self) -> dict[str, Any]:
        """Valid workflow IR for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

    def test_workflow_save_basic_success(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Valid workflow should save to library.

        Tests the core functionality - workflow file is created in the correct location
        with correct content.
        """
        # Setup
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "draft.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        # Run command
        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "my-workflow", "--description", "Test workflow"],
            env={"HOME": str(tmp_path)},
        )

        # Verify
        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert "Saved workflow 'my-workflow'" in result.output

        # Verify file exists with correct content
        saved_file = home_pflow / "my-workflow.json"
        assert saved_file.exists(), "Workflow file should be created"

        saved_data = json.loads(saved_file.read_text())
        assert saved_data["name"] == "my-workflow"
        assert saved_data["description"] == "Test workflow"
        assert saved_data["ir"]["nodes"][0]["id"] == "test"

    def test_workflow_save_auto_normalizes(self, runner: click.testing.CliRunner, tmp_path: Any) -> None:
        """Missing ir_version and edges should be auto-added."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "draft.json"
        # Workflow missing ir_version and edges
        workflow = {"nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}]}
        draft.write_text(json.dumps(workflow))

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "test-workflow", "--description", "Test"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"

        # Verify normalized fields were added
        saved_file = home_pflow / "test-workflow.json"
        saved_data = json.loads(saved_file.read_text())
        assert "ir_version" in saved_data["ir"], "Should add ir_version"
        assert "edges" in saved_data["ir"], "Should add edges"

    def test_workflow_save_rejects_invalid_workflow(self, runner: click.testing.CliRunner, tmp_path: Any) -> None:
        """Invalid workflows should be rejected before saving."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "bad.json"
        # Invalid workflow - missing required 'id' field in node
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"type": "shell", "params": {}}],  # Missing 'id'
            "edges": [],
        }
        draft.write_text(json.dumps(workflow))

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "bad-workflow", "--description", "Test"],
            env={"HOME": str(tmp_path)},
        )

        # Should fail
        assert result.exit_code != 0, "Should reject invalid workflow"

        # Should NOT create file
        saved_file = home_pflow / "bad-workflow.json"
        assert not saved_file.exists(), "Invalid workflow should not be saved"

    def test_workflow_save_validates_name_format(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Workflow names must match allowed pattern.

        After fix: ^[a-z0-9]+(?:-[a-z0-9]+)*$
        (lowercase, alphanumeric, single hyphens, must start/end with alphanumeric)
        """
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "test.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        invalid_names = [
            "My-Workflow",  # Uppercase
            "-myworkflow",  # Starts with hyphen
            "my--workflow",  # Double hyphen
            "workflow_name",  # Underscore
            "my.workflow",  # Dot
            "",  # Empty
        ]

        for invalid_name in invalid_names:
            result = runner.invoke(
                workflow_cmd,
                ["save", str(draft), "--name", invalid_name, "--description", "Test"],
                env={"HOME": str(tmp_path)},
            )

            assert result.exit_code != 0, f"Should reject invalid name: {invalid_name}"
            assert "name" in result.output.lower() or "invalid" in result.output.lower()

        # Valid names should work
        valid_names = ["myworkflow", "my-workflow", "workflow-123", "test1"]
        for valid_name in valid_names:
            result = runner.invoke(
                workflow_cmd,
                ["save", str(draft), "--name", valid_name, "--description", "Test", "--force"],
                env={"HOME": str(tmp_path)},
            )

            assert result.exit_code == 0, f"Should accept valid name: {valid_name}"

    def test_workflow_save_blocks_reserved_names(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Should reject reserved workflow names."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "test.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        reserved_names = ["null", "undefined", "none", "test", "settings", "registry", "workflow", "mcp"]

        for reserved in reserved_names:
            result = runner.invoke(
                workflow_cmd,
                ["save", str(draft), "--name", reserved, "--description", "Test"],
                env={"HOME": str(tmp_path)},
            )

            assert result.exit_code != 0, f"Should reject reserved name: {reserved}"
            assert "reserved" in result.output.lower()

    def test_workflow_save_delete_draft_flag(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """--delete-draft should remove source file after successful save."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Create draft in safe location
        draft_dir = tmp_path / ".pflow" / "workflows"
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft = draft_dir / "draft.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        assert draft.exists(), "Draft should exist before save"

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "saved-workflow", "--description", "Test", "--delete-draft"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert not draft.exists(), "Draft should be deleted after successful save"

        # Saved file should exist
        saved_file = home_pflow / "saved-workflow.json"
        assert saved_file.exists()

    def test_workflow_save_delete_draft_safety(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Should refuse to delete files outside .pflow/workflows/ for safety.

        Critical: Prevents accidental deletion of user files
        """
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Create draft in unsafe location (project root)
        unsafe_draft = tmp_path / "important-file.json"
        unsafe_draft.write_text(json.dumps(sample_workflow_ir))

        result = runner.invoke(
            workflow_cmd,
            ["save", str(unsafe_draft), "--name", "test-workflow", "--description", "Test", "--delete-draft"],
            env={"HOME": str(tmp_path)},
        )

        # Should save successfully
        assert result.exit_code == 0, f"Command failed: {result.output}"

        # But should NOT delete the unsafe file
        assert unsafe_draft.exists(), "File outside .pflow/workflows/ should NOT be deleted"

        # Should show warning
        assert "not deleting" in result.output.lower() or "warning" in result.output.lower()

    def test_workflow_save_overwrites_existing_with_force(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Saving with --force should overwrite existing workflow."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Create existing workflow
        existing = home_pflow / "my-workflow.json"
        existing_wrapper = {
            "name": "my-workflow",
            "description": "Old",
            "ir": {"ir_version": "0.1.0", "nodes": [], "edges": []},
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "version": "1.0.0",
        }
        existing.write_text(json.dumps(existing_wrapper))

        # Save new version
        draft = tmp_path / "draft.json"
        new_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "new", "type": "shell", "params": {"command": "echo new"}}],
            "edges": [],
        }
        draft.write_text(json.dumps(new_workflow))

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "my-workflow", "--description", "Updated workflow", "--force"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"

        # Verify overwrite happened
        saved_data = json.loads(existing.read_text())
        assert saved_data["ir"]["nodes"][0]["id"] == "new"

    def test_workflow_save_rejects_overwrite_without_force(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Should reject overwriting existing workflow without --force flag."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Create existing workflow
        existing = home_pflow / "my-workflow.json"
        existing_wrapper = {
            "name": "my-workflow",
            "description": "Existing",
            "ir": sample_workflow_ir,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "version": "1.0.0",
        }
        existing.write_text(json.dumps(existing_wrapper))

        # Try to save without --force
        draft = tmp_path / "draft.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "my-workflow", "--description", "New"],
            env={"HOME": str(tmp_path)},
        )

        # Should fail
        assert result.exit_code != 0, "Should reject overwrite without --force"
        assert "already exists" in result.output.lower()
        assert "--force" in result.output.lower()

    def test_workflow_save_handles_missing_draft(self, runner: click.testing.CliRunner, tmp_path: Any) -> None:
        """Should show helpful error for nonexistent draft file."""
        result = runner.invoke(
            workflow_cmd,
            ["save", "/nonexistent/draft.json", "--name", "test", "--description", "Test"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code != 0
        # Click's Path validator should catch this
        assert "does not exist" in result.output.lower() or "not found" in result.output.lower()

    def test_workflow_save_enforces_max_name_length(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Workflow names must be 50 characters or less."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "test.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        # Name with 51 characters
        long_name = "a" * 51

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", long_name, "--description", "Test"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code != 0, "Should reject names longer than 50 characters"
        assert "50 characters" in result.output.lower()

    def test_workflow_save_success_output_format(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Success output should show path and execution command."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "draft.json"
        draft.write_text(json.dumps(sample_workflow_ir))

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "test-workflow", "--description", "Test"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0
        # Should show success message
        assert "Saved workflow 'test-workflow'" in result.output
        # Should show location
        assert "Location:" in result.output
        # Should show execution command
        assert "pflow test-workflow" in result.output
