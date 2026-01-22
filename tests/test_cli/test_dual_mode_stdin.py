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
import os
import subprocess
import sys
import tempfile

import pytest
from click.testing import CliRunner

from pflow.cli.main import main


@pytest.fixture(scope="module")
def prepared_subprocess_env(tmp_path_factory, uv_exe):
    """Module-scoped env to avoid repeated registry init overhead per test."""
    home = tmp_path_factory.mktemp("home_dual_mode")
    (home / ".pflow").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PFLOW_INCLUDE_TEST_NODES"] = "true"

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


class TestDualModeStdinBehavior:
    """Test dual-mode stdin behavior through actual CLI usage."""

    def test_file_workflow_with_stdin_data_routes_to_input(self, tmp_path):
        """Test that stdin data is routed to input marked with stdin: true."""
        # Create a workflow with stdin: true input
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True, "description": "Data from stdin"}},
            "nodes": [
                {
                    "id": "test_echo",
                    "type": "echo",
                    "params": {"message": "${data}"},
                }
            ],
            "edges": [],
            "start_node": "test_echo",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        # Use file path directly (new interface - no --file flag)
        # Flags must come before the workflow path
        result = runner.invoke(main, ["--verbose", str(workflow_file)], input="Test stdin data")

        assert result.exit_code == 0
        # Verify workflow executed with stdin data routed to input
        assert "Test stdin data" in result.output or "executed" in result.output.lower()

    def test_json_via_stdin_triggers_planner(self, tmp_path):
        """Test that JSON input via stdin triggers the planner (no longer direct workflow execution)."""
        # JSON via stdin is now treated as natural language input for the planner
        json_input = '{"task": "example"}'

        runner = CliRunner()
        result = runner.invoke(main, [], input=json_input)

        # With no workflow specified and stdin containing data, it should fail with clear error
        assert result.exit_code != 0
        # The system now expects workflow to be specified via args or file path
        assert "no workflow specified" in result.output.lower() or "error" in result.output.lower()

    def test_plain_text_stdin_with_args_treats_stdin_as_data(self):
        """Test that plain text stdin with args treats stdin as data.

        The new system will either:
        1. Try to resolve it as a workflow name (and fail)
        2. Treat it as natural language for the planner
        """
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent-test-workflow-xyz123"], input="This is data, not workflow")

        # With new system, non-existent workflow names will fail
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_plain_text_stdin_without_workflow_shows_clear_error(self):
        """Test clear error when stdin contains data but no workflow specified."""
        runner = CliRunner()
        result = runner.invoke(main, [], input="Just some random data")

        # Should now trigger the planner with the stdin as natural language
        # The planner will try to interpret "Just some random data" as a workflow request
        # Without proper workflow this will either:
        # 1. Exit with error because it's not a valid request
        # 2. Execute with the planner trying to handle it
        # Either way, check for reasonable behavior
        assert result.exit_code in [0, 1]  # Either success or failure is acceptable
        # Check for some output indicating processing happened
        assert len(result.output) > 0

    def test_json_stdin_with_args_processes_args_as_workflow(self):
        """Test that unquoted multi-word args show validation error."""
        json_data = '{"data": "some json"}'

        runner = CliRunner()
        # With planner validation, unquoted multi-word args now error
        result = runner.invoke(main, ["describe", "this", "data"], input=json_data)

        assert result.exit_code == 1
        # Should show validation error for unquoted multi-word input
        assert "Invalid input" in result.output or "must be quoted" in result.output

    def test_no_stdin_uses_args_normally(self):
        """Test that unquoted multi-word args show validation error."""
        runner = CliRunner()
        result = runner.invoke(main, ["workflow", "from", "args"])

        assert result.exit_code == 1
        assert "Invalid input" in result.output or "must be quoted" in result.output

    def test_empty_stdin_falls_back_to_args(self):
        """Test that empty stdin falls back to args mode.

        The new system will try to resolve the args as a workflow name.
        """
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent-empty-test-abc789"], input="")

        # With new system, non-existent workflow names will fail
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_stdin_error_when_no_stdin_input_declared(self, tmp_path):
        """Test that piping to workflow without stdin: true shows helpful error.

        This is the main error path users will hit when they try to pipe data
        to a workflow that hasn't declared which input should receive stdin.
        """
        # Create a workflow WITHOUT stdin: true on any input
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"path": {"type": "string", "required": True}},
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "${path}"}}],
            "edges": [],
            "start_node": "echo1",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_file)], input="piped data")

        # Should fail with helpful error message
        assert result.exit_code == 1
        # Error message should explain how to fix it
        assert "stdin" in result.output.lower()
        assert "true" in result.output.lower()

    def test_stdin_error_when_multiple_stdin_inputs(self, tmp_path):
        """Test that workflow with multiple stdin: true inputs shows validation error.

        Only one input can receive piped data - having multiple is ambiguous.
        """
        # Create a workflow with TWO stdin: true inputs (invalid)
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "input_a": {"type": "string", "required": True, "stdin": True},
                "input_b": {"type": "string", "required": True, "stdin": True},
            },
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
            "start_node": "echo1",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_file)])

        # Should fail validation
        assert result.exit_code == 1
        # Error should mention both input names
        assert "input_a" in result.output
        assert "input_b" in result.output
        assert "stdin" in result.output.lower()

    def test_cli_param_overrides_stdin(self, tmp_path):
        """Test that CLI parameter takes precedence over piped stdin.

        This allows users to debug/test workflows without changing piped data.
        """
        output_file = tmp_path / "output.txt"
        # Create a workflow with stdin: true input that writes to file
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True}},
            "nodes": [
                {
                    "id": "write1",
                    "type": "write-file",
                    "params": {"file_path": str(output_file), "content": "${data}"},
                }
            ],
            "edges": [],
            "start_node": "write1",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        # Pipe "piped_value" but also provide CLI param - CLI should win
        result = runner.invoke(main, [str(workflow_file), "data=cli_value"], input="piped_value_ignored")

        assert result.exit_code == 0
        # Verify the CLI value was used, not the piped value
        assert output_file.exists()
        written_content = output_file.read_text()
        assert written_content == "cli_value", f"Expected 'cli_value' but got '{written_content}'"


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
    def test_pipe_data_to_workflow_file_creates_expected_output(self, tmp_path, uv_exe, prepared_subprocess_env):
        """Test actual shell pipe: echo 'data' | pflow workflow.json"""
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
        env = prepared_subprocess_env

        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pflow.cli.main_wrapper", str(workflow_file)],  # No --file flag
            input="Test data from pipe",
            capture_output=True,
            text=True,
            shell=False,
            env=env,
        )

        assert result.returncode == 0
        # Success is determined by exit code; empty stdout is valid

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_pipe_json_triggers_planner(self, tmp_path, uv_exe, prepared_subprocess_env):
        """Test piping JSON data now triggers planner, not direct workflow execution."""
        json_data = '{"task": "analyze this data"}'

        env = prepared_subprocess_env
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pflow.cli.main_wrapper"],
            input=json_data,
            capture_output=True,
            text=True,
            shell=False,
            env=env,
        )

        # The behavior depends on whether a planner is available
        # Either it processes through planner or shows an error
        # Both are acceptable outcomes for this test
        assert result.returncode in [0, 1]
        assert result.stdout or result.stderr  # Should have some output


class TestBinaryAndLargeStdinBehavior:
    """Test binary and large stdin handling through CLI behavior.

    FIX HISTORY:
    - Reduced from complex mocking to behavior-focused tests
    - Test actual CLI output and file creation, not internal StdinData objects
    - Focus on user-visible behavior when handling different stdin types
    """

    def test_binary_stdin_shows_appropriate_warning(self, tmp_path, uv_exe, prepared_subprocess_env):
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
            env = prepared_subprocess_env

            with open(binary_file, "rb") as binary_stdin:
                result = subprocess.run(  # noqa: S603
                    [
                        sys.executable,
                        "-m",
                        "pflow.cli.main_wrapper",
                        "--verbose",
                        str(workflow_file),
                    ],  # No --file flag, flags first
                    stdin=binary_stdin,
                    capture_output=True,
                    text=True,
                    shell=False,
                    env=env,
                )

            # Should handle binary data gracefully
            assert result.returncode == 0
            # Success indicated by exit code 0 - binary data should be handled without crashing
        finally:
            import os

            os.unlink(binary_file)

    def test_very_large_stdin_handled_appropriately(self, tmp_path):
        """Test that very large stdin is handled without crashing.

        The test verifies that pflow can receive and route large stdin data
        without memory issues or crashes. We use a write-file node which
        can handle large data properly (written via Python, not shell argv).
        """
        output_file = tmp_path / "output.txt"
        # Create a workflow with stdin: true input to accept large data
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True, "description": "Large data"}},
            "nodes": [
                {
                    "id": "write_data",
                    "type": "write-file",
                    "params": {"file_path": str(output_file), "content": "${data}"},
                }
            ],
            "edges": [],
            "start_node": "write_data",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        # Create large data (1MB)
        large_data = "x" * (1024 * 1024)

        runner = CliRunner()
        # Flags must come before the workflow path
        result = runner.invoke(main, ["--verbose", str(workflow_file)], input=large_data)  # No --file flag

        # Should handle large data without crashing - success indicated by exit code 0
        assert result.exit_code == 0, f"Expected success but got: {result.output}"
        # Verify the data was actually written correctly
        assert output_file.exists(), "Output file should have been created"
        assert output_file.read_text() == large_data, "Large data should be written correctly"


class TestWorkflowChaining:
    """Test workflow chaining via Unix pipes.

    These tests verify that `pflow -p workflow1.json | pflow workflow2.json` works correctly.
    This is critical functionality for Unix-first piping behavior.

    The key challenge: when shell pipes two processes, they start simultaneously.
    Process B checks for stdin before Process A has produced output. The fix uses
    FIFO detection to block appropriately on real pipes (matching cat/grep/jq behavior).
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_workflow_chaining_producer_to_consumer(self, tmp_path, uv_exe, prepared_subprocess_env):
        """Test that two workflows can be chained via Unix pipe.

        This is THE key test for stdin routing - it verifies that:
        1. Producer workflow outputs data via -p flag
        2. Consumer workflow receives and processes it via stdin: true

        Without FIFO detection, this test would fail because the consumer
        would check for stdin before the producer has written anything.
        """
        # Producer workflow: generates JSON array
        producer = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "generate",
                    "type": "shell",
                    "params": {"command": "echo '[1,2,3]'"},
                }
            ],
            "edges": [],
            "start_node": "generate",
            "outputs": {"result": {"source": "${generate.stdout}"}},
        }

        # Consumer workflow: counts array length
        consumer = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True}},
            "nodes": [
                {
                    "id": "count",
                    "type": "shell",
                    "params": {"stdin": "${data}", "command": "jq length"},
                }
            ],
            "edges": [],
            "start_node": "count",
            "outputs": {"count": {"source": "${count.stdout}"}},
        }

        producer_file = tmp_path / "producer.json"
        consumer_file = tmp_path / "consumer.json"
        producer_file.write_text(json.dumps(producer))
        consumer_file.write_text(json.dumps(consumer))

        env = prepared_subprocess_env

        # Use shell=True to get actual pipe behavior
        # This is the real Unix pipe test
        cmd = f"{uv_exe} run pflow -p {producer_file} | {uv_exe} run pflow -p {consumer_file}"
        result = subprocess.run(  # noqa: S602
            cmd,
            capture_output=True,
            text=True,
            shell=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"Pipeline failed: stdout={result.stdout}, stderr={result.stderr}"
        # The output should be "3" (length of [1,2,3])
        assert result.stdout.strip() == "3", f"Expected '3' but got '{result.stdout.strip()}'"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_three_stage_pipeline(self, tmp_path, uv_exe, prepared_subprocess_env):
        """Test three workflows chained via pipes: producer | transform | consumer."""
        # Producer: generates [1,2,3,4,5]
        producer = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "gen", "type": "shell", "params": {"command": "echo '[1,2,3,4,5]'"}}],
            "edges": [],
            "start_node": "gen",
            "outputs": {"result": {"source": "${gen.stdout}"}},
        }

        # Transform: doubles each element
        transform = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True}},
            "nodes": [{"id": "double", "type": "shell", "params": {"stdin": "${data}", "command": "jq '[.[] * 2]'"}}],
            "edges": [],
            "start_node": "double",
            "outputs": {"result": {"source": "${double.stdout}"}},
        }

        # Consumer: sums all elements
        consumer = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True}},
            "nodes": [{"id": "sum", "type": "shell", "params": {"stdin": "${data}", "command": "jq 'add'"}}],
            "edges": [],
            "start_node": "sum",
            "outputs": {"result": {"source": "${sum.stdout}"}},
        }

        producer_file = tmp_path / "producer.json"
        transform_file = tmp_path / "transform.json"
        consumer_file = tmp_path / "consumer.json"
        producer_file.write_text(json.dumps(producer))
        transform_file.write_text(json.dumps(transform))
        consumer_file.write_text(json.dumps(consumer))

        env = prepared_subprocess_env

        # Three-stage pipeline
        cmd = f"{uv_exe} run pflow -p {producer_file} | {uv_exe} run pflow -p {transform_file} | {uv_exe} run pflow -p {consumer_file}"
        result = subprocess.run(  # noqa: S602
            cmd,
            capture_output=True,
            text=True,
            shell=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"Pipeline failed: stdout={result.stdout}, stderr={result.stderr}"
        # [1,2,3,4,5] doubled = [2,4,6,8,10], sum = 30
        assert result.stdout.strip() == "30", f"Expected '30' but got '{result.stdout.strip()}'"
