"""Test that stdin reading doesn't hang in non-TTY environments.

This test ensures that pflow doesn't hang when run in environments where
stdin/stdout are non-TTY but have no actual data (like Claude Code or
when piped through grep).
"""

import json
import subprocess

import pytest


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


def test_read_stdin_enhanced_no_hang(monkeypatch):
    """Test that read_stdin_enhanced doesn't hang when there's no actual input."""
    import io

    from pflow.core.shell_integration import read_stdin_enhanced

    # Mock stdin to simulate non-TTY with no data
    mock_stdin = io.StringIO("")
    mock_stdin.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", mock_stdin)

    # Mock select to indicate no data available
    def mock_select(rlist, wlist, xlist, timeout):
        return ([], [], [])

    monkeypatch.setattr("select.select", mock_select)

    # This should return None quickly without hanging
    result = read_stdin_enhanced()

    # Should return None when no stdin data available
    assert result is None


def test_stdin_has_data_with_fifo(monkeypatch):
    """Test stdin_has_data returns True for FIFO pipes."""
    import stat

    from pflow.core.shell_integration import stdin_has_data

    # Mock stdin as FIFO pipe
    class MockStdin:
        closed = False

        def isatty(self):
            return False

        def fileno(self):
            return 0

    monkeypatch.setattr("sys.stdin", MockStdin())

    # Mock os.fstat to return FIFO mode
    class MockStatResult:
        st_mode = stat.S_IFIFO | 0o644

    monkeypatch.setattr("os.fstat", lambda fd: MockStatResult())

    # Should return True for FIFO
    assert stdin_has_data() is True


def test_stdin_has_data_non_fifo_returns_false(monkeypatch):
    """Test stdin_has_data returns False for non-FIFO (e.g., char device, socket).

    This is the simplified behavior - only FIFOs are read.
    Non-FIFO stdin (like in Claude Code) returns False to avoid hanging.
    """
    import stat

    from pflow.core.shell_integration import stdin_has_data

    # Mock stdin as character device (like in Claude Code)
    class MockStdin:
        closed = False

        def isatty(self):
            return False

        def fileno(self):
            return 0

    monkeypatch.setattr("sys.stdin", MockStdin())

    # Mock os.fstat to return character device mode (NOT FIFO)
    class MockStatResult:
        st_mode = stat.S_IFCHR | 0o644  # Character device

    monkeypatch.setattr("os.fstat", lambda fd: MockStatResult())

    # Should return False for non-FIFO
    assert stdin_has_data() is False


def test_stdin_has_data_returns_true_for_fifo(monkeypatch):
    """Test stdin_has_data returns True immediately for FIFO pipes.

    This is critical for workflow chaining (pflow A | pflow B).
    When stdin is a FIFO pipe, we return True immediately so the caller
    blocks on read() - matching Unix tool behavior (cat, grep, jq).
    """
    import stat

    from pflow.core.shell_integration import stdin_has_data

    # Mock stdin as non-TTY FIFO pipe
    class MockFileno:
        def __call__(self):
            return 0  # fake fd

    class MockStdin:
        def isatty(self):
            return False

        @property
        def closed(self):
            return False

        def fileno(self):
            return 0

    mock_stdin = MockStdin()
    monkeypatch.setattr("sys.stdin", mock_stdin)

    # Mock os.fstat to return FIFO mode
    class MockStatResult:
        st_mode = stat.S_IFIFO | 0o644  # FIFO with read/write permissions

    def mock_fstat(fd):
        return MockStatResult()

    monkeypatch.setattr("os.fstat", mock_fstat)

    # Should return True immediately for FIFO without checking select
    # This is the key behavior for workflow chaining
    assert stdin_has_data() is True


def test_stdin_has_data_socket_returns_false(monkeypatch):
    """Test stdin_has_data returns False for socket stdin.

    The simplified implementation only reads FIFOs.
    Sockets (like in some environments) return False to avoid potential hangs.
    """
    import stat

    from pflow.core.shell_integration import stdin_has_data

    # Mock stdin as socket (not FIFO)
    class MockStdin:
        closed = False

        def isatty(self):
            return False

        def fileno(self):
            return 0

    monkeypatch.setattr("sys.stdin", MockStdin())

    # Mock os.fstat to return socket mode (NOT FIFO)
    class MockStatResult:
        st_mode = stat.S_IFSOCK | 0o644  # Socket, not FIFO

    monkeypatch.setattr("os.fstat", lambda fd: MockStatResult())

    # Should return False for socket (not a FIFO)
    assert stdin_has_data() is False


# Integration test - only ONE subprocess test to verify the actual fix
@pytest.mark.integration
@pytest.mark.serial
def test_stdin_no_hang_integration(tmp_path):
    """Integration test: verify pflow doesn't hang when piped through grep.

    This is the only subprocess test - it verifies the actual bug is fixed.
    All other tests are unit tests for better performance.
    """
    import os

    # Create a simple test workflow
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo 'test output'"}}],
        "edges": [],
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Create minimal env - we don't need the full registry for this test
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PFLOW_INCLUDE_TEST_NODES"] = "true"

    # Create minimal .pflow directory with just the shell node
    pflow_dir = tmp_path / ".pflow"
    pflow_dir.mkdir(exist_ok=True)  # exist_ok=True in case conftest already created it
    registry_data = {"nodes": {"shell": {"module": "pflow.nodes.shell.shell", "class_name": "ShellNode"}}}
    (pflow_dir / "registry.json").write_text(json.dumps(registry_data))

    try:
        # Run pflow with stdout as PIPE (simulates non-TTY like when piped to grep)
        # This tests the core issue: pflow shouldn't hang when stdout is non-TTY
        result = subprocess.run(
            ["uv", "run", "pflow", str(workflow_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # No stdin input, simulating pipe scenario
            text=True,
            env=env,
            timeout=2,  # Shorter timeout - if it doesn't hang, it completes quickly
        )

        # Should have completed without hanging
        assert result.returncode == 0, f"Unexpected return code: {result.returncode}\nstderr: {result.stderr}"
        # Check output is as expected
        assert "test output" in result.stdout or "test output" in result.stderr

    except subprocess.TimeoutExpired:
        pytest.fail("pflow hung when stdout is non-TTY (piped)")
