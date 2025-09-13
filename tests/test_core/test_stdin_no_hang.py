"""Test that stdin reading doesn't hang in non-TTY environments.

This test ensures that pflow doesn't hang when run in environments where
stdin/stdout are non-TTY but have no actual data (like Claude Code or
when piped through grep).
"""

import json
import subprocess

import pytest


def test_stdin_no_hang_when_piped(tmp_path, prepared_subprocess_env):
    """Test that pflow doesn't hang when stdout is piped (non-TTY)."""
    # Create a simple test workflow
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo 'test output'"}}],
        "edges": [],
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    try:
        # Run pflow with stdout as PIPE (simulates non-TTY like when piped to grep)
        # This tests the core issue: pflow shouldn't hang when stdout is non-TTY
        # Note: We can't use capture_output here because we need stdin=DEVNULL
        result = subprocess.run(
            ["uv", "run", "pflow", str(workflow_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # No stdin input, simulating pipe scenario
            text=True,
            env=prepared_subprocess_env,
            timeout=3,
        )

        # Should have completed without hanging
        assert result.returncode == 0, f"Unexpected return code: {result.returncode}\nstderr: {result.stderr}"
        # Check output is as expected
        assert "test output" in result.stdout or "test output" in result.stderr

    except subprocess.TimeoutExpired:
        pytest.fail("pflow hung when stdout is non-TTY (piped)")


def test_stdin_has_data_function():
    """Test the stdin_has_data function directly."""
    from pflow.core.shell_integration import stdin_has_data

    # When running in pytest, stdin should not have data
    # (unless something is explicitly piped in)
    # This test may need adjustment based on test runner environment
    result = stdin_has_data()
    # We can't assert a specific value as it depends on the test environment
    # Just ensure it doesn't hang or raise an exception
    assert isinstance(result, bool)


def test_read_stdin_no_hang(monkeypatch):
    """Test that read_stdin doesn't hang when there's no actual input."""
    import io

    from pflow.core.shell_integration import read_stdin

    # Mock stdin to simulate non-TTY with no data
    mock_stdin = io.StringIO("")
    mock_stdin.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", mock_stdin)

    # Mock select to indicate no data available
    def mock_select(rlist, wlist, xlist, timeout):
        return ([], [], [])

    monkeypatch.setattr("select.select", mock_select)

    # This should return None quickly without hanging
    result = read_stdin()

    # Should return None when no stdin data available
    assert result is None


def test_workflow_execution_with_piped_output(tmp_path, prepared_subprocess_env):
    """Integration test: workflow execution with non-TTY output (simulating pipe)."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "echo1", "type": "shell", "params": {"command": "echo 'Line 1: hello'"}},
            {"id": "echo2", "type": "shell", "params": {"command": "echo 'Line 2: world'"}},
        ],
        "edges": [{"from": "echo1", "to": "echo2"}],
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    try:
        # Run pflow with pipes (non-TTY) and verify it completes without hanging
        # Note: We can't use capture_output here because we need stdin=DEVNULL
        result = subprocess.run(
            ["uv", "run", "pflow", str(workflow_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # No stdin input
            text=True,
            env=prepared_subprocess_env,
            timeout=3,
        )

        # Should complete successfully
        assert result.returncode == 0, f"Unexpected return code: {result.returncode}\nstderr: {result.stderr}"

        # Verify the output contains expected text (at least one should appear)
        combined_output = result.stdout + result.stderr
        # Due to how shell nodes work, we may only see the last output
        assert "world" in combined_output or "hello" in combined_output

    except subprocess.TimeoutExpired:
        pytest.fail("Workflow execution hung when output is piped (non-TTY)")


def test_simulated_grep_filtering(tmp_path, prepared_subprocess_env):
    """Test that output can be filtered (like grep) without hanging."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo 'hello world'"}}],
        "edges": [],
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    try:
        # Run pflow with piped output (simulating what happens with grep)
        proc = subprocess.Popen(
            ["uv", "run", "pflow", str(workflow_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # No stdin input (like grep doesn't provide input to pflow)
            text=True,
            env=prepared_subprocess_env,
        )

        # Read output with timeout (simulating grep reading the output)
        try:
            stdout, stderr = proc.communicate(timeout=3)

            # Simulate grep filtering - check if pattern exists
            combined_output = stdout + stderr
            lines_with_hello = [line for line in combined_output.splitlines() if "hello" in line]

            # Should find the output line
            assert len(lines_with_hello) > 0, (
                f"Pattern 'hello' not found in output.\nstdout: {stdout}\nstderr: {stderr}"
            )
            assert any("hello world" in line for line in lines_with_hello)

        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("pflow hung when output is being read (simulating grep)")

    except subprocess.TimeoutExpired:
        pytest.fail("pflow hung during initialization")
