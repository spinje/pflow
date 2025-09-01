"""Tests for workflow save functionality in CLI."""

import json
import shutil
import subprocess

import click.testing
import pytest

from pflow.cli.main import main

# Note: Removed autouse fixture that was modifying user's registry.
# The global test isolation in tests/conftest.py now ensures tests use
# temporary registry paths, and nodes are auto-discovered as needed.


class TestWorkflowSaveCLI:
    """Test suite for workflow save functionality in CLI context."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return click.testing.CliRunner()

    @pytest.fixture
    def sample_workflow(self, tmp_path):
        """Create a sample workflow IR."""
        output_file = tmp_path / "test_output.txt"
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": str(output_file),
                        "content": "Test content",
                    },
                }
            ],
            "edges": [],
            "start_node": "writer",
        }

    def test_save_prompt_not_shown_for_file_input(self, runner, sample_workflow, tmp_path):
        """Test that save prompt is not shown when workflow comes from file."""
        # Create a workflow file
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(sample_workflow))

        # Run with file input (no --file flag needed anymore)
        result = runner.invoke(main, [str(workflow_file)])

        assert result.exit_code == 0
        assert "Save this workflow?" not in result.output

    def test_save_prompt_not_shown_in_non_interactive_mode(self, runner, sample_workflow, tmp_path):
        """Test that save prompt is not shown in non-interactive mode (piped input)."""
        # For stdin JSON workflows, we need to save to a file and reference it
        # The CLI no longer accepts JSON workflows directly via stdin
        workflow_file = tmp_path / "stdin_workflow.json"
        workflow_file.write_text(json.dumps(sample_workflow))

        # Simulate non-interactive mode (stdin is not a TTY in tests)
        # Save prompts are only shown for generated workflows from natural language
        result = runner.invoke(main, [str(workflow_file)])

        assert result.exit_code == 0
        assert "Save this workflow?" not in result.output

    def test_natural_language_workflow_placeholder(self, runner):
        """Test natural language workflow collection (before Task 17 implementation)."""
        # For now, workflows from args just show collection message
        # When Task 17 is implemented, this will process and save workflows
        result = runner.invoke(main, ["create", "a", "backup", "workflow"])

        assert result.exit_code == 0
        assert "Collected workflow from args: create a backup workflow" in result.output
        # Save prompt will be added when natural language planner is implemented
        assert "Save this workflow?" not in result.output

    def test_save_prompt_not_shown_after_execution_failure(self, runner, tmp_path):
        """Test that save prompt is not shown after execution failure."""
        # Create an invalid workflow that will fail
        invalid_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "invalid",
                    "type": "non-existent-node",
                    "params": {},
                }
            ],
            "edges": [],
            "start_node": "invalid",
        }

        # Write to file since CLI no longer accepts JSON via stdin directly
        workflow_file = tmp_path / "invalid_workflow.json"
        workflow_file.write_text(json.dumps(invalid_workflow))

        result = runner.invoke(main, [str(workflow_file)])

        assert result.exit_code == 1
        assert "Save this workflow?" not in result.output
        # Updated CLI error messaging prints a single friendly planning line
        assert "❌ Planning failed:" in result.output
        assert "non-existent-node" in result.output

    def test_no_prompt_when_stdout_is_piped(self, sample_workflow, tmp_path):
        """Test that save prompt is not shown when stdout is piped."""
        # Create a workflow file with simpler workflow
        simple_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
            "start_node": "echo1",
        }
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(simple_workflow))

        # Find uv executable
        uv = shutil.which("uv")
        if not uv:
            pytest.skip("uv not in PATH")

        # Run with stdout piped - using a simple echo workflow
        try:
            # Seed isolated HOME with minimal registry for subprocess
            import os

            temp_home = tmp_path / "home"
            pflow_dir = temp_home / ".pflow"
            pflow_dir.mkdir(parents=True, exist_ok=True)
            # Do not pre-create registry.json; allow CLI to auto-discover when missing

            env = os.environ.copy()
            env["HOME"] = str(temp_home)
            env["PFLOW_INCLUDE_TEST_NODES"] = "true"

            # Initialize registry via CLI to auto-discover core nodes
            _ = subprocess.run(  # noqa: S603
                [uv, "run", "pflow", "registry", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
                cwd=str(tmp_path),
                env=env,
            )

            completed = subprocess.run(  # noqa: S603
                [uv, "run", "pflow", "--output-format", "json", str(workflow_file)],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
                cwd=str(tmp_path),  # Use tmp_path as working directory
                env=env,
            )

            # Should complete successfully when stdout is piped (no interactive prompt)
            assert completed.returncode == 0

            # The key test: no save prompt should appear when stdout is piped
            assert "Save this workflow?" not in completed.stdout
            assert "Save this workflow?" not in completed.stderr

        except subprocess.TimeoutExpired as e:
            # Timeout means it's likely waiting for input (prompt), which is a test failure
            pytest.fail(f"Command timed out - likely showing prompt when piped: {e}")
