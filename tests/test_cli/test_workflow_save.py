"""Tests for workflow save functionality in CLI."""

import os
import subprocess
import sys

import click.testing
import pytest

from pflow.cli.main import main
from tests.shared.markdown_utils import write_workflow_file


@pytest.fixture(scope="module")
def prepared_subprocess_env(tmp_path_factory, uv_exe):
    """Module-scoped env to avoid repeated registry init overhead per test."""
    home = tmp_path_factory.mktemp("home_workflow_save")
    (home / ".pflow").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)

    subprocess.run(  # noqa: S603
        [uv_exe, "run", "pflow", "registry", "list", "--json"],
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )

    return env


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
        workflow_file = tmp_path / "workflow.pflow.md"
        write_workflow_file(sample_workflow, workflow_file)

        # Run with file input (no --file flag needed anymore)
        result = runner.invoke(main, [str(workflow_file)])

        assert result.exit_code == 0
        assert "Save this workflow?" not in result.output

    def test_save_prompt_not_shown_in_non_interactive_mode(self, runner, sample_workflow, tmp_path):
        """Test that save prompt is not shown in non-interactive mode (piped input)."""
        workflow_file = tmp_path / "stdin_workflow.pflow.md"
        write_workflow_file(sample_workflow, workflow_file)

        # Simulate non-interactive mode (stdin is not a TTY in tests)
        # Save prompts are only shown for generated workflows from natural language
        result = runner.invoke(main, [str(workflow_file)])

        assert result.exit_code == 0
        assert "Save this workflow?" not in result.output

    def test_natural_language_workflow_placeholder(self, runner):
        """Test that unquoted multi-word input shows validation error."""
        # With planner validation, unquoted multi-word input now errors
        result = runner.invoke(main, ["create", "a", "backup", "workflow"])

        assert result.exit_code == 1
        assert "Invalid input" in result.output or "must be quoted" in result.output

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
        workflow_file = tmp_path / "invalid_workflow.pflow.md"
        write_workflow_file(invalid_workflow, workflow_file)

        result = runner.invoke(main, [str(workflow_file)])

        assert result.exit_code == 1
        assert "Save this workflow?" not in result.output
        # Check that the specific error is shown (validation catches unknown node type)
        assert "non-existent-node" in result.output or "Unknown node type" in result.output

    def test_no_prompt_when_stdout_is_piped(self, sample_workflow, tmp_path, uv_exe, prepared_subprocess_env):
        """Test that save prompt is not shown when stdout is piped."""
        # Create a workflow file with simpler workflow
        simple_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
            "start_node": "echo1",
        }
        workflow_file = tmp_path / "workflow.pflow.md"
        write_workflow_file(simple_workflow, workflow_file)

        # Find uv executable
        _ = uv_exe  # Ensure fixture is requested for skip behavior without using it

        # Run with stdout piped - using a simple echo workflow
        try:
            # Use prepared env with isolated HOME and initialized registry
            env = prepared_subprocess_env

            completed = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "pflow.cli", "--output-format", "json", str(workflow_file)],
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
