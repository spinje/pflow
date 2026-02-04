"""Tests for `pflow workflow save` command.

Tests the CLI command that saves draft workflows to the global library.
Focuses on command-line behavior, not WorkflowManager internals.
"""

from typing import Any

import click.testing
import pytest

from pflow.cli.commands.workflow import workflow as workflow_cmd
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file


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
        """Valid workflow should save to library."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "draft.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "my-workflow"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert "Saved workflow 'my-workflow'" in result.output

        # Verify file exists (now .pflow.md with frontmatter)
        saved_file = home_pflow / "my-workflow.pflow.md"
        assert saved_file.exists(), "Workflow file should be created"

        content = saved_file.read_text()
        # Saved file should have YAML frontmatter
        assert content.startswith("---\n")
        # Should contain the workflow content
        assert "## Steps" in content
        assert "### test" in content

    def test_workflow_save_auto_normalizes(self, runner: click.testing.CliRunner, tmp_path: Any) -> None:
        """Missing ir_version and edges should be auto-added."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "draft.pflow.md"
        # Workflow missing ir_version and edges — the markdown parser
        # won't include ir_version (normalize_ir adds it)
        workflow = {"nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}]}
        write_workflow_file(workflow, draft)

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "test-workflow"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"

        # Verify file was saved
        saved_file = home_pflow / "test-workflow.pflow.md"
        assert saved_file.exists()

    def test_workflow_save_rejects_invalid_workflow(self, runner: click.testing.CliRunner, tmp_path: Any) -> None:
        """Invalid workflows should be rejected before saving."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Write a markdown file that parses but produces invalid IR (missing type on node)
        draft = tmp_path / "bad.pflow.md"
        draft.write_text("# Bad\n\nBad workflow.\n\n## Steps\n\n### node1\n\nA node.\n\n- id: node1\n")

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "bad-workflow"],
            env={"HOME": str(tmp_path)},
        )

        # Should fail
        assert result.exit_code != 0, "Should reject invalid workflow"

        # Should NOT create file
        saved_file = home_pflow / "bad-workflow.pflow.md"
        assert not saved_file.exists(), "Invalid workflow should not be saved"

    def test_workflow_save_validates_name_format(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Workflow names must match allowed pattern."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "test.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

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
                ["save", str(draft), "--name", invalid_name],
                env={"HOME": str(tmp_path)},
            )

            assert result.exit_code != 0, f"Should reject invalid name: {invalid_name}"
            assert "name" in result.output.lower() or "invalid" in result.output.lower()

        # Valid names should work
        valid_names = ["myworkflow", "my-workflow", "workflow-123", "test1"]
        for valid_name in valid_names:
            result = runner.invoke(
                workflow_cmd,
                ["save", str(draft), "--name", valid_name, "--force"],
                env={"HOME": str(tmp_path)},
            )

            assert result.exit_code == 0, f"Should accept valid name: {valid_name}"

    def test_workflow_save_blocks_reserved_names(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Should reject reserved workflow names."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        draft = tmp_path / "test.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

        reserved_names = ["null", "undefined", "none", "test", "settings", "registry", "workflow", "mcp"]

        for reserved in reserved_names:
            result = runner.invoke(
                workflow_cmd,
                ["save", str(draft), "--name", reserved],
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
        draft = draft_dir / "draft.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

        assert draft.exists(), "Draft should exist before save"

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "saved-workflow", "--delete-draft"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert not draft.exists(), "Draft should be deleted after successful save"

        # Saved file should exist
        saved_file = home_pflow / "saved-workflow.pflow.md"
        assert saved_file.exists()

    def test_workflow_save_delete_draft_safety(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Should refuse to delete files outside .pflow/workflows/ for safety."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Create draft in unsafe location (project root)
        unsafe_draft = tmp_path / "important-file.pflow.md"
        write_workflow_file(sample_workflow_ir, unsafe_draft)

        result = runner.invoke(
            workflow_cmd,
            ["save", str(unsafe_draft), "--name", "test-workflow", "--delete-draft"],
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
        from pflow.core.workflow_manager import WorkflowManager

        wm = WorkflowManager(home_pflow)
        old_ir = {"ir_version": "0.1.0", "nodes": [], "edges": []}
        wm.save("my-workflow", ir_to_markdown(old_ir, title="Old Workflow"))

        # Save new version
        draft = tmp_path / "draft.pflow.md"
        new_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "new", "type": "shell", "params": {"command": "echo new"}}],
            "edges": [],
        }
        write_workflow_file(new_workflow, draft)

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "my-workflow", "--force"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"

        # Verify overwrite happened — saved file should contain new node
        existing = home_pflow / "my-workflow.pflow.md"
        content = existing.read_text()
        assert "### new" in content

    def test_workflow_save_rejects_overwrite_without_force(
        self, runner: click.testing.CliRunner, tmp_path: Any, sample_workflow_ir: dict[str, Any]
    ) -> None:
        """Should reject overwriting existing workflow without --force flag."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        # Create existing workflow
        from pflow.core.workflow_manager import WorkflowManager

        wm = WorkflowManager(home_pflow)
        wm.save("my-workflow", ir_to_markdown(sample_workflow_ir, title="Existing"))

        # Try to save without --force
        draft = tmp_path / "draft.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "my-workflow"],
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
            ["save", "/nonexistent/draft.pflow.md", "--name", "test"],
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

        draft = tmp_path / "test.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

        # Name with 51 characters
        long_name = "a" * 51

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", long_name],
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

        draft = tmp_path / "draft.pflow.md"
        write_workflow_file(sample_workflow_ir, draft)

        result = runner.invoke(
            workflow_cmd,
            ["save", str(draft), "--name", "test-workflow"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0
        # Should show success message
        assert "Saved workflow 'test-workflow'" in result.output
        # Should show location
        assert "Location:" in result.output
        # Should show execution command
        assert "pflow test-workflow" in result.output
