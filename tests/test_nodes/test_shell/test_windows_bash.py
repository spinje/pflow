"""Bash-on-Windows for the shell node (Task 116, ADR-0013).

Covers the three pieces that make "POSIX sh everywhere" hold on win32:
1. _resolve_windows_bash() — deliberate Git Bash resolution (WSL trap rejected)
2. exec() argv shape — ["bash", "-c", command], no shell=True
3. The prep-raise design — a missing bash must raise from prep(), where it is
   immune to exec_fallback's swallow-everything conversion AND to
   ignore_errors: true. Raising from exec() instead would turn a missing
   shell into a silent green run with empty stdout (the deep-review Critical
   this design exists to prevent) — the ignore_errors test below goes red if
   anyone "simplifies" the raise back into exec().

All tests run on Linux: win32 behavior is reached by monkeypatching
sys.platform; real-Windows verification is the CI windows-latest job.
"""

import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

from pflow.core.user_errors import UserFriendlyError
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.nodes.shell import shell as shell_module
from pflow.nodes.shell.shell import ShellNode, _resolve_windows_bash


class TestResolveWindowsBash:
    """Resolution order: PFLOW_BASH > PATH (non-System32) > git-derived > defaults."""

    @pytest.fixture(autouse=True)
    def _no_ambient_resolution(self, monkeypatch):
        """Default every source to 'not found' so each test enables exactly one."""
        monkeypatch.delenv("PFLOW_BASH", raising=False)
        monkeypatch.setattr(shell_module.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(shell_module, "_GIT_BASH_DEFAULT_PATHS", ())

    def test_pflow_bash_override_wins(self, monkeypatch):
        """PFLOW_BASH is trusted verbatim — no existence check (the user set it
        deliberately; a wrong path surfaces as a subprocess error naming it)."""
        monkeypatch.setenv("PFLOW_BASH", r"D:\custom\bash.exe")
        monkeypatch.setattr(shell_module.shutil, "which", lambda cmd: r"C:\Program Files\Git\bin\bash.exe")
        assert _resolve_windows_bash() == r"D:\custom\bash.exe"

    def test_empty_pflow_bash_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("PFLOW_BASH", "")
        assert _resolve_windows_bash() is None

    def test_bash_on_path_accepted(self, monkeypatch):
        monkeypatch.setattr(
            shell_module.shutil,
            "which",
            lambda cmd: r"C:\Program Files\Git\bin\bash.exe" if cmd == "bash" else None,
        )
        assert _resolve_windows_bash() == r"C:\Program Files\Git\bin\bash.exe"

    @pytest.mark.parametrize(
        "wsl_path",
        [r"C:\Windows\System32\bash.exe", r"c:\windows\system32\bash.exe", r"C:\WINDOWS\SYSTEM32\bash.exe"],
    )
    def test_system32_bash_rejected(self, monkeypatch, wsl_path):
        """The WSL trap (ADR-0013): System32 bash is a Linux VM, not a Windows
        shell. Case-insensitive, and CI can never catch this — runners have Git
        Bash on PATH — so this unit test is the only guard."""
        monkeypatch.setattr(shell_module.shutil, "which", lambda cmd: wsl_path if cmd == "bash" else None)
        assert _resolve_windows_bash() is None

    def test_system32_rejection_falls_through_to_git(self, monkeypatch, tmp_path):
        """Rejecting WSL bash continues resolution instead of giving up."""
        git_exe = tmp_path / "Git" / "cmd" / "git.exe"
        git_bash = tmp_path / "Git" / "bin" / "bash.exe"
        for f in (git_exe, git_bash):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.touch()

        def which(cmd):
            return {"bash": r"C:\Windows\System32\bash.exe", "git": str(git_exe)}.get(cmd)

        monkeypatch.setattr(shell_module.shutil, "which", which)
        assert _resolve_windows_bash() == str(git_bash)

    @pytest.mark.parametrize(
        ("git_rel", "bash_rel"),
        [
            ("Git/cmd/git.exe", "Git/bin/bash.exe"),  # standard PATH entry
            ("Git/cmd/git.exe", "Git/usr/bin/bash.exe"),  # bin/ absent, usr/bin present
            ("Git/bin/git.exe", "Git/bin/bash.exe"),  # git.exe from Git\bin
            ("Git/mingw64/bin/git.exe", "Git/bin/bash.exe"),  # git.exe from mingw64\bin
            ("Git/mingw64/bin/git.exe", "Git/usr/bin/bash.exe"),
        ],
    )
    def test_git_derived_layouts(self, monkeypatch, tmp_path, git_rel, bash_rel):
        """bash.exe is found relative to git.exe across real Git for Windows layouts."""
        git_exe = tmp_path / git_rel
        git_bash = tmp_path / bash_rel
        for f in (git_exe, git_bash):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.touch()
        monkeypatch.setattr(shell_module.shutil, "which", lambda cmd: str(git_exe) if cmd == "git" else None)
        assert _resolve_windows_bash() == str(git_bash)

    def test_git_without_bash_returns_none(self, monkeypatch, tmp_path):
        git_exe = tmp_path / "Git" / "cmd" / "git.exe"
        git_exe.parent.mkdir(parents=True)
        git_exe.touch()
        monkeypatch.setattr(shell_module.shutil, "which", lambda cmd: str(git_exe) if cmd == "git" else None)
        assert _resolve_windows_bash() is None

    def test_default_install_location_probed_last(self, monkeypatch, tmp_path):
        default_bash = tmp_path / "Git" / "bin" / "bash.exe"
        default_bash.parent.mkdir(parents=True)
        default_bash.touch()
        monkeypatch.setattr(shell_module, "_GIT_BASH_DEFAULT_PATHS", (str(default_bash),))
        assert _resolve_windows_bash() == str(default_bash)

    def test_nothing_found_returns_none(self):
        assert _resolve_windows_bash() is None


def _make_node(**params) -> ShellNode:
    node = ShellNode()
    node.set_params({"command": "echo hello", **params})
    return node


class TestWindowsExecArgv:
    """On win32 the command must run as ["bash", "-c", cmd] — list form, no shell=True."""

    def test_command_runs_through_bash(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(shell_module, "_resolve_windows_bash", lambda: r"C:\Git\bin\bash.exe")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"hello\n", stderr=b"")

        with patch.object(shell_module.subprocess, "run", return_value=completed) as mock_run:
            shared: dict = {}
            action = _make_node().run(shared)

        assert action == "default"
        assert shared["stdout"] == "hello"
        argv = mock_run.call_args.args[0]
        assert argv == [r"C:\Git\bin\bash.exe", "-c", "echo hello"]
        assert mock_run.call_args.kwargs.get("shell") is not True

    def test_posix_path_unchanged(self):
        """On non-win32 the command still goes through shell=True as a string."""
        completed = subprocess.CompletedProcess(args="", returncode=0, stdout=b"hello\n", stderr=b"")
        with patch.object(shell_module.subprocess, "run", return_value=completed) as mock_run:
            _make_node().run({})
        assert mock_run.call_args.args[0] == "echo hello"
        assert mock_run.call_args.kwargs.get("shell") is True


class TestMissingBashRaisesFromPrep:
    """The silent-success regression guard: missing bash must raise, always."""

    @pytest.fixture(autouse=True)
    def _win32_without_bash(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(shell_module, "_resolve_windows_bash", lambda: None)

    def test_prep_raises_user_friendly_error(self):
        with pytest.raises(UserFriendlyError) as exc_info:
            _make_node().prep({})
        # Agent-facing wording: authoring-surface guidance only — install link
        # and the env-var escape hatch, never runtime internals.
        assert "gitforwindows.org" in " ".join(exc_info.value.suggestions)
        assert "PFLOW_BASH" in " ".join(exc_info.value.suggestions)

    def test_error_surfaces_even_with_ignore_errors(self):
        """THE regression test the prep-raise design exists for: under
        ignore_errors: true an exec()-raise would be swallowed by
        exec_fallback into {exit_code: -2} and post() would return success —
        a silent green run. From prep() the raise must still propagate."""
        node = _make_node(ignore_errors=True)
        with pytest.raises(UserFriendlyError):
            node.run({})

    def test_no_subprocess_is_ever_spawned(self):
        """prep() failing means exec() never runs — nothing must hit cmd.exe."""
        with patch.object(shell_module.subprocess, "run") as mock_run, pytest.raises(UserFriendlyError):
            _make_node().run({})
        mock_run.assert_not_called()

    def test_full_pipeline_fails_loudly_with_ignore_errors(self):
        """End-to-end through the REAL engine (tests/CLAUDE.md pitfall #20):
        the node-level tests above prove prep() raises, but the silent-success
        trap lives in the engine/runner machinery around it — this pins that a
        workflow run with a missing bash and ignore_errors: true comes back
        FAILED with the install guidance in the diagnostics, not a green run
        with empty stdout."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step",
                    "type": "shell",
                    "params": {"command": "echo hello", "ignore_errors": True},
                }
            ],
            "edges": [],
            "start_node": "step",
        }

        result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

        assert not result.success, "missing bash under ignore_errors must NOT be a green run"
        rendered = " ".join(
            f"{d.title or ''} {d.message or ''} {' '.join(d.suggestions or [])}" for d in result.diagnostics
        )
        assert "gitforwindows.org" in rendered, f"install guidance lost in the pipeline: {rendered!r}"
        assert "PFLOW_BASH" in rendered
        # The step never executed — no success artifacts may leak into shared
        assert result.shared_after.get("exit_code") != 0


# Resolved at import, BEFORE any test patches sys.platform: shutil.which has
# its own `sys.platform == "win32"` branch (PATHEXT probing) that would return
# None for extensionless /usr/bin/bash once the fake platform is in place.
_REAL_BASH = shutil.which("bash")


@pytest.mark.skipif(_REAL_BASH is None, reason="needs a real bash to exercise the win32 exec branch")
class TestWindowsExecRealBash:
    """Run the win32 exec branch against a REAL bash (available on Linux/macOS).

    The argv-shape test above mocks subprocess.run, so it can't catch a broken
    kwarg in the win32 call (e.g. dropped stdin piping or capture). On Windows
    CI the whole shell suite exercises this branch; these two tests give the
    same signal on every Linux run, before any push.
    """

    @pytest.fixture(autouse=True)
    def _fake_win32_with_real_bash(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(shell_module, "_resolve_windows_bash", lambda: _REAL_BASH)

    def test_full_lifecycle_stdin_and_pipes(self):
        """stdin reaches the command, POSIX pipe syntax works inside -c."""
        node = ShellNode()
        node.set_params({"command": "tr a-z A-Z | rev", "stdin": "hello"})
        shared: dict = {}
        assert node.run(shared) == "default"
        assert shared["stdout"] == "OLLEH"
        assert shared["exit_code"] == 0

    def test_nonzero_exit_and_stderr_propagate(self):
        node = ShellNode()
        node.set_params({"command": "echo boom >&2; exit 3"})
        shared: dict = {}
        assert node.run(shared) == "error"
        assert shared["exit_code"] == 3
        assert "boom" in shared["stderr"]
