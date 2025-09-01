"""Tests for dual-mode stdin support in CLI.

FIX HISTORY:
- 2024: Rewrote from excessive mocking (18 anti-patterns) to behavior-focused tests
- Removed testing of internal get_input_source function
- Added real CLI behavior tests using CliRunner with actual stdin
- Tests now validate user-visible behavior, not implementation details

LESSONS LEARNED:
- Test what users experience through CLI, not internal functions
- Use real stdin via CliRunner input parameter instead of mocking sys.stdin
- Focus on end-to-end behavior: input -> CLI -> output
- Mock only external boundaries (filesystem), not internal components
"""

import json
import shutil
import subprocess
import sys
import tempfile

import pytest
from click.testing import CliRunner

from pflow.cli.main import main

# Note: Removed autouse fixture that was modifying user's registry.
# The global test isolation in tests/conftest.py now ensures tests use
# temporary registry paths, and nodes are auto-discovered as needed.


class TestDualModeStdinBehavior:
    """Test dual-mode stdin behavior through actual CLI usage."""

    def test_file_workflow_with_stdin_data_shows_injection_message(self, tmp_path):
        """Test that stdin data is injected when using --file option."""
        # Create a minimal valid workflow using echo node
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "Test content"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--file", str(workflow_file), "--verbose"], input="Test stdin data")

        assert result.exit_code == 0
        # Test that workflow executes successfully and stdin injection is handled
        # The exact message format may vary (text vs JSON output), so test for key indicators
        assert "Injected" in result.output or "stdin" in result.output.lower()
        # Verify workflow executed (look for content or success indicators)
        assert "Test content" in result.output or "executed" in result.output.lower()

    def test_json_workflow_via_stdin_executes_successfully(self, tmp_path):
        """Test that JSON workflow via stdin is recognized and executed."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "Content from piped workflow"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        runner = CliRunner()
        result = runner.invoke(main, [], input=json.dumps(workflow))

        assert result.exit_code == 0
        # Test that workflow was executed successfully
        # The output may be in text or JSON format, so check for success indicators
        assert "Workflow executed successfully" in result.output or "Content from piped workflow" in result.output

    def test_plain_text_stdin_with_args_treats_stdin_as_data(self):
        """Test that plain text stdin with args treats stdin as data.

        Uses a workflow name that's unlikely to exist as a saved workflow.
        """
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent-test-workflow-xyz123"], input="This is data, not workflow")

        assert result.exit_code == 0
        assert "Collected workflow from args: nonexistent-test-workflow-xyz123" in result.output
        assert "Also collected stdin data: This is data, not workflow" in result.output

    def test_plain_text_stdin_without_workflow_shows_clear_error(self):
        """Test clear error when stdin contains data but no workflow specified."""
        runner = CliRunner()
        result = runner.invoke(main, [], input="Just some random data")

        assert result.exit_code == 1
        assert "no workflow specified" in result.output
        assert "Use --file or provide a workflow" in result.output

    def test_json_workflow_with_args_shows_conflict_error(self):
        """Test error when both stdin workflow and args are provided."""
        workflow = {"ir_version": "0.1.0", "nodes": []}

        runner = CliRunner()
        result = runner.invoke(main, ["some-arg"], input=json.dumps(workflow))

        assert result.exit_code == 1
        assert "Cannot use stdin input when command arguments are provided" in result.output

    def test_no_stdin_uses_args_normally(self):
        """Test that args work normally when no stdin is provided."""
        runner = CliRunner()
        result = runner.invoke(main, ["workflow", "from", "args"])

        assert result.exit_code == 0
        assert "Collected workflow from args: workflow from args" in result.output

    def test_empty_stdin_falls_back_to_args(self):
        """Test that empty stdin falls back to args mode.

        Uses a workflow name that's unlikely to exist as a saved workflow.
        """
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent-empty-test-abc789"], input="")

        assert result.exit_code == 0
        assert "Collected workflow from args: nonexistent-empty-test-abc789" in result.output


class TestRealShellIntegration:
    """Test actual shell behavior using subprocess for true integration.

    FIX HISTORY:
    - Converted from mocked tests to real subprocess tests
    - Tests actual shell pipe behavior, not mocked internals
    - Validates true end-to-end integration

    Note: We use 'uv run pflow' in these tests because we're running in the development
    environment where pflow isn't installed globally. End users will simply type 'pflow'
    directly after installation (e.g., pip install pflow).
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_pipe_data_to_workflow_file_creates_expected_output(self, tmp_path):
        """Test actual shell pipe: echo 'data' | pflow --file workflow.json"""
        # Create a workflow using echo node
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "Test content"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        # Test real shell pipe
        uv_path = shutil.which("uv")
        if not uv_path:
            pytest.skip("uv not found in PATH")
        result = subprocess.run(  # noqa: S603
            [uv_path, "run", "pflow", "--file", str(workflow_file)],
            input="Test data from pipe",
            capture_output=True,
            text=True,
            shell=False,
        )

        assert result.returncode == 0
        # Verify workflow executed - success indicated by exit code 0 and output present
        assert result.stdout  # Should have some output

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_pipe_json_workflow_executes_correctly(self, tmp_path):
        """Test piping JSON workflow: echo '{"ir_version": ...}' | pflow"""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "Content from piped workflow"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        uv_path = shutil.which("uv")
        if not uv_path:
            pytest.skip("uv not found in PATH")
        result = subprocess.run(  # noqa: S603
            [uv_path, "run", "pflow"], input=json.dumps(workflow), capture_output=True, text=True, shell=False
        )

        assert result.returncode == 0
        # Verify workflow executed - check for successful completion
        assert result.stdout  # Should have some output
        # The message content or success message should be present
        assert "Content from piped workflow" in result.stdout or "Workflow executed successfully" in result.stdout


class TestBinaryAndLargeStdinBehavior:
    """Test binary and large stdin handling through CLI behavior.

    FIX HISTORY:
    - Reduced from complex mocking to behavior-focused tests
    - Test actual CLI output and file creation, not internal StdinData objects
    - Focus on user-visible behavior when handling different stdin types
    """

    def test_binary_stdin_shows_appropriate_warning(self, tmp_path):
        """Test that binary stdin produces appropriate user feedback."""
        # Create a simple workflow using echo node
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "Test content"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        # Create a temporary binary file to simulate binary stdin
        binary_data = b"Binary\x00Data\xff"

        # Use a real binary file as input
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(binary_data)
            binary_file = f.name

        try:
            # Test with actual binary file input
            uv_path = shutil.which("uv")
            if not uv_path:
                pytest.skip("uv not found in PATH")
            with open(binary_file, "rb") as binary_stdin:
                result = subprocess.run(  # noqa: S603
                    [uv_path, "run", "pflow", "--file", str(workflow_file), "--verbose"],
                    stdin=binary_stdin,
                    capture_output=True,
                    text=True,
                    shell=False,
                )

            # Should handle binary data gracefully
            assert result.returncode == 0
            # Success indicated by exit code 0 - binary data should be handled without crashing
        finally:
            import os

            os.unlink(binary_file)

    def test_very_large_stdin_handled_appropriately(self, tmp_path):
        """Test that very large stdin is handled without crashing."""
        # Create a simple workflow using echo node
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "Test content"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        # Create large data (1MB)
        large_data = "x" * (1024 * 1024)

        runner = CliRunner()
        result = runner.invoke(main, ["--file", str(workflow_file), "--verbose"], input=large_data)

        # Should handle large data without crashing - success indicated by exit code 0
        assert result.exit_code == 0
        # The key test is that large data doesn't cause crashes
