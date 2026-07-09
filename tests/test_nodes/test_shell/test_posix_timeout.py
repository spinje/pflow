"""POSIX shell timeout process-group behavior."""

import subprocess
import sys
import time

import pytest

import pflow.nodes.shell.shell as shell_module
from pflow.nodes.shell.shell import ShellNode, _run_posix_shell_command


def run_shell_node(shared, **params):
    node = ShellNode()
    node.set_params(params)
    return node.run(shared)


def test_posix_runner_kills_process_group_on_timeout(monkeypatch):
    """Timeout should kill grandchildren by terminating the shell's process group."""

    class FakeProc:
        pid = 4321
        returncode = None

        def __init__(self):
            self.communicate_calls = 0
            self.communicate_timeouts = []
            self.killed = False

        def communicate(self, input=None, timeout=None, **kwargs):  # noqa: A002 - mirrors subprocess API.
            self.communicate_calls += 1
            self.communicate_timeouts.append(timeout)
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired("sleep 10", timeout or 0, output=b"partial", stderr=b"err")
            self.returncode = -9
            return b"captured", b"stderr"

        def kill(self):
            self.killed = True

    fake_proc = FakeProc()
    popen_calls = []
    killpg_calls = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return fake_proc

    def fake_getpgid(pid):
        return pid + 100

    def fake_killpg(pgid, sig):
        killpg_calls.append((pgid, sig))

    monkeypatch.setattr(shell_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(shell_module.os, "getpgid", fake_getpgid, raising=False)
    monkeypatch.setattr(shell_module.os, "killpg", fake_killpg, raising=False)
    monkeypatch.setattr(shell_module.signal, "SIGKILL", 9, raising=False)

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        _run_posix_shell_command(
            "sleep 10",
            stdin_bytes=None,
            cwd=None,
            env={"PATH": "x"},
            timeout=0.1,
        )

    assert popen_calls[0][0][0] == "sleep 10"
    assert popen_calls[0][1] == {
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": None,
        "cwd": None,
        "env": {"PATH": "x"},
        "start_new_session": True,
    }
    assert killpg_calls == [(4421, 9)]
    assert fake_proc.killed is True
    assert fake_proc.communicate_timeouts == [0.1, 1]
    assert exc_info.value.output == b"captured"
    assert exc_info.value.stderr == b"stderr"


def test_posix_runner_timeout_uses_partial_output_when_drain_still_times_out(monkeypatch):
    """A missed pipe holder must not make timeout recovery block indefinitely."""

    class FakeProc:
        pid = 4321

        def communicate(self, input=None, timeout=None, **kwargs):  # noqa: A002 - mirrors subprocess API.
            raise subprocess.TimeoutExpired("sleep 10", timeout or 0, output=b"partial", stderr=b"err")

        def kill(self):
            pass

    monkeypatch.setattr(shell_module.subprocess, "Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(shell_module.os, "getpgid", lambda pid: pid + 100, raising=False)
    monkeypatch.setattr(shell_module.os, "killpg", lambda pgid, sig: None, raising=False)
    monkeypatch.setattr(shell_module.signal, "SIGKILL", 9, raising=False)

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        _run_posix_shell_command(
            "sleep 10",
            stdin_bytes=None,
            cwd=None,
            env={"PATH": "x"},
            timeout=0.1,
        )

    assert exc_info.value.output == b"partial"
    assert exc_info.value.stderr == b"err"


@pytest.mark.parametrize("raised", [KeyboardInterrupt, SystemExit])
def test_posix_runner_kills_process_group_on_interrupt(monkeypatch, raised):
    """Ctrl-C/SystemExit should not leave the shell process group orphaned."""

    class FakeProc:
        pid = 4321

        def __init__(self):
            self.communicate_calls = 0
            self.killed = False

        def communicate(self, input=None, timeout=None, **kwargs):  # noqa: A002 - mirrors subprocess API.
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise raised()
            return b"", b""

        def kill(self):
            self.killed = True

    fake_proc = FakeProc()
    killpg_calls = []

    monkeypatch.setattr(shell_module.subprocess, "Popen", lambda *args, **kwargs: fake_proc)
    monkeypatch.setattr(shell_module.os, "getpgid", lambda pid: pid + 100, raising=False)
    monkeypatch.setattr(shell_module.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)), raising=False)
    monkeypatch.setattr(shell_module.signal, "SIGKILL", 9, raising=False)

    with pytest.raises(raised):
        _run_posix_shell_command(
            "sleep 10",
            stdin_bytes=None,
            cwd=None,
            env={"PATH": "x"},
            timeout=0.1,
        )

    assert killpg_calls == [(4421, 9)]
    assert fake_proc.killed is True
    assert fake_proc.communicate_calls == 2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups are not available on Windows")
def test_shell_timeout_kills_grandchild_holding_stdout_pipe():
    """A real grandchild that inherits stdout must not keep communicate() blocked."""
    shared = {}
    start = time.monotonic()

    action = run_shell_node(shared, command="sleep 2 | cat", timeout=0.05)

    elapsed = time.monotonic() - start
    assert elapsed < 0.5
    assert action == "error"
    assert shared["exit_code"] == -1
    assert "timed out" in shared["error"]
