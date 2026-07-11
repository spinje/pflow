"""No-hang guarantee for a non-interactive side-effecting resume (Task 164, Decision 4).

Decision 4 promises: a side-effecting failed step, resumed in a non-interactive context,
raises an actionable error — **never a prompt or a hang**. Every other resume test drives
this through ``CliRunner``, which is ALWAYS non-TTY and feeds empty stdin — so it exercises
the refusal branch but *cannot distinguish a correct refusal from a real hang* (a broken
guard would still not block, because ``CliRunner`` never provides a live stdin to block on).

The hang is only observable against a real process whose stdin is an OPEN, idle, non-TTY
pipe — the exact shape an agent produces when it spawns ``pflow`` with a stdin pipe it holds
open but never writes to. ``resume._prompt_or_raise_side_effect`` calls ``click.confirm``
only when ``can_prompt`` (``stdin_tty and stderr_tty``) is true; if a future change drops or
inverts that guard, ``click.confirm`` blocks on the idle pipe until the timeout. This test
catches that regression as a timeout — the catastrophic-and-silent failure mode for agents.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe/subprocess test"),
]

_HINT_RE = re.compile(r"pflow resume (\S+)")

# step1 (shell) -> boom (shell, side-effecting K, fails unless mode=ok).
_WF = """# Resume No-Hang Demo

## Inputs

### mode

boom fails unless "ok".

- type: string
- required: true

## Steps

### step1

Upstream value.

- type: shell
- next: boom

```shell command
echo "upstream"
```

### boom

Side-effecting step that fails unless mode=ok.

- type: shell

```shell command
test "${mode}" = "ok" && echo "boom-ok"
```
"""


def _skip_if_uv_sandbox_panics(result: subprocess.CompletedProcess) -> None:
    """Skip when sandboxed uv panics before pflow starts (CI/dev sandbox quirk)."""
    if result.returncode == 101 and "Attempted to create a NULL object" in (result.stderr or ""):
        pytest.skip("uv subprocess panics in this sandbox before pflow starts")


def test_side_effecting_resume_non_tty_refuses_without_hanging(tmp_path, uv_exe, prepared_subprocess_env):
    env = dict(prepared_subprocess_env)
    env.pop("PYTEST_CURRENT_TEST", None)  # production-like logging (pitfall in subprocess_env docs)
    wf = tmp_path / "wf.pflow.md"
    wf.write_text(_WF, encoding="utf-8")

    # 1) Real failed run streams a trace and prints the resume target.
    fail = subprocess.run(  # noqa: S603
        [uv_exe, "run", "pflow", str(wf), "mode=bad"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    _skip_if_uv_sandbox_panics(fail)
    assert fail.returncode == 1, fail.stderr
    match = _HINT_RE.search(fail.stderr)
    assert match, f"failed run should print the resume hint; stderr:\n{fail.stderr}"
    exec_id = match.group(1)

    # 2) Resume with stdin = an OPEN, idle, non-TTY pipe (parent holds the write end open,
    #    never writes). A correct refusal exits fast; a dropped can_prompt guard blocks on
    #    click.confirm until the timeout — which surfaces here as TimeoutExpired.
    read_fd, write_fd = os.pipe()
    try:
        resume = subprocess.run(  # noqa: S603
            [uv_exe, "run", "pflow", "resume", exec_id, "mode=ok"],
            stdin=read_fd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            "resume HUNG on a non-interactive side-effecting step — "
            "the can_prompt guard in _prompt_or_raise_side_effect is broken"
        )
    finally:
        os.close(read_fd)
        os.close(write_fd)

    _skip_if_uv_sandbox_panics(resume)
    # Exited (not hung) with the actionable refusal — never a prompt.
    assert resume.returncode == 1, resume.stderr
    assert "--force" in resume.stderr
    assert "boom" in resume.stderr
