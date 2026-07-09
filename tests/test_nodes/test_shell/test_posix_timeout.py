"""POSIX shell timeout process-group behavior."""

import subprocess

import pytest

import pflow.nodes.shell.shell as shell_module
from pflow.nodes.shell.shell import _run_posix_shell_command


def test_posix_runner_kills_process_group_on_timeout(monkeypatch):
    """Timeout should kill grandchildren by terminating the shell's process group."""

    class FakeProc:
        pid = 4321
        returncode = None

        def __init__(self):
            self.communicate_calls = 0
            self.killed = False

        def communicate(self, stdin_data=None, timeout=None, **kwargs):
            self.communicate_calls += 1
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
    assert exc_info.value.output == b"captured"
    assert exc_info.value.stderr == b"stderr"
