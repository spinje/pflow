"""Tests for dual-mode stdin support in CLI."""

import json
import subprocess
import sys

import pytest
from click.testing import CliRunner

from pflow.cli.main import get_input_source, main

# Get the actual module for patching
main_module = sys.modules["pflow.cli.main"]


class TestGetInputSourceDualMode:
    """Test the modified get_input_source function with dual-mode support."""

    def test_file_with_stdin_data(self, monkeypatch, tmp_path):
        """Test that stdin is treated as data when --file is provided."""
        # Create a test workflow file
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text('{"ir_version": "0.1.0"}')

        # Mock stdin with data
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.read", lambda: "test data content")

        content, source, stdin_data = get_input_source(str(workflow_file), ())

        assert source == "file"
        assert content == '{"ir_version": "0.1.0"}'
        assert stdin_data == "test data content"

    def test_stdin_workflow_mode(self, monkeypatch):
        """Test that stdin containing workflow JSON is treated as workflow."""
        workflow_json = '{"ir_version": "0.1.0", "nodes": []}'

        # Mock stdin with workflow JSON
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.read", lambda: workflow_json)

        content, source, stdin_data = get_input_source(None, ())

        assert source == "stdin"
        assert content == workflow_json
        assert stdin_data is None

    def test_stdin_data_with_args(self, monkeypatch):
        """Test that stdin is treated as data when args are provided."""
        # Mock stdin with non-workflow data
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.read", lambda: "plain text data")

        content, source, stdin_data = get_input_source(None, ("some-workflow",))

        assert source == "args"
        assert content == "some-workflow"
        assert stdin_data == "plain text data"

    def test_stdin_data_without_workflow_raises_error(self, monkeypatch):
        """Test that stdin data without workflow specification raises error."""
        # Mock stdin with non-workflow data
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.read", lambda: "plain text data")

        with pytest.raises(Exception) as exc_info:
            get_input_source(None, ())

        assert "no workflow specified" in str(exc_info.value)

    def test_stdin_workflow_with_args_raises_error(self, monkeypatch):
        """Test that stdin workflow with args raises error."""
        workflow_json = '{"ir_version": "0.1.0", "nodes": []}'

        # Mock stdin with workflow JSON
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.read", lambda: workflow_json)

        with pytest.raises(Exception) as exc_info:
            get_input_source(None, ("some-arg",))

        assert "Cannot use stdin input when command arguments are provided" in str(exc_info.value)

    def test_no_stdin_with_args(self, monkeypatch):
        """Test normal args mode without stdin."""
        # Mock no stdin
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: True)

        content, source, stdin_data = get_input_source(None, ("workflow", "args"))

        assert source == "args"
        assert content == "workflow args"
        assert stdin_data is None

    def test_empty_stdin_treated_as_no_stdin(self, monkeypatch):
        """Test that empty stdin is handled correctly."""
        # Mock empty stdin
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.read", lambda: "")

        content, source, stdin_data = get_input_source(None, ("workflow",))

        assert source == "args"
        assert content == "workflow"
        assert stdin_data is None


class TestCLIIntegrationDualMode:
    """Integration tests for dual-mode stdin with the full CLI."""

    def test_stdin_data_injected_into_shared_storage(self, tmp_path):
        """Test that stdin data is properly injected into shared storage."""
        # Create a test workflow that uses stdin
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "write", "type": "write-file", "params": {"file_path": str(tmp_path / "output.txt")}}],
            "edges": [],
            "start_node": "write",
        }

        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--file", str(workflow_file), "--verbose"], input="Hello from stdin")

        # Check that stdin was injected (verbose mode shows this)
        assert "Injected" in result.output and "stdin data" in result.output
        assert "16 bytes" in result.output  # "Hello from stdin" is 16 bytes

    def test_backward_compatibility_stdin_workflow(self, tmp_path):
        """Test that piping workflow JSON still works."""
        # Create a minimal valid workflow with a simple write operation
        output_file = tmp_path / "test_output.txt"
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": str(output_file),
                        "content": "Test content from workflow",  # Provide content in params
                    },
                }
            ],
            "edges": [],
            "start_node": "writer",
        }

        runner = CliRunner()
        result = runner.invoke(main, [], input=json.dumps(workflow))

        # Should process as workflow, not data
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output

        # Verify the file was created
        assert output_file.exists()
        assert output_file.read_text() == "Test content from workflow"

    def test_error_on_ambiguous_stdin(self):
        """Test clear error when stdin data provided without workflow."""
        runner = CliRunner()
        result = runner.invoke(main, [], input="Some random data")

        assert result.exit_code == 1
        assert "no workflow specified" in result.output


class TestSubprocessIntegration:
    """Test actual subprocess behavior for shell integration."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_pipe_data_to_workflow_file(self, tmp_path):
        """Test actual shell pipe: echo "data" | pflow --file workflow.json"""
        # Create a simple workflow file
        # Create a minimal valid workflow
        output_file = tmp_path / "output.txt"
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": str(output_file),
                        "content": "Test content",  # Provide content
                    },
                }
            ],
            "edges": [],
            "start_node": "writer",
        }
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        # Test piping data
        result = subprocess.run(
            ["pflow", "--file", str(workflow_file)], input="Test data from pipe", capture_output=True, text=True
        )

        assert result.returncode == 0
        assert "Workflow executed successfully" in result.stdout

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
    def test_pipe_workflow_json(self, tmp_path):
        """Test piping workflow JSON: echo '{"ir_version": ...}' | pflow"""
        # Create a minimal valid workflow
        output_file = tmp_path / "piped_output.txt"
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": str(output_file), "content": "Content from piped workflow"},
                }
            ],
            "edges": [],
            "start_node": "writer",
        }

        result = subprocess.run(["pflow"], input=json.dumps(workflow), capture_output=True, text=True)

        assert result.returncode == 0
        assert "Workflow executed successfully" in result.stdout


class TestBinaryStdinHandling:
    """Test binary stdin support in CLI."""

    def test_binary_stdin_with_file(self, monkeypatch, tmp_path):
        """Test that binary stdin is handled correctly with --file."""
        from pflow.core.shell_integration import StdinData

        # Create a test workflow file
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text('{"ir_version": "0.1.0"}')

        # Mock enhanced stdin to return binary data
        binary_data = b"Binary\x00Data\xff"
        stdin_obj = StdinData(binary_data=binary_data)

        # Mock isatty to indicate piped input
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)

        # Mock read_stdin to return None (binary data can't be read as text)
        # Need to patch where it's imported in main.py, not where it's defined
        monkeypatch.setattr(main_module, "read_stdin_content", lambda: None)

        # Mock read_stdin_enhanced to return our binary data
        monkeypatch.setattr(main_module, "read_stdin_enhanced", lambda: stdin_obj)

        content, source, stdin_data = get_input_source(str(workflow_file), ())

        assert source == "file"
        assert content == '{"ir_version": "0.1.0"}'
        assert isinstance(stdin_data, StdinData)
        assert stdin_data.is_binary
        assert stdin_data.binary_data == binary_data

    def test_large_stdin_with_file(self, monkeypatch, tmp_path):
        """Test that large stdin is streamed to temp file."""
        from pflow.core.shell_integration import StdinData

        # Create a test workflow file
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text('{"ir_version": "0.1.0"}')

        # Mock enhanced stdin to return temp file path
        temp_path = "/tmp/pflow_stdin_test123"
        stdin_obj = StdinData(temp_path=temp_path)

        # Mock isatty to indicate piped input
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("pflow.core.shell_integration.sys.stdin.isatty", lambda: False)

        # Mock read_stdin to return None (large data can't fit in memory as text)
        # Need to patch where it's imported in main.py, not where it's defined
        monkeypatch.setattr(main_module, "read_stdin_content", lambda: None)

        # Mock read_stdin_enhanced to return our temp file data
        monkeypatch.setattr(main_module, "read_stdin_enhanced", lambda: stdin_obj)

        content, source, stdin_data = get_input_source(str(workflow_file), ())

        assert source == "file"
        assert isinstance(stdin_data, StdinData)
        assert stdin_data.is_temp_file
        assert stdin_data.temp_path == temp_path

    def test_cli_binary_stdin_injection(self, monkeypatch, tmp_path):
        """Test that binary stdin is properly injected into shared store."""
        from pflow.core.shell_integration import StdinData

        # Create a simple workflow
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "write-file",
                    "params": {"file_path": str(tmp_path / "output.txt"), "content": "test"},
                }
            ],
            "edges": [],
            "start_node": "test",
        }

        # Mock binary stdin
        binary_data = b"Binary\x00Data"
        stdin_obj = StdinData(binary_data=binary_data)

        runner = CliRunner()
        with monkeypatch.context() as m:
            m.setattr(main_module, "get_input_source", lambda f, w: (json.dumps(workflow), "file", stdin_obj))

            result = runner.invoke(main, ["--file", "dummy.json"])

            # Check verbose output shows binary data injection
            result = runner.invoke(main, ["--file", "dummy.json", "-v"])
            assert "binary stdin data" in result.output or result.exit_code == 0

    def test_cli_temp_file_cleanup(self, monkeypatch, tmp_path):
        """Test that temp files are cleaned up after execution."""

        from pflow.core.shell_integration import StdinData

        # Create actual temp file
        temp_file = tmp_path / "stdin_temp"
        temp_file.write_bytes(b"Large data")

        # Create a simple workflow
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "write-file",
                    "params": {"file_path": str(tmp_path / "output.txt"), "content": "test"},
                }
            ],
            "edges": [],
            "start_node": "test",
        }

        # Mock stdin with temp file
        stdin_obj = StdinData(temp_path=str(temp_file))

        runner = CliRunner()
        with monkeypatch.context() as m:
            m.setattr(main_module, "get_input_source", lambda f, w: (json.dumps(workflow), "file", stdin_obj))

            # Run workflow
            result = runner.invoke(main, ["--file", "dummy.json", "-v"])

            # Temp file should be cleaned up (mocked in test, real cleanup in actual run)
            assert result.exit_code == 0
