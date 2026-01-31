"""Test that stdin reading doesn't hang in non-TTY environments.

This test ensures that pflow doesn't hang when run in environments where
stdin/stdout are non-TTY but have no actual data (like Claude Code or
when piped through grep).

Key behavior tested:
- FIFO pipes (real shell pipes): stdin_has_data() returns True
- Non-FIFO (char devices, sockets): stdin_has_data() returns False
- StringIO (CliRunner): stdin_has_data() returns False
- Integration: pflow subprocess doesn't hang with non-TTY stdout

Note: stdin_has_data() uses FIFO-only detection (stat.S_ISFIFO), NOT select().
select() was removed in Task 115 Session 6 because it lies on character devices
(returns "ready" even when no data exists, causing stdin.read() to hang forever).
See shell_integration.py docstring and Task 115 progress log for full history.
"""

import json
import subprocess

import pytest


def test_stdin_has_data_returns_false_in_test_environment():
    """stdin_has_data returns False in pytest (no real pipe)."""
    from pflow.core.shell_integration import stdin_has_data

    result = stdin_has_data()
    assert isinstance(result, bool)
    # In pytest, stdin is not a FIFO pipe
    assert result is False


def test_stdin_has_data_returns_true_for_fifo(monkeypatch):
    """stdin_has_data returns True for FIFO pipes (real shell pipes).

    Critical for workflow chaining (pflow A | pflow B).
    """
    import stat

    from pflow.core.shell_integration import stdin_has_data

    class MockStdin:
        closed = False

        def isatty(self):
            return False

        def fileno(self):
            return 0

    monkeypatch.setattr("sys.stdin", MockStdin())
    monkeypatch.setattr(
        "os.fstat",
        lambda fd: type("StatResult", (), {"st_mode": stat.S_IFIFO | 0o644})(),
    )

    assert stdin_has_data() is True


def test_stdin_has_data_returns_false_for_char_device(monkeypatch):
    """stdin_has_data returns False for character devices (e.g. Claude Code).

    This is the original regression case (BF-20250112-stdin-hang-nontty-grep):
    Claude Code's stdin is a char device (S_ISCHR=True) where select() returns
    "ready" but read() hangs forever. FIFO-only detection avoids this.
    Not a duplicate of the socket test — char device is the specific environment
    that triggered the original bug.
    """
    import stat

    from pflow.core.shell_integration import stdin_has_data

    class MockStdin:
        closed = False

        def isatty(self):
            return False

        def fileno(self):
            return 0

    monkeypatch.setattr("sys.stdin", MockStdin())
    monkeypatch.setattr(
        "os.fstat",
        lambda fd: type("StatResult", (), {"st_mode": stat.S_IFCHR | 0o644})(),
    )

    assert stdin_has_data() is False


def test_stdin_has_data_returns_false_for_socket(monkeypatch):
    """stdin_has_data returns False for sockets."""
    import stat

    from pflow.core.shell_integration import stdin_has_data

    class MockStdin:
        closed = False

        def isatty(self):
            return False

        def fileno(self):
            return 0

    monkeypatch.setattr("sys.stdin", MockStdin())
    monkeypatch.setattr(
        "os.fstat",
        lambda fd: type("StatResult", (), {"st_mode": stat.S_IFSOCK | 0o644})(),
    )

    assert stdin_has_data() is False


def test_stdin_has_data_returns_false_for_stringio(monkeypatch):
    """stdin_has_data returns False for StringIO (CliRunner tests).

    StringIO has no fileno(), so we can't check S_ISFIFO.
    """
    import io

    from pflow.core.shell_integration import stdin_has_data

    mock_stdin = io.StringIO("")
    mock_stdin.isatty = lambda: False  # type: ignore[assignment]
    monkeypatch.setattr("sys.stdin", mock_stdin)

    assert stdin_has_data() is False


def test_read_stdin_returns_none_without_fifo(monkeypatch):
    """read_stdin returns None when stdin is not a FIFO pipe."""
    import io

    from pflow.core.shell_integration import read_stdin

    mock_stdin = io.StringIO("")
    mock_stdin.isatty = lambda: False  # type: ignore[assignment]
    monkeypatch.setattr("sys.stdin", mock_stdin)

    assert read_stdin() is None


def test_read_stdin_enhanced_returns_none_without_fifo(monkeypatch):
    """read_stdin_enhanced returns None when stdin is not a FIFO pipe."""
    import io

    from pflow.core.shell_integration import read_stdin_enhanced

    mock_stdin = io.StringIO("")
    mock_stdin.isatty = lambda: False  # type: ignore[assignment]
    monkeypatch.setattr("sys.stdin", mock_stdin)

    assert read_stdin_enhanced() is None


@pytest.mark.integration
@pytest.mark.serial
def test_stdin_no_hang_integration(tmp_path, uv_exe):
    """Integration test: pflow doesn't hang when stdout is non-TTY.

    Verifies the core bug fix: when pflow is piped (e.g. `pflow ... | grep`),
    it should complete normally instead of hanging on stdin.read().

    Uses a minimal registry (only shell node) to keep subprocess startup fast.
    The signal here is "did it complete within timeout" so startup speed matters.
    """
    import os

    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo 'test output'"}}],
        "edges": [],
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Deliberately NOT using prepared_subprocess_env here. This test detects hangs
    # via timeout, so subprocess startup speed directly affects reliability.
    # A minimal registry (one node) starts faster than the full registry (~30 nodes).
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PFLOW_INCLUDE_TEST_NODES"] = "true"

    pflow_dir = tmp_path / ".pflow"
    pflow_dir.mkdir(exist_ok=True)
    registry_data = {"nodes": {"shell": {"module": "pflow.nodes.shell.shell", "class_name": "ShellNode"}}}
    (pflow_dir / "registry.json").write_text(json.dumps(registry_data))

    try:
        result = subprocess.run(
            [uv_exe, "run", "pflow", str(workflow_path)],
            stdout=subprocess.PIPE,  # Non-TTY stdout — this is the test condition
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # No stdin data — the scenario that triggered the original hang
            text=True,
            env=env,
            timeout=5,
        )

        assert result.returncode == 0, f"Unexpected return code: {result.returncode}\nstderr: {result.stderr}"
        assert "test output" in result.stdout or "test output" in result.stderr

    except subprocess.TimeoutExpired:
        pytest.fail("pflow hung when stdout is non-TTY (piped)")
